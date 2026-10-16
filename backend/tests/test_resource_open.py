"""网页资料打开次数与快速访问排序测试。"""

from __future__ import annotations

import json
from uuid import uuid4

from fastapi.testclient import TestClient


def create_resource(client: TestClient, url: str) -> dict[str, object]:
    """创建一条测试网页资料。"""

    response = client.post(
        "/api/v1/memos",
        json={
            "client_id": str(uuid4()),
            "type": "resource",
            "title": url,
            "body": url,
            "source_url": url,
        },
    )
    assert response.status_code == 201
    result: dict[str, object] = response.json()
    return result


def test_record_open_increments_without_touching_version(client: TestClient) -> None:
    """打开只累加统计，不改版本号和更新时间，正在进行的编辑不会冲突。"""

    created = create_resource(client, "https://example.com/open")
    assert created["resource_open_count"] == 0
    assert created["resource_last_opened_at"] is None

    first = client.post(f"/api/v1/resources/{created['id']}/open")
    second = client.post(f"/api/v1/resources/{created['id']}/open")
    assert first.status_code == 200
    assert first.json()["resource_open_count"] == 1
    assert second.json()["resource_open_count"] == 2
    assert second.json()["resource_last_opened_at"].endswith("Z")

    current = client.get(f"/api/v1/memos/{created['id']}").json()
    assert current["resource_open_count"] == 2
    assert current["version"] == created["version"]
    assert current["updated_at"] == created["updated_at"]

    edited = client.patch(
        f"/api/v1/memos/{created['id']}",
        json={"expected_version": created["version"], "title": "改过的标题"},
    )
    assert edited.status_code == 200
    assert edited.json()["resource_open_count"] == 2


def test_opened_desc_sort_ranks_most_opened_first(client: TestClient) -> None:
    """快速访问按打开次数降序，次数相同时最近打开的在前。"""

    rarely = create_resource(client, "https://example.com/rarely")
    often = create_resource(client, "https://example.com/often")
    recent = create_resource(client, "https://example.com/recent")
    never = create_resource(client, "https://example.com/never")
    for memo, times in ((often, 3), (rarely, 1), (recent, 1)):
        for _ in range(times):
            assert (
                client.post(f"/api/v1/resources/{memo['id']}/open").status_code == 200
            )

    response = client.get(
        "/api/v1/memos",
        params={"type": "resource", "sort": "opened_desc"},
    )
    assert response.status_code == 200
    ids = [item["id"] for item in response.json()["items"]]
    assert ids == [often["id"], recent["id"], rarely["id"], never["id"]]


def test_record_open_rejects_other_types_and_trash(client: TestClient) -> None:
    """只有未删除的网页资料记录打开。"""

    idea = client.post(
        "/api/v1/memos",
        json={"client_id": str(uuid4()), "type": "idea", "body": "不是网页"},
    ).json()
    assert client.post(f"/api/v1/resources/{idea['id']}/open").status_code == 400

    resource = create_resource(client, "https://example.com/trashed")
    trashed = client.delete(
        f"/api/v1/memos/{resource['id']}",
        params={"expected_version": resource["version"]},
    )
    assert trashed.status_code in (200, 204)
    assert client.post(f"/api/v1/resources/{resource['id']}/open").status_code == 404
    assert client.post(f"/api/v1/resources/{uuid4()}/open").status_code == 404


