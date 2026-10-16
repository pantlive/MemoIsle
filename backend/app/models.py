"""数据库模型。"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.schemas import MemoStatus, MemoType


def utc_now() -> datetime:
    """返回带时区的当前时间。"""

    return datetime.now(UTC)


def enum_values(enum_class: type[MemoType] | type[MemoStatus]) -> list[str]:
    """让数据库枚举保存 API 使用的字符串值。"""

    return [item.value for item in enum_class]


class User(Base):
    """应用账号模型。"""

    __tablename__ = "user"
    __table_args__ = (UniqueConstraint("email", name="uq_user_email"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True, index=True)
    email_verified: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    link_health_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )
    link_health_interval_hours: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=30 * 24,
    )
    review_daily_limit: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=10,
    )
    review_intervals_days: Mapped[list[int]] = mapped_column(
        JSON,
        nullable=False,
        default=lambda: [1, 3, 7, 14, 30, 60],
    )
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )


class AuthEmailToken(Base):
    """邮箱验证和密码重置的一次性邮件令牌。"""

    __tablename__ = "auth_email_token"
    __table_args__ = (
        Index("ix_auth_email_token_user_purpose", "user_id", "purpose"),
        Index("ix_auth_email_token_expires", "expires_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
    )
    purpose: Mapped[str] = mapped_column(String(30), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )


class AuthVerificationCode(Base):
    """邮箱注册验证码模型，只保存验证码哈希。"""

    __tablename__ = "auth_verification_code"
    __table_args__ = (
        Index("ix_auth_verification_code_email_sent", "email", "sent_at"),
        Index("ix_auth_verification_code_expires", "expires_at"),
        Index(
            "uq_auth_verification_code_email_unconsumed",
            "email",
            unique=True,
            sqlite_where=text("consumed_at IS NULL"),
            postgresql_where=text("consumed_at IS NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )


class AuthLoginAttempt(Base):
    """邮箱登录失败记录，用于按账号维度限流。"""

    __tablename__ = "auth_login_attempt"
    __table_args__ = (Index("ix_auth_login_attempt_email_time", "email", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    successful: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )


class AuthIdentity(Base):
    """第三方登录身份与账号的绑定关系。"""

    __tablename__ = "auth_identity"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "provider_user_id",
            name="uq_auth_identity_provider_subject",
        ),
        Index("ix_auth_identity_user", "user_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    provider_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )


class AuthSession(Base):
    """服务端可撤销的 Bearer 登录会话。"""

    __tablename__ = "auth_session"
    __table_args__ = (Index("ix_auth_session_user", "user_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )


class AuthCredential(Base):
    """邮箱密码登录凭据。"""

    __tablename__ = "auth_credential"
    __table_args__ = (
        UniqueConstraint("email", name="uq_auth_credential_email"),
        Index("ix_auth_credential_user", "user_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    password_salt: Mapped[str] = mapped_column(String(64), nullable=False)
    password_iterations: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )


class Memo(Base):
    """统一收藏条目模型。"""

    __tablename__ = "memo"
    __table_args__ = (
        UniqueConstraint("user_id", "client_id", name="uq_memo_user_client"),
        Index("ix_memo_user_updated", "user_id", "updated_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    client_id: Mapped[str] = mapped_column(String(36), nullable=False)
    type: Mapped[MemoType] = mapped_column(
        Enum(
            MemoType,
            native_enum=False,
            values_callable=enum_values,
            name="memo_type",
        ),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    source_title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    resource_page_title: Mapped[str | None] = mapped_column(
        String(300),
        nullable=True,
    )
    resource_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    resource_site_name: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )
    resource_favicon_url: Mapped[str | None] = mapped_column(
        String(2048),
        nullable=True,
    )
    resource_image_url: Mapped[str | None] = mapped_column(
        String(2048),
        nullable=True,
    )
    resource_metadata_status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="none",
    )
    resource_metadata_error: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    resource_category: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        index=True,
    )
    resource_category_label: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    resource_category_status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="none",
    )
    resource_category_confidence: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    resource_category_source: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )
    # 完成大模型分类的时间独立保存，后续手动调整不导致重复调用模型。
    resource_ai_classified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    # 巡检中心待确认标记；分类队列只排除确认失效，不看此字段。
    resource_ai_review_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
    )
    # 新网页自动排队；处理后清除此标记，失败不会无限循环重试。
    resource_ai_auto_pending: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
    )
    # 摘要仅取公开网页正文；空字符串表示已经提取但没有可用内容。
    resource_text_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 模型证据只保存白名单类别、数值和固定原因，不保存原始模型响应。
    resource_ai_assessment: Mapped[dict[str, object] | None] = mapped_column(
        JSON, nullable=True,
    )
    # 分类复核与网页巡检分别记录；确认失效的网页不进入分类确认队列。
    resource_ai_confirmation_pending: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
    )
    resource_ai_confirmation: Mapped[dict[str, object] | None] = mapped_column(
        JSON(none_as_null=True), nullable=True,
    )
    resource_categories: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    resource_kind: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
        index=True,
    )
    resource_reading_status: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
        index=True,
    )
    resource_auto_tags: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    resource_title_user_defined: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    resource_last_enriched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    resource_import_folder: Mapped[str | None] = mapped_column(
        String(1_000),
        nullable=True,
    )
    resource_import_batch_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
        index=True,
    )
    # 电子书：只保存云盘文件引用与元数据快照，不保存电子书本体。
    ebook_provider: Mapped[str | None] = mapped_column(String(20), nullable=True)
    ebook_file_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    ebook_path: Mapped[str | None] = mapped_column(String(1_000), nullable=True)
    ebook_share_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    ebook_format: Mapped[str | None] = mapped_column(String(20), nullable=True)
    ebook_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ebook_snapshot: Mapped[dict[str, object] | None] = mapped_column(
        JSON,
        nullable=True,
    )
    link_health_status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="unchecked",
    )
    link_health_http_status: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    link_health_error: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    link_last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    link_last_success_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    link_next_check_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    link_consecutive_failures: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    link_effective_url: Mapped[str | None] = mapped_column(
        String(2048),
        nullable=True,
    )
    link_metadata_fingerprint: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    word_phonetic: Mapped[str | None] = mapped_column(String(120), nullable=True)
    word_us_audio_url: Mapped[str | None] = mapped_column(
        String(2048),
        nullable=True,
    )
    word_uk_audio_url: Mapped[str | None] = mapped_column(
        String(2048),
        nullable=True,
    )
    normalized_lemma: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
        index=True,
    )
    word_meaning: Mapped[str | None] = mapped_column(Text, nullable=True)
    word_example: Mapped[str | None] = mapped_column(Text, nullable=True)
    familiarity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    review_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_review_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    next_review_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    audio_storage_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    audio_mime_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    audio_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    audio_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_storage_name: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    image_mime_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    image_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    image_thumbnail_storage_name: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    # 图片 OCR 文本与自动标签；未启用或未识别时状态为 none/disabled。
    image_ocr_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_ocr_status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="none",
    )
    image_ocr_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    image_ocr_source: Mapped[str | None] = mapped_column(String(30), nullable=True)
    image_auto_tags: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    image_ocr_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcript_status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="none",
    )
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    collections: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    starred: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # 网页资料的打开统计只是使用记录，更新时不改动版本号和 updated_at。
    resource_open_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )
    resource_last_opened_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    # 用户从快速访问移除后继续计数，只是不再出现在快速访问里。
    resource_quick_access_hidden: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
    )
    status: Mapped[MemoStatus] = mapped_column(
        Enum(
            MemoStatus,
            native_enum=False,
            values_callable=enum_values,
            name="memo_status",
        ),
        nullable=False,
        default=MemoStatus.ACTIVE,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    status_before_trash: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )


class MemoDeletion(Base):
    """永久删除仅留下账号、标识和时间，供离线设备同步清理缓存。"""

    __tablename__ = "memo_deletion"
    __table_args__ = (
        Index("ix_memo_deletion_user_time", "user_id", "deleted_at"),
        Index("ix_memo_deletion_user_client", "user_id", "client_id"),
    )

    memo_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    client_id: Mapped[str] = mapped_column(String(36), nullable=False)
    deleted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now,
    )


class BookmarkImportBatch(Base):
    """一次 Chrome 书签导入批次。"""

    __tablename__ = "bookmark_import_batch"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    total_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    valid_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    imported_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )
    undone_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class BookmarkImportItem(Base):
    """书签导入批次中的一个来源项目。"""

    __tablename__ = "bookmark_import_item"
    __table_args__ = (
        UniqueConstraint(
            "batch_id",
            "client_item_id",
            name="uq_bookmark_import_item_batch_client",
        ),
        Index("ix_bookmark_import_item_batch_status", "batch_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    batch_id: Mapped[str] = mapped_column(
        ForeignKey("bookmark_import_batch.id"),
        nullable=False,
    )
    client_item_id: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    source_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    normalized_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    folder_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    memo_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    existing_memo_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )


class BrowserOpenTab(Base):
    """浏览器扩展同步的当前打开标签页。"""

    __tablename__ = "browser_open_tab"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "extension_id",
            "tab_id",
            name="uq_browser_open_tab_identity",
        ),
        Index("ix_browser_open_tab_user_status", "user_id", "status"),
        Index("ix_browser_open_tab_user_seen", "user_id", "last_seen_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    extension_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tab_id: Mapped[int] = mapped_column(Integer, nullable=False)
    window_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    page_title: Mapped[str] = mapped_column(String(300), nullable=False)
    favicon_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="open")
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )


class BrowserBookmarkSnapshot(Base):
    """浏览器扩展同步的书签树快照。"""

    __tablename__ = "browser_bookmark_snapshot"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "extension_id",
            name="uq_browser_bookmark_snapshot_identity",
        ),
        Index(
            "ix_browser_bookmark_snapshot_user_synced",
            "user_id",
            "synced_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    extension_id: Mapped[str] = mapped_column(String(64), nullable=False)
    bookmarks: Mapped[list[dict[str, object]]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    total_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    truncated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )


class BrowserCapture(Base):
    """浏览器扩展授权的短时一次性网页上下文。"""

    __tablename__ = "browser_capture"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_browser_capture_token_hash"),
        Index("ix_browser_capture_user_expires", "user_id", "expires_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    extension_id: Mapped[str] = mapped_column(String(64), nullable=False)
    nonce: Mapped[str] = mapped_column(String(100), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    page_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    page_title: Mapped[str] = mapped_column(String(300), nullable=False)
    favicon_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class LinkHealthEvent(Base):
    """网页巡检结果和用户处理动作的审计记录。"""

    __tablename__ = "link_health_event"
    __table_args__ = (
        Index("ix_link_health_event_memo_created", "memo_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    memo_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    health_status: Mapped[str] = mapped_column(String(30), nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    effective_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )


class LinkHealthSitePause(Base):
    """当前用户暂停某个网站巡检的配置。"""

    __tablename__ = "link_health_site_pause"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "hostname",
            name="uq_link_health_site_pause_user_host",
        ),
        Index("ix_link_health_site_pause_user", "user_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    hostname: Mapped[str] = mapped_column(String(253), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )


class ResourceCategoryTemplate(Base):
    """用户自定义的网页资料分类模板。"""

    __tablename__ = "resource_category_template"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "code",
            name="uq_resource_category_template_user_code",
        ),
        Index(
            "ix_resource_category_template_user_active",
            "user_id",
            "is_active",
        ),
        Index(
            "ix_resource_category_template_user_parent",
            "user_id",
            "parent_code",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    parent_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # 分类口径：模型判定这个类别时的判据、正例与边界反例，每行一条。
    definition: Mapped[str | None] = mapped_column(Text, nullable=True)
    include_examples: Mapped[str | None] = mapped_column(Text, nullable=True)
    exclude_examples: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )


class ResourceCategoryRule(Base):
    """用户自定义的网页资料分类匹配规则。"""

    __tablename__ = "resource_category_rule"
    __table_args__ = (
        Index(
            "ix_resource_category_rule_user_enabled_priority",
            "user_id",
            "enabled",
            "priority",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    category_code: Mapped[str] = mapped_column(String(50), nullable=False)
    match_type: Mapped[str] = mapped_column(String(30), nullable=False)
    pattern: Mapped[str] = mapped_column(String(500), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )


class ModelProviderSetting(Base):
    """按账号保存模型配置；API Key 仅以密文落库。"""

    __tablename__ = "model_provider_setting"

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("user.id", ondelete="CASCADE"),
        primary_key=True,
    )
    provider: Mapped[str] = mapped_column(String(20), primary_key=True)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    # 空值继续使用服务器默认地址，兼容升级前保存的账号配置。
    base_url: Mapped[str | None] = mapped_column(String(2048))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # 自动分类的置信度阈值；空值继续使用服务器默认值。
    min_confidence: Mapped[float | None] = mapped_column(Float)
    credential_cipher: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now,
    )


class CloudAccount(Base):
    """用户绑定的云盘账号；凭据只保存密文与脱敏提示。"""

    __tablename__ = "cloud_account"
    __table_args__ = (
        UniqueConstraint("user_id", "provider", name="uq_cloud_account_user_provider"),
        Index("ix_cloud_account_user_status", "user_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    credential_cipher: Mapped[str] = mapped_column(Text, nullable=False)
    credential_hint: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    default_folder: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        default="/MemoIsle/电子书",
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_error: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )


class ResourceClassificationJob(Base):
    """每个账号保留一个可恢复的网页批量分类任务。"""

    __tablename__ = "resource_classification_job"

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("user.id", ondelete="CASCADE"), primary_key=True,
    )
    id: Mapped[str] = mapped_column(String(36), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    automatic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # 固定本轮条目快照，进度与分类结果在同一事务提交。
    memo_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    total_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    succeeded_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(String(200), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # 重试次数属于当前游标条目，等待状态持久化，服务重启也不会绕过上限。
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    # 租约阻止并发启动和恢复循环重复处理同一任务。
    worker_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now,
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )


class ImageOrganizationJob(Base):
    """图片批量整理持久化快照与租约，重启后继续未处理条目。"""

    __tablename__ = 'image_organization_job'
    user_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    id: Mapped[str] = mapped_column(String(36), nullable=False)
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    items: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)
    total_count: Mapped[int] = mapped_column(Integer, default=0)
    processed_count: Mapped[int] = mapped_column(Integer, default=0)
    succeeded_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(String(200), nullable=True)
    worker_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now,
    )


class EbookTransferJob(Base):
    """电子书转存/上传任务。"""

    __tablename__ = "ebook_transfer_job"
    __table_args__ = (
        Index("ix_ebook_transfer_job_user_status", "user_id", "status"),
        Index("ix_ebook_transfer_job_user_created", "user_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    memo_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    share_password: Mapped[str | None] = mapped_column(String(100), nullable=True)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    # transfer：云盘分享链接转存；upload：直链下载后上传。
    mode: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stage: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    target_folder: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        default="/MemoIsle/电子书",
    )
    # 用户提交时填写的标签、分类与备注，任务成功后写入新建的 Memo。
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    collections: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    cloud_file_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    cloud_path: Mapped[str | None] = mapped_column(String(1_000), nullable=True)
    snapshot: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class VaultKey(Base):
    """密码库的库密钥，已被主密码派生的密钥包裹。

    服务器只保存派生参数和包裹后的密文，无法得到主密码或库密钥。
    """

    __tablename__ = "vault_key"

    user_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kdf: Mapped[str] = mapped_column(String(30), nullable=False)
    kdf_iterations: Mapped[int] = mapped_column(Integer, nullable=False)
    kdf_salt: Mapped[str] = mapped_column(String(64), nullable=False)
    wrapped_key: Mapped[str] = mapped_column(String(128), nullable=False)
    wrap_iv: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )


class VaultItem(Base):
    """密码库条目；标题、类型和内容都在浏览器里加密后才上传。"""

    __tablename__ = "vault_item"
    __table_args__ = (Index("ix_vault_item_user_updated", "user_id", "updated_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    iv: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )
