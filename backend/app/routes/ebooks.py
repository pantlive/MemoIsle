"""云盘绑定与电子书转存任务。"""

from __future__ import annotations

from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    HTTPException,
    status,
)

from app.cloud_account_service import (
    CloudAccountExistsError,
    CloudAccountNotFoundError,
    CloudCredentialRejectedError,
    create_cloud_account,
    delete_cloud_account,
    list_cloud_accounts,
    verify_cloud_account,
)
from app.cloud_drive import UnsupportedProviderError
from app.ebook_service import (
    EbookJobNotFoundError,
    EbookJobStateError,
    EbookLinkError,
    create_ebook_job,
    get_ebook_job,
    list_ebook_jobs,
    process_ebook_job_in_background,
    retry_ebook_job,
)
from app.routes.deps import SessionDependency, SettingsDependency, UserDependency
from app.schemas import (
    CloudAccountCreate,
    CloudAccountRead,
    EbookJobCreate,
    EbookJobRead,
)

router = APIRouter()


@router.get(
    "/cloud-accounts",
    response_model=list[CloudAccountRead],
    tags=["cloud"],
)
def list_cloud_accounts_route(
    session: SessionDependency,
    user_id: UserDependency,
) -> list[CloudAccountRead]:
    """返回当前用户已绑定的云盘账号。"""

    return [
        CloudAccountRead.model_validate(account)
        for account in list_cloud_accounts(session, user_id)
    ]


@router.post(
    "/cloud-accounts",
    response_model=CloudAccountRead,
    status_code=status.HTTP_201_CREATED,
    tags=["cloud"],
)
def create_cloud_account_route(
    payload: CloudAccountCreate,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> CloudAccountRead:
    """绑定云盘账号：先校验凭据，再加密保存。"""

    try:
        account = create_cloud_account(
            session,
            user_id,
            provider=payload.provider.value,
            credential=payload.credential,
            default_folder=payload.default_folder,
            settings=settings,
        )
    except CloudAccountExistsError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except (CloudCredentialRejectedError, UnsupportedProviderError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return CloudAccountRead.model_validate(account)


@router.delete(
    "/cloud-accounts/{account_id}",
    response_model=dict[str, bool],
    tags=["cloud"],
)
def delete_cloud_account_route(
    account_id: UUID,
    session: SessionDependency,
    user_id: UserDependency,
) -> dict[str, bool]:
    """解绑云盘账号。"""

    try:
        delete_cloud_account(session, user_id, str(account_id))
    except CloudAccountNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return {"deleted": True}


@router.post(
    "/cloud-accounts/{account_id}/verify",
    response_model=CloudAccountRead,
    tags=["cloud"],
)
def verify_cloud_account_route(
    account_id: UUID,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> CloudAccountRead:
    """重新校验云盘凭据并刷新状态。"""

    try:
        account = verify_cloud_account(
            session,
            user_id,
            str(account_id),
            settings=settings,
        )
    except CloudAccountNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except CloudCredentialRejectedError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return CloudAccountRead.model_validate(account)


@router.get(
    "/ebooks/jobs",
    response_model=list[EbookJobRead],
    tags=["ebooks"],
)
def list_ebook_jobs_route(
    session: SessionDependency,
    user_id: UserDependency,
) -> list[EbookJobRead]:
    """返回当前用户最近的电子书任务。"""

    return [
        EbookJobRead.model_validate(job) for job in list_ebook_jobs(session, user_id)
    ]


@router.post(
    "/ebooks/jobs",
    response_model=EbookJobRead,
    status_code=status.HTTP_201_CREATED,
    tags=["ebooks"],
)
def create_ebook_job_route(
    payload: EbookJobCreate,
    background_tasks: BackgroundTasks,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> EbookJobRead:
    """提交电子书链接，并立刻在后台开始转存或下载上传。"""

    try:
        job = create_ebook_job(
            session,
            user_id,
            url=payload.url,
            settings=settings,
            provider=payload.provider.value if payload.provider else None,
            share_password=payload.share_password,
            target_folder=payload.target_folder,
            tags=payload.tags,
            collections=payload.collections,
            note=payload.note,
        )
    except EbookLinkError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    background_tasks.add_task(
        process_ebook_job_in_background,
        settings.database_url,
        user_id,
        job.id,
        settings,
    )
    return EbookJobRead.model_validate(job)


@router.get(
    "/ebooks/jobs/{job_id}",
    response_model=EbookJobRead,
    tags=["ebooks"],
)
def read_ebook_job_route(
    job_id: UUID,
    session: SessionDependency,
    user_id: UserDependency,
) -> EbookJobRead:
    """查询单个电子书任务进度。"""

    try:
        job = get_ebook_job(session, user_id, str(job_id))
    except EbookJobNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return EbookJobRead.model_validate(job)


@router.post(
    "/ebooks/jobs/{job_id}/retry",
    response_model=EbookJobRead,
    tags=["ebooks"],
)
def retry_ebook_job_route(
    job_id: UUID,
    background_tasks: BackgroundTasks,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> EbookJobRead:
    """重试失败的电子书任务。"""

    try:
        job = retry_ebook_job(session, user_id, str(job_id))
    except EbookJobNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except EbookJobStateError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    background_tasks.add_task(
        process_ebook_job_in_background,
        settings.database_url,
        user_id,
        job.id,
        settings,
    )
    return EbookJobRead.model_validate(job)
