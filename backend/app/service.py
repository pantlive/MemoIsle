"""条目业务逻辑。"""

from __future__ import annotations

import hashlib
import io
import json
import re
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from PIL import Image, ImageOps
from sqlalchemy import Select, String, Update, and_, cast, delete, func, or_, select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.category_service import assign_memo_categories, descendant_category_codes
from app.config import Settings
from app.database import (
    SQLITE_LOCK_COMMIT_ATTEMPTS,
    commit_with_retry,
    is_sqlite_lock_error,
)
from app.memo_deletion_service import record_memo_deletion
from app.models import Memo, User
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
    ReviewSettingsUpdate,
    WordMergeRequest,
    WordReviewRequest,
)
from app.url_normalization import canonicalize_resource_url
from app.word_service import normalize_word_lemma


class MemoNotFoundError(LookupError):
    """条目不存在或不属于当前用户。"""


class MemoVersionConflictError(RuntimeError):
    """客户端版本落后于服务端。"""

    def __init__(self, current: Memo) -> None:
        super().__init__("条目已在其他设备更新")
        self.current = current


class MemoTypeError(ValueError):
    """请求的操作与条目类型不匹配。"""


class MemoNotTrashedError(ValueError):
    """只有回收站中的条目可以恢复或永久删除。"""


class WordDuplicateError(RuntimeError):
    """规范化词形已经存在。"""

    def __init__(self, current: Memo) -> None:
        super().__init__("已收藏相同词形")
        self.current = current


class ResourceDuplicateError(RuntimeError):
    """规范化网址已经存在。"""

    def __init__(self, current: Memo) -> None:
        super().__init__("已收藏相同网址")
        self.current = current


class AudioValidationError(ValueError):
    """录音内容或类型不符合上传约束。"""


class ImageValidationError(ValueError):
    """图片内容或类型不符合上传约束。"""


MAX_AUDIO_BYTES = 20 * 1024 * 1024
ALLOWED_AUDIO_TYPES = {
    "audio/mp4",
    "audio/mpeg",
    "audio/ogg",
    "audio/webm",
    "audio/x-m4a",
}

MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_IMAGE_DIMENSION = 12_000
MAX_IMAGE_PIXELS = 50_000_000
MAX_THUMBNAIL_DIMENSION = 1_280
ALLOWED_IMAGE_TYPES = {
    "image/gif",
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
}
PIL_IMAGE_MIME_TYPES = {
    "GIF": "image/gif",
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
}

DEFAULT_REVIEW_DAILY_LIMIT = 10
DEFAULT_REVIEW_INTERVALS_DAYS = (1, 3, 7, 14, 30, 60)
MAX_REVIEW_DAILY_LIMIT = 100


def _normalized_review_intervals(value: object) -> tuple[int, ...]:
    """读取数据库中的复习间隔；旧数据异常时回退到默认计划。"""

    if not isinstance(value, (list, tuple)) or len(value) != 6:
        return DEFAULT_REVIEW_INTERVALS_DAYS
    if any(
        isinstance(interval, bool)
        or not isinstance(interval, int)
        or interval < 1
        or interval > 365
        for interval in value
    ):
        return DEFAULT_REVIEW_INTERVALS_DAYS
    return tuple(value)


def get_review_settings(
    session: Session,
    user_id: str,
) -> tuple[int, tuple[int, ...]]:
    """读取账号复习计划；开发模式下尚未建账号时返回默认值。"""

    user = session.get(User, user_id)
    if user is None:
        return DEFAULT_REVIEW_DAILY_LIMIT, DEFAULT_REVIEW_INTERVALS_DAYS
    daily_limit = user.review_daily_limit
    if not isinstance(daily_limit, int) or not (
        1 <= daily_limit <= MAX_REVIEW_DAILY_LIMIT
    ):
        daily_limit = DEFAULT_REVIEW_DAILY_LIMIT
    return daily_limit, _normalized_review_intervals(user.review_intervals_days)


def update_review_settings(
    session: Session,
    user_id: str,
    payload: ReviewSettingsUpdate,
) -> tuple[int, tuple[int, ...]]:
    """保存账号复习计划，并为开发模式补建本地用户配置。"""

    user = session.get(User, user_id)
    if user is None:
        user = User(
            id=user_id,
            display_name="本地开发用户",
        )
        session.add(user)
    if payload.daily_limit is not None:
        user.review_daily_limit = payload.daily_limit
    if payload.intervals_days is not None:
        user.review_intervals_days = list(payload.intervals_days)
    session.commit()
    session.refresh(user)
    return get_review_settings(session, user_id)


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


