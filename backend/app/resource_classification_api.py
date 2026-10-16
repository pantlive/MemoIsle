"""当前账号的网页批量模型分类接口。"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.config import Settings
from app.dependencies import get_current_user_id, get_session, get_settings
from app.resource_classification_review_service import (
    ReviewReason,
    confirm_classification_reviews,
    list_classification_reviews,
)
from app.resource_classification_service import (
    ResourceClassificationConfigurationError,
    ResourceClassificationStateError,
    classification_state,
    resume_classification_job,
    retry_classified_classifications,
    retry_folder_classifications,
    retry_review_classifications,
    start_classification_job,
)
from app.schemas import (
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


@router.post("/review/retry", response_model=ResourceClassificationState, status_code=202)
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


@router.post("/classified/retry", response_model=ResourceClassificationState, status_code=202)
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
