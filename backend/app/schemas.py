"""API 数据模型。"""

from __future__ import annotations

import base64
import binascii
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationInfo,
    field_serializer,
    field_validator,
    model_validator,
)

from app.resource_classification_quality import (
    ClassificationAssessment,
    ClassificationConfirmation,
)
from app.resource_classification_retry import MAX_AUTOMATIC_RETRIES


def normalize_model_base_url(value: str | None) -> str | None:
    """校验基础地址，完整模型接口地址会去掉已知端点后缀。"""

    cleaned = (value or "").strip()
    if not cleaned:
        return None
    if any(char.isspace() or ord(char) < 32 for char in cleaned):
        raise ValueError("请求地址不能包含空白或控制字符")
    try:
        parsed = urlsplit(cleaned)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or "\\" in cleaned
            or parsed.port == 0
        ):
            raise ValueError("invalid_model_url")
    except ValueError as error:
        raise ValueError("请填写不含凭据或查询参数的 HTTP(S) 地址") from error
    path = parsed.path.rstrip("/")
    for endpoint in ("/chat/completions", "/systemone"):
        if path.endswith(endpoint):
            path = path.removesuffix(endpoint).rstrip("/")
            break
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


class ModelProvider(StrEnum):
    """设置页支持的分类模型服务。"""

    DEEPSEEK = "deepseek"
    JEV = "jev"


class ModelSettingUpdate(BaseModel):
    """保存模型配置；空密钥保留原有凭据。"""

    model: str = Field(min_length=1, max_length=200)
    enabled: bool = True
    api_key: SecretStr | None = None
    base_url: str | None = Field(default=None, max_length=2_048)
    # 低于该置信度的分类结果进人工确认中心；留空沿用原值。
    min_confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str | None) -> str | None:
        """留空恢复默认地址；同时兼容基础地址和完整接口地址。"""

        return normalize_model_base_url(value)

    @field_validator("model")
    @classmethod
    def validate_model(cls, value: str) -> str:
        """去除模型名称两端空白并拒绝空名称。"""

        cleaned = value.strip()
        if not cleaned:
            raise ValueError("请填写模型名称")
        return cleaned


class ModelSettingRead(BaseModel):
    """模型设置摘要，不返回明文或密文凭据。"""

    provider: ModelProvider
    model: str
    base_url: str
    default_base_url: str
    custom_base_url: str | None = None
    enabled: bool
    has_api_key: bool
    key_hint: str
    credential_source: Literal["account", "environment", "none"]
    has_custom_settings: bool
    error: str | None = None
    # 生效的自动分类置信度阈值，以及服务器默认值。
    min_confidence: float = 0.7
    default_min_confidence: float = 0.7


class ModelConnectionResult(BaseModel):
    """模型服务的最小请求测试结果。"""

    provider: ModelProvider
    model: str
    message: str


class AuthProvider(StrEnum):
    """支持的第三方登录提供方。"""

    GOOGLE = "google"
    WECHAT = "wechat"
    APPLE = "apple"


class AuthProviderInfo(BaseModel):
    """单个第三方登录入口信息。"""

    provider: AuthProvider
    label: str
    enabled: bool


class AuthProvidersResponse(BaseModel):
    """当前应用可用的登录方式。"""

    providers: list[AuthProviderInfo]
    dev_login_available: bool
    email_login_enabled: bool = True


class AuthUserResponse(BaseModel):
    """当前登录用户信息。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str | None
    email_verified: bool = False
    display_name: str
    created_at: datetime
    updated_at: datetime

    @field_serializer("created_at", "updated_at")
    def serialize_utc_datetime(self, value: datetime) -> str:
        """统一输出账号时间。"""

        resolved = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return resolved.astimezone(UTC).isoformat().replace("+00:00", "Z")


class AuthSessionResponse(BaseModel):
    """登录成功后返回的 Bearer 会话。"""

    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: AuthUserResponse

    @field_serializer("expires_at")
    def serialize_utc_datetime(self, value: datetime) -> str:
        """统一输出会话到期时间。"""

        resolved = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return resolved.astimezone(UTC).isoformat().replace("+00:00", "Z")


class EmailRegisterResponse(BaseModel):
    """邮箱验证码注册成功后的结果。"""

    user: AuthUserResponse


class AuthLogoutResponse(BaseModel):
    """退出登录结果。"""

    revoked: bool


class EmailRegisterRequest(BaseModel):
    """使用邮箱验证码注册请求。"""

    email: str = Field(min_length=5, max_length=320)
    password: str = Field(min_length=8, max_length=128)
    confirm_password: str = Field(min_length=8, max_length=128)
    verification_code: str = Field(
        min_length=6,
        max_length=6,
        pattern=r"^\d{6}$",
    )
    display_name: str | None = Field(default=None, max_length=120)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        """校验并统一邮箱格式。"""

        cleaned = value.strip().lower()
        if "@" not in cleaned or cleaned.startswith("@") or cleaned.endswith("@"):
            raise ValueError("请输入有效的邮箱地址")
        local, domain = cleaned.rsplit("@", 1)
        if not local or not domain or "." not in domain or " " in cleaned:
            raise ValueError("请输入有效的邮箱地址")
        return cleaned

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str | None) -> str | None:
        """清理可选昵称。"""

        return normalize_optional_text(value)

    @model_validator(mode="after")
    def validate_password_confirmation(self) -> EmailRegisterRequest:
        """确保两次输入的注册密码一致。"""

        if self.password != self.confirm_password:
            raise ValueError("两次输入的密码不一致")
        return self


class VerificationCodeRequest(BaseModel):
    """请求发送邮箱注册验证码。"""

    email: str = Field(min_length=5, max_length=320)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        """校验并统一邮箱格式。"""

        cleaned = value.strip().lower()
        if "@" not in cleaned or cleaned.startswith("@") or cleaned.endswith("@"):
            raise ValueError("请输入有效的邮箱地址")
        local, domain = cleaned.rsplit("@", 1)
        if not local or not domain or "." not in domain or " " in cleaned:
            raise ValueError("请输入有效的邮箱地址")
        return cleaned


class EmailLoginRequest(BaseModel):
    """邮箱登录请求。"""

    email: str = Field(min_length=5, max_length=320)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        """统一邮箱大小写和空白。"""

        return value.strip().lower()


class EmailTokenRequest(BaseModel):
    """请求邮件验证或密码重置链接。"""

    email: str = Field(min_length=5, max_length=320)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        """统一邮箱大小写和空白。"""

        return value.strip().lower()


class EmailTokenConfirmRequest(BaseModel):
    """提交邮件链接中的一次性令牌。"""

    token: str = Field(min_length=16, max_length=256)


class PasswordResetConfirmRequest(BaseModel):
    """提交密码重置令牌和新密码。"""

    token: str = Field(min_length=16, max_length=256)
    password: str = Field(min_length=8, max_length=128)
    confirm_password: str = Field(min_length=8, max_length=128)

    @model_validator(mode="after")
    def validate_password_confirmation(self) -> PasswordResetConfirmRequest:
        """确保两次输入的重置密码一致。"""

        if self.password != self.confirm_password:
            raise ValueError("两次输入的密码不一致")
        return self


class AuthActionResponse(BaseModel):
    """认证辅助操作的通用结果。"""

    status: str = "ok"


class MemoType(StrEnum):
    """条目类型。"""

    WORD = "word"
    RESOURCE = "resource"
    IDEA = "idea"
    IMAGE = "image"


class CloudProvider(StrEnum):
    """支持的云盘服务商。"""

    ALIYUN = "aliyun"
    BAIDU = "baidu"


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
    OPENED_DESC = "opened_desc"


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


class ResourceCategoryRuleMatchType(StrEnum):
    """用户分类规则的匹配范围。"""

    DOMAIN = "domain"
    URL = "url"
    TEXT = "text"


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


class ResourceClassificationJobRead(BaseModel):
    """网页批量模型分类的安全进度摘要。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    status: str
    model: str
    automatic: bool = False
    total_count: int
    processed_count: int
    succeeded_count: int
    failed_count: int
    skipped_count: int
    error: str | None
    error_code: str | None = None
    retry_count: int = 0
    retry_limit: int = MAX_AUTOMATIC_RETRIES
    next_retry_at: datetime | None = None
    created_at: datetime
    finished_at: datetime | None

    @field_serializer("created_at", "finished_at", "next_retry_at")
    def serialize_utc_datetime(self, value: datetime | None) -> str | None:
        """SQLite 时间按 UTC 输出，保证浏览器正确显示重试等待时间。"""

        if value is None:
            return None
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).isoformat().replace("+00:00", "Z")


