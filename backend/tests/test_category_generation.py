"""DeepSeek 分类模板生成与 Jev 归类的回归测试。"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.category_generation_service import (
    CategoryGenerationNotConfiguredError,
    CategoryGenerationUnavailableError,
    generate_category_suggestions,
)
from app.config import Settings
from app.resource_processing import (
    ClassificationCategory,
    ClassificationRule,
    ResourceMetadata,
    classify_resource,
)
from app.schemas import (
    ResourceCategoryGenerateResponse,
    ResourceCategoryRead,
)


def category(
    code: str = "tool",
    name: str = "工具与服务",
    parent_code: str | None = None,
    depth: int = 1,
    is_active: bool = True,
) -> ResourceCategoryRead:
    """构造包含层级信息的模板样本。"""

    return ResourceCategoryRead(
        id=None, code=code, name=name, description="分类范围",
        is_system=True, is_active=is_active, version=1,
        parent_code=parent_code, depth=depth,
    )


def settings(tmp_path: Path) -> Settings:
    """构造只连接模拟模型的隔离配置。"""

    return Settings(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'test.db'}",
        cors_origins=(), local_user_id="test-user",
        audio_directory=tmp_path / "audio",
        deepseek_api_key="test-deepseek-key",
    )


def completion(categories: object) -> httpx.Response:
    """按真实 chat/completions 格式封装模型建议。"""

    return httpx.Response(200, json={
        "choices": [{"message": {"content": json.dumps({
            "categories": categories,
        }, ensure_ascii=False)}}],
    })


def test_generation_uses_deepseek_and_filters_duplicates(
    tmp_path: Path,
) -> None:
    """使用独立 DeepSeek 凭证，并保留合法层级与数量限制。"""

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return completion([
            {"name": "工具与服务"},
            {"name": "AI 工具", "description": "代理工具", "parent_code": "tool"},
            {"name": "AI 工具", "parent_code": "tool"},
            {"name": "数据处理", "parent_code": "tool"},
        ])

    with httpx.Client(transport=httpx.MockTransport(handler)) as model_client:
        result = generate_category_suggestions(
            "细化 AI 与开发工具", [category()], settings(tmp_path),
            max_categories=1, client=model_client,
        )
    assert [item.name for item in result.categories] == ["AI 工具"]
    assert result.categories[0].parent_code == "tool"
    assert str(requests[0].url) == (
        "https://api.deepseek.com/v1/chat/completions"
    )
    assert requests[0].headers["authorization"] == "Bearer test-deepseek-key"
    payload = json.loads(requests[0].content)
    assert payload["model"] == "deepseek-flash"
    assert payload["thinking"] == {"type": "disabled"}
    assert payload["response_format"] == {"type": "json_object"}
    state = json.loads(payload["messages"][1]["content"])
    assert set(state) == {
        "instructions", "max_categories", "existing_categories",
    }


@pytest.mark.parametrize("suggestions", [
    [{"name": "   "}],
    [{"name": "过长说明", "description": "字" * 301}],
    [{"name": "未知父类", "parent_code": "missing"}],
    [{"name": "四级分类", "parent_code": "deep"}],
    [{"name": "停用父类", "parent_code": "disabled"}],
    [None],
    None,
])
def test_invalid_generated_templates_are_rejected(
    tmp_path: Path,
    suggestions: object,
) -> None:
    """无效模板不能进入预览或被自动写入目录。"""

    def handler(_request: httpx.Request) -> httpx.Response:
        return completion(suggestions)

    existing = [
        category(), category("deep", depth=3),
        category("disabled", is_active=False),
    ]
    with httpx.Client(transport=httpx.MockTransport(handler)) as model_client:
        with pytest.raises(CategoryGenerationUnavailableError):
            generate_category_suggestions(
                "生成类别", existing, settings(tmp_path), client=model_client,
            )


@pytest.mark.parametrize("status", [401, 429, 500])
def test_upstream_errors_have_safe_public_message(
    tmp_path: Path,
    status: int,
) -> None:
    """上游错误不会把凭证或响应原文传回客户端。"""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status, json={"error": "private upstream details"},
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as model_client:
        with pytest.raises(CategoryGenerationUnavailableError) as caught:
            generate_category_suggestions(
                "生成类别", [], settings(tmp_path), client=model_client,
            )
    assert "private upstream" not in str(caught.value)
    assert "test-deepseek-key" not in str(caught.value)


def test_generation_requires_its_own_key(tmp_path: Path) -> None:
    """其他模型的配置不能意外成为 DeepSeek 的凭证。"""

    config = replace(
        settings(tmp_path), deepseek_api_key=None,
        llm_api_key="another-provider-key", jev_api_key="jev-provider-key",
    )
    with pytest.raises(CategoryGenerationNotConfiguredError):
        generate_category_suggestions("生成类别", [], config)


def test_environment_loads_separate_provider_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """两个供应商的地址、模型和凭证分别从后端环境读取。"""

    monkeypatch.setenv("MEMOISLE_DEEPSEEK_API_KEY", "deepseek-test-key")
    monkeypatch.setenv("MEMOISLE_DEEPSEEK_MODEL", "custom-deepseek-model")
    monkeypatch.setenv("MEMOISLE_JEV_API_KEY", "jev-test-key")
    monkeypatch.setenv("MEMOISLE_JEV_MODEL", "custom-jev-model")
    monkeypatch.setenv("MEMOISLE_JEV_MIN_CONFIDENCE", "0.85")
    config = Settings.from_environment()
    assert config.deepseek_api_key == "deepseek-test-key"
    assert config.deepseek_model == "custom-deepseek-model"
    assert config.jev_api_key == "jev-test-key"
    assert config.jev_model == "custom-jev-model"
    assert config.jev_min_confidence == 0.85


@pytest.mark.parametrize("content", ["", "not JSON", '{"categories":{}}'])
def test_malformed_completions_are_rejected(
    tmp_path: Path,
    content: str,
) -> None:
    """空输出和无效 JSON 不会被误当成可用模板。"""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "choices": [{"message": {"content": content}}],
        })

    with httpx.Client(transport=httpx.MockTransport(handler)) as model_client:
        with pytest.raises(CategoryGenerationUnavailableError):
            generate_category_suggestions(
                "生成类别", [], settings(tmp_path), client=model_client,
            )


def test_generation_route_validates_input_and_configuration(
    client: TestClient,
) -> None:
    """接口拒绝空白要求，并在未配置时明确返回不可用。"""

    assert client.post(
        "/api/v1/resource-categories/generate", json={"instructions": "   "},
    ).status_code == 422
    response = client.post(
        "/api/v1/resource-categories/generate", json={"instructions": "细化工具"},
    )
    assert response.status_code == 503


def test_generate_add_and_classify_with_jev(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """生成预览不写库，加入模板后 Jev 能把 GitHub 网页归入新类别。"""

    before = client.get("/api/v1/resource-categories").json()

    def deepseek_handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        state = json.loads(payload["messages"][1]["content"])
        assert len(state["existing_categories"]) == len(before)
        return completion([
            {
                "name": "AI 工具", "description": "AI 应用和编程代理",
                "parent_code": "tool",
            },
        ])

    def generate(
        instructions: str,
        existing: Sequence[ResourceCategoryRead],
        _settings: Settings,
        max_categories: int,
    ) -> ResourceCategoryGenerateResponse:
        with httpx.Client(
            transport=httpx.MockTransport(deepseek_handler),
        ) as model_client:
            return generate_category_suggestions(
                instructions, existing, settings(tmp_path),
                max_categories, model_client,
            )

    monkeypatch.setattr("app.api.generate_category_suggestions", generate)
    preview = client.post(
        "/api/v1/resource-categories/generate",
        json={"instructions": "按 AI 领域细分工具"},
    )
    assert preview.status_code == 200
    assert client.get("/api/v1/resource-categories").json() == before
    added = client.post(
        "/api/v1/resource-categories", json=preview.json()["categories"][0],
    )
    assert added.status_code == 201
    selected = added.json()["code"]

    def jev_handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert request.url.path == "/v1/systemone"
        assert request.headers["authorization"] == "Bearer test-jev-key"
        assert selected in payload["questions"]["category"]["criteria"]
        return httpx.Response(200, json={"answers": {"category": {
            "choice": selected, "confidence": 0.95,
        }}})

    with httpx.Client(
        transport=httpx.MockTransport(jev_handler),
    ) as model_client:
        decision = classify_resource(
            ResourceMetadata(
                final_url="https://github.com/getpaseo/paseo",
                page_title="Paseo", description="AI coding agent tool",
                site_name="GitHub", favicon_url=None, http_status=200,
            ),
            category_options=[
                ClassificationCategory(
                    item["code"], item["name"], item["description"],
                )
                for item in client.get("/api/v1/resource-categories").json()
            ],
            jev_api_key="test-jev-key", client=model_client,
        )
    assert decision.category == selected
    assert decision.source == "jev"
    assert decision.confidence == 0.95


@pytest.mark.parametrize("choice,confidence", [
    ("tool", 0.1), ("unknown", 0.99), ("tool", float("nan")),
    ("tool", True), ("tool", 2.0),
])
def test_jev_uncertain_or_invalid_results_fall_back(
    choice: str,
    confidence: object,
) -> None:
    """不确定或非法模型输出回退规则，不阻断收藏。"""

    def handler(_request: httpx.Request) -> httpx.Response:
        # JSON 不支持 NaN，使用无效内容来覆盖错误响应的降级路径。
        content = json.dumps({"answers": {"category": {
            "choice": choice, "confidence": confidence,
        }}})
        return httpx.Response(200, text=content)

    with httpx.Client(transport=httpx.MockTransport(handler)) as model_client:
        decision = classify_resource(
            ResourceMetadata(
                final_url="https://github.com/getpaseo/paseo",
                page_title="Paseo", description=None, site_name="GitHub",
                favicon_url=None, http_status=200,
            ),
            jev_api_key="test-jev-key", client=model_client,
        )
    assert decision.source == "rule"
    assert decision.category == "tool"


def test_user_rule_precedes_jev() -> None:
    """明确的用户规则优先于模型判断。"""

    def handler(_request: httpx.Request) -> httpx.Response:
        pytest.fail("用户规则已匹配时不应请求模型")

    with httpx.Client(transport=httpx.MockTransport(handler)) as model_client:
        decision = classify_resource(
            ResourceMetadata(
                final_url="https://github.com/getpaseo/paseo",
                page_title="Paseo", description=None, site_name="GitHub",
                favicon_url=None, http_status=200,
            ),
            user_rules=[ClassificationRule(
                "custom_ai", "AI 工具", "domain", "github.com",
            )],
            jev_api_key="test-jev-key", client=model_client,
        )
    assert decision.category == "custom_ai"
    assert decision.source == "user_rule"
