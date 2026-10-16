"""分类口径判定器测试：口径优先、系统兜底、低置信度交人工。"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from app.resource_classification_judge import (
    JudgeCategory,
    judge_resource_category,
)
from app.resource_classification_quality import UncertainClassificationError

PRIMARY = JudgeCategory(
    code="custom_plan",
    label="code-plan",
    path="code-plan",
    definition="卖订阅额度的编程 agent 套餐，例如 Claude Code、Codex。",
    include_examples="Claude Code 订阅页\nCodex 套餐对比",
    exclude_examples="模型 API 平台不算，应归大模型服务",
)
FALLBACK = JudgeCategory(
    code="tool",
    label="工具与服务",
    path="工具与服务",
    description="软件、网站、服务和开发工具",
)


def completion(content: dict[str, Any]) -> httpx.Response:
    """构造 OpenAI 兼容响应。"""

    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": json.dumps(content)}}]},
    )


def judge(**overrides: Any) -> Any:
    """用固定元数据调用判定器。"""

    arguments: dict[str, Any] = {
        "url": "https://example.com/plan",
        "page_title": "Codex 套餐价格",
        "description": "订阅额度与用量对比",
        "site_name": "Example",
        "text_excerpt": None,
        "categories": [PRIMARY],
        "fallback_categories": [FALLBACK],
        "api_key": "test-key",
        "base_url": "https://model.example/v1",
        "model": "deepseek-test",
        "min_confidence": 0.7,
    }
    arguments.update(overrides)
    return judge_resource_category(**arguments)


def test_definition_and_examples_are_sent_to_the_model() -> None:
    """用户写的口径、正反例和已确认样本都要进入提示词。"""

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return completion(
            {
                "category": "custom_plan",
                "confidence": 0.88,
                "reason": "标题是 Codex 套餐价格，命中订阅额度口径",
            }
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = judge(
            client=client,
            exemplars={
                "custom_plan": [{"title": "Claude Code 定价", "domain": "a.com"}]
            },
        )

    assert result.category == "custom_plan"
    assert result.fallback_used is False
    assert len(requests) == 1
    body = json.loads(requests[0].content)
    content = json.loads(body["messages"][1]["content"])
    assert content["categories"][0]["口径"].startswith("卖订阅额度")
    assert "Claude Code 订阅页" in content["categories"][0]["属于"]
    assert "大模型服务" in content["categories"][0]["不属于"]
    samples = content["confirmed_examples"]["custom_plan"]
    assert samples[0]["title"] == "Claude Code 定价"
    codes = [item["code"] for item in content["categories"]]
    assert "custom_plan" in codes
    assert "tool" in codes
    assert "所有成立" in content["task"]


def test_lists_every_matching_tag_in_one_pass() -> None:
    """一次列出当前网页所有成立的功能标签，细类和系统类都可出现。"""

    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        content = json.loads(request.content)["messages"][1]["content"]
        bodies.append(json.loads(content))
        return completion(
            {
                "category": "custom_plan",
                "extra_categories": ["tool"],
                "confidence": 0.9,
                "reason": "套餐页，同时也是在线服务",
            }
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = judge(client=client)

    assert len(bodies) == 1
    assert {item["code"] for item in bodies[0]["categories"]} == {
        "custom_plan",
        "tool",
    }
    assert result.category == "custom_plan"
    assert result.extra_categories == ("tool",)
    assert result.fallback_used is False
    assert [item["code"] for item in result.assessment["proposed_categories"]] == [
        "custom_plan",
        "tool",
    ]


def test_proposal_keeps_all_listed_tags_beyond_three_candidates() -> None:
    """完整标签列表不受候选截断影响，Jev 展示仍只用前三条。"""

    extras = ["tool", "learning", "article", "media"]
    fallbacks = [
        FALLBACK,
        JudgeCategory(code="learning", label="学习资料", path="学习资料"),
        JudgeCategory(code="article", label="文章阅读", path="文章阅读"),
        JudgeCategory(code="media", label="视频与音频", path="视频与音频"),
    ]

    def handler(_request: httpx.Request) -> httpx.Response:
        return completion(
            {
                "category": "custom_plan",
                "extra_categories": extras,
                "confidence": 0.9,
                "reason": "套餐页同时沾边多个功能",
            }
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = judge(client=client, fallback_categories=fallbacks)

    codes = [item["code"] for item in result.assessment["proposed_categories"]]
    assert codes == ["custom_plan", *extras]
    assert [item["code"] for item in result.assessment["candidates"]] == codes[:3]


def test_no_match_on_full_list_is_uncertain() -> None:
    """完整白名单都不匹配时交人工确认，不再另起一次系统分类。"""

    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return completion(
            {"category": "none", "confidence": 0.9, "reason": "都不匹配"}
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(UncertainClassificationError) as error:
            judge(client=client)

    assert calls == 1
    assert error.value.assessment["reason_code"] == "no_match"
    assert error.value.assessment["reason"] == "都不匹配"


def test_rejected_examples_are_sent_and_explained() -> None:
    """被用户改掉的模型判断要作为反例进入提示词。"""

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return completion(
            {
                "category": "custom_plan",
                "confidence": 0.8,
                "reason": "命中订阅套餐口径",
            }
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        judge(
            client=client,
            rejected={
                "custom_plan": [
                    {
                        "title": "火山方舟",
                        "domain": "volcengine.com",
                        "actual": "大模型服务",
                    }
                ]
            },
        )

    content = json.loads(json.loads(requests[0].content)["messages"][1]["content"])
    rejected = content["rejected_examples"]["custom_plan"]
    assert rejected[0]["title"] == "火山方舟"
    assert rejected[0]["actual_category"] == "大模型服务"
    assert "rejected_examples" in content["task"]


def test_low_confidence_is_kept_for_manual_review() -> None:
    """像但不确定时进人工确认，不偷偷降级到系统分类。"""

    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return completion(
            {
                "category": "custom_plan",
                "confidence": 0.42,
                "reason": "可能是套餐，也可能是模型平台",
            }
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(UncertainClassificationError) as error:
            judge(client=client)

    assert calls == 1
    assert error.value.assessment["reason_code"] == "low_confidence"
    assert error.value.assessment["confidence"] == 0.42
    assert error.value.assessment["candidates"][0]["code"] == "custom_plan"
    assert "fallback_used" not in error.value.assessment


def test_unknown_category_is_rejected() -> None:
    """模型自造的分类编码必须被拒绝。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return completion({"category": "custom_invented", "confidence": 0.99})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(UncertainClassificationError) as error:
            judge(client=client)

    assert error.value.assessment["reason_code"] == "unknown_category"


