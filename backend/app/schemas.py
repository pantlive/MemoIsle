"""API 数据模型。"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)


class MemoType(StrEnum):
    """条目类型。"""

    WORD = "word"
    RESOURCE = "resource"
    IDEA = "idea"


class MemoStatus(StrEnum):
    """条目状态。"""

    INBOX = "inbox"
    ACTIVE = "active"
    ARCHIVED = "archived"
    TRASHED = "trashed"


class MemoSort(StrEnum):
    """资料库列表排序方式。"""

    UPDATED_DESC = "updated_desc"
    UPDATED_ASC = "updated_asc"
    CREATED_DESC = "created_desc"
    CREATED_ASC = "created_asc"
    TITLE_ASC = "title_asc"
    TITLE_DESC = "title_desc"


class ReviewFeedback(StrEnum):
    """单词复习反馈。"""

    FORGOT = "forgot"
    FUZZY = "fuzzy"
    REMEMBERED = "remembered"


class ResourceCategory(StrEnum):
    """网页资料的系统分类。"""

    LEARNING = "learning"
    ARTICLE = "article"
    MEDIA = "media"
    TOOL = "tool"
    BOOK_PAPER = "book_paper"
    PRODUCT = "product"
    OTHER = "other"


class ResourceKind(StrEnum):
    """网页资料的内容形态。"""

    ARTICLE = "article"
    VIDEO = "video"
    COURSE = "course"
    TOOL = "tool"
    BOOK = "book"
    OTHER = "other"


class ResourceReadingStatus(StrEnum):
    """网页资料的阅读进度。"""

    UNREAD = "unread"
    READING = "reading"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class ResourceProcessStatus(StrEnum):
    """网页资料后台处理状态。"""

    NONE = "none"
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class LinkHealthStatus(StrEnum):
    """网页链接巡检状态。"""

    UNCHECKED = "unchecked"
    HEALTHY = "healthy"
    REDIRECTED = "redirected"
    CHANGED = "changed"
    AUTH_REQUIRED = "auth_required"
    TEMPORARY_FAILURE = "temporary_failure"
    FAILED = "failed"
    IGNORED = "ignored"


class LinkHealthAction(StrEnum):
    """用户对网页巡检结果执行的处理动作。"""

    RETRY = "retry"
    IGNORE = "ignore"
    RESUME = "resume"
    ADOPT_REDIRECT = "adopt_redirect"
    UPDATE_URL = "update_url"
    UPDATE_METADATA = "update_metadata"
    DELETE = "delete"


class MemoCreate(BaseModel):
    """创建条目请求。"""

    client_id: UUID
    type: MemoType = MemoType.IDEA
    title: str | None = Field(default=None, max_length=200)
    body: str = Field(min_length=1, max_length=50_000)
    source_url: str | None = Field(default=None, max_length=2_048)
    source_title: str | None = Field(default=None, max_length=200)
    word_phonetic: str | None = Field(default=None, max_length=120)
    word_meaning: str | None = Field(default=None, max_length=5_000)
    word_example: str | None = Field(default=None, max_length=5_000)
    tags: list[str] = Field(default_factory=list, max_length=20)
    collections: list[str] = Field(default_factory=list, max_length=20)
    resource_kind: ResourceKind | None = None
    resource_reading_status: ResourceReadingStatus | None = None
    starred: bool = False

    @field_validator("body")
    @classmethod
    def validate_body(cls, value: str) -> str:
        """拒绝只有空白字符的正文。"""

        cleaned = value.strip()
        if not cleaned:
            raise ValueError("正文不能为空")
        return cleaned

    @field_validator("tags", "collections")
    @classmethod
    def normalize_tags(cls, value: list[str]) -> list[str]:
        """去除空标签并保持输入顺序去重。"""

        return list(dict.fromkeys(tag.strip() for tag in value if tag.strip()))

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: str | None) -> str | None:
        """只接受可在客户端安全打开的 HTTP(S) 来源链接。"""

        return normalize_source_url(value)

    @field_validator("source_title")
    @classmethod
    def normalize_source_title(cls, value: str | None) -> str | None:
        """清理可选来源标题。"""

        return normalize_optional_text(value)

    @model_validator(mode="after")
    def validate_resource_url(self) -> MemoCreate:
        """检查不同内容类型的最小必填字段。"""

        if self.type == MemoType.RESOURCE and self.source_url is None:
            raise ValueError("网页资料必须提供来源链接")
        if self.type == MemoType.WORD and not normalize_optional_text(self.title):
            raise ValueError("英语单词必须提供词形")
        return self


class MemoUpdate(BaseModel):
    """更新条目请求。"""

    expected_version: int = Field(ge=1)
    title: str | None = Field(default=None, max_length=200)
    body: str | None = Field(default=None, min_length=1, max_length=50_000)
    source_url: str | None = Field(default=None, max_length=2_048)
    source_title: str | None = Field(default=None, max_length=200)
    word_phonetic: str | None = Field(default=None, max_length=120)
    word_meaning: str | None = Field(default=None, max_length=5_000)
    word_example: str | None = Field(default=None, max_length=5_000)
    resource_category: ResourceCategory | None = None
    resource_kind: ResourceKind | None = None
    resource_reading_status: ResourceReadingStatus | None = None
    tags: list[str] | None = Field(default=None, max_length=20)
    collections: list[str] | None = Field(default=None, max_length=20)
    starred: bool | None = None
    status: MemoStatus | None = None

    @field_validator("body")
    @classmethod
    def validate_optional_body(cls, value: str | None) -> str | None:
        """更新正文时拒绝空白内容。"""

        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("正文不能为空")
        return cleaned

    @field_validator("tags", "collections")
    @classmethod
    def normalize_optional_tags(cls, value: list[str] | None) -> list[str] | None:
        """规范化可选标签列表。"""

        if value is None:
            return None
        return list(dict.fromkeys(tag.strip() for tag in value if tag.strip()))

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: str | None) -> str | None:
        """更新时规范化来源链接。"""

        return normalize_source_url(value)

    @field_validator("source_title")
    @classmethod
    def normalize_source_title(cls, value: str | None) -> str | None:
        """更新时清理来源标题。"""

        return normalize_optional_text(value)

    @field_validator("word_phonetic", "word_meaning", "word_example")
    @classmethod
    def normalize_word_text(cls, value: str | None) -> str | None:
        """清理单词扩展字段。"""

        return normalize_optional_text(value)


class MemoRead(BaseModel):
    """返回给客户端的条目。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    client_id: UUID
    type: MemoType
    title: str
    body: str
    source_url: str | None
    source_title: str | None
    resource_page_title: str | None
    resource_description: str | None
    resource_site_name: str | None
    resource_favicon_url: str | None
    resource_image_url: str | None
    resource_metadata_status: ResourceProcessStatus
    resource_metadata_error: str | None
    resource_category: ResourceCategory | None
    resource_category_status: ResourceProcessStatus
    resource_category_confidence: float | None
    resource_category_source: str | None
    resource_kind: ResourceKind | None
    resource_reading_status: ResourceReadingStatus | None
    resource_auto_tags: list[str]
    resource_last_enriched_at: datetime | None
    resource_import_folder: str | None
    resource_import_batch_id: UUID | None
    link_health_status: LinkHealthStatus
    link_health_http_status: int | None
    link_health_error: str | None
    link_last_checked_at: datetime | None
    link_last_success_at: datetime | None
    link_next_check_at: datetime | None
    link_consecutive_failures: int
    link_effective_url: str | None
    word_phonetic: str | None
    word_meaning: str | None
    word_example: str | None
    familiarity: int
    review_count: int
    last_review_at: datetime | None
    next_review_at: datetime | None
    audio_mime_type: str | None
    audio_size_bytes: int | None
    audio_duration_ms: int | None
    transcript: str | None
    transcript_status: str
    tags: list[str]
    collections: list[str]
    starred: bool
    status: MemoStatus
    version: int
    created_at: datetime
    updated_at: datetime

    @field_serializer(
        "created_at",
        "updated_at",
        "last_review_at",
        "next_review_at",
        "resource_last_enriched_at",
        "link_last_checked_at",
        "link_last_success_at",
        "link_next_check_at",
    )
    def serialize_utc_datetime(self, value: datetime | None) -> str | None:
        """SQLite 返回无时区时间时，按服务端统一的 UTC 约定输出。"""

        if value is None:
            return None
        resolved = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return resolved.astimezone(UTC).isoformat().replace("+00:00", "Z")


