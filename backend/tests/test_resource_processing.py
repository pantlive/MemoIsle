"""网页元数据与自动分类测试。"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from app.config import Settings
from app.database import Database
from app.resource_processing import (
    ClassificationCategory,
    ClassificationRule,
    ResourceMetadata,
    UnsafeResourceUrlError,
    classify_resource,
    classify_resource_by_rules,
    fetch_resource_metadata,
    validate_public_resource_url,
)
from app.resource_service import enrich_resource
from app.schemas import MemoCreate, MemoType, ResourceCategory
from app.service import create_memo, list_memos
from fastapi.testclient import TestClient


def test_private_resource_url_is_rejected() -> None:
    """元数据任务不能访问本机或内网地址。"""

    with pytest.raises(UnsafeResourceUrlError, match="non_public_ip"):
        validate_public_resource_url(
            "http://internal.example/secret",
            resolver=lambda _host, _port: ["127.0.0.1"],
        )


def test_fetch_metadata_validates_redirect_and_extracts_html() -> None:
    """抓取器会校验重定向并只提取允许保存的元数据。"""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start":
            return httpx.Response(302, headers={"Location": "/guide"})
        return httpx.Response(
            200,
            headers={"Content-Type": "text/html; charset=utf-8"},
            text=(
                "<html><head><title>普通标题</title>"
                '<meta property="og:title" content="PyTorch 入门课程">'
                '<meta name="description" content=" 从张量开始学习。 ">'
                '<meta property="og:site_name" content="学习站">'
                '<link rel="icon" href="/favicon.png">'
                '<meta property="og:image" content="/cover.png">'
                "</head><body>正文不会保存</body></html>"
            ),
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        metadata = fetch_resource_metadata(
            "https://public.example/start",
            client=client,
            resolver=lambda _host, _port: ["93.184.216.34"],
        )

    assert metadata.final_url == "https://public.example/guide"
    assert metadata.page_title == "PyTorch 入门课程"
    assert metadata.description == "从张量开始学习。"
    assert metadata.site_name == "学习站"
    assert metadata.favicon_url == "https://public.example/favicon.png"
    assert metadata.image_url == "https://public.example/cover.png"


def test_rules_and_optional_llm_use_fixed_categories() -> None:
    """明确资料使用规则，模糊资料可由大模型返回白名单分类。"""

    rule_decision = classify_resource_by_rules(
        "https://docs.pytorch.org/tutorials/",
        "PyTorch Tutorials",
        "Learn tensor basics",
        "PyTorch",
    )
    assert rule_decision.category == ResourceCategory.LEARNING
    assert rule_decision.source == "rule"

    def llm_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": '{"category":"product"}'}}
                ]
            },
        )

    metadata = ResourceMetadata(
        final_url="https://example.com/item/42",
        page_title="值得保存的东西",
        description="以后可能会需要",
        site_name="Example",
        favicon_url=None,
        http_status=200,
    )
    with httpx.Client(transport=httpx.MockTransport(llm_handler)) as client:
        llm_decision = classify_resource(
            metadata,
            llm_base_url="https://llm.example/v1",
            llm_model="classification-model",
            client=client,
        )
    assert llm_decision.category == ResourceCategory.PRODUCT
    assert llm_decision.source == "llm"


def test_user_rule_has_priority_and_can_select_custom_category() -> None:
    """用户规则优先于系统规则，并可命中自定义分类。"""

    metadata = ResourceMetadata(
        final_url="https://github.com/example/project",
        page_title="项目主页",
        description="工具项目",
        site_name="GitHub",
        favicon_url=None,
        http_status=200,
    )
    decision = classify_resource(
        metadata,
        user_rules=[
            ClassificationRule(
                category_code="custom_research",
                category_label="我的研究",
                match_type="domain",
                pattern="github.com",
            )
        ],
        category_options=[
            ClassificationCategory(
                code="custom_research",
                label="我的研究",
                description="需要长期研究的项目",
            )
        ],
    )
    assert decision.category == "custom_research"
    assert decision.category_label == "我的研究"
    assert decision.source == "user_rule"


def test_user_category_template_and_rule_api(client: TestClient) -> None:
    """用户可以创建分类模板和规则，并应用到已有资料。"""

    resource_response = client.post(
        "/api/v1/memos",
        json={
            "client_id": str(uuid4()),
            "type": "resource",
            "title": "研究项目",
            "body": "等待整理",
            "source_url": "https://notes.example.com/project",
            "tags": [],
        },
    )
    assert resource_response.status_code == 201

    custom_response = client.post(
        "/api/v1/resource-categories",
        json={
            "name": "我的研究",
            "description": "需要长期跟进的项目",
        },
    )
    assert custom_response.status_code == 201
    custom_category = custom_response.json()
    assert custom_category["is_system"] is False

    rule_response = client.post(
        "/api/v1/resource-category-rules",
        json={
            "category_code": custom_category["code"],
            "match_type": "domain",
            "pattern": "example.com",
            "priority": 10,
        },
    )
    assert rule_response.status_code == 201
    assert rule_response.json()["category_label"] == "我的研究"

    memo_response = client.get(
        f"/api/v1/memos/{resource_response.json()['id']}"
    )
    assert memo_response.status_code == 200
    assert memo_response.json()["resource_category"] == custom_category["code"]
    assert memo_response.json()["resource_category_label"] == "我的研究"

    rules_response = client.get("/api/v1/resource-category-rules")
    assert rules_response.status_code == 200
    assert len(rules_response.json()) == 1


def test_enrichment_updates_metadata_category_and_search(tmp_path: Path) -> None:
    """资料处理结果会写回条目并立即参与搜索。"""

    database = Database(f"sqlite+pysqlite:///{tmp_path / 'resource.db'}")
    database.create_schema()
    settings = Settings(
        database_url=database.database_url,
        cors_origins=("http://localhost:5173",),
        local_user_id="00000000-0000-0000-0000-000000000001",
        audio_directory=tmp_path / "audio",
        resource_enrichment_enabled=False,
    )
    with database.session_factory() as session:
        memo = create_memo(
            session,
            settings.local_user_id,
            MemoCreate(
                client_id=uuid4(),
                type=MemoType.RESOURCE,
                body="稍后阅读",
                source_url="https://learn.example/course",
                tags=[],
            ),
        )

        def fetcher(_url: str) -> ResourceMetadata:
            return ResourceMetadata(
                final_url="https://learn.example/course",
                page_title="张量基础课程",
                description="Tensor 与自动求导学习资料",
                site_name="学习站",
                favicon_url="https://learn.example/favicon.png",
                http_status=200,
            )

        enriched = enrich_resource(
            session,
            settings.local_user_id,
            memo.id,
            settings,
            metadata_fetcher=fetcher,
        )
        assert enriched.resource_metadata_status == "ready"
        assert enriched.resource_category == ResourceCategory.LEARNING
        assert enriched.title == "张量基础课程"
        assert enriched.link_health_status == "healthy"
        assert "学习资料" in enriched.resource_auto_tags

        results = list_memos(
            session,
            settings.local_user_id,
            query_text="自动求导",
        )
        assert [item.id for item in results] == [memo.id]
    database.dispose()


def test_resource_category_filter_api(client: TestClient) -> None:
    """资料列表可使用自动分类进行组合筛选。"""

    created = client.post(
        "/api/v1/memos",
        json={
            "client_id": str(uuid4()),
            "type": "resource",
            "title": "课程资料",
            "body": "稍后学习",
            "source_url": "https://example.com/course",
            "tags": [],
        },
    ).json()
    updated = client.patch(
        f"/api/v1/memos/{created['id']}",
        json={
            "expected_version": created["version"],
            "resource_category": "learning",
        },
    )
    assert updated.status_code == 200

    response = client.get(
        "/api/v1/memos",
        params={"type": "resource", "category": "learning"},
    )
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [created["id"]]
