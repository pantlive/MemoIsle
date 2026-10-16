"""分类通道测试：口径判定优先、关键词规则不抢细类、故障不阻断收藏。"""

from __future__ import annotations

import json

import httpx
import pytest
from app.resource_processing import (
    ClassificationCategory,
    ResourceMetadata,
    classify_resource,
)

METADATA = ResourceMetadata(
    final_url="https://github.com/example/agent-tool",
    page_title="GitHub - example/agent-tool: 多代理编排工具",
    description="Orchestrate multiple coding agents",
    site_name="GitHub",
    favicon_url=None,
    http_status=200,
)

CUSTOM_CATEGORY = ClassificationCategory(
    code="custom_agents",
    label="agents代码工具",
    path="工具与服务 / agents代码工具",
    definition="编排 coding agent 的开源工具，含仓库和文档。",
)


def completion(content: dict[str, object]) -> httpx.Response:
    """构造 OpenAI 兼容响应。"""

    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": json.dumps(content)}}]},
    )


def test_deepseek_proposes_tags_then_jev_classifies() -> None:
    """对话模型先列出所有可能标签，再由 Jev 在这份候选里做最终分类。"""

    paths: list[str] = []
    jev_criteria: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path.endswith("/chat/completions"):
            return completion(
                {
                    "category": "custom_agents",
                    "extra_categories": ["tool"],
                    "confidence": 0.9,
                    "reason": "编排工具仓库，也是在线服务",
                }
            )
        payload = json.loads(request.content)
        jev_criteria.append(payload["questions"]["category"]["criteria"])
        return httpx.Response(
            200,
            json={
                "answers": {
                    "category": {"choice": "custom_agents", "confidence": 0.91}
                }
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        decision = classify_resource(
            METADATA,
            client=client,
            category_options=[
                CUSTOM_CATEGORY,
                ClassificationCategory(
                    code="tool", label="工具与服务", is_fallback=True,
                ),
            ],
            deepseek_api_key="deepseek-key",
            deepseek_base_url="https://deepseek.example/v1",
            deepseek_model="deepseek-test",
            jev_api_key="jev-key",
            jev_base_url="https://jev.example/v1",
            jev_model="jev-test",
        )

    assert "/v1/chat/completions" in paths
    assert any(path.endswith("/systemone") for path in paths)
    assert list(jev_criteria[0]) == ["custom_agents", "tool"]
    assert "none" not in jev_criteria[0]
    assert decision.category == "custom_agents"
    assert decision.source == "jev"
    assert decision.extra_categories == ("tool",)
    assert "agents代码工具" in decision.auto_tags
    assert "工具与服务" in decision.auto_tags
    assert decision.assessment is not None
    assert decision.assessment["status"] == "classified"
    assert [item["code"] for item in decision.assessment["proposed_categories"]] == [
        "custom_agents",
        "tool",
    ]
    assert decision.assessment["model"] == "jev-test"


def test_high_confidence_keyword_rule_does_not_preempt_custom_categories() -> None:
    """github.com 这类关键词只能兜底，不能抢在用户细类之前定案。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return completion(
            {
                "category": "custom_agents",
                "confidence": 0.83,
                "reason": "仓库就是 agent 工具",
            }
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        decision = classify_resource(
            METADATA,
            client=client,
            category_options=[
                CUSTOM_CATEGORY,
                ClassificationCategory(
                    code="tool", label="工具与服务", is_fallback=True,
                ),
            ],
            deepseek_api_key="deepseek-key",
            deepseek_model="deepseek-test",
        )

    assert decision.category == "custom_agents"


def test_llm_extra_categories_become_auto_tags() -> None:
    """模型同时命中多个细类时，附加功能类进入分类和自动标签。"""

    sibling = ClassificationCategory(
        code="custom_plans",
        label="code-plan",
        path="工具与服务 / code-plan",
        definition="卖编程 agent 套餐。",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return completion(
            {
                "category": "custom_agents",
                "extra_categories": ["custom_plans"],
                "confidence": 0.9,
                "reason": "仓库和套餐页都沾边",
            }
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        decision = classify_resource(
            METADATA,
            client=client,
            category_options=[
                CUSTOM_CATEGORY,
                sibling,
                ClassificationCategory(
                    code="tool", label="工具与服务", is_fallback=True,
                ),
            ],
            deepseek_api_key="deepseek-key",
            deepseek_model="deepseek-test",
        )

    assert decision.category == "custom_agents"
    assert decision.extra_categories == ("custom_plans",)
    assert "agents代码工具" in decision.auto_tags
    assert "code-plan" in decision.auto_tags
    assert "GitHub" in decision.auto_tags


def test_low_confidence_proposal_still_goes_to_jev() -> None:
    """对话模型不够确定时仍把候选交给 Jev，由 Jev 做最终分类。"""

    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path.endswith("/chat/completions"):
            return completion(
                {
                    "category": "custom_agents",
                    "confidence": 0.42,
                    "reason": "可能是 agent 工具",
                }
            )
        return httpx.Response(
            200,
            json={
                "answers": {
                    "category": {"choice": "custom_agents", "confidence": 0.86}
                }
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        decision = classify_resource(
            METADATA,
            client=client,
            category_options=[
                CUSTOM_CATEGORY,
                ClassificationCategory(
                    code="tool", label="工具与服务", is_fallback=True,
                ),
            ],
            deepseek_api_key="deepseek-key",
            deepseek_model="deepseek-test",
            jev_api_key="jev-key",
            jev_base_url="https://jev.example/v1",
            jev_model="jev-test",
        )

    assert "/v1/chat/completions" in paths
    assert any(path.endswith("/systemone") for path in paths)
    assert decision.category == "custom_agents"
    assert decision.source == "jev"
    assert decision.confidence == 0.86


def test_deepseek_http_error_falls_through_to_jev() -> None:
    """DeepSeek 通道故障时改走 Jev，不直接掉回关键词大类。"""

    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path.endswith("/chat/completions"):
            return httpx.Response(500, json={"error": "upstream"})
        return httpx.Response(
            200,
            json={
                "answers": {
                    "category": {"choice": "custom_agents", "confidence": 0.88}
                }
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        decision = classify_resource(
            METADATA,
            client=client,
            category_options=[
                CUSTOM_CATEGORY,
                ClassificationCategory(
                    code="tool", label="工具与服务", is_fallback=True,
                ),
            ],
            deepseek_api_key="deepseek-key",
            deepseek_base_url="https://deepseek.example/v1",
            deepseek_model="deepseek-test",
            jev_api_key="jev-key",
            jev_base_url="https://jev.example/v1",
            jev_model="jev-test",
        )

    assert "/v1/chat/completions" in paths
    assert any(path.endswith("/systemone") for path in paths)
    assert decision.category == "custom_agents"
    assert decision.source == "jev"


def test_jev_asks_custom_categories_before_system_fallback() -> None:
    """Jev 第一步只看用户细类，明确都不匹配才问系统七类。"""

    bodies: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        bodies.append(payload)
        criteria = payload["questions"]["category"]["criteria"]
        if "none" in criteria:
            return httpx.Response(
                200,
                json={"answers": {"category": {"choice": "none", "confidence": 0.9}}},
            )
        return httpx.Response(
            200,
            json={"answers": {"category": {"choice": "tool", "confidence": 0.84}}},
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        decision = classify_resource(
            METADATA,
            client=client,
            category_options=[
                CUSTOM_CATEGORY,
                ClassificationCategory(
                    code="tool", label="工具与服务", is_fallback=True,
                ),
            ],
            jev_api_key="jev-key",
            jev_base_url="https://jev.example/v1",
            jev_model="jev-test",
        )

    assert len(bodies) == 2
    first = bodies[0]["questions"]["category"]["criteria"]
    second = bodies[1]["questions"]["category"]["criteria"]
    assert "custom_agents" in first and "tool" not in first
    assert "none" in first
    assert list(second) == ["tool"]
    assert decision.category == "tool"
    assert decision.source == "jev"
    assert decision.assessment is not None
    assert decision.assessment["fallback_used"] is True


def test_confident_rule_still_short_circuits_without_custom_categories() -> None:
    """没有自定义细类时不额外花模型调用，保持原有关键词行为。"""

    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return completion({"category": "tool", "confidence": 0.9})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        decision = classify_resource(
            METADATA,
            client=client,
            deepseek_api_key="deepseek-key",
            deepseek_model="deepseek-test",
        )

    assert calls == 0
    assert decision.source == "rule"
    assert decision.category == "tool"


def test_uncertain_result_keeps_rule_decision_with_evidence() -> None:
    """模型不确定时保留关键词结果，并把证据交给确认中心。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return completion(
            {"category": "custom_agents", "confidence": 0.3, "reason": "信息不足"}
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        decision = classify_resource(
            METADATA,
            client=client,
            category_options=[
                CUSTOM_CATEGORY,
                ClassificationCategory(
                    code="tool", label="工具与服务", is_fallback=True,
                ),
            ],
            deepseek_api_key="deepseek-key",
            deepseek_model="deepseek-test",
        )

    assert decision.category == "tool"
    assert decision.assessment is not None
    assert decision.assessment["status"] == "uncertain"
    assert decision.assessment["reason_code"] == "low_confidence"


def test_service_failure_is_swallowed_for_saves_and_raised_for_jobs() -> None:
    """单条保存失败降级为规则结果，后台任务则抛出以便报错重试。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    options = {
        "category_options": [
            CUSTOM_CATEGORY,
            ClassificationCategory(code="tool", label="工具与服务", is_fallback=True),
        ],
        "deepseek_api_key": "deepseek-key",
        "deepseek_model": "deepseek-test",
    }
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        decision = classify_resource(METADATA, client=client, **options)
        assert decision.source == "rule"
        with pytest.raises(httpx.HTTPStatusError):
            classify_resource(
                METADATA,
                client=client,
                raise_service_errors=True,
                **options,
            )


def test_uncertain_without_matching_category_keeps_keyword_fallback() -> None:
    """自定义分类和系统分类都不匹配时，保留关键词结果并把依据交人工确认。"""

    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return completion({"category": "none", "confidence": 0.8, "reason": "都不匹配"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        decision = classify_resource(
            METADATA,
            client=client,
            category_options=[
                CUSTOM_CATEGORY,
                ClassificationCategory(
                    code="learning", label="学习资料", is_fallback=True,
                ),
                ClassificationCategory(
                    code="tool", label="工具与服务", is_fallback=True
                ),
            ],
            deepseek_api_key="deepseek-key",
            deepseek_model="deepseek-test",
        )

    assert calls == 1
    assert decision.category == "tool"
    assert decision.assessment is not None
    assert decision.assessment["status"] == "uncertain"
    assert decision.assessment["reason_code"] == "no_match"
