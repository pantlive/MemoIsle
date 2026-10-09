"""API 数据模型。"""

from __future__ import annotations

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
    job: ResourceClassificationJobRead | None


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
        min_length=1, max_length=100,
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
    reason: Literal[
        "missing", "conflict", "not_pending", "no_candidate", "category_unavailable",
    ] | None = None


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
                code
                for item in value
                if (code := normalize_optional_text(item))
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
    parent_code: str | None = Field(default=None, max_length=50)

    @field_validator("name", "description", "parent_code")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        """清理分类名称、说明和父分类。"""

        return normalize_optional_text(value)


class ResourceCategoryGenerateRequest(BaseModel):
    """根据用户整理要求生成分类模板建议。"""

    instructions: str = Field(min_length=1, max_length=2_000)
    max_categories: int = Field(default=6, ge=1, le=12)

    @field_validator("instructions")
    @classmethod
    def normalize_instructions(cls, value: str) -> str:
        """拒绝空白要求，避免模型生成无关目录。"""

        cleaned = value.strip()
        if not cleaned:
            raise ValueError("请说明你希望怎样整理分类")
        return cleaned


class ResourceCategoryGenerateResponse(BaseModel):
    """模型生成的类别建议；使用现有创建接口加入模板。"""

    model: str
    categories: list[ResourceCategoryCreate] = Field(max_length=12)


class ResourceCategoryUpdate(BaseModel):
    """更新用户网页资料分类。"""

    expected_version: int = Field(ge=1)
    name: str | None = Field(default=None, max_length=50)
    description: str | None = Field(default=None, max_length=300)
    is_active: bool | None = None
    parent_code: str | None = Field(default=None, max_length=50)

    @field_validator("name", "description", "parent_code")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        """清理分类名称、说明和父分类。"""

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
    action: Literal['ocr', 'classify', 'ocr_classify']
    status: Literal['pending', 'processing', 'completed', 'failed']
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

    action: Literal['trash', 'restore', 'permanent']
    items: list[MemoBatchSelection] = Field(min_length=1, max_length=100)

    @model_validator(mode='after')
    def unique_items(self) -> MemoBatchRequest:
        """重复标识会造成重复版本操作，因此整批拒绝。"""

        if len({item.memo_id for item in self.items}) != len(self.items):
            raise ValueError('不能重复选择同一条内容')
        return self


class MemoBatchResultItem(BaseModel):
    """冲突和状态变化只返回固定编码。"""

    memo_id: UUID
    status: Literal['updated', 'skipped']
    reason: Literal['missing', 'conflict', 'not_applicable'] | None = None


class MemoBatchResult(BaseModel):
    """选中条目操作的汇总及逐项结果。"""

    updated_count: int
    skipped_count: int
    results: list[MemoBatchResultItem]


class ImageOrganizationRequest(BaseModel):
    """全库处理未完成图片，或只处理显式勾选的版本。"""

    action: Literal['ocr', 'classify', 'ocr_classify'] = 'ocr'
    scope: Literal['all', 'selected'] = 'selected'
    items: list[MemoBatchSelection] = Field(default_factory=list, max_length=100)

    @model_validator(mode='after')
    def validate_selection(self) -> ImageOrganizationRequest:
        """拒绝空选择、重复选择及含糊的全库请求。"""

        if self.scope == 'selected' and not self.items:
            raise ValueError('请选择需要处理的图片')
        if self.scope == 'all' and self.items:
            raise ValueError('全库处理不需要选择条目')
        if len({item.memo_id for item in self.items}) != len(self.items):
            raise ValueError('不能重复选择同一张图片')
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
