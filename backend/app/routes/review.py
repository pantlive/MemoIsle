"""回顾队列、复习设置与英语单词（查词、导入、合并、复习反馈）。"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID, uuid4

from fastapi import (
    APIRouter,
    BackgroundTasks,
    HTTPException,
    Query,
    Request,
    status,
)
from sqlalchemy import select

from app.models import Memo
from app.review_digest_service import random_memo, weekly_summary
from app.routes.deps import SessionDependency, SettingsDependency, UserDependency
from app.schemas import (
    MemoRead,
    MemoStatus,
    MemoType,
    RandomMemoResponse,
    ReviewQueueResponse,
    ReviewSettingsResponse,
    ReviewSettingsUpdate,
    ReviewSkipRequest,
    WeeklySummaryResponse,
    WordDictionarySenseRead,
    WordImportErrorRead,
    WordImportResponse,
    WordLookupRequest,
    WordLookupResponse,
    WordMergeRequest,
    WordReviewRequest,
)
from app.service import (
    MemoNotFoundError,
    MemoTypeError,
    MemoVersionConflictError,
    WordDuplicateError,
    create_memo,
    get_review_settings,
    list_review_queue,
    merge_word,
    review_word,
    skip_review_item,
    update_review_settings,
)
from app.word_import_service import (
    MAX_WORD_IMPORT_BYTES,
    WordImportFormatError,
    WordImportTooLargeError,
    build_word_import_payload,
    is_word_record,
    parse_word_import,
)
from app.word_service import (
    WordDictionaryUnavailableError,
    enrich_word,
    enrich_word_in_background,
    lookup_word_preview,
    normalize_word_lemma,
)

router = APIRouter()


@router.get(
    "/review-settings",
    response_model=ReviewSettingsResponse,
    tags=["review"],
)
def read_review_settings_route(
    session: SessionDependency,
    user_id: UserDependency,
) -> ReviewSettingsResponse:
    """返回当前账号的自定义复习计划。"""

    daily_limit, intervals_days = get_review_settings(session, user_id)
    return ReviewSettingsResponse(
        daily_limit=daily_limit,
        intervals_days=list(intervals_days),
    )


@router.patch(
    "/review-settings",
    response_model=ReviewSettingsResponse,
    tags=["review"],
)
def update_review_settings_route(
    payload: ReviewSettingsUpdate,
    session: SessionDependency,
    user_id: UserDependency,
) -> ReviewSettingsResponse:
    """更新当前账号的自定义复习计划。"""

    daily_limit, intervals_days = update_review_settings(
        session,
        user_id,
        payload,
    )
    return ReviewSettingsResponse(
        daily_limit=daily_limit,
        intervals_days=list(intervals_days),
    )


@router.get("/review-queue", response_model=ReviewQueueResponse, tags=["review"])
def review_queue_route(
    session: SessionDependency,
    user_id: UserDependency,
    limit: Annotated[int | None, Query(ge=1, le=100)] = None,
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
        daily_limit=counts["daily_limit"],
        scheduled_count=counts["scheduled_count"],
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
    "/words/import",
    response_model=WordImportResponse,
    tags=["words"],
)
async def import_words_route(
    request: Request,
    background_tasks: BackgroundTasks,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
    file_format: Annotated[str, Query(alias="format")] = "json",
) -> WordImportResponse:
    """导入 JSON 或 CSV 单词，只保留当前账号的单词内容。"""

    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared_size = int(content_length)
        except ValueError as error:
            raise HTTPException(
                status_code=400,
                detail="Content-Length 无效",
            ) from error
        if declared_size > MAX_WORD_IMPORT_BYTES:
            raise HTTPException(status_code=413, detail="单词导入文件不能超过 5 MB")

    content = await request.body()
    try:
        records = parse_word_import(content, file_format)
    except WordImportTooLargeError as error:
        raise HTTPException(status_code=413, detail=str(error)) from error
    except WordImportFormatError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    imported_count = 0
    duplicate_count = 0
    skipped_count = 0
    failed_count = 0
    errors: list[WordImportErrorRead] = []
    for record in records:
        if not is_word_record(record):
            # 允许直接回灌完整 MemoIsle JSON/CSV，只提取其中的 word 条目。
            skipped_count += 1
            continue
        try:
            payload = build_word_import_payload(record)
        except (TypeError, ValueError) as error:
            failed_count += 1
            if len(errors) < 50:
                message = str(error).strip() or "字段校验失败"
                errors.append(
                    WordImportErrorRead(
                        row=record.row_number,
                        message=message[:200],
                    )
                )
            continue

        existing = session.scalar(
            select(Memo).where(
                Memo.user_id == user_id,
                Memo.client_id == str(payload.client_id),
            )
        )
        if existing is not None:
            if existing.type == MemoType.WORD and existing.status != MemoStatus.TRASHED:
                duplicate_count += 1
                continue
            # client_id 已被其他类型或回收站条目占用时，换用新标识继续导入。
            payload = payload.model_copy(update={"client_id": uuid4()})
        try:
            memo = create_memo(session, user_id, payload)
        except WordDuplicateError:
            duplicate_count += 1
            continue
        imported_count += 1
        if settings.word_dictionary_enabled:
            background_tasks.add_task(
                enrich_word_in_background,
                settings.database_url,
                user_id,
                memo.id,
                settings,
            )

    return WordImportResponse(
        total_count=len(records),
        imported_count=imported_count,
        duplicate_count=duplicate_count,
        skipped_count=skipped_count,
        failed_count=failed_count,
        errors=errors,
    )


@router.post(
    "/words/lookup",
    response_model=WordLookupResponse,
    tags=["words"],
)
def lookup_word_route(
    payload: WordLookupRequest,
    _user_id: UserDependency,
    settings: SettingsDependency,
) -> WordLookupResponse:
    """查询单词并返回可由用户选择的中文释义预览。"""

    lemma = normalize_word_lemma(payload.word)
    if not lemma:
        raise HTTPException(status_code=422, detail="请输入有效的英语单词或短语")
    try:
        dictionary = lookup_word_preview(lemma, settings)
    except WordDictionaryUnavailableError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    return WordLookupResponse(
        word=payload.word,
        lemma=lemma,
        phonetic=dictionary.phonetic,
        us_audio_url=dictionary.us_audio_url,
        uk_audio_url=dictionary.uk_audio_url,
        senses=[
            WordDictionarySenseRead(
                index=index,
                part_of_speech=sense.part_of_speech,
                definition=sense.definition,
                example=sense.example,
            )
            for index, sense in enumerate(dictionary.senses)
        ],
        source_name=dictionary.source_name,
        source_url=dictionary.source_url,
    )


@router.post(
    "/words/{memo_id}/dictionary",
    response_model=MemoRead,
    tags=["words"],
)
def enrich_word_route(
    memo_id: UUID,
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> MemoRead:
    """手动补全单词释义、音标、例句和英美音源。"""

    try:
        memo = enrich_word(session, user_id, str(memo_id), settings)
    except WordDictionaryUnavailableError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
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


@router.get(
    "/review/weekly-summary",
    response_model=WeeklySummaryResponse,
    tags=["review"],
)
def weekly_summary_route(
    session: SessionDependency,
    user_id: UserDependency,
) -> WeeklySummaryResponse:
    """最近七天新增了什么、复习了多少、读了多少。"""

    summary = weekly_summary(session, user_id)
    return WeeklySummaryResponse.model_validate(
        {
            **summary,
            "highlights": [
                MemoRead.model_validate(memo) for memo in summary["highlights"]
            ],
        }
    )


@router.get("/review/random", response_model=RandomMemoResponse, tags=["review"])
def random_memo_route(
    session: SessionDependency,
    user_id: UserDependency,
    memo_type: Annotated[MemoType | None, Query(alias="type")] = None,
    exclude: Annotated[list[str] | None, Query()] = None,
) -> RandomMemoResponse:
    """随机漫游：从资料库里随机抽一条，重新遇见很久没看的内容。"""

    memo = random_memo(session, user_id, memo_type=memo_type, exclude_ids=exclude)
    return RandomMemoResponse(
        item=MemoRead.model_validate(memo) if memo is not None else None,
    )
