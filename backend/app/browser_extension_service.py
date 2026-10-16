"""浏览器扩展下载包生成业务。"""

from __future__ import annotations

import json
import re
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from app.config import PROJECT_ROOT

EXTENSION_DIRECTORY = PROJECT_ROOT / "extension"
EXTENSION_RUNTIME_FILES = (
    "manifest.json",
    "background.js",
    "content.js",
    "README.md",
    "icons/icon16.png",
    "icons/icon32.png",
    "icons/icon48.png",
    "icons/icon128.png",
    "install.cmd",
    "install.ps1",
)
EXTENSION_ARCHIVE_DIRECTORY = "memoisle-extension"
_EXTENSION_VERSION_PATTERN = re.compile(r"[0-9]+(?:\.[0-9]+){0,3}")


def read_browser_extension_version() -> str:
    """读取当前扩展清单中的版本号，供下载文件名使用。"""

    manifest = json.loads(
        (EXTENSION_DIRECTORY / "manifest.json").read_text(encoding="utf-8"),
    )
    version = str(manifest.get("version", "")).strip()
    if _EXTENSION_VERSION_PATTERN.fullmatch(version) is None:
        raise ValueError("invalid_extension_version")
    return version


def browser_extension_archive_filename(version: str | None = None) -> str:
    """下载 ZIP 使用带版本号的文件名，避免覆盖旧包时分不清版本。"""

    resolved = version or read_browser_extension_version()
    return f"memoisle-browser-extension-{resolved}.zip"


def build_browser_extension_archive() -> bytes:
    """将当前版本的浏览器扩展运行文件打包为 ZIP。"""

    archive_buffer = BytesIO()
    with ZipFile(archive_buffer, mode="w", compression=ZIP_DEFLATED) as archive:
        # 只打包安装所需文件，避免把测试代码和开发依赖交付给用户。
        for file_name in EXTENSION_RUNTIME_FILES:
            source_path = EXTENSION_DIRECTORY / file_name
            archive_path = f"{EXTENSION_ARCHIVE_DIRECTORY}/{file_name}"
            archive.writestr(archive_path, source_path.read_bytes())
    return archive_buffer.getvalue()
