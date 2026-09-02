"""条目业务逻辑。"""

from __future__ import annotations

import json
import unicodedata
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from sqlalchemy import Select, String, cast, func, or_, select
from sqlalchemy.orm import Session

from app.models import Memo
from app.schemas import (
    MemoCreate,
    MemoSort,
    MemoStatus,
    MemoType,
    MemoUpdate,
    ResourceKind,
    ResourceProcessStatus,
    ResourceReadingStatus,
    ReviewFeedback,
    WordMergeRequest,
    WordReviewRequest,
)
from app.url_normalization import canonicalize_resource_url


class MemoNotFoundError(LookupError):
    """条目不存在或不属于当前用户。"""


class MemoVersionConflictError(RuntimeError):
    """客户端版本落后于服务端。"""

    def __init__(self, current: Memo) -> None:
        super().__init__("条目已在其他设备更新")
        self.current = current


class MemoTypeError(ValueError):
    """请求的操作与条目类型不匹配。"""


class WordDuplicateError(RuntimeError):
    """规范化词形已经存在。"""

    def __init__(self, current: Memo) -> None:
        super().__init__("已收藏相同词形")
        self.current = current


class AudioValidationError(ValueError):
    """录音内容或类型不符合上传约束。"""


MAX_AUDIO_BYTES = 20 * 1024 * 1024
ALLOWED_AUDIO_TYPES = {
    "audio/mp4",
    "audio/mpeg",
    "audio/ogg",
    "audio/webm",
    "audio/x-m4a",
}


def normalize_lemma(value: str) -> str:
    """把英语词形规范为可比较的小写形式。"""

    folded = unicodedata.normalize("NFKC", value).casefold().strip()
    return " ".join(folded.split())


def append_unique_text(existing: str | None, incoming: str | None) -> str | None:
    """把新文本追加到已有内容，重复片段不重复保存。"""

    addition = (incoming or "").strip()
    if not addition:
        return existing
    current = (existing or "").strip()
    if not current:
        return addition
    if addition.casefold() in current.casefold():
        return current
    return f"{current}\n{addition}"


def escape_like_pattern(value: str) -> str:
    """转义 SQL LIKE 查询中的通配符。"""

    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def build_title(
    title: str | None,
    body: str,
    source_title: str | None = None,
    source_url: str | None = None,
) -> str:
    """优先使用显式标题，否则从正文第一行生成。"""

    if title and title.strip():
        return title.strip()
    if source_title and source_title.strip():
        return source_title.strip()
    if source_url:
        hostname = urlsplit(source_url).hostname
        if hostname:
            return hostname.removeprefix("www.")
    first_line = next(
        (line.strip() for line in body.splitlines() if line.strip()),
        "灵感",
    )
    if len(first_line) <= 80:
        return first_line
    return f"{first_line[:77]}..."


