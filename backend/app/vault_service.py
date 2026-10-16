"""密码库业务逻辑：只存取浏览器加密后的数据。"""

from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.database import commit_with_retry
from app.models import VaultItem, VaultKey
from app.schemas import (
    VaultItemCreate,
    VaultItemUpdate,
    VaultKeyCreate,
    VaultKeyUpdate,
    VaultStatus,
)

MAX_VAULT_ITEMS = 5_000


class VaultNotConfiguredError(LookupError):
    """还没有设置主密码。"""


class VaultAlreadyConfiguredError(RuntimeError):
    """已经设置过主密码。"""


class VaultItemNotFoundError(LookupError):
    """条目不存在或不属于当前账号。"""


class VaultItemExistsError(RuntimeError):
    """同一 ID 的条目已存在。"""


class VaultLimitError(RuntimeError):
    """条目数量超出上限。"""


class VaultVersionConflictError(RuntimeError):
    """版本号已过期，返回服务端当前版本。"""

    def __init__(self, current: VaultItem | VaultKey) -> None:
        super().__init__("内容已在其他地方修改，请刷新后重试")
        self.current = current


def _vault_key(session: Session, user_id: str) -> VaultKey | None:
    return session.get(VaultKey, user_id)


def _require_vault(session: Session, user_id: str) -> VaultKey:
    key = _vault_key(session, user_id)
    if key is None:
        raise VaultNotConfiguredError
    return key


def vault_status(session: Session, user_id: str) -> VaultStatus:
    """读取密码库状态；未设置时只返回 configured=false。"""

    key = _vault_key(session, user_id)
    if key is None:
        return VaultStatus(configured=False)
    item_count = (
        session.scalar(
            select(func.count())
            .select_from(VaultItem)
            .where(VaultItem.user_id == user_id)
        )
        or 0
    )
    return VaultStatus(
        configured=True,
        kdf=key.kdf,
        kdf_iterations=key.kdf_iterations,
        kdf_salt=key.kdf_salt,
        wrapped_key=key.wrapped_key,
        wrap_iv=key.wrap_iv,
        version=key.version,
        item_count=item_count,
    )


def create_vault(
    session: Session, user_id: str, payload: VaultKeyCreate
) -> VaultStatus:
    """首次保存包裹后的库密钥。"""

    if _vault_key(session, user_id) is not None:
        raise VaultAlreadyConfiguredError
    session.add(VaultKey(user_id=user_id, version=1, **payload.model_dump()))
    commit_with_retry(session)
    return vault_status(session, user_id)


def update_vault_key(
    session: Session, user_id: str, payload: VaultKeyUpdate
) -> VaultStatus:
    """更改主密码；条目由同一把库密钥加密，不需要重新加密。"""

    key = _require_vault(session, user_id)
    if key.version != payload.expected_version:
        raise VaultVersionConflictError(key)
    for field, value in payload.model_dump(exclude={"expected_version"}).items():
        setattr(key, field, value)
    key.version += 1
    commit_with_retry(session)
    return vault_status(session, user_id)


def reset_vault(session: Session, user_id: str) -> None:
    """忘记主密码时清空整个密码库；数据无法解密，只能删除。"""

    session.execute(delete(VaultItem).where(VaultItem.user_id == user_id))
    session.execute(delete(VaultKey).where(VaultKey.user_id == user_id))
    commit_with_retry(session)


def list_vault_items(session: Session, user_id: str) -> list[VaultItem]:
    """返回全部密文条目，由浏览器解密后在本地搜索。"""

    _require_vault(session, user_id)
    return list(
        session.scalars(
            select(VaultItem)
            .where(VaultItem.user_id == user_id)
            .order_by(VaultItem.updated_at.desc(), VaultItem.id.desc())
        )
    )


def _get_item(session: Session, user_id: str, item_id: str) -> VaultItem:
    item = session.scalar(
        select(VaultItem).where(VaultItem.id == item_id, VaultItem.user_id == user_id)
    )
    if item is None:
        raise VaultItemNotFoundError
    return item


def create_vault_item(
    session: Session, user_id: str, payload: VaultItemCreate
) -> VaultItem:
    """保存新条目。"""

    _require_vault(session, user_id)
    item_id = str(payload.id)
    if session.get(VaultItem, item_id) is not None:
        raise VaultItemExistsError
    count = (
        session.scalar(
            select(func.count())
            .select_from(VaultItem)
            .where(VaultItem.user_id == user_id)
        )
        or 0
    )
    if count >= MAX_VAULT_ITEMS:
        raise VaultLimitError
    item = VaultItem(
        id=item_id,
        user_id=user_id,
        ciphertext=payload.ciphertext,
        iv=payload.iv,
        version=1,
    )
    session.add(item)
    commit_with_retry(session)
    session.refresh(item)
    return item


def update_vault_item(
    session: Session,
    user_id: str,
    item_id: str,
    payload: VaultItemUpdate,
) -> VaultItem:
    """按版本号替换密文。"""

    item = _get_item(session, user_id, item_id)
    if item.version != payload.expected_version:
        raise VaultVersionConflictError(item)
    item.ciphertext = payload.ciphertext
    item.iv = payload.iv
    item.version += 1
    commit_with_retry(session)
    session.refresh(item)
    return item


def delete_vault_item(
    session: Session,
    user_id: str,
    item_id: str,
    expected_version: int,
) -> None:
    """按版本号永久删除条目。"""

    item = _get_item(session, user_id, item_id)
    if item.version != expected_version:
        raise VaultVersionConflictError(item)
    session.delete(item)
    commit_with_retry(session)
