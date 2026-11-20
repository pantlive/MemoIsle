"""安卓安装包公开下载、错误响应及断点续传测试。"""

from __future__ import annotations

import hashlib
import json
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


def _publish_release(
    tmp_path: Path,
    *,
    content: bytes = b"PK\x03\x04android-release",
    size: int | None = None,
) -> tuple[Path, dict[str, object]]:
    """模拟签名脚本输出：APK 与同目录的版本信息 JSON。"""

    package = tmp_path / "memoisle-android.apk"
    package.write_bytes(content)
    metadata = {
        "versionCode": 6,
        "versionName": "0.1.5",
        "sha256": hashlib.sha256(content).hexdigest(),
        "size": len(content) if size is None else size,
        "notes": "支持自动更新",
    }
    (tmp_path / "memoisle-android.json").write_text(
        json.dumps(metadata, ensure_ascii=False), encoding="utf-8",
    )
    return package, metadata


def test_latest_android_release_is_public(
    client: TestClient,
    tmp_path: Path,
) -> None:
    """未登录也能读取最新版本信息，下载地址固定为相对路径。"""

    package, metadata = _publish_release(tmp_path)
    client.app.state.settings = replace(
        client.app.state.settings,
        auth_dev_mode=False,
        android_apk_path=package,
    )
    response = client.get("/api/v1/android/latest")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"
    assert response.json() == {
        "version_code": 6,
        "version_name": "0.1.5",
        "sha256": metadata["sha256"],
        "size": metadata["size"],
        "release_notes": "支持自动更新",
        "download_url": "android/download",
    }


def test_latest_android_release_uses_configured_metadata_path(
    client: TestClient,
    tmp_path: Path,
) -> None:
    """可单独指定版本信息文件位置。"""

    package, _ = _publish_release(tmp_path)
    custom = tmp_path / "meta" / "release.json"
    custom.parent.mkdir()
    (tmp_path / "memoisle-android.json").rename(custom)
    client.app.state.settings = replace(
        client.app.state.settings,
        auth_dev_mode=False,
        android_apk_path=package,
        android_apk_metadata_path=custom,
    )
    response = client.get("/api/v1/android/latest")
    assert response.status_code == 200
    assert response.json()["version_code"] == 6


def test_latest_android_release_without_metadata_returns_404(
    client: TestClient,
    tmp_path: Path,
) -> None:
    """只上传了 APK、没有版本信息时按未发布处理。"""

    package, _ = _publish_release(tmp_path)
    (tmp_path / "memoisle-android.json").unlink()
    client.app.state.settings = replace(
        client.app.state.settings,
        auth_dev_mode=False,
        android_apk_path=package,
    )
    response = client.get("/api/v1/android/latest")
    assert response.status_code == 404
    assert response.json() == {"detail": "安卓安装包暂未发布"}


def test_latest_android_release_without_apk_returns_404(
    client: TestClient,
    tmp_path: Path,
) -> None:
    """版本信息还在但 APK 缺失时也不能提示更新。"""

    package, _ = _publish_release(tmp_path)
    package.unlink()
    client.app.state.settings = replace(
        client.app.state.settings,
        android_apk_path=package,
    )
    response = client.get("/api/v1/android/latest")
    assert response.status_code == 404


def test_latest_android_release_size_mismatch_returns_404(
    client: TestClient,
    tmp_path: Path,
) -> None:
    """APK 已替换但 JSON 未同步时大小不一致，不让客户端下载到校验失败的包。"""

    package, _ = _publish_release(tmp_path, size=1)
    client.app.state.settings = replace(
        client.app.state.settings,
        auth_dev_mode=False,
        android_apk_path=package,
    )
    response = client.get("/api/v1/android/latest")
    assert response.status_code == 404
    assert response.json() == {"detail": "安卓安装包暂未发布"}


def test_latest_android_release_with_incomplete_metadata_returns_404(
    client: TestClient,
    tmp_path: Path,
) -> None:
    """缺少字段或字段类型不对时按未发布处理。"""

    package, metadata = _publish_release(tmp_path)
    client.app.state.settings = replace(
        client.app.state.settings,
        android_apk_path=package,
    )
    metadata_file = tmp_path / "memoisle-android.json"
    for broken in (
        {key: value for key, value in metadata.items() if key != "versionCode"},
        {**metadata, "versionCode": True},
        {**metadata, "sha256": "not-a-hash"},
        [metadata],
    ):
        metadata_file.write_text(json.dumps(broken), encoding="utf-8")
        assert client.get("/api/v1/android/latest").status_code == 404
    metadata_file.write_text("{broken", encoding="utf-8")
    assert client.get("/api/v1/android/latest").status_code == 404
