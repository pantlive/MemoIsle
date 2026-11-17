"""密码库二次验证。

网页端要同时满足 IP 白名单、登录会话、客户端令牌和浏览器指纹，授权 4 小时。
手机端不检查 IP，授权 24 小时。读数据不会延长窗口。库里不存明文 IP、验证码或 TOTP 密钥。

客户端类型来自请求头 X-MemoIsle-Client，缺省按网页处理。这个头可以伪造，
伪造成手机端就能绕过 IP 白名单；局限写在 docs/implementation-status.md。
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import ipaddress
import logging
import re
import secrets
import struct
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from urllib.parse import quote
from uuid import uuid4

from fastapi import HTTPException, Request, Response, status
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.cloud_account_service import (
    CloudCredentialRejectedError,
    decrypt_credential,
    encrypt_credential,
)
from app.config import Settings, parse_cidr_list
from app.email_service import send_vault_alert_email, send_vault_code_email
from app.models import (
    AuthSession,
    User,
    VaultAccessGrant,
    VaultChallenge,
    VaultSecuritySetting,
    utc_now,
)

logger = logging.getLogger(__name__)

ClientType = Literal["web", "mobile"]
VAULT_CLIENT_HEADER = "X-MemoIsle-Client"
VAULT_CLIENT_COOKIE = "memoisle_vault_client"
VAULT_CLIENT_TOKEN_HEADER = "X-MemoIsle-Vault-Client"
VAULT_CLIENT_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{32,128}$")
# 手机端不把 IP 放进匹配条件。仍写一个固定 HMAC 输入，避免列里出现空地址。
MOBILE_IP_PLACEHOLDER = "mobile-any-ip"
IP_HASH_PURPOSE = "vault-access-ip"
FINGERPRINT_PURPOSE = "vault-access-client"
TOKEN_HASH_PURPOSE = "vault-access-token"
CODE_HASH_PURPOSE = "vault-access-code"
TOTP_STEP_SECONDS = 30
TOTP_DIGITS = 6
TOTP_WINDOW = 1


class VaultAccessError(Exception):
    """密码库门禁拒绝或暂时不能完成验证。"""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


class VaultCodeRateLimitedError(VaultAccessError):
    """验证码发得太勤。"""

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "vault_code_rate_limited",
            "验证码发送过于频繁，请稍后重试",
        )
        self.retry_after_seconds = max(1, retry_after_seconds)


class VaultTotpLockedError(VaultAccessError):
    """动态码失败次数用尽，锁定期间正确的码也不接受。"""

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "vault_totp_locked",
            "动态码尝试次数过多，请稍后再试",
        )
        self.retry_after_seconds = max(1, retry_after_seconds)


@dataclass(frozen=True)
class AuthContext:
    """当前请求对应的用户和登录会话。开发模式没有 Bearer 时会话为空。"""

    user_id: str
    session_id: str | None


@dataclass(frozen=True)
class IssuedAccess:
    """一次验证通过后的结果。网页令牌只放 Cookie，不放进响应体。"""

    granted: bool
    expires_at: datetime | None
    totp_enabled: bool
    hours: int
    client_type: ClientType
    client_token: str | None = None


def http_error(error: VaultAccessError) -> HTTPException:
    """把门禁错误转成带 code 的 4xx，前端靠 code 区分白名单和二次验证。"""

    headers = None
    if isinstance(error, (VaultCodeRateLimitedError, VaultTotpLockedError)):
        headers = {"Retry-After": str(error.retry_after_seconds)}
    return HTTPException(
        status_code=error.status_code,
        detail={"message": error.message, "code": error.code},
        headers=headers,
    )


def _as_utc(value: datetime) -> datetime:
    """SQLite 取回的时间可能没有时区，按 UTC 比较。"""

    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def _hmac(settings: Settings, purpose: str, value: str) -> str:
    """用登录密钥做 HMAC，数据库泄漏后也不能反推出 IP、验证码或令牌。"""

    return hmac.new(
        settings.auth_token_secret.encode("utf-8"),
        f"{purpose}\n{value}".encode(),
        hashlib.sha256,
    ).hexdigest()


def _normalize_ip(value: str) -> str:
    text = value.strip().strip("[]")
    if "%" in text:
        text = text.split("%", 1)[0]
    return text


def _parse_ip(
    value: str | None,
) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    if not value:
        return None
    try:
        return ipaddress.ip_address(_normalize_ip(value))
    except ValueError:
        return None


def trusted_proxy_networks(
    settings: Settings,
) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """解析可信反向代理。配置阶段已经校验过，这里再挡一次手工改坏的值。"""

    try:
        rendered = parse_cidr_list(settings.trusted_proxy_ips, "TRUSTED_PROXY_IPS")
    except ValueError:
        return []
    return [ipaddress.ip_network(item, strict=False) for item in rendered]


def peer_is_trusted(peer: str | None, settings: Settings) -> bool:
    """直连地址必须落在可信代理名单里，才采信它带来的 X-Forwarded-For。"""

    address = _parse_ip(peer)
    if address is None:
        return False
    return any(address in network for network in trusted_proxy_networks(settings))


def client_ip(request: Request) -> str | None:
    """解析客户端 IP。不可解析时返回空，调用方一律当成不允许。"""

    settings = _settings(request)
    peer = request.client.host if request.client is not None else None
    if peer_is_trusted(peer, settings):
        forwarded = request.headers.get("x-forwarded-for", "")
        for part in forwarded.split(","):
            address = _parse_ip(part)
            if address is not None:
                return str(address)
        return None
    address = _parse_ip(peer)
    if address is None:
        return None
    return str(address)


def client_ip_hash(settings: Settings, ip: str | None, client_type: ClientType) -> str:
    """网页保存真实 IP 的 HMAC。手机端不参与匹配，写入固定占位。"""

    material = ip if client_type == "web" and ip else MOBILE_IP_PLACEHOLDER
    return _hmac(settings, IP_HASH_PURPOSE, material)


def client_type(request: Request) -> ClientType:
    """缺省按网页处理。手机端要自己带 X-MemoIsle-Client: mobile。"""

    value = request.headers.get(VAULT_CLIENT_HEADER, "").strip().lower()
    if value == "mobile":
        return "mobile"
    return "web"


def read_client_token(request: Request) -> str | None:
    """先读手机请求头，再读网页 HttpOnly Cookie。格式不对就当成没有令牌。"""

    for candidate in (
        request.headers.get(VAULT_CLIENT_TOKEN_HEADER),
        request.cookies.get(VAULT_CLIENT_COOKIE),
    ):
        if not candidate:
            continue
        token = candidate.strip()
        if VAULT_CLIENT_TOKEN_PATTERN.fullmatch(token):
            return token
    return None


def client_fingerprint_hash(settings: Settings, token: str, user_agent: str) -> str:
    """令牌加 User-Agent 的 HMAC。换浏览器或换 UA 都对不上。"""

    return _hmac(
        settings,
        FINGERPRINT_PURPOSE,
        f"{token}\n{user_agent.strip()[:512]}",
    )


def user_agent_of(request: Request) -> str:
    return request.headers.get("user-agent", "").strip()[:512]


def allowlist_networks(
    raw_items: list[str],
) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """把 CIDR 文本收成网络。解析失败的条目直接丢掉，不让一次坏数据把接口打崩。"""

    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    seen: set[ipaddress.IPv4Network | ipaddress.IPv6Network] = set()
    for item in raw_items:
        text = item.strip()
        if not text:
            continue
        try:
            network = ipaddress.ip_network(text, strict=False)
        except ValueError:
            continue
        if network in seen:
            continue
        seen.add(network)
        networks.append(network)
    return networks


def env_allowlist(settings: Settings) -> list[str]:
    """环境变量白名单。启动时已校验；测试里手工写坏时忽略坏条目。"""

    try:
        return list(
            parse_cidr_list(
                settings.vault_web_ip_allowlist,
                "VAULT_WEB_IP_ALLOWLIST",
            )
        )
    except ValueError:
        return []


def user_allowlist(session: Session, user_id: str) -> list[str]:
    setting = session.get(VaultSecuritySetting, user_id)
    if setting is None or not setting.ip_allowlist:
        return []
    return [str(network) for network in allowlist_networks(list(setting.ip_allowlist))]


def effective_allowlist(settings: Settings, user_entries: list[str]) -> list[str]:
    """环境变量兜底，再并上设置页追加的条目。环境变量里的条目删不掉。"""

    merged = allowlist_networks([*env_allowlist(settings), *user_entries])
    return [str(network) for network in merged]


def ip_allowed(ip: str | None, networks: list[str]) -> bool:
    """IP 解析失败一律不允许。名单用 CIDR 匹配。"""

    address = _parse_ip(ip)
    if address is None:
        return False
    for network in allowlist_networks(networks):
        if address in network:
            return True
    return False


def enforce_web_ip(request: Request, session: Session, user_id: str) -> None:
    """网页端检查白名单。手机端直接返回。"""

    if client_type(request) == "mobile":
        return
    _enforce_ip(request, session, user_id)


def enforce_mutation_ip(request: Request, session: Session, user_id: str) -> None:
    """改白名单时，手机端也必须从当前允许的 IP 进来。"""

    _enforce_ip(request, session, user_id)


def _enforce_ip(request: Request, session: Session, user_id: str) -> None:
    networks = effective_allowlist(
        _settings(request),
        user_allowlist(session, user_id),
    )
    if not networks:
        raise VaultAccessError(
            status.HTTP_403_FORBIDDEN,
            "vault_ip_allowlist_empty",
            "还没有配置网页密码库的 IP 白名单",
        )
    if not ip_allowed(client_ip(request), networks):
        raise VaultAccessError(
            status.HTTP_403_FORBIDDEN,
            "vault_ip_blocked",
            "当前网络不在密码库白名单中",
        )


def resolve_auth(request: Request, session: Session) -> AuthContext:
    """识别当前用户和登录会话。退出登录后的令牌在这里就被拒绝。"""

    settings = _settings(request)
    authorization = request.headers.get("authorization")
    if authorization:
        scheme, separator, token = authorization.partition(" ")
        if not separator or scheme.lower() != "bearer" or not token.strip():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="登录凭证格式无效",
                headers={"WWW-Authenticate": "Bearer"},
            )
        token_hash = hashlib.sha256(token.strip().encode("utf-8")).hexdigest()
        auth_session = session.scalar(
            select(AuthSession).where(AuthSession.token_hash == token_hash),
        )
        if auth_session is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="登录已过期，请重新登录",
                headers={"WWW-Authenticate": "Bearer"},
            )
        expires_at = _as_utc(auth_session.expires_at)
        revoked_at = auth_session.revoked_at
        if revoked_at is not None or expires_at <= utc_now():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="登录已过期，请重新登录",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return AuthContext(user_id=auth_session.user_id, session_id=auth_session.id)
    if settings.auth_dev_mode:
        return AuthContext(user_id=settings.local_user_id, session_id=None)
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="请先登录",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _session_still_live(
    session: Session,
    auth: AuthContext,
    settings: Settings,
) -> bool:
    """开发模式的空会话只在开发开关开着时有效。正式会话被撤销后授权作废。"""

    if auth.session_id is None:
        return settings.auth_dev_mode
    auth_session = session.get(AuthSession, auth.session_id)
    if auth_session is None or auth_session.user_id != auth.user_id:
        return False
    if auth_session.revoked_at is not None:
        return False
    return _as_utc(auth_session.expires_at) > utc_now()


def grant_hours(settings: Settings, kind: ClientType) -> int:
    if kind == "mobile":
        return settings.vault_mobile_grant_hours
    return settings.vault_web_grant_hours


def active_grant(
    session: Session,
    settings: Settings,
    auth: AuthContext,
    *,
    kind: ClientType,
    ip: str | None,
    token: str | None,
    user_agent: str,
) -> VaultAccessGrant | None:
    """返回仍绑定当前会话、令牌和浏览器的授权。网页还要 IP 一致。"""

    if token is None or not _session_still_live(session, auth, settings):
        return None
    now = utc_now()
    statement = select(VaultAccessGrant).where(
        VaultAccessGrant.user_id == auth.user_id,
        VaultAccessGrant.client_type == kind,
        VaultAccessGrant.token_hash == _hmac(settings, TOKEN_HASH_PURPOSE, token),
        VaultAccessGrant.fingerprint_hash
        == client_fingerprint_hash(settings, token, user_agent),
        VaultAccessGrant.expires_at > now,
    )
    if auth.session_id is None:
        statement = statement.where(VaultAccessGrant.auth_session_id.is_(None))
    else:
        statement = statement.where(VaultAccessGrant.auth_session_id == auth.session_id)
    if kind == "web":
        statement = statement.where(
            VaultAccessGrant.ip_hash == client_ip_hash(settings, ip, "web"),
        )
    grant = session.scalar(statement)
    if grant is None:
        return None
    if _as_utc(grant.expires_at) <= now:
        return None
    return grant


def security_setting(session: Session, user_id: str) -> VaultSecuritySetting | None:
    return session.get(VaultSecuritySetting, user_id)


def totp_enabled(session: Session, user_id: str) -> bool:
    setting = security_setting(session, user_id)
    return bool(setting and setting.totp_enabled and setting.totp_secret_cipher)


def describe_access(
    session: Session,
    settings: Settings,
    auth: AuthContext,
    request: Request,
) -> IssuedAccess:
    """只报告当前状态，不签发授权，也不延长已有窗口。"""

    kind = client_type(request)
    grant = active_grant(
        session,
        settings,
        auth,
        kind=kind,
        ip=client_ip(request),
        token=read_client_token(request),
        user_agent=user_agent_of(request),
    )
    expires_at = _as_utc(grant.expires_at) if grant is not None else None
    return IssuedAccess(
        granted=grant is not None,
        expires_at=expires_at,
        totp_enabled=totp_enabled(session, auth.user_id),
        hours=grant_hours(settings, kind),
        client_type=kind,
    )


def issue_grant(
    session: Session,
    settings: Settings,
    *,
    user_id: str,
    auth_session_id: str | None,
    kind: ClientType,
    ip: str | None,
    user_agent: str,
    token: str,
    hours: int,
) -> VaultAccessGrant:
    """签发或续期授权。过期时间从现在起算，不会因为之后的读取再往后推。"""

    now = utc_now()
    session.execute(
        delete(VaultAccessGrant).where(
            VaultAccessGrant.user_id == user_id,
            VaultAccessGrant.expires_at <= now,
        ),
    )
    token_hash = _hmac(settings, TOKEN_HASH_PURPOSE, token)
    fingerprint = client_fingerprint_hash(settings, token, user_agent)
    ip_hash = client_ip_hash(settings, ip, kind)
    statement = select(VaultAccessGrant).where(
        VaultAccessGrant.user_id == user_id,
        VaultAccessGrant.client_type == kind,
        VaultAccessGrant.token_hash == token_hash,
        VaultAccessGrant.fingerprint_hash == fingerprint,
    )
    if auth_session_id is None:
        statement = statement.where(VaultAccessGrant.auth_session_id.is_(None))
    else:
        statement = statement.where(VaultAccessGrant.auth_session_id == auth_session_id)
    if kind == "web":
        statement = statement.where(VaultAccessGrant.ip_hash == ip_hash)
    grant = session.scalar(statement)
    expires_at = now + timedelta(hours=hours)
    if grant is None:
        grant = VaultAccessGrant(
            id=str(uuid4()),
            user_id=user_id,
            auth_session_id=auth_session_id,
            client_type=kind,
            ip_hash=ip_hash,
            fingerprint_hash=fingerprint,
            token_hash=token_hash,
            expires_at=expires_at,
            created_at=now,
        )
        session.add(grant)
    else:
        grant.expires_at = expires_at
        grant.ip_hash = ip_hash
    session.flush()
    return grant


def set_client_cookie(response: Response, request: Request, token: str) -> None:
    """网页把客户端令牌放进 HttpOnly Cookie，脚本读不到。"""

    response.set_cookie(
        key=VAULT_CLIENT_COOKIE,
        value=token,
        max_age=400 * 24 * 3600,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        path="/api/v1/vault",
    )


def _require_user(session: Session, user_id: str) -> User:
    user = session.get(User, user_id)
    if user is None or not (user.email or "").strip():
        raise VaultAccessError(
            status.HTTP_400_BAD_REQUEST,
            "vault_email_missing",
            "账号没有邮箱，无法发送密码库验证邮件",
        )
    return user


def _prepare_challenge(session: Session, settings: Settings, user_id: str) -> str:
    """签发六位验证码。沿用注册验证码的间隔、有效期和尝试次数，但不检查邮箱是否已注册。"""

    now = utc_now()
    session.execute(
        update(VaultChallenge)
        .where(VaultChallenge.user_id == user_id)
        .values(user_id=user_id),
    )
    session.flush()
    latest = session.scalar(
        select(VaultChallenge)
        .where(VaultChallenge.user_id == user_id)
        .order_by(VaultChallenge.sent_at.desc()),
    )
    if latest is not None:
        resend_at = _as_utc(latest.sent_at) + timedelta(
            seconds=settings.auth_verification_code_resend_seconds,
        )
        if resend_at > now:
            raise VaultCodeRateLimitedError(int((resend_at - now).total_seconds()))
    session.execute(
        update(VaultChallenge)
        .where(
            VaultChallenge.user_id == user_id,
            VaultChallenge.consumed_at.is_(None),
        )
        .values(consumed_at=now),
    )
    code = f"{secrets.randbelow(1_000_000):06d}"
    session.add(
        VaultChallenge(
            id=str(uuid4()),
            user_id=user_id,
            code_hash=_hmac(settings, CODE_HASH_PURPOSE, f"{user_id}:{code}"),
            sent_at=now,
            expires_at=now
            + timedelta(minutes=settings.auth_verification_code_expire_minutes),
            attempt_count=0,
        ),
    )
    try:
        session.flush()
    except IntegrityError as error:
        raise VaultCodeRateLimitedError(
            settings.auth_verification_code_resend_seconds,
        ) from error
    return code


def send_access_code(request: Request, session: Session, auth: AuthContext) -> str:
    """把验证码发到账号邮箱。邮件写明客户端和授权时长，不写密钥。"""

    settings = _settings(request)
    kind = client_type(request)
    if kind == "web":
        enforce_web_ip(request, session, auth.user_id)
    user = _require_user(session, auth.user_id)
    code = _prepare_challenge(session, settings, auth.user_id)
    hours = grant_hours(settings, kind)
    try:
        send_vault_code_email(
            settings,
            user.email or "",
            code,
            client_type=kind,
            user_agent=user_agent_of(request)[:200],
            hours=hours,
        )
    except Exception:
        session.rollback()
        raise
    session.commit()
    return user.email or ""


def _load_open_challenge(session: Session, user_id: str) -> VaultChallenge | None:
    return session.scalar(
        select(VaultChallenge)
        .where(
            VaultChallenge.user_id == user_id,
            VaultChallenge.consumed_at.is_(None),
        )
        .order_by(VaultChallenge.sent_at.desc()),
    )


def _consume_email_code(
    session: Session,
    settings: Settings,
    user_id: str,
    code: str,
) -> bool:
    """校验并消费验证码。失败时增加尝试次数，成功时标记已使用。"""

    challenge = _load_open_challenge(session, user_id)
    now = utc_now()
    if (
        challenge is None
        or _as_utc(challenge.expires_at) <= now
        or challenge.attempt_count >= settings.auth_verification_code_max_attempts
    ):
        return False
    expected = _hmac(settings, CODE_HASH_PURPOSE, f"{user_id}:{code.strip()}")
    if not hmac.compare_digest(challenge.code_hash, expected):
        challenge.attempt_count += 1
        if challenge.attempt_count >= settings.auth_verification_code_max_attempts:
            challenge.consumed_at = now
        session.commit()
        return False
    result = session.execute(
        update(VaultChallenge)
        .where(
            VaultChallenge.id == challenge.id,
            VaultChallenge.consumed_at.is_(None),
            VaultChallenge.attempt_count < settings.auth_verification_code_max_attempts,
        )
        .values(consumed_at=now),
    )
    if int(result.rowcount or 0) != 1:
        session.rollback()
        return False
    return True


def _verification_window(settings: Settings) -> timedelta:
    """动态码锁定和报警节流共用邮箱验证码的有效期。"""

    return timedelta(minutes=settings.auth_verification_code_expire_minutes)


def _retry_after_seconds(
    started_at: datetime,
    settings: Settings,
    now: datetime,
) -> int:
    remaining = _verification_window(settings) - (now - _as_utc(started_at))
    return max(1, int(remaining.total_seconds()))


def _reset_expired_totp_failures(
    setting: VaultSecuritySetting,
    settings: Settings,
    now: datetime,
) -> None:
    started_at = setting.totp_failure_window_started_at
    if started_at is None:
        return
    if now - _as_utc(started_at) >= _verification_window(settings):
        setting.totp_failure_count = 0
        setting.totp_failure_window_started_at = None


def _totp_is_locked(setting: VaultSecuritySetting, settings: Settings) -> bool:
    return (
        setting.totp_failure_window_started_at is not None
        and setting.totp_failure_count >= settings.auth_verification_code_max_attempts
    )


def _notify_alert(
    request: Request,
    session: Session,
    user: User,
    reason: str,
    *,
    raise_on_delivery_error: bool,
) -> bool:
    """同一用户在验证码有效期内只发一封报警，其余次数留到下一封汇总。

    发送失败也会占住这个窗口，避免穷举时反复打 SMTP。
    调用前对同一会话做的失败计数会一起提交。
    """

    setting = _ensure_setting(session, user.id)
    now = utc_now()
    app_settings = _settings(request)
    sent_at = setting.alert_sent_at
    if (
        sent_at is not None
        and now - _as_utc(sent_at) < _verification_window(app_settings)
    ):
        setting.alert_suppressed_count += 1
        session.commit()
        return False
    suppressed = setting.alert_suppressed_count
    try:
        send_vault_alert_email(
            app_settings,
            user.email or "",
            occurred_at=now,
            client_ip=client_ip(request),
            client_type=client_type(request),
            user_agent=user_agent_of(request)[:200],
            reason=reason,
            suppressed_count=suppressed,
        )
    except Exception:
        logger.exception("密码库报警邮件发送失败")
        setting.alert_sent_at = now
        session.commit()
        if raise_on_delivery_error:
            raise
        return False
    setting.alert_sent_at = now
    setting.alert_suppressed_count = 0
    session.commit()
    return True


def _alert(
    request: Request,
    session: Session,
    user: User | None,
    reason: str,
) -> None:
    """报警邮件只写时间、IP、客户端和浏览器。没有邮箱或发信失败时不挡住原错误。"""

    if user is None or not (user.email or "").strip():
        session.commit()
        return
    _notify_alert(
        request,
        session,
        user,
        reason,
        raise_on_delivery_error=False,
    )


def verify_access(
    request: Request,
    session: Session,
    auth: AuthContext,
    *,
    method: Literal["email", "totp"],
    code: str,
) -> tuple[IssuedAccess, str]:
    """用一次性邮箱验证码或已绑定的动态码换取授权。

    返回授权状态，以及要写入 Cookie 或交给手机保存的客户端令牌。
    """

    settings = _settings(request)
    kind = client_type(request)
    if kind == "web":
        enforce_web_ip(request, session, auth.user_id)
        if client_ip(request) is None:
            raise VaultAccessError(
                status.HTTP_400_BAD_REQUEST,
                "vault_ip_blocked",
                "无法识别客户端地址，请稍后重试",
            )
    user = session.get(User, auth.user_id)
    if method == "totp":
        if not totp_enabled(session, auth.user_id):
            raise VaultAccessError(
                status.HTTP_400_BAD_REQUEST,
                "vault_totp_unavailable",
                "还没有绑定身份验证器",
            )
        setting = _ensure_setting(session, auth.user_id)
        now = utc_now()
        _reset_expired_totp_failures(setting, settings, now)
        if _totp_is_locked(setting, settings):
            started_at = setting.totp_failure_window_started_at
            if started_at is None:
                started_at = now
            raise VaultTotpLockedError(
                _retry_after_seconds(started_at, settings, now),
            )
        if not _totp_matches(session, settings, auth.user_id, code):
            if setting.totp_failure_window_started_at is None:
                setting.totp_failure_window_started_at = now
                setting.totp_failure_count = 1
            else:
                setting.totp_failure_count += 1
            locked = _totp_is_locked(setting, settings)
            _alert(request, session, user, "身份验证器动态码不正确")
            if locked:
                started_at = setting.totp_failure_window_started_at or now
                raise VaultTotpLockedError(
                    _retry_after_seconds(started_at, settings, now),
                )
            raise VaultAccessError(
                status.HTTP_403_FORBIDDEN,
                "vault_code_invalid",
                "动态码不正确",
            )
        setting.totp_failure_count = 0
        setting.totp_failure_window_started_at = None
    else:
        if not _consume_email_code(session, settings, auth.user_id, code):
            _alert(request, session, user, "邮箱验证码不正确或已失效")
            raise VaultAccessError(
                status.HTTP_403_FORBIDDEN,
                "vault_code_invalid",
                "验证码不正确或已失效",
            )
    token = read_client_token(request) or secrets.token_urlsafe(32)
    hours = grant_hours(settings, kind)
    grant = issue_grant(
        session,
        settings,
        user_id=auth.user_id,
        auth_session_id=auth.session_id,
        kind=kind,
        ip=client_ip(request),
        user_agent=user_agent_of(request),
        token=token,
        hours=hours,
    )
    session.commit()
    return IssuedAccess(
        granted=True,
        expires_at=_as_utc(grant.expires_at),
        totp_enabled=totp_enabled(session, auth.user_id),
        hours=hours,
        client_type=kind,
        client_token=token if kind == "mobile" else None,
    ), token


def record_unlock_failure(
    request: Request,
    session: Session,
    auth: AuthContext,
) -> bool:
    """主密码在客户端校验失败后上报。没有邮箱时不发信，也不报错。"""

    if client_type(request) == "web":
        enforce_web_ip(request, session, auth.user_id)
    user = session.get(User, auth.user_id)
    if user is None or not (user.email or "").strip():
        return False
    return _notify_alert(
        request,
        session,
        user,
        "主密码不正确",
        raise_on_delivery_error=True,
    )


def _ensure_setting(session: Session, user_id: str) -> VaultSecuritySetting:
    setting = session.get(VaultSecuritySetting, user_id)
    if setting is None:
        setting = VaultSecuritySetting(
            user_id=user_id,
            totp_secret_cipher=None,
            totp_enabled=False,
            ip_allowlist=[],
            totp_failure_count=0,
            totp_failure_window_started_at=None,
            alert_sent_at=None,
            alert_suppressed_count=0,
        )
        session.add(setting)
        session.flush()
    return setting


def normalize_user_allowlist(entries: list[str], env_entries: list[str]) -> list[str]:
    """校验用户追加的 CIDR，并去掉已经在环境变量里的条目。"""

    env_networks = set(allowlist_networks(env_entries))
    normalized: list[str] = []
    seen: set[ipaddress.IPv4Network | ipaddress.IPv6Network] = set()
    for entry in entries:
        text = entry.strip()
        if not text:
            continue
        try:
            network = ipaddress.ip_network(text, strict=False)
        except ValueError as error:
            raise VaultAccessError(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "vault_allowlist_invalid",
                f"IP 白名单格式无效：{text}",
            ) from error
        if network in env_networks or network in seen:
            continue
        seen.add(network)
        normalized.append(str(network))
    if len(normalized) > 32:
        raise VaultAccessError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "vault_allowlist_invalid",
            "追加的 IP 白名单最多 32 条",
        )
    return normalized


def update_user_allowlist(
    request: Request,
    session: Session,
    auth: AuthContext,
    entries: list[str],
) -> tuple[list[str], list[str]]:
    """只替换用户追加的名单。调用方必须已经确认当前 IP 被允许，且授权有效。"""

    settings = _settings(request)
    env_entries = env_allowlist(settings)
    normalized = normalize_user_allowlist(entries, env_entries)
    setting = _ensure_setting(session, auth.user_id)
    setting.ip_allowlist = normalized
    session.commit()
    return env_entries, normalized


def generate_totp_secret() -> str:
    """生成 160 位随机密钥，Base32 不带填充，方便手输。"""

    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _totp_key(secret: str) -> bytes:
    padded = secret.strip().upper() + "=" * ((8 - len(secret.strip()) % 8) % 8)
    try:
        key = base64.b32decode(padded, casefold=True)
    except (ValueError, binascii.Error) as error:
        raise VaultAccessError(
            status.HTTP_400_BAD_REQUEST,
            "vault_totp_unavailable",
            "身份验证器密钥无效，请重新绑定",
        ) from error
    if not key:
        raise VaultAccessError(
            status.HTTP_400_BAD_REQUEST,
            "vault_totp_unavailable",
            "身份验证器密钥无效，请重新绑定",
        )
    return key


def totp_at(secret: str, counter: int) -> str:
    """RFC 6238：HMAC-SHA1，30 秒一步，6 位数字。"""

    digest = hmac.new(
        _totp_key(secret),
        struct.pack(">Q", counter),
        hashlib.sha1,
    ).digest()
    offset = digest[-1] & 0x0F
    binary = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{binary % 10**TOTP_DIGITS:0{TOTP_DIGITS}d}"


def verify_totp(secret: str, code: str, now: float | None = None) -> bool:
    """允许前后各一个时间窗，抵消手机和服务器的少量时差。"""

    candidate = code.strip().replace(" ", "")
    if not re.fullmatch(r"\d{6}", candidate):
        return False
    moment = time.time() if now is None else now
    counter = int(moment // TOTP_STEP_SECONDS)
    for delta in range(-TOTP_WINDOW, TOTP_WINDOW + 1):
        if hmac.compare_digest(totp_at(secret, counter + delta), candidate):
            return True
    return False


def _current_totp_secret(
    session: Session,
    settings: Settings,
    user_id: str,
) -> str | None:
    setting = security_setting(session, user_id)
    if setting is None or not setting.totp_secret_cipher:
        return None
    try:
        return decrypt_credential(settings, setting.totp_secret_cipher)
    except CloudCredentialRejectedError:
        return None


def _totp_matches(
    session: Session,
    settings: Settings,
    user_id: str,
    code: str,
) -> bool:
    secret = _current_totp_secret(session, settings, user_id)
    if secret is None:
        return False
    return verify_totp(secret, code)


def begin_totp_setup(
    request: Request,
    session: Session,
    auth: AuthContext,
) -> tuple[str, str]:
    """生成密钥并加密保存，但要等确认动态码后才启用。"""

    settings = _settings(request)
    secret = generate_totp_secret()
    setting = _ensure_setting(session, auth.user_id)
    setting.totp_secret_cipher = encrypt_credential(settings, secret)
    setting.totp_enabled = False
    session.commit()
    user = session.get(User, auth.user_id)
    account = (user.email if user and user.email else "vault").strip()
    uri = (
        f"otpauth://totp/MemoIsle:{quote(account)}"
        f"?secret={secret}&issuer=MemoIsle&algorithm=SHA1&digits=6&period=30"
    )
    return secret, uri


def confirm_totp(
    request: Request,
    session: Session,
    auth: AuthContext,
    code: str,
) -> None:
    """用当前密钥算出的动态码确认绑定。确认前不能拿它换授权。"""

    settings = _settings(request)
    setting = security_setting(session, auth.user_id)
    if setting is None or not setting.totp_secret_cipher:
        raise VaultAccessError(
            status.HTTP_400_BAD_REQUEST,
            "vault_totp_unavailable",
            "请先生成身份验证器密钥",
        )
    if not _totp_matches(session, settings, auth.user_id, code):
        raise VaultAccessError(
            status.HTTP_403_FORBIDDEN,
            "vault_code_invalid",
            "动态码不正确，绑定尚未生效",
        )
    setting.totp_enabled = True
    session.commit()


def require_grant_user(request: Request, session: Session) -> str:
    """敏感接口：网页先过 IP，再要求未过期的授权。"""

    auth = resolve_auth(request, session)
    try:
        enforce_web_ip(request, session, auth.user_id)
    except VaultAccessError as error:
        raise http_error(error) from error
    settings = _settings(request)
    grant = active_grant(
        session,
        settings,
        auth,
        kind=client_type(request),
        ip=client_ip(request),
        token=read_client_token(request),
        user_agent=user_agent_of(request),
    )
    if grant is None:
        raise http_error(
            VaultAccessError(
                status.HTTP_403_FORBIDDEN,
                "vault_step_up_required",
                "需要先验证邮箱验证码或身份验证器动态码才能打开密码库",
            ),
        )
    return auth.user_id


def require_ip_user(request: Request, session: Session) -> AuthContext:
    """状态接口只检查网页 IP，不发放授权。"""

    auth = resolve_auth(request, session)
    try:
        enforce_web_ip(request, session, auth.user_id)
    except VaultAccessError as error:
        raise http_error(error) from error
    return auth
