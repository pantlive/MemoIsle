"""MemoIsle 数据备份与恢复。

    # 备份（服务运行中即可执行）
    python backend/scripts/backup.py create --to /mnt/backup/memoisle
    # 只备份数据库与密钥，不带录音和图片
    python backend/scripts/backup.py create --to /mnt/backup/memoisle --no-media
    # 只保留最近 14 份
    python backend/scripts/backup.py create --to /mnt/backup/memoisle --keep 14
    # 校验
    python backend/scripts/backup.py verify /mnt/backup/memoisle/memoisle-backup-...
    # 恢复（先停止服务）
    python backend/scripts/backup.py restore /mnt/backup/memoisle/memoisle-backup-...

数据位置读取与服务相同的 MEMOISLE_* 环境变量。
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.backup_service import (  # noqa: E402
    BackupError,
    create_backup,
    restore_backup,
    verify_backup,
)
from app.config import Settings  # noqa: E402


def prune(destination: Path, keep: int) -> list[Path]:
    """按名称（即时间）只保留最近 ``keep`` 份完整备份。"""

    backups = sorted(
        path
        for path in destination.glob("memoisle-backup-*")
        if path.is_dir() and (path / "manifest.json").is_file()
    )
    removed = backups[:-keep] if keep > 0 else []
    for path in removed:
        shutil.rmtree(path)
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(description="MemoIsle 数据备份与恢复")
    commands = parser.add_subparsers(dest="command", required=True)

    create = commands.add_parser("create", help="生成一份备份")
    create.add_argument("--to", type=Path, required=True, help="备份存放目录")
    create.add_argument("--no-media", action="store_true", help="不备份录音和图片")
    create.add_argument(
        "--keep",
        type=int,
        default=0,
        help="只保留最近 N 份，0 表示不清理",
    )

    verify = commands.add_parser("verify", help="校验一份备份")
    verify.add_argument("backup", type=Path)

    restore = commands.add_parser("restore", help="从备份恢复（需先停止服务）")
    restore.add_argument("backup", type=Path)

    args = parser.parse_args()
    settings = Settings.from_environment()
    try:
        if args.command == "create":
            args.to.mkdir(parents=True, exist_ok=True)
            result = create_backup(settings, args.to, include_media=not args.no_media)
            print(f"已备份到 {result.directory}（{len(result.files)} 个文件）")
            for name in result.missing_keys:
                print(
                    f"注意：没有找到 {name}。如果密钥是用环境变量配置的，"
                    "请把那个值另外保存好，否则恢复后加密凭据无法解密。",
                )
            for path in prune(args.to, args.keep):
                print(f"已清理旧备份 {path.name}")
        elif args.command == "verify":
            manifest = verify_backup(args.backup)
            count = len(manifest["files"])
            print(f"备份完整：{count} 个文件，创建于 {manifest['created_at']}")
        else:
            kept = restore_backup(settings, args.backup)
            print("恢复完成，可以启动服务了。")
            if kept is not None:
                print(f"原有数据已挪到 {kept}，确认无误后可自行删除。")
    except BackupError as error:
        print(f"失败：{error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
