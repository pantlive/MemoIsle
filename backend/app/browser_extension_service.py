"""浏览器扩展下载包生成业务。"""

from __future__ import annotations

from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from app.config import PROJECT_ROOT

EXTENSION_DIRECTORY = PROJECT_ROOT / "extension"
EXTENSION_RUNTIME_FILES = (
    "manifest.json",
    "background.js",
    "README.md",
)
EXTENSION_ARCHIVE_DIRECTORY = "memoisle-extension"


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
