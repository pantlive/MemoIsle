"""FTS5 全文检索：触发器维护、相关度排序与短关键词回退。"""

from __future__ import annotations

from uuid import uuid4

from app import memo_search
from fastapi.testclient import TestClient


def _create(client: TestClient, **fields: object) -> dict[str, object]:
    payload = {"client_id": str(uuid4()), "type": "idea", "body": "", **fields}
    response = client.post("/api/v1/memos", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _search(client: TestClient, query: str, sort: str = "relevance") -> list[str]:
    response = client.get("/api/v1/memos", params={"q": query, "sort": sort})
    assert response.status_code == 200, response.text
    return [item["id"] for item in response.json()["items"]]


def test_fts_is_enabled_on_sqlite(client: TestClient) -> None:
    assert memo_search.fts_enabled()


def test_relevance_ranks_title_hits_first(client: TestClient) -> None:
    body_hit = _create(client, title="周末计划", body="顺便研究一下向量数据库的选型")
    title_hit = _create(client, title="向量数据库笔记", body="记录索引原理")
    assert _search(client, "向量数据库") == [title_hit["id"], body_hit["id"]]
    # 按更新时间排序时仍是最新的在前，不受相关度影响。
    assert _search(client, "向量数据库", sort="updated_desc") == [
        title_hit["id"],
        body_hit["id"],
    ]


def test_index_follows_updates_and_deletes(client: TestClient) -> None:
    memo = _create(client, body="原始内容里有火山口")
    assert _search(client, "火山口") == [memo["id"]]

    updated = client.patch(
        f"/api/v1/memos/{memo['id']}",
        json={"body": "改写后讲的是珊瑚礁", "expected_version": memo["version"]},
    )
    assert updated.status_code == 200, updated.text
    assert _search(client, "火山口") == []
    assert _search(client, "珊瑚礁") == [memo["id"]]

    trashed = client.delete(
        f"/api/v1/memos/{memo['id']}?expected_version={updated.json()['version']}"
    )
    assert trashed.status_code == 200
    assert _search(client, "珊瑚礁") == []


def test_short_tokens_and_tags_still_match(client: TestClient) -> None:
    tagged = _create(client, body="任意正文", tags=["读书"])
    other = _create(client, body="无关内容")
    # 两个字的中文关键词不足 trigram 长度，走 FTS 表上的 LIKE。
    assert _search(client, "读书") == [tagged["id"]]
    assert other["id"] not in _search(client, "读书")
    # 长短词混合时两者都要满足。
    assert _search(client, "任意正文 读书") == [tagged["id"]]
    assert _search(client, "任意正文 不存在") == []


def test_rebuild_restores_missing_index_rows(client: TestClient) -> None:
    memo = _create(client, body="需要重建的极光记录")
    database = client.app.state.database
    with database.engine.begin() as connection:
        connection.exec_driver_sql("DELETE FROM memo_search")
        connection.exec_driver_sql("DELETE FROM memo_search_doc")
    assert _search(client, "极光记录") == []
    with database.engine.begin() as connection:
        assert memo_search.ensure_memo_search_index(connection)
    assert _search(client, "极光记录") == [memo["id"]]
