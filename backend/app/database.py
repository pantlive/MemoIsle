"""数据库连接与会话管理。"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from sqlalchemy import MetaData, create_engine, inspect, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

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
        engine_options: dict[str, Any] = {"pool_pre_ping": True}
        if database_url.startswith("sqlite"):
            engine_options["connect_args"] = {"check_same_thread": False}
        self.engine: Engine = create_engine(database_url, **engine_options)
        self.session_factory = sessionmaker(
            bind=self.engine,
            class_=Session,
            expire_on_commit=False,
        )

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
        existing_columns = inspect(self.engine).get_columns("memo")
        columns = {column["name"] for column in existing_columns}
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
        }
        with self.engine.begin() as connection:
            for column_name, statement in migrations.items():
                if column_name not in columns:
                    # 迁移语句来自固定映射，不拼接外部输入。
                    connection.execute(text(statement))
            # 旧资料在新增字段后进入待处理状态，其他类型保持 none。
            connection.execute(
                text(
                    "UPDATE memo SET resource_metadata_status = 'pending', "
                    "resource_category_status = 'pending' "
                    "WHERE type = 'resource' "
                    "AND resource_metadata_status = 'none'"
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
