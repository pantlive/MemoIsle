"""安卓安装包公开下载、错误响应及断点续传测试。"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient


def test_android_package_is_public_and_supports_head_and_range(
    client: TestClient,
    tmp_path: Path,
) -> None:
    """未登录的手机下载器能获取文件信息并继续分段下载。"""

    package = tmp_path / "release.apk"
    content = b"PK\x03\x04android-package-test"
    package.write_bytes(content)
    client.app.state.settings = replace(
        client.app.state.settings,
        auth_dev_mode=False,
        android_apk_path=package,
    )
    response = client.get("/api/v1/android/download")
    assert response.status_code == 200
    assert response.content == content
    assert response.headers["content-type"] == "application/vnd.android.package-archive"
    assert 'filename="MemoIsle-android.apk"' in response.headers["content-disposition"]
    metadata = client.head("/api/v1/android/download")
    assert metadata.status_code == 200
    assert metadata.content == b""
    assert int(metadata.headers["content-length"]) == len(content)
    partial = client.get(
        "/api/v1/android/download", headers={"Range": "bytes=0-3"},
    )
    assert partial.status_code == 206
    assert partial.content == b"PK\x03\x04"
    assert partial.headers["content-range"] == f"bytes 0-3/{len(content)}"


def test_missing_android_package_returns_explicit_404(
    client: TestClient,
    tmp_path: Path,
) -> None:
    """安装包缺失时返回清晰错误，避免下载到前端 HTML 页面。"""

    client.app.state.settings = replace(
        client.app.state.settings,
        android_apk_path=tmp_path / "missing.apk",
    )
    response = client.get("/api/v1/android/download")
    assert response.status_code == 404
    assert response.json() == {"detail": "安卓安装包暂未发布"}