class MemoListResponse(BaseModel):
    """条目列表响应。"""

    items: list[MemoRead]


class LinkHealthListResponse(BaseModel):
    """网页巡检中心列表与状态摘要。"""

    items: list[MemoRead]
    counts: dict[str, int]


class LinkHealthActionRequest(BaseModel):
    """处理一条网页巡检结果。"""

    expected_version: int = Field(ge=1)
    action: LinkHealthAction
    new_url: str | None = Field(default=None, max_length=2_048)

    @field_validator("new_url")
    @classmethod
    def validate_new_url(cls, value: str | None) -> str | None:
        """规范化用户提供的替换网址。"""

        return normalize_source_url(value)

    @model_validator(mode="after")
    def validate_action_fields(self) -> LinkHealthActionRequest:
        """更新网址动作必须携带新网址。"""

        if self.action == LinkHealthAction.UPDATE_URL and self.new_url is None:
            raise ValueError("更新网址必须提供新网址")
        return self


class SyncResponse(BaseModel):
    """增量同步响应。"""

    items: list[MemoRead]
    cursor: datetime


class WordReviewRequest(BaseModel):
    """提交单词复习反馈。"""

    expected_version: int = Field(ge=1)
    feedback: ReviewFeedback


class ReviewQueueResponse(BaseModel):
    """到期单词复习队列。"""

    items: list[MemoRead]


