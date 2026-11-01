"""网页资料：元数据补全、链接巡检、快速访问、书签导入、分类与分类规则。"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    HTTPException,
    Query,
    status,
)
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
from app.category_generation_service import (
    CategoryGenerationNotConfiguredError,
    CategoryGenerationUnavailableError,
    generate_category_suggestions,
)
from app.category_service import (
    CategoryCodeNotFoundError,
    CategoryNameConflictError,
    CategoryParentError,
    CategoryRuleNotFoundError,
    CategoryTemplateNotFoundError,
    CategoryVersionConflictError,
    category_label,
    category_template_to_option,
    create_category_rule,
    create_category_template,
    delete_category_rule,
    delete_category_template,
    library_pages_for_generation,
    list_category_rules,
    list_resource_category_options,
    update_category_rule,
    update_category_template,
)
from app.link_health_service import (
    apply_link_health_action,
    check_resource_link,
    get_link_health_settings,
    list_link_health_center,
    update_link_health_settings,
    update_link_health_site_pause,
)
from app.model_settings_service import resolve_model_settings
from app.models import ResourceCategoryRule
from app.resource_service import (
    apply_user_category_rules_in_background,
    enrich_resource,
    reclassify_user_rule_resources_in_background,
)
from app.routes.deps import SessionDependency, SettingsDependency, UserDependency
from app.schemas import (
    BookmarkImportBatchRead,
    BookmarkImportPreview,
    BookmarkImportRequest,
    LinkHealthActionRequest,
    LinkHealthListResponse,
    LinkHealthSettingsUpdate,
    LinkHealthSitePauseRequest,
    LinkHealthStatus,
    MemoRead,
    ResourceCategoryCreate,
    ResourceCategoryGenerateRequest,
    ResourceCategoryGenerateResponse,
    ResourceCategoryRead,
    ResourceCategoryRuleCreate,
    ResourceCategoryRuleRead,
    ResourceCategoryRuleUpdate,
    ResourceCategoryUpdate,
    ResourceOpenRead,
    ResourceQuickAccessRead,
    ResourceQuickAccessUpdate,
)
from app.service import (
    MemoNotFoundError,
    MemoTypeError,
    MemoVersionConflictError,
    list_quick_access,
    record_resource_open,
    set_resource_quick_access_hidden,
)

router = APIRouter()


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
    settings: SettingsDependency,
    health_status: Annotated[
        LinkHealthStatus | None,
        Query(alias="status"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> LinkHealthListResponse:
    """读取失效、重定向、变化和暂时失败的网页资料。"""

    items, counts = list_link_health_center(
        session,
        user_id,
        health_status,
        limit,
        offset=offset,
    )
    return LinkHealthListResponse(
        items=[MemoRead.model_validate(item) for item in items],
        counts=counts,
        settings=get_link_health_settings(session, user_id, settings),
    )


@router.patch(
    "/resources/link-health/settings",
    response_model=LinkHealthListResponse,
    tags=["resources"],
)
def update_link_health_settings_route(
    payload: LinkHealthSettingsUpdate,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> LinkHealthListResponse:
    """更新账号级巡检设置并返回最新巡检中心。"""

    try:
        health_settings = update_link_health_settings(
            session,
            user_id,
            payload,
            settings,
        )
    except MemoNotFoundError as error:
        raise HTTPException(status_code=404, detail="账号不存在") from error
    items, counts = list_link_health_center(session, user_id)
    return LinkHealthListResponse(
        items=[MemoRead.model_validate(item) for item in items],
        counts=counts,
        settings=health_settings,
    )


@router.post(
    "/resources/link-health/site-pauses",
    response_model=LinkHealthListResponse,
    tags=["resources"],
)
def update_link_health_site_pause_route(
    payload: LinkHealthSitePauseRequest,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> LinkHealthListResponse:
    """暂停或恢复当前账号下某个网站的巡检。"""

    health_settings = update_link_health_site_pause(
        session,
        user_id,
        payload,
        settings,
    )
    items, counts = list_link_health_center(session, user_id)
    return LinkHealthListResponse(
        items=[MemoRead.model_validate(item) for item in items],
        counts=counts,
        settings=health_settings,
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
    "/resource-categories/generate",
    response_model=ResourceCategoryGenerateResponse,
    tags=["resources"],
)
def generate_resource_categories_route(
    payload: ResourceCategoryGenerateRequest,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> ResourceCategoryGenerateResponse:
    """根据整理要求和收藏网页聚类，生成当前用户可添加的分类建议。"""

    existing = [
        ResourceCategoryRead.model_validate(option)
        for option in list_resource_category_options(session, user_id)
    ]
    library_pages = library_pages_for_generation(session, user_id)
    if not payload.instructions and not library_pages:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="请说明整理要求，或先收藏网页后再根据网页聚类",
        )
    try:
        return generate_category_suggestions(
            payload.instructions,
            existing,
            resolve_model_settings(session, user_id, settings),
            payload.max_categories,
            library_pages=library_pages,
            mode=payload.mode,
        )
    except CategoryGenerationNotConfiguredError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except CategoryGenerationUnavailableError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


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
            payload.parent_code,
            definition=payload.definition,
            include_examples=payload.include_examples,
            exclude_examples=payload.exclude_examples,
        )
    except CategoryNameConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except CategoryParentError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return ResourceCategoryRead.model_validate(
        category_template_to_option(session, user_id, template),
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
    except CategoryParentError as error:
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
    return ResourceCategoryRead.model_validate(
        category_template_to_option(session, user_id, template),
    )


@router.delete(
    "/resource-categories/{category_id}",
    response_model=dict[str, bool],
    tags=["resources"],
)
def delete_resource_category_route(
    category_id: UUID,
    background_tasks: BackgroundTasks,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> dict[str, bool]:
    """删除自定义分类模板，并重新判断原先使用该分类的资料。"""

    try:
        delete_category_template(session, user_id, str(category_id))
    except CategoryTemplateNotFoundError as error:
        raise HTTPException(status_code=404, detail="分类模板不存在") from error
    background_tasks.add_task(
        apply_user_category_rules_in_background,
        settings.database_url,
        user_id,
    )
    return {"deleted": True}


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


@router.post(
    "/resources/{memo_id}/open",
    response_model=ResourceOpenRead,
    tags=["resources"],
)
def record_resource_open_route(
    memo_id: UUID,
    session: SessionDependency,
    user_id: UserDependency,
) -> ResourceOpenRead:
    """记录一次打开原网页，用于快速访问排序。"""

    try:
        memo = record_resource_open(session, user_id, str(memo_id))
    except MemoNotFoundError as error:
        raise HTTPException(status_code=404, detail="条目不存在") from error
    except MemoTypeError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return ResourceOpenRead(
        resource_open_count=memo.resource_open_count,
        resource_last_opened_at=memo.resource_last_opened_at,
    )


@router.get(
    "/resources/quick-access",
    response_model=list[MemoRead],
    tags=["resources"],
)
def list_quick_access_route(
    session: SessionDependency,
    user_id: UserDependency,
    limit: Annotated[int, Query(ge=1, le=50)] = 8,
) -> list[MemoRead]:
    """快速访问：按打开次数排列常用网页，已移除的不出现。"""

    return [
        MemoRead.model_validate(memo)
        for memo in list_quick_access(session, user_id, limit)
    ]


@router.put(
    "/resources/{memo_id}/quick-access",
    response_model=ResourceQuickAccessRead,
    tags=["resources"],
)
def update_quick_access_route(
    memo_id: UUID,
    payload: ResourceQuickAccessUpdate,
    session: SessionDependency,
    user_id: UserDependency,
) -> ResourceQuickAccessRead:
    """从快速访问移除，或重新显示。"""

    try:
        memo = set_resource_quick_access_hidden(
            session, user_id, str(memo_id), payload.hidden,
        )
    except MemoNotFoundError as error:
        raise HTTPException(status_code=404, detail="条目不存在") from error
    except MemoTypeError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return ResourceQuickAccessRead(
        resource_quick_access_hidden=memo.resource_quick_access_hidden,
    )
