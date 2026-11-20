"""健康检查与客户端安装包下载。"""

from __future__ import annotations

import json
import re
from typing import Any

from fastapi import (
    APIRouter,
    HTTPException,
)
from fastapi.responses import FileResponse, JSONResponse, Response

from app.browser_extension_service import (
    browser_extension_archive_filename,
    build_browser_extension_archive,
)
from app.config import ANDROID_APK_METADATA_FILENAME, Settings
from app.routes.deps import SettingsDependency

router = APIRouter()

ANDROID_PACKAGE_MISSING = "安卓安装包暂未发布"
ANDROID_DOWNLOAD_PATH = "android/download"
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@router.get("/health", tags=["system"])
def health() -> dict[str, str]:
    """提供部署和开发环境健康检查。"""

    return {"status": "ok"}


@router.api_route(
    "/android/download",
    methods=["GET", "HEAD"],
    response_class=FileResponse,
    tags=["android"],
)
def download_android_route(settings: SettingsDependency) -> FileResponse:
    """公开下载已发布的签名 APK，支持手机浏览器及断点续传。"""

    if not settings.android_apk_path.is_file():
        raise HTTPException(status_code=404, detail=ANDROID_PACKAGE_MISSING)
    return FileResponse(
        settings.android_apk_path,
        media_type="application/vnd.android.package-archive",
        filename="MemoIsle-android.apk",
        headers={"Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff"},
    )


def _android_release(settings: Settings) -> dict[str, Any] | None:
    """读取签名脚本生成的版本信息；文件缺失、字段不全或与 APK 对不上时返回 None。"""

    apk_path = settings.android_apk_path
    metadata_path = (
        settings.android_apk_metadata_path
        or apk_path.parent / ANDROID_APK_METADATA_FILENAME
    )
    if not apk_path.is_file() or not metadata_path.is_file():
        return None
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(metadata, dict):
        return None
    version_code = metadata.get("versionCode")
    version_name = metadata.get("versionName")
    sha256 = metadata.get("sha256")
    size = metadata.get("size")
    notes = metadata.get("notes") or ""
    # bool 是 int 的子类，单独排除，避免 true 被当成版本号 1。
    if (
        not isinstance(version_code, int)
        or isinstance(version_code, bool)
        or version_code <= 0
        or not isinstance(version_name, str)
        or not version_name.strip()
        or not isinstance(sha256, str)
        or not isinstance(size, int)
        or isinstance(size, bool)
        or not isinstance(notes, str)
    ):
        return None
    sha256 = sha256.strip().lower()
    if not _SHA256_PATTERN.fullmatch(sha256):
        return None
    # 只换了 APK、JSON 还是旧的时大小对不上；宁可不提示，
    # 也不让客户端下到校验失败的包。
    try:
        if apk_path.stat().st_size != size:
            return None
    except OSError:
        return None
    return {
        "version_code": version_code,
        "version_name": version_name.strip(),
        "sha256": sha256,
        "size": size,
        "release_notes": notes.strip(),
        "download_url": ANDROID_DOWNLOAD_PATH,
    }


@router.get("/android/latest", tags=["android"])
def latest_android_release_route(settings: SettingsDependency) -> JSONResponse:
    """公开返回已发布 APK 的版本信息，供安卓端检查更新。"""

    release = _android_release(settings)
    if release is None:
        raise HTTPException(status_code=404, detail=ANDROID_PACKAGE_MISSING)
    return JSONResponse(release, headers={"Cache-Control": "no-cache"})


@router.get(
    "/browser-extension/download",
    response_class=Response,
    tags=["browser-extension"],
)
def download_browser_extension_route(settings: SettingsDependency) -> Response:
    """下载可解压后加载到 Chrome 或 Edge 的扩展包。"""

    archive = build_browser_extension_archive(settings.web_base_url)
    filename = browser_extension_archive_filename()
    return Response(
        content=archive,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )
