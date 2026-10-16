"""数据库连接与会话管理。"""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from sqlalchemy import MetaData, create_engine, event, inspect, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import NullPool

SQLITE_BUSY_TIMEOUT_MS = 30_000
SQLITE_LOCK_COMMIT_ATTEMPTS = 8

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """SQLAlchemy 声明式模型基类。"""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Database:
    """封装数据库引擎和会话工厂。"""

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self._prepare_sqlite_directory(database_url)
        engine_options: dict[str, Any] = {}
        if database_url.startswith("sqlite"):
            # NullPool 避免后台循环各自建引擎后堆积连接；timeout 与 busy_timeout 对齐。
            engine_options["connect_args"] = {
                "check_same_thread": False,
                "timeout": SQLITE_BUSY_TIMEOUT_MS / 1000,
            }
            engine_options["poolclass"] = NullPool
        else:
            engine_options["pool_pre_ping"] = True
        self.engine: Engine = create_engine(database_url, **engine_options)
        if database_url.startswith("sqlite"):
            self._enable_sqlite_concurrency()
        self.session_factory = sessionmaker(
            bind=self.engine,
            class_=Session,
            expire_on_commit=False,
        )

    def _enable_sqlite_concurrency(self) -> None:
        """让后台巡检与接口写入不再互相锁死。

        SQLite 默认的回滚日志模式下，一个长时间读取（例如巡检占用连接读链接）
        会挡住所有写入，前台保存直接报 “database is locked”。WAL 让读不阻塞写，
        busy_timeout 让偶发的同时写入等待而不是立刻失败。
        """

        @event.listens_for(self.engine, "connect")
        def _set_sqlite_pragma(dbapi_connection: Any, _record: Any) -> None:
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=NORMAL")
            finally:
                cursor.close()

    @staticmethod
    def _prepare_sqlite_directory(database_url: str) -> None:
        """为文件型 SQLite 数据库创建父目录。"""

        url = make_url(database_url)
        if not url.drivername.startswith("sqlite") or not url.database:
            return
        if url.database == ":memory:":
            return
        database_path = Path(url.database)
        database_path.parent.mkdir(parents=True, exist_ok=True)

    def create_schema(self) -> None:
        """创建当前 MVP 所需数据库表。"""

        # 导入模型以保证声明式元数据已注册。
        from app import models  # noqa: F401

        Base.metadata.create_all(self.engine)
        self._migrate_sqlite_schema()

    def _migrate_sqlite_schema(self) -> None:
        """为已有本地数据库补充可空字段，避免清空开发数据。"""

        if self.engine.dialect.name != "sqlite":
            return
        user_columns = {
            column["name"] for column in inspect(self.engine).get_columns("user")
        }
        existing_columns = inspect(self.engine).get_columns("memo")
        columns = {column["name"] for column in existing_columns}
        with self.engine.begin() as connection:
            for name, kind in {
                "resource_text_excerpt": "TEXT",
                "resource_ai_assessment": "JSON",
            }.items():
                if name not in columns:
                    # 可空字段不修改旧分类与完成标记，支持原库直接升级。
                    connection.execute(text(
                        f"ALTER TABLE memo ADD COLUMN {name} {kind}",
                    ))
        browser_bookmark_columns = {
            column["name"]
            for column in inspect(self.engine).get_columns("browser_bookmark_snapshot")
        }
        user_migrations = {
            "email_verified": (
                "ALTER TABLE user ADD COLUMN email_verified BOOLEAN "
                "NOT NULL DEFAULT 0"
            ),
            "link_health_enabled": (
                "ALTER TABLE user ADD COLUMN link_health_enabled BOOLEAN "
                "NOT NULL DEFAULT 1"
            ),
            "link_health_interval_hours": (
                "ALTER TABLE user ADD COLUMN link_health_interval_hours INTEGER "
                "NOT NULL DEFAULT 720"
            ),
            "review_daily_limit": (
                "ALTER TABLE user ADD COLUMN review_daily_limit INTEGER "
                "NOT NULL DEFAULT 10"
            ),
            "review_intervals_days": (
                "ALTER TABLE user ADD COLUMN review_intervals_days JSON "
                "NOT NULL DEFAULT '[1,3,7,14,30,60]'"
            ),
        }
        migrations = {
            "source_url": "ALTER TABLE memo ADD COLUMN source_url VARCHAR(2048)",
            "source_title": "ALTER TABLE memo ADD COLUMN source_title VARCHAR(200)",
            "resource_page_title": (
                "ALTER TABLE memo ADD COLUMN resource_page_title VARCHAR(300)"
            ),
            "resource_description": (
                "ALTER TABLE memo ADD COLUMN resource_description TEXT"
            ),
            "resource_site_name": (
                "ALTER TABLE memo ADD COLUMN resource_site_name VARCHAR(200)"
            ),
            "resource_favicon_url": (
                "ALTER TABLE memo ADD COLUMN resource_favicon_url VARCHAR(2048)"
            ),
            "resource_image_url": (
                "ALTER TABLE memo ADD COLUMN resource_image_url VARCHAR(2048)"
            ),
            "resource_metadata_status": (
                "ALTER TABLE memo ADD COLUMN resource_metadata_status "
                "VARCHAR(30) NOT NULL DEFAULT 'none'"
            ),
            "resource_metadata_error": (
                "ALTER TABLE memo ADD COLUMN resource_metadata_error VARCHAR(100)"
            ),
            "resource_category": (
                "ALTER TABLE memo ADD COLUMN resource_category VARCHAR(50)"
            ),
            "resource_category_label": (
                "ALTER TABLE memo ADD COLUMN resource_category_label VARCHAR(100)"
            ),
            "resource_category_status": (
                "ALTER TABLE memo ADD COLUMN resource_category_status "
                "VARCHAR(30) NOT NULL DEFAULT 'none'"
            ),
            "resource_category_confidence": (
                "ALTER TABLE memo ADD COLUMN resource_category_confidence FLOAT"
            ),
            "resource_category_source": (
                "ALTER TABLE memo ADD COLUMN resource_category_source VARCHAR(30)"
            ),
            "resource_ai_classified_at": (
                "ALTER TABLE memo ADD COLUMN resource_ai_classified_at DATETIME"
            ),
            "resource_ai_review_required": (
                "ALTER TABLE memo ADD COLUMN resource_ai_review_required "
                "BOOLEAN NOT NULL DEFAULT 0"
            ),
            "resource_ai_auto_pending": (
                "ALTER TABLE memo ADD COLUMN resource_ai_auto_pending "
                "BOOLEAN NOT NULL DEFAULT 0"
            ),
            "resource_ai_confirmation_pending": (
                "ALTER TABLE memo ADD COLUMN resource_ai_confirmation_pending "
                "BOOLEAN NOT NULL DEFAULT 0"
            ),
            "resource_ai_confirmation": (
                "ALTER TABLE memo ADD COLUMN resource_ai_confirmation JSON"
            ),
            "resource_kind": (
                "ALTER TABLE memo ADD COLUMN resource_kind VARCHAR(30)"
            ),
            "resource_reading_status": (
                "ALTER TABLE memo ADD COLUMN resource_reading_status VARCHAR(30)"
            ),
            "resource_auto_tags": (
                "ALTER TABLE memo ADD COLUMN resource_auto_tags JSON "
                "NOT NULL DEFAULT '[]'"
            ),
            "resource_title_user_defined": (
                "ALTER TABLE memo ADD COLUMN resource_title_user_defined "
                "BOOLEAN NOT NULL DEFAULT 0"
            ),
            "resource_last_enriched_at": (
                "ALTER TABLE memo ADD COLUMN resource_last_enriched_at DATETIME"
            ),
            "resource_import_folder": (
                "ALTER TABLE memo ADD COLUMN resource_import_folder VARCHAR(1000)"
            ),
            "resource_import_batch_id": (
                "ALTER TABLE memo ADD COLUMN resource_import_batch_id VARCHAR(36)"
            ),
            "link_health_status": (
                "ALTER TABLE memo ADD COLUMN link_health_status VARCHAR(30) "
                "NOT NULL DEFAULT 'unchecked'"
            ),
            "link_health_http_status": (
                "ALTER TABLE memo ADD COLUMN link_health_http_status INTEGER"
            ),
            "link_health_error": (
                "ALTER TABLE memo ADD COLUMN link_health_error VARCHAR(100)"
            ),
            "link_last_checked_at": (
                "ALTER TABLE memo ADD COLUMN link_last_checked_at DATETIME"
            ),
            "link_last_success_at": (
                "ALTER TABLE memo ADD COLUMN link_last_success_at DATETIME"
            ),
            "link_next_check_at": (
                "ALTER TABLE memo ADD COLUMN link_next_check_at DATETIME"
            ),
            "link_consecutive_failures": (
                "ALTER TABLE memo ADD COLUMN link_consecutive_failures INTEGER "
                "NOT NULL DEFAULT 0"
            ),
            "link_effective_url": (
                "ALTER TABLE memo ADD COLUMN link_effective_url VARCHAR(2048)"
            ),
            "link_metadata_fingerprint": (
                "ALTER TABLE memo ADD COLUMN link_metadata_fingerprint VARCHAR(64)"
            ),
            "word_us_audio_url": (
                "ALTER TABLE memo ADD COLUMN word_us_audio_url VARCHAR(2048)"
            ),
            "word_uk_audio_url": (
                "ALTER TABLE memo ADD COLUMN word_uk_audio_url VARCHAR(2048)"
            ),
            "word_phonetic": "ALTER TABLE memo ADD COLUMN word_phonetic VARCHAR(120)",
            "normalized_lemma": (
                "ALTER TABLE memo ADD COLUMN normalized_lemma VARCHAR(200)"
            ),
            "word_meaning": "ALTER TABLE memo ADD COLUMN word_meaning TEXT",
            "word_example": "ALTER TABLE memo ADD COLUMN word_example TEXT",
            "familiarity": (
                "ALTER TABLE memo ADD COLUMN familiarity INTEGER NOT NULL DEFAULT 0"
            ),
            "review_count": (
                "ALTER TABLE memo ADD COLUMN review_count INTEGER NOT NULL DEFAULT 0"
            ),
            "last_review_at": "ALTER TABLE memo ADD COLUMN last_review_at DATETIME",
            "next_review_at": "ALTER TABLE memo ADD COLUMN next_review_at DATETIME",
            "audio_storage_name": (
                "ALTER TABLE memo ADD COLUMN audio_storage_name VARCHAR(100)"
            ),
            "audio_mime_type": (
                "ALTER TABLE memo ADD COLUMN audio_mime_type VARCHAR(100)"
            ),
            "audio_size_bytes": "ALTER TABLE memo ADD COLUMN audio_size_bytes INTEGER",
            "audio_duration_ms": (
                "ALTER TABLE memo ADD COLUMN audio_duration_ms INTEGER"
            ),
            "image_storage_name": (
                "ALTER TABLE memo ADD COLUMN image_storage_name VARCHAR(100)"
            ),
            "image_mime_type": (
                "ALTER TABLE memo ADD COLUMN image_mime_type VARCHAR(100)"
            ),
            "image_size_bytes": (
                "ALTER TABLE memo ADD COLUMN image_size_bytes INTEGER"
            ),
            "image_width": "ALTER TABLE memo ADD COLUMN image_width INTEGER",
            "image_height": "ALTER TABLE memo ADD COLUMN image_height INTEGER",
            "image_hash": "ALTER TABLE memo ADD COLUMN image_hash VARCHAR(64)",
            "image_thumbnail_storage_name": (
                "ALTER TABLE memo ADD COLUMN image_thumbnail_storage_name VARCHAR(100)"
            ),
            "image_ocr_text": "ALTER TABLE memo ADD COLUMN image_ocr_text TEXT",
            "image_ocr_status": (
                "ALTER TABLE memo ADD COLUMN image_ocr_status VARCHAR(30) "
                "NOT NULL DEFAULT 'none'"
            ),
            "image_ocr_error": (
                "ALTER TABLE memo ADD COLUMN image_ocr_error VARCHAR(500)"
            ),
            "image_ocr_source": (
                "ALTER TABLE memo ADD COLUMN image_ocr_source VARCHAR(30)"
            ),
            "image_auto_tags": (
                "ALTER TABLE memo ADD COLUMN image_auto_tags JSON NOT NULL DEFAULT '[]'"
            ),
            "image_ocr_updated_at": (
                "ALTER TABLE memo ADD COLUMN image_ocr_updated_at DATETIME"
            ),
            "transcript": "ALTER TABLE memo ADD COLUMN transcript TEXT",
            "transcript_status": (
                "ALTER TABLE memo ADD COLUMN transcript_status VARCHAR(30) "
                "NOT NULL DEFAULT 'none'"
            ),
            "collections": (
                "ALTER TABLE memo ADD COLUMN collections JSON NOT NULL DEFAULT '[]'"
            ),
            "starred": (
                "ALTER TABLE memo ADD COLUMN starred BOOLEAN NOT NULL DEFAULT 0"
            ),
            "resource_open_count": (
                "ALTER TABLE memo ADD COLUMN resource_open_count INTEGER "
                "NOT NULL DEFAULT 0"
            ),
            "resource_last_opened_at": (
                "ALTER TABLE memo ADD COLUMN resource_last_opened_at DATETIME"
            ),
            "resource_quick_access_hidden": (
                "ALTER TABLE memo ADD COLUMN resource_quick_access_hidden BOOLEAN "
                "NOT NULL DEFAULT 0"
            ),
            "deleted_at": "ALTER TABLE memo ADD COLUMN deleted_at DATETIME",
            "status_before_trash": (
                "ALTER TABLE memo ADD COLUMN status_before_trash VARCHAR(20)"
            ),
            "resource_categories": (
                "ALTER TABLE memo ADD COLUMN resource_categories JSON "
                "NOT NULL DEFAULT '[]'"
            ),
            "ebook_provider": (
                "ALTER TABLE memo ADD COLUMN ebook_provider VARCHAR(20)"
            ),
            "ebook_file_id": (
                "ALTER TABLE memo ADD COLUMN ebook_file_id VARCHAR(120)"
            ),
            "ebook_path": "ALTER TABLE memo ADD COLUMN ebook_path VARCHAR(1000)",
            "ebook_share_url": (
                "ALTER TABLE memo ADD COLUMN ebook_share_url VARCHAR(2048)"
            ),
            "ebook_format": "ALTER TABLE memo ADD COLUMN ebook_format VARCHAR(20)",
            "ebook_size_bytes": (
                "ALTER TABLE memo ADD COLUMN ebook_size_bytes INTEGER"
            ),
            "ebook_snapshot": "ALTER TABLE memo ADD COLUMN ebook_snapshot JSON",
        }
        browser_bookmark_migrations = {
            "revision": (
                "ALTER TABLE browser_bookmark_snapshot ADD COLUMN revision "
                "INTEGER NOT NULL DEFAULT 0"
            ),
        }
        ebook_job_columns = {
            column["name"]
            for column in inspect(self.engine).get_columns("ebook_transfer_job")
        }
        ebook_job_migrations = {
            "tags": (
                "ALTER TABLE ebook_transfer_job ADD COLUMN tags JSON "
                "NOT NULL DEFAULT '[]'"
            ),
            "collections": (
                "ALTER TABLE ebook_transfer_job ADD COLUMN collections JSON "
                "NOT NULL DEFAULT '[]'"
            ),
            "note": "ALTER TABLE ebook_transfer_job ADD COLUMN note TEXT",
        }
        model_setting_columns = {
            column["name"] for column in inspect(self.engine).get_columns(
                "model_provider_setting",
            )
        }
        classification_job_columns = {
            column["name"]
            for column in inspect(self.engine).get_columns(
                "resource_classification_job",
            )
        }
        with self.engine.begin() as connection:
            if "automatic" not in classification_job_columns:
                connection.execute(text(
                    "ALTER TABLE resource_classification_job "
                    "ADD COLUMN automatic BOOLEAN NOT NULL DEFAULT 0",
                ))
            classification_retry_migrations = {
                "error_code": "ADD COLUMN error_code VARCHAR(40)",
                "retry_count": "ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0",
                "next_retry_at": "ADD COLUMN next_retry_at DATETIME",
            }
            for name, statement in classification_retry_migrations.items():
                if name not in classification_job_columns:
                    # 只补字段，保留原队列、游标和全部成功或未确定计数。
                    connection.execute(text(
                        f"ALTER TABLE resource_classification_job {statement}",
                    ))
            if "base_url" not in model_setting_columns:
                # 已有账号凭据保持原值，只补充可空的请求地址。
                connection.execute(text(
                    "ALTER TABLE model_provider_setting "
                    "ADD COLUMN base_url VARCHAR(2048)",
                ))
            if "min_confidence" not in model_setting_columns:
                # 空值继续使用服务器默认阈值，兼容升级前保存的账号配置。
                connection.execute(text(
                    "ALTER TABLE model_provider_setting "
                    "ADD COLUMN min_confidence FLOAT",
                ))
            for column_name, statement in user_migrations.items():
                if column_name not in user_columns:
                    # 迁移语句来自固定映射，不拼接外部输入。
                    connection.execute(text(statement))
            for column_name, statement in migrations.items():
                if column_name not in columns:
                    # 迁移语句来自固定映射，不拼接外部输入。
                    connection.execute(text(statement))
            if "resource_ai_classified_at" not in columns:
                # 旧版成功的 Jev/LLM 分类同样视为已处理，升级后不重复收费。
                connection.execute(text(
                    "UPDATE memo SET resource_ai_classified_at = updated_at "
                    "WHERE resource_category_source IN ('jev', 'llm')",
                ))
            # 每次启动补齐全部异常的确认标记，也修复中断升级留下的默认值。
            connection.execute(text(
                "UPDATE memo SET resource_ai_review_required = 1 "
                "WHERE resource_ai_review_required = 0 AND link_health_status IN "
                "('failed', 'redirected', 'changed', 'auth_required', "
                "'temporary_failure', 'ignored')",
            ))
            if "resource_ai_confirmation_pending" not in columns:
                # 只恢复旧批次已经尝试过的未确定条目，不补造模型候选或改写进度。
                connection.execute(text(
                    "UPDATE memo SET resource_ai_confirmation_pending = 1 "
                    "WHERE type = 'resource' AND status != 'trashed' "
                    "AND source_url IS NOT NULL AND ebook_provider IS NULL "
                    "AND resource_ai_classified_at IS NULL "
                    "AND (resource_category_source IS NULL OR "
                    "resource_category_source NOT IN "
                    "('manual','user_rule','jev','llm')) "
                    "AND link_health_status != 'failed' "
                    "AND (json_extract(resource_ai_assessment, '$.status') "
                    "= 'uncertain' "
                    "OR EXISTS (SELECT 1 FROM resource_classification_job AS job, "
                    "json_each(job.memo_ids) AS item WHERE job.user_id = memo.user_id "
                    "AND item.value = memo.id "
                    "AND CAST(item.key AS INTEGER) < job.processed_count))",
                ))
            for column_name, statement in browser_bookmark_migrations.items():
                if column_name not in browser_bookmark_columns:
                    # 迁移语句来自固定映射，不拼接外部输入。
                    connection.execute(text(statement))
            for column_name, statement in ebook_job_migrations.items():
                if column_name not in ebook_job_columns:
                    # 迁移语句来自固定映射，不拼接外部输入。
                    connection.execute(text(statement))
            from app.word_service import normalize_word_lemma

            word_rows = connection.execute(
                text("SELECT id, title FROM memo WHERE type = 'word'"),
            ).all()
            for word_id, title in word_rows:
                connection.execute(
                    text(
                        "UPDATE memo SET normalized_lemma = :normalized_lemma "
                        "WHERE id = :id",
                    ),
                    {
                        "id": word_id,
                        "normalized_lemma": normalize_word_lemma(title),
                    },
                )
            # 旧资料在新增字段后进入待处理状态，其他类型保持 none。
            connection.execute(
                text(
                    "UPDATE memo SET resource_metadata_status = 'pending', "
                    "resource_category_status = 'pending' "
                    "WHERE type = 'resource' "
                    "AND resource_metadata_status = 'none'"
                )
            )
            connection.execute(
                text(
                    "UPDATE memo SET deleted_at = updated_at "
                    "WHERE status = 'trashed' AND deleted_at IS NULL"
                )
            )
            connection.execute(
                text(
                    "UPDATE memo SET status_before_trash = "
                    "CASE WHEN type = 'idea' THEN 'inbox' ELSE 'active' END "
                    "WHERE status = 'trashed' AND status_before_trash IS NULL"
                )
            )
            # 旧网页资料补齐内容形态与阅读进度默认值。
            connection.execute(
                text(
                    "UPDATE memo SET resource_kind = 'other' "
                    "WHERE type = 'resource' AND resource_kind IS NULL"
                )
            )
            connection.execute(
                text(
                    "UPDATE memo SET resource_reading_status = 'unread' "
                    "WHERE type = 'resource' "
                    "AND resource_reading_status IS NULL"
                )
            )
            # 旧系统分类补齐显示名称，用户自定义分类由分类任务写入名称。
            connection.execute(
                text(
                    "UPDATE memo SET resource_category_label = "
                    "CASE resource_category "
                    "WHEN 'learning' THEN '学习资料' "
                    "WHEN 'article' THEN '文章阅读' "
                    "WHEN 'media' THEN '视频与音频' "
                    "WHEN 'tool' THEN '工具与服务' "
                    "WHEN 'book_paper' THEN '书籍与论文' "
                    "WHEN 'product' THEN '商品与好物' "
                    "WHEN 'other' THEN '其他' END "
                    "WHERE type = 'resource' "
                    "AND resource_category_label IS NULL"
                )
            )
            # 旧资料新增巡检字段后，从下一轮调度开始逐步检查来源链接。
            connection.execute(
                text(
                    "UPDATE memo SET link_next_check_at = CURRENT_TIMESTAMP "
                    "WHERE type = 'resource' AND source_url IS NOT NULL "
                    "AND link_next_check_at IS NULL"
                )
            )
            # 旧单词补齐规范化词形，供重复检测使用。
            connection.execute(
                text(
                    "UPDATE memo SET normalized_lemma = lower(trim(title)) "
                    "WHERE type = 'word' AND normalized_lemma IS NULL"
                )
            )
            # 服务重启时将未完成的网页处理恢复为可重试状态。
            connection.execute(
                text(
                    "UPDATE memo SET resource_metadata_status = 'pending', "
                    "resource_category_status = 'pending' "
                    "WHERE type = 'resource' "
                    "AND resource_metadata_status = 'processing'"
                )
            )
            table_names = set(inspect(self.engine).get_table_names())
            if "resource_category_template" in table_names:
                template_columns = {
                    column["name"]
                    for column in inspect(self.engine).get_columns(
                        "resource_category_template",
                    )
                }
                if "parent_code" not in template_columns:
                    connection.execute(
                        text(
                            "ALTER TABLE resource_category_template "
                            "ADD COLUMN parent_code VARCHAR(50)"
                        )
                    )
                # 分类口径：老模板补空列，判定时按“只给类名”降级处理。
                for name in ("definition", "include_examples", "exclude_examples"):
                    if name not in template_columns:
                        connection.execute(
                            text(
                                "ALTER TABLE resource_category_template "
                                f"ADD COLUMN {name} TEXT"
                            )
                        )
            if "resource_categories" in columns:
                connection.execute(
                    text(
                        "UPDATE memo SET resource_categories = "
                        "'[\"' || resource_category || '\"]' "
                        "WHERE type = 'resource' "
                        "AND resource_category IS NOT NULL "
                        "AND resource_category != '' "
                        "AND (resource_categories IS NULL "
                        "OR resource_categories = '[]' "
                        "OR resource_categories = 'null')"
                    )
                )
            if "auth_verification_code" in table_names:
                unconsumed = connection.execute(
                    text(
                        "SELECT id, email, sent_at FROM auth_verification_code "
                        "WHERE consumed_at IS NULL"
                    ),
                ).all()
                latest_by_email: dict[str, tuple[str, Any]] = {}
                for code_id, email, sent_at in unconsumed:
                    current = latest_by_email.get(email)
                    if current is None or sent_at > current[1]:
                        latest_by_email[email] = (code_id, sent_at)
                keep_ids = {code_id for code_id, _ in latest_by_email.values()}
                for code_id, _email, _sent_at in unconsumed:
                    if code_id not in keep_ids:
                        connection.execute(
                            text(
                                "UPDATE auth_verification_code "
                                "SET consumed_at = CURRENT_TIMESTAMP "
                                "WHERE id = :id"
                            ),
                            {"id": code_id},
                        )
                connection.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS "
                        "uq_auth_verification_code_email_unconsumed "
                        "ON auth_verification_code (email) "
                        "WHERE consumed_at IS NULL"
                    ),
                )

    def session(self) -> Iterator[Session]:
        """提供请求级数据库会话。"""

        database_session = self.session_factory()
        try:
            yield database_session
        finally:
            database_session.close()

    def dispose(self) -> None:
        """释放数据库连接池。"""

        self.engine.dispose()


def is_sqlite_lock_error(error: BaseException) -> bool:
    """识别 SQLite 写锁冲突，便于提交层重试。"""

    message = str(error).lower()
    return "database is locked" in message or "database is busy" in message


def commit_with_retry(
    session: Session,
    attempts: int = SQLITE_LOCK_COMMIT_ATTEMPTS,
) -> None:
    """提交会话；遇到 SQLite 锁时回滚后短暂重试，避免前台保存直接 500。"""

    delay = 0.05
    for attempt in range(attempts):
        try:
            session.commit()
            return
        except OperationalError as error:
            if not is_sqlite_lock_error(error) or attempt == attempts - 1:
                raise
            session.rollback()
            time.sleep(delay)
            delay = min(delay * 2, 0.8)
