"""SQLite 并发行为：巡检读取不能阻塞界面写入。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from app.database import SQLITE_BUSY_TIMEOUT_MS, Database, commit_with_retry
from sqlalchemy import text


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


def test_commit_with_retry_recovers_from_real_sqlite_lock(
    tmp_path: Path,
) -> None:
    """真实写锁竞争下，commit_with_retry 重试后数据必须真正落库。

    早期实现只"回滚再提交"，但 rollback 会撤销待写变更，第二次 commit 没
    有内容可写、接口却返回成功——数据根本没进去。这里压小 busy_timeout
    并持锁，强制走重试分支，断言新增行真实存在。
    """

    import threading
    import time
    from uuid import uuid4

    from app.models import Memo
    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import sessionmaker

    database_path = tmp_path / "lock.db"
    engine = create_engine(
        f"sqlite+pysqlite:///{database_path}",
        connect_args={"timeout": 0.05},
    )

    @event.listens_for(engine, "connect")
    def _small_busy_timeout(dbapi_conn, _):
        dbapi_conn.cursor().execute("PRAGMA busy_timeout=50")

    from app.database import Base

    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    def hold_lock(seconds: float) -> None:
        conn = sqlite3.connect(database_path)
        conn.execute("BEGIN IMMEDIATE")
        time.sleep(seconds)
        conn.rollback()
        conn.close()

    new_id = str(uuid4())
    lock_thread = threading.Thread(target=hold_lock, args=(2.0,))
    lock_thread.start()
    time.sleep(0.1)  # 确保写锁已被持有，第一次 commit 必然失败
    with Session() as session:
        session.add(
            Memo(
                id=new_id,
                user_id="u1",
                client_id=str(uuid4()),
                type="idea",
                title="锁冲突新增",
                body="",
                version=1,
                status="active",
            )
        )
        try:
            commit_with_retry(session)
        finally:
            lock_thread.join()
    with engine.connect() as connection:
        inserted = connection.exec_driver_sql(
            "SELECT COUNT(*) FROM memo WHERE id=?",
            (new_id,),
        ).scalar()
    assert inserted == 1, "重试后新增行必须真实落库"
    engine.dispose()


def test_existing_database_gains_history_setting_column(tmp_path: Path) -> None:
    """旧库升级后补上浏览历史开关列，已有账号保持默认关闭。"""

    database_path = tmp_path / "upgrade.db"
    database = Database(f"sqlite+pysqlite:///{database_path}")
    database.create_schema()
    database.dispose()

    # 模拟升级前的库：去掉新列，再写入一个已有账号。
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "ALTER TABLE user DROP COLUMN browser_history_extended_search",
        )
        connection.execute(
            "INSERT INTO user (id, display_name, email_verified, "
            "link_health_enabled, link_health_interval_hours, "
            "review_daily_limit, review_intervals_days, created_at, updated_at) "
            "VALUES ('u1', '老用户', 0, 1, 720, 10, '[1,3,7,14,30,60]', "
            "'2026-01-01', '2026-01-01')",
        )

    upgraded = Database(f"sqlite+pysqlite:///{database_path}")
    upgraded.create_schema()
    try:
        with upgraded.engine.connect() as connection:
            columns = {
                row[1]
                for row in connection.exec_driver_sql("PRAGMA table_info(user)")
            }
            enabled = connection.exec_driver_sql(
                "SELECT browser_history_extended_search FROM user WHERE id='u1'",
            ).scalar()
        assert "browser_history_extended_search" in columns
        # 默认关闭：老账号升级后仍然只能搜索最近 30 天。
        assert enabled == 0
    finally:
        upgraded.dispose()


def test_commit_with_retry_persists_changes_under_real_lock(
    tmp_path: Path,
) -> None:
    """真实写锁竞争下，commit_with_retry 必须把新增/更新真正落库。

    早期实现只"回滚后再提交"，但 rollback 会撤销待写变更，第二次 commit
    没有内容可写，于是接口返回成功、数据却没写。这里把 busy_timeout 压到
    极小并持锁 2 秒，强制走重试分支，断言数据真实落库。
    """

    import threading
    import time
    from uuid import uuid4

    from app.models import Memo
    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import sessionmaker

    database_path = tmp_path / "lock.db"
    engine = create_engine(
        f"sqlite+pysqlite:///{database_path}",
        connect_args={"timeout": 0.05},
    )

    @event.listens_for(engine, "connect")
    def _small_busy_timeout(dbapi_conn, _):
        dbapi_conn.cursor().execute("PRAGMA busy_timeout=50")

    from app.database import Base

    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    def hold_lock(seconds: float) -> None:
        conn = sqlite3.connect(database_path)
        conn.execute("BEGIN IMMEDIATE")
        time.sleep(seconds)
        conn.rollback()
        conn.close()

    mid = str(uuid4())
    with Session() as session:
        session.add(
            Memo(
                id=mid,
                user_id="u1",
                client_id=str(uuid4()),
                type="idea",
                title="原始",
                body="",
                version=1,
                status="active",
            )
        )
        session.commit()

    # 更新：持锁期间把标题改掉，断言最终落库。
    thread = threading.Thread(target=hold_lock, args=(2.0,))
    thread.start()
    time.sleep(0.1)
    with Session() as session:
        memo = session.get(Memo, mid)
        memo.title = "锁冲突下改的标题"
        try:
            commit_with_retry(session)
        finally:
            thread.join()
    with engine.connect() as connection:
        stored = connection.exec_driver_sql(
            "SELECT title FROM memo WHERE id=?",
            (mid,),
        ).scalar()
    assert stored == "锁冲突下改的标题"

    # 新增：持锁期间插入一条，断言真的写进去了。
    new_id = str(uuid4())
    thread = threading.Thread(target=hold_lock, args=(2.0,))
    thread.start()
    time.sleep(0.1)
    with Session() as session:
        session.add(
            Memo(
                id=new_id,
                user_id="u1",
                client_id=str(uuid4()),
                type="idea",
                title="锁冲突新增",
                body="",
                version=1,
                status="active",
            )
        )
        try:
            commit_with_retry(session)
        finally:
            thread.join()
    with engine.connect() as connection:
        inserted = connection.exec_driver_sql(
            "SELECT COUNT(*) FROM memo WHERE id=?",
            (new_id,),
        ).scalar()
    assert inserted == 1
    engine.dispose()