def create_memo(session: Session, user_id: str, payload: MemoCreate) -> Memo:
    """幂等创建一条收藏内容。"""

    existing = session.scalar(
        select(Memo).where(
            Memo.user_id == user_id,
            Memo.client_id == str(payload.client_id),
        )
    )
    if existing is not None:
        return existing

    if payload.type == MemoType.RESOURCE and payload.source_url is not None:
        # 相同规范网址只保留一份资料，避免扩展和手动收藏产生重复项。
        try:
            normalized_url = canonicalize_resource_url(payload.source_url)
        except ValueError:
            normalized_url = None
        if normalized_url is not None:
            resources = session.scalars(
                select(Memo).where(
                    Memo.user_id == user_id,
                    Memo.type == MemoType.RESOURCE,
                    Memo.status != MemoStatus.TRASHED,
                    Memo.source_url.is_not(None),
                )
            ).all()
            for resource in resources:
                try:
                    if (
                        canonicalize_resource_url(resource.source_url or "")
                        == normalized_url
                    ):
                        return resource
                except ValueError:
                    # 历史异常网址不影响当前收藏。
                    continue

    if payload.type == MemoType.WORD:
        lemma = normalize_lemma(payload.title or "")
        existing_word = session.scalar(
            select(Memo).where(
                Memo.user_id == user_id,
                Memo.type == MemoType.WORD,
                Memo.status != MemoStatus.TRASHED,
                Memo.normalized_lemma == lemma,
            )
        )
        if existing_word is not None and not payload.allow_duplicate:
            raise WordDuplicateError(existing_word)

    now = datetime.now(UTC)
    memo = Memo(
        id=str(uuid4()),
        user_id=user_id,
        client_id=str(payload.client_id),
        type=payload.type,
        title=build_title(
            payload.title,
            payload.body,
            payload.source_title,
            payload.source_url,
        ),
        body=payload.body,
        source_url=payload.source_url,
        source_title=payload.source_title,
        resource_metadata_status=(
            ResourceProcessStatus.PENDING
            if payload.type == MemoType.RESOURCE
            else ResourceProcessStatus.NONE
        ),
        resource_category_status=(
            ResourceProcessStatus.PENDING
            if payload.type == MemoType.RESOURCE
            else ResourceProcessStatus.NONE
        ),
        resource_kind=(
            payload.resource_kind or ResourceKind.OTHER
            if payload.type == MemoType.RESOURCE
            else None
        ),
        resource_reading_status=(
            payload.resource_reading_status or ResourceReadingStatus.UNREAD
            if payload.type == MemoType.RESOURCE
            else None
        ),
        resource_title_user_defined=bool(payload.title or payload.source_title),
        link_health_status="unchecked",
        link_next_check_at=now if payload.type == MemoType.RESOURCE else None,
        word_phonetic=payload.word_phonetic,
        word_meaning=payload.word_meaning,
        word_example=payload.word_example,
        normalized_lemma=(
            normalize_lemma(payload.title or "")
            if payload.type == MemoType.WORD
            else None
        ),
        familiarity=0,
        review_count=0,
        next_review_at=now if payload.type == MemoType.WORD else None,
        transcript_status="none",
        tags=payload.tags,
        collections=payload.collections,
        starred=payload.starred,
        status=(
            MemoStatus.INBOX
            if payload.type == MemoType.IDEA
            else MemoStatus.ACTIVE
        ),
        version=1,
    )
    session.add(memo)
    session.commit()
    session.refresh(memo)
    return memo