class ResourceClassificationState(BaseModel):
    """当前账号待处理网页数量和最近一次任务。"""

    pending_count: int
    classified_count: int
    protected_count: int
    deferred_count: int = 0
    review_count: int = 0
    classified_retry_count: int = 0
    folder_retry_count: int = 0
    job: ResourceClassificationJobRead | None


class BookmarkFolderMappingRead(BaseModel):
    """一个书签文件夹或标签对应的分类。"""

    key: str
    kind: Literal["folder", "tag"]
    text: str
    page_count: int
    # pending 还没判断；mapped 对应到分类；unmapped 没有对应分类或设为不沿用。
    status: Literal["pending", "mapped", "unmapped"]
    source: Literal["jev", "manual"] | None
    category_code: str | None
    category_label: str | None
    confidence: float | None


class BookmarkFolderMappingList(BaseModel):
    """书签原归类的对应关系总览。"""

    items: list[BookmarkFolderMappingRead]
    categories: list[dict[str, str]]
    pending_count: int
    page_count: int
    retry_count: int


class BookmarkFolderOverrideRequest(BaseModel):
    """手动指定对应分类、设为不沿用，或恢复由 Jev 判断。"""

    key: str = Field(min_length=1, max_length=1_000)
    mode: Literal["category", "skip", "auto"]
    category_code: str | None = Field(default=None, max_length=50)


class ResourceClassificationReviewCandidate(BaseModel):
    """显示当前模板路径与候选可用性，停用的类别不能采纳。"""

    code: str
    label: str
    probability: float | None = Field(default=None, ge=0, le=1)
    available: bool


class ResourceClassificationReviewItem(BaseModel):
    """复核只读取本人网页与分类证据，不返回私人备注或模型凭据。"""

    id: UUID
    version: int
    title: str
    source_url: str
    current_category_label: str | None
    assessment: ClassificationAssessment | None
    candidates: list[ResourceClassificationReviewCandidate]


class ResourceClassificationReviewList(BaseModel):
    """筛选后的完整总数与分页结果。"""

    items: list[ResourceClassificationReviewItem]
    total_count: int
    limit: int
    offset: int


class ResourceClassificationReviewSelection(BaseModel):
    """使用用户所见版本和可选候选编码保护批量确认。"""

    memo_id: UUID
    expected_version: int = Field(ge=1)
    candidate_code: str | None = Field(default=None, max_length=100)


class ResourceClassificationReviewRequest(BaseModel):
    """每次只确认明确选中的条目，不隐式操作全部筛选结果。"""

    action: Literal["adopt", "keep", "assign"]
    items: list[ResourceClassificationReviewSelection] = Field(
        min_length=1,
        max_length=100,
    )
    category_code: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def validate_review_request(self) -> ResourceClassificationReviewRequest:
        """拒绝重复条目和缺少目标分类的请求，避免重复提交或误操作。"""

        if len({item.memo_id for item in self.items}) != len(self.items):
            raise ValueError("同一批次不能重复选择网页")
        if self.action == "assign" and not self.category_code:
            raise ValueError("请指定目标分类")
        if self.action != "assign" and self.category_code is not None:
            raise ValueError("当前操作不需要指定统一分类")
        return self


class ResourceClassificationReviewResultItem(BaseModel):
    """逐项返回安全原因，版本变化或巡检异常不会被覆盖。"""

    memo_id: UUID
    status: Literal["updated", "skipped"]
    reason: (
        Literal[
            "missing",
            "conflict",
            "not_pending",
            "no_candidate",
            "category_unavailable",
        ]
        | None
    ) = None


