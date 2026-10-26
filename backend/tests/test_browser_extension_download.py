"""浏览器扩展下载接口测试。"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from io import BytesIO
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient
from PIL import Image


def test_browser_extension_download_contains_runtime_files(
    client: TestClient,
) -> None:
    """下载包应包含可直接加载的扩展运行文件。"""

    response = client.get("/api/v1/browser-extension/download")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    with ZipFile(BytesIO(response.content)) as archive:
        file_names = set(archive.namelist())
        assert file_names == {
            "memoisle-extension/README.md",
            "memoisle-extension/background.js",
            "memoisle-extension/content.js",
            "memoisle-extension/icons/icon16.png",
            "memoisle-extension/icons/icon32.png",
            "memoisle-extension/icons/icon48.png",
            "memoisle-extension/icons/icon128.png",
            "memoisle-extension/install.cmd",
            "memoisle-extension/install.ps1",
            "memoisle-extension/manifest.json",
        }
        manifest = json.loads(
            archive.read("memoisle-extension/manifest.json").decode("utf-8")
        )
        icon = Image.open(
            BytesIO(archive.read("memoisle-extension/icons/icon128.png")),
        ).convert("RGBA")
    assert (
        f"memoisle-browser-extension-{manifest['version']}.zip"
        in response.headers["content-disposition"]
    )
    assert manifest["manifest_version"] == 3
    assert "tabs" in manifest["permissions"]
    assert "activeTab" in manifest["permissions"]
    assert "scripting" in manifest["permissions"]
    assert "bookmarks" in manifest["permissions"]
    assert "notifications" in manifest["permissions"]
    assert manifest["icons"] == {
        "16": "icons/icon16.png",
        "32": "icons/icon32.png",
        "48": "icons/icon48.png",
        "128": "icons/icon128.png",
    }
    # 角落应是主页同款浅薄荷底，而不是旧版日出浪纹的深青绿。
    mint = icon.getpixel((24, 24))
    assert mint[0] > 180 and mint[1] > 200 and mint[2] > 180


@pytest.mark.parametrize(
    "origin",
    [
        "https://memo.17115859.xyz:9443",
        "https://memo.example.com",
    ],
)
def test_download_uses_configured_deployment_origin(
    client: TestClient,
    origin: str,
) -> None:
    """正式下载包的注入范围、回连地址和更新脚本使用同一部署源与端口。"""

    client.app.state.settings = replace(
        client.app.state.settings,
        web_base_url=f"{origin}/",
    )
    response = client.get(
        "/api/v1/browser-extension/download",
        headers={"host": "untrusted.example", "x-forwarded-host": "other.example"},
    )
    assert response.status_code == 200
    with ZipFile(BytesIO(response.content)) as archive:
        manifest = json.loads(archive.read("memoisle-extension/manifest.json"))
        background = archive.read("memoisle-extension/background.js").decode()
        installer = archive.read("memoisle-extension/install.ps1").decode()
    assert manifest["version"] == "0.5.1"
    assert manifest["content_scripts"][0]["matches"] == [f"{origin}/*"]
    assert f"{origin}/*" in manifest["host_permissions"]
    assert all(
        "localhost" not in value and "127.0.0.1" not in value
        for value in manifest["host_permissions"]
    )
    config_match = re.search(
        r"const DEFAULT_CONFIG = (\{.*?\});", background, re.DOTALL
    )
    assert config_match is not None
    assert json.loads(config_match[1]) == {
        "apiBaseUrl": f"{origin}/api/v1",
        "webBaseUrl": f"{origin}/",
    }
    assert f'[string]$ApiBase = "{origin}/api/v1"' in installer
    assert "untrusted.example" not in background


def test_local_download_keeps_development_port_discovery(client: TestClient) -> None:
    """本地开发继续接受启动器分配的 Vite 端口。"""

    client.app.state.settings = replace(
        client.app.state.settings,
        web_base_url="http://localhost:5174/",
    )
    response = client.get("/api/v1/browser-extension/download")
    with ZipFile(BytesIO(response.content)) as archive:
        manifest = json.loads(archive.read("memoisle-extension/manifest.json"))
    matches = manifest["content_scripts"][0]["matches"]
    assert "http://localhost:5174/*" in matches
    assert "http://127.0.0.1:5178/*" in matches