def memo_query(
    user_id: str,
    memo_type: MemoType | None = None,
    updated_after: datetime | None = None,
    query_text: str | None = None,
    resource_category: str | None = None,
    resource_kind: ResourceKind | None = None,
    resource_reading_status: ResourceReadingStatus | None = None,
    link_health_status: str | None = None,
    tag: str | None = None,
    collection: str | None = None,
    starred: bool | None = None,
    memo_status: MemoStatus | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    sort: MemoSort = MemoSort.UPDATED_DESC,
    include_trashed: bool = False,
    oldest_first: bool = False,
) -> Select[tuple[Memo]]:
    """构造当前用户可见条目的查询。"""

    query = select(Memo).where(Memo.user_id == user_id)
    if memo_status is not None:
        query = query.where(Memo.status == memo_status)
    elif not include_trashed:
        query = query.where(Memo.status != MemoStatus.TRASHED)
    if memo_type is not None:
        query = query.where(Memo.type == memo_type)
    if updated_after is not None:
        query = query.where(Memo.updated_at > updated_after)
    if resource_category is not None:
        query = query.where(Memo.resource_category == resource_category)
    if resource_kind is not None:
        query = query.where(Memo.resource_kind == resource_kind)
    if resource_reading_status is not None:
        query = query.where(
            Memo.resource_reading_status == resource_reading_status,
        )
    if link_health_status is not None:
        query = query.where(Memo.link_health_status == link_health_status)
    if tag and (cleaned_tag := tag.strip()):
        # SQLite 中按 JSON 字符串的完整标签筛选，避免部分词误命中。
        escaped_tag = json.dumps(cleaned_tag, ensure_ascii=True)
        tag_pattern = f"%{escape_like_pattern(escaped_tag)}%"
        query = query.where(
            or_(
                cast(Memo.tags, String).ilike(tag_pattern, escape="\\"),
                cast(Memo.resource_auto_tags, String).ilike(
                    tag_pattern,
                    escape="\\",
                ),
            )
        )
    if collection and (cleaned_collection := collection.strip()):
        escaped_collection = json.dumps(cleaned_collection, ensure_ascii=True)
        collection_pattern = f"%{escape_like_pattern(escaped_collection)}%"
        query = query.where(
            cast(Memo.collections, String).ilike(collection_pattern, escape="\\")
        )
    if starred is not None:
        query = query.where(Memo.starred == starred)
    if created_from is not None:
        query = query.where(Memo.created_at >= created_from)
    if created_to is not None:
        query = query.where(Memo.created_at < created_to)
    if query_text and (cleaned_query := query_text.strip()):
        # 同时检索三种内容类型的用户可见文本。
        pattern = f"%{escape_like_pattern(cleaned_query)}%"
        tag_text = cast(Memo.tags, String)
        auto_tag_text = cast(Memo.resource_auto_tags, String)
        # 同时匹配 JSON 原文和 Unicode 转义形式，兼容已有 SQLite 数据。
        escaped_json_query = json.dumps(cleaned_query, ensure_ascii=True)[1:-1]
        escaped_json_pattern = (
            f"%{escape_like_pattern(escaped_json_query)}%"
        )
        query = query.where(
            or_(
                Memo.title.ilike(pattern, escape="\\"),
                Memo.body.ilike(pattern, escape="\\"),
                Memo.source_url.ilike(pattern, escape="\\"),
                Memo.source_title.ilike(pattern, escape="\\"),
                Memo.resource_page_title.ilike(pattern, escape="\\"),
                Memo.resource_description.ilike(pattern, escape="\\"),
                Memo.resource_site_name.ilike(pattern, escape="\\"),
                Memo.resource_category.ilike(pattern, escape="\\"),
                Memo.resource_kind.ilike(pattern, escape="\\"),
                Memo.resource_reading_status.ilike(pattern, escape="\\"),
                Memo.resource_import_folder.ilike(pattern, escape="\\"),
                Memo.word_phonetic.ilike(pattern, escape="\\"),
                Memo.word_meaning.ilike(pattern, escape="\\"),
                Memo.word_example.ilike(pattern, escape="\\"),
                Memo.transcript.ilike(pattern, escape="\\"),
                tag_text.ilike(pattern, escape="\\"),
                tag_text.ilike(escaped_json_pattern, escape="\\"),
                auto_tag_text.ilike(pattern, escape="\\"),
                auto_tag_text.ilike(escaped_json_pattern, escape="\\"),
                cast(Memo.collections, String).ilike(pattern, escape="\\"),
                cast(Memo.collections, String).ilike(
                    escaped_json_pattern,
                    escape="\\",
                ),
            )
        )
    # 增量同步固定按正序推进游标；普通列表尊重用户选择的排序。
    if oldest_first:
        return query.order_by(Memo.updated_at.asc(), Memo.id.asc())
    sort_orders = {
        MemoSort.UPDATED_DESC: (Memo.updated_at.desc(), Memo.id.desc()),
        MemoSort.UPDATED_ASC: (Memo.updated_at.asc(), Memo.id.asc()),
        MemoSort.CREATED_DESC: (Memo.created_at.desc(), Memo.id.desc()),
        MemoSort.CREATED_ASC: (Memo.created_at.asc(), Memo.id.asc()),
        MemoSort.TITLE_ASC: (Memo.title.asc(), Memo.id.asc()),
        MemoSort.TITLE_DESC: (Memo.title.desc(), Memo.id.desc()),
    }
    return query.order_by(*sort_orders[sort])


def list_memos(
    session: Session,
    user_id: str,
    memo_type: MemoType | None = None,
    updated_after: datetime | None = None,
    query_text: str | None = None,
    resource_category: str | None = None,
    resource_kind: ResourceKind | None = None,
    resource_reading_status: ResourceReadingStatus | None = None,
    link_health_status: str | None = None,
    tag: str | None = None,
    collection: str | None = None,
    starred: bool | None = None,
    memo_status: MemoStatus | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    sort: MemoSort = MemoSort.UPDATED_DESC,
    limit: int = 100,
    offset: int = 0,
    include_trashed: bool = False,
    oldest_first: bool = False,
) -> list[Memo]:
    """读取当前用户的条目。"""

    query = memo_query(
        user_id=user_id,
        memo_type=memo_type,
        updated_after=updated_after,
        query_text=query_text,
        resource_category=resource_category,
        resource_kind=resource_kind,
        resource_reading_status=resource_reading_status,
        link_health_status=link_health_status,
        tag=tag,
        collection=collection,
        starred=starred,
        memo_status=memo_status,
        created_from=created_from,
        created_to=created_to,
        sort=sort,
        include_trashed=include_trashed,
        oldest_first=oldest_first,
    ).offset(offset).limit(limit)
    return list(session.scalars(query).all())