class ResourceClassificationReviewResult(BaseModel):
    """部分条目不再适用时，其余符合条件的选择仍可一次完成。"""

    updated_count: int
    skipped_count: int
    results: list[ResourceClassificationReviewResultItem]


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
    # 图片收藏允许只上传图片，正文可以留空。
    body: str = Field(default="", max_length=50_000)
    transcript: str | None = Field(default=None, max_length=50_000)
    source_url: str | None = Field(default=None, max_length=2_048)
    source_title: str | None = Field(default=None, max_length=200)
    word_phonetic: str | None = Field(default=None, max_length=120)
    word_meaning: str | None = Field(default=None, max_length=5_000)
    word_example: str | None = Field(default=None, max_length=5_000)
    allow_duplicate: bool = False
    tags: list[str] = Field(default_factory=list, max_length=20)
    collections: list[str] = Field(default_factory=list, max_length=20)
    resource_kind: ResourceKind | None = None
    resource_reading_status: ResourceReadingStatus | None = None
    starred: bool = False

    @field_validator("body")
    @classmethod
    def validate_body(cls, value: str, info: ValidationInfo) -> str:
        """拒绝只有空白字符的正文；图片收藏允许正文为空。"""

        cleaned = value.strip()
        if not cleaned and info.data.get("type") != MemoType.IMAGE:
            raise ValueError("正文不能为空")
        return cleaned

    @field_validator("transcript")
    @classmethod
    def normalize_transcript(cls, value: str | None) -> str | None:
        """清理可选转写文本，拒绝只有空白的转写。"""

        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

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

    @field_validator("title", "source_title", mode="before")
    @classmethod
    def normalize_titles(cls, value: object) -> object:
        """浏览器标题常超过字段上限，截断后仍可收藏。"""

        return truncate_optional_text(value, 200)

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
    type: MemoType | None = None
    title: str | None = Field(default=None, max_length=200)
    body: str | None = Field(default=None, max_length=50_000)
    source_url: str | None = Field(default=None, max_length=2_048)
    source_title: str | None = Field(default=None, max_length=200)
    word_phonetic: str | None = Field(default=None, max_length=120)
    word_meaning: str | None = Field(default=None, max_length=5_000)
    word_example: str | None = Field(default=None, max_length=5_000)
    resource_category: str | None = Field(default=None, max_length=50)
    resource_categories: list[str] | None = Field(default=None, max_length=8)
    resource_kind: ResourceKind | None = None
    resource_reading_status: ResourceReadingStatus | None = None
    tags: list[str] | None = Field(default=None, max_length=20)
    collections: list[str] | None = Field(default=None, max_length=20)
    starred: bool | None = None
    status: MemoStatus | None = None

    @field_validator("body")
    @classmethod
    def validate_optional_body(cls, value: str | None) -> str | None:
        """更新正文时清理首尾空白；允许清空正文。"""

        if value is None:
            return None
        return value.strip()

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

    @field_validator("title", "source_title", mode="before")
    @classmethod
    def normalize_titles(cls, value: object) -> object:
        """更新时同样截断过长标题，避免编辑网页资料时 422。"""

        return truncate_optional_text(value, 200)

    @field_validator("resource_category")
    @classmethod
    def normalize_resource_category(cls, value: str | None) -> str | None:
        """清理系统或用户自定义的分类编码。"""

        return normalize_optional_text(value)

    @field_validator("resource_categories")
    @classmethod
    def normalize_resource_categories(
        cls,
        value: list[str] | None,
    ) -> list[str] | None:
        """去重并清理多分类编码，保留用户选择顺序。"""

        if value is None:
            return None
        return list(
            dict.fromkeys(
                code for item in value if (code := normalize_optional_text(item))
            ),
        )

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
    resource_category: str | None
    resource_category_label: str | None
    resource_categories: list[str] = Field(default_factory=list)
    resource_category_status: ResourceProcessStatus
    resource_category_confidence: float | None
    resource_category_source: str | None
    resource_ai_classified_at: datetime | None = None
    resource_ai_review_required: bool = False
    resource_text_excerpt: str | None = None
    resource_ai_assessment: ClassificationAssessment | None = None
    resource_ai_confirmation_pending: bool = False
    resource_ai_confirmation: ClassificationConfirmation | None = None
    resource_kind: ResourceKind | None
    resource_reading_status: ResourceReadingStatus | None
    resource_auto_tags: list[str]
    resource_last_enriched_at: datetime | None
    resource_import_folder: str | None
    resource_import_tags: list[str] = Field(default_factory=list)
    resource_import_batch_id: UUID | None
    # 电子书：只暴露云盘文件引用与元数据快照，不含电子书本体。
    ebook_provider: CloudProvider | None
    ebook_file_id: str | None
    ebook_path: str | None
    ebook_share_url: str | None
    ebook_format: str | None
    ebook_size_bytes: int | None
    ebook_snapshot: dict[str, object] | None
    link_health_status: LinkHealthStatus
    link_health_http_status: int | None
    link_health_error: str | None
    link_last_checked_at: datetime | None
    link_last_success_at: datetime | None
    link_next_check_at: datetime | None
    link_consecutive_failures: int
    link_effective_url: str | None
    word_phonetic: str | None
    word_us_audio_url: str | None
    word_uk_audio_url: str | None
    word_meaning: str | None
    word_example: str | None
    familiarity: int
    review_count: int
    last_review_at: datetime | None
    next_review_at: datetime | None
    audio_mime_type: str | None
    audio_size_bytes: int | None
    audio_duration_ms: int | None
    image_mime_type: str | None
    image_size_bytes: int | None
    image_width: int | None
    image_height: int | None
    image_hash: str | None
    image_ocr_text: str | None
    image_ocr_status: str
    image_ocr_error: str | None
    image_ocr_source: str | None
    image_auto_tags: list[str]
    image_ocr_updated_at: datetime | None
    transcript: str | None
    transcript_status: str
    tags: list[str]
    collections: list[str]
    starred: bool
    resource_open_count: int = 0
    resource_last_opened_at: datetime | None = None
    resource_quick_access_hidden: bool = False
    status: MemoStatus
    deleted_at: datetime | None = None
    version: int
    created_at: datetime
    updated_at: datetime

    @field_validator("resource_categories", mode="before")
    @classmethod
    def default_resource_categories(cls, value: object) -> object:
        """旧数据没有多分类字段时按空列表返回。"""

        return value or []

    @field_validator("image_auto_tags", mode="before")
    @classmethod
    def default_image_auto_tags(cls, value: object) -> object:
        """旧数据没有图片自动标签字段时按空列表返回。"""

        return value or []

    @field_serializer(
        "created_at",
        "updated_at",
        "deleted_at",
        "last_review_at",
        "next_review_at",
        "resource_last_enriched_at",
        "link_last_checked_at",
        "link_last_success_at",
        "link_next_check_at",
        "image_ocr_updated_at",
        "resource_last_opened_at",
    )
    def serialize_utc_datetime(self, value: datetime | None) -> str | None:
        """SQLite 返回无时区时间时，按服务端统一的 UTC 约定输出。"""

        if value is None:
            return None
        resolved = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return resolved.astimezone(UTC).isoformat().replace("+00:00", "Z")


class ResourceOpenRead(BaseModel):
    """记录一次网页资料打开后的统计。"""

    resource_open_count: int
    resource_last_opened_at: datetime

    @field_serializer("resource_last_opened_at")
    def serialize_opened_at(self, value: datetime) -> str:
        """与条目时间字段一致，统一输出 UTC。"""

        resolved = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return resolved.astimezone(UTC).isoformat().replace("+00:00", "Z")


class ResourceQuickAccessUpdate(BaseModel):
    """从快速访问移除或恢复一条网页资料。"""

    hidden: bool


class ResourceQuickAccessRead(BaseModel):
    """快速访问显示状态。"""

    resource_quick_access_hidden: bool


class MemoListResponse(BaseModel):
    """条目列表响应。"""

    items: list[MemoRead]
    total_count: int


class MemoCountsResponse(BaseModel):
    """当前用户各内容类型的数量。"""

    total_count: int
    word_count: int
    resource_count: int
    idea_count: int
    image_count: int = 0
    inbox_count: int = 0


class ResourceCategoryRead(BaseModel):
    """Web 可使用的系统或用户分类。"""

    id: UUID | None
    code: str
    name: str
    description: str | None
    definition: str | None = None
    include_examples: str | None = None
    exclude_examples: str | None = None
    is_system: bool
    is_active: bool
    version: int
    parent_code: str | None = None
    depth: int = 1
    path: str = ""


class ResourceCategoryCreate(BaseModel):
    """创建用户网页资料分类。"""

    name: str = Field(min_length=1, max_length=50)
    description: str | None = Field(default=None, max_length=300)
    definition: str | None = Field(default=None, max_length=600)
    include_examples: str | None = Field(default=None, max_length=800)
    exclude_examples: str | None = Field(default=None, max_length=800)
    parent_code: str | None = Field(default=None, max_length=50)

    @field_validator(
        "name",
        "description",
        "definition",
        "include_examples",
        "exclude_examples",
        "parent_code",
    )
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        """清理分类名称、说明、口径与父分类。"""

        return normalize_optional_text(value)


