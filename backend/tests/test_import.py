"""完整资料备份导入测试。"""

from __future__ import annotations

import json
from uuid import uuid4

from fastapi.testclient import TestClient


def test_import_json_backup_restores_all_types(client: TestClient) -> None:
    """JSON 备份可恢复灵感、单词和网页资料。"""

    idea_id = str(uuid4())
    word_id = str(uuid4())
    resource_id = str(uuid4())
    payload = {
        "format": "memoisle-json",
        "version": 1,
        "memos": [
            {
                "client_id": idea_id,
                "type": "idea",
                "title": "备份灵感",
                "body": "从导出恢复",
                "transcript": "备份会议转写",
                "tags": ["备份"],
            },
            {
                "client_id": word_id,
                "type": "word",
                "title": "importable",
                "body": "可导入的",
                "word_meaning": "可导入的",
                "word_example": "This word is importable.",
            },
            {
                "client_id": resource_id,
                "type": "resource",
                "title": "备份文章",
                "body": "https://example.com/backup",
                "source_url": "https://example.com/backup",
                "starred": True,
                "resource_category": "learning",
                "resource_categories": ["learning"],
                "status": "trashed",
            },
        ],
    }
    response = client.post(
        "/api/v1/imports?format=json",
        content=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 200
    assert response.json()["imported_count"] == 3
    assert response.json()["failed_count"] == 0

    ideas = client.get("/api/v1/memos", params={"type": "idea"}).json()["items"]
    imported_idea = next(item for item in ideas if item["title"] == "备份灵感")
    assert imported_idea["transcript"] == "备份会议转写"

    words = client.get("/api/v1/memos", params={"type": "word"}).json()["items"]
    assert {item["title"] for item in words} == {"importable"}

    trash = client.get("/api/v1/memos", params={"status": "trashed"}).json()["items"]
    imported_resource = next(item for item in trash if item["title"] == "备份文章")
    assert imported_resource["starred"] is True
    assert imported_resource["resource_category"] == "learning"

    second = client.post(
        "/api/v1/imports?format=json",
        content=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    assert second.status_code == 200
    assert second.json()["imported_count"] == 0
    assert second.json()["duplicate_count"] == 3


def test_import_rejects_markdown(client: TestClient) -> None:
    """Markdown 导出只供阅读，不能作为恢复格式。"""

    response = client.post(
        "/api/v1/imports?format=markdown",
        content=b"# MemoIsle export\n",
        headers={"Content-Type": "text/markdown"},
    )
    assert response.status_code == 422


def test_import_image_backup_keeps_metadata_only(client: TestClient) -> None:
    """图片备份只恢复标题备注和元数据，二进制需要在客户端重新上传。"""

    image_id = str(uuid4())
    payload = {
        "format": "memoisle-json",
        "version": 1,
        "memos": [
            {
                "client_id": image_id,
                "type": "image",
                "title": "备份图片",
                "body": "旅行照片",
                "image_mime_type": "image/png",
                "image_width": 320,
                "image_height": 180,
                "image_size_bytes": 1234,
            }
        ],
    }
    response = client.post(
        "/api/v1/imports?format=json",
        content=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 200
    assert response.json()["imported_count"] == 1
    assert response.json()["failed_count"] == 0

    items = client.get("/api/v1/memos", params={"type": "image"}).json()["items"]
    imported = next(item for item in items if item["title"] == "备份图片")
    assert imported["body"] == "旅行照片"
    # 导出不包含图片二进制，导入后需要重新上传。
    assert imported["image_mime_type"] is None
    assert imported["image_hash"] is None
    assert client.get(f"/api/v1/memos/{imported['id']}/image").status_code == 404

