"""易忘事项：文字、图片、文件、版本冲突、隔离、限额和备份目录。"""

from __future__ import annotations

import io
from dataclasses import replace
from urllib.parse import quote
from uuid import uuid4

from app.auth_service import create_dev_session
from app.service import MAX_IMAGE_BYTES
from fastapi.testclient import TestClient
from PIL import Image

BASE = "/api/v1/forget"


def item(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "title": "门禁密码放哪",
        "content": "抽屉第二层",
        "pinned": False,
    }
    payload.update(overrides)
    return payload


def create(client: TestClient, **overrides: object) -> dict[str, object]:
    response = client.post(f"{BASE}/items", json=item(**overrides))
    assert response.status_code == 201, response.text
    body: dict[str, object] = response.json()
    return body


def upload(
    client: TestClient,
    item_id: str,
    content: bytes,
    filename: str,
    mime: str,
) -> dict[str, object]:
    response = client.post(
        f"{BASE}/items/{item_id}/attachments",
        content=content,
        headers={"Content-Type": mime, "X-Filename": quote(filename)},
    )
    assert response.status_code == 201, response.text
    body: dict[str, object] = response.json()
    return body


def png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), "#336699").save(buffer, format="PNG")
    return buffer.getvalue()


def other_account_headers(client: TestClient) -> dict[str, str]:
    """新建另一个账号并关闭开发模式回退，之后不带令牌的请求会被拒绝。"""

    settings = client.app.state.settings
    with client.app.state.database.session_factory() as session:
        token = create_dev_session(
            session, replace(settings, local_user_id=str(uuid4()))
        ).token
    client.app.state.settings = replace(settings, auth_dev_mode=False)
    return {"Authorization": f"Bearer {token}"}


def stored_files(client: TestClient) -> list:
    directory = client.app.state.settings.forget_directory
    if not directory.exists():
        return []
    return [path for path in directory.rglob("*") if path.is_file()]


