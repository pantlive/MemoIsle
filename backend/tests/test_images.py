"""图片收藏接口测试。"""

from __future__ import annotations

import hashlib
import io
from pathlib import Path
from uuid import uuid4

import pytest
from app.service import MAX_IMAGE_BYTES, ImageValidationError, _decode_image
from fastapi.testclient import TestClient
from PIL import Image


def create_image_memo(client: TestClient, title: str = "测试图片") -> dict[str, object]:
    """创建一条图片收藏测试数据。"""

    response = client.post(
        "/api/v1/memos",
        json={
            "client_id": str(uuid4()),
            "type": "image",
            "title": title,
            "body": "图片收藏备注",
        },
    )
    assert response.status_code == 201
    result: dict[str, object] = response.json()
    return result


def create_idea_memo(client: TestClient) -> dict[str, object]:
    """创建一条非图片类型测试数据。"""

    response = client.post(
        "/api/v1/memos",
        json={
            "client_id": str(uuid4()),
            "type": "idea",
            "body": "这不是图片收藏",
        },
    )
    assert response.status_code == 201
    result: dict[str, object] = response.json()
    return result


def test_upload_and_download_image(client: TestClient) -> None:
    """图片收藏可上传原图和缩略图，并再次读取原图。"""

    created = create_image_memo(client)
    memo_id = str(created["id"])
    buffer = io.BytesIO()
    Image.new("RGB", (320, 180), "#336699").save(buffer, format="PNG")
    image_content = buffer.getvalue()

    uploaded = client.post(
        f"/api/v1/memos/{memo_id}/image",
        params={"expected_version": 1},
        headers={"Content-Type": "image/png"},
        content=image_content,
    )
    assert uploaded.status_code == 200
    payload = uploaded.json()
    assert payload["image_mime_type"] == "image/png"
    assert payload["image_width"] == 320
    assert payload["image_height"] == 180
    assert payload["image_size_bytes"] == len(image_content)
    assert payload["image_hash"] == hashlib.sha256(image_content).hexdigest()
    assert payload["version"] == 2

    image_directory = client.app.state.settings.image_directory
    assert isinstance(image_directory, Path)
    assert (image_directory / f"{memo_id}.image").is_file()
    assert (image_directory / f"{memo_id}.thumbnail.webp").is_file()

    original = client.get(f"/api/v1/memos/{memo_id}/image")
    assert original.status_code == 200
    assert original.content == image_content
    assert original.headers["content-type"].startswith("image/png")

    thumbnail = client.get(f"/api/v1/memos/{memo_id}/image/thumbnail")
    assert thumbnail.status_code == 200
    assert thumbnail.headers["content-type"].startswith("image/webp")
    thumbnail_image = Image.open(io.BytesIO(thumbnail.content))
    assert thumbnail_image.format == "WEBP"


def test_image_upload_rejects_wrong_type_and_invalid_file(
    client: TestClient,
) -> None:
    """非图片条目和伪造图片都不能上传。"""

    idea = create_idea_memo(client)
    wrong_type = client.post(
        f"/api/v1/memos/{idea['id']}/image",
        params={"expected_version": 1},
        headers={"Content-Type": "image/png"},
        content=b"fake-image",
    )
    assert wrong_type.status_code == 422

    created = create_image_memo(client, "伪造图片")
    invalid_file = client.post(
        f"/api/v1/memos/{created['id']}/image",
        params={"expected_version": 1},
        headers={"Content-Type": "image/png"},
        content=b"not-an-image",
    )
    assert invalid_file.status_code == 422
    assert invalid_file.json()["detail"] == "图片文件无效或已损坏"


def test_image_counts_and_permanent_delete(client: TestClient) -> None:
    """图片计入类型统计，永久删除时清理原图和缩略图。"""

    created = create_image_memo(client, "统计和删除图片")
    memo_id = str(created["id"])
    buffer = io.BytesIO()
    Image.new("RGB", (24, 24), "#996633").save(buffer, format="PNG")
    uploaded = client.post(
        f"/api/v1/memos/{memo_id}/image",
        params={"expected_version": 1},
        headers={"Content-Type": "image/png"},
        content=buffer.getvalue(),
    )
    assert uploaded.status_code == 200

    counts = client.get("/api/v1/memos/counts").json()
    assert counts["image_count"] == 1

    image_directory = client.app.state.settings.image_directory
    original_path = image_directory / f"{memo_id}.image"
    thumbnail_path = image_directory / f"{memo_id}.thumbnail.webp"
    assert original_path.is_file()
    assert thumbnail_path.is_file()

    trashed = client.delete(
        f"/api/v1/memos/{memo_id}",
        params={"expected_version": uploaded.json()["version"]},
    )
    assert trashed.status_code == 200
    deleted = client.delete(
        f"/api/v1/memos/{memo_id}/permanent",
        params={"expected_version": trashed.json()["version"]},
    )
    assert deleted.status_code == 200
    assert original_path.is_file() is False
    assert thumbnail_path.is_file() is False