def test_invalid_json_is_rejected() -> None:
    """正文不是合法 JSON 时按无效响应处理。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "无法判断"}}]},
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(UncertainClassificationError) as error:
            judge(client=client)

    assert error.value.assessment["reason_code"] == "invalid_response"


def test_reason_is_sanitized_and_capped() -> None:
    """依据文本压缩为单行并限长，避免把上游文本原样存库。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return completion(
            {
                "category": "custom_plan",
                "confidence": 0.9,
                "reason": "第一行\n第二行\t带控制符\u0007 " + "长" * 400,
            }
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = judge(client=client)

    reason = result.assessment["reason"] or ""
    assert "\n" not in reason and "\u0007" not in reason
    assert reason.startswith("第一行 第二行 带控制符")
    assert len(reason) == 200


def test_system_categories_are_primary_when_no_custom_category_exists() -> None:
    """没有自定义分类时直接判定系统分类，并标记为兜底。"""

    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return completion({"category": "tool", "confidence": 0.77})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = judge(client=client, categories=[], exemplars={})

    assert result.category == "tool"
    assert result.fallback_used is True
    assert len(bodies) == 1


def test_name_is_used_as_scope_when_definition_is_missing() -> None:
    """用户只起功能名时，名称和路径仍要作为判定口径发给模型。"""

    requests: list[httpx.Request] = []
    unnamed = JudgeCategory(
        code="custom_agents",
        label="agents代码工具",
        path="工具与服务 / agents代码工具",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return completion(
            {
                "category": "custom_agents",
                "confidence": 0.86,
                "reason": "标题是编排工具仓库",
            }
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = judge(client=client, categories=[unnamed], fallback_categories=[])

    content = json.loads(json.loads(requests[0].content)["messages"][1]["content"])
    assert "agents代码工具" in content["categories"][0]["口径"]
    assert result.category == "custom_agents"


def test_extra_categories_keep_whitelist_and_drop_inventions() -> None:
    """附加功能类只保留当前列表里的编码，模型自造的丢掉。"""

    sibling = JudgeCategory(
        code="custom_agents",
        label="agents代码工具",
        path="工具与服务 / agents代码工具",
        definition="编排 coding agent 的开源工具。",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return completion(
            {
                "category": "custom_plan",
                "extra_categories": ["custom_agents", "invented", "tool"],
                "confidence": 0.9,
                "reason": "既是套餐也是 agent 工具",
            }
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = judge(
            client=client,
            categories=[PRIMARY, sibling],
            fallback_categories=[],
        )

    assert result.category == "custom_plan"
    assert result.extra_categories == ("custom_agents",)


def test_deeper_child_is_preferred_over_parent() -> None:
    """模型停在大类、但子类也成立时，把更细的功能类提成主分类。"""

    parent = JudgeCategory(
        code="custom_ai",
        label="人工智能",
        path="人工智能",
        definition="和 AI 相关的内容。",
    )
    child = JudgeCategory(
        code="custom_plan",
        label="code-plan",
        path="人工智能 / code-plan",
        definition="卖编程 agent 套餐。",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return completion(
            {
                "category": "custom_ai",
                "extra_categories": ["custom_plan"],
                "confidence": 0.84,
                "reason": "属于 AI，更具体是套餐页",
            }
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = judge(
            client=client,
            categories=[parent, child],
            fallback_categories=[],
        )

    assert result.category == "custom_plan"
    assert result.extra_categories == ("custom_ai",)


def test_no_match_without_fallback_categories_stays_uncertain() -> None:
    """没有兜底分类可用时，全不匹配就交人工确认。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return completion(
            {"category": "none", "confidence": 0.95, "reason": "都不匹配"}
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(UncertainClassificationError) as error:
            judge(client=client, fallback_categories=[])

    assert error.value.assessment["reason_code"] == "no_match"
    assert error.value.assessment["reason"] == "都不匹配"