def test_crud_search_and_pin_order(client: TestClient) -> None:
    """新建、搜索、修改、置顶排序和删除。"""

    pinned = create(client, title="  先记住这个  ", content="  ", pinned=True)
    assert pinned["title"] == "先记住这个"
    assert pinned["content"] == ""
    assert pinned["pinned"] is True
    assert pinned["version"] == 1
    assert pinned["attachments"] == []
    assert pinned["created_at"].endswith("Z")

    later = create(client, title="其他", content="备用钥匙在门口")
    listed = client.get(f"{BASE}/items").json()
    # 后写的更新，但置顶的仍排在前面。
    assert [row["id"] for row in listed] == [pinned["id"], later["id"]]

    by_title = client.get(f"{BASE}/items", params={"q": "记住"}).json()
    assert [row["id"] for row in by_title] == [pinned["id"]]
    by_body = client.get(f"{BASE}/items", params={"q": "钥匙"}).json()
    assert [row["id"] for row in by_body] == [later["id"]]
    assert client.get(f"{BASE}/items", params={"q": "不存在"}).json() == []

    updated = client.put(
        f"{BASE}/items/{later['id']}",
        json=item(
            title="改过的标题",
            content="新的正文",
            pinned=False,
            expected_version=1,
        ),
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["version"] == 2
    assert updated.json()["title"] == "改过的标题"

    removed = client.delete(
        f"{BASE}/items/{later['id']}", params={"expected_version": 2}
    )
    assert removed.status_code == 204
    assert [row["id"] for row in client.get(f"{BASE}/items").json()] == [pinned["id"]]
    assert (
        client.delete(
            f"{BASE}/items/{later['id']}", params={"expected_version": 2}
        ).status_code
        == 404
    )


def test_version_conflict_returns_current_item(client: TestClient) -> None:
    created = create(client)
    saved = client.put(
        f"{BASE}/items/{created['id']}",
        json=item(title="新标题", expected_version=1),
    )
    assert saved.status_code == 200, saved.text

    stale = client.put(
        f"{BASE}/items/{created['id']}",
        json=item(title="更旧的标题", expected_version=1),
    )
    assert stale.status_code == 409
    detail = stale.json()["detail"]
    assert detail["code"] == "version_conflict"
    assert detail["current"]["version"] == 2
    assert detail["current"]["title"] == "新标题"

    stale_delete = client.delete(
        f"{BASE}/items/{created['id']}", params={"expected_version": 1}
    )
    assert stale_delete.status_code == 409
    assert stale_delete.json()["detail"]["current"]["version"] == 2


def test_other_user_cannot_see_or_change_items(client: TestClient) -> None:
    created = create(client)
    uploaded = upload(
        client, str(created["id"]), b"secret-note", "note.txt", "text/plain"
    )
    attachment_id = uploaded["attachments"][0]["id"]
    headers = other_account_headers(client)

    assert client.get(f"{BASE}/items", headers=headers).json() == []
    assert (
        client.put(
            f"{BASE}/items/{created['id']}",
            headers=headers,
            json=item(expected_version=1),
        ).status_code
        == 404
    )
    assert (
        client.delete(
            f"{BASE}/items/{created['id']}",
            headers=headers,
            params={"expected_version": 1},
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"{BASE}/items/{created['id']}/attachments",
            headers={**headers, "Content-Type": "text/plain", "X-Filename": "a.txt"},
            content=b"nope",
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"{BASE}/items/{created['id']}/attachments/{attachment_id}",
            headers=headers,
        ).status_code
        == 404
    )
    assert (
        client.delete(
            f"{BASE}/items/{created['id']}/attachments/{attachment_id}",
            headers=headers,
        ).status_code
        == 404
    )


def test_attachment_limits_chinese_name_and_download_headers(
    client: TestClient, monkeypatch: object
) -> None:
    """超过 20 MB、超过 20 个附件会被拒绝；下载按类型决定是否内联。"""

    assert MAX_IMAGE_BYTES == 20 * 1024 * 1024
    created = create(client)
    item_id = str(created["id"])

    named = upload(client, item_id, "会议纪要".encode(), "会议纪要.txt", "text/plain")
    text = named["attachments"][0]
    assert text["kind"] == "file"
    assert text["original_name"] == "会议纪要.txt"
    assert text["original_name"] not in {path.name for path in stored_files(client)}
    user_id = client.app.state.settings.local_user_id
    assert all(path.parent.name == user_id for path in stored_files(client))

    download = client.get(f"{BASE}/items/{item_id}/attachments/{text['id']}")
    assert download.status_code == 200, download.text
    disposition = download.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    assert f"filename*=UTF-8''{quote('会议纪要.txt')}" in disposition
    assert download.headers["content-type"].startswith("application/octet-stream")
    assert download.headers["x-content-type-options"] == "nosniff"
    assert download.content == "会议纪要".encode()

    html = upload(
        client,
        item_id,
        b"<script>alert(1)</script>",
        "page.html",
        "text/html",
    )["attachments"][-1]
    html_download = client.get(f"{BASE}/items/{item_id}/attachments/{html['id']}")
    assert html_download.headers["content-disposition"].startswith("attachment;")
    assert html_download.headers["content-type"].startswith("application/octet-stream")
    assert html_download.headers["x-content-type-options"] == "nosniff"

    disguised = upload(
        client,
        item_id,
        b"<html>not a png</html>",
        "fake.png",
        "image/png",
    )["attachments"][-1]
    assert disguised["kind"] == "file"
    fake_download = client.get(f"{BASE}/items/{item_id}/attachments/{disguised['id']}")
    assert fake_download.headers["content-disposition"].startswith("attachment;")
    assert fake_download.headers["x-content-type-options"] == "nosniff"

    image = upload(client, item_id, png_bytes(), "画面.png", "image/png")
    image = image["attachments"][-1]
    assert image["kind"] == "image"
    assert image["mime"] == "image/png"
    image_download = client.get(f"{BASE}/items/{item_id}/attachments/{image['id']}")
    assert image_download.headers["content-disposition"].startswith("inline;")
    assert image_download.headers["content-type"].startswith("image/png")
    assert image_download.headers["x-content-type-options"] == "nosniff"
    assert f"filename*=UTF-8''{quote('画面.png')}" in image_download.headers[
        "content-disposition"
    ]

    traversed = upload(
        client, item_id, b"x", "../../etc/passwd", "text/plain"
    )["attachments"][-1]
    assert traversed["original_name"] == "passwd"

    monkeypatch.setattr("app.forget_api.MAX_IMAGE_BYTES", 8)
    too_big = client.post(
        f"{BASE}/items/{item_id}/attachments",
        content=b"0123456789",
        headers={"Content-Type": "text/plain", "X-Filename": "big.txt"},
    )
    assert too_big.status_code == 413

    # 上面已经有若干附件，补到 20 个后再拒绝。
    existing = len(client.get(f"{BASE}/items").json()[0]["attachments"])
    for index in range(existing, 20):
        upload(client, item_id, b"x", f"extra-{index}.txt", "text/plain")
    overflow = client.post(
        f"{BASE}/items/{item_id}/attachments",
        content=b"x",
        headers={"Content-Type": "text/plain", "X-Filename": "overflow.txt"},
    )
    assert overflow.status_code == 400
    assert overflow.json()["detail"] == "每条最多 20 个附件"


def test_deleting_item_or_attachment_removes_files(client: TestClient) -> None:
    created = create(client)
    item_id = str(created["id"])
    uploaded = upload(client, item_id, b"keep-me", "keep.txt", "text/plain")
    attachment_id = uploaded["attachments"][0]["id"]
    upload(client, item_id, b"drop-me", "drop.txt", "text/plain")
    assert len(stored_files(client)) == 2

    removed = client.delete(f"{BASE}/items/{item_id}/attachments/{attachment_id}")
    assert removed.status_code == 204
    assert len(stored_files(client)) == 1
    listed = client.get(f"{BASE}/items").json()
    assert [row["original_name"] for row in listed[0]["attachments"]] == ["drop.txt"]

    deleted = client.delete(
        f"{BASE}/items/{item_id}", params={"expected_version": listed[0]["version"]}
    )
    assert deleted.status_code == 204
    assert stored_files(client) == []
    assert client.get(f"{BASE}/items").json() == []