def test_create_image_memo_allows_empty_body(client: TestClient) -> None:
    """图片收藏可以只有图片，正文允许留空。"""

    response = client.post(
        "/api/v1/memos",
        json={
            "client_id": str(uuid4()),
            "type": "image",
            "title": "旅行照片",
            "body": "",
        },
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["type"] == "image"
    assert payload["title"] == "旅行照片"
    assert payload["body"] == ""

    untitled = client.post(
        "/api/v1/memos",
        json={
            "client_id": str(uuid4()),
            "type": "image",
            "body": "",
        },
    )
    assert untitled.status_code == 201
    assert untitled.json()["title"] == "图片收藏"

    empty_idea = client.post(
        "/api/v1/memos",
        json={"client_id": str(uuid4()), "type": "idea", "body": ""},
    )
    assert empty_idea.status_code == 422


def test_update_image_note_and_clear(client: TestClient) -> None:
    """图片收藏可以编辑标题备注，也可以把备注清空。"""

    created = create_image_memo(client, "旧标题")
    memo_id = str(created["id"])
    updated = client.patch(
        f"/api/v1/memos/{memo_id}",
        json={
            "expected_version": 1,
            "title": "新标题",
            "body": "新的备注",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["title"] == "新标题"
    assert updated.json()["body"] == "新的备注"
    assert updated.json()["version"] == 2

    cleared = client.patch(
        f"/api/v1/memos/{memo_id}",
        json={"expected_version": 2, "body": ""},
    )
    assert cleared.status_code == 200
    assert cleared.json()["body"] == ""
    assert cleared.json()["version"] == 3


def test_image_upload_replaces_previous_file(client: TestClient) -> None:
    """重新上传会替换原图和缩略图并递增版本号。"""

    created = create_image_memo(client, "替换图片")
    memo_id = str(created["id"])
    first = io.BytesIO()
    Image.new("RGB", (100, 60), "#112233").save(first, format="PNG")
    uploaded = client.post(
        f"/api/v1/memos/{memo_id}/image",
        params={"expected_version": 1},
        headers={"Content-Type": "image/png"},
        content=first.getvalue(),
    )
    assert uploaded.status_code == 200
    assert uploaded.json()["image_width"] == 100

    second = io.BytesIO()
    Image.new("RGB", (48, 80), "#332211").save(second, format="JPEG")
    replaced = client.post(
        f"/api/v1/memos/{memo_id}/image",
        params={"expected_version": 2},
        headers={"Content-Type": "image/jpeg"},
        content=second.getvalue(),
    )
    assert replaced.status_code == 200
    payload = replaced.json()
    assert payload["version"] == 3
    assert payload["image_mime_type"] == "image/jpeg"
    assert payload["image_width"] == 48
    assert payload["image_height"] == 80

    original = client.get(f"/api/v1/memos/{memo_id}/image")
    assert original.status_code == 200
    assert original.content == second.getvalue()


def test_image_is_searchable_and_exported(client: TestClient) -> None:
    """图片收藏出现在类型列表与关键词搜索中，并带元数据导出。"""

    assert client.post("/api/v1/auth/dev-login").status_code == 200
    created = create_image_memo(client, "海边日落")
    memo_id = str(created["id"])
    buffer = io.BytesIO()
    Image.new("RGB", (64, 32), "#ff8800").save(buffer, format="PNG")
    assert (
        client.post(
            f"/api/v1/memos/{memo_id}/image",
            params={"expected_version": 1},
            headers={"Content-Type": "image/png"},
            content=buffer.getvalue(),
        ).status_code
        == 200
    )

    listed = client.get("/api/v1/memos", params={"type": "image"})
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["items"]] == [memo_id]

    searched = client.get("/api/v1/memos", params={"q": "日落"})
    assert searched.status_code == 200
    assert [item["id"] for item in searched.json()["items"]] == [memo_id]

    exported = client.get("/api/v1/exports/json")
    assert exported.status_code == 200
    assert exported.json()["image_files_included"] is False
    exported_image = next(
        item for item in exported.json()["memos"] if item["id"] == memo_id
    )
    assert exported_image["image_mime_type"] == "image/png"
    assert exported_image["image_width"] == 64

    markdown = client.get("/api/v1/exports/markdown")
    assert markdown.status_code == 200
    assert "image_mime_type" in markdown.text
    assert "image_width" in markdown.text
    assert "图片文件未包含" in markdown.text


def test_oversized_image_content_is_rejected() -> None:
    """超过 20 MB 的字节即使绕过客户端压缩也会在解码前被拒绝。"""

    with pytest.raises(ImageValidationError):
        _decode_image(b"\x00" * (MAX_IMAGE_BYTES + 1), "image/png")