class ResourceCategoryGenerateMode(StrEnum):
    """聚类分两步：先确认顶级分类，够用后再细分。"""

    TOP_LEVEL = "top_level"
    SUBCATEGORIES = "subcategories"


class ResourceCategoryGenerateRequest(BaseModel):
    """根据整理要求和收藏网页聚类生成分类模板建议。"""

    instructions: str = Field(default="", max_length=2_000)
    max_categories: int = Field(default=12, ge=1, le=12)
    mode: ResourceCategoryGenerateMode = ResourceCategoryGenerateMode.SUBCATEGORIES

    @field_validator("instructions")
    @classmethod
    def normalize_instructions(cls, value: str) -> str:
        """允许留空，空要求时改用收藏网页聚类。"""

        return value.strip()


class ResourceCategorySuggestion(ResourceCategoryCreate):
    """聚类标签；已有模板带 existing_code，examples 便于对照网页。"""

    existing_code: str | None = Field(default=None, max_length=80)
    examples: list[str] = Field(default_factory=list, max_length=5)


class ResourceCategoryGenerateResponse(BaseModel):
    """模型生成的类别建议；使用现有创建接口加入模板。"""

    model: str
    categories: list[ResourceCategorySuggestion] = Field(max_length=12)


class ResourceCategoryUpdate(BaseModel):
    """更新用户网页资料分类。"""

    expected_version: int = Field(ge=1)
    name: str | None = Field(default=None, max_length=50)
    description: str | None = Field(default=None, max_length=300)
    definition: str | None = Field(default=None, max_length=600)
    include_examples: str | None = Field(default=None, max_length=800)
    exclude_examples: str | None = Field(default=None, max_length=800)
    is_active: bool | None = None
    parent_code: str | None = Field(default=None, max_length=50)

    @field_validator(
        "name",
        "description",
        "definition",
        "include_examples",
        "exclude_examples",
        "parent_code",
    )
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        """清理分类名称、说明、口径和父分类。"""

        return normalize_optional_text(value)


class ResourceCategoryRuleCreate(BaseModel):
    """创建用户网页资料分类规则。"""

    name: str | None = Field(default=None, max_length=100)
    category_code: str = Field(min_length=1, max_length=50)
    match_type: ResourceCategoryRuleMatchType
    pattern: str = Field(min_length=1, max_length=500)
    priority: int = Field(default=100, ge=0, le=10_000)
    enabled: bool = True

    @field_validator("name", "category_code", "pattern")
    @classmethod
    def normalize_rule_text(cls, value: str | None) -> str | None:
        """清理规则名称、分类编码和匹配内容。"""

        return normalize_optional_text(value)


class ResourceCategoryRuleUpdate(BaseModel):
    """更新用户网页资料分类规则。"""

    expected_version: int = Field(ge=1)
    name: str | None = Field(default=None, max_length=100)
    category_code: str | None = Field(default=None, max_length=50)
    match_type: ResourceCategoryRuleMatchType | None = None
    pattern: str | None = Field(default=None, max_length=500)
    priority: int | None = Field(default=None, ge=0, le=10_000)
    enabled: bool | None = None

    @field_validator("name", "category_code", "pattern")
    @classmethod
    def normalize_rule_text(cls, value: str | None) -> str | None:
        """清理规则名称、分类编码和匹配内容。"""

        return normalize_optional_text(value)


class ResourceCategoryRuleRead(BaseModel):
    """返回给 Web 的用户分类规则。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    category_code: str
    category_label: str
    match_type: ResourceCategoryRuleMatchType
    pattern: str
    priority: int
    enabled: bool
    version: int
    created_at: datetime
    updated_at: datetime

    @field_serializer("created_at", "updated_at")
    def serialize_utc_datetime(self, value: datetime) -> str:
        """统一输出分类规则时间。"""

        resolved = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return resolved.astimezone(UTC).isoformat().replace("+00:00", "Z")


class CloudAccountRead(BaseModel):
    """返回给前端的云盘绑定；只暴露脱敏提示，不含凭据明文。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    provider: CloudProvider
    display_name: str
    credential_hint: str
    default_folder: str
    status: str
    last_checked_at: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime

    @field_serializer("last_checked_at", "created_at", "updated_at")
    def serialize_utc_datetime(self, value: datetime | None) -> str | None:
        """统一输出云盘绑定时间。"""

        if value is None:
            return None
        resolved = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return resolved.astimezone(UTC).isoformat().replace("+00:00", "Z")


class CloudAccountCreate(BaseModel):
    """绑定云盘账号请求。"""

    provider: CloudProvider
    credential: str = Field(min_length=1, max_length=8_000)
    default_folder: str | None = Field(default=None, max_length=500)


class EbookJobMode(StrEnum):
    """电子书任务的来源形态。"""

    TRANSFER = "transfer"
    UPLOAD = "upload"


class EbookJobStatus(StrEnum):
    """电子书任务状态。"""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class EbookJobCreate(BaseModel):
    """提交电子书链接。"""

    url: str = Field(min_length=1, max_length=2_048)
    provider: CloudProvider | None = None
    share_password: str | None = Field(default=None, max_length=100)
    target_folder: str | None = Field(default=None, max_length=500)
    tags: list[str] = Field(default_factory=list, max_length=20)
    collections: list[str] = Field(default_factory=list, max_length=20)
    note: str | None = Field(default=None, max_length=5_000)


