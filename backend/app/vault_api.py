"""密码库接口：端到端加密，服务器只存取密文。"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.dependencies import get_current_user_id, get_session
from app.models import VaultItem
from app.schemas import (
    VaultItemCreate,
    VaultItemRead,
    VaultItemUpdate,
    VaultKeyCreate,
    VaultKeyUpdate,
    VaultStatus,
)
from app.vault_service import (
    VaultAlreadyConfiguredError,
    VaultItemExistsError,
    VaultItemNotFoundError,
    VaultLimitError,
    VaultNotConfiguredError,
    VaultVersionConflictError,
    create_vault,
    create_vault_item,
    delete_vault_item,
    list_vault_items,
    reset_vault,
    update_vault_item,
    update_vault_key,
    vault_status,
)

router = APIRouter(prefix="/vault", tags=["vault"])
SessionDependency = Annotated[Session, Depends(get_session)]
UserDependency = Annotated[str, Depends(get_current_user_id)]

RESET_CONFIRMATION = "delete-all-vault-items"


def _not_configured() -> HTTPException:
    return HTTPException(status_code=404, detail="还没有设置密码库主密码")


def _conflict(error: VaultVersionConflictError) -> HTTPException:
    current = error.current
    detail: dict[str, object] = {"message": str(error), "code": "version_conflict"}
    if isinstance(current, VaultItem):
        detail["current"] = VaultItemRead.model_validate(current).model_dump(
            mode="json"
        )
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


@router.get("", response_model=VaultStatus)
def read_vault_route(
    session: SessionDependency, user_id: UserDependency
) -> VaultStatus:
    """读取密码库状态和解锁所需的包裹参数。"""

    return vault_status(session, user_id)


@router.post("", response_model=VaultStatus, status_code=status.HTTP_201_CREATED)
def create_vault_route(
    payload: VaultKeyCreate,
    session: SessionDependency,
    user_id: UserDependency,
) -> VaultStatus:
    """首次设置主密码。"""

    try:
        return create_vault(session, user_id, payload)
    except VaultAlreadyConfiguredError as error:
        raise HTTPException(status_code=409, detail="密码库已经设置过主密码") from error


@router.put("/key", response_model=VaultStatus)
def update_vault_key_route(
    payload: VaultKeyUpdate,
    session: SessionDependency,
    user_id: UserDependency,
) -> VaultStatus:
    """更改主密码。"""

    try:
        return update_vault_key(session, user_id, payload)
    except VaultNotConfiguredError as error:
        raise _not_configured() from error
    except VaultVersionConflictError as error:
        raise _conflict(error) from error


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def reset_vault_route(
    session: SessionDependency,
    user_id: UserDependency,
    confirm: Annotated[str, Query()],
) -> Response:
    """忘记主密码时清空密码库，必须带上固定的确认参数。"""

    if confirm != RESET_CONFIRMATION:
        raise HTTPException(status_code=400, detail="缺少清空密码库的确认")
    reset_vault(session, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/items", response_model=list[VaultItemRead])
def list_vault_items_route(
    session: SessionDependency,
    user_id: UserDependency,
) -> list[VaultItemRead]:
    """读取全部密文条目。"""

    try:
        items = list_vault_items(session, user_id)
    except VaultNotConfiguredError as error:
        raise _not_configured() from error
    return [VaultItemRead.model_validate(item) for item in items]


@router.post(
    "/items", response_model=VaultItemRead, status_code=status.HTTP_201_CREATED
)
def create_vault_item_route(
    payload: VaultItemCreate,
    session: SessionDependency,
    user_id: UserDependency,
) -> VaultItemRead:
    """保存新条目。"""

    try:
        item = create_vault_item(session, user_id, payload)
    except VaultNotConfiguredError as error:
        raise _not_configured() from error
    except VaultItemExistsError as error:
        raise HTTPException(status_code=409, detail="条目已存在") from error
    except VaultLimitError as error:
        raise HTTPException(status_code=400, detail="密码库条目数量已达上限") from error
    return VaultItemRead.model_validate(item)


@router.put("/items/{item_id}", response_model=VaultItemRead)
def update_vault_item_route(
    item_id: UUID,
    payload: VaultItemUpdate,
    session: SessionDependency,
    user_id: UserDependency,
) -> VaultItemRead:
    """带版本号更新条目。"""

    try:
        item = update_vault_item(session, user_id, str(item_id), payload)
    except VaultItemNotFoundError as error:
        raise HTTPException(status_code=404, detail="条目不存在") from error
    except VaultVersionConflictError as error:
        raise _conflict(error) from error
    return VaultItemRead.model_validate(item)


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_vault_item_route(
    item_id: UUID,
    session: SessionDependency,
    user_id: UserDependency,
    expected_version: Annotated[int, Query(ge=1)],
) -> Response:
    """永久删除条目。"""

    try:
        delete_vault_item(session, user_id, str(item_id), expected_version)
    except VaultItemNotFoundError as error:
        raise HTTPException(status_code=404, detail="条目不存在") from error
    except VaultVersionConflictError as error:
        raise _conflict(error) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["RESET_CONFIRMATION", "router"]