def count_memos(
    session: Session,
    user_id: str,
    memo_type: MemoType | None = None,
    updated_after: datetime | None = None,
    query_text: str | None = None,
    resource_category: str | None = None,
    resource_kind: ResourceKind | None = None,
    resource_reading_status: ResourceReadingStatus | None = None,
    link_health_status: str | None = None,
    tag: str | None = None,
    collection: str | None = None,
    starred: bool | None = None,
    memo_status: MemoStatus | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    include_trashed: bool = False,
) -> int:
    """统计与当前筛选条件匹配的条目总数。"""

    query = memo_query(
        user_id=user_id,
        memo_type=memo_type,
        updated_after=updated_after,
        query_text=query_text,
        resource_category=resource_category,
        resource_kind=resource_kind,
        resource_reading_status=resource_reading_status,
        link_health_status=link_health_status,
        tag=tag,
        collection=collection,
        starred=starred,
        memo_status=memo_status,
        created_from=created_from,
        created_to=created_to,
        include_trashed=include_trashed,
    ).order_by(None)
    return int(session.scalar(select(func.count()).select_from(query.subquery())) or 0)


def count_memos_by_type(session: Session, user_id: str) -> dict[MemoType, int]:
    """统计当前用户未删除的各内容类型数量。"""

    counts = {memo_type: 0 for memo_type in MemoType}
    rows = session.execute(
        select(Memo.type, func.count(Memo.id))
        .where(
            Memo.user_id == user_id,
            Memo.status != MemoStatus.TRASHED,
        )
        .group_by(Memo.type)
    )
    for memo_type, count in rows:
        counts[MemoType(memo_type)] = int(count)
    return counts


def get_memo(session: Session, user_id: str, memo_id: str) -> Memo:
    """按标识读取当前用户的一条内容。"""

    memo = session.scalar(
        select(Memo).where(Memo.id == memo_id, Memo.user_id == user_id)
    )
    if memo is None:
        raise MemoNotFoundError
    return memo


def update_memo(
    session: Session,
    user_id: str,
    memo_id: str,
    payload: MemoUpdate,
) -> Memo:
    """使用乐观版本号更新条目。"""

    memo = get_memo(session, user_id, memo_id)
    if memo.version != payload.expected_version:
        raise MemoVersionConflictError(memo)

    changes = payload.model_dump(exclude_unset=True, exclude={"expected_version"})
    previous_source_url = memo.source_url
    if memo.type == MemoType.RESOURCE and memo.resource_import_batch_id is not None:
        # 用户显式编辑后不再允许“撤销导入”批量移除该资料。
        memo.resource_import_batch_id = None
    for field_name, value in changes.items():
        setattr(memo, field_name, value)
    if "body" in changes and "title" not in changes:
        memo.title = build_title(None, memo.body)
    if memo.type == MemoType.WORD and "title" in changes:
        memo.normalized_lemma = normalize_lemma(memo.title)
    if memo.type == MemoType.RESOURCE and "title" in changes:
        memo.resource_title_user_defined = True
    if (
        memo.type == MemoType.RESOURCE
        and "resource_category" in changes
        and changes["resource_category"] is not None
    ):
        memo.resource_category_status = ResourceProcessStatus.READY
        memo.resource_category_confidence = 1.0
        memo.resource_category_source = "manual"
    if memo.type == MemoType.RESOURCE and memo.source_url != previous_source_url:
        # 修改网址后重新执行元数据、分类与健康检查。
        memo.resource_metadata_status = ResourceProcessStatus.PENDING
        memo.resource_metadata_error = None
        memo.resource_category_status = ResourceProcessStatus.PENDING
        memo.resource_category_confidence = None
        memo.resource_category_source = None
        memo.link_health_status = "unchecked"
        memo.link_health_http_status = None
        memo.link_health_error = None
        memo.link_consecutive_failures = 0
        memo.link_next_check_at = datetime.now(UTC)
        memo.link_effective_url = None
        memo.link_metadata_fingerprint = None
    memo.version += 1
    # SQLite 不会可靠执行服务端时区函数，因此在应用层统一更新时间。
    memo.updated_at = datetime.now(UTC)
    session.commit()
    session.refresh(memo)
    return memo


