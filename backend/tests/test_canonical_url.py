"""网页资料规范化网址列的行为测试。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from app.database import Database
from app.models import Memo
from fastapi.testclient import TestClient


def create_resource(
    client: TestClient,
    url: str,
    title: str = "示例网页",
) -> dict[str, object]:
    """创建一条网页资料。"""

    response = client.post(
        "/api/v1/memos",
        json={
            "client_id": "3f6b0f26-1e0b-4c1c-9a70-6d8f2f9c4a01",
            "type": "resource",
            "body": url,
            "source_url": url,
            "source_title": title,
            "tags": [],
        },
    )
    assert response.status_code == 201, response.text
    result: dict[str, object] = response.json()
    return result


def canonical_url_of(client: TestClient, memo_id: str) -> str | None:
    """直接读库取出规范化网址。"""

    with client.app.state.database.session_factory() as session:
        memo = session.get(Memo, memo_id)
        assert memo is not None
        return memo.canonical_url


def test_resource_stores_canonical_url(client: TestClient) -> None:
    """创建网页资料时把规范化网址写进单独一列。"""

    created = create_resource(
        client,
        "HTTPS://Example.COM:443/guide/?b=2&a=1#section",
    )
    assert canonical_url_of(client, str(created["id"])) == (
        "https://example.com/guide/?b=2&a=1"
    )


def test_canonical_url_tracks_source_url_edits(client: TestClient) -> None:
    """修改来源网址后重算，转成其他类型时清空。"""

    created = create_resource(client, "https://example.com/old")
    memo_id = str(created["id"])
    version = int(created["version"])

    updated = client.patch(
        f"/api/v1/memos/{memo_id}",
        json={
            "expected_version": version,
            "source_url": "https://Example.com/new?x=1#frag",
        },
    )
    assert updated.status_code == 200, updated.text
    assert canonical_url_of(client, memo_id) == "https://example.com/new?x=1"

    converted = client.patch(
        f"/api/v1/memos/{memo_id}",
        json={
            "expected_version": updated.json()["version"],
            "type": "idea",
        },
    )
    assert converted.status_code == 200, converted.text
    assert canonical_url_of(client, memo_id) is None


def test_duplicate_detection_uses_canonical_url(client: TestClient) -> None:
    """大小写、默认端口和 fragment 不同也视为同一网页。"""

    create_resource(client, "https://example.com/library")
    duplicate = client.post(
        "/api/v1/memos",
        json={
            "client_id": "9c1f2f96-0e4c-4a0f-8a2f-2f2f2f2f2f2f",
            "type": "resource",
            "body": "HTTPS://EXAMPLE.COM:443/library#top",
            "source_url": "HTTPS://EXAMPLE.COM:443/library#top",
            "tags": [],
        },
    )
    assert duplicate.status_code == 409
    detail = duplicate.json()["detail"]
    assert detail["code"] == "duplicate_resource"


def test_trashed_resource_does_not_block_new_save(client: TestClient) -> None:
    """回收站里的同网址资料不再参与查重。"""

    created = create_resource(client, "https://example.com/reusable")
    trashed = client.patch(
        f"/api/v1/memos/{created['id']}",
        json={
            "expected_version": created["version"],
            "status": "trashed",
        },
    )
    assert trashed.status_code == 200

    again = client.post(
        "/api/v1/memos",
        json={
            "client_id": "5d0f6a1c-31f4-4a63-9f5b-6c0f9d0e1a22",
            "type": "resource",
            "body": "https://example.com/reusable",
            "source_url": "https://example.com/reusable",
            "tags": [],
        },
    )
    assert again.status_code == 201


def test_upgrade_backfills_canonical_url(tmp_path: Path) -> None:
    """旧库补列后按来源网址回填规范化结果。"""

    from app.schemas import MemoCreate, MemoType
    from app.service import create_memo

    database_path = tmp_path / "upgrade.db"
    database = Database(f"sqlite+pysqlite:///{database_path}")
    database.create_schema()

    # 先写入两条网页资料，再把新列删掉，模拟升级前的库。
    with database.session_factory() as session:
        for index, url in enumerate(
            ["HTTPS://Example.COM:443/guide#top", "https://example.com/other"],
        ):
            create_memo(
                session,
                "u1",
                MemoCreate(
                    client_id=f"00000000-0000-0000-0000-00000000000{index}",
                    type=MemoType.RESOURCE,
                    body=url,
                    source_url=url,
                    tags=[],
                ),
            )
    database.dispose()

    with sqlite3.connect(database_path) as connection:
        connection.execute("DROP INDEX ix_memo_user_canonical_url")
        connection.execute("ALTER TABLE memo DROP COLUMN canonical_url")

    upgraded = Database(f"sqlite+pysqlite:///{database_path}")
    upgraded.create_schema()
    try:
        with upgraded.engine.connect() as connection:
            rows = dict(
                connection.exec_driver_sql(
                    "SELECT id, canonical_url FROM memo",
                ).all(),
            )
        assert sorted(rows.values()) == [
            "https://example.com/guide",
            "https://example.com/other",
        ]
    finally:
        upgraded.dispose()


def test_history_marks_saved_with_indexed_lookup(client: TestClient) -> None:
    """历史列表按页查询规范化网址，能标出已收藏的条目。"""

    created = create_resource(client, "https://example.com/guide")
    client.post(
        "/api/v1/browser-history/sync",
        headers={"Origin": f"chrome-extension://{'c' * 32}"},
        json={
            "extension_id": "c" * 32,
            "visits": [
                {
                    "page_url": "https://example.com/guide",
                    "page_title": "指南",
                    "visited_at": "2026-10-20T08:00:00Z",
                },
            ],
        },
    )

    items = client.get("/api/v1/browser-history").json()["items"]
    assert [item["saved_memo_id"] for item in items] == [created["id"]]
