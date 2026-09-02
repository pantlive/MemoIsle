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
from fastapi.responses import FileResponse, Response
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
    read_browser_bookmark_snapshot,
    sync_browser_bookmarks,
    sync_open_browser_tabs,
)
from app.browser_extension_service import build_browser_extension_archive
from app.category_service import (
    CategoryCodeNotFoundError,
    CategoryNameConflictError,
    CategoryRuleNotFoundError,
    CategoryTemplateNotFoundError,
    CategoryVersionConflictError,
    category_code_exists,
    category_label,
    create_category_rule,
    create_category_template,
    delete_category_rule,
    list_category_rules,
    list_resource_category_options,
    update_category_rule,
    update_category_template,
)
from app.config import Settings
from app.dependencies import get_current_user_id, get_session, get_settings
from app.link_health_service import (
    apply_link_health_action,
    check_resource_link,
    list_link_health_center,
)
from app.models import ResourceCategoryRule
from app.resource_processing import UnsafeResourceUrlError
from app.resource_service import (
    apply_user_category_rules_in_background,
    enrich_resource,
    enrich_resource_in_background,
    reclassify_user_rule_resources_in_background,
)
from app.schemas import (
    BookmarkImportBatchRead,
    BookmarkImportPreview,
    BookmarkImportRequest,
    BrowserBookmarkSnapshotRead,
    BrowserBookmarkSyncRequest,
    BrowserBookmarkSyncResponse,
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
    MemoCountsResponse,
    MemoCreate,
    MemoListResponse,
    MemoRead,
    MemoSort,
    MemoStatus,
    MemoType,
    MemoUpdate,
    ResourceCategoryCreate,
    ResourceCategoryRead,
    ResourceCategoryRuleCreate,
    ResourceCategoryRuleRead,
    ResourceCategoryRuleUpdate,
    ResourceCategoryUpdate,
    ResourceKind,
    ResourceReadingStatus,
    ReviewQueueResponse,
    ReviewSkipRequest,
    SyncResponse,
    WordMergeRequest,
    WordReviewRequest,
)
from app.service import (
    AudioValidationError,
    MemoNotFoundError,
    MemoTypeError,
    MemoVersionConflictError,
    WordDuplicateError,
    attach_audio,
    count_memos,
    count_memos_by_type,
    create_memo,
    get_audio_path,
    get_memo,
    list_memos,
    list_review_queue,
    merge_word,
    review_word,
    skip_review_item,
    update_memo,
)

router = APIRouter()
SessionDependency = Annotated[Session, Depends(get_session)]
UserDependency = Annotated[str, Depends(get_current_user_id)]
SettingsDependency = Annotated[Settings, Depends(get_settings)]


def resource_category_rule_read(
    session: Session,
    user_id: str,
    rule: ResourceCategoryRule,
) -> ResourceCategoryRuleRead:
    """将数据库规则补充分类名称后返回给客户端。"""

    return ResourceCategoryRuleRead(
        id=rule.id,
        name=rule.name,
        category_code=rule.category_code,
        category_label=category_label(session, user_id, rule.category_code)
        or rule.category_code,
        match_type=rule.match_type,
        pattern=rule.pattern,
        priority=rule.priority,
        enabled=rule.enabled,
        version=rule.version,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


@router.get("/health", tags=["system"])
def health() -> dict[str, str]:
    """提供部署和开发环境健康检查。"""

    return {"status": "ok"}


@router.get(
    "/browser-extension/download",
    response_class=Response,
    tags=["browser-extension"],
)
def download_browser_extension_route() -> Response:
    """下载可解压后加载到 Chrome 或 Edge 的扩展包。"""

    archive = build_browser_extension_archive()
    return Response(
        content=archive,
        media_type="application/zip",
        headers={
            "Content-Disposition": (
                'attachment; filename="memoisle-browser-extension.zip"'
            ),
            "Cache-Control": "no-store",
        },
    )


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
    "/browser-bookmarks/sync",
    response_model=BrowserBookmarkSyncResponse,
    tags=["browser-bookmarks"],
)
def sync_browser_bookmarks_route(
    payload: BrowserBookmarkSyncRequest,
    request: Request,
    session: SessionDependency,
    user_id: UserDependency,
) -> BrowserBookmarkSyncResponse:
    """接收扩展直接读取的当前浏览器书签树快照。"""

    try:
        snapshot = sync_browser_bookmarks(
            session,
            user_id,
            payload,
            request.headers.get("origin"),
        )
    except BrowserCaptureOriginError as error:
        raise HTTPException(status_code=403, detail="浏览器扩展来源不匹配") from error
    return BrowserBookmarkSyncResponse(
        synced_count=len(snapshot.bookmarks),
        truncated=snapshot.truncated,
    )


