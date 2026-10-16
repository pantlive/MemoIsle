"""当前账号的网页批量模型分类接口。"""

from datetime import UTC, datetime
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.config import Settings
from app.dependencies import get_current_user_id, get_session, get_settings
from app.resource_classification_retry import classify_service_failure
from app.resource_classification_review_service import (
    ReviewReason,
    confirm_classification_reviews,
    list_classification_reviews,
)
from app.resource_classification_service import (
    ResourceClassificationConfigurationError,
    ResourceClassificationStateError,
    classification_state,
    folder_mapping_overview,
    map_pending_folders,
    resume_classification_job,
    retry_classified_classifications,
    retry_folder_classifications,
    retry_review_classifications,
    start_classification_job,
    update_folder_override,
)
from app.schemas import (
    BookmarkFolderMappingList,
    BookmarkFolderOverrideRequest,
    ResourceClassificationReviewList,
    ResourceClassificationReviewRequest,
    ResourceClassificationReviewResult,
    ResourceClassificationState,
)

router = APIRouter(prefix="/resource-classification", tags=["resources"])
SessionDependency = Annotated[Session, Depends(get_session)]
UserDependency = Annotated[str, Depends(get_current_user_id)]
SettingsDependency = Annotated[Settings, Depends(get_settings)]


@router.get("/review", response_model=ResourceClassificationReviewList)
def list_classification_reviews_route(
    session: SessionDependency,
    user_id: UserDependency,
    query: Annotated[str, Query(max_length=200)] = "",
    reason: ReviewReason | None = None,
    candidate_code: Annotated[str | None, Query(max_length=100)] = None,
    max_confidence: Annotated[float | None, Query(ge=0, le=1)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ResourceClassificationReviewList:
    """读取本人未确定网页，支持搜索、候选、原因和置信度筛选。"""

    return list_classification_reviews(
        session,
        user_id,
        query,
        reason,
        candidate_code,
        max_confidence,
        limit,
        offset,
    )


@router.post(
    "/review/retry", response_model=ResourceClassificationState, status_code=202
)
def retry_classification_reviews_route(
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> ResourceClassificationState:
    """把待确认网页重新排队给大模型和 Jev，保留原分类直到有新结果。"""

    try:
        retry_review_classifications(session, user_id, settings)
    except ResourceClassificationConfigurationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except ResourceClassificationStateError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return classification_state(session, user_id)


@router.post("/review/confirm", response_model=ResourceClassificationReviewResult)
def confirm_classification_reviews_route(
    session: SessionDependency,
    user_id: UserDependency,
    payload: ResourceClassificationReviewRequest,
) -> ResourceClassificationReviewResult:
    """确认用户明确选择的条目，冲突或巡检异常逐项跳过。"""

    try:
        return confirm_classification_reviews(session, user_id, payload)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post(
    "/classified/retry", response_model=ResourceClassificationState, status_code=202
)
def retry_classified_classifications_route(
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> ResourceClassificationState:
    """把已完成模型分类的网页重新排队给大模型和 Jev，保留原分类直到有新结果。"""

    try:
        retry_classified_classifications(session, user_id, settings)
    except ResourceClassificationConfigurationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except ResourceClassificationStateError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return classification_state(session, user_id)


@router.get("/folders", response_model=BookmarkFolderMappingList)
def list_folder_mappings_route(
    session: SessionDependency,
    user_id: UserDependency,
) -> BookmarkFolderMappingList:
    """列出书签文件夹和标签各自对应的分类，供重新判断前确认。"""

    return folder_mapping_overview(session, user_id)


@router.post("/folders/map", response_model=BookmarkFolderMappingList)
def map_pending_folders_route(
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
    limit: Annotated[int, Query(ge=1, le=20)] = 5,
) -> BookmarkFolderMappingList:
    """让 Jev 判断几个还没判断过的文件夹或标签；界面反复调用直到全部完成。"""

    try:
        return map_pending_folders(session, user_id, settings, limit)
    except ResourceClassificationConfigurationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except (httpx.HTTPError, httpx.InvalidURL) as error:
        session.rollback()
        failure = classify_service_failure(error, datetime.now(UTC))
        raise HTTPException(status_code=502, detail=failure.message) from error


@router.put("/folders/override", response_model=BookmarkFolderMappingList)
def update_folder_override_route(
    session: SessionDependency,
    user_id: UserDependency,
    payload: BookmarkFolderOverrideRequest,
) -> BookmarkFolderMappingList:
    """手动指定文件夹对应的分类、设为不沿用，或恢复由 Jev 判断。"""

    try:
        return update_folder_override(
            session, user_id, payload.key, payload.mode, payload.category_code
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post(
    "/folders/retry",
    response_model=ResourceClassificationState,
    status_code=202,
)
def retry_folder_classifications_route(
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> ResourceClassificationState:
    """让 Jev 按书签原文件夹重新判断已导入网页，人工确认和规则保护的跳过。"""

    try:
        retry_folder_classifications(session, user_id, settings)
    except ResourceClassificationConfigurationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except ResourceClassificationStateError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return classification_state(session, user_id)


@router.get("", response_model=ResourceClassificationState)
def get_classification_state_route(
    session: SessionDependency,
    user_id: UserDependency,
) -> ResourceClassificationState:
    """读取本人网页的待分类数量和最近任务进度。"""

    return classification_state(session, user_id)


@router.post("/resume", response_model=ResourceClassificationState, status_code=202)
def resume_classification_route(
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> ResourceClassificationState:
    """继续当前账号的暂停任务，重复点击不会重建队列或重复处理。"""

    try:
        resume_classification_job(session, user_id, settings)
    except ResourceClassificationConfigurationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except ResourceClassificationStateError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return classification_state(session, user_id)


@router.post("", response_model=ResourceClassificationState, status_code=202)
def start_classification_route(
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> ResourceClassificationState:
    """仅排队未处理网页；已有任务正在运行时返回其进度。"""

    try:
        start_classification_job(session, user_id, settings)
    except ResourceClassificationConfigurationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return classification_state(session, user_id)
