"""健康检查与客户端安装包下载。"""

from __future__ import annotations

from fastapi import (
    APIRouter,
    HTTPException,
)
from fastapi.responses import FileResponse, Response

from app.browser_extension_service import (
    browser_extension_archive_filename,
    build_browser_extension_archive,
)
from app.routes.deps import SettingsDependency

router = APIRouter()


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
        raise HTTPException(status_code=404, detail="安卓安装包暂未发布")
    return FileResponse(
        settings.android_apk_path,
        media_type="application/vnd.android.package-archive",
        filename="MemoIsle-android.apk",
        headers={"Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff"},
    )


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