class EbookJobRead(BaseModel):
    """返回给前端的电子书任务状态。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    memo_id: UUID | None
    source_url: str
    provider: CloudProvider
    mode: EbookJobMode
    status: EbookJobStatus
    progress: int
    stage: str
    target_folder: str
    cloud_file_id: str | None
    cloud_path: str | None
    error: str | None
    attempts: int
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None

    @field_serializer("created_at", "updated_at", "finished_at")
    def serialize_utc_datetime(self, value: datetime | None) -> str | None:
        """统一输出任务时间。"""

        if value is None:
            return None
        resolved = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return resolved.astimezone(UTC).isoformat().replace("+00:00", "Z")


class LinkHealthSettingsResponse(BaseModel):
    """当前账号的网页巡检开关、频率和站点暂停配置。"""

    enabled: bool
    interval_hours: int = Field(ge=1, le=24 * 365)
    paused_sites: list[str]


class LinkHealthSettingsUpdate(BaseModel):
    """更新当前账号网页巡检设置。"""

    enabled: bool | None = None
    interval_hours: int | None = Field(default=None, ge=1, le=24 * 365)

    @model_validator(mode="after")
    def require_setting(self) -> LinkHealthSettingsUpdate:
        """拒绝没有任何设置变更的请求。"""

        if self.enabled is None and self.interval_hours is None:
            raise ValueError("至少提供一个巡检设置")
        return self


class LinkHealthSitePauseRequest(BaseModel):
    """暂停或恢复某个网站的网页巡检。"""

    hostname: str = Field(min_length=1, max_length=253)
    paused: bool = True

    @field_validator("hostname")
    @classmethod
    def normalize_hostname(cls, value: str) -> str:
        """规范化网站主机名，避免把路径或协议写入暂停配置。"""

        cleaned = value.strip().lower().rstrip(".")
        if (
            not cleaned
            or any(
                not (character.isalnum() or character in {".", "-", "_"})
                for character in cleaned
            )
            or cleaned.startswith(".")
            or cleaned.endswith(".")
        ):
            raise ValueError("网站主机名格式不正确")
        return cleaned


class LinkHealthListResponse(BaseModel):
    """网页巡检中心列表与状态摘要。"""

    items: list[MemoRead]
    counts: dict[str, int]
    settings: LinkHealthSettingsResponse


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


class MemoDeletionRead(BaseModel):
    """同步永久删除通知，不包含已删除的正文或附件信息。"""

    model_config = ConfigDict(from_attributes=True)
    memo_id: UUID
    client_id: UUID
    deleted_at: datetime

    @field_serializer("deleted_at")
    def serialize_deleted_at(self, value: datetime) -> str:
        """SQLite 无时区时间统一解释为 UTC。"""

        return value.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")


class ImageOrganizationJobRead(BaseModel):
    """不返回完整队列、存储文件名或模型凭据。"""

    model_config = ConfigDict(from_attributes=True)
    id: UUID
    action: Literal["ocr", "classify", "ocr_classify"]
    status: Literal["pending", "processing", "completed", "failed"]
    total_count: int
    processed_count: int
    succeeded_count: int
    failed_count: int
    skipped_count: int
    error: str | None


class MemoBatchSelection(BaseModel):
    """用户明确选择的条目与所见版本。"""

    memo_id: UUID
    expected_version: int = Field(ge=1)


class MemoBatchRequest(BaseModel):
    """只对选中条目操作，不隐式覆盖筛选结果或整个回收站。"""

    action: Literal["trash", "restore", "permanent"]
    items: list[MemoBatchSelection] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_items(self) -> MemoBatchRequest:
        """重复标识会造成重复版本操作，因此整批拒绝。"""

        if len({item.memo_id for item in self.items}) != len(self.items):
            raise ValueError("不能重复选择同一条内容")
        return self


class MemoBatchResultItem(BaseModel):
    """冲突和状态变化只返回固定编码。"""

    memo_id: UUID
    status: Literal["updated", "skipped"]
    reason: Literal["missing", "conflict", "not_applicable"] | None = None


class MemoBatchResult(BaseModel):
    """选中条目操作的汇总及逐项结果。"""

    updated_count: int
    skipped_count: int
    results: list[MemoBatchResultItem]


class ImageOrganizationRequest(BaseModel):
    """全库处理未完成图片，或只处理显式勾选的版本。"""

    action: Literal["ocr", "classify", "ocr_classify"] = "ocr"
    scope: Literal["all", "selected"] = "selected"
    items: list[MemoBatchSelection] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_selection(self) -> ImageOrganizationRequest:
        """拒绝空选择、重复选择及含糊的全库请求。"""

        if self.scope == "selected" and not self.items:
            raise ValueError("请选择需要处理的图片")
        if self.scope == "all" and self.items:
            raise ValueError("全库处理不需要选择条目")
        if len({item.memo_id for item in self.items}) != len(self.items):
            raise ValueError("不能重复选择同一张图片")
        return self


class ImageOrganizationState(BaseModel):
    """当前账号图片整理进度与未完成数量。"""

    pending_ocr_count: int
    pending_classification_count: int
    duplicate_group_count: int
    job: ImageOrganizationJobRead | None


class ImageDuplicateItem(BaseModel):
    """重复组只显示本人图片的名称和版本，不暴露附件存储路径。"""

    model_config = ConfigDict(from_attributes=True)
    id: UUID
    title: str
    version: int


class ImageDuplicateGroup(BaseModel):
    image_hash: str
    count: int
    items: list[ImageDuplicateItem]


class ImageDuplicateList(BaseModel):
    groups: list[ImageDuplicateGroup]
    total_count: int
    offset: int
    limit: int


class SyncResponse(BaseModel):
    """增量同步响应。"""

    items: list[MemoRead]
    cursor: datetime
    cursor_id: UUID | None = None
    deleted_items: list[MemoDeletionRead] = Field(default_factory=list)
    has_more: bool = False


class WordReviewRequest(BaseModel):
    """提交单词复习反馈。"""

    expected_version: int = Field(ge=1)
    feedback: ReviewFeedback


class WordLookupRequest(BaseModel):
    """请求预览词典中的单词释义。"""

    word: str = Field(min_length=1, max_length=200)

    @field_validator("word")
    @classmethod
    def normalize_lookup_word(cls, value: str) -> str:
        """合并多余空白，保留用户输入的词形用于界面展示。"""

        cleaned = " ".join(value.strip().split())
        if not cleaned:
            raise ValueError("请输入英语单词或短语")
        return cleaned


class WordDictionarySenseRead(BaseModel):
    """单个可供用户选择的词典释义。"""

    index: int = Field(ge=0)
    part_of_speech: str | None = None
    definition: str
    example: str | None = None


class WordLookupResponse(BaseModel):
    """单词查词预览结果。"""

    word: str
    lemma: str
    phonetic: str | None
    us_audio_url: str | None
    uk_audio_url: str | None
    senses: list[WordDictionarySenseRead]
    source_name: str | None = None
    source_url: str | None = None


class WordImportErrorRead(BaseModel):
    """单词批量导入中的单行错误。"""

    row: int = Field(ge=1)
    message: str


class WordImportResponse(BaseModel):
    """单词批量导入结果摘要。"""

    total_count: int = Field(ge=0)
    imported_count: int = Field(ge=0)
    duplicate_count: int = Field(ge=0)
    skipped_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    errors: list[WordImportErrorRead] = Field(default_factory=list, max_length=50)


class SpeechTtsRequest(BaseModel):
    """请求服务端生成一段可播放的语音。"""

    text: str = Field(min_length=1, max_length=2_000)
    voice: str | None = Field(default=None, max_length=64)

    @field_validator("text", "voice")
    @classmethod
    def normalize_speech_text(cls, value: str | None) -> str | None:
        """清理语音文本，避免把多余空白送入模型。"""

        return " ".join(value.split()) if value is not None else None


class MeetingSummaryRequest(BaseModel):
    """请求生成一份会议纪要。"""

    title: str | None = Field(default=None, max_length=200)
    transcript: str = Field(min_length=1, max_length=50_000)

    @field_validator("title")
    @classmethod
    def normalize_meeting_title(cls, value: str | None) -> str | None:
        """清理可选的会议标题。"""

        if value is None:
            return None
        cleaned = " ".join(value.split())
        return cleaned or None

    @field_validator("transcript")
    @classmethod
    def normalize_meeting_transcript(cls, value: str) -> str:
        """清理会议转写文本。"""

        cleaned = value.strip()
        if not cleaned:
            raise ValueError("会议转写不能为空")
        return cleaned


class MeetingSummaryResponse(BaseModel):
    """会议纪要生成结果。"""

    summary: str = Field(min_length=1, max_length=20_000)


class WordMergeRequest(BaseModel):
    """把新语境合并进已有单词。"""

    expected_version: int = Field(ge=1)
    word_phonetic: str | None = Field(default=None, max_length=120)
    word_meaning: str | None = Field(default=None, max_length=5_000)
    word_example: str | None = Field(default=None, max_length=5_000)
    source_url: str | None = Field(default=None, max_length=2_048)
    source_title: str | None = Field(default=None, max_length=200)

    @field_validator("word_phonetic", "word_meaning", "word_example", "source_title")
    @classmethod
    def normalize_merge_text(cls, value: str | None) -> str | None:
        """清理合并进已有单词的可选文本。"""

        return normalize_optional_text(value)

    @field_validator("source_url")
    @classmethod
    def validate_merge_source_url(cls, value: str | None) -> str | None:
        """合并来源链接时只接受 HTTP(S)。"""

        return normalize_source_url(value)


class ReviewSkipRequest(BaseModel):
    """跳过今日回顾中的一条内容。"""

    expected_version: int = Field(ge=1)


class ReviewQueueResponse(BaseModel):
    """今日回顾队列，混合到期单词、未读资料和待整理灵感。"""

    items: list[MemoRead]
    word_count: int = 0
    resource_count: int = 0
    idea_count: int = 0
    daily_limit: int = Field(default=10, ge=1, le=100)
    scheduled_count: int = Field(default=0, ge=0)


class ReviewSettingsResponse(BaseModel):
    """当前账号的自定义复习计划。"""

    daily_limit: int = Field(ge=1, le=100)
    intervals_days: list[int] = Field(min_length=6, max_length=6)

    @field_validator("intervals_days")
    @classmethod
    def validate_intervals_days(cls, value: list[int]) -> list[int]:
        """限制复习间隔为 1 到 365 天，避免误配置造成极端队列。"""

        if any(interval < 1 or interval > 365 for interval in value):
            raise ValueError("复习间隔必须在 1 到 365 天之间")
        return value


class ReviewSettingsUpdate(BaseModel):
    """更新当前账号的自定义复习计划。"""

    daily_limit: int | None = Field(default=None, ge=1, le=100)
    intervals_days: list[int] | None = Field(
        default=None,
        min_length=6,
        max_length=6,
    )

    @field_validator("intervals_days")
    @classmethod
    def validate_intervals_days(cls, value: list[int] | None) -> list[int] | None:
        """限制复习间隔为 1 到 365 天。"""

        if value is not None and any(
            interval < 1 or interval > 365 for interval in value
        ):
            raise ValueError("复习间隔必须在 1 到 365 天之间")
        return value

    @model_validator(mode="after")
    def require_setting(self) -> ReviewSettingsUpdate:
        """拒绝没有任何设置变更的请求。"""

        if self.daily_limit is None and self.intervals_days is None:
            raise ValueError("至少提供一个复习计划设置")
        return self


class BookmarkInput(BaseModel):
    """浏览器本地解析后提交的一条 Chrome 书签。"""

    client_item_id: str = Field(min_length=1, max_length=100)
    title: str = Field(default="", max_length=300)
    url: str = Field(max_length=2_048)
    folder_path: str | None = Field(default=None, max_length=1_000)
    # Firefox 导出的书签带 TAGS 属性；Chrome/Edge 没有标签。
    tags: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("tags")
    @classmethod
    def normalize_bookmark_tags(cls, value: list[str]) -> list[str]:
        """去掉空标签，按顺序去重并限长。"""

        cleaned = (" ".join(tag.split())[:50] for tag in value)
        return list(dict.fromkeys(tag for tag in cleaned if tag))

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


class BrowserBookmarkDeltaChange(BaseModel):
    """扩展提交的一条书签增量变更。"""

    action: Literal["upsert", "remove"]
    client_item_id: str = Field(min_length=1, max_length=100)
    item: BookmarkInput | None = None

    @model_validator(mode="after")
    def validate_delta_item(self) -> BrowserBookmarkDeltaChange:
        """新增或更新必须带完整书签，删除不能携带书签正文。"""

        if self.action == "upsert":
            if self.item is None:
                raise ValueError("新增或更新书签必须提供完整项目")
            if self.item.client_item_id != self.client_item_id:
                raise ValueError("书签变更标识与项目标识不一致")
        elif self.item is not None:
            raise ValueError("删除书签不能携带项目正文")
        return self


class BrowserBookmarkDeltaSyncRequest(BaseModel):
    """扩展提交的带版本校验的书签增量变更。"""

    extension_id: str = Field(pattern=r"^[a-p]{32}$")
    base_revision: int = Field(ge=0)
    total_count: int = Field(ge=0)
    changes: list[BrowserBookmarkDeltaChange] = Field(
        default_factory=list,
        max_length=1_000,
    )

    @model_validator(mode="after")
    def validate_delta_ids(self) -> BrowserBookmarkDeltaSyncRequest:
        """同一批次不能重复操作同一书签，避免顺序依赖。"""

        identifiers = [change.client_item_id for change in self.changes]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("同一批次不能重复变更书签")
        return self


class BrowserBookmarkSyncResponse(BaseModel):
    """浏览器书签快照同步结果。"""

    synced_count: int
    truncated: bool
    total_count: int
    revision: int


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

    @field_validator("page_url")
    @classmethod
    def validate_capture_url(cls, value: str | None) -> str | None:
        """只接受扩展可明确识别的 HTTP(S) 页面地址。"""

        return normalize_source_url(value)

    @field_validator("favicon_url", mode="before")
    @classmethod
    def normalize_capture_favicon(cls, value: object) -> object:
        """图标过长或非公网地址时丢弃，不阻止当前页收藏。"""

        if value is None:
            return None
        if not isinstance(value, str):
            return value
        cleaned = value.strip()
        if not cleaned or len(cleaned) > 2_048:
            return None
        try:
            return normalize_source_url(cleaned)
        except ValueError:
            return None

    @field_validator("page_title", mode="before")
    @classmethod
    def normalize_capture_title(cls, value: object) -> object:
        """浏览器标题可能超过 300 字，截断后仍可授权收藏。"""

        if not isinstance(value, str):
            return value
        return " ".join(value.split()).strip()[:300]

    @field_validator("nonce")
    @classmethod
    def normalize_capture_nonce(cls, value: str) -> str:
        """清理扩展提交的一次性随机数。"""

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

    @field_validator("page_url")
    @classmethod
    def normalize_tab_url(cls, value: str | None) -> str | None:
        """清理标签页地址，公网校验由服务端统一执行。"""

        return normalize_optional_text(value)

    @field_validator("favicon_url", mode="before")
    @classmethod
    def normalize_tab_favicon(cls, value: object) -> object:
        """data: 图标常超过 2048，丢弃后不影响标签页进入选择器。"""

        if value is None:
            return None
        if not isinstance(value, str):
            return value
        cleaned = value.strip()
        if not cleaned or len(cleaned) > 2_048:
            return None
        return cleaned

    @field_validator("page_title", mode="before")
    @classmethod
    def normalize_tab_title(cls, value: object) -> object:
        """清理并截断标签页标题。"""

        if not isinstance(value, str):
            return value
        return " ".join(value.split()).strip()[:300]


class BrowserTabSyncRequest(BaseModel):
    """扩展提交的当前浏览器标签页快照。"""

    extension_id: str = Field(pattern=r"^[a-p]{32}$")
    tabs: list[BrowserTabSyncItem] = Field(default_factory=list, max_length=200)

    @field_validator("tabs", mode="before")
    @classmethod
    def coerce_open_tabs(cls, value: object) -> object:
        """丢掉超长网址，避免一张快照里的异常标签让整个同步 422。"""

        if not isinstance(value, list):
            return value
        cleaned: list[object] = []
        for item in value:
            if isinstance(item, dict):
                url = item.get("page_url")
                if isinstance(url, str) and len(url.strip()) > 2_048:
                    continue
            cleaned.append(item)
            if len(cleaned) >= 200:
                break
        return cleaned


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


class BrowserHistoryVisitInput(BaseModel):
    """扩展上报的一次浏览记录。"""

    page_url: str = Field(min_length=1, max_length=2_048)
    page_title: str = Field(default="", max_length=300)
    favicon_url: str | None = Field(default=None, max_length=2_048)
    # 扩展本地读取的访问时间，缺失时由服务端按接收时间补齐。
    visited_at: datetime | None = None
    # 浏览器统计的该网址累计访问次数；重复上报时服务端取较大值。
    visit_count: int = Field(default=1, ge=1, le=1_000_000)

    @field_validator("page_url", mode="before")
    @classmethod
    def normalize_visit_url(cls, value: object) -> object:
        """清理空白地址，公网校验由服务端统一执行。"""

        if not isinstance(value, str):
            return value
        return value.strip()

    @field_validator("favicon_url", mode="before")
    @classmethod
    def normalize_visit_favicon(cls, value: object) -> object:
        """data: 图标常超过 2048，丢弃后不影响历史条目。"""

        if value is None:
            return None
        if not isinstance(value, str):
            return value
        cleaned = value.strip()
        if not cleaned or len(cleaned) > 2_048:
            return None
        return cleaned

    @field_validator("page_title", mode="before")
    @classmethod
    def normalize_visit_title(cls, value: object) -> object:
        """清理并截断标题。"""

        if not isinstance(value, str):
            return value
        return " ".join(value.split()).strip()[:300]


class BrowserHistorySyncRequest(BaseModel):
    """扩展提交的一批浏览记录。"""

    extension_id: str = Field(pattern=r"^[a-p]{32}$")
    # 扩展实例标识：不同电脑各自一个，用来隔离同一账号的历史。
    device_id: str = Field(default="legacy", min_length=1, max_length=64)
    # 设备可读名称，例如「Mac · Chrome」，用于 Web 端区分来源。
    device_name: str = Field(default="", max_length=120)
    # 机器指纹：由系统、架构、时区等算出，扩展重装后仍是同一个值。
    # 两台配置相同的电脑会算出同一个指纹，因此只作为「疑似同一台机器」的线索。
    hardware_key: str = Field(default="", max_length=64)
    # 本次安装的随机标识，重装扩展后会变。
    install_id: str = Field(default="", max_length=64)
    visits: list[BrowserHistoryVisitInput] = Field(
        default_factory=list,
        max_length=500,
    )
    # 浏览器已清空历史后，扩展可以要求清空「本设备」的记录。
    replace_all: bool = False

    @field_validator("device_id", mode="before")
    @classmethod
    def normalize_device_id(cls, value: object) -> object:
        """只保留字母数字和短横线，避免异常字符进索引。"""

        if not isinstance(value, str):
            return value
        cleaned = "".join(
            character
            for character in value.strip()
            if character.isalnum() or character in {"-", "_"}
        )
        return cleaned[:64] or "legacy"

    @field_validator("device_name", mode="before")
    @classmethod
    def normalize_device_name(cls, value: object) -> object:
        """清理设备名称，控制长度。"""

        if not isinstance(value, str):
            return ""
        return " ".join(value.split()).strip()[:120]

    @field_validator("hardware_key", "install_id", mode="before")
    @classmethod
    def normalize_opaque_token(cls, value: object) -> object:
        """指纹和安装标识只保留安全字符。"""

        if not isinstance(value, str):
            return ""
        return "".join(
            character
            for character in value.strip()
            if character.isalnum() or character in {"-", "_"}
        )[:64]


class BrowserHistorySyncResponse(BaseModel):
    """浏览记录同步结果。"""

    synced_count: int
    total_count: int
    # 服务端最终使用的设备标识。指纹撞车时服务端会派一个新 ID，
    # 扩展据此把 identity 固定下来，后续同步都用它。
    device_id: str = "legacy"
    # 指纹与已有设备相同、但不是同一次安装时，给出那台设备的 ID，
    # 由用户在界面上确认「同一台机器（合并）」还是「另一台电脑」。
    possible_same_device_id: str | None = None


class BrowserHistoryDeviceMerge(BaseModel):
    """把一台设备的历史并进另一台。"""

    target_device_id: str = Field(min_length=1, max_length=64)


class BrowserHistoryDeviceUpdate(BaseModel):
    """重命名一台设备。"""

    device_name: str = Field(min_length=1, max_length=120)

    @field_validator("device_name", mode="before")
    @classmethod
    def normalize_device_name(cls, value: object) -> object:
        """清理名称，不允许空名。"""

        if not isinstance(value, str):
            return ""
        return " ".join(value.split()).strip()[:120]


class BrowserHistoryEntryRead(BaseModel):
    """Web 展示的一条浏览历史。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    page_url: str
    page_title: str
    favicon_url: str | None
    visit_count: int
    first_visited_at: datetime
    last_visited_at: datetime
    # 该网址是否已经在资料库里，前端据此显示「已收藏」。
    saved_memo_id: UUID | None = None
    # 这条记录来自哪台设备；合并展示时给出最近一次访问的设备。
    device_id: str = "legacy"
    device_name: str = ""

    @field_serializer("first_visited_at", "last_visited_at")
    def serialize_utc_datetime(self, value: datetime) -> str:
        """统一输出 UTC。"""

        resolved = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return resolved.astimezone(UTC).isoformat().replace("+00:00", "Z")


