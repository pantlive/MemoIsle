"""条目的增删改查、回收站、增量同步、录音/图片附件、会议摘要与 TTS。"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from fastapi.responses import FileResponse
from sqlalchemy import select

from app.category_service import (
    CategoryCodeNotFoundError,
    category_code_exists,
    category_label,
)
from app.config import normalize_image_ocr_provider
from app.image_ocr_service import (
    mark_image_ocr_pending,
    process_image_ocr_in_background,
    recognize_image_ocr,
)
from app.meeting_service import (
    MeetingSummaryNotConfiguredError,
    MeetingSummaryUnavailableError,
    summarize_meeting,
)
from app.memo_deletion_service import sync_change_page
from app.models import MemoDeletion
from app.resource_service import (
    enrich_resource_in_background,
)
from app.routes.deps import SessionDependency, SettingsDependency, UserDependency
from app.schemas import (
    AuthActionResponse,
    LinkHealthStatus,
    MeetingSummaryRequest,
    MeetingSummaryResponse,
    MemoCountsResponse,
    MemoCreate,
    MemoListResponse,
    MemoRead,
    MemoSort,
    MemoStatus,
    MemoType,
    MemoUpdate,
    ResourceKind,
    ResourceReadingStatus,
    SpeechTtsRequest,
    SyncResponse,
)
from app.service import (
    IMAGE_DUPLICATE_HEADER,
    MAX_IMAGE_BYTES,
    AudioValidationError,
    ImageValidationError,
    MemoNotFoundError,
    MemoNotTrashedError,
    MemoTypeError,
    MemoVersionConflictError,
    ResourceDuplicateError,
    WordDuplicateError,
    attach_audio,
    attach_image,
    audio_download_filename,
    count_memos,
    count_memos_by_type,
    create_memo,
    empty_trash,
    find_image_duplicate,
    get_audio_path,
    get_image_path,
    get_memo,
    is_trash_expired,
    list_memos,
    move_memo_to_trash,
    permanently_delete_memo,
    purge_expired_trash,
    restore_all_trash,
    restore_memo,
    update_memo,
)
from app.speech_service import (
    SpeechServiceUnavailableError,
    SpeechTextTooLongError,
    synthesize_speech,
)
from app.word_service import (
    enrich_word_in_background,
)

router = APIRouter()


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

    if (
        session.scalar(
            select(MemoDeletion.memo_id).where(
                MemoDeletion.user_id == user_id,
                MemoDeletion.client_id == str(payload.client_id),
            )
        )
        is not None
    ):
        raise HTTPException(
            status_code=410,
            detail="该条目已永久删除，请使用新的收藏标识",
        )
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
    except ResourceDuplicateError as error:
        current = MemoRead.model_validate(error.current)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": str(error),
                "code": "duplicate_resource",
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
    if memo.type == MemoType.WORD and settings.word_dictionary_enabled:
        background_tasks.add_task(
            enrich_word_in_background,
            settings.database_url,
            user_id,
            memo.id,
            settings,
        )
    return MemoRead.model_validate(memo)


@router.get("/memos", response_model=MemoListResponse, tags=["memos"])
def list_memos_route(
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
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

    if memo_status == MemoStatus.TRASHED:
        purge_expired_trash(
            session,
            settings.audio_directory,
            settings.image_directory,
            settings.trash_retention_days,
            user_id=user_id,
        )
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
        image_count=counts[MemoType.IMAGE],
        inbox_count=count_memos(session, user_id, memo_status=MemoStatus.INBOX),
    )


@router.delete(
    "/memos/trash",
    tags=["memos"],
)
def empty_trash_route(
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> dict[str, int]:
    """清空当前用户的回收站，返回永久删除的条目数。"""

    deleted = empty_trash(
        session,
        user_id,
        settings.audio_directory,
        settings.image_directory,
    )
    return {"deleted_count": deleted}


@router.post("/memos/trash/restore", tags=["memos"])
def restore_all_trash_route(
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> dict[str, int]:
    """还原当前账号的全部回收站条目，遵循已有保留期限。"""

    purge_expired_trash(
        session,
        settings.audio_directory,
        settings.image_directory,
        settings.trash_retention_days,
        user_id=user_id,
    )
    return {"restored_count": restore_all_trash(session, user_id)}


@router.get("/memos/{memo_id}", response_model=MemoRead, tags=["memos"])
def get_memo_route(
    memo_id: UUID,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> MemoRead:
    """读取一条内容。"""

    try:
        memo = get_memo(session, user_id, str(memo_id))
    except MemoNotFoundError as error:
        raise HTTPException(status_code=404, detail="条目不存在") from error
    if is_trash_expired(memo, settings.trash_retention_days):
        permanently_delete_memo(
            session,
            user_id,
            memo.id,
            memo.version,
            settings.audio_directory,
            settings.image_directory,
        )
        raise HTTPException(status_code=404, detail="条目不存在")
    return MemoRead.model_validate(memo)


@router.patch("/memos/{memo_id}", response_model=MemoRead, tags=["memos"])
def update_memo_route(
    memo_id: UUID,
    payload: MemoUpdate,
    background_tasks: BackgroundTasks,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> MemoRead:
    """更新条目并检测跨设备版本冲突。"""

    category_codes = payload.resource_categories
    if category_codes is None and payload.resource_category is not None:
        category_codes = [payload.resource_category]
    if category_codes:
        try:
            for code in category_codes:
                if not category_code_exists(session, user_id, code):
                    raise CategoryCodeNotFoundError("分类不存在或已停用")
        except CategoryCodeNotFoundError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
    try:
        memo = update_memo(session, user_id, str(memo_id), payload)
    except MemoNotFoundError as error:
        raise HTTPException(status_code=404, detail="条目不存在") from error
    except MemoTypeError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
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
    except MemoVersionConflictError as error:
        current = MemoRead.model_validate(error.current)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": str(error), "current": current.model_dump(mode="json")},
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
    if "resource_category" in payload.model_fields_set:
        memo.resource_category_label = (
            category_label(session, user_id, payload.resource_category)
            if payload.resource_category is not None
            else None
        )
        session.commit()
        session.refresh(memo)
    return MemoRead.model_validate(memo)


@router.delete("/memos/{memo_id}", response_model=MemoRead, tags=["memos"])
def trash_memo_route(
    memo_id: UUID,
    session: SessionDependency,
    user_id: UserDependency,
    expected_version: Annotated[int, Query(ge=1)],
) -> MemoRead:
    """把条目移入回收站。"""

    try:
        memo = move_memo_to_trash(
            session,
            user_id,
            str(memo_id),
            expected_version,
        )
    except MemoNotFoundError as error:
        raise HTTPException(status_code=404, detail="条目不存在") from error
    except MemoVersionConflictError as error:
        current = MemoRead.model_validate(error.current)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": str(error), "current": current.model_dump(mode="json")},
        ) from error
    return MemoRead.model_validate(memo)


@router.post("/memos/{memo_id}/restore", response_model=MemoRead, tags=["memos"])
def restore_memo_route(
    memo_id: UUID,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
    expected_version: Annotated[int, Query(ge=1)],
) -> MemoRead:
    """从回收站恢复条目。"""

    purge_expired_trash(
        session,
        settings.audio_directory,
        settings.image_directory,
        settings.trash_retention_days,
        user_id=user_id,
    )
    try:
        memo = restore_memo(
            session,
            user_id,
            str(memo_id),
            expected_version,
        )
    except MemoNotFoundError as error:
        raise HTTPException(status_code=404, detail="条目不存在") from error
    except MemoNotTrashedError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except MemoVersionConflictError as error:
        current = MemoRead.model_validate(error.current)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": str(error), "current": current.model_dump(mode="json")},
        ) from error
    return MemoRead.model_validate(memo)


@router.delete(
    "/memos/{memo_id}/permanent",
    response_model=AuthActionResponse,
    tags=["memos"],
)
def permanently_delete_memo_route(
    memo_id: UUID,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
    expected_version: Annotated[int, Query(ge=1)],
) -> AuthActionResponse:
    """永久删除回收站中的条目，需要客户端二次确认后调用。"""

    purge_expired_trash(
        session,
        settings.audio_directory,
        settings.image_directory,
        settings.trash_retention_days,
        user_id=user_id,
    )
    try:
        permanently_delete_memo(
            session,
            user_id,
            str(memo_id),
            expected_version,
            settings.audio_directory,
            settings.image_directory,
        )
    except MemoNotFoundError as error:
        raise HTTPException(status_code=404, detail="条目不存在") from error
    except MemoNotTrashedError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except MemoVersionConflictError as error:
        current = MemoRead.model_validate(error.current)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": str(error), "current": current.model_dump(mode="json")},
        ) from error
    return AuthActionResponse(status="deleted")


@router.get("/sync/changes", response_model=SyncResponse, tags=["sync"])
def sync_changes_route(
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
    cursor: Annotated[datetime | None, Query()] = None,
    cursor_id: Annotated[UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> SyncResponse:
    """按服务端更新时间返回增量同步数据。"""

    purge_expired_trash(
        session,
        settings.audio_directory,
        settings.image_directory,
        settings.trash_retention_days,
        user_id=user_id,
    )
    return sync_change_page(
        session,
        user_id,
        cursor,
        str(cursor_id) if cursor_id else None,
        limit,
    )


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
    inline: Annotated[bool, Query()] = False,
) -> FileResponse:
    """下载当前用户的一条录音；显式要求在线播放时返回 inline。"""

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
        # 默认按附件下载；客户端需要在线播放时可传 inline=true。
        filename=audio_download_filename(memo),
        content_disposition_type="inline" if inline else "attachment",
    )


@router.post("/memos/{memo_id}/image", response_model=MemoRead, tags=["image"])
async def upload_memo_image_route(
    memo_id: UUID,
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
    expected_version: Annotated[int, Query(ge=1)],
) -> MemoRead:
    """接收原始图片字节并关联到一条图片收藏。"""

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
        if declared_size > MAX_IMAGE_BYTES:
            raise HTTPException(status_code=413, detail="图片不能超过 20 MB")
    content = await request.body()
    try:
        memo = attach_image(
            session=session,
            user_id=user_id,
            memo_id=str(memo_id),
            expected_version=expected_version,
            content=content,
            mime_type=content_type,
            image_directory=settings.image_directory,
        )
    except MemoNotFoundError as error:
        raise HTTPException(status_code=404, detail="图片收藏不存在") from error
    except (MemoTypeError, ImageValidationError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except MemoVersionConflictError as error:
        current = MemoRead.model_validate(error.current)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": str(error), "current": current.model_dump(mode="json")},
        ) from error
    duplicate = find_image_duplicate(session, user_id, memo)
    if duplicate is not None:
        # 客户端据此提示「这张图片已经收藏过」，并可跳到已有条目。
        response.headers[IMAGE_DUPLICATE_HEADER] = duplicate.id
    if (
        normalize_image_ocr_provider(settings.image_ocr_provider) != "none"
        # 已从相同图片复用了识别结果时不再排队识别。
        and memo.image_ocr_status != "ready"
    ):
        # 图片落盘后再在后台识别；识别失败不影响图片本身已经保存。
        mark_image_ocr_pending(session, memo)
        background_tasks.add_task(
            process_image_ocr_in_background,
            settings.database_url,
            user_id,
            memo.id,
            settings,
        )
    return MemoRead.model_validate(memo)


@router.get("/memos/{memo_id}/image", tags=["image"])
def download_memo_image_route(
    memo_id: UUID,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> FileResponse:
    """查看当前用户图片收藏的原图。"""

    try:
        memo, image_path = get_image_path(
            session,
            user_id,
            str(memo_id),
            settings.image_directory,
        )
    except MemoNotFoundError as error:
        raise HTTPException(status_code=404, detail="图片不存在") from error
    except MemoTypeError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return FileResponse(
        path=image_path,
        media_type=memo.image_mime_type or "application/octet-stream",
        filename=f"memoisle-{memo.id}.image",
        content_disposition_type="inline",
    )


@router.get("/memos/{memo_id}/image/thumbnail", tags=["image"])
def download_memo_image_thumbnail_route(
    memo_id: UUID,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> FileResponse:
    """查看当前用户图片收藏的缩略图。"""

    try:
        memo, image_path = get_image_path(
            session,
            user_id,
            str(memo_id),
            settings.image_directory,
            thumbnail=True,
        )
    except MemoNotFoundError as error:
        raise HTTPException(status_code=404, detail="缩略图不存在") from error
    except MemoTypeError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return FileResponse(
        path=image_path,
        media_type="image/webp",
        filename=f"memoisle-{memo.id}.thumbnail.webp",
        content_disposition_type="inline",
    )


@router.post(
    "/memos/{memo_id}/image/ocr",
    response_model=MemoRead,
    tags=["image"],
)
def recognize_image_ocr_route(
    memo_id: UUID,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> MemoRead:
    """手动重试图片文字识别与自动标签。"""

    if normalize_image_ocr_provider(settings.image_ocr_provider) == "none":
        raise HTTPException(
            status_code=503,
            detail="服务端未启用图片 OCR（MEMOISLE_IMAGE_OCR_PROVIDER）",
        )
    try:
        memo = recognize_image_ocr(session, user_id, str(memo_id), settings)
    except MemoNotFoundError as error:
        raise HTTPException(status_code=404, detail="图片不存在") from error
    except MemoTypeError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return MemoRead.model_validate(memo)


@router.post(
    "/meeting/summary",
    response_model=MeetingSummaryResponse,
    tags=["meeting"],
)
def summarize_meeting_route(
    payload: MeetingSummaryRequest,
    _user_id: UserDependency,
    settings: SettingsDependency,
) -> MeetingSummaryResponse:
    """根据会议转写生成结构化会议纪要。"""

    try:
        summary = summarize_meeting(
            transcript=payload.transcript,
            title=payload.title,
            settings=settings,
        )
    except MeetingSummaryNotConfiguredError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except MeetingSummaryUnavailableError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    return MeetingSummaryResponse(summary=summary)


@router.post("/speech/tts", tags=["speech"])
def synthesize_speech_route(
    payload: SpeechTtsRequest,
    _user_id: UserDependency,
    settings: SettingsDependency,
) -> FileResponse:
    """使用可选的 sanoTTS 服务生成私有语音。"""

    try:
        audio_path = synthesize_speech(
            text=payload.text,
            settings=settings,
            voice=payload.voice,
        )
    except SpeechTextTooLongError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except SpeechServiceUnavailableError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return FileResponse(
        path=audio_path,
        media_type="audio/wav",
        filename="memoisle-speech.wav",
        content_disposition_type="inline",
    )
