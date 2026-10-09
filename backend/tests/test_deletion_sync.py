"""永久删除通知的账号隔离、组合分页及离线重放保护。"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.auth_service import create_dev_session
from app.models import Memo, MemoDeletion
from fastapi.testclient import TestClient


def create_idea(client: TestClient) -> dict[str, object]:
    """创建不触发模型和抓取的普通条目。"""

    response = client.post(
        "/api/v1/memos",
        json={
            "client_id": str(uuid4()),
            "type": "idea",
            "body": "删除通知不会保留正文",
        },
    )
    assert response.status_code == 201
    return response.json()


@pytest.mark.parametrize("method", ["single", "all", "expired"])
def test_all_permanent_delete_paths_emit_minimal_notification(
    client: TestClient,
    method: str,
) -> None:
    """单条删除、清空和保留期清理都能通知离线设备，不保留正文。"""

    memo = create_idea(client)
    cursor = client.get("/api/v1/sync/changes").json()["cursor"]
    trashed = client.delete(
        f"/api/v1/memos/{memo['id']}",
        params={
            "expected_version": memo["version"],
        },
    ).json()
    if method == "single":
        response = client.delete(
            f"/api/v1/memos/{memo['id']}/permanent",
            params={
                "expected_version": trashed["version"],
            },
        )
        assert response.status_code == 200
    elif method == "all":
        assert client.delete("/api/v1/memos/trash").json()["deleted_count"] == 1
    else:
        with client.app.state.database.session_factory() as session:
            row = session.get(Memo, memo["id"])
            row.deleted_at = datetime.now(UTC) - timedelta(days=31)
            session.commit()
    page = client.get("/api/v1/sync/changes", params={"cursor": cursor}).json()
    assert page["items"] == []
    assert len(page["deleted_items"]) == 1 and not page["has_more"]
    notice = page["deleted_items"][0]
    assert notice["memo_id"] == memo["id"] and notice["client_id"] == memo["client_id"]
    assert set(notice) == {"memo_id", "client_id", "deleted_at"}
    assert (
        client.post(
            "/api/v1/memos",
            json={
                "client_id": memo["client_id"],
                "type": "idea",
                "body": "旧设备重试",
            },
        ).status_code
        == 410
    )
    client.app.state.database.create_schema()
    assert client.get("/api/v1/sync/changes", params={"cursor": cursor}).json()[
        "deleted_items"
    ] == [notice]


def test_mixed_same_timestamp_pages_and_delete_only_pages_do_not_skip(
    client: TestClient,
) -> None:
    """更新与删除共享排序游标，相同时间及只含删除的满页都不会漏项。"""

    ids = sorted(str(uuid4()) for _ in range(7))
    timestamp = datetime(2025, 1, 1, tzinfo=UTC)
    with client.app.state.database.session_factory() as session:
        for index, memo_id in enumerate(ids):
            if index % 2:
                session.add(
                    Memo(
                        id=memo_id,
                        client_id=str(uuid4()),
                        user_id=client.app.state.settings.local_user_id,
                        type="idea",
                        title="同步条目",
                        body="",
                        updated_at=timestamp,
                    )
                )
            else:
                session.add(
                    MemoDeletion(
                        memo_id=memo_id,
                        client_id=str(uuid4()),
                        user_id=client.app.state.settings.local_user_id,
                        deleted_at=timestamp,
                    )
                )
        session.commit()
    params: dict[str, object] = {"limit": 2}
    seen: list[str] = []
    while True:
        page = client.get("/api/v1/sync/changes", params=params).json()
        current = [row["id"] for row in page["items"]] + [
            row["memo_id"] for row in page["deleted_items"]
        ]
        assert len(current) <= 2
        seen.extend(current)
        if not page["has_more"]:
            break
        params.update(cursor=page["cursor"], cursor_id=page["cursor_id"])
    assert sorted(seen) == ids and len(seen) == len(set(seen))


def test_deletion_notifications_are_account_scoped(client: TestClient) -> None:
    """删除通知、客户端重放拦截和游标均不泄漏其他账号标识。"""

    memo = create_idea(client)
    client.delete(
        f"/api/v1/memos/{memo['id']}", params={"expected_version": memo["version"]}
    )
    client.delete("/api/v1/memos/trash")
    settings = client.app.state.settings
    with client.app.state.database.session_factory() as session:
        token = create_dev_session(
            session, replace(settings, local_user_id=str(uuid4()))
        ).token
    client.app.state.settings = replace(settings, auth_dev_mode=False)
    assert client.get("/api/v1/sync/changes").status_code == 401
    headers = {"Authorization": f"Bearer {token}"}
    assert (
        client.get("/api/v1/sync/changes", headers=headers).json()["deleted_items"]
        == []
    )
    assert (
        client.post(
            "/api/v1/memos",
            headers=headers,
            json={
                "client_id": memo["client_id"],
                "type": "idea",
                "body": "其他账号的新条目",
            },
        ).status_code
        == 201
    )
