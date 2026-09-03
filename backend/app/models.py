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
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str | None] = mapped_column(String(300), nullable=True)
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