def _start_of_utc_day(now: datetime) -> datetime:
    """按服务端 UTC 约定计算当天零点，用于排除已经跳过或复习过的条目。"""

    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _not_reviewed_today(now: datetime):
    """今天已经跳过、复习或处理过的条目不再进入今日回顾。"""

    return or_(
        Memo.last_review_at.is_(None),
        Memo.last_review_at < _start_of_utc_day(now),
    )


def _count_review_items(session: Session, *filters: object) -> int:
    """统计满足回顾条件的条目数量。"""

    return int(session.scalar(select(func.count(Memo.id)).where(*filters)) or 0)


def _load_review_items(
    session: Session,
    *filters: object,
    order_by: tuple[object, ...],
    limit: int,
) -> list[Memo]:
    """读取一类回顾候选，条数不超过本次回顾上限。"""

    query = select(Memo).where(*filters).order_by(*order_by).limit(limit)
    return list(session.scalars(query).all())


def _interleave_review_items(*groups: list[Memo], limit: int) -> list[Memo]:
    """按单词、资料、灵感轮询混合，保证一次回顾不超过 5 至 10 条。"""

    items: list[Memo] = []
    index = 0
    while len(items) < limit:
        added = False
        for group in groups:
            if index < len(group):
                items.append(group[index])
                added = True
                if len(items) >= limit:
                    break
        if not added:
            break
        index += 1
    return items


def list_review_queue(
    session: Session,
    user_id: str,
    limit: int = 10,
    memo_type: MemoType | None = None,
) -> tuple[list[Memo], dict[str, int]]:
    """读取今日回顾：到期单词、未读资料和待整理灵感。"""

    now = datetime.now(UTC)
    not_reviewed_today = _not_reviewed_today(now)
    word_filters = (
        Memo.user_id == user_id,
        Memo.type == MemoType.WORD,
        Memo.status != MemoStatus.TRASHED,
        or_(Memo.next_review_at.is_(None), Memo.next_review_at <= now),
        not_reviewed_today,
    )
    resource_filters = (
        Memo.user_id == user_id,
        Memo.type == MemoType.RESOURCE,
        Memo.status != MemoStatus.TRASHED,
        Memo.resource_reading_status == ResourceReadingStatus.UNREAD,
        not_reviewed_today,
    )
    idea_filters = (
        Memo.user_id == user_id,
        Memo.type == MemoType.IDEA,
        Memo.status == MemoStatus.INBOX,
        not_reviewed_today,
    )
    counts = {
        "word_count": _count_review_items(session, *word_filters),
        "resource_count": _count_review_items(session, *resource_filters),
        "idea_count": _count_review_items(session, *idea_filters),
    }
    words = _load_review_items(
        session,
        *word_filters,
        order_by=(Memo.next_review_at.asc(), Memo.created_at.asc()),
        limit=limit,
    )
    resources = _load_review_items(
        session,
        *resource_filters,
        order_by=(Memo.created_at.asc(), Memo.id.asc()),
        limit=limit,
    )
    ideas = _load_review_items(
        session,
        *idea_filters,
        order_by=(Memo.created_at.asc(), Memo.id.asc()),
        limit=limit,
    )
    if memo_type == MemoType.WORD:
        items = words[:limit]
    elif memo_type == MemoType.RESOURCE:
        items = resources[:limit]
    elif memo_type == MemoType.IDEA:
        items = ideas[:limit]
    else:
        items = _interleave_review_items(words, resources, ideas, limit=limit)
    return items, counts


def skip_review_item(
    session: Session,
    user_id: str,
    memo_id: str,
    expected_version: int,
) -> Memo:
    """把当前条目移出今日回顾，不改变熟悉度或阅读进度。"""

    memo = get_memo(session, user_id, memo_id)
    if memo.version != expected_version:
        raise MemoVersionConflictError(memo)
    if memo.status == MemoStatus.TRASHED:
        raise MemoTypeError("回收站中的内容不能进入回顾")

    now = datetime.now(UTC)
    memo.last_review_at = now
    memo.version += 1
    memo.updated_at = now
    session.commit()
    session.refresh(memo)
    return memo