def test_json_backup_roundtrip_keeps_open_stats(client: TestClient) -> None:
    """导出再导入后，打开次数和最近打开时间保持不变。"""

    assert client.post("/api/v1/auth/dev-login").status_code == 200
    created = create_resource(client, "https://example.com/backup-open")
    for _ in range(4):
        client.post(f"/api/v1/resources/{created['id']}/open")
    client.put(f"/api/v1/resources/{created['id']}/quick-access", json={"hidden": True})
    exported = client.get("/api/v1/exports/json")
    assert exported.status_code == 200
    backup = exported.json()
    record = next(item for item in backup["memos"] if item["id"] == created["id"])
    assert record["resource_open_count"] == 4
    opened_at = record["resource_last_opened_at"]

    trashed = client.delete(
        f"/api/v1/memos/{created['id']}",
        params={"expected_version": created["version"]},
    )
    assert trashed.status_code in (200, 204)
    deleted = client.delete(
        f"/api/v1/memos/{created['id']}/permanent",
        params={"expected_version": trashed.json()["version"]},
    )
    assert deleted.status_code in (200, 204), deleted.text
    record["client_id"] = str(uuid4())
    restored = client.post(
        "/api/v1/imports?format=json",
        content=json.dumps({**backup, "memos": [record]}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    assert restored.status_code == 200, restored.text
    items = client.get("/api/v1/memos", params={"type": "resource"}).json()["items"]
    match = next(
        item
        for item in items
        if item["source_url"] == "https://example.com/backup-open"
    )
    assert match["resource_open_count"] == 4
    assert match["resource_last_opened_at"] == opened_at
    assert match["resource_quick_access_hidden"] is True


def test_quick_access_lists_opened_and_respects_hidden(client: TestClient) -> None:
    """快速访问只列打开过的网页；移除后不再出现但继续计数，可以恢复。"""

    often = create_resource(client, "https://example.com/qa-often")
    once = create_resource(client, "https://example.com/qa-once")
    create_resource(client, "https://example.com/qa-never")
    for _ in range(3):
        client.post(f"/api/v1/resources/{often['id']}/open")
    client.post(f"/api/v1/resources/{once['id']}/open")

    listed = client.get("/api/v1/resources/quick-access")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [often["id"], once["id"]]
    assert (
        client.get("/api/v1/resources/quick-access", params={"limit": 1}).json()[0][
            "id"
        ]
        == often["id"]
    )

    hidden = client.put(
        f"/api/v1/resources/{often['id']}/quick-access",
        json={"hidden": True},
    )
    assert hidden.status_code == 200
    assert hidden.json() == {"resource_quick_access_hidden": True}
    assert [
        item["id"] for item in client.get("/api/v1/resources/quick-access").json()
    ] == [once["id"]]

    # 移除不算修改，也不影响继续计数。
    current = client.get(f"/api/v1/memos/{often['id']}").json()
    assert current["version"] == often["version"]
    assert current["updated_at"] == often["updated_at"]
    assert current["resource_quick_access_hidden"] is True
    assert (
        client.post(f"/api/v1/resources/{often['id']}/open").json()[
            "resource_open_count"
        ]
        == 4
    )
    assert often["id"] not in [
        item["id"] for item in client.get("/api/v1/resources/quick-access").json()
    ]

    restored = client.put(
        f"/api/v1/resources/{often['id']}/quick-access",
        json={"hidden": False},
    )
    assert restored.json() == {"resource_quick_access_hidden": False}
    assert client.get("/api/v1/resources/quick-access").json()[0]["id"] == often["id"]


def test_quick_access_excludes_trash_and_rejects_other_types(
    client: TestClient,
) -> None:
    """回收站里的网页不出现；非网页资料不能设置快速访问。"""

    resource = create_resource(client, "https://example.com/qa-trash")
    client.post(f"/api/v1/resources/{resource['id']}/open")
    client.delete(
        f"/api/v1/memos/{resource['id']}",
        params={"expected_version": resource["version"]},
    )
    assert client.get("/api/v1/resources/quick-access").json() == []
    assert (
        client.put(
            f"/api/v1/resources/{resource['id']}/quick-access",
            json={"hidden": True},
        ).status_code
        == 404
    )

    idea = client.post(
        "/api/v1/memos",
        json={"client_id": str(uuid4()), "type": "idea", "body": "不是网页"},
    ).json()
    assert (
        client.put(
            f"/api/v1/resources/{idea['id']}/quick-access",
            json={"hidden": True},
        ).status_code
        == 400
    )
