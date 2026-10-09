"""云盘账号绑定服务。

凭据只以密文落库，接口侧只暴露脱敏提示（如 ...a1b2）。
"""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

import httpx
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.cloud_drive import (
    SUPPORTED_PROVIDERS,
    CloudDriveError,
    CredentialInvalidError,
    UnsupportedProviderError,
    build_client,
)
from app.config import Settings
from app.models import CloudAccount

DEFAULT_EBOOK_FOLDER = "/MemoIsle/电子书"
MAX_CREDENTIAL_LENGTH = 8_000
MAX_FOLDER_LENGTH = 500


class CloudAccountNotFoundError(LookupError):
    """云盘绑定不存在或不属于当前用户。"""


class CloudAccountExistsError(ValueError):
    """同一用户已经绑定过该服务商。"""


class CloudCredentialRejectedError(ValueError):
    """服务商拒绝了该凭据。"""


def _resolve_secret(settings: Settings) -> str:
    """取云盘凭据加密密钥，未单独配置时回退到登录密钥。"""

    return settings.cloud_credential_secret or settings.auth_token_secret


def _fernet(settings: Settings) -> Fernet:
    secret = _resolve_secret(settings)
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
    return Fernet(key)


def encrypt_credential(settings: Settings, plaintext: str) -> str:
    """加密云盘凭据。"""

    return _fernet(settings).encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_credential(settings: Settings, cipher: str) -> str:
    """解密云盘凭据；密钥变更或密文损坏时提示重新绑定。"""

    try:
        return _fernet(settings).decrypt(cipher.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as error:
        raise CloudCredentialRejectedError(
            "云盘凭据无法解密（密钥已变更），请重新绑定",
        ) from error


def credential_hint(plaintext: str) -> str:
    """生成脱敏提示，只保留凭据末尾 4 个字符。

    JSON 粘贴时优先取 token 字段的值，避免提示变成 `34"}` 这类噪音。
    """

    cleaned = plaintext.strip()
    if not cleaned:
        return ""
    if cleaned.startswith("{"):
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            for key in ("refresh_token", "access_token", "token"):
                value = data.get(key)
                if isinstance(value, str) and value.strip():
                    cleaned = value.strip()
                    break
    return f"...{cleaned[-4:]}"


def normalize_provider(provider: str) -> str:
    """校验并归一化服务商标识。"""

    cleaned = (provider or "").strip().lower()
    if cleaned not in SUPPORTED_PROVIDERS:
        raise UnsupportedProviderError("云盘服务商必须是 aliyun 或 baidu")
    return cleaned


def normalize_folder(folder: str | None) -> str:
    """归一化转存目录，保证以 / 开头且长度受限。"""

    cleaned = (folder or "").strip() or DEFAULT_EBOOK_FOLDER
    if not cleaned.startswith("/"):
        cleaned = f"/{cleaned}"
    if len(cleaned) > MAX_FOLDER_LENGTH:
        raise ValueError("云盘目录过长")
    return cleaned


def build_cloud_client(
    provider: str,
    credential: str,
    *,
    settings: Settings,
    http_client: httpx.Client | None = None,
):
    """按服务商构建客户端。"""

    return build_client(
        normalize_provider(provider),
        credential,
        timeout=settings.resource_fetch_timeout_seconds,
        http_client=http_client,
    )


def verify_credential(
    provider: str,
    credential: str,
    *,
    settings: Settings,
    http_client: httpx.Client | None = None,
):
    """校验云盘凭据并返回账号信息。"""

    client = build_cloud_client(
        provider,
        credential,
        settings=settings,
        http_client=http_client,
    )
    try:
        return client.check_credential()
    except CredentialInvalidError as error:
        raise CloudCredentialRejectedError(str(error)) from error
    except CloudDriveError as error:
        raise CloudCredentialRejectedError(str(error)) from error


def list_cloud_accounts(session: Session, user_id: str) -> list[CloudAccount]:
    """列出当前用户已绑定的云盘账号。"""

    return list(
        session.scalars(
            select(CloudAccount)
            .where(CloudAccount.user_id == user_id)
            .order_by(CloudAccount.created_at.asc()),
        ).all(),
    )


def get_cloud_account(
    session: Session,
    user_id: str,
    account_id: str,
) -> CloudAccount:
    """读取单个云盘绑定。"""

    account = session.scalar(
        select(CloudAccount).where(
            CloudAccount.id == account_id,
            CloudAccount.user_id == user_id,
        ),
    )
    if account is None:
        raise CloudAccountNotFoundError("云盘绑定不存在")
    return account


def get_account_for_provider(
    session: Session,
    user_id: str,
    provider: str,
) -> CloudAccount | None:
    """按服务商读取云盘绑定。"""

    return session.scalar(
        select(CloudAccount).where(
            CloudAccount.user_id == user_id,
            CloudAccount.provider == normalize_provider(provider),
        ),
    )


def create_cloud_account(
    session: Session,
    user_id: str,
    *,
    provider: str,
    credential: str,
    settings: Settings,
    default_folder: str | None = None,
    http_client: httpx.Client | None = None,
) -> CloudAccount:
    """绑定云盘账号：先校验凭据，再加密落库。"""

    resolved_provider = normalize_provider(provider)
    plaintext = (credential or "").strip()
    if not plaintext:
        raise CloudCredentialRejectedError("请粘贴云盘登录态")
    if len(plaintext) > MAX_CREDENTIAL_LENGTH:
        raise CloudCredentialRejectedError("云盘登录态过长，请检查是否粘贴了多余内容")
    if get_account_for_provider(session, user_id, resolved_provider) is not None:
        raise CloudAccountExistsError("该云盘已绑定，请先解绑或重新校验")

    account_info = verify_credential(
        resolved_provider,
        plaintext,
        settings=settings,
        http_client=http_client,
    )

    account = CloudAccount(
        id=str(uuid4()),
        user_id=user_id,
        provider=resolved_provider,
        display_name=account_info.display_name[:120],
        credential_cipher=encrypt_credential(settings, plaintext),
        credential_hint=credential_hint(plaintext),
        default_folder=normalize_folder(default_folder),
        status="active",
        last_checked_at=datetime.now(UTC),
        last_error=None,
    )
    session.add(account)
    session.commit()
    session.refresh(account)
    return account


def delete_cloud_account(session: Session, user_id: str, account_id: str) -> None:
    """解绑云盘账号。"""

    account = get_cloud_account(session, user_id, account_id)
    session.delete(account)
    session.commit()


def verify_cloud_account(
    session: Session,
    user_id: str,
    account_id: str,
    *,
    settings: Settings,
    http_client: httpx.Client | None = None,
) -> CloudAccount:
    """重新校验已绑定云盘，并刷新状态。"""

    account = get_cloud_account(session, user_id, account_id)
    credential = decrypt_credential(settings, account.credential_cipher)
    account.last_checked_at = datetime.now(UTC)
    try:
        account_info = verify_credential(
            account.provider,
            credential,
            settings=settings,
            http_client=http_client,
        )
    except CloudCredentialRejectedError as error:
        account.status = "invalid"
        account.last_error = str(error)[:200]
        session.commit()
        session.refresh(account)
        return account
    account.status = "active"
    account.last_error = None
    account.display_name = account_info.display_name[:120]
    session.commit()
    session.refresh(account)
    return account
