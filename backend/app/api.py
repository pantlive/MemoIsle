"""Memo API 路由。"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    status,
)
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.bookmark_service import (
    BookmarkBatchNotFoundError,
    BookmarkBatchStateError,
    create_bookmark_batch,
    preview_bookmarks,
    process_bookmark_batch_in_background,
    read_bookmark_batch,
    retry_bookmark_batch,
    undo_bookmark_batch,
)
from app.browser_capture_service import (
    BrowserCaptureConsumedError,
    BrowserCaptureExpiredError,
    BrowserCaptureNotFoundError,
    BrowserCaptureOriginError,
    create_browser_capture,
    exchange_browser_capture,
    list_open_browser_tabs,
    sync_open_browser_tabs,
)
from app.config import Settings
from app.dependencies import get_current_user_id, get_session, get_settings
from app.link_health_service import (
    apply_link_health_action,
    check_resource_link,
    list_link_health_center,
)
from app.resource_processing import UnsafeResourceUrlError
from app.resource_service import enrich_resource, enrich_resource_in_background
from app.schemas import (
    BookmarkImportBatchRead,
    BookmarkImportPreview,
    BookmarkImportRequest,
    BrowserCaptureContext,
    BrowserCaptureCreate,
    BrowserCaptureCreated,
    BrowserCaptureExchangeRequest,
    BrowserOpenTabListResponse,
    BrowserOpenTabRead,
    BrowserTabSyncRequest,
    BrowserTabSyncResponse,
    LinkHealthActionRequest,
    LinkHealthListResponse,
    LinkHealthStatus,
    MemoCreate,
    MemoListResponse,
    MemoRead,
    MemoSort,
    MemoStatus,
    MemoType,
    MemoUpdate,
    ResourceCategory,
    ResourceKind,
    ResourceReadingStatus,
    ReviewQueueResponse,
    SyncResponse,
    WordReviewRequest,
)
from app.service import (
    AudioValidationError,
    MemoNotFoundError,
    MemoTypeError,
    MemoVersionConflictError,
    attach_audio,
    create_memo,
    get_audio_path,
    get_memo,
    list_memos,
    list_review_queue,
    review_word,
    update_memo,
)

router = APIRouter()
SessionDependency = Annotated[Session, Depends(get_session)]
UserDependency = Annotated[str, Depends(get_current_user_id)]
SettingsDependency = Annotated[Settings, Depends(get_settings)]


@router.get("/health", tags=["system"])
def health() -> dict[str, str]:
    """提供部署和开发环境健康检查。"""

    return {"status": "ok"}


@router.post(
    "/browser-captures",
    response_model=BrowserCaptureCreated,
    status_code=status.HTTP_201_CREATED,
    tags=["browser-captures"],
)
def create_browser_capture_route(
    payload: BrowserCaptureCreate,
    request: Request,
    session: SessionDependency,
    user_id: UserDependency,
) -> BrowserCaptureCreated:
    """接收扩展明确授权的当前页并签发短时一次性凭据。"""

    try:
        return create_browser_capture(
            session,
            user_id,
            payload,
            request.headers.get("origin"),
        )
    except BrowserCaptureOriginError as error:
        raise HTTPException(status_code=403, detail="浏览器扩展来源不匹配") from error
    except (UnsafeResourceUrlError, ValueError) as error:
        raise HTTPException(status_code=422, detail="当前网页不支持收藏") from error


@router.post(
    "/browser-captures/exchange",
    response_model=BrowserCaptureContext,
    tags=["browser-captures"],
)
def exchange_browser_capture_route(
    payload: BrowserCaptureExchangeRequest,
    session: SessionDependency,
    user_id: UserDependency,
) -> BrowserCaptureContext:
    """由 Web 一次性换取扩展授权的网页附件。"""

    try:
        return exchange_browser_capture(session, user_id, payload.token)
    except BrowserCaptureNotFoundError as error:
        raise HTTPException(status_code=404, detail="网页授权不存在") from error
    except BrowserCaptureExpiredError as error:
        raise HTTPException(
            status_code=410,
            detail="网页授权已过期，请重新点击扩展",
        ) from error
    except BrowserCaptureConsumedError as error:
        raise HTTPException(status_code=409, detail="网页授权已经使用") from error


@router.post(
    "/browser-tabs/sync",
    response_model=BrowserTabSyncResponse,
    tags=["browser-tabs"],
)
def sync_browser_tabs_route(
    payload: BrowserTabSyncRequest,
    request: Request,
    session: SessionDependency,
    user_id: UserDependency,
) -> BrowserTabSyncResponse:
    """接收扩展同步的当前浏览器打开标签页快照。"""

    try:
        synced_count = sync_open_browser_tabs(
            session,
            user_id,
            payload,
            request.headers.get("origin"),
        )
    except BrowserCaptureOriginError as error:
        raise HTTPException(status_code=403, detail="浏览器扩展来源不匹配") from error
    except (ValueError, OSError) as error:
        raise HTTPException(status_code=422, detail="浏览器标签页快照无效") from error
    return BrowserTabSyncResponse(synced_count=synced_count)


@router.get(
    "/browser-tabs/open",
    response_model=BrowserOpenTabListResponse,
    tags=["browser-tabs"],
)
def list_open_browser_tabs_route(
    session: SessionDependency,
    user_id: UserDependency,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> BrowserOpenTabListResponse:
    """读取当前浏览器正在打开、且可安全收藏的网页。"""

    items = list_open_browser_tabs(session, user_id, limit=limit)
    return BrowserOpenTabListResponse(
        items=[BrowserOpenTabRead.model_validate(item) for item in items]
    )


@router.post(
    "/memos",
    response_model=MemoRead,
    status_code=status.HTTP_201_CREATED,
    tags=["memos"],
)
def create_memo_route(
    payload: MemoCreate,
    background_tasks: BackgroundTasks,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> MemoRead:
    """创建或返回同一客户端标识对应的条目。"""

    memo = create_memo(session, user_id, payload)
    if (
        memo.type == MemoType.RESOURCE
        and settings.resource_enrichment_enabled
        and memo.resource_metadata_status in {"pending", "failed"}
    ):
        background_tasks.add_task(
            enrich_resource_in_background,
            settings.database_url,
            user_id,
            memo.id,
            settings,
        )
    return MemoRead.model_validate(memo)


@router.post(
    "/resources/{memo_id}/enrich",
    response_model=MemoRead,
    tags=["resources"],
)
def enrich_resource_route(
    memo_id: UUID,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> MemoRead:
    """手动重试网页元数据与自动分类。"""

    try:
        memo = enrich_resource(
            session,
            user_id,
            str(memo_id),
            settings,
        )
    except MemoNotFoundError as error:
        raise HTTPException(status_code=404, detail="网页资料不存在") from error
    except MemoTypeError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return MemoRead.model_validate(memo)


@router.get(
    "/resources/link-health",
    response_model=LinkHealthListResponse,
    tags=["resources"],
)
def list_link_health_route(
    session: SessionDependency,
    user_id: UserDependency,
    health_status: Annotated[
        LinkHealthStatus | None,
        Query(alias="status"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 200,
) -> LinkHealthListResponse:
    """读取失效、重定向、变化和暂时失败的网页资料。"""

    items, counts = list_link_health_center(
        session,
        user_id,
        health_status,
        limit,
    )
    return LinkHealthListResponse(
        items=[MemoRead.model_validate(item) for item in items],
        counts=counts,
    )


@router.post(
    "/resources/{memo_id}/link-checks",
    response_model=MemoRead,
    tags=["resources"],
)
def check_resource_link_route(
    memo_id: UUID,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
    expected_version: Annotated[int, Query(ge=1)],
) -> MemoRead:
    """人工触发一次带 SSRF 防护的网页链接检查。"""

    try:
        memo = check_resource_link(
            session,
            user_id,
            str(memo_id),
            settings,
            expected_version=expected_version,
            force=True,
        )
    except MemoNotFoundError as error:
        raise HTTPException(status_code=404, detail="网页资料不存在") from error
    except MemoTypeError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except MemoVersionConflictError as error:
        current = MemoRead.model_validate(error.current)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": str(error), "current": current.model_dump(mode="json")},
        ) from error
    return MemoRead.model_validate(memo)


@router.post(
    "/resources/{memo_id}/link-health-actions",
    response_model=MemoRead,
    tags=["resources"],
)
def apply_link_health_action_route(
    memo_id: UUID,
    payload: LinkHealthActionRequest,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> MemoRead:
    """处理一条巡检提醒。"""

    try:
        memo = apply_link_health_action(
            session,
            user_id,
            str(memo_id),
            payload,
            settings,
        )
    except MemoNotFoundError as error:
        raise HTTPException(status_code=404, detail="网页资料不存在") from error
    except (MemoTypeError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except MemoVersionConflictError as error:
        current = MemoRead.model_validate(error.current)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": str(error), "current": current.model_dump(mode="json")},
        ) from error
    return MemoRead.model_validate(memo)


@router.post(
    "/bookmark-imports/preview",
    response_model=BookmarkImportPreview,
    tags=["bookmark-imports"],
)
def preview_bookmark_import_route(
    payload: BookmarkImportRequest,
    session: SessionDependency,
    user_id: UserDependency,
) -> BookmarkImportPreview:
    """校验浏览器本地解析的书签，并返回去重预览。"""

    return preview_bookmarks(session, user_id, payload)


@router.post(
    "/bookmark-imports",
    response_model=BookmarkImportBatchRead,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["bookmark-imports"],
)
def create_bookmark_import_route(
    payload: BookmarkImportRequest,
    background_tasks: BackgroundTasks,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> BookmarkImportBatchRead:
    """确认并异步处理一个 Chrome 书签导入批次。"""

    batch = create_bookmark_batch(session, user_id, payload)
    response = read_bookmark_batch(session, user_id, batch.id)
    background_tasks.add_task(
        process_bookmark_batch_in_background,
        settings.database_url,
        user_id,
        batch.id,
        settings,
    )
    return response


@router.get(
    "/bookmark-imports/{batch_id}",
    response_model=BookmarkImportBatchRead,
    tags=["bookmark-imports"],
)
def get_bookmark_import_route(
    batch_id: UUID,
    session: SessionDependency,
    user_id: UserDependency,
) -> BookmarkImportBatchRead:
    """读取书签导入批次进度和逐项结果。"""

    try:
        return read_bookmark_batch(session, user_id, str(batch_id))
    except BookmarkBatchNotFoundError as error:
        raise HTTPException(status_code=404, detail="书签导入批次不存在") from error


@router.post(
    "/bookmark-imports/{batch_id}/retry",
    response_model=BookmarkImportBatchRead,
    tags=["bookmark-imports"],
)
def retry_bookmark_import_route(
    batch_id: UUID,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> BookmarkImportBatchRead:
    """重新处理书签导入批次中的失败项目。"""

    try:
        retry_bookmark_batch(
            session,
            user_id,
            str(batch_id),
            settings,
        )
        return read_bookmark_batch(session, user_id, str(batch_id))
    except BookmarkBatchNotFoundError as error:
        raise HTTPException(status_code=404, detail="书签导入批次不存在") from error
    except BookmarkBatchStateError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post(
    "/bookmark-imports/{batch_id}/undo",
    response_model=BookmarkImportBatchRead,
    tags=["bookmark-imports"],
)
def undo_bookmark_import_route(
    batch_id: UUID,
    session: SessionDependency,
    user_id: UserDependency,
) -> BookmarkImportBatchRead:
    """撤销本批导入且尚未被用户编辑的网页资料。"""

    try:
        undo_bookmark_batch(session, user_id, str(batch_id))
        return read_bookmark_batch(session, user_id, str(batch_id))
    except BookmarkBatchNotFoundError as error:
        raise HTTPException(status_code=404, detail="书签导入批次不存在") from error


@router.get("/memos", response_model=MemoListResponse, tags=["memos"])
def list_memos_route(
    session: SessionDependency,
    user_id: UserDependency,
    memo_type: Annotated[MemoType | None, Query(alias="type")] = None,
    query_text: Annotated[str | None, Query(alias="q", max_length=200)] = None,
    resource_category: Annotated[
        ResourceCategory | None,
        Query(alias="category"),
    ] = None,
    resource_kind: Annotated[
        ResourceKind | None,
        Query(alias="resource_kind"),
    ] = None,
    resource_reading_status: Annotated[
        ResourceReadingStatus | None,
        Query(alias="reading_status"),
    ] = None,
    link_health_status: Annotated[
        LinkHealthStatus | None,
        Query(alias="health"),
    ] = None,
    tag: Annotated[str | None, Query(max_length=100)] = None,
    collection: Annotated[str | None, Query(max_length=100)] = None,
    starred: Annotated[bool | None, Query()] = None,
    memo_status: Annotated[MemoStatus | None, Query(alias="status")] = None,
    created_from: Annotated[date | None, Query()] = None,
    created_to: Annotated[date | None, Query()] = None,
    sort: Annotated[MemoSort, Query()] = MemoSort.UPDATED_DESC,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> MemoListResponse:
    """按类型及关键词读取当前用户条目。"""

    items = list_memos(
        session,
        user_id,
        memo_type=memo_type,
        query_text=query_text,
        resource_category=resource_category,
        resource_kind=resource_kind,
        resource_reading_status=resource_reading_status,
        link_health_status=(
            link_health_status.value if link_health_status is not None else None
        ),
        tag=tag,
        collection=collection,
        starred=starred,
        memo_status=memo_status,
        created_from=(
            datetime.combine(created_from, time.min, tzinfo=UTC)
            if created_from is not None
            else None
        ),
        created_to=(
            datetime.combine(created_to, time.min, tzinfo=UTC) + timedelta(days=1)
            if created_to is not None
            else None
        ),
        sort=sort,
        limit=limit,
    )
    return MemoListResponse(items=[MemoRead.model_validate(item) for item in items])


@router.get("/memos/{memo_id}", response_model=MemoRead, tags=["memos"])
def get_memo_route(
    memo_id: UUID,
    session: SessionDependency,
    user_id: UserDependency,
) -> MemoRead:
    """读取一条内容。"""

    try:
        memo = get_memo(session, user_id, str(memo_id))
    except MemoNotFoundError as error:
        raise HTTPException(status_code=404, detail="条目不存在") from error
    return MemoRead.model_validate(memo)


@router.patch("/memos/{memo_id}", response_model=MemoRead, tags=["memos"])
def update_memo_route(
    memo_id: UUID,
    payload: MemoUpdate,
    session: SessionDependency,
    user_id: UserDependency,
) -> MemoRead:
    """更新条目并检测跨设备版本冲突。"""

    try:
        memo = update_memo(session, user_id, str(memo_id), payload)
    except MemoNotFoundError as error:
        raise HTTPException(status_code=404, detail="条目不存在") from error
    except MemoVersionConflictError as error:
        current = MemoRead.model_validate(error.current)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": str(error), "current": current.model_dump(mode="json")},
        ) from error
    return MemoRead.model_validate(memo)


@router.get("/sync/changes", response_model=SyncResponse, tags=["sync"])
def sync_changes_route(
    session: SessionDependency,
    user_id: UserDependency,
    cursor: Annotated[datetime | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> SyncResponse:
    """按服务端更新时间返回增量同步数据。"""

    requested_at = datetime.now(UTC)
    items = list_memos(
        session,
        user_id,
        updated_after=cursor,
        limit=limit,
        include_trashed=True,
        oldest_first=True,
    )
    next_cursor = items[-1].updated_at if items else requested_at
    return SyncResponse(
        items=[MemoRead.model_validate(item) for item in items],
        cursor=next_cursor,
    )


@router.get("/review-queue", response_model=ReviewQueueResponse, tags=["review"])
def review_queue_route(
    session: SessionDependency,
    user_id: UserDependency,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> ReviewQueueResponse:
    """返回已经到期的英语单词。"""

    items = list_review_queue(session, user_id, limit=limit)
    return ReviewQueueResponse(
        items=[MemoRead.model_validate(item) for item in items],
    )


@router.post(
    "/words/{memo_id}/reviews",
    response_model=MemoRead,
    tags=["review"],
)
def review_word_route(
    memo_id: UUID,
    payload: WordReviewRequest,
    session: SessionDependency,
    user_id: UserDependency,
) -> MemoRead:
    """提交一次单词复习反馈。"""

    try:
        memo = review_word(session, user_id, str(memo_id), payload)
    except MemoNotFoundError as error:
        raise HTTPException(status_code=404, detail="单词不存在") from error
    except MemoTypeError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except MemoVersionConflictError as error:
        current = MemoRead.model_validate(error.current)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": str(error), "current": current.model_dump(mode="json")},
        ) from error
    return MemoRead.model_validate(memo)


@router.post("/memos/{memo_id}/audio", response_model=MemoRead, tags=["audio"])
async def upload_memo_audio_route(
    memo_id: UUID,
    request: Request,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
    expected_version: Annotated[int, Query(ge=1)],
    duration_ms: Annotated[int | None, Header(alias="X-Audio-Duration-Ms")] = None,
) -> MemoRead:
    """接收原始音频字节并关联到一条灵感。"""

    content_type = request.headers.get("content-type", "")
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared_size = int(content_length)
        except ValueError as error:
            raise HTTPException(
                status_code=400,
                detail="Content-Length 无效",
            ) from error
        if declared_size > 20 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="录音不能超过 20 MB")
    content = await request.body()
    try:
        memo = attach_audio(
            session=session,
            user_id=user_id,
            memo_id=str(memo_id),
            expected_version=expected_version,
            content=content,
            mime_type=content_type,
            duration_ms=duration_ms,
            audio_directory=settings.audio_directory,
        )
    except MemoNotFoundError as error:
        raise HTTPException(status_code=404, detail="灵感不存在") from error
    except (MemoTypeError, AudioValidationError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except MemoVersionConflictError as error:
        current = MemoRead.model_validate(error.current)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": str(error), "current": current.model_dump(mode="json")},
        ) from error
    return MemoRead.model_validate(memo)


@router.get("/memos/{memo_id}/audio", tags=["audio"])
def download_memo_audio_route(
    memo_id: UUID,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> FileResponse:
    """下载或播放当前用户的一条录音。"""

    try:
        memo, audio_path = get_audio_path(
            session,
            user_id,
            str(memo_id),
            settings.audio_directory,
        )
    except MemoNotFoundError as error:
        raise HTTPException(status_code=404, detail="录音不存在") from error
    return FileResponse(
        path=audio_path,
        media_type=memo.audio_mime_type or "application/octet-stream",
        filename=f"memoisle-{memo.id}.audio",
        content_disposition_type="inline",
    )
