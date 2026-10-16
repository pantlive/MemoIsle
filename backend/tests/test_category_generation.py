"""DeepSeek 分类模板生成与 Jev 归类的回归测试。"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
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
    ResourceCategoryGenerateMode,
    ResourceCategoryGenerateResponse,
    ResourceCategoryRead,
)
from fastapi.testclient import TestClient


def category(
    code: str = "tool",
    name: str = "工具与服务",
    parent_code: str | None = None,
    depth: int = 1,
    is_active: bool = True,
) -> ResourceCategoryRead:
    """构造包含层级信息的模板样本。"""

    return ResourceCategoryRead(
        id=None,
        code=code,
        name=name,
        description="分类范围",
        is_system=True,
        is_active=is_active,
        version=1,
        parent_code=parent_code,
        depth=depth,
    )


def settings(tmp_path: Path) -> Settings:
    """构造只连接模拟模型的隔离配置。"""

    return Settings(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'test.db'}",
        cors_origins=(),
        local_user_id="test-user",
        audio_directory=tmp_path / "audio",
        deepseek_api_key="test-deepseek-key",
    )


def completion(categories: object) -> httpx.Response:
    """按真实 chat/completions 格式封装模型建议。"""

    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "categories": categories,
                            },
                            ensure_ascii=False,
                        )
                    }
                }
            ],
        },
    )


def test_generation_uses_deepseek_and_filters_duplicates(
    tmp_path: Path,
) -> None:
    """使用独立 DeepSeek 凭证，并保留合法层级与数量限制。"""

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return completion(
            [
                {"name": "工具与服务"},
                {"name": "AI 工具", "description": "代理工具", "parent_code": "tool"},
                {"name": "AI 工具", "parent_code": "tool"},
                {"name": "数据处理", "parent_code": "tool"},
            ]
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as model_client:
        result = generate_category_suggestions(
            "细化 AI 与开发工具",
            [category()],
            settings(tmp_path),
            max_categories=1,
            client=model_client,
        )
    assert [item.name for item in result.categories] == ["AI 工具"]
    assert result.categories[0].parent_code == "tool"
    assert result.categories[0].existing_code is None
    assert str(requests[0].url) == ("https://api.deepseek.com/v1/chat/completions")
    assert requests[0].headers["authorization"] == "Bearer test-deepseek-key"
    payload = json.loads(requests[0].content)
    assert payload["model"] == "deepseek-flash"
    assert payload["thinking"] == {"type": "enabled"}
    assert payload["reasoning_effort"] == "max"
    assert payload["response_format"] == {"type": "json_object"}
    assert "temperature" not in payload
    state = json.loads(payload["messages"][1]["content"])
    assert set(state) == {
        "task",
        "mode",
        "instructions",
        "max_categories",
        "existing_categories",
        "valid_parent_codes",
        "library_pages",
    }
    assert state["mode"] == "subcategories"
    assert state["library_pages"] == []
    assert state["valid_parent_codes"] == [
        {
            "code": "tool",
            "name": "工具与服务",
            "parent_code": None,
            "depth": 1,
        }
    ]


def test_generation_clusters_library_pages_without_instructions(
    tmp_path: Path,
) -> None:
    """没有整理要求时，仍把网页样本交给模型做聚类。"""

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return completion(
            [
                {
                    "name": "编程代理",
                    "description": "编码助手与代理工具",
                    "parent_code": "tool",
                },
            ]
        )

    pages = [
        {
            "title": "Codex 定价",
            "site": "OpenAI",
            "domain": "openai.com",
            "summary": "套餐对比",
        }
    ]
    with httpx.Client(transport=httpx.MockTransport(handler)) as model_client:
        result = generate_category_suggestions(
            "",
            [category()],
            settings(tmp_path),
            client=model_client,
            library_pages=pages,
        )
    assert [item.name for item in result.categories] == ["编程代理"]
    state = json.loads(json.loads(requests[0].content)["messages"][1]["content"])
    assert state["instructions"] == ""
    assert state["library_pages"] == pages
    assert "细类" in state["task"]


def test_generation_keeps_existing_clusters_and_examples(
    tmp_path: Path,
) -> None:
    """已有模板也作为聚类标签返回，并带上网页例子。"""

    def handler(_request: httpx.Request) -> httpx.Response:
        return completion(
            [
                {
                    "name": "工具与服务",
                    "examples": ["Codex 定价", "  ", 12, "Usage - Command Code"],
                },
                {
                    "name": "编程代理",
                    "description": "编码助手",
                    "parent_code": "tool",
                    "examples": ["Claude Code 指南"],
                },
            ]
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as model_client:
        result = generate_category_suggestions(
            "",
            [category()],
            settings(tmp_path),
            max_categories=6,
            client=model_client,
        )
    assert [item.name for item in result.categories] == ["编程代理"]
    assert result.categories[0].existing_code is None
    assert result.categories[0].examples == ["Claude Code 指南"]
    assert result.categories[0].parent_code == "tool"


def test_subcategory_mode_keeps_only_fine_classes(tmp_path: Path) -> None:
    """确认顶级够用后，结果里只保留细类。"""

    def handler(_request: httpx.Request) -> httpx.Response:
        return completion(
            [
                {"name": "新领域甲"},
                {"name": "编程代理", "parent_code": "tool"},
                {"name": "评测站点", "parent_code": "tool"},
                {"name": "工具与服务"},
            ]
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as model_client:
        result = generate_category_suggestions(
            "",
            [category()],
            settings(tmp_path),
            max_categories=4,
            client=model_client,
            mode=ResourceCategoryGenerateMode.SUBCATEGORIES,
        )
    assert [item.name for item in result.categories] == ["编程代理", "评测站点"]
    assert all(item.parent_code == "tool" for item in result.categories)


def test_top_level_mode_keeps_only_root_classes(tmp_path: Path) -> None:
    """确认顶级不够时，结果里只保留新的顶级类。"""

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return completion(
            [
                {"name": "新领域甲"},
                {"name": "新领域乙"},
                {"name": "编程代理", "parent_code": "tool"},
                {"name": "工具与服务"},
            ]
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as model_client:
        result = generate_category_suggestions(
            "",
            [category()],
            settings(tmp_path),
            max_categories=4,
            client=model_client,
            mode=ResourceCategoryGenerateMode.TOP_LEVEL,
        )
    assert [item.name for item in result.categories] == [
        "新领域甲",
        "新领域乙",
        "工具与服务",
    ]
    assert result.categories[0].parent_code is None
    assert result.categories[2].existing_code == "tool"
    state = json.loads(json.loads(requests[0].content)["messages"][1]["content"])
    assert state["mode"] == "top_level"
    assert "顶级" in state["task"]


@pytest.mark.parametrize(
    "suggestions",
    [
        [{"name": "   "}],
        [None],
    ],
)
def test_invalid_generated_items_are_skipped(
    tmp_path: Path,
    suggestions: object,
) -> None:
    """空名称和非法条目跳过，不把整次聚类打成失败。"""

    def handler(_request: httpx.Request) -> httpx.Response:
        return completion(suggestions)

    with httpx.Client(transport=httpx.MockTransport(handler)) as model_client:
        result = generate_category_suggestions(
            "生成类别",
            [category()],
            settings(tmp_path),
            client=model_client,
        )
    assert result.categories == []


def test_unusable_parents_are_dropped_in_subcategory_mode(
    tmp_path: Path,
) -> None:
    """细分时编造的父类不会挤占细类名额。"""

    def handler(_request: httpx.Request) -> httpx.Response:
        return completion(
            [
                {"name": "未知父类", "parent_code": "missing"},
                {"name": "四级分类", "parent_code": "deep"},
                {"name": "停用父类", "parent_code": "disabled"},
                {
                    "name": "AI 工具",
                    "parent_code": "tool",
                    "description": "字" * 301,
                },
                {"name": "工具与服务", "parent_code": "工具与服务"},
            ]
        )

    existing = [
        category(),
        category("deep", "深层", depth=3),
        category("disabled", "停用", is_active=False),
    ]
    with httpx.Client(transport=httpx.MockTransport(handler)) as model_client:
        result = generate_category_suggestions(
            "生成类别",
            existing,
            settings(tmp_path),
            max_categories=6,
            client=model_client,
        )
    assert [item.name for item in result.categories] == ["AI 工具"]
    assert result.categories[0].parent_code == "tool"
    assert result.categories[0].description == "字" * 300


@pytest.mark.parametrize("status", [401, 429, 500])
def test_upstream_errors_have_safe_public_message(
    tmp_path: Path,
    status: int,
) -> None:
    """上游错误不会把凭证或响应原文传回客户端。"""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status,
            json={"error": "private upstream details"},
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as model_client:
        with pytest.raises(CategoryGenerationUnavailableError) as caught:
            generate_category_suggestions(
                "生成类别",
                [],
                settings(tmp_path),
                client=model_client,
            )
    assert "private upstream" not in str(caught.value)
    assert "test-deepseek-key" not in str(caught.value)
    if status == 401:
        assert "认证失败" in str(caught.value)
    elif status == 429:
        assert "额度不足" in str(caught.value)


def test_generation_requires_its_own_key(tmp_path: Path) -> None:
    """其他模型的配置不能意外成为 DeepSeek 的凭证。"""

    config = replace(
        settings(tmp_path),
        deepseek_api_key=None,
        llm_api_key="another-provider-key",
        jev_api_key="jev-provider-key",
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


def test_empty_completion_is_rejected(tmp_path: Path) -> None:
    """空输出仍视为生成失败，避免把空白当成没有细类。"""

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": ""}}],
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as model_client:
        with pytest.raises(CategoryGenerationUnavailableError):
            generate_category_suggestions(
                "生成类别",
                [],
                settings(tmp_path),
                client=model_client,
            )
    assert len(requests) == 1


@pytest.mark.parametrize("content", ["not JSON", '{"categories":{}}'])
def test_unusable_completion_returns_empty_after_retry(
    tmp_path: Path,
    content: str,
) -> None:
    """无法解析的正文重试一次后返回空列表，不再 502。"""

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": content}}],
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as model_client:
        result = generate_category_suggestions(
            "生成类别",
            [category()],
            settings(tmp_path),
            client=model_client,
        )
    assert result.categories == []
    assert len(requests) == 2
    retry = json.loads(requests[1].content)
    assert "不要分析过程" in retry["messages"][0]["content"]


def test_generation_reads_fenced_and_truncated_json(tmp_path: Path) -> None:
    """markdown 围栏和截断的类别数组仍能收回已经写完的标签。"""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": (
                                "```json\n"
                                '{"categories":[{"name":"编程代理","parent_code":"tool"},'
                                '{"name":"未写完"'
                                "\n```"
                            )
                        }
                    }
                ],
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as model_client:
        result = generate_category_suggestions(
            "",
            [category()],
            settings(tmp_path),
            client=model_client,
        )
    assert [item.name for item in result.categories] == ["编程代理"]
    assert result.categories[0].parent_code == "tool"


def test_generation_reads_grouped_and_wrapped_json(tmp_path: Path) -> None:
    """细类按父类分组、夹在说明文字里，或写成单条对象时仍能解析。"""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": (
                                "按大类细分如下：\n"
                                '{"工具与服务":[{"name":"编程代理"},{"name":"评测站点"}]}'
                            )
                        }
                    }
                ],
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as model_client:
        result = generate_category_suggestions(
            "",
            [category()],
            settings(tmp_path),
            client=model_client,
        )
    assert [item.name for item in result.categories] == ["编程代理", "评测站点"]
    assert all(item.parent_code == "tool" for item in result.categories)

    def single_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {"name": "编程代理", "parent_code": "tool"},
                                ensure_ascii=False,
                            )
                        }
                    }
                ],
            },
        )

    with httpx.Client(transport=httpx.MockTransport(single_handler)) as model_client:
        result = generate_category_suggestions(
            "",
            [category()],
            settings(tmp_path),
            client=model_client,
        )
    assert [item.name for item in result.categories] == ["编程代理"]


def test_generation_reads_nested_and_dict_content(tmp_path: Path) -> None:
    """嵌套 data.categories、已解析对象、title/parentCode 都能解析。"""

    def nested_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "data": {
                                        "categories": [
                                            {
                                                "name": "编程代理",
                                                "parent_code": "tool",
                                            }
                                        ]
                                    }
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ],
            },
        )

    with httpx.Client(transport=httpx.MockTransport(nested_handler)) as model:
        result = generate_category_suggestions(
            "",
            [category()],
            settings(tmp_path),
            client=model,
        )
    assert [item.name for item in result.categories] == ["编程代理"]

    def dict_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": {
                                "categories": [
                                    {
                                        "title": "评测站点",
                                        "parentCode": "tool",
                                    }
                                ]
                            }
                        }
                    }
                ],
            },
        )

    with httpx.Client(transport=httpx.MockTransport(dict_handler)) as model:
        result = generate_category_suggestions(
            "",
            [category()],
            settings(tmp_path),
            client=model,
        )
    assert [item.name for item in result.categories] == ["评测站点"]
    assert result.categories[0].parent_code == "tool"


def test_generation_recovers_name_fields_from_prose(tmp_path: Path) -> None:
    """不是完整 JSON 时，仍能从 name 字段收回新细类。"""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": (
                                '建议如下 "name": "编程代理",'
                                ' "parent_code": "tool" 即可'
                            )
                        }
                    }
                ],
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as model_client:
        result = generate_category_suggestions(
            "",
            [category()],
            settings(tmp_path),
            client=model_client,
        )
    assert [item.name for item in result.categories] == ["编程代理"]
    assert result.categories[0].parent_code == "tool"


def test_generation_retries_compact_json_after_analysis(
    tmp_path: Path,
) -> None:
    """分析-only JSON 再请求一次紧凑格式后仍能得到细类。"""

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {"analysis": "先看网页用途"},
                                    ensure_ascii=False,
                                )
                            }
                        }
                    ],
                },
            )
        return completion(
            [{"name": "编程代理", "parent_code": "tool"}],
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as model_client:
        result = generate_category_suggestions(
            "",
            [category()],
            settings(tmp_path),
            client=model_client,
        )
    assert [item.name for item in result.categories] == ["编程代理"]
    assert len(requests) == 2
    retry = json.loads(requests[1].content)
    assert "不要分析过程" in retry["messages"][0]["content"]
    assert "existing_categories" not in json.loads(
        retry["messages"][1]["content"],
    )


def test_subcategory_infers_parent_from_name_and_examples(
    tmp_path: Path,
) -> None:
    """细分漏了 parent_code 时，用大类名或网页已有分类补上。"""

    def named_handler(_request: httpx.Request) -> httpx.Response:
        return completion(
            [{"name": "编程代理", "description": "挂在工具与服务下面"}],
        )

    with httpx.Client(transport=httpx.MockTransport(named_handler)) as model:
        result = generate_category_suggestions(
            "",
            [category()],
            settings(tmp_path),
            client=model,
        )
    assert [item.name for item in result.categories] == ["编程代理"]
    assert result.categories[0].parent_code == "tool"

    def example_handler(_request: httpx.Request) -> httpx.Response:
        return completion(
            [{"name": "评测站点", "examples": ["Codex 定价"]}],
        )

    pages = [
        {
            "title": "Codex 定价",
            "site": "OpenAI",
            "domain": "openai.com",
            "category": "tool",
        }
    ]
    with httpx.Client(transport=httpx.MockTransport(example_handler)) as model:
        result = generate_category_suggestions(
            "",
            [category()],
            settings(tmp_path),
            client=model,
            library_pages=pages,
        )
    assert [item.name for item in result.categories] == ["评测站点"]
    assert result.categories[0].parent_code == "tool"


def test_generation_falls_back_to_function_clusters(
    tmp_path: Path,
) -> None:
    """模型空输出或超时后，按用途给出细类，不用网站名。"""

    pages = [
        {
            "title": "Codex 定价",
            "site": "OpenAI",
            "domain": "openai.com",
            "category": "tool",
        },
        {
            "title": "Claude Code 指南",
            "site": "OpenAI",
            "domain": "openai.com",
            "category": "tool",
        },
    ]

    def empty_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": ""}}]},
        )

    with httpx.Client(transport=httpx.MockTransport(empty_handler)) as model:
        result = generate_category_suggestions(
            "",
            [category()],
            settings(tmp_path),
            client=model,
            library_pages=pages,
        )
    assert [item.name for item in result.categories] == ["编程代理"]
    assert result.categories[0].parent_code == "tool"
    assert all(item.name != "OpenAI" for item in result.categories)

    def timeout_handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timeout")

    with httpx.Client(transport=httpx.MockTransport(timeout_handler)) as model:
        result = generate_category_suggestions(
            "",
            [category()],
            settings(tmp_path),
            client=model,
            library_pages=pages,
        )
    assert [item.name for item in result.categories] == ["编程代理"]


def test_generation_skips_site_names_and_reads_function_lists(
    tmp_path: Path,
) -> None:
    """网站名细类丢弃；中文列表里的用途标签仍能收回。"""

    pages = [
        {
            "title": "Codex 定价",
            "site": "OpenAI",
            "domain": "openai.com",
            "category": "tool",
        }
    ]

    def site_handler(_request: httpx.Request) -> httpx.Response:
        return completion(
            [{"name": "OpenAI", "parent_code": "tool"}],
        )

    with httpx.Client(transport=httpx.MockTransport(site_handler)) as model:
        result = generate_category_suggestions(
            "",
            [category()],
            settings(tmp_path),
            client=model,
            library_pages=pages,
        )
    assert result.categories == []

    def list_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": (
                                "细类如下：\n"
                                "1. 编程代理（工具与服务）\n"
                                "2. 评测站点（工具与服务）\n"
                            )
                        }
                    }
                ],
            },
        )

    with httpx.Client(transport=httpx.MockTransport(list_handler)) as model:
        result = generate_category_suggestions(
            "",
            [category()],
            settings(tmp_path),
            client=model,
        )
    assert [item.name for item in result.categories] == [
        "编程代理",
        "评测站点",
    ]
    assert all(item.parent_code == "tool" for item in result.categories)


def test_generation_reads_segmented_message_content(tmp_path: Path) -> None:
    """分段正文和 reasoning_content 也能抽出 JSON。"""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": [
                                {
                                    "type": "text",
                                    "text": (
                                        '{"categories":[{"name":"编程代理",'
                                        '"parent_code":"tool"}]}'
                                    ),
                                },
                            ]
                        }
                    }
                ],
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as model_client:
        result = generate_category_suggestions(
            "",
            [category()],
            settings(tmp_path),
            client=model_client,
        )
    assert [item.name for item in result.categories] == ["编程代理"]


def test_generation_retries_without_thinking_on_400(tmp_path: Path) -> None:
    """中转拒绝思考参数时先丢掉 JSON 约束，最后才关掉思考。"""

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        payload = json.loads(request.content)
        if "thinking" in payload:
            return httpx.Response(400, json={"error": {"code": "bad_request"}})
        return completion([{"name": "编程代理", "parent_code": "tool"}])

    with httpx.Client(transport=httpx.MockTransport(handler)) as model_client:
        result = generate_category_suggestions(
            "",
            [category()],
            settings(tmp_path),
            client=model_client,
        )
    assert [item.name for item in result.categories] == ["编程代理"]
    first = json.loads(requests[0].content)
    assert first["thinking"] == {"type": "enabled"}
    assert first["reasoning_effort"] == "max"
    assert "thinking" not in json.loads(requests[-1].content)
    assert len(requests) >= 2


def test_generation_route_validates_input_and_configuration(
    client: TestClient,
) -> None:
    """没有整理要求且没有网页时拒绝；有网页时可按聚类生成。"""

    assert (
        client.post(
            "/api/v1/resource-categories/generate",
            json={"instructions": "   "},
        ).status_code
        == 422
    )
    created = client.post(
        "/api/v1/memos",
        json={
            "client_id": str(uuid4()),
            "type": "resource",
            "title": "Codex 定价",
            "body": "套餐页",
            "source_url": "https://openai.com/codex",
        },
    )
    assert created.status_code == 201
    assert (
        client.post(
            "/api/v1/resource-categories/generate",
            json={},
        ).status_code
        == 503
    )
    response = client.post(
        "/api/v1/resource-categories/generate",
        json={"instructions": "细化工具"},
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
        return completion(
            [
                {
                    "name": "AI 工具",
                    "description": "AI 应用和编程代理",
                    "parent_code": "tool",
                },
            ]
        )

    def generate(
        instructions: str,
        existing: Sequence[ResourceCategoryRead],
        _settings: Settings,
        max_categories: int,
        **_kwargs: object,
    ) -> ResourceCategoryGenerateResponse:
        with httpx.Client(
            transport=httpx.MockTransport(deepseek_handler),
        ) as model_client:
            return generate_category_suggestions(
                instructions,
                existing,
                settings(tmp_path),
                max_categories,
                model_client,
            )

    monkeypatch.setattr("app.api.generate_category_suggestions", generate)
    preview = client.post(
        "/api/v1/resource-categories/generate",
        json={"instructions": "按 AI 领域细分工具"},
    )
    assert preview.status_code == 200
    assert client.get("/api/v1/resource-categories").json() == before
    added = client.post(
        "/api/v1/resource-categories",
        json=preview.json()["categories"][0],
    )
    assert added.status_code == 201
    selected = added.json()["code"]

    def jev_handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert request.url.path == "/v1/systemone"
        assert request.headers["authorization"] == "Bearer test-jev-key"
        assert selected in payload["questions"]["category"]["criteria"]
        return httpx.Response(
            200,
            json={
                "answers": {
                    "category": {
                        "choice": selected,
                        "confidence": 0.95,
                    }
                }
            },
        )

    with httpx.Client(
        transport=httpx.MockTransport(jev_handler),
    ) as model_client:
        decision = classify_resource(
            ResourceMetadata(
                final_url="https://github.com/getpaseo/paseo",
                page_title="Paseo",
                description="AI coding agent tool",
                site_name="GitHub",
                favicon_url=None,
                http_status=200,
            ),
            category_options=[
                ClassificationCategory(
                    item["code"],
                    item["name"],
                    item["description"],
                )
                for item in client.get("/api/v1/resource-categories").json()
            ],
            jev_api_key="test-jev-key",
            client=model_client,
        )
    assert decision.category == selected
    assert decision.source == "jev"
    assert decision.confidence == 0.95


@pytest.mark.parametrize(
    "choice,confidence",
    [
        ("tool", 0.1),
        ("unknown", 0.99),
        ("tool", float("nan")),
        ("tool", True),
        ("tool", 2.0),
    ],
)
def test_jev_uncertain_or_invalid_results_fall_back(
    choice: str,
    confidence: object,
) -> None:
    """不确定或非法模型输出回退规则，不阻断收藏。"""

    def handler(_request: httpx.Request) -> httpx.Response:
        # JSON 不支持 NaN，使用无效内容来覆盖错误响应的降级路径。
        content = json.dumps(
            {
                "answers": {
                    "category": {
                        "choice": choice,
                        "confidence": confidence,
                    }
                }
            }
        )
        return httpx.Response(200, text=content)

    with httpx.Client(transport=httpx.MockTransport(handler)) as model_client:
        decision = classify_resource(
            ResourceMetadata(
                final_url="https://github.com/getpaseo/paseo",
                page_title="Paseo",
                description=None,
                site_name="GitHub",
                favicon_url=None,
                http_status=200,
            ),
            jev_api_key="test-jev-key",
            client=model_client,
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
                page_title="Paseo",
                description=None,
                site_name="GitHub",
                favicon_url=None,
                http_status=200,
            ),
            user_rules=[
                ClassificationRule(
                    "custom_ai",
                    "AI 工具",
                    "domain",
                    "github.com",
                )
            ],
            jev_api_key="test-jev-key",
            client=model_client,
        )
    assert decision.category == "custom_ai"
    assert decision.source == "user_rule"
