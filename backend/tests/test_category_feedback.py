"""分类反馈回流测试：人工修正既当正例，也当原分类的反例。"""

from __future__ import annotations

from uuid import uuid4

from app.category_service import (
    category_exemplars,
    category_rejected_examples,
)
from app.models import Memo
from app.resource_classification_quality import parse_jev_assessment
from app.resource_processing import ClassificationCategory
from fastapi.testclient import TestClient

TOOL = ClassificationCategory(code="tool", label="工具与服务", is_fallback=True)
AGENTS = ClassificationCategory(
    code="custom_agents",
    label="agents代码工具",
    path="工具与服务 / agents代码工具",
)


def create_resource(client: TestClient, title: str) -> str:
    """通过真实接口创建一条网页资料。"""

    response = client.post(
        "/api/v1/memos",
        json={
            "client_id": str(uuid4()),
            "type": "resource",
            "title": title,
            "body": "用户的私人备注不会发送给模型",
            "source_url": f"https://github.com/example/{uuid4().hex}",
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def model_pick(choice: str) -> dict[str, object]:
    """构造一次成功的 Jev 判断证据。"""

    _, assessment = parse_jev_assessment(
        {"answers": {"category": {"choice": choice, "confidence": 0.9}}},
        {"tool": "工具与服务", "custom_agents": "agents代码工具"},
        0.7,
        "typesafe/jev",
        False,
    )
    return dict(assessment)


def correct_memo(
    client: TestClient,
    memo_id: str,
    *,
    picked: str,
    final: str,
) -> None:
    """把模型首选写入证据，再按用户的人工选择落库。"""

    with client.app.state.database.session_factory() as session:
        memo = session.get(Memo, memo_id)
        assert memo is not None
        memo.link_health_status = "healthy"
        memo.resource_metadata_status = "ready"
        memo.resource_ai_assessment = model_pick(picked)
        memo.resource_category = final
        memo.resource_category_source = "manual"
        memo.version += 1
        session.commit()


def test_correction_becomes_negative_example_for_rejected_category(
    client: TestClient,
) -> None:
    """模型判成工具、用户改成 agents 代码工具的条目，是工具类的反例。"""

    memo_id = create_resource(client, "GitHub - example/agent-tool")
    correct_memo(client, memo_id, picked="tool", final="custom_agents")

    with client.app.state.database.session_factory() as session:
        rejected = category_rejected_examples(
            session,
            client.app.state.settings.local_user_id,
            [TOOL, AGENTS],
        )
        confirmed = category_exemplars(
            session,
            client.app.state.settings.local_user_id,
            [TOOL, AGENTS],
        )

    assert list(rejected) == ["tool"]
    entry = rejected["tool"][0]
    assert entry["domain"] == "github.com"
    assert entry["actual"] == "工具与服务 / agents代码工具"
    # 同一条同时是目标分类的正例。
    assert [item["title"] for item in confirmed["custom_agents"]] == [
        "GitHub - example/agent-tool"
    ]
    assert "tool" not in confirmed


def test_kept_model_choice_is_not_a_negative_example(client: TestClient) -> None:
    """用户保留模型判断时不产生反例。"""

    memo_id = create_resource(client, "GitHub - example/plain-tool")
    correct_memo(client, memo_id, picked="tool", final="tool")

    with client.app.state.database.session_factory() as session:
        rejected = category_rejected_examples(
            session,
            client.app.state.settings.local_user_id,
            [TOOL, AGENTS],
        )

    assert rejected == {}


def test_model_only_records_are_not_used_as_feedback(client: TestClient) -> None:
    """模型自己的旧结论不算已确认，不会变成正例或反例。"""

    memo_id = create_resource(client, "GitHub - example/auto-tool")
    with client.app.state.database.session_factory() as session:
        memo = session.get(Memo, memo_id)
        assert memo is not None
        memo.resource_ai_assessment = model_pick("tool")
        memo.resource_category = "tool"
        memo.resource_category_source = "jev"
        session.commit()

    with client.app.state.database.session_factory() as session:
        user_id = client.app.state.settings.local_user_id
        rejected = category_rejected_examples(session, user_id, [TOOL, AGENTS])
        confirmed = category_exemplars(session, user_id, [TOOL, AGENTS])

    assert rejected == {}
    assert confirmed == {}