class BrowserHistoryDayGroup(BaseModel):
    """按访问日期分组的历史条目，前端直接按块渲染。"""

    # 本地日期（YYYY-MM-DD），按前端传入的时区偏移换算。
    date: str
    count: int
    items: list[BrowserHistoryEntryRead]


class BrowserHistoryDeviceRead(BaseModel):
    """一台同步过浏览历史的设备。"""

    device_id: str
    device_name: str
    total_count: int
    synced_at: datetime
    # 指纹相同说明「可能是同一台机器」（重装，或另一台同款电脑）。
    # 给出候选设备 ID，由用户确认是合并还是并列。
    possible_same_device_id: str | None = None

    @field_serializer("synced_at")
    def serialize_device_synced_at(self, value: datetime) -> str:
        """统一输出 UTC。"""

        resolved = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return resolved.astimezone(UTC).isoformat().replace("+00:00", "Z")


class BrowserHistoryListResponse(BaseModel):
    """浏览历史列表。"""

    extension_connected: bool
    synced_at: datetime | None
    total_count: int
    items: list[BrowserHistoryEntryRead]
    # 按日期分块的同一批条目；items 保留给旧客户端逐条渲染。
    days: list[BrowserHistoryDayGroup] = Field(default_factory=list)
    # 当前实际生效的搜索窗口；None 表示不限时间（全部历史）。
    window_days: int | None
    # 账号是否已在设置里打开「搜索更久的历史」。
    extended_search_enabled: bool
    # 分页信息：每页条数、本页起点、是否还有下一页以及下一页起点。
    page_size: int
    offset: int
    has_more: bool
    next_offset: int | None = None
    # 深翻页用的游标；非空时下次传 cursor 而不是 offset，查询与深度无关。
    next_cursor: str | None = None
    # 当前账号下同步过历史的所有设备，用于按设备筛选。
    devices: list[BrowserHistoryDeviceRead] = Field(default_factory=list)
    # 本次查询实际应用的设备筛选；None 表示已按网址合并所有设备。
    device_id: str | None = None

    @field_serializer("synced_at")
    def serialize_history_synced_at(self, value: datetime | None) -> str | None:
        """统一输出最近同步时间。"""

        if value is None:
            return None
        resolved = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return resolved.astimezone(UTC).isoformat().replace("+00:00", "Z")


