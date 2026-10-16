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


def test_import_keeps_valid_categories_when_some_codes_are_missing(
    client: TestClient,
) -> None:
    """备份里失效的自定义分类不能把仍有效的系统分类一并丢掉。"""

    payload = {
        "format": "memoisle-json",
        "version": 1,
        "memos": [
            {
                "client_id": str(uuid4()),
                "type": "resource",
                "title": "部分分类失效",
                "body": "https://example.com/partial-category",
                "source_url": "https://example.com/partial-category",
                "resource_category": "learning",
                "resource_categories": ["learning", "custom_deleted_elsewhere"],
            },
            {
                "client_id": str(uuid4()),
                "type": "resource",
                "title": "全部分类失效",
                "body": "https://example.com/gone-category",
                "source_url": "https://example.com/gone-category",
                "resource_category": "custom_deleted_elsewhere",
                "resource_categories": ["custom_deleted_elsewhere"],
                "resource_category_label": "旧自定义分类",
            },
        ],
    }
    response = client.post(
        "/api/v1/imports?format=json",
        content=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 200
    assert response.json()["imported_count"] == 2

    items = client.get("/api/v1/memos", params={"type": "resource"}).json()["items"]
    partial = next(item for item in items if item["title"] == "部分分类失效")
    assert partial["resource_category"] == "learning"
    assert partial["resource_categories"] == ["learning"]

    gone = next(item for item in items if item["title"] == "全部分类失效")
    assert gone["resource_category"] is None
    assert gone["resource_categories"] == []
    assert gone["resource_category_label"] == "旧自定义分类"


def test_import_csv_restores_review_progress(client: TestClient) -> None:
    """CSV 把复习整数写成文本，导入后仍要恢复熟悉度和复习次数。"""

    word_id = str(uuid4())
    csv_text = (
        "client_id,type,title,body,word_meaning,familiarity,review_count\n"
        f"{word_id},word,csvword,可导入的,可导入的,3,5\n"
    )
    response = client.post(
        "/api/v1/imports?format=csv",
        content=csv_text.encode("utf-8"),
        headers={"Content-Type": "text/csv"},
    )
    assert response.status_code == 200
    assert response.json()["imported_count"] == 1

    words = client.get("/api/v1/memos", params={"type": "word"}).json()["items"]
    imported = next(item for item in words if item["title"] == "csvword")
    assert imported["familiarity"] == 3
    assert imported["review_count"] == 5


def test_import_image_restores_categories(client: TestClient) -> None:
    """图片备份同样恢复多分类。"""

    image_id = str(uuid4())
    payload = {
        "format": "memoisle-json",
        "version": 1,
        "memos": [
            {
                "client_id": image_id,
                "type": "image",
                "title": "分类图片",
                "body": "课堂笔记",
                "resource_category": "learning",
                "resource_categories": ["learning", "article"],
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

    items = client.get("/api/v1/memos", params={"type": "image"}).json()["items"]
    imported = next(item for item in items if item["title"] == "分类图片")
    assert imported["resource_category"] == "learning"
    assert imported["resource_categories"] == ["learning", "article"]


def test_import_restores_ebook_cloud_references(client: TestClient) -> None:
    """同账号还原时保留云盘电子书引用，不含文件本体。"""

    resource_id = str(uuid4())
    payload = {
        "format": "memoisle-json",
        "version": 1,
        "memos": [
            {
                "client_id": resource_id,
                "type": "resource",
                "title": "云盘电子书",
                "body": "https://example.com/ebook",
                "source_url": "https://example.com/ebook",
                "ebook_provider": "aliyun",
                "ebook_file_id": "file-42",
                "ebook_path": "/books/guide.epub",
                "ebook_share_url": "https://example.com/share/guide",
                "ebook_format": "epub",
                "ebook_size_bytes": 2048,
                "ebook_snapshot": {"name": "guide.epub"},
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

    items = client.get("/api/v1/memos", params={"type": "resource"}).json()["items"]
    imported = next(item for item in items if item["title"] == "云盘电子书")
    assert imported["ebook_provider"] == "aliyun"
    assert imported["ebook_file_id"] == "file-42"
    assert imported["ebook_path"] == "/books/guide.epub"
    assert imported["ebook_share_url"] == "https://example.com/share/guide"
    assert imported["ebook_format"] == "epub"
    assert imported["ebook_size_bytes"] == 2048
    assert imported["ebook_snapshot"] == {"name": "guide.epub"}


def test_import_restores_timestamps_as_utc(client: TestClient) -> None:
    """备份时间写入 UTC：带 Z、带偏移和无时区的字符串都按 UTC 解释。"""

    payload = {
        "format": "memoisle-json",
        "version": 1,
        "memos": [
            {
                "client_id": str(uuid4()),
                "type": "idea",
                "title": "旧灵感",
                "body": "带时区",
                "created_at": "2020-01-02T03:04:05Z",
                "updated_at": "2020-06-07T08:09:10+08:00",
            },
            {
                "client_id": str(uuid4()),
                "type": "idea",
                "title": "无时区灵感",
                "body": "按 UTC 解释",
                "created_at": "2019-12-01T10:11:12",
                "updated_at": "2019-12-01T10:11:12",
            },
        ],
    }
    response = client.post(
        "/api/v1/imports?format=json",
        content=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 200
    assert response.json()["imported_count"] == 2

    items = client.get("/api/v1/memos", params={"type": "idea"}).json()["items"]
    zoned = next(item for item in items if item["title"] == "旧灵感")
    assert zoned["created_at"] == "2020-01-02T03:04:05Z"
    assert zoned["updated_at"] == "2020-06-07T00:09:10Z"
    naive = next(item for item in items if item["title"] == "无时区灵感")
    assert naive["created_at"] == "2019-12-01T10:11:12Z"
    assert naive["updated_at"] == "2019-12-01T10:11:12Z"


def test_import_recreates_custom_category_templates(client: TestClient) -> None:
    """JSON 备份里的自定义分类按原 code 重建，条目才能对上。"""

    custom_code = f"custom_{uuid4().hex}"
    child_code = f"custom_{uuid4().hex}"
    payload = {
        "format": "memoisle-json",
        "version": 1,
        "categories": [
            {
                "code": custom_code,
                "name": "备份编程",
                "parent_code": "learning",
                "is_active": True,
            },
            {
                "code": child_code,
                "name": "备份 Python",
                "parent_code": custom_code,
                "is_active": True,
            },
        ],
        "memos": [
            {
                "client_id": str(uuid4()),
                "type": "resource",
                "title": "带自定义分类的文章",
                "body": "https://example.com/restore-category",
                "source_url": "https://example.com/restore-category",
                "resource_category": child_code,
                "resource_categories": [child_code, "article"],
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

    categories = client.get("/api/v1/resource-categories").json()
    codes = {item["code"]: item for item in categories}
    assert custom_code in codes
    assert child_code in codes
    assert codes[child_code]["parent_code"] == custom_code
    assert codes[child_code]["path"] == "学习资料 / 备份编程 / 备份 Python"

    items = client.get("/api/v1/memos", params={"type": "resource"}).json()["items"]
    imported = next(item for item in items if item["title"] == "带自定义分类的文章")
    assert imported["resource_category"] == child_code
    assert imported["resource_categories"] == [child_code, "article"]


def test_export_json_includes_category_templates(client: TestClient) -> None:
    """JSON 导出带上自定义分类，便于换账号还原。"""

    login = client.post("/api/v1/auth/dev-login")
    assert login.status_code == 200
    created = client.post("/api/v1/resource-categories", json={"name": "导出分类"})
    assert created.status_code == 201
    exported = client.get("/api/v1/exports/json")
    assert exported.status_code == 200
    payload = exported.json()
    assert payload["format"] == "memoisle-json"
    codes = {item["code"] for item in payload["categories"]}
    assert created.json()["code"] in codes

