"""分页选择、部分成功、账号隔离及并发删除保护。"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from app.auth_service import create_dev_session
from app.models import Memo, MemoDeletion
from app.service import delete_memo_snapshot
from fastapi.testclient import TestClient


def seed_memos(client: TestClient, count: int, trashed: bool = False) -> list[str]:
    """直接建立超过两百条的隔离测试记录。"""

    ids = [str(uuid4()) for _ in range(count)]
    with client.app.state.database.session_factory() as session:
        session.add_all(
            [
                Memo(
                    id=memo_id,
                    user_id=client.app.state.settings.local_user_id,
                    client_id=str(uuid4()),
                    type="idea",
                    title=f"批量 {index}",
                    body="",
                    status="trashed" if trashed else "active",
                    deleted_at=datetime.now(UTC) if trashed else None,
                    status_before_trash="archived" if trashed else None,
                )
                for index, memo_id in enumerate(ids)
            ]
        )
        session.commit()
    return ids


@pytest.mark.parametrize("trashed", [False, True])
@pytest.mark.parametrize("limit", [10, 25, 50, 100])
def test_list_pages_cover_all_records_without_hidden_selection(
    client: TestClient,
    trashed: bool,
    limit: int,
) -> None:
    """不同页大小均覆盖全库，当前页选择不影响隐藏记录。"""

    ids = seed_memos(client, 237, trashed)
    seen: set[str] = set()
    for offset in range(0, len(ids), limit):
        response = client.get(
            "/api/v1/memos",
            params={
                "status": "trashed" if trashed else "active",
                "limit": limit,
                "offset": offset,
            },
        )
        assert response.status_code == 200
        page = response.json()
        assert page["total_count"] == 237
        current = {row["id"] for row in page["items"]}
        assert not seen.intersection(current)
        seen.update(current)
    assert seen == set(ids)
    chosen = [{"memo_id": memo_id, "expected_version": 1} for memo_id in ids[:2]]
    result = client.post(
        "/api/v1/memos/batch",
        json={
            "action": "restore" if trashed else "trash",
            "items": chosen,
        },
    ).json()
    assert result["updated_count"] == 2 and result["skipped_count"] == 0
    assert (
        client.get(
            "/api/v1/memos",
            params={
                "status": "trashed" if trashed else "active",
            },
        ).json()["total_count"]
        == 235
    )


def test_mixed_batch_returns_conflicts_and_preserves_restore_status(
    client: TestClient,
) -> None:
    """旧版本、不适用状态和缺失记录逐项跳过，正确记录仍恢复原状态。"""

    ids = seed_memos(client, 3, True)
    active = seed_memos(client, 1)[0]
    with client.app.state.database.session_factory() as session:
        row = session.get(Memo, ids[0])
        row.version = 2
        row.title = "其他设备已修改"
        session.commit()
    selections = [
        {"memo_id": memo_id, "expected_version": 1}
        for memo_id in [ids[0], ids[1], active, str(uuid4())]
    ]
    result = client.post(
        "/api/v1/memos/batch",
        json={
            "action": "restore",
            "items": selections,
        },
    ).json()
    assert result["updated_count"] == 1 and result["skipped_count"] == 3
    assert [row["reason"] for row in result["results"]] == [
        "conflict",
        None,
        "not_applicable",
        "missing",
    ]
    restored = client.get(f"/api/v1/memos/{ids[1]}").json()
    assert restored["status"] == "archived" and restored["version"] == 2
    assert restored["deleted_at"] is None


def test_selected_permanent_delete_notifies_only_selected_records(
    client: TestClient,
) -> None:
    """永久删除只作用于明确选择，不将整个回收站清空。"""

    ids = seed_memos(client, 4, True)
    response = client.post(
        "/api/v1/memos/batch",
        json={
            "action": "permanent",
            "items": [{"memo_id": ids[2], "expected_version": 1}],
        },
    )
    assert response.status_code == 200 and response.json()["updated_count"] == 1
    page = client.get("/api/v1/sync/changes").json()
    assert [item["memo_id"] for item in page["deleted_items"]] == [ids[2]]
    assert {item["id"] for item in page["items"]} == set(ids) - {ids[2]}


def test_batch_limits_auth_and_expired_restore(client: TestClient) -> None:
    """限制重复选择和数量，恢复不能绕过保留期或账号边界。"""

    ids = seed_memos(client, 2, True)
    item = {"memo_id": ids[0], "expected_version": 1}
    for items in [
        [],
        [item, item],
        [{"memo_id": str(uuid4()), "expected_version": 1} for _ in range(101)],
    ]:
        assert (
            client.post(
                "/api/v1/memos/batch",
                json={
                    "action": "restore",
                    "items": items,
                },
            ).status_code
            == 422
        )
    with client.app.state.database.session_factory() as session:
        row = session.get(Memo, ids[0])
        row.deleted_at = datetime.now(UTC) - timedelta(days=31)
        session.commit()
    result = client.post(
        "/api/v1/memos/batch",
        json={
            "action": "restore",
            "items": [item],
        },
    ).json()
    assert result["results"][0]["reason"] == "missing"
    settings = client.app.state.settings
    with client.app.state.database.session_factory() as session:
        token = create_dev_session(
            session, replace(settings, local_user_id=str(uuid4()))
        ).token
    client.app.state.settings = replace(settings, auth_dev_mode=False)
    assert (
        client.post(
            "/api/v1/memos/batch", json={"action": "restore", "items": [item]}
        ).status_code
        == 401
    )
    response = client.post(
        "/api/v1/memos/batch",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "action": "permanent",
            "items": [{"memo_id": ids[1], "expected_version": 1}],
        },
    )
    assert response.json()["results"][0]["reason"] == "missing"
    with client.app.state.database.session_factory() as session:
        assert session.get(Memo, ids[1]) is not None


def test_stale_delete_snapshot_preserves_restored_image_and_files(
    client: TestClient,
    tmp_path: Path,
) -> None:
    """还原赢得并发时，旧清空快照不能删除记录、附件或产生通知。"""

    memo_id = seed_memos(client, 1, True)[0]
    path = tmp_path / "restored.image"
    path.write_bytes(b"synthetic attachment")
    factory = client.app.state.database.session_factory
    with factory() as deletion_session:
        snapshot = deletion_session.get(Memo, memo_id)
        snapshot.image_storage_name = path.name
        deletion_session.commit()
        # 提前加载属性，模拟已经显示给用户的旧版本快照。
        assert snapshot.version == 1
        with factory() as restoration_session:
            restored = restoration_session.get(Memo, memo_id)
            restored.status = "active"
            restored.version += 1
            restoration_session.commit()
        assert not delete_memo_snapshot(deletion_session, snapshot, tmp_path, tmp_path)
    assert path.is_file()
    with factory() as session:
        assert session.get(Memo, memo_id).status == "active"
        assert session.get(MemoDeletion, memo_id) is None