class BrowserHistorySettingsRead(BaseModel):
    """历史记录相关的账号设置。"""

    model_config = ConfigDict(from_attributes=True)

    extended_search_enabled: bool


class BrowserHistorySettingsUpdate(BaseModel):
    """更新是否允许搜索更久的历史。"""

    extended_search_enabled: bool


def normalize_optional_text(value: str | None) -> str | None:
    """将空白可选文本统一转换为 ``None``。"""

    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def truncate_optional_text(value: object, max_length: int) -> object:
    """截断过长可选文本；非字符串交给后续类型校验。"""

    if value is None:
        return None
    if not isinstance(value, str):
        return value
    cleaned = value.strip()
    if not cleaned:
        return None
    return cleaned[:max_length]


def normalize_source_url(value: str | None) -> str | None:
    """规范化并校验网页来源链接。"""

    cleaned = normalize_optional_text(value)
    if cleaned is None:
        return None
    parsed = urlsplit(cleaned)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise ValueError("来源链接必须是有效的 HTTP 或 HTTPS 地址")
    return cleaned


# 密码库：服务器只接收浏览器加密后的数据，这里只校验格式和长度。
VAULT_KDF = "pbkdf2-sha256"
VAULT_MIN_ITERATIONS = 600_000
VAULT_MAX_ITERATIONS = 5_000_000
VAULT_MAX_CIPHERTEXT_BYTES = 64 * 1024


