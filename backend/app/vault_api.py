"""密码库接口：端到端加密，服务器只存取密文。"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.dependencies import get_session
from app.email_service import EmailDeliveryError
from app.models import VaultItem
from app.schemas import (
    VaultAccessStatus,
    VaultAccessVerify,
    VaultItemCreate,
    VaultItemRead,
    VaultItemUpdate,
    VaultKeyCreate,
    VaultKeyUpdate,
    VaultSecurityRead,
    VaultSecurityUpdate,
    VaultStatus,
    VaultTotpConfirm,
    VaultTotpSetup,
    VaultUnlockFailureReport,
)
from app.vault_security_service import (
    AuthContext,
    IssuedAccess,
    VaultAccessError,
    VaultCodeRateLimitedError,
    begin_totp_setup,
    confirm_totp,
    describe_access,
    enforce_mutation_ip,
    env_allowlist,
    http_error,
    record_unlock_failure,
    require_grant_user,
    require_ip_user,
    resolve_auth,
    send_access_code,
    set_client_cookie,
    totp_enabled,
    update_user_allowlist,
    user_allowlist,
    verify_access,
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


def _ip_user(request: Request, session: SessionDependency) -> AuthContext:
    """登录，并且网页请求的 IP 在白名单里。"""

    return require_ip_user(request, session)


def _grant_user(request: Request, session: SessionDependency) -> str:
    """在 IP 检查通过后，还要有未过期的密码库授权。"""

    return require_grant_user(request, session)


IpUser = Annotated[AuthContext, Depends(_ip_user)]
GrantUser = Annotated[str, Depends(_grant_user)]

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
def read_vault_route(session: SessionDependency, auth: IpUser) -> VaultStatus:
    """读取密码库状态和解锁所需的包裹参数。网页端先检查 IP 白名单。"""

    return vault_status(session, auth.user_id)


@router.post("", response_model=VaultStatus, status_code=status.HTTP_201_CREATED)
def create_vault_route(
    payload: VaultKeyCreate,
    session: SessionDependency,
    auth: IpUser,
) -> VaultStatus:
    """首次设置主密码。"""

    try:
        return create_vault(session, auth.user_id, payload)
    except VaultAlreadyConfiguredError as error:
        raise HTTPException(status_code=409, detail="密码库已经设置过主密码") from error


@router.put("/key", response_model=VaultStatus)
def update_vault_key_route(
    payload: VaultKeyUpdate,
    session: SessionDependency,
    user_id: GrantUser,
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
    user_id: GrantUser,
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
    user_id: GrantUser,
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
    user_id: GrantUser,
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
    user_id: GrantUser,
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
    user_id: GrantUser,
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


def _status_model(
    access: IssuedAccess,
    client_token: str | None = None,
) -> VaultAccessStatus:
    return VaultAccessStatus(
        granted=access.granted,
        expires_at=access.expires_at,
        totp_enabled=access.totp_enabled,
        hours=access.hours,
        client_type=access.client_type,
        client_token=client_token,
    )


def _guard(session: Session, error: VaultAccessError) -> HTTPException:
    session.rollback()
    return http_error(error)


@router.get("/access", response_model=VaultAccessStatus)
def read_vault_access_route(
    request: Request,
    session: SessionDependency,
    auth: IpUser,
) -> VaultAccessStatus:
    """当前 IP 和浏览器上有没有授权。这个接口不发放授权，也不延长窗口。"""

    described = describe_access(session, request.app.state.settings, auth, request)
    return _status_model(described)


@router.post("/access/code")
def send_vault_access_code_route(
    request: Request,
    session: SessionDependency,
) -> dict[str, str]:
    """把打开密码库的验证码发到账号邮箱。"""

    auth = resolve_auth(request, session)
    try:
        email = send_access_code(request, session, auth)
    except VaultCodeRateLimitedError as error:
        raise http_error(error) from error
    except VaultAccessError as error:
        raise _guard(session, error) from error
    except EmailDeliveryError as error:
        session.rollback()
        raise HTTPException(status_code=503, detail="验证码邮件发送失败") from error
    return {"detail": f"验证码已发送到 {email}"}


@router.post("/access/verify", response_model=VaultAccessStatus)
def verify_vault_access_route(
    payload: VaultAccessVerify,
    request: Request,
    response: Response,
    session: SessionDependency,
) -> VaultAccessStatus:
    """校验验证码或动态码，给当前客户端签发固定时长的授权。"""

    auth = resolve_auth(request, session)
    try:
        issued, token = verify_access(
            request,
            session,
            auth,
            method=payload.method,
            code=payload.code,
        )
    except VaultAccessError as error:
        raise _guard(session, error) from error
    set_client_cookie(response, request, token)
    return _status_model(issued, issued.client_token)


@router.post("/unlock-failed", response_model=VaultUnlockFailureReport)
def report_vault_unlock_failure_route(
    request: Request,
    session: SessionDependency,
) -> VaultUnlockFailureReport:
    """客户端发现主密码不正确时上报，服务端发一封报警邮件。"""

    auth = resolve_auth(request, session)
    try:
        sent = record_unlock_failure(request, session, auth)
    except VaultAccessError as error:
        raise _guard(session, error) from error
    except EmailDeliveryError as error:
        raise HTTPException(status_code=503, detail="报警邮件发送失败") from error
    return VaultUnlockFailureReport(sent=sent)


@router.get("/security", response_model=VaultSecurityRead)
def read_vault_security_route(
    request: Request,
    session: SessionDependency,
    user_id: GrantUser,
) -> VaultSecurityRead:
    """读取白名单和身份验证器是否已绑定。不返回密钥。"""

    settings = request.app.state.settings
    return VaultSecurityRead(
        totp_enabled=totp_enabled(session, user_id),
        env_allowlist=env_allowlist(settings),
        user_allowlist=user_allowlist(session, user_id),
        web_grant_hours=settings.vault_web_grant_hours,
        mobile_grant_hours=settings.vault_mobile_grant_hours,
    )


@router.put("/security", response_model=VaultSecurityRead)
def update_vault_security_route(
    payload: VaultSecurityUpdate,
    request: Request,
    session: SessionDependency,
    user_id: GrantUser,
) -> VaultSecurityRead:
    """修改用户追加的白名单。当前 IP 必须已经被允许，环境变量条目不会被删掉。"""

    auth = resolve_auth(request, session)
    if auth.user_id != user_id:
        raise HTTPException(status_code=401, detail="请先登录")
    try:
        enforce_mutation_ip(request, session, auth.user_id)
        env_entries, user_entries = update_user_allowlist(
            request,
            session,
            auth,
            payload.user_allowlist,
        )
    except VaultAccessError as error:
        raise _guard(session, error) from error
    settings = request.app.state.settings
    return VaultSecurityRead(
        totp_enabled=totp_enabled(session, auth.user_id),
        env_allowlist=env_entries,
        user_allowlist=user_entries,
        web_grant_hours=settings.vault_web_grant_hours,
        mobile_grant_hours=settings.vault_mobile_grant_hours,
    )


@router.post("/totp/setup", response_model=VaultTotpSetup)
def setup_vault_totp_route(
    request: Request,
    session: SessionDependency,
    user_id: GrantUser,
) -> VaultTotpSetup:
    """生成身份验证器密钥。确认前不会启用。"""

    auth = resolve_auth(request, session)
    if auth.user_id != user_id:
        raise HTTPException(status_code=401, detail="请先登录")
    try:
        secret, uri = begin_totp_setup(request, session, auth)
    except VaultAccessError as error:
        raise _guard(session, error) from error
    return VaultTotpSetup(secret=secret, otpauth_uri=uri)


@router.post("/totp/confirm")
def confirm_vault_totp_route(
    payload: VaultTotpConfirm,
    request: Request,
    session: SessionDependency,
    user_id: GrantUser,
) -> dict[str, bool]:
    """用动态码确认绑定。绑定之后才能用动态码换授权。"""

    auth = resolve_auth(request, session)
    if auth.user_id != user_id:
        raise HTTPException(status_code=401, detail="请先登录")
    try:
        confirm_totp(request, session, auth, payload.code)
    except VaultAccessError as error:
        raise _guard(session, error) from error
    return {"totp_enabled": True}


__all__ = ["RESET_CONFIRMATION", "router"]