@router.get(
    "/browser-bookmarks/current",
    response_model=BrowserBookmarkSnapshotRead,
    tags=["browser-bookmarks"],
)
def read_browser_bookmarks_route(
    session: SessionDependency,
    user_id: UserDependency,
) -> BrowserBookmarkSnapshotRead:
    """向 Web 返回最近一次扩展同步的浏览器书签。"""

    return read_browser_bookmark_snapshot(session, user_id)


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

    try:
        memo = create_memo(session, user_id, payload)
    except WordDuplicateError as error:
        current = MemoRead.model_validate(error.current)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": str(error),
                "code": "duplicate_lemma",
                "current": current.model_dump(mode="json"),
            },
        ) from error
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
        str | None,
        Query(alias="category", max_length=50),
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
    offset: Annotated[int, Query(ge=0)] = 0,
) -> MemoListResponse:
    """按类型及关键词读取当前用户条目。"""

    normalized_health_status = (
        link_health_status.value if link_health_status is not None else None
    )
    normalized_created_from = (
        datetime.combine(created_from, time.min, tzinfo=UTC)
        if created_from is not None
        else None
    )
    normalized_created_to = (
        datetime.combine(created_to, time.min, tzinfo=UTC) + timedelta(days=1)
        if created_to is not None
        else None
    )
    items = list_memos(
        session,
        user_id,
        memo_type=memo_type,
        query_text=query_text,
        resource_category=resource_category,
        resource_kind=resource_kind,
        resource_reading_status=resource_reading_status,
        link_health_status=normalized_health_status,
        tag=tag,
        collection=collection,
        starred=starred,
        memo_status=memo_status,
        created_from=normalized_created_from,
        created_to=normalized_created_to,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    total_count = count_memos(
        session,
        user_id,
        memo_type=memo_type,
        query_text=query_text,
        resource_category=resource_category,
        resource_kind=resource_kind,
        resource_reading_status=resource_reading_status,
        link_health_status=normalized_health_status,
        tag=tag,
        collection=collection,
        starred=starred,
        memo_status=memo_status,
        created_from=normalized_created_from,
        created_to=normalized_created_to,
    )
    return MemoListResponse(
        items=[MemoRead.model_validate(item) for item in items],
        total_count=total_count,
    )


@router.get("/memos/counts", response_model=MemoCountsResponse, tags=["memos"])
def count_memos_route(
    session: SessionDependency,
    user_id: UserDependency,
) -> MemoCountsResponse:
    """返回当前用户未删除内容的类型数量。"""

    counts = count_memos_by_type(session, user_id)
    return MemoCountsResponse(
        total_count=sum(counts.values()),
        word_count=counts[MemoType.WORD],
        resource_count=counts[MemoType.RESOURCE],
        idea_count=counts[MemoType.IDEA],
    )


@router.get(
    "/resource-categories",
    response_model=list[ResourceCategoryRead],
    tags=["resources"],
)
def list_resource_categories_route(
    session: SessionDependency,
    user_id: UserDependency,
) -> list[ResourceCategoryRead]:
    """返回系统分类和当前用户的自定义分类模板。"""

    return [
        ResourceCategoryRead.model_validate(option)
        for option in list_resource_category_options(session, user_id)
    ]


@router.post(
    "/resource-categories",
    response_model=ResourceCategoryRead,
    status_code=status.HTTP_201_CREATED,
    tags=["resources"],
)
def create_resource_category_route(
    payload: ResourceCategoryCreate,
    session: SessionDependency,
    user_id: UserDependency,
) -> ResourceCategoryRead:
    """创建当前用户的自定义网页资料分类。"""

    try:
        template = create_category_template(
            session,
            user_id,
            payload.name,
            payload.description,
        )
    except CategoryNameConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return ResourceCategoryRead(
        id=template.id,
        code=template.code,
        name=template.name,
        description=template.description,
        is_system=False,
        is_active=template.is_active,
        version=template.version,
    )


@router.patch(
    "/resource-categories/{category_id}",
    response_model=ResourceCategoryRead,
    tags=["resources"],
)
def update_resource_category_route(
    category_id: UUID,
    payload: ResourceCategoryUpdate,
    background_tasks: BackgroundTasks,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> ResourceCategoryRead:
    """更新或停用当前用户的自定义网页资料分类。"""

    try:
        template = update_category_template(
            session,
            user_id,
            str(category_id),
            payload.expected_version,
            payload.model_dump(exclude_unset=True, exclude={"expected_version"}),
        )
    except CategoryTemplateNotFoundError as error:
        raise HTTPException(status_code=404, detail="分类模板不存在") from error
    except CategoryNameConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except CategoryVersionConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": str(error)},
        ) from error
    background_tasks.add_task(
        reclassify_user_rule_resources_in_background,
        settings.database_url,
        user_id,
        settings,
    )
    return ResourceCategoryRead(
        id=template.id,
        code=template.code,
        name=template.name,
        description=template.description,
        is_system=False,
        is_active=template.is_active,
        version=template.version,
    )


@router.get(
    "/resource-category-rules",
    response_model=list[ResourceCategoryRuleRead],
    tags=["resources"],
)
def list_resource_category_rules_route(
    session: SessionDependency,
    user_id: UserDependency,
) -> list[ResourceCategoryRuleRead]:
    """返回当前用户的网页资料分类规则。"""

    return [
        resource_category_rule_read(session, user_id, rule)
        for rule in list_category_rules(session, user_id)
    ]


@router.post(
    "/resource-category-rules",
    response_model=ResourceCategoryRuleRead,
    status_code=status.HTTP_201_CREATED,
    tags=["resources"],
)
def create_resource_category_rule_route(
    payload: ResourceCategoryRuleCreate,
    background_tasks: BackgroundTasks,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> ResourceCategoryRuleRead:
    """创建规则并异步应用到已有网页资料。"""

    try:
        rule = create_category_rule(
            session,
            user_id,
            payload.name,
            payload.category_code,
            payload.match_type,
            payload.pattern,
            payload.priority,
            payload.enabled,
        )
    except CategoryCodeNotFoundError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    background_tasks.add_task(
        apply_user_category_rules_in_background,
        settings.database_url,
        user_id,
    )
    return resource_category_rule_read(session, user_id, rule)


@router.patch(
    "/resource-category-rules/{rule_id}",
    response_model=ResourceCategoryRuleRead,
    tags=["resources"],
)
def update_resource_category_rule_route(
    rule_id: UUID,
    payload: ResourceCategoryRuleUpdate,
    background_tasks: BackgroundTasks,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> ResourceCategoryRuleRead:
    """更新规则并重新处理受影响的资料。"""

    try:
        rule = update_category_rule(
            session,
            user_id,
            str(rule_id),
            payload.expected_version,
            payload.model_dump(exclude_unset=True, exclude={"expected_version"}),
        )
    except CategoryRuleNotFoundError as error:
        raise HTTPException(status_code=404, detail="分类规则不存在") from error
    except CategoryCodeNotFoundError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except CategoryVersionConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": str(error)},
        ) from error
    background_tasks.add_task(
        reclassify_user_rule_resources_in_background,
        settings.database_url,
        user_id,
        settings,
    )
    return resource_category_rule_read(session, user_id, rule)


@router.delete(
    "/resource-category-rules/{rule_id}",
    response_model=dict[str, bool],
    tags=["resources"],
)
def delete_resource_category_rule_route(
    rule_id: UUID,
    background_tasks: BackgroundTasks,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> dict[str, bool]:
    """删除规则并重新处理原先由用户规则分类的资料。"""

    try:
        delete_category_rule(session, user_id, str(rule_id))
    except CategoryRuleNotFoundError as error:
        raise HTTPException(status_code=404, detail="分类规则不存在") from error
    background_tasks.add_task(
        reclassify_user_rule_resources_in_background,
        settings.database_url,
        user_id,
        settings,
    )
    return {"deleted": True}


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

    if payload.resource_category is not None and not category_code_exists(
        session,
        user_id,
        payload.resource_category,
    ):
        raise HTTPException(status_code=422, detail="分类不存在或已停用")
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
    if "resource_category" in payload.model_fields_set:
        memo.resource_category_label = (
            category_label(session, user_id, payload.resource_category)
            if payload.resource_category is not None
            else None
        )
        session.commit()
        session.refresh(memo)
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
    memo_type: Annotated[MemoType | None, Query(alias="type")] = None,
) -> ReviewQueueResponse:
    """返回今日回顾：到期单词、未读资料和待整理灵感。"""

    items, counts = list_review_queue(
        session,
        user_id,
        limit=limit,
        memo_type=memo_type,
    )
    return ReviewQueueResponse(
        items=[MemoRead.model_validate(item) for item in items],
        word_count=counts["word_count"],
        resource_count=counts["resource_count"],
        idea_count=counts["idea_count"],
    )


@router.post(
    "/review-queue/{memo_id}/skip",
    response_model=MemoRead,
    tags=["review"],
)
def skip_review_route(
    memo_id: UUID,
    payload: ReviewSkipRequest,
    session: SessionDependency,
    user_id: UserDependency,
) -> MemoRead:
    """跳过当前回顾条目，明天之前不再出现。"""

    try:
        memo = skip_review_item(
            session,
            user_id,
            str(memo_id),
            payload.expected_version,
        )
    except MemoNotFoundError as error:
        raise HTTPException(status_code=404, detail="内容不存在") from error
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
    "/words/{memo_id}/merge",
    response_model=MemoRead,
    tags=["words"],
)
def merge_word_route(
    memo_id: UUID,
    payload: WordMergeRequest,
    session: SessionDependency,
    user_id: UserDependency,
) -> MemoRead:
    """把新语境合并进已有单词，不新建重复词形。"""

    try:
        memo = merge_word(session, user_id, str(memo_id), payload)
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