def _decoded_length(value: str, field: str) -> int:
    """校验标准 Base64 并返回解码后的字节数。"""

    try:
        return len(base64.b64decode(value, validate=True))
    except (binascii.Error, ValueError) as error:
        raise ValueError(f"{field} 不是有效的 Base64") from error


class VaultKeyFields(BaseModel):
    """主密码派生参数与包裹后的库密钥。"""

    kdf: Literal["pbkdf2-sha256"] = VAULT_KDF
    kdf_iterations: int = Field(ge=VAULT_MIN_ITERATIONS, le=VAULT_MAX_ITERATIONS)
    kdf_salt: str = Field(max_length=64)
    # AES-256 库密钥经 AES-GCM 包裹：32 字节密钥 + 16 字节认证标签。
    wrapped_key: str = Field(max_length=128)
    wrap_iv: str = Field(max_length=32)

    @field_validator("kdf_salt")
    @classmethod
    def validate_salt(cls, value: str) -> str:
        """盐至少 16 字节。"""

        if _decoded_length(value, "kdf_salt") < 16:
            raise ValueError("kdf_salt 至少 16 字节")
        return value

    @field_validator("wrapped_key")
    @classmethod
    def validate_wrapped_key(cls, value: str) -> str:
        """只接受包裹后的 256 位密钥。"""

        if _decoded_length(value, "wrapped_key") != 48:
            raise ValueError("wrapped_key 长度无效")
        return value

    @field_validator("wrap_iv")
    @classmethod
    def validate_wrap_iv(cls, value: str) -> str:
        """AES-GCM 使用 12 字节随机 IV。"""

        if _decoded_length(value, "wrap_iv") != 12:
            raise ValueError("wrap_iv 必须是 12 字节")
        return value


class VaultKeyCreate(VaultKeyFields):
    """首次设置主密码。"""


class VaultKeyUpdate(VaultKeyFields):
    """更改主密码：用新主密码重新包裹同一把库密钥。"""

    expected_version: int = Field(ge=1)


class VaultStatus(BaseModel):
    """密码库是否已设置，以及解锁所需的包裹参数。"""

    configured: bool
    kdf: str | None = None
    kdf_iterations: int | None = None
    kdf_salt: str | None = None
    wrapped_key: str | None = None
    wrap_iv: str | None = None
    version: int | None = None
    item_count: int = 0


class VaultItemFields(BaseModel):
    """加密后的条目内容。"""

    ciphertext: str = Field(min_length=1)
    iv: str = Field(max_length=32)

    @field_validator("ciphertext")
    @classmethod
    def validate_ciphertext(cls, value: str) -> str:
        """限制单条密文大小，至少要包含 GCM 认证标签。"""

        size = _decoded_length(value, "ciphertext")
        if size < 16 or size > VAULT_MAX_CIPHERTEXT_BYTES:
            raise ValueError("ciphertext 大小无效")
        return value

    @field_validator("iv")
    @classmethod
    def validate_iv(cls, value: str) -> str:
        """AES-GCM 使用 12 字节随机 IV。"""

        if _decoded_length(value, "iv") != 12:
            raise ValueError("iv 必须是 12 字节")
        return value


class VaultItemCreate(VaultItemFields):
    """新建条目；ID 由浏览器生成，因为它参与加密的附加认证数据。"""

    id: UUID


class VaultItemUpdate(VaultItemFields):
    """带版本号更新条目。"""

    expected_version: int = Field(ge=1)


class VaultItemRead(BaseModel):
    """返回给浏览器解密的条目。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    ciphertext: str
    iv: str
    version: int
    created_at: datetime
    updated_at: datetime

    @field_serializer("created_at", "updated_at")
    def serialize_time(self, value: datetime) -> str:
        """统一输出 UTC。"""

        resolved = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return resolved.astimezone(UTC).isoformat().replace("+00:00", "Z")
