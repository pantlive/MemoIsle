"""易忘事项接口：文字、图片和文件，按账号隔离，直接删除。"""

from __future__ import annotations

from typing import Annotated
from urllib.parse import unquote_plus
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.config import Settings
from app.content_disposition import content_disposition
from app.dependencies import get_current_user_id, get_session, get_settings
from app.forget_service import (
    ForgetAttachmentLimitError,
    ForgetAttachmentNotFoundError,
    ForgetItemLimitError,
    ForgetItemNotFoundError,
    ForgetPayloadTooLargeError,
    ForgetVersionConflictError,
    add_attachment,
    create_item,
    delete_attachment,
    delete_item,
    list_items,
    open_attachment,
    update_item,
)
from app.schemas import (
    ForgetItemCreate,
    ForgetItemRead,
    ForgetItemUpdate,
)
from app.service import MAX_IMAGE_BYTES

router = APIRouter(prefix="/forget", tags=["forget"])
SessionDependency = Annotated[Session, Depends(get_session)]
UserDependency = Annotated[str, Depends(get_current_user_id)]
SettingsDependency = Annotated[Settings, Depends(get_settings)]


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="这条事项不存在或已删除")


def _attachment_not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="这个附件不存在或已删除")


def _conflict(error: ForgetVersionConflictError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "message": str(error),
            "code": "version_conflict",
            "current": ForgetItemRead.model_validate(error.current).model_dump(
                mode="json"
            ),
        },
    )


async def _read_limited_body(request: Request) -> bytes:
    """边读边数，超过 20 MB 立刻 413，避免把超大请求整个读进内存。"""

    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            declared_size = int(declared)
        except ValueError as error:
            raise HTTPException(
                status_code=400, detail="Content-Length 无效"
            ) from error
        if declared_size > MAX_IMAGE_BYTES:
            raise HTTPException(status_code=413, detail="附件不能超过 20 MB")
    chunks: list[bytes] = []
    received = 0
    async for chunk in request.stream():
        received += len(chunk)
        if received > MAX_IMAGE_BYTES:
            raise HTTPException(status_code=413, detail="附件不能超过 20 MB")
        chunks.append(chunk)
    return b"".join(chunks)


def _filename_from_header(request: Request) -> str:
    raw = request.headers.get("x-filename")
    if raw is None or not raw.strip():
        raise HTTPException(
            status_code=400,
            detail="请在 X-Filename 请求头里提供文件名",
        )
    return unquote_plus(raw)


@router.get("/items", response_model=list[ForgetItemRead])
def list_items_route(
    session: SessionDependency,
    user_id: UserDependency,
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=2_000)] = 2_000,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ForgetItemRead]:
    """按标题和正文搜索，置顶在前。"""

    items = list_items(session, user_id, query=q, limit=limit, offset=offset)
    return [ForgetItemRead.model_validate(item) for item in items]


@router.post(
    "/items",
    response_model=ForgetItemRead,
    status_code=status.HTTP_201_CREATED,
)
def create_item_route(
    payload: ForgetItemCreate,
    session: SessionDependency,
    user_id: UserDependency,
) -> ForgetItemRead:
    """新建一条事项。"""

    try:
        item = create_item(session, user_id, payload)
    except ForgetItemLimitError as error:
        raise HTTPException(
            status_code=400, detail="易忘事项已达 2000 条上限"
        ) from error
    return ForgetItemRead.model_validate(item)


@router.put("/items/{item_id}", response_model=ForgetItemRead)
def update_item_route(
    item_id: UUID,
    payload: ForgetItemUpdate,
    session: SessionDependency,
    user_id: UserDependency,
) -> ForgetItemRead:
    """带版本号修改文字和置顶。"""

    try:
        item = update_item(session, user_id, str(item_id), payload)
    except ForgetItemNotFoundError as error:
        raise _not_found() from error
    except ForgetVersionConflictError as error:
        raise _conflict(error) from error
    return ForgetItemRead.model_validate(item)


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_item_route(
    item_id: UUID,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
    expected_version: Annotated[int, Query(ge=1)],
) -> Response:
    """带版本号直接删除一条事项及其附件，不进回收站。"""

    try:
        delete_item(
            session,
            user_id,
            str(item_id),
            expected_version,
            settings.forget_directory,
        )
    except ForgetItemNotFoundError as error:
        raise _not_found() from error
    except ForgetVersionConflictError as error:
        raise _conflict(error) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/items/{item_id}/attachments",
    response_model=ForgetItemRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_attachment_route(
    item_id: UUID,
    request: Request,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> ForgetItemRead:
    """上传一个附件。原始文件名放在 URL 编码的 X-Filename 请求头里。"""

    filename = _filename_from_header(request)
    content = await _read_limited_body(request)
    if not content:
        raise HTTPException(status_code=400, detail="附件内容不能为空")
    try:
        item = add_attachment(
            session,
            user_id,
            str(item_id),
            content,
            filename,
            request.headers.get("content-type"),
            settings.forget_directory,
        )
    except ForgetItemNotFoundError as error:
        raise _not_found() from error
    except ForgetAttachmentLimitError as error:
        raise HTTPException(status_code=400, detail="每条最多 20 个附件") from error
    except ForgetPayloadTooLargeError as error:
        raise HTTPException(status_code=413, detail="附件不能超过 20 MB") from error
    return ForgetItemRead.model_validate(item)


@router.get("/items/{item_id}/attachments/{attachment_id}")
def download_attachment_route(
    item_id: UUID,
    attachment_id: UUID,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> FileResponse:
    """下载附件。图片 inline 返回，其他一律按二进制附件下载。"""

    try:
        attachment, path = open_attachment(
            session,
            user_id,
            str(item_id),
            str(attachment_id),
            settings.forget_directory,
        )
    except ForgetItemNotFoundError as error:
        raise _not_found() from error
    except ForgetAttachmentNotFoundError as error:
        raise _attachment_not_found() from error
    inline = attachment.kind == "image"
    return FileResponse(
        path,
        media_type=attachment.mime if inline else "application/octet-stream",
        headers={
            "Content-Disposition": content_disposition(
                attachment.original_name,
                "inline" if inline else "attachment",
            ),
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )


@router.delete(
    "/items/{item_id}/attachments/{attachment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_attachment_route(
    item_id: UUID,
    attachment_id: UUID,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> Response:
    """删除一个附件，并在提交后再清理磁盘文件。"""

    try:
        delete_attachment(
            session,
            user_id,
            str(item_id),
            str(attachment_id),
            settings.forget_directory,
        )
    except ForgetItemNotFoundError as error:
        raise _not_found() from error
    except ForgetAttachmentNotFoundError as error:
        raise _attachment_not_found() from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)
