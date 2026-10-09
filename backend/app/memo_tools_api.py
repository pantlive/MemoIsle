"""条目批量管理与图片整理入口。"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.dependencies import get_current_user_id, get_session, get_settings
from app.image_organization_service import (
    image_filters,
    image_organization_state,
    list_duplicate_images,
    resume_image_organization,
    start_image_organization,
)
from app.memo_batch_service import apply_memo_batch
from app.models import Memo
from app.schemas import (
    ImageDuplicateList,
    ImageOrganizationRequest,
    ImageOrganizationState,
    MemoBatchRequest,
    MemoBatchResult,
    MemoListResponse,
    MemoRead,
)
from app.service import purge_expired_trash

router = APIRouter(tags=["memos"])
SessionDependency = Annotated[Session, Depends(get_session)]
UserDependency = Annotated[str, Depends(get_current_user_id)]
SettingsDependency = Annotated[Settings, Depends(get_settings)]


@router.post("/memos/batch", response_model=MemoBatchResult)
def apply_memo_batch_route(
    payload: MemoBatchRequest,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> MemoBatchResult:
    """批量恢复不得绕过保留期，所有操作仅作用于本人明确选择的版本。"""

    purge_expired_trash(
        session,
        settings.audio_directory,
        settings.image_directory,
        settings.trash_retention_days,
        user_id=user_id,
    )
    return apply_memo_batch(session, user_id, settings, payload)


@router.get("/images/organization", response_model=ImageOrganizationState)
def get_image_organization_route(
    session: SessionDependency, user_id: UserDependency
) -> ImageOrganizationState:
    """读取本人图片整理进度与全量计数。"""

    return image_organization_state(session, user_id)


@router.post(
    "/images/organization", response_model=ImageOrganizationState, status_code=202
)
def start_image_organization_route(
    payload: ImageOrganizationRequest,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> ImageOrganizationState:
    """只排队用户明确请求的图片，不上传图像。"""

    try:
        return start_image_organization(session, user_id, settings, payload)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post(
    "/images/organization/resume",
    response_model=ImageOrganizationState,
    status_code=202,
)
def resume_image_organization_route(
    session: SessionDependency, user_id: UserDependency
) -> ImageOrganizationState:
    """从暂停位置继续图片整理。"""

    try:
        return resume_image_organization(session, user_id)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/images/duplicates", response_model=ImageDuplicateList)
def list_duplicate_images_route(
    session: SessionDependency,
    user_id: UserDependency,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=20)] = 10,
) -> ImageDuplicateList:
    """按完整文件哈希读取本人精确重复的图片组。"""

    return list_duplicate_images(session, user_id, offset, limit)


@router.get("/images/duplicates/{image_hash}", response_model=MemoListResponse)
def list_duplicate_image_group_route(
    image_hash: str,
    session: SessionDependency,
    user_id: UserDependency,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> MemoListResponse:
    """大重复组也支持完整分页，当前账号以外的图片不可见。"""

    filters = (*image_filters(user_id), Memo.image_hash == image_hash)
    total = session.scalar(select(func.count()).select_from(Memo).where(*filters)) or 0
    rows = session.scalars(
        select(Memo)
        .where(*filters)
        .order_by(Memo.created_at, Memo.id)
        .offset(offset)
        .limit(limit)
    ).all()
    return MemoListResponse(
        items=[MemoRead.model_validate(row) for row in rows], total_count=total
    )
