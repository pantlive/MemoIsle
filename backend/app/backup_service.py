"""数据库与密钥文件的备份、恢复。

一份备份是一个目录，包含：

- ``memoisle.db``：用 SQLite 的 ``VACUUM INTO`` 生成的一致性快照。
  服务运行中也能执行，不需要停机，也不会读到写了一半的页。
- 两个密钥文件：``.memoisle-auth.key``（登录会话与云盘凭据）和
  ``.memoisle-model.key``（模型服务凭据）。丢了它们，库里加密的凭据就再也解不开。
- 可选的录音、图片目录。
- ``manifest.json``：记录来源路径、时间与各文件的 SHA-256，恢复前先校验。
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.engine import make_url

from app.config import Settings, auth_secret_file
from app.model_settings_service import credential_key_file

MANIFEST_NAME = "manifest.json"
DATABASE_NAME = "memoisle.db"
MANIFEST_FORMAT = "memoisle-backup"
MANIFEST_VERSION = 1


class BackupError(RuntimeError):
    """备份或恢复无法完成。"""


@dataclass(frozen=True)
class BackupResult:
    """一次备份的产出。"""

    directory: Path
    files: dict[str, str]
    missing_keys: list[str]


def sqlite_database_path(settings: Settings) -> Path:
    """取出 SQLite 数据库文件路径；其他数据库不在本脚本的支持范围内。"""

    url = make_url(settings.database_url)
    if url.get_backend_name() != "sqlite" or url.database in (None, "", ":memory:"):
        raise BackupError("只支持备份文件型 SQLite 数据库")
    return Path(url.database)


def _key_files(settings: Settings) -> dict[str, Path]:
    return {
        ".memoisle-auth.key": auth_secret_file(settings.database_url),
        ".memoisle-model.key": credential_key_file(settings),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hash_tree(root: Path, prefix: str) -> dict[str, str]:
    return {
        f"{prefix}/{path.relative_to(root).as_posix()}": _sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def create_backup(
    settings: Settings,
    destination_root: Path,
    *,
    include_media: bool = True,
    now: datetime | None = None,
) -> BackupResult:
    """在 ``destination_root`` 下新建一个带时间戳的备份目录。"""

    database_path = sqlite_database_path(settings)
    if not database_path.is_file():
        raise BackupError(f"数据库不存在：{database_path}")

    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    target = destination_root / f"memoisle-backup-{stamp}"
    if target.exists():
        raise BackupError(f"备份目录已存在：{target}")
    # 先写到临时目录，全部完成后再改名，中途失败不会留下看似完整的备份。
    staging = destination_root / f".{target.name}.partial"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, mode=0o700)

    try:
        snapshot = staging / DATABASE_NAME
        source = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
        try:
            source.execute("VACUUM INTO ?", (str(snapshot),))
        finally:
            source.close()
        _verify_sqlite(snapshot)

        files = {DATABASE_NAME: _sha256(snapshot)}
        missing_keys: list[str] = []
        for name, path in _key_files(settings).items():
            if path.is_file():
                copied = staging / name
                shutil.copy2(path, copied)
                copied.chmod(0o600)
                files[name] = _sha256(copied)
            else:
                # 用环境变量配置密钥时没有文件，属于正常情况，但要提示用户另行保存。
                missing_keys.append(name)

        if include_media:
            for label, directory in (
                ("audio", settings.audio_directory),
                ("images", settings.image_directory),
            ):
                if directory.is_dir():
                    shutil.copytree(directory, staging / label)
                    files.update(_hash_tree(staging / label, label))

        manifest = {
            "format": MANIFEST_FORMAT,
            "version": MANIFEST_VERSION,
            "created_at": (now or datetime.now(UTC)).isoformat(),
            "source_database": str(database_path),
            "missing_keys": missing_keys,
            "files": files,
        }
        (staging / MANIFEST_NAME).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        staging.rename(target)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return BackupResult(directory=target, files=files, missing_keys=missing_keys)


def _verify_sqlite(path: Path) -> None:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        result = connection.execute("PRAGMA integrity_check").fetchone()
    finally:
        connection.close()
    if not result or result[0] != "ok":
        raise BackupError(f"数据库快照校验失败：{result}")


def verify_backup(backup_directory: Path) -> dict[str, object]:
    """按 manifest 校验备份完整性，返回 manifest。"""

    manifest_path = backup_directory / MANIFEST_NAME
    if not manifest_path.is_file():
        raise BackupError(f"不是 MemoIsle 备份目录：{backup_directory}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("format") != MANIFEST_FORMAT:
        raise BackupError("备份格式无法识别")
    for name, expected in manifest.get("files", {}).items():
        path = backup_directory / name
        if not path.is_file():
            raise BackupError(f"备份缺少文件：{name}")
        if _sha256(path) != expected:
            raise BackupError(f"备份文件已损坏：{name}")
    _verify_sqlite(backup_directory / DATABASE_NAME)
    return manifest


def restore_backup(settings: Settings, backup_directory: Path) -> Path | None:
    """把备份恢复到当前配置的位置，返回被替换数据的留底目录。

    必须先停止服务。现有数据不会被直接删除，而是挪到旁边的
    ``pre-restore-<时间>`` 目录，恢复出错时可以手动换回来。
    """

    manifest = verify_backup(backup_directory)
    database_path = sqlite_database_path(settings)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    keep_dir = database_path.parent / f"pre-restore-{stamp}"

    targets: list[tuple[Path, Path]] = [
        (backup_directory / DATABASE_NAME, database_path),
    ]
    for name, path in _key_files(settings).items():
        if (backup_directory / name).is_file():
            targets.append((backup_directory / name, path))
    for label, directory in (
        ("audio", settings.audio_directory),
        ("images", settings.image_directory),
    ):
        if (backup_directory / label).is_dir():
            targets.append((backup_directory / label, directory))

    # WAL 模式下未合并的写入在 -wal 文件里；换库时必须一起挪走，
    # 否则旧日志会被回放到新库上。
    sidecars = [
        database_path.with_name(database_path.name + suffix)
        for suffix in ("-wal", "-shm")
    ]
    moved_any = False
    for existing in [target for _, target in targets] + sidecars:
        if existing.exists():
            keep_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            shutil.move(str(existing), str(keep_dir / existing.name))
            moved_any = True

    for source, target in targets:
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)
            if target.name.startswith(".memoisle-") and target.suffix == ".key":
                target.chmod(0o600)
    del manifest
    return keep_dir if moved_any else None
