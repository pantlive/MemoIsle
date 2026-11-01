"""每周摘要与随机漫游。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.models import Memo
from fastapi.testclient import TestClient


def _create(client: TestClient, **fields: object) -> dict[str, object]:
    payload = {"client_id": str(uuid4()), "type": "idea", "body": "正文", **fields}
    response = client.post("/api/v1/memos", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_weekly_summary_counts_recent_activity(client: TestClient) -> None:
    idea = _create(client, title="本周想法", tags=["写作", "产品"])
    _create(client, title="另一个", tags=["写作"])
    word = _create(client, type="word", title="serendipity", body="意外发现")
    resource = _create(
        client,
        type="resource",
        title="一篇文章",
        source_url="https://example.com/a",
    )
    old = _create(client, title="很久以前", tags=["旧标签"])

    database = client.app.state.database
    now = datetime.now(UTC)
    with database.session_factory() as session:
        stale = session.get(Memo, str(old["id"]))
        stale.created_at = now - timedelta(days=30)
        reviewed = session.get(Memo, str(word["id"]))
        reviewed.last_review_at = now - timedelta(days=1)
        opened = session.get(Memo, str(resource["id"]))
        opened.resource_last_opened_at = now - timedelta(hours=2)
        session.commit()

    response = client.get("/api/v1/review/weekly-summary")
    assert response.status_code == 200, response.text
    summary = response.json()
    assert summary["created_total"] == 4
    assert summary["created_by_type"]["idea"] == 2
    assert summary["created_by_type"]["word"] == 1
    assert summary["created_by_type"]["resource"] == 1
    assert summary["reviewed_words"] == 1
    assert summary["opened_resources"] == 1
    assert summary["top_tags"][0] == {"tag": "写作", "count": 2}
    assert all(tag["tag"] != "旧标签" for tag in summary["top_tags"])
    highlight_ids = [item["id"] for item in summary["highlights"]]
    assert idea["id"] in highlight_ids
    assert old["id"] not in highlight_ids


def test_random_walk_respects_type_and_exclusions(client: TestClient) -> None:
    empty = client.get("/api/v1/review/random")
    assert empty.status_code == 200
    assert empty.json() == {"item": None}

    first = _create(client, title="第一条")
    second = _create(client, title="第二条")
    word = _create(client, type="word", title="ephemeral", body="短暂的")

    picked = client.get("/api/v1/review/random", params={"type": "word"}).json()
    assert picked["item"]["id"] == word["id"]

    excluded = client.get(
        "/api/v1/review/random",
        params={"type": "idea", "exclude": [first["id"]]},
    ).json()
    assert excluded["item"]["id"] == second["id"]

    # 全部被排除时仍然返回一条，而不是空结果。
    fallback = client.get(
        "/api/v1/review/random",
        params={"type": "idea", "exclude": [first["id"], second["id"]]},
    ).json()
    assert fallback["item"]["id"] in {first["id"], second["id"]}