def merge_word(
    session: Session,
    user_id: str,
    memo_id: str,
    payload: WordMergeRequest,
) -> Memo:
    """把新的释义、例句或来源合并进已有单词。"""

    memo = get_memo(session, user_id, memo_id)
    if memo.type != MemoType.WORD:
        raise MemoTypeError("只有英语单词可以合并语境")
    if memo.version != payload.expected_version:
        raise MemoVersionConflictError(memo)

    if payload.word_phonetic and not (memo.word_phonetic or "").strip():
        memo.word_phonetic = payload.word_phonetic
    memo.word_meaning = append_unique_text(memo.word_meaning, payload.word_meaning)
    memo.word_example = append_unique_text(memo.word_example, payload.word_example)
    if payload.word_meaning:
        memo.body = memo.word_meaning or memo.body
    if payload.source_url and not memo.source_url:
        memo.source_url = payload.source_url
    if payload.source_title and not memo.source_title:
        memo.source_title = payload.source_title
    memo.version += 1
    memo.updated_at = datetime.now(UTC)
    session.commit()
    session.refresh(memo)
    return memo


def review_word(
    session: Session,
    user_id: str,
    memo_id: str,
    payload: WordReviewRequest,
) -> Memo:
    """记录复习反馈并计算下一次复习时间。"""

    memo = get_memo(session, user_id, memo_id)
    if memo.type != MemoType.WORD:
        raise MemoTypeError("只有英语单词可以提交复习反馈")
    if memo.version != payload.expected_version:
        raise MemoVersionConflictError(memo)

    current_familiarity = memo.familiarity
    if payload.feedback == ReviewFeedback.FORGOT:
        next_familiarity = max(0, current_familiarity - 1)
        interval_days = 1
    elif payload.feedback == ReviewFeedback.FUZZY:
        next_familiarity = current_familiarity
        interval_days = 3
    else:
        next_familiarity = min(5, current_familiarity + 1)
        interval_days = (1, 3, 7, 14, 30, 60)[next_familiarity]

    now = datetime.now(UTC)
    memo.familiarity = next_familiarity
    memo.review_count += 1
    memo.last_review_at = now
    memo.next_review_at = now + timedelta(days=interval_days)
    memo.version += 1
    memo.updated_at = now
    session.commit()
    session.refresh(memo)
    return memo


def attach_audio(
    session: Session,
    user_id: str,
    memo_id: str,
    expected_version: int,
    content: bytes,
    mime_type: str,
    duration_ms: int | None,
    audio_directory: Path,
) -> Memo:
    """校验并保存录音文件，再更新条目的音频元数据。"""

    memo = get_memo(session, user_id, memo_id)
    if memo.type != MemoType.IDEA:
        raise MemoTypeError("当前仅支持为灵感添加语音")
    if memo.version != expected_version:
        raise MemoVersionConflictError(memo)
    normalized_mime_type = mime_type.split(";", maxsplit=1)[0].strip().lower()
    if normalized_mime_type not in ALLOWED_AUDIO_TYPES:
        raise AudioValidationError("不支持的音频格式")
    if not content:
        raise AudioValidationError("录音内容不能为空")
    if len(content) > MAX_AUDIO_BYTES:
        raise AudioValidationError("录音不能超过 20 MB")
    if duration_ms is not None and not 0 <= duration_ms <= 60 * 60 * 1000:
        raise AudioValidationError("录音时长超出允许范围")

    audio_directory.mkdir(parents=True, exist_ok=True)
    storage_name = f"{memo.id}.audio"
    audio_path = audio_directory / storage_name
    # 文件名完全由服务端条目标识生成，不使用客户端文件名。
    audio_path.write_bytes(content)

    now = datetime.now(UTC)
    memo.audio_storage_name = storage_name
    memo.audio_mime_type = normalized_mime_type
    memo.audio_size_bytes = len(content)
    memo.audio_duration_ms = duration_ms
    memo.transcript = memo.body if memo.body.strip() != "语音记录" else None
    memo.transcript_status = "manual" if memo.transcript else "not_requested"
    memo.version += 1
    memo.updated_at = now
    session.commit()
    session.refresh(memo)
    return memo


def get_audio_path(
    session: Session,
    user_id: str,
    memo_id: str,
    audio_directory: Path,
) -> tuple[Memo, Path]:
    """解析当前用户条目的录音文件。"""

    memo = get_memo(session, user_id, memo_id)
    if memo.audio_storage_name is None:
        raise MemoNotFoundError
    audio_path = audio_directory / memo.audio_storage_name
    if not audio_path.is_file():
        raise MemoNotFoundError
    return memo, audio_path
