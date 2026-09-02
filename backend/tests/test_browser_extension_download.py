"""浏览器扩展下载接口测试。"""

from __future__ import annotations

import json
from io import BytesIO
from zipfile import ZipFile

from fastapi.testclient import TestClient


def test_browser_extension_download_contains_runtime_files(
    client: TestClient,
) -> None:
    """下载包应包含可直接加载的扩展运行文件。"""

    response = client.get("/api/v1/browser-extension/download")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert "memoisle-browser-extension.zip" in response.headers[
        "content-disposition"
    ]
    with ZipFile(BytesIO(response.content)) as archive:
        file_names = set(archive.namelist())
        assert file_names == {
            "memoisle-extension/README.md",
            "memoisle-extension/background.js",
            "memoisle-extension/manifest.json",
        }
        manifest = json.loads(
            archive.read("memoisle-extension/manifest.json").decode("utf-8")
        )
    assert manifest["manifest_version"] == 3
    assert "tabs" in manifest["permissions"]
