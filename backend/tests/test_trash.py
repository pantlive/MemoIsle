"""回收站列表、恢复、永久删除和 30 天清理。"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.auth_service import create_dev_session
from app.models import Memo
from app.schemas import MemoStatus, MemoType
from fastapi.testclient import TestClient
from sqlalchemy import select


def _create_idea(client: TestClient, body: str = "回收站测试灵感") -> dict[str, object]:
    """创建一条灵感。"""

    response = client.post(
        "/api/v1/memos",
        json={
            "client_id": str(uuid4()),
            "type": "idea",
            "body": body,
        },
    )
    assert response.status_code == 201
    result: dict[str, object] = response.json()
    return result


def test_delete_moves_memo_to_trash_and_restore_returns_inbox(
    client: TestClient,
) -> None:
    """删除进入回收站，恢复后回到进入前的 inbox 状态。"""

    created = _create_idea(client)
    memo_id = created["id"]
    trashed = client.delete(
        f"/api/v1/memos/{memo_id}",
        params={"expected_version": created["version"]},
    )
    assert trashed.status_code == 200
    payload = trashed.json()
    assert payload["status"] == "trashed"
    assert payload["deleted_at"] is not None
    assert client.get("/api/v1/memos").json()["items"] == []

    trash_list = client.get("/api/v1/memos", params={"status": "trashed"})
    assert trash_list.status_code == 200
    assert [item["id"] for item in trash_list.json()["items"]] == [memo_id]

    restored = client.post(
        f"/api/v1/memos/{memo_id}/restore",
        params={"expected_version": payload["version"]},
    )
    assert restored.status_code == 200
    assert restored.json()["status"] == "inbox"
    assert restored.json()["deleted_at"] is None
    assert [item["id"] for item in client.get("/api/v1/memos").json()["items"]] == [
        memo_id
    ]
    trash_after_restore = client.get(
        "/api/v1/memos",
        params={"status": "trashed"},
    )
    assert trash_after_restore.json()["items"] == []


def test_permanent_delete_requires_trash_and_removes_row(
    client: TestClient,
) -> None:
    """未进回收站不能永久删除；进回收站后永久删除会移除条目。"""

    created = _create_idea(client)
    memo_id = created["id"]
    blocked = client.delete(
        f"/api/v1/memos/{memo_id}/permanent",
        params={"expected_version": created["version"]},
    )
    assert blocked.status_code == 400

    trashed = client.delete(
        f"/api/v1/memos/{memo_id}",
        params={"expected_version": created["version"]},
    )
    assert trashed.status_code == 200
    deleted = client.delete(
        f"/api/v1/memos/{memo_id}/permanent",
        params={"expected_version": trashed.json()["version"]},
    )
    assert deleted.status_code == 200
    assert deleted.json()["status"] == "deleted"
    assert client.get(f"/api/v1/memos/{memo_id}").status_code == 404
    remaining = client.get("/api/v1/memos", params={"status": "trashed"})
    assert remaining.json()["items"] == []


def test_expired_trash_is_purged_after_retention_days(
    client: TestClient,
) -> None:
    """超过保留天数的回收站条目会在读取回收站时被永久清理。"""

    created = _create_idea(client, "过期回收站条目")
    memo_id = str(created["id"])
    trashed = client.delete(
        f"/api/v1/memos/{memo_id}",
        params={"expected_version": created["version"]},
    )
    assert trashed.status_code == 200

    database = client.app.state.database
    with database.session_factory() as session:
        memo = session.scalar(select(Memo).where(Memo.id == memo_id))
        assert memo is not None
        memo.deleted_at = datetime.now(UTC) - timedelta(days=31)
        session.commit()

    remaining = client.get("/api/v1/memos", params={"status": "trashed"})
    assert remaining.status_code == 200
    assert remaining.json()["items"] == []
    assert client.get(f"/api/v1/memos/{memo_id}").status_code == 404


def test_permanent_delete_removes_audio_file(client: TestClient) -> None:
    """永久删除带录音的灵感时同时删除音频文件。"""

    created = _create_idea(client, "语音记录")
    memo_id = str(created["id"])
    audio_directory = client.app.state.settings.audio_directory
    audio_directory.mkdir(parents=True, exist_ok=True)
    uploaded = client.post(
        f"/api/v1/memos/{memo_id}/audio",
        params={"expected_version": created["version"]},
        headers={"content-type": "audio/mp4", "x-audio-duration-ms": "1200"},
        content=b"fake-m4a-bytes",
    )
    assert uploaded.status_code == 200
    storage_name = f"{memo_id}.audio"
    audio_path = audio_directory / storage_name
    assert audio_path.is_file()

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
    assert audio_path.is_file() is False


def test_patch_status_trashed_sets_deleted_at(client: TestClient) -> None:
    """现有 PATCH 移入回收站的路径同样记录删除时间。"""

    created = _create_idea(client)
    patched = client.patch(
        f"/api/v1/memos/{created['id']}",
        json={"expected_version": created["version"], "status": "trashed"},
    )
    assert patched.status_code == 200
    assert patched.json()["status"] == "trashed"
    assert patched.json()["deleted_at"] is not None


def test_restore_all_preserves_statuses_attachments_and_sync_versions(
    client: TestClient,
) -> None:
    """批量还原各类收藏的原状态及附件，更新时间和版本可被同步识别。"""

    cases = (
        ("idea", "inbox"),
        ("idea", "archived"),
        ("word", "active"),
        ("resource", "archived"),
        ("image", "active"),
    )
    trashed: list[dict[str, object]] = []
    for index, (memo_type, original_status) in enumerate(cases):
        payload = {
            "client_id": str(uuid4()),
            "type": memo_type,
            "title": f"批量还原 {index}",
            "body": "保留原始内容",
        }
        if memo_type == "resource":
            payload["source_url"] = "https://example.com/restore"
        response = client.post("/api/v1/memos", json=payload)
        assert response.status_code == 201
        memo = response.json()
        if memo["status"] != original_status:
            response = client.patch(
                f"/api/v1/memos/{memo['id']}",
                json={
                    "expected_version": memo["version"],
                    "status": original_status,
                },
            )
            assert response.status_code == 200
            memo = response.json()
        deleted = client.delete(
            f"/api/v1/memos/{memo['id']}",
            params={
                "expected_version": memo["version"],
            },
        )
        assert deleted.status_code == 200
        trashed.append(deleted.json())

    settings = client.app.state.settings
    settings.audio_directory.mkdir(parents=True, exist_ok=True)
    settings.image_directory.mkdir(parents=True, exist_ok=True)
    audio_path = settings.audio_directory / "batch-restore.audio"
    image_path = settings.image_directory / "batch-restore.image"
    thumbnail_path = settings.image_directory / "batch-restore.thumbnail.webp"
    for path in (audio_path, image_path, thumbnail_path):
        path.write_bytes(b"isolated-test-attachment")
    with client.app.state.database.session_factory() as session:
        session.get(Memo, trashed[0]["id"]).audio_storage_name = audio_path.name
        image = session.get(Memo, trashed[-1]["id"])
        image.image_storage_name = image_path.name
        image.image_thumbnail_storage_name = thumbnail_path.name
        session.commit()

    response = client.post("/api/v1/memos/trash/restore")
    assert response.status_code == 200
    assert response.json() == {"restored_count": len(cases)}
    for memo, (_, original_status) in zip(trashed, cases, strict=True):
        restored = client.get(f"/api/v1/memos/{memo['id']}").json()
        assert restored["status"] == original_status
        assert restored["deleted_at"] is None
        assert restored["version"] == memo["version"] + 1
        assert restored["updated_at"] > memo["updated_at"]
        assert restored["body"] == "保留原始内容"
    assert all(path.exists() for path in (audio_path, image_path, thumbnail_path))
    assert client.post("/api/v1/memos/trash/restore").json()["restored_count"] == 0

    # 批量清空复用永久删除流程，原图、缩略图和录音都一起清理。
    for memo in trashed:
        current = client.get(f"/api/v1/memos/{memo['id']}").json()
        client.delete(
            f"/api/v1/memos/{memo['id']}",
            params={
                "expected_version": current["version"],
            },
        ).raise_for_status()
    assert client.delete("/api/v1/memos/trash").json()["deleted_count"] == len(cases)
    assert not any(path.exists() for path in (audio_path, image_path, thumbnail_path))


@pytest.mark.parametrize("action", ["restore", "empty"])
def test_bulk_trash_actions_are_authenticated_and_account_scoped(
    client: TestClient,
    action: str,
) -> None:
    """批量操作要求登录，且不会处理其他账号或当前账号的正常内容。"""

    settings = client.app.state.settings
    with client.app.state.database.session_factory() as session:
        own = create_dev_session(session, settings).token
        other = create_dev_session(
            session,
            replace(settings, local_user_id=str(uuid4())),
        ).token
    client.app.state.settings = replace(settings, auth_dev_mode=False)
    method = "POST" if action == "restore" else "DELETE"
    endpoint = (
        "/api/v1/memos/trash/restore" if action == "restore" else "/api/v1/memos/trash"
    )
    assert client.request(method, endpoint).status_code == 401
    created: dict[str, list[dict[str, object]]] = {}
    for owner, token in (("own", own), ("other", other)):
        client.headers["Authorization"] = f"Bearer {token}"
        normal = _create_idea(client, f"{owner} 保留内容")
        removed = _create_idea(client, f"{owner} 回收站内容")
        response = client.delete(
            f"/api/v1/memos/{removed['id']}",
            params={
                "expected_version": removed["version"],
            },
        )
        assert response.status_code == 200
        created[owner] = [normal, response.json()]
    client.headers["Authorization"] = f"Bearer {own}"
    response = client.request(method, endpoint)
    assert response.status_code == 200
    assert response.json() == {
        "restored_count" if action == "restore" else "deleted_count": 1
    }
    own_normal = client.get(f"/api/v1/memos/{created['own'][0]['id']}").json()
    assert own_normal["version"] == created["own"][0]["version"]
    assert own_normal["status"] == "inbox"
    client.headers["Authorization"] = f"Bearer {other}"
    other_trash = client.get("/api/v1/memos", params={"status": "trashed"}).json()
    assert [memo["id"] for memo in other_trash["items"]] == [created["other"][1]["id"]]
    assert client.get(f"/api/v1/memos/{created['other'][0]['id']}").status_code == 200


@pytest.mark.parametrize("action", ["restore", "empty"])
def test_bulk_trash_actions_cover_items_beyond_search_and_page_limit(
    client: TestClient,
    action: str,
) -> None:
    """超过默认一百条展示限制的回收站，也能在一次请求中全部处理。"""

    normal = _create_idea(client, "正常条目保留")
    settings = client.app.state.settings
    with client.app.state.database.session_factory() as session:
        session.add_all(
            [
                Memo(
                    id=str(uuid4()),
                    client_id=str(uuid4()),
                    user_id=settings.local_user_id,
                    type=MemoType.IDEA,
                    title=f"已删除内容 {index}",
                    body="回收站分页测试",
                    status=MemoStatus.TRASHED,
                    status_before_trash="inbox",
                    deleted_at=datetime.now(UTC),
                )
                for index in range(105)
            ]
        )
        session.commit()
    page = client.get("/api/v1/memos", params={"status": "trashed"}).json()
    assert len(page["items"]) == 100
    assert page["total_count"] == 105
    filtered = client.get(
        "/api/v1/memos",
        params={
            "status": "trashed",
            "query": "内容 104",
            "limit": 1,
        },
    ).json()
    assert len(filtered["items"]) == 1
    response = (
        client.post("/api/v1/memos/trash/restore")
        if action == "restore"
        else client.delete("/api/v1/memos/trash")
    )
    assert response.status_code == 200
    assert response.json() == {
        "restored_count" if action == "restore" else "deleted_count": 105
    }
    assert (
        client.get("/api/v1/memos", params={"status": "trashed"}).json()["total_count"]
        == 0
    )
    assert client.get(f"/api/v1/memos/{normal['id']}").json()["status"] == "inbox"


def test_bulk_restore_does_not_revive_expired_trash(client: TestClient) -> None:
    """一键还原沿用三十天期限，到期条目清理，不会被重新带回收藏。"""

    fresh = _create_idea(client, "仍可恢复")
    expired = _create_idea(client, "过期内容")
    for memo in (fresh, expired):
        client.delete(
            f"/api/v1/memos/{memo['id']}",
            params={
                "expected_version": memo["version"],
            },
        ).raise_for_status()
    with client.app.state.database.session_factory() as session:
        session.get(Memo, expired["id"]).deleted_at = datetime.now(UTC) - timedelta(
            days=31
        )
        session.commit()
    response = client.post("/api/v1/memos/trash/restore")
    assert response.status_code == 200
    assert response.json() == {"restored_count": 1}
    assert client.get(f"/api/v1/memos/{fresh['id']}").json()["status"] == "inbox"
    assert client.get(f"/api/v1/memos/{expired['id']}").status_code == 404
    assert client.delete("/api/v1/memos/trash").json() == {"deleted_count": 0}
