"""第三方登录与 Bearer 会话服务。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode, urlsplit
from uuid import uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import AuthCredential, AuthIdentity, AuthSession, User, utc_now
from app.schemas import AuthProvider

GOOGLE_AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USER_INFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
WECHAT_AUTHORIZATION_URL = "https://open.weixin.qq.com/connect/qrconnect"
WECHAT_TOKEN_URL = "https://api.weixin.qq.com/sns/oauth2/access_token"
WECHAT_USER_INFO_URL = "https://api.weixin.qq.com/sns/userinfo"
APPLE_AUTHORIZATION_URL = "https://appleid.apple.com/auth/authorize"
APPLE_TOKEN_URL = "https://appleid.apple.com/auth/token"
STATE_TTL_SECONDS = 10 * 60
PASSWORD_ITERATIONS = 600_000
DUMMY_PASSWORD_SALT = "0" * 32


class AuthProviderDisabledError(Exception):
    """请求的第三方登录提供方未配置。"""


class AuthStateError(Exception):
    """登录 state 缺失、过期或签名无效。"""


class AuthProviderError(Exception):
    """第三方登录交换或资料读取失败。"""


class EmailAlreadyRegisteredError(Exception):
    """邮箱已经被注册或绑定。"""


class InvalidEmailCredentialsError(Exception):
    """邮箱或密码不正确。"""


@dataclass(frozen=True, slots=True)
class ProviderProfile:
    """OAuth 提供方返回的最小身份信息。"""

    provider: AuthProvider
    provider_user_id: str
    display_name: str
    email: str | None = None
    email_verified: bool = False


@dataclass(frozen=True, slots=True)
class CreatedAuthSession:
    """新建登录会话的明文凭据和数据库记录。"""

    token: str
    session: AuthSession
    user: User


def provider_label(provider: AuthProvider) -> str:
    """返回登录入口展示名称。"""

    return {
        AuthProvider.GOOGLE: "使用 Google 登录",
        AuthProvider.WECHAT: "使用微信登录",
        AuthProvider.APPLE: "使用 Apple 登录",
    }[provider]


def provider_enabled(settings: Settings, provider: AuthProvider) -> bool:
    """判断提供方凭据是否配置完整。"""

    match provider:
        case AuthProvider.GOOGLE:
            return bool(settings.google_client_id and settings.google_client_secret)
        case AuthProvider.WECHAT:
            return bool(settings.wechat_app_id and settings.wechat_app_secret)
        case AuthProvider.APPLE:
            return bool(settings.apple_client_id and settings.apple_client_secret)


def resolve_post_login_uri(
    settings: Settings,
    requested_uri: str | None,
) -> str:
    """校验回调后的前端跳转地址，防止开放重定向。"""

    if not requested_uri:
        if not settings.cors_origins:
            raise AuthProviderError("未配置登录回跳地址")
        return settings.cors_origins[0]

    parsed = urlsplit(requested_uri)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    if requested_uri == settings.auth_mobile_redirect_uri:
        return requested_uri
    if parsed.scheme not in {"http", "https"} or origin not in settings.cors_origins:
        raise AuthProviderError("登录回跳地址不受信任")
    return requested_uri


def sign_state(
    settings: Settings,
    provider: AuthProvider,
    post_login_uri: str,
) -> str:
    """为 OAuth 回调生成带 HMAC 签名的 state。"""

    payload = {
        "provider": provider.value,
        "post_login_uri": post_login_uri,
        "expires_at": int(
            (utc_now() + timedelta(seconds=STATE_TTL_SECONDS)).timestamp(),
        ),
    }
    payload_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    payload_text = base64.urlsafe_b64encode(payload_bytes).rstrip(b"=").decode("ascii")
    signature = hmac.new(
        settings.auth_token_secret.encode("utf-8"),
        payload_text.encode("ascii"),
        hashlib.sha256,
    ).digest()
    signature_text = base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")
    return f"{payload_text}.{signature_text}"


def verify_state(settings: Settings, state: str) -> tuple[AuthProvider, str]:
    """验证 OAuth state 并返回提供方与回跳地址。"""

    if "." not in state:
        raise AuthStateError("登录 state 无效")
    payload_text, signature_text = state.split(".", 1)
    expected_signature = base64.urlsafe_b64encode(
        hmac.new(
            settings.auth_token_secret.encode("utf-8"),
            payload_text.encode("ascii"),
            hashlib.sha256,
        ).digest(),
    ).rstrip(b"=").decode("ascii")
    if not hmac.compare_digest(signature_text, expected_signature):
        raise AuthStateError("登录 state 无效")

    padding = "=" * (-len(payload_text) % 4)
    payload = json.loads(
        base64.urlsafe_b64decode(payload_text + padding).decode("utf-8"),
    )
    if int(payload["expires_at"]) <= int(utc_now().timestamp()):
        raise AuthStateError("登录 state 已过期")
    return AuthProvider(payload["provider"]), payload["post_login_uri"]


def build_authorization_url(
    settings: Settings,
    provider: AuthProvider,
    redirect_uri: str,
    state: str,
) -> str:
    """生成第三方登录授权地址。"""

    if not provider_enabled(settings, provider):
        raise AuthProviderDisabledError
    match provider:
        case AuthProvider.GOOGLE:
            query = urlencode(
                {
                    "client_id": settings.google_client_id,
                    "redirect_uri": redirect_uri,
                    "response_type": "code",
                    "scope": "openid email profile",
                    "state": state,
                    "prompt": "select_account",
                },
            )
            return f"{GOOGLE_AUTHORIZATION_URL}?{query}"
        case AuthProvider.WECHAT:
            query = urlencode(
                {
                    "appid": settings.wechat_app_id,
                    "redirect_uri": redirect_uri,
                    "response_type": "code",
                    "scope": "snsapi_login",
                    "state": state,
                },
            )
            return f"{WECHAT_AUTHORIZATION_URL}?{query}#wechat_redirect"
        case AuthProvider.APPLE:
            query = urlencode(
                {
                    "client_id": settings.apple_client_id,
                    "redirect_uri": redirect_uri,
                    "response_type": "code",
                    "scope": "name email",
                    "response_mode": "form_post",
                    "state": state,
                },
            )
            return f"{APPLE_AUTHORIZATION_URL}?{query}"


def _request_json(
    method: str,
    url: str,
    *,
    data: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
) -> dict[str, Any]:
    """请求第三方接口并统一校验 JSON 响应。"""

    try:
        response = httpx.request(
            method,
            url,
            data=data,
            params=params,
            timeout=10.0,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise AuthProviderError("第三方登录服务暂时不可用") from error
    if not isinstance(payload, dict):
        raise AuthProviderError("第三方登录返回数据格式无效")
    return payload


def _decode_jwt_payload(token: str) -> dict[str, Any]:
    """解析 Apple ID Token 的 JWT 载荷。"""

    try:
        payload_text = token.split(".", 3)[1]
        padding = "=" * (-len(payload_text) % 4)
        payload = json.loads(
            base64.urlsafe_b64decode(payload_text + padding).decode("utf-8"),
        )
    except (IndexError, ValueError, UnicodeDecodeError) as error:
        raise AuthProviderError("Apple 登录凭证无效") from error
    if not isinstance(payload, dict):
        raise AuthProviderError("Apple 登录凭证无效")
    return payload


def exchange_authorization_code(
    settings: Settings,
    provider: AuthProvider,
    code: str,
    redirect_uri: str,
    callback_user: dict[str, Any] | None = None,
) -> ProviderProfile:
    """用授权码交换第三方用户身份。"""

    if not provider_enabled(settings, provider):
        raise AuthProviderDisabledError
    match provider:
        case AuthProvider.GOOGLE:
            token_payload = _request_json(
                "POST",
                GOOGLE_TOKEN_URL,
                data={
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": redirect_uri,
                },
            )
            access_token = token_payload.get("access_token")
            if not isinstance(access_token, str):
                raise AuthProviderError("Google 未返回访问令牌")
            profile_payload = _request_json(
                "GET",
                GOOGLE_USER_INFO_URL,
                params={"access_token": access_token},
            )
            subject = profile_payload.get("sub")
            if not isinstance(subject, str) or not subject:
                raise AuthProviderError("Google 未返回用户标识")
            email = profile_payload.get("email")
            return ProviderProfile(
                provider=provider,
                provider_user_id=subject,
                display_name=(
                    profile_payload.get("name")
                    if isinstance(profile_payload.get("name"), str)
                    else "Google 用户"
                ),
                email=email.lower() if isinstance(email, str) else None,
                email_verified=profile_payload.get("email_verified") is True,
            )
        case AuthProvider.WECHAT:
            token_payload = _request_json(
                "GET",
                WECHAT_TOKEN_URL,
                params={
                    "appid": settings.wechat_app_id,
                    "secret": settings.wechat_app_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                },
            )
            if token_payload.get("errcode") is not None:
                raise AuthProviderError("微信授权码交换失败")
            access_token = token_payload.get("access_token")
            openid = token_payload.get("openid")
            if not isinstance(access_token, str) or not isinstance(openid, str):
                raise AuthProviderError("微信未返回访问令牌")
            profile_payload = _request_json(
                "GET",
                WECHAT_USER_INFO_URL,
                params={
                    "access_token": access_token,
                    "openid": openid,
                    "lang": "zh_CN",
                },
            )
            if profile_payload.get("errcode") is not None:
                raise AuthProviderError("微信用户资料读取失败")
            return ProviderProfile(
                provider=provider,
                provider_user_id=token_payload.get("unionid") or openid,
                display_name=(
                    profile_payload.get("nickname")
                    if isinstance(profile_payload.get("nickname"), str)
                    else "微信用户"
                ),
            )
        case AuthProvider.APPLE:
            token_payload = _request_json(
                "POST",
                APPLE_TOKEN_URL,
                data={
                    "client_id": settings.apple_client_id,
                    "client_secret": settings.apple_client_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": redirect_uri,
                },
            )
            id_token = token_payload.get("id_token")
            if not isinstance(id_token, str):
                raise AuthProviderError("Apple 未返回身份令牌")
            claims = _decode_jwt_payload(id_token)
            now = int(utc_now().timestamp())
            if (
                claims.get("iss") != "https://appleid.apple.com"
                or claims.get("aud") != settings.apple_client_id
                or int(claims.get("exp", 0)) <= now
                or not isinstance(claims.get("sub"), str)
            ):
                raise AuthProviderError("Apple 身份令牌校验失败")
            email = claims.get("email")
            callback_name = None
            if callback_user and isinstance(callback_user.get("name"), dict):
                name = callback_user["name"]
                callback_name = " ".join(
                    part
                    for part in (name.get("firstName"), name.get("lastName"))
                    if isinstance(part, str) and part
                )
            return ProviderProfile(
                provider=provider,
                provider_user_id=claims["sub"],
                display_name=callback_name or "Apple 用户",
                email=email.lower() if isinstance(email, str) else None,
                email_verified=claims.get("email_verified") in {True, "true"},
            )


def _normalized_expires_at(value: datetime) -> datetime:
    """把数据库可能返回的朴素时间统一为 UTC 时间。"""

    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _password_digest(
    password: str,
    salt: str,
    iterations: int,
) -> str:
    """使用 PBKDF2-SHA256 计算密码摘要。"""

    normalized_password = unicodedata.normalize("NFKC", password)
    return hashlib.pbkdf2_hmac(
        "sha256",
        normalized_password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    ).hex()


def register_with_password(
    session: Session,
    settings: Settings,
    email: str,
    password: str,
    display_name: str | None = None,
) -> CreatedAuthSession:
    """创建邮箱密码账号并签发登录会话。"""

    existing_credential = session.scalar(
        select(AuthCredential).where(AuthCredential.email == email),
    )
    existing_verified_user = session.scalar(select(User).where(User.email == email))
    if existing_credential is not None or existing_verified_user is not None:
        raise EmailAlreadyRegisteredError

    password_salt = secrets.token_bytes(16).hex()
    user = User(
        id=str(uuid4()),
        email=None,
        display_name=(display_name or email.rsplit("@", 1)[0])[:120],
    )
    credential = AuthCredential(
        id=str(uuid4()),
        user_id=user.id,
        email=email,
        password_hash=_password_digest(password, password_salt, PASSWORD_ITERATIONS),
        password_salt=password_salt,
        password_iterations=PASSWORD_ITERATIONS,
    )
    session.add(user)
    session.add(credential)
    session.commit()
    session.refresh(user)
    return _create_session(session, settings, user, "email")


def login_with_password(
    session: Session,
    settings: Settings,
    email: str,
    password: str,
) -> CreatedAuthSession:
    """校验邮箱密码并签发登录会话。"""

    credential = session.scalar(
        select(AuthCredential).where(AuthCredential.email == email),
    )
    if credential is None:
        # 对不存在账号也执行一次摘要计算，减少响应时间差异。
        _password_digest(password, DUMMY_PASSWORD_SALT, PASSWORD_ITERATIONS)
        raise InvalidEmailCredentialsError

    candidate_hash = _password_digest(
        password,
        credential.password_salt,
        credential.password_iterations,
    )
    if not hmac.compare_digest(candidate_hash, credential.password_hash):
        raise InvalidEmailCredentialsError
    user = session.get(User, credential.user_id)
    if user is None:
        raise InvalidEmailCredentialsError
    return _create_session(session, settings, user, "email")


def _create_session(
    session: Session,
    settings: Settings,
    user: User,
    provider: AuthProvider | str,
) -> CreatedAuthSession:
    """生成 opaque token 并只保存其哈希值。"""

    token = secrets.token_urlsafe(48)
    auth_session = AuthSession(
        id=str(uuid4()),
        user_id=user.id,
        token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
        provider=provider.value if isinstance(provider, AuthProvider) else provider,
        expires_at=utc_now() + timedelta(seconds=settings.auth_token_ttl_seconds),
    )
    session.add(auth_session)
    session.commit()
    session.refresh(auth_session)
    session.refresh(user)
    return CreatedAuthSession(token=token, session=auth_session, user=user)


def login_with_provider(
    session: Session,
    settings: Settings,
    profile: ProviderProfile,
) -> CreatedAuthSession:
    """根据第三方身份登录，必要时创建账号或绑定身份。"""

    identity = session.scalar(
        select(AuthIdentity).where(
            AuthIdentity.provider == profile.provider.value,
            AuthIdentity.provider_user_id == profile.provider_user_id,
        ),
    )
    user = session.get(User, identity.user_id) if identity else None
    if user is None and profile.email_verified and profile.email is not None:
        user = session.scalar(select(User).where(User.email == profile.email))

    if user is None:
        user = User(
            id=str(uuid4()),
            email=profile.email if profile.email_verified else None,
            display_name=profile.display_name[:120] or "MemoIsle 用户",
        )
        session.add(user)
        session.flush()

    if identity is None:
        identity = AuthIdentity(
            id=str(uuid4()),
            user_id=user.id,
            provider=profile.provider.value,
            provider_user_id=profile.provider_user_id,
            email=profile.email if profile.email_verified else None,
            display_name=profile.display_name[:120] or "MemoIsle 用户",
        )
        session.add(identity)
    else:
        identity.display_name = profile.display_name[:120] or identity.display_name
        identity.email = profile.email if profile.email_verified else identity.email
        if profile.email_verified and user.email is None:
            user.email = profile.email
    session.commit()
    session.refresh(user)
    return _create_session(session, settings, user, profile.provider)


def create_dev_session(session: Session, settings: Settings) -> CreatedAuthSession:
    """为显式开启的本地开发模式签发会话。"""

    user = session.get(User, settings.local_user_id)
    if user is None:
        user = User(
            id=settings.local_user_id,
            display_name="本地开发用户",
        )
        session.add(user)
        session.commit()
        session.refresh(user)
    return _create_session(session, settings, user, "dev")


def get_user_by_token(session: Session, token: str) -> User | None:
    """校验 Bearer 会话并返回用户。"""

    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    auth_session = session.scalar(
        select(AuthSession).where(AuthSession.token_hash == token_hash),
    )
    if auth_session is None:
        return None
    if (
        auth_session.revoked_at is not None
        or _normalized_expires_at(auth_session.expires_at) <= utc_now()
    ):
        return None
    return session.get(User, auth_session.user_id)


def revoke_session(session: Session, token: str) -> bool:
    """撤销当前 Bearer 会话。"""

    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    auth_session = session.scalar(
        select(AuthSession).where(AuthSession.token_hash == token_hash),
    )
    if auth_session is None or auth_session.revoked_at is not None:
        return False
    auth_session.revoked_at = utc_now()
    session.commit()
    return True