class BookmarkInput(BaseModel):
    """浏览器本地解析后提交的一条 Chrome 书签。"""

    client_item_id: str = Field(min_length=1, max_length=100)
    title: str = Field(default="", max_length=300)
    url: str = Field(max_length=2_048)
    folder_path: str | None = Field(default=None, max_length=1_000)

    @field_validator("client_item_id", "title")
    @classmethod
    def normalize_bookmark_text(cls, value: str) -> str:
        """清理书签标识和标题中的首尾空白。"""

        return value.strip()

    @field_validator("folder_path")
    @classmethod
    def normalize_folder_path(cls, value: str | None) -> str | None:
        """将空书签文件夹统一转换为空值。"""

        return normalize_optional_text(value)


class BookmarkImportRequest(BaseModel):
    """书签导入预览或确认请求。"""

    items: list[BookmarkInput] = Field(min_length=1, max_length=5_000)

    @model_validator(mode="after")
    def validate_client_item_ids(self) -> BookmarkImportRequest:
        """保证同一批次的客户端项目标识唯一。"""

        identifiers = [item.client_item_id for item in self.items]
        if any(not identifier for identifier in identifiers):
            raise ValueError("书签项目标识不能为空")
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("书签项目标识不能重复")
        return self


class BrowserBookmarkSyncRequest(BaseModel):
    """扩展提交的当前浏览器书签树快照。"""

    extension_id: str = Field(pattern=r"^[a-p]{32}$")
    items: list[BookmarkInput] = Field(default_factory=list, max_length=5_000)
    total_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_snapshot_count(self) -> BrowserBookmarkSyncRequest:
        """总数不能小于实际提交的书签数量。"""

        if self.total_count < len(self.items):
            raise ValueError("书签总数不能小于已提交数量")
        identifiers = [item.client_item_id for item in self.items]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("书签项目标识不能重复")
        return self


class BrowserBookmarkSyncResponse(BaseModel):
    """浏览器书签快照同步结果。"""

    synced_count: int
    truncated: bool


class BrowserBookmarkSnapshotRead(BaseModel):
    """Web 可直接导入的最近浏览器书签快照。"""

    extension_connected: bool
    synced_at: datetime | None
    total_count: int
    truncated: bool
    items: list[BookmarkInput]

    @field_serializer("synced_at")
    def serialize_utc_datetime(self, value: datetime | None) -> str | None:
        """统一输出书签快照同步时间。"""

        if value is None:
            return None
        resolved = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return resolved.astimezone(UTC).isoformat().replace("+00:00", "Z")


class BookmarkPreviewItem(BaseModel):
    """单条书签的导入校验结果。"""

    client_item_id: str
    title: str
    url: str
    normalized_url: str | None
    folder_path: str | None
    status: str
    existing_memo_id: UUID | None = None
    error_code: str | None = None


class BookmarkImportPreview(BaseModel):
    """书签文件确认导入前的去重预览。"""

    total_count: int
    valid_count: int
    duplicate_count: int
    invalid_count: int
    items: list[BookmarkPreviewItem]


class BookmarkImportItemRead(BaseModel):
    """已持久化书签导入项目。"""

    model_config = ConfigDict(from_attributes=True)

    client_item_id: str
    title: str
    source_url: str
    normalized_url: str
    folder_path: str | None
    status: str
    memo_id: UUID | None
    existing_memo_id: UUID | None
    error_code: str | None


