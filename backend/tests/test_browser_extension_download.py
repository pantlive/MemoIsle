"""浏览器扩展下载接口测试。"""

from __future__ import annotations

import json
from io import BytesIO
from zipfile import ZipFile

from PIL import Image

from fastapi.testclient import TestClient


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
        f'memoisle-browser-extension-{manifest["version"]}.zip'
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
