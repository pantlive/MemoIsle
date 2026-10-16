"""SQLite 并发行为：巡检读取不能阻塞界面写入。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from app.database import Database, SQLITE_BUSY_TIMEOUT_MS, commit_with_retry
from sqlalchemy import text
from sqlalchemy.exc import OperationalError


def test_sqlite_uses_wal_and_waits_for_locks(tmp_path: Path) -> None:
    """连接启用 WAL 并在偶发锁上等待，避免直接抛 database is locked。"""

    database = Database(f"sqlite+pysqlite:///{tmp_path / 'concurrency.db'}")
    database.create_schema()
    try:
        with database.engine.connect() as connection:
            journal_mode = connection.exec_driver_sql(
                "PRAGMA journal_mode",
            ).scalar()
            busy_timeout = connection.exec_driver_sql(
                "PRAGMA busy_timeout",
            ).scalar()
        assert journal_mode == "wal"
        assert busy_timeout is not None and busy_timeout >= SQLITE_BUSY_TIMEOUT_MS
    finally:
        database.dispose()


def test_read_transaction_does_not_block_writes(tmp_path: Path) -> None:
    """一个连接保持读事务时，另一个连接仍能写入。

    用原生连接显式开启读事务，模拟后台巡检读取链接时前台保存网页。
    """

    database_path = tmp_path / "concurrency.db"
    database = Database(f"sqlite+pysqlite:///{database_path}")
    database.create_schema()
    reader = sqlite3.connect(database_path, isolation_level=None)
    try:
        reader.execute("BEGIN")
        # 常量查询不读文件、不持锁；读一次真实表才能占住读事务。
        reader.execute("select name from sqlite_master").fetchall()
        with database.session_factory() as session:
            session.execute(text("create table probe (id integer)"))
            session.commit()
    finally:
        reader.close()
        database.dispose()


def test_commit_with_retry_recovers_from_sqlite_lock() -> None:
    """提交遇到 database is locked 时回滚并重试，而不是直接失败。"""

    class FakeSession:
        def __init__(self) -> None:
            self.commits = 0
            self.rollbacks = 0

        def commit(self) -> None:
            self.commits += 1
            if self.commits < 3:
                raise OperationalError(
                    "INSERT",
                    {},
                    Exception("database is locked"),
                )

        def rollback(self) -> None:
            self.rollbacks += 1

    session = FakeSession()
    commit_with_retry(session)  # type: ignore[arg-type]
    assert session.commits == 3
    assert session.rollbacks == 2
