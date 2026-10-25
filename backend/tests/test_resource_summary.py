"""网页资料用途简介：模型调用、写入保护、冷却与隐私字段测试。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from uuid import uuid4

import httpx
import pytest
from app.models import Memo
from app.resource_summary_service import summarize_user_resources
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def pause_summary_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    """只允许测试显式驱动，避免后台循环发出请求。"""

    async def idle(
        _database_url: str,
        _settings: object,
        stop_event: asyncio.Event,
    ) -> None:
        """在测试生命周期结束时退出。"""

        await stop_event.wait()

    monkeypatch.setattr("app.main.resource_summary_loop", idle)


def configure_deepseek(client: TestClient) -> None:
    """使用模拟配置，不访问真实服务。"""

    response = client.put(
        "/api/v1/model-settings/deepseek",
        json={
            "model": "deepseek-test",
            "api_key": "summary-test-fake-key",
            "base_url": "https://relay.example/v1",
        },
    )
    assert response.status_code == 200


def seed_resource(client: TestClient, title: str = "Python 文档") -> str:
    """插入一条已抓取完元数据的网页，备注里放私人内容。"""

    memo_id = str(uuid4())
    with client.app.state.database.session_factory() as session:
        session.add(
            Memo(
                id=memo_id,
                user_id=client.app.state.settings.local_user_id,
                client_id=str(uuid4()),
                type="resource",
                title=title,
                body="我的私人备注",
                source_url=f"https://example.com/{memo_id}",
                resource_description="The official home of Python",
                resource_metadata_status="ready",
                link_health_status="healthy",
            )
        )
        session.commit()
    return memo_id


def model_client(
    handler: Callable[[httpx.Request], httpx.Response],
) -> httpx.Client:
    """把模型请求交给本地处理函数。"""

    return httpx.Client(transport=httpx.MockTransport(handler))


def completion(summary: str) -> httpx.Response:
    """构造 OpenAI 兼容响应。"""

    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": json.dumps({"summary": summary})}}]},
    )


def run(client: TestClient, http: httpx.Client) -> int:
    """为本地用户处理一批网页。"""

    with client.app.state.database.session_factory() as session:
        return summarize_user_resources(
            session,
            client.app.state.settings.local_user_id,
            client.app.state.settings,
            8,
            http,
        )


def test_summary_is_written_synced_and_searchable(client: TestClient) -> None:
    """写入简介会提升版本供客户端同步，且不把备注发给模型。"""

    configure_deepseek(client)
    memo_id = seed_resource(client)
    before = client.get(f"/api/v1/memos/{memo_id}").json()
    sent: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return completion("「Python 官方文档，查标准库用法和语言参考。」")

    assert run(client, model_client(handler)) == 1
    assert str(sent[0]["model"]) == "deepseek-test"
    user_text = json.dumps(sent[0]["messages"], ensure_ascii=False)
    assert "我的私人备注" not in user_text
    assert "The official home of Python" in user_text

    after = client.get(f"/api/v1/memos/{memo_id}").json()
    assert after["resource_ai_summary"] == "Python 官方文档，查标准库用法和语言参考。"
    assert after["version"] == before["version"] + 1
    found = client.get("/api/v1/memos", params={"q": "标准库用法"}).json()
    assert [item["id"] for item in found["items"]] == [memo_id]

    # 已有简介的网页不再请求模型。
    assert run(client, model_client(handler)) == 0
    assert len(sent) == 1


def test_without_model_settings_nothing_is_sent(client: TestClient) -> None:
    """账号和服务器都未配置 DeepSeek 时直接跳过。"""

    seed_resource(client)

    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("不应请求模型")

    assert run(client, model_client(handler)) == 0


def test_insufficient_information_waits_for_retry(client: TestClient) -> None:
    """模型认为信息不足时只记录尝试，不改版本，冷却期内不再请求。"""

    configure_deepseek(client)
    memo_id = seed_resource(client)
    before = client.get(f"/api/v1/memos/{memo_id}").json()
    calls: list[int] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return completion("")

    assert run(client, model_client(handler)) == 0
    assert run(client, model_client(handler)) == 0
    assert len(calls) == 1
    after = client.get(f"/api/v1/memos/{memo_id}").json()
    assert after["resource_ai_summary"] is None
    assert after["version"] == before["version"]


def test_quota_error_stops_the_batch(client: TestClient) -> None:
    """额度或凭据错误对整批都成立，本轮只请求一次。"""

    configure_deepseek(client)
    seed_resource(client, "第一条")
    seed_resource(client, "第二条")
    calls: list[int] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(429, json={"error": {"type": "rate_limit_error"}})

    assert run(client, model_client(handler)) == 0
    assert len(calls) == 1


def test_edit_during_generation_wins(client: TestClient) -> None:
    """模型等待期间换了网址，晚到的简介不能写到新网址上。"""

    configure_deepseek(client)
    memo_id = seed_resource(client)
    current = client.get(f"/api/v1/memos/{memo_id}").json()

    def handler(_request: httpx.Request) -> httpx.Response:
        edited = client.patch(
            f"/api/v1/memos/{memo_id}",
            json={
                "expected_version": current["version"],
                "source_url": "https://example.org/changed",
            },
        )
        assert edited.status_code == 200
        return completion("旧网址的简介")

    assert run(client, model_client(handler)) == 0
    after = client.get(f"/api/v1/memos/{memo_id}").json()
    assert after["resource_ai_summary"] is None


def test_url_change_clears_summary(client: TestClient) -> None:
    """换网址后旧简介不再适用，等待重新生成。"""

    configure_deepseek(client)
    memo_id = seed_resource(client)
    assert run(client, model_client(lambda _request: completion("旧简介"))) == 1
    current = client.get(f"/api/v1/memos/{memo_id}").json()
    assert current["resource_ai_summary"] == "旧简介"

    edited = client.patch(
        f"/api/v1/memos/{memo_id}",
        json={
            "expected_version": current["version"],
            "source_url": "https://example.org/new",
        },
    )
    assert edited.status_code == 200
    assert edited.json()["resource_ai_summary"] is None