# 搜索词按空白与常见分隔符拆开，词序不再影响结果。
_SEARCH_TOKEN_SEPARATORS = re.compile(r"[\s,，、;；:：/\\|+\-—_*#~^]+")
# 中英文之间没有空格时继续拆分，让「React教程」也能命中「React 教程」。
_SEARCH_CJK_ASCII_BOUNDARY = re.compile(
    r"(?<=[0-9A-Za-z])(?=[\u2e80-\u9fff\uf900-\ufaff])"
    r"|(?<=[\u2e80-\u9fff\uf900-\ufaff])(?=[0-9A-Za-z])"
)
# 单个查询最多参与匹配的关键词数量，避免超长输入拼出巨型 SQL。
MAX_SEARCH_TOKENS = 12


def split_search_tokens(value: str) -> list[str]:
    """把模糊搜索输入拆成若干关键词，重复词只保留一次。"""

    tokens: list[str] = []
    seen: set[str] = set()
    for chunk in _SEARCH_TOKEN_SEPARATORS.split(value):
        if not chunk:
            continue
        for part in _SEARCH_CJK_ASCII_BOUNDARY.split(chunk):
            cleaned = part.strip()
            if not cleaned:
                continue
            folded = cleaned.casefold()
            if folded in seen:
                continue
            seen.add(folded)
            tokens.append(cleaned)
            if len(tokens) >= MAX_SEARCH_TOKENS:
                return tokens
    return tokens


def search_token_condition(pattern: str, escaped_json_pattern: str):
    """构造单个关键词的条件：任一可搜索文本命中即可。"""

    tag_text = cast(Memo.tags, String)
    auto_tag_text = cast(Memo.resource_auto_tags, String)
    image_auto_tag_text = cast(Memo.image_auto_tags, String)
    collections_text = cast(Memo.collections, String)
    categories_text = cast(Memo.resource_categories, String)
    return or_(
        Memo.title.ilike(pattern, escape="\\"),
        Memo.body.ilike(pattern, escape="\\"),
        Memo.source_url.ilike(pattern, escape="\\"),
        Memo.source_title.ilike(pattern, escape="\\"),
        Memo.resource_page_title.ilike(pattern, escape="\\"),
        Memo.resource_description.ilike(pattern, escape="\\"),
        Memo.resource_site_name.ilike(pattern, escape="\\"),
        Memo.resource_category.ilike(pattern, escape="\\"),
        Memo.resource_category_label.ilike(pattern, escape="\\"),
        categories_text.ilike(pattern, escape="\\"),
        Memo.resource_kind.ilike(pattern, escape="\\"),
        Memo.resource_reading_status.ilike(pattern, escape="\\"),
        Memo.resource_import_folder.ilike(pattern, escape="\\"),
        Memo.word_phonetic.ilike(pattern, escape="\\"),
        Memo.word_meaning.ilike(pattern, escape="\\"),
        Memo.word_example.ilike(pattern, escape="\\"),
        Memo.transcript.ilike(pattern, escape="\\"),
        Memo.image_ocr_text.ilike(pattern, escape="\\"),
        tag_text.ilike(pattern, escape="\\"),
        tag_text.ilike(escaped_json_pattern, escape="\\"),
        auto_tag_text.ilike(pattern, escape="\\"),
        auto_tag_text.ilike(escaped_json_pattern, escape="\\"),
        image_auto_tag_text.ilike(pattern, escape="\\"),
        image_auto_tag_text.ilike(escaped_json_pattern, escape="\\"),
        collections_text.ilike(pattern, escape="\\"),
        collections_text.ilike(escaped_json_pattern, escape="\\"),
    )


def build_title(
    title: str | None,
    body: str,
    source_title: str | None = None,
    source_url: str | None = None,
    memo_type: MemoType | None = None,
) -> str:
    """优先使用显式标题，否则从正文第一行生成。"""

    if title and title.strip():
        return title.strip()[:200]
    if source_title and source_title.strip():
        return source_title.strip()[:200]
    if source_url:
        hostname = urlsplit(source_url).hostname
        if hostname:
            return hostname.removeprefix("www.")
    default_title = "图片收藏" if memo_type == MemoType.IMAGE else "灵感"
    first_line = next(
        (line.strip() for line in body.splitlines() if line.strip()),
        default_title,
    )
    if len(first_line) <= 80:
        return first_line
    return f"{first_line[:77]}..."


