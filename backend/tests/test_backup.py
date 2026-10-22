"""备份与恢复：快照一致、密钥随行、恢复可逆、损坏可发现。"""

from __future__ import annotations

import dataclasses
import json
import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest
from app.backup_service import (
    BackupError,
    create_backup,
    restore_backup,
    verify_backup,
)
from app.cloud_account_service import decrypt_credential, encrypt_credential
from app.config import Settings
from app.database import Database
from app.models import Memo


def make_settings(root: Path) -> Settings:
    return Settings(
        database_url=f"sqlite+pysqlite:///{root / 'memoisle.db'}",
        cors_origins=("http://localhost:5173",),
        local_user_id="u1",
        auth_dev_mode=True,
        auth_token_secret="backup-test-secret",
        cloud_credential_secret="backup-test-secret",
        audio_directory=root / "audio",
        image_directory=root / "images",
        resource_enrichment_enabled=False,
        resource_health_monitor_enabled=False,
        word_dictionary_enabled=False,
    )


def add_memo(database: Database, title: str) -> None:
    with database.session_factory() as session:
        session.add(
            Memo(
                id=str(uuid4()),
                user_id="u1",
                client_id=str(uuid4()),
                type="idea",
                title=title,
                body="",
                version=1,
                status="active",
            )
        )
        session.commit()


def titles(database_path: Path) -> list[str]:
    connection = sqlite3.connect(database_path)
    try:
        return sorted(row[0] for row in connection.execute("SELECT title FROM memo"))
    finally:
        connection.close()


@pytest.fixture
def live(tmp_path: Path):
    root = tmp_path / "data"
    root.mkdir()
    settings = make_settings(root)
    database = Database(settings.database_url)
    database.create_schema()
    (root / ".memoisle-auth.key").write_text("auth-key-content", encoding="utf-8")
    (root / ".memoisle-model.key").write_text("model-key-content", encoding="utf-8")
    settings.audio_directory.mkdir()
    (settings.audio_directory / "a.m4a").write_bytes(b"audio")
    yield settings, database, root
    database.dispose()


def test_backup_includes_committed_data_keys_and_media(live, tmp_path: Path) -> None:
    settings, database, _ = live
    add_memo(database, "备份前写入")

    result = create_backup(settings, tmp_path / "backups")

    assert titles(result.directory / "memoisle.db") == ["备份前写入"]
    assert (result.directory / ".memoisle-auth.key").read_text() == "auth-key-content"
    assert (result.directory / ".memoisle-model.key").read_text() == "model-key-content"
    assert (result.directory / "audio" / "a.m4a").read_bytes() == b"audio"
    assert (result.directory / ".memoisle-auth.key").stat().st_mode & 0o777 == 0o600
    assert result.missing_keys == []
    verify_backup(result.directory)


def test_backup_while_writer_holds_wal_is_consistent(live, tmp_path: Path) -> None:
    """服务运行中（有未合并的 WAL）也能拿到一致快照。"""

    settings, database, root = live
    add_memo(database, "已提交")
    # 另一个连接写入后不关闭，WAL 里留着尚未合并回主库的页。
    writer = sqlite3.connect(root / "memoisle.db")
    writer.execute("PRAGMA journal_mode=WAL")
    # 复制已有行再改主键和标题，不必关心 memo 表有哪些必填列。
    writer.execute("CREATE TEMP TABLE copy AS SELECT * FROM memo LIMIT 1")
    writer.execute(
        "UPDATE copy SET id = ?, client_id = ?, title = '仅在 WAL 中'",
        (str(uuid4()), str(uuid4())),
    )
    writer.execute("INSERT INTO memo SELECT * FROM copy")
    writer.commit()
    try:
        assert (root / "memoisle.db-wal").stat().st_size > 0
        result = create_backup(settings, tmp_path / "backups", include_media=False)
    finally:
        writer.close()

    assert titles(result.directory / "memoisle.db") == ["仅在 WAL 中", "已提交"]


def test_restore_round_trip_keeps_old_data_aside(live, tmp_path: Path) -> None:
    settings, database, root = live
    add_memo(database, "原始数据")
    cipher = encrypt_credential(settings, '{"access_token": "t"}')
    backup = create_backup(settings, tmp_path / "backups")

    add_memo(database, "备份之后的改动")
    (root / ".memoisle-auth.key").write_text("rotated", encoding="utf-8")
    database.dispose()

    kept = restore_backup(settings, backup.directory)

    assert titles(root / "memoisle.db") == ["原始数据"]
    assert (root / ".memoisle-auth.key").read_text() == "auth-key-content"
    # 留底目录里是恢复前的数据，可以手动换回。
    assert kept is not None
    assert titles(kept / "memoisle.db") == ["原始数据", "备份之后的改动"]
    assert (kept / ".memoisle-auth.key").read_text() == "rotated"
    # 恢复后的密钥能解开备份时加密的凭据。
    assert json.loads(decrypt_credential(settings, cipher))["access_token"] == "t"


def test_restore_moves_stale_wal_away(live, tmp_path: Path) -> None:
    """换库时旧的 -wal 必须挪走，否则会被回放到恢复出来的库上。"""

    settings, database, root = live
    add_memo(database, "备份内容")
    backup = create_backup(settings, tmp_path / "backups", include_media=False)
    database.dispose()
    (root / "memoisle.db-wal").write_bytes(b"stale wal from the old database")

    kept = restore_backup(settings, backup.directory)

    assert not (root / "memoisle.db-wal").exists()
    assert (kept / "memoisle.db-wal").exists()
    assert titles(root / "memoisle.db") == ["备份内容"]


def test_verify_detects_tampering(live, tmp_path: Path) -> None:
    settings, _, _ = live
    backup = create_backup(settings, tmp_path / "backups")
    (backup.directory / ".memoisle-auth.key").write_text("tampered", encoding="utf-8")

    with pytest.raises(BackupError, match="损坏"):
        verify_backup(backup.directory)
    with pytest.raises(BackupError):
        restore_backup(settings, backup.directory)


def test_missing_key_files_are_reported(live, tmp_path: Path) -> None:
    """密钥用环境变量配置时没有文件，备份要提示用户另行保存。"""

    settings, _, root = live
    (root / ".memoisle-auth.key").unlink()

    result = create_backup(settings, tmp_path / "backups", include_media=False)

    assert result.missing_keys == [".memoisle-auth.key"]


def test_failed_backup_leaves_no_partial_directory(live, tmp_path: Path) -> None:
    settings, _, _ = live
    broken = dataclasses.replace(
        settings,
        database_url=f"sqlite+pysqlite:///{tmp_path / 'missing.db'}",
    )
    destination = tmp_path / "backups"
    destination.mkdir()

    with pytest.raises(BackupError):
        create_backup(broken, destination)

    assert list(destination.iterdir()) == []
