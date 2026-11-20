"""轻量文件与文本中转接口：Web 与 Android 互传，服务端只转发不存储。

内容只在 :class:`app.relay_service.RelayHub` 的进程内存里暂放，接收端取走即删，
无人接收时 10 分钟后自动清理；不写数据库、不落盘。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.dependencies import get_current_user_id, get_session
from app.relay_service import (
    MAX_FILE_BYTES,
    MAX_TEXT_BYTES,
    MAX_WAIT_SECONDS,
    RelayDevice,
    RelayError,
    RelayHub,
    RelayItem,
    RelayTooLargeError,
)

router = APIRouter(prefix="/relay", tags=["relay"])
SessionDependency = Annotated[Session, Depends(get_session)]
UserDependency = Annotated[str, Depends(get_current_user_id)]


class RelayTextCreate(BaseModel):
    # 字节上限在 RelayHub 里按 UTF-8 校验，这里只挡住明显过长的请求。
    text: str = Field(min_length=1, max_length=MAX_TEXT_BYTES)
    target: RelayDevice
    source: RelayDevice | None = None


class RelayItemRead(BaseModel):
    id: str
    kind: Literal["text", "file"]
    source: RelayDevice
    target: RelayDevice
    filename: str | None
    mime_type: str | None
    size: int
    created_at: datetime
    expires_at: datetime
    # 剩余秒数，客户端据此倒计时，不受两端时钟偏差影响。
    expires_in: int
    text: str | None = None


def get_relay_hub(request: Request) -> RelayHub:
    hub: RelayHub = request.app.state.relay_hub
    return hub


HubDependency = Annotated[RelayHub, Depends(get_relay_hub)]


def _release_session(session: Session) -> None:
    """中转不需要数据库，校验完登录就归还连接，长轮询期间不占连接。"""

    session.close()


def _to_read(item: RelayItem, now: float) -> RelayItemRead:
    return RelayItemRead(
        id=item.id,
        kind=item.kind,
        source=item.source,
        target=item.target,
        filename=item.filename,
        mime_type=item.mime_type,
        size=item.size,
        created_at=datetime.fromtimestamp(item.created_at, UTC),
        expires_at=datetime.fromtimestamp(item.expires_at, UTC),
        expires_in=max(0, int(item.expires_at - now)),
        text=item.text(),
    )


def _http_error(error: RelayError) -> HTTPException:
    return HTTPException(status_code=error.status_code, detail=error.message)


def _source_of(request: Request, explicit: RelayDevice | None) -> RelayDevice:
    if explicit is not None:
        return explicit
    client = request.headers.get("x-memoisle-client", "").lower()
    return "android" if client in {"mobile", "android"} else "web"


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
        if declared_size > MAX_FILE_BYTES:
            raise _http_error(RelayTooLargeError("文件不能超过 20 MB"))
    chunks: list[bytes] = []
    received = 0
    async for chunk in request.stream():
        received += len(chunk)
        if received > MAX_FILE_BYTES:
            raise _http_error(RelayTooLargeError("文件不能超过 20 MB"))
        chunks.append(chunk)
    return b"".join(chunks)


def _content_disposition(filename: str) -> str:
    ascii_name = filename.encode("ascii", "ignore").decode("ascii").strip() or "file"
    ascii_name = ascii_name.replace('"', "").replace("\\", "")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"


@router.post(
    "/text", response_model=RelayItemRead, status_code=status.HTTP_201_CREATED
)
async def send_text_route(
    payload: RelayTextCreate,
    request: Request,
    session: SessionDependency,
    user_id: UserDependency,
    hub: HubDependency,
) -> RelayItemRead:
    """发一段文字给另一端。"""

    _release_session(session)
    try:
        item = hub.push_text(
            user_id,
            payload.text,
            source=_source_of(request, payload.source),
            target=payload.target,
        )
    except RelayError as error:
        raise _http_error(error) from error
    return _to_read(item, hub.now())


@router.post(
    "/file", response_model=RelayItemRead, status_code=status.HTTP_201_CREATED
)
async def send_file_route(
    request: Request,
    session: SessionDependency,
    user_id: UserDependency,
    hub: HubDependency,
    target: RelayDevice,
    filename: Annotated[str, Query(min_length=1, max_length=1024)],
    source: RelayDevice | None = None,
) -> RelayItemRead:
    """发一个小文件给另一端；请求体是原始文件字节，类型取 Content-Type。"""

    _release_session(session)
    content = await _read_limited_body(request)
    try:
        item = hub.push_file(
            user_id,
            content,
            filename=filename,
            mime_type=request.headers.get("content-type"),
            source=_source_of(request, source),
            target=target,
        )
    except RelayError as error:
        raise _http_error(error) from error
    return _to_read(item, hub.now())


@router.get("/inbox", response_model=list[RelayItemRead])
async def inbox_route(
    session: SessionDependency,
    user_id: UserDependency,
    hub: HubDependency,
    device: RelayDevice,
    wait: Annotated[int, Query(ge=0, le=MAX_WAIT_SECONDS)] = 0,
    known: Annotated[str, Query(max_length=2000)] = "",
) -> list[RelayItemRead]:
    """列出发给本端的内容。

    ``wait`` 大于 0 时开启长轮询：列表和 ``known``（逗号分隔、客户端已显示的 id）
    相同就最多等这么多秒，有新内容或有内容被取走时立刻返回。文本直接带上内容，
    文件只给元数据，需要再调下载接口取走。
    """

    _release_session(session)
    known_ids = frozenset(part for part in known.split(",") if part)
    items = await hub.wait_for(user_id, device, wait, known_ids)
    now = hub.now()
    return [_to_read(item, now) for item in items]


@router.get("/items/{item_id}/download")
async def download_item_route(
    item_id: str,
    session: SessionDependency,
    user_id: UserDependency,
    hub: HubDependency,
) -> Response:
    """取走一条内容并立即从服务端删除，第二次再取返回 404。"""

    _release_session(session)
    try:
        item = hub.take(user_id, item_id)
    except RelayError as error:
        raise _http_error(error) from error
    if item.kind == "text":
        return Response(
            content=item.content,
            media_type="text/plain; charset=utf-8",
            headers={"Cache-Control": "no-store"},
        )
    return Response(
        content=item.content,
        media_type=item.mime_type or "application/octet-stream",
        headers={
            "Content-Disposition": _content_disposition(item.filename or "file"),
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def discard_item_route(
    item_id: str,
    session: SessionDependency,
    user_id: UserDependency,
    hub: HubDependency,
) -> Response:
    """忽略（或复制完文本后移除）一条内容。"""

    _release_session(session)
    try:
        hub.discard(user_id, item_id)
    except RelayError as error:
        raise _http_error(error) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["get_relay_hub", "router"]
