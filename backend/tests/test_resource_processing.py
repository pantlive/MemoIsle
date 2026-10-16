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
    validate_browser_tab_url,
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


def test_browser_tab_url_skips_dns_and_rejects_literal_private_hosts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """标签页快照不能做 DNS，否则扩展连刷会堵死收藏请求。"""

    def boom(_hostname: str, _port: int, **_kwargs: object) -> list[object]:
        raise AssertionError("tab snapshot must not resolve DNS")

    monkeypatch.setattr("app.resource_processing.socket.getaddrinfo", boom)
    assert (
        validate_browser_tab_url("https://example.com/guide")
        == "https://example.com/guide"
    )
    with pytest.raises(UnsafeResourceUrlError, match="non_public_ip"):
        validate_browser_tab_url("http://127.0.0.1/private")
    with pytest.raises(UnsafeResourceUrlError, match="local_hostname"):
        validate_browser_tab_url("http://localhost/admin")
    with pytest.raises(UnsafeResourceUrlError, match="invalid_scheme"):
        validate_browser_tab_url("chrome://extensions")


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
    assert memo_response.json()["resource_categories"] == [custom_category["code"]]

    rules_response = client.get("/api/v1/resource-category-rules")
    assert rules_response.status_code == 200
    assert len(rules_response.json()) == 1

    renamed = client.patch(
        f"/api/v1/resource-categories/{custom_category['id']}",
        json={
            "expected_version": custom_category["version"],
            "name": "研究归档",
            "description": "长期项目",
        },
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "研究归档"
    renamed_memo = client.get(f"/api/v1/memos/{resource_response.json()['id']}")
    assert renamed_memo.status_code == 200
    assert renamed_memo.json()["resource_category_label"] == "研究归档"

    deleted = client.delete(
        f"/api/v1/resource-categories/{custom_category['id']}",
    )
    assert deleted.status_code == 200
    assert deleted.json() == {"deleted": True}
    leftover_rules = client.get("/api/v1/resource-category-rules")
    assert leftover_rules.status_code == 200
    assert leftover_rules.json() == []
    leftover_categories = client.get("/api/v1/resource-categories")
    assert leftover_categories.status_code == 200
    assert all(
        item["id"] != custom_category["id"]
        for item in leftover_categories.json()
    )
    cleared_memo = client.get(f"/api/v1/memos/{resource_response.json()['id']}")
    assert cleared_memo.status_code == 200
    assert cleared_memo.json()["resource_category"] is None
    missing = client.delete(
        f"/api/v1/resource-categories/{custom_category['id']}",
    )
    assert missing.status_code == 404


def test_category_hierarchy_and_multi_assign(client: TestClient) -> None:
    """自定义分类最多三层，资料可同时属于多个分类。"""

    created = client.post(
        "/api/v1/memos",
        json={
            "client_id": str(uuid4()),
            "type": "resource",
            "title": "PyTorch 教程",
            "body": "深度学习",
            "source_url": "https://learn.example.com/pytorch",
            "tags": [],
        },
    )
    assert created.status_code == 201
    memo_id = created.json()["id"]

    programming = client.post(
        "/api/v1/resource-categories",
        json={"name": "编程", "parent_code": "learning"},
    )
    assert programming.status_code == 201
    assert programming.json()["parent_code"] == "learning"
    assert programming.json()["depth"] == 2
    assert programming.json()["path"] == "学习资料 / 编程"

    python = client.post(
        "/api/v1/resource-categories",
        json={
            "name": "Python",
            "parent_code": programming.json()["code"],
        },
    )
    assert python.status_code == 201
    assert python.json()["depth"] == 3

    too_deep = client.post(
        "/api/v1/resource-categories",
        json={
            "name": "异步",
            "parent_code": python.json()["code"],
        },
    )
    assert too_deep.status_code == 422

    assigned = client.patch(
        f"/api/v1/memos/{memo_id}",
        json={
            "expected_version": created.json()["version"],
            "resource_categories": [
                python.json()["code"],
                "article",
            ],
        },
    )
    assert assigned.status_code == 200
    assert assigned.json()["resource_category"] == python.json()["code"]
    assert assigned.json()["resource_categories"] == [
        python.json()["code"],
        "article",
    ]

    filtered = client.get(
        "/api/v1/memos",
        params={"type": "resource", "category": "learning"},
    )
    assert filtered.status_code == 200
    assert filtered.json()["items"][0]["id"] == memo_id

    deleted_parent = client.delete(
        f"/api/v1/resource-categories/{programming.json()['id']}",
    )
    assert deleted_parent.status_code == 200
    leftover = client.get("/api/v1/resource-categories")
    leftover_codes = {item["code"] for item in leftover.json()}
    assert programming.json()["code"] not in leftover_codes
    assert python.json()["code"] not in leftover_codes
    remaining = client.get(f"/api/v1/memos/{memo_id}")
    assert remaining.json()["resource_categories"] == ["article"]
    assert remaining.json()["resource_category"] == "article"


def test_delete_category_rewrites_image_memos(client: TestClient) -> None:
    """删除自定义分类时，图片上的同一编码也要清掉。"""

    created = client.post(
        "/api/v1/memos",
        json={
            "client_id": str(uuid4()),
            "type": "image",
            "title": "课堂照片",
            "body": "板书",
        },
    )
    assert created.status_code == 201
    custom = client.post("/api/v1/resource-categories", json={"name": "课堂笔记"})
    assert custom.status_code == 201
    assigned = client.patch(
        f"/api/v1/memos/{created.json()['id']}",
        json={
            "expected_version": created.json()["version"],
            "resource_categories": [custom.json()["code"], "article"],
        },
    )
    assert assigned.status_code == 200
    assert assigned.json()["resource_categories"] == [
        custom.json()["code"],
        "article",
    ]

    deleted = client.delete(f"/api/v1/resource-categories/{custom.json()['id']}")
    assert deleted.status_code == 200
    remaining = client.get(f"/api/v1/memos/{created.json()['id']}")
    assert remaining.json()["resource_categories"] == ["article"]
    assert remaining.json()["resource_category"] == "article"


def test_user_rule_extra_categories_bump_version(client: TestClient) -> None:
    """附加分类变化也要增加 version，避免打开中的编辑器用旧快照覆盖。"""

    created = client.post(
        "/api/v1/memos",
        json={
            "client_id": str(uuid4()),
            "type": "resource",
            "title": "规则网页",
            "body": "备注",
            "source_url": "https://rules.example.com/page",
        },
    )
    assert created.status_code == 201
    primary = client.post("/api/v1/resource-categories", json={"name": "规则主类"})
    extra = client.post("/api/v1/resource-categories", json={"name": "规则附加"})
    other = client.post("/api/v1/resource-categories", json={"name": "规则另一附加"})
    assert primary.status_code == extra.status_code == other.status_code == 201
    first_rule = client.post(
        "/api/v1/resource-category-rules",
        json={
            "category_code": primary.json()["code"],
            "match_type": "domain",
            "pattern": "rules.example.com",
            "priority": 10,
        },
    )
    second_rule = client.post(
        "/api/v1/resource-category-rules",
        json={
            "category_code": extra.json()["code"],
            "match_type": "domain",
            "pattern": "rules.example.com",
            "priority": 20,
        },
    )
    assert first_rule.status_code == second_rule.status_code == 201

    before = client.get(f"/api/v1/memos/{created.json()['id']}").json()
    assert before["resource_category"] == primary.json()["code"]
    assert extra.json()["code"] in before["resource_categories"]

    changed = client.patch(
        f"/api/v1/resource-category-rules/{second_rule.json()['id']}",
        json={
            "expected_version": second_rule.json()["version"],
            "category_code": other.json()["code"],
        },
    )
    assert changed.status_code == 200
    after = client.get(f"/api/v1/memos/{created.json()['id']}").json()
    assert after["resource_category"] == primary.json()["code"]
    assert other.json()["code"] in after["resource_categories"]
    assert extra.json()["code"] not in after["resource_categories"]
    assert after["version"] > before["version"]


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
