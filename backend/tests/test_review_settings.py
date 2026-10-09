"""自定义复习计划接口测试。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient


def create_word(client: TestClient, lemma: str) -> dict[str, object]:
    """创建一条最小单词测试数据。"""

    response = client.post(
        "/api/v1/memos",
        json={
            "client_id": str(uuid4()),
            "type": "word",
            "title": lemma,
            "body": f"{lemma} 的释义",
            "tags": [],
        },
    )
    assert response.status_code == 201
    return response.json()


def test_review_plan_defaults_and_updates_queue(client: TestClient) -> None:
    """复习计划可保存，并限制今日队列而不丢失待处理数量。"""

    defaults = client.get("/api/v1/review-settings")
    assert defaults.status_code == 200
    assert defaults.json() == {
        "daily_limit": 10,
        "intervals_days": [1, 3, 7, 14, 30, 60],
    }

    words = [create_word(client, lemma) for lemma in ("alpha", "bravo", "charlie")]
    updated = client.patch(
        "/api/v1/review-settings",
        json={
            "daily_limit": 2,
            "intervals_days": [2, 4, 6, 8, 10, 12],
        },
    )
    assert updated.status_code == 200
    assert updated.json() == {
        "daily_limit": 2,
        "intervals_days": [2, 4, 6, 8, 10, 12],
    }

    queue = client.get("/api/v1/review-queue").json()
    assert len(queue["items"]) == 2
    assert queue["scheduled_count"] == 2
    assert queue["daily_limit"] == 2
    assert queue["word_count"] == len(words)

    reviewed = client.post(
        f"/api/v1/words/{words[0]['id']}/reviews",
        json={"expected_version": 1, "feedback": "remembered"},
    )
    assert reviewed.status_code == 200
    last_review_at = datetime.fromisoformat(
        reviewed.json()["last_review_at"].replace("Z", "+00:00")
    )
    next_review_at = datetime.fromisoformat(
        reviewed.json()["next_review_at"].replace("Z", "+00:00")
    )
    assert last_review_at.tzinfo is not None
    assert next_review_at - last_review_at == timedelta(days=4)
    assert datetime.now(UTC) < next_review_at


def test_review_plan_rejects_invalid_intervals(client: TestClient) -> None:
    """复习计划拒绝错误的间隔数量和范围。"""

    too_few = client.patch(
        "/api/v1/review-settings",
        json={"intervals_days": [1, 2]},
    )
    assert too_few.status_code == 422

    out_of_range = client.patch(
        "/api/v1/review-settings",
        json={"intervals_days": [1, 2, 3, 4, 5, 0]},
    )
    assert out_of_range.status_code == 422

    empty = client.patch("/api/v1/review-settings", json={})
    assert empty.status_code == 422