def create_memo(
    session: Session,
    user_id: str,
    payload: MemoCreate,
    *,
    commit: bool = True,
) -> Memo:
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
                        if not payload.allow_duplicate:
                            raise ResourceDuplicateError(resource)
                        break
                except ValueError:
                    # 历史异常网址不影响当前收藏。
                    continue

    if payload.type == MemoType.WORD:
        lemma = normalize_word_lemma(payload.title or "")
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
            payload.type,
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
        resource_ai_auto_pending=payload.type == MemoType.RESOURCE,
        resource_categories=[],
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
            normalize_word_lemma(payload.title or "")
            if payload.type == MemoType.WORD
            else None
        ),
        transcript=payload.transcript,
        transcript_status="manual" if payload.transcript else "none",
        familiarity=0,
        review_count=0,
        next_review_at=now if payload.type == MemoType.WORD else None,
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
    if commit:
        commit_with_retry(session)
        session.refresh(memo)
    return memo


def memo_query(
    user_id: str,
    memo_type: MemoType | None = None,
    updated_after: datetime | None = None,
    updated_after_id: str | None = None,
    query_text: str | None = None,
    resource_category: str | None = None,
    resource_category_codes: list[str] | None = None,
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
        # 时间戳相同时用条目 ID 继续分页，避免恰好卡在分页边界的条目丢失。
        updated_filter = Memo.updated_at > updated_after
        if updated_after_id is not None:
            updated_filter = or_(
                updated_filter,
                and_(
                    Memo.updated_at == updated_after,
                    Memo.id > updated_after_id,
                ),
            )
        query = query.where(updated_filter)
    if resource_category_codes:
        category_conditions = [Memo.resource_category.in_(resource_category_codes)]
        for code in resource_category_codes:
            escaped_code = json.dumps(code, ensure_ascii=True)
            category_conditions.append(
                cast(Memo.resource_categories, String).ilike(
                    f"%{escape_like_pattern(escaped_code)}%",
                    escape="\\",
                ),
            )
        query = query.where(or_(*category_conditions))
    elif resource_category is not None:
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
                cast(Memo.image_auto_tags, String).ilike(
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
    if query_text and (search_tokens := split_search_tokens(query_text)):
        # 逐词收窄：关键词之间是「与」关系，词序和分隔符不影响结果。
        # 同时检索三种内容类型的用户可见文本。
        for token in search_tokens:
            pattern = f"%{escape_like_pattern(token)}%"
            # 同时匹配 JSON 原文和 Unicode 转义形式，兼容已有 SQLite 数据。
            escaped_json_token = json.dumps(token, ensure_ascii=True)[1:-1]
            escaped_json_pattern = (
                f"%{escape_like_pattern(escaped_json_token)}%"
            )
            query = query.where(
                search_token_condition(pattern, escaped_json_pattern)
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
        MemoSort.OPENED_DESC: (
            Memo.resource_open_count.desc(),
            Memo.resource_last_opened_at.desc(),
            Memo.updated_at.desc(),
            Memo.id.desc(),
        ),
    }
    return query.order_by(*sort_orders[sort])


def list_memos(
    session: Session,
    user_id: str,
    memo_type: MemoType | None = None,
    updated_after: datetime | None = None,
    updated_after_id: str | None = None,
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

    category_codes = (
        descendant_category_codes(session, user_id, resource_category)
        if resource_category
        else None
    )
    query = memo_query(
        user_id=user_id,
        memo_type=memo_type,
        updated_after=updated_after,
        updated_after_id=updated_after_id,
        query_text=query_text,
        resource_category=resource_category,
        resource_category_codes=category_codes,
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


def list_memos_for_export(session: Session, user_id: str) -> list[Memo]:
    """读取当前用户全部条目，供隐私导出使用。"""

    # 导出必须包含回收站中仍在保留期内的条目，避免用户无法迁移完整数据。
    query = memo_query(
        user_id=user_id,
        sort=MemoSort.CREATED_ASC,
        include_trashed=True,
    )
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

    category_codes = (
        descendant_category_codes(session, user_id, resource_category)
        if resource_category
        else None
    )
    query = memo_query(
        user_id=user_id,
        memo_type=memo_type,
        updated_after=updated_after,
        query_text=query_text,
        resource_category=resource_category,
        resource_category_codes=category_codes,
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


def _execute_with_lock_retry(session: Session, statement: Update) -> None:
    """执行并提交一条更新语句。

    回滚会撤销已执行的语句，所以遇到 SQLite 锁时连同语句一起重试，
    不能只重试提交。
    """

    delay = 0.05
    for attempt in range(SQLITE_LOCK_COMMIT_ATTEMPTS):
        try:
            session.execute(statement)
            session.commit()
            return
        except OperationalError as error:
            session.rollback()
            if not is_sqlite_lock_error(error) or attempt == SQLITE_LOCK_COMMIT_ATTEMPTS - 1:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 0.8)


def record_resource_open(session: Session, user_id: str, memo_id: str) -> Memo:
    """网页资料打开次数加一，不改动版本号，避免与正在进行的编辑冲突。"""

    memo = get_memo(session, user_id, memo_id)
    if memo.type != MemoType.RESOURCE:
        raise MemoTypeError("只有网页资料记录打开次数")
    if memo.status == MemoStatus.TRASHED:
        raise MemoNotFoundError
    opened_at = datetime.now(UTC)
    # 在数据库里自增，多个标签页同时打开也不会丢计数；显式保留 updated_at，
    # 否则 onupdate 会刷新它，让「最近更新」排序和增量同步把打开当成修改。
    statement = (
        update(Memo)
        .where(Memo.id == memo.id, Memo.user_id == user_id)
        .values(
            resource_open_count=Memo.resource_open_count + 1,
            resource_last_opened_at=opened_at,
            updated_at=Memo.updated_at,
        )
        .execution_options(synchronize_session=False)
    )
    _execute_with_lock_retry(session, statement)
    session.refresh(memo)
    return memo


def list_quick_access(session: Session, user_id: str, limit: int) -> list[Memo]:
    """快速访问：打开过、未被移除的网页资料，按打开次数降序。"""

    query = (
        select(Memo)
        .where(
            Memo.user_id == user_id,
            Memo.type == MemoType.RESOURCE,
            Memo.status != MemoStatus.TRASHED,
            Memo.resource_open_count > 0,
            Memo.resource_quick_access_hidden.is_(False),
        )
        .order_by(
            Memo.resource_open_count.desc(),
            Memo.resource_last_opened_at.desc(),
            Memo.id.desc(),
        )
        .limit(limit)
    )
    return list(session.scalars(query))


def set_resource_quick_access_hidden(
    session: Session,
    user_id: str,
    memo_id: str,
    hidden: bool,
) -> Memo:
    """移除或恢复快速访问；与打开统计一样不改版本号和更新时间。"""

    memo = get_memo(session, user_id, memo_id)
    if memo.type != MemoType.RESOURCE:
        raise MemoTypeError("只有网页资料可以加入快速访问")
    if memo.status == MemoStatus.TRASHED:
        raise MemoNotFoundError
    _execute_with_lock_retry(
        session,
        update(Memo)
        .where(Memo.id == memo.id, Memo.user_id == user_id)
        .values(resource_quick_access_hidden=hidden, updated_at=Memo.updated_at)
        .execution_options(synchronize_session=False),
    )
    session.refresh(memo)
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
    previous_status = memo.status
    previous_type = memo.type
    requested_type = changes.pop("type", None)
    type_changed = requested_type is not None and requested_type != previous_type
    if type_changed:
        if previous_type == MemoType.IMAGE or requested_type == MemoType.IMAGE:
            # 图片文件与条目生命周期强绑定，第一版先禁止双向类型转换。
            raise MemoTypeError("图片条目暂不支持转换类型")
        source_url = changes.get("source_url", memo.source_url)
        if requested_type == MemoType.RESOURCE and not source_url:
            raise MemoTypeError("转换为网页资料需要来源网址")
        if requested_type == MemoType.WORD:
            normalized_lemma = normalize_word_lemma(
                changes.get("title") or memo.title,
            )
            existing_word = session.scalar(
                select(Memo).where(
                    Memo.user_id == user_id,
                    Memo.type == MemoType.WORD,
                    Memo.status != MemoStatus.TRASHED,
                    Memo.id != memo.id,
                    Memo.normalized_lemma == normalized_lemma,
                )
            )
            if existing_word is not None:
                raise WordDuplicateError(existing_word)
        memo.type = requested_type
        _reset_type_specific_fields(memo, requested_type)
    if memo.type == MemoType.RESOURCE and memo.resource_import_batch_id is not None:
        # 用户显式编辑后不再允许“撤销导入”批量移除该资料。
        memo.resource_import_batch_id = None
    for field_name, value in changes.items():
        setattr(memo, field_name, value)
    _apply_trash_status_side_effects(memo, previous_status)
    if "body" in changes and "title" not in changes:
        memo.title = build_title(None, memo.body)
    if memo.type == MemoType.WORD and "title" in changes:
        memo.normalized_lemma = normalize_word_lemma(memo.title)
    if type_changed and memo.type == MemoType.WORD:
        memo.normalized_lemma = normalize_word_lemma(memo.title)
        if "word_meaning" not in changes:
            memo.word_meaning = memo.body
    if type_changed and memo.type == MemoType.IDEA:
        memo.word_phonetic = None
        memo.word_us_audio_url = None
        memo.word_uk_audio_url = None
        memo.normalized_lemma = None
        memo.word_meaning = None
        memo.word_example = None
    if memo.type == MemoType.RESOURCE and "title" in changes:
        memo.resource_title_user_defined = True
    if memo.type in {MemoType.RESOURCE, MemoType.IMAGE} and (
        "resource_categories" in changes or "resource_category" in changes
    ):
        if "resource_categories" in changes:
            assigned_codes = list(changes.get("resource_categories") or [])
        else:
            assigned_code = changes.get("resource_category")
            assigned_codes = [assigned_code] if assigned_code else []
        assign_memo_categories(
            session,
            user_id,
            memo,
            assigned_codes,
            manual=True,
        )
    if memo.type == MemoType.RESOURCE and (
        memo.source_url != previous_source_url or type_changed
    ):
        # 修改网址后重新执行元数据、分类与健康检查。
        memo.resource_ai_classified_at = None
        memo.resource_text_excerpt = None
        memo.resource_ai_assessment = None
        memo.resource_ai_confirmation_pending = False
        memo.resource_ai_confirmation = None
        memo.resource_ai_review_required = False
        memo.resource_ai_auto_pending = True
        memo.resource_metadata_status = ResourceProcessStatus.PENDING
        memo.resource_metadata_error = None
        memo.resource_category = None
        memo.resource_category_label = None
        memo.resource_categories = []
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


def _reset_type_specific_fields(memo: Memo, target_type: MemoType) -> None:
    """切换条目类型时清理不再适用的扩展字段。"""

    memo.resource_ai_classified_at = None
    memo.resource_text_excerpt = None
    memo.resource_ai_assessment = None
    memo.resource_ai_confirmation_pending = False
    memo.resource_ai_confirmation = None
    memo.resource_ai_review_required = False
    memo.resource_ai_auto_pending = target_type == MemoType.RESOURCE
    if target_type == MemoType.RESOURCE:
        # 资源转换保留标题、正文和来源链接，重新等待网页处理。
        memo.word_phonetic = None
        memo.word_us_audio_url = None
        memo.word_uk_audio_url = None
        memo.normalized_lemma = None
        memo.word_meaning = None
        memo.word_example = None
        memo.resource_metadata_status = ResourceProcessStatus.PENDING
        memo.resource_metadata_error = None
        memo.resource_category = None
        memo.resource_category_label = None
        memo.resource_categories = []
        memo.resource_category_status = ResourceProcessStatus.PENDING
        memo.resource_category_confidence = None
        memo.resource_category_source = None
        memo.resource_kind = ResourceKind.OTHER
        memo.resource_reading_status = ResourceReadingStatus.UNREAD
        memo.resource_auto_tags = []
        memo.resource_last_enriched_at = None
        memo.link_health_status = "unchecked"
        memo.link_health_http_status = None
        memo.link_health_error = None
        memo.link_last_checked_at = None
        memo.link_last_success_at = None
        memo.link_next_check_at = datetime.now(UTC)
        memo.link_consecutive_failures = 0
        memo.link_effective_url = None
        memo.link_metadata_fingerprint = None
        return

    # 单词和灵感不再需要网页元数据或巡检状态。
    memo.resource_page_title = None
    memo.resource_description = None
    memo.resource_site_name = None
    memo.resource_favicon_url = None
    memo.resource_image_url = None
    memo.resource_metadata_status = ResourceProcessStatus.NONE
    memo.resource_metadata_error = None
    memo.resource_category = None
    memo.resource_category_label = None
    memo.resource_categories = []
    memo.resource_category_status = ResourceProcessStatus.NONE
    memo.resource_category_confidence = None
    memo.resource_category_source = None
    memo.resource_kind = None
    memo.resource_reading_status = None
    memo.resource_auto_tags = []
    memo.resource_last_enriched_at = None
    memo.resource_import_folder = None
    memo.resource_import_batch_id = None
    memo.link_health_status = "unchecked"
    memo.link_health_http_status = None
    memo.link_health_error = None
    memo.link_last_checked_at = None
    memo.link_last_success_at = None
    memo.link_next_check_at = None
    memo.link_consecutive_failures = 0
    memo.link_effective_url = None
    memo.link_metadata_fingerprint = None


def _aware_utc(value: datetime | None) -> datetime | None:
    """把 SQLite 可能返回的无时区时间按 UTC 解释。"""

    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _apply_trash_status_side_effects(
    memo: Memo,
    previous_status: MemoStatus,
) -> None:
    """进入或离开回收站时维护删除时间和恢复前状态。"""

    if memo.status == MemoStatus.TRASHED and previous_status != MemoStatus.TRASHED:
        memo.deleted_at = datetime.now(UTC)
        memo.status_before_trash = previous_status.value
    elif memo.status != MemoStatus.TRASHED:
        memo.deleted_at = None
        memo.status_before_trash = None


def _restore_status_for(memo: Memo) -> MemoStatus:
    """恢复回收站条目时尽量回到进入回收站前的状态。"""

    if memo.status_before_trash:
        try:
            previous = MemoStatus(memo.status_before_trash)
        except ValueError:
            previous = MemoStatus.ACTIVE
        if previous != MemoStatus.TRASHED:
            return previous
    return MemoStatus.INBOX if memo.type == MemoType.IDEA else MemoStatus.ACTIVE


def _delete_memo_files(
    memo: Memo,
    audio_directory: Path,
    image_directory: Path,
) -> None:
    """永久删除时同时移除服务端保存的录音和图片文件。"""

    if not memo.audio_storage_name:
        audio_path = None
    else:
        audio_path = audio_directory / memo.audio_storage_name
    image_names = {
        memo.image_storage_name,
        memo.image_thumbnail_storage_name,
    }
    image_paths = [image_directory / name for name in image_names if name]

    # 调用方已提交删除；缺失附件不阻塞清理。
    if audio_path is not None:
        audio_path.unlink(missing_ok=True)
    for image_path in image_paths:
        image_path.unlink(missing_ok=True)


def effective_deleted_at(memo: Memo) -> datetime | None:
    """回收站条目的删除时间；旧数据回退到更新时间。"""

    if memo.status != MemoStatus.TRASHED:
        return None
    return _aware_utc(memo.deleted_at) or _aware_utc(memo.updated_at)


def is_trash_expired(
    memo: Memo,
    retention_days: int,
    now: datetime | None = None,
) -> bool:
    """判断回收站条目是否已超过保留期限。"""

    deleted_at = effective_deleted_at(memo)
    if deleted_at is None:
        return False
    cutoff = (now or datetime.now(UTC)) - timedelta(days=retention_days)
    return deleted_at <= cutoff


def move_memo_to_trash(
    session: Session,
    user_id: str,
    memo_id: str,
    expected_version: int,
) -> Memo:
    """把条目移入回收站，默认保留 30 天。"""

    return update_memo(
        session,
        user_id,
        memo_id,
        MemoUpdate(expected_version=expected_version, status=MemoStatus.TRASHED),
    )


def restore_memo(
    session: Session,
    user_id: str,
    memo_id: str,
    expected_version: int,
) -> Memo:
    """从回收站恢复到进入回收站前的状态。"""

    memo = get_memo(session, user_id, memo_id)
    if memo.status != MemoStatus.TRASHED:
        raise MemoNotTrashedError("该条目不在回收站")
    return update_memo(
        session,
        user_id,
        memo_id,
        MemoUpdate(
            expected_version=expected_version,
            status=_restore_status_for(memo),
        ),
    )


def permanently_delete_memo(
    session: Session,
    user_id: str,
    memo_id: str,
    expected_version: int,
    audio_directory: Path,
    image_directory: Path,
) -> None:
    """从回收站永久删除条目及附件文件。"""

    memo = get_memo(session, user_id, memo_id)
    if memo.status != MemoStatus.TRASHED:
        raise MemoNotTrashedError("只有回收站中的条目可以永久删除")
    if memo.version != expected_version:
        raise MemoVersionConflictError(memo)
    if not delete_memo_snapshot(session, memo, audio_directory, image_directory):
        raise MemoVersionConflictError(get_memo(session, user_id, memo_id))


def delete_memo_snapshot(
    session: Session,
    memo: Memo,
    audio_directory: Path,
    image_directory: Path,
) -> bool:
    """删除已核对的回收站版本，确认提交后再清理附件，保护并发还原。"""

    result = session.execute(
        delete(Memo)
        .where(
            Memo.id == memo.id,
            Memo.user_id == memo.user_id,
            Memo.status == MemoStatus.TRASHED,
            Memo.version == memo.version,
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        session.rollback()
        return False
    record_memo_deletion(session, memo)
    session.expunge(memo)
    session.commit()
    _delete_memo_files(memo, audio_directory, image_directory)
    return True


def empty_trash(
    session: Session,
    user_id: str,
    audio_directory: Path,
    image_directory: Path,
) -> int:
    """清空当前用户回收站，返回永久删除的条目数。"""

    memos = list(
        session.scalars(
            select(Memo).where(
                Memo.user_id == user_id,
                Memo.status == MemoStatus.TRASHED,
            )
        ).all()
    )
    return sum(
        delete_memo_snapshot(session, memo, audio_directory, image_directory)
        for memo in memos
    )


def restore_all_trash(session: Session, user_id: str) -> int:
    """一次提交恢复当前账号的全部回收站条目，保留附件和原有状态。"""

    memos = list(session.scalars(
        select(Memo).where(
            Memo.user_id == user_id,
            Memo.status == MemoStatus.TRASHED,
        ),
    ).all())
    restored_count = 0
    now = datetime.now(UTC)
    for memo in memos:
        # 按版本及回收站状态更新，跳过操作期间已被其他设备处理的内容。
        result = session.execute(
            update(Memo)
            .where(
                Memo.id == memo.id,
                Memo.user_id == user_id,
                Memo.status == MemoStatus.TRASHED,
                Memo.version == memo.version,
            )
            .values(
                status=_restore_status_for(memo),
                deleted_at=None,
                status_before_trash=None,
                resource_import_batch_id=None,
                version=Memo.version + 1,
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        restored_count += result.rowcount
    session.commit()
    session.expire_all()
    return restored_count


def purge_expired_trash(
    session: Session,
    audio_directory: Path,
    image_directory: Path,
    retention_days: int,
    user_id: str | None = None,
    now: datetime | None = None,
) -> int:
    """永久删除超过保留期限的回收站条目。"""

    query = select(Memo).where(Memo.status == MemoStatus.TRASHED)
    if user_id is not None:
        query = query.where(Memo.user_id == user_id)
    expired = [
        memo
        for memo in session.scalars(query).all()
        if is_trash_expired(memo, retention_days, now)
    ]
    return sum(
        delete_memo_snapshot(session, memo, audio_directory, image_directory)
        for memo in expired
    )


def run_trash_purge(database_url: str, settings: Settings) -> int:
    """打开独立会话并清理过期回收站条目。"""

    from app.database import Database

    database = Database(database_url)
    try:
        with database.session_factory() as session:
            return purge_expired_trash(
                session,
                settings.audio_directory,
                settings.image_directory,
                settings.trash_retention_days,
            )
    finally:
        database.dispose()


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
    limit: int | None = None,
    memo_type: MemoType | None = None,
) -> tuple[list[Memo], dict[str, int]]:
    """读取今日回顾：到期单词、未读资料和待整理灵感。"""

    daily_limit, _ = get_review_settings(session, user_id)
    # 显式 limit 只能缩小本次队列，不能绕过账号设置的每日上限。
    effective_limit = min(limit or daily_limit, daily_limit)
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
        limit=effective_limit,
    )
    resources = _load_review_items(
        session,
        *resource_filters,
        order_by=(Memo.created_at.asc(), Memo.id.asc()),
        limit=effective_limit,
    )
    ideas = _load_review_items(
        session,
        *idea_filters,
        order_by=(Memo.created_at.asc(), Memo.id.asc()),
        limit=effective_limit,
    )
    if memo_type == MemoType.WORD:
        items = words[:effective_limit]
    elif memo_type == MemoType.RESOURCE:
        items = resources[:effective_limit]
    elif memo_type == MemoType.IDEA:
        items = ideas[:effective_limit]
    else:
        items = _interleave_review_items(
            words,
            resources,
            ideas,
            limit=effective_limit,
        )
    counts["daily_limit"] = daily_limit
    counts["scheduled_count"] = len(items)
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

    _, intervals_days = get_review_settings(session, user_id)
    current_familiarity = memo.familiarity
    if payload.feedback == ReviewFeedback.FORGOT:
        next_familiarity = max(0, current_familiarity - 1)
        interval_days = intervals_days[0]
    elif payload.feedback == ReviewFeedback.FUZZY:
        next_familiarity = current_familiarity
        interval_days = intervals_days[1]
    else:
        next_familiarity = min(5, current_familiarity + 1)
        interval_days = intervals_days[next_familiarity]

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
    # 会议记录会先保存转写，上传音频时不能被占位正文覆盖。
    memo.transcript = memo.transcript or (
        memo.body if memo.body.strip() not in {"语音记录", "会议记录"} else None
    )
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


def _decode_image(content: bytes, declared_mime_type: str) -> Image.Image:
    """校验真实图片格式并解码，防止只依赖 Content-Type 的伪图片。"""

    normalized_mime_type = declared_mime_type.split(";", maxsplit=1)[0].strip().lower()
    # 浏览器偶发会把 JPEG 声明成 image/jpg，服务端统一保存标准 MIME。
    if normalized_mime_type == "image/jpg":
        normalized_mime_type = "image/jpeg"
    if normalized_mime_type not in ALLOWED_IMAGE_TYPES:
        raise ImageValidationError("不支持的图片格式")
    if not content:
        raise ImageValidationError("图片内容不能为空")
    if len(content) > MAX_IMAGE_BYTES:
        raise ImageValidationError("图片不能超过 20 MB")

    try:
        image = Image.open(io.BytesIO(content))
        actual_mime_type = PIL_IMAGE_MIME_TYPES.get(image.format or "")
        if actual_mime_type != normalized_mime_type:
            raise ImageValidationError("图片内容与声明格式不一致")
        if (
            image.width <= 0
            or image.height <= 0
            or image.width > MAX_IMAGE_DIMENSION
            or image.height > MAX_IMAGE_DIMENSION
            or image.width * image.height > MAX_IMAGE_PIXELS
        ):
            raise ImageValidationError("图片尺寸超出允许范围")
        # 强制解码当前帧，能发现被截断的图片数据。
        image.load()
        return image
    except ImageValidationError:
        raise
    except Exception as error:
        raise ImageValidationError("图片文件无效或已损坏") from error


def _build_image_thumbnail(image: Image.Image) -> bytes:
    """生成最大边 1280 像素的 WebP 缩略图。"""

    thumbnail = ImageOps.exif_transpose(image).copy()
    # WebP 统一使用 RGB/RGBA，避免调色板、CMYK 等模式保存失败。
    if thumbnail.mode not in {"RGB", "RGBA"}:
        thumbnail = thumbnail.convert("RGBA")
    thumbnail.thumbnail(
        (MAX_THUMBNAIL_DIMENSION, MAX_THUMBNAIL_DIMENSION),
        Image.Resampling.LANCZOS,
    )
    buffer = io.BytesIO()
    thumbnail.save(buffer, format="WEBP", quality=85)
    return buffer.getvalue()


def attach_image(
    session: Session,
    user_id: str,
    memo_id: str,
    expected_version: int,
    content: bytes,
    mime_type: str,
    image_directory: Path,
) -> Memo:
    """校验并保存图片，再更新条目的图片元数据。"""

    memo = get_memo(session, user_id, memo_id)
    if memo.type != MemoType.IMAGE:
        raise MemoTypeError("当前仅支持为图片收藏上传图片")
    if memo.version != expected_version:
        raise MemoVersionConflictError(memo)

    normalized_mime_type = mime_type.split(";", maxsplit=1)[0].strip().lower()
    if normalized_mime_type == "image/jpg":
        normalized_mime_type = "image/jpeg"
    image = _decode_image(content, normalized_mime_type)
    thumbnail_content = _build_image_thumbnail(image)

    image_directory.mkdir(parents=True, exist_ok=True)
    storage_name = f"{memo.id}.image"
    thumbnail_storage_name = f"{memo.id}.thumbnail.webp"
    # 文件名完全由服务端条目标识生成，不使用客户端上传文件名。
    (image_directory / storage_name).write_bytes(content)
    (image_directory / thumbnail_storage_name).write_bytes(thumbnail_content)

    now = datetime.now(UTC)
    memo.image_storage_name = storage_name
    memo.image_mime_type = normalized_mime_type
    memo.image_size_bytes = len(content)
    memo.image_width = image.width
    memo.image_height = image.height
    memo.image_hash = hashlib.sha256(content).hexdigest()
    memo.image_thumbnail_storage_name = thumbnail_storage_name
    # 替换图片后旧的识别结果不再对应新图片，先清空等待重新识别。
    memo.image_ocr_text = None
    memo.image_ocr_status = "none"
    memo.image_ocr_error = None
    memo.image_ocr_source = None
    memo.image_auto_tags = []
    memo.image_ocr_updated_at = None
    # 新图不能沿用旧图的模型判断，手动分类仍然保留。
    memo.resource_ai_classified_at = None
    memo.resource_ai_assessment = None
    if memo.resource_category_source not in {"manual", "user_rule"}:
        memo.resource_category = None
        memo.resource_category_label = None
        memo.resource_categories = []
        memo.resource_category_source = None
        memo.resource_category_status = "none"
        memo.resource_category_confidence = None
    memo.resource_ai_confirmation = None
    memo.resource_ai_confirmation_pending = False
    memo.version += 1
    memo.updated_at = now
    session.commit()
    session.refresh(memo)
    return memo


def get_image_path(
    session: Session,
    user_id: str,
    memo_id: str,
    image_directory: Path,
    thumbnail: bool = False,
) -> tuple[Memo, Path]:
    """解析当前用户图片收藏的原图或缩略图。"""

    memo = get_memo(session, user_id, memo_id)
    if memo.type != MemoType.IMAGE:
        raise MemoTypeError("当前条目不是图片收藏")
    storage_name = (
        memo.image_thumbnail_storage_name
        if thumbnail
        else memo.image_storage_name
    )
    if storage_name is None or storage_name != Path(storage_name).name:
        raise MemoNotFoundError
    image_path = image_directory / storage_name
    if not image_path.is_file():
        raise MemoNotFoundError
    return memo, image_path