class BookmarkImportBatchRead(BaseModel):
    """书签导入批次及其当前进度。"""

    id: UUID
    status: str
    total_count: int
    valid_count: int
    duplicate_count: int
    invalid_count: int
    imported_count: int
    failed_count: int
    created_at: datetime
    updated_at: datetime
    undone_at: datetime | None
    items: list[BookmarkImportItemRead]

    @field_serializer("created_at", "updated_at", "undone_at")
    def serialize_utc_datetime(self, value: datetime | None) -> str | None:
        """统一输出 UTC 时间字符串。"""

        if value is None:
            return None
        resolved = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return resolved.astimezone(UTC).isoformat().replace("+00:00", "Z")


class BrowserCaptureCreate(BaseModel):
    """扩展提交的当前网页一次性上下文。"""

    extension_id: str = Field(pattern=r"^[a-p]{32}$")
    tab_id: int | None = Field(default=None, ge=0)
    window_id: int | None = Field(default=None, ge=0)
    nonce: str = Field(min_length=16, max_length=100)
    page_url: str = Field(min_length=1, max_length=2_048)
    page_title: str = Field(default="", max_length=300)
    favicon_url: str | None = Field(default=None, max_length=2_048)

    @field_validator("page_url", "favicon_url")
    @classmethod
    def validate_capture_url(cls, value: str | None) -> str | None:
        """只接受扩展可明确识别的 HTTP(S) 页面地址。"""

        return normalize_source_url(value)

    @field_validator("page_title", "nonce")
    @classmethod
    def normalize_capture_text(cls, value: str) -> str:
        """清理扩展提交的短文本。"""

        return value.strip()


class BrowserCaptureCreated(BaseModel):
    """扩展创建一次性捕获后的短时凭据。"""

    token: str
    expires_at: datetime

    @field_serializer("expires_at")
    def serialize_utc_datetime(self, value: datetime) -> str:
        """统一输出令牌到期时间。"""

        resolved = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return resolved.astimezone(UTC).isoformat().replace("+00:00", "Z")


class BrowserCaptureExchangeRequest(BaseModel):
    """Web 使用一次性令牌交换网页附件。"""

    token: str = Field(min_length=32, max_length=200)


class BrowserCaptureContext(BaseModel):
    """Web 可附加到快速捕获的页面基础信息。"""

    page_url: str
    page_title: str
    favicon_url: str | None
    nonce: str


class BrowserTabSyncItem(BaseModel):
    """浏览器当前打开标签页的基础信息。"""

    tab_id: int = Field(ge=0)
    window_id: int | None = Field(default=None, ge=0)
    page_url: str = Field(min_length=1, max_length=2_048)
    page_title: str = Field(default="", max_length=300)
    favicon_url: str | None = Field(default=None, max_length=2_048)

    @field_validator("page_url", "favicon_url")
    @classmethod
    def normalize_tab_url(cls, value: str | None) -> str | None:
        """清理标签页地址，公网校验由服务端统一执行。"""

        return normalize_optional_text(value)

    @field_validator("page_title")
    @classmethod
    def normalize_tab_title(cls, value: str) -> str:
        """清理标签页标题。"""

        return " ".join(value.split()).strip()


class BrowserTabSyncRequest(BaseModel):
    """扩展提交的当前浏览器标签页快照。"""

    extension_id: str = Field(pattern=r"^[a-p]{32}$")
    tabs: list[BrowserTabSyncItem] = Field(default_factory=list, max_length=200)


class BrowserOpenTabRead(BaseModel):
    """Web 可选择的当前浏览器打开标签页。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tab_id: int
    window_id: int | None
    page_url: str
    page_title: str
    favicon_url: str | None
    last_seen_at: datetime

    @field_serializer("last_seen_at")
    def serialize_utc_datetime(self, value: datetime) -> str:
        """统一输出标签页最近同步时间。"""

        resolved = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return resolved.astimezone(UTC).isoformat().replace("+00:00", "Z")


class BrowserOpenTabListResponse(BaseModel):
    """当前浏览器打开标签页列表。"""

    items: list[BrowserOpenTabRead]


class BrowserTabSyncResponse(BaseModel):
    """浏览器标签页快照同步结果。"""

    synced_count: int


def normalize_optional_text(value: str | None) -> str | None:
    """将空白可选文本统一转换为 ``None``。"""

    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def normalize_source_url(value: str | None) -> str | None:
    """规范化并校验网页来源链接。"""

    cleaned = normalize_optional_text(value)
    if cleaned is None:
        return None
    parsed = urlsplit(cleaned)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise ValueError("来源链接必须是有效的 HTTP 或 HTTPS 地址")
    return cleaned
