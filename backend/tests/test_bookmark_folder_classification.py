"""书签原文件夹复核：对应已有分类、Jev 认可后沿用，不认可时照常完整分类。"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

import httpx
import pytest
from app.bookmark_folder_classification import (
    categories_fingerprint,
    meaningful_folder_path,
)
from app.category_service import classification_categories
from app.models import BookmarkFolderCategory, Memo, ResourceClassificationJob
from app.resource_classification_service import run_pending_classification_jobs
from app.resource_processing import CategoryDecision, ResourceMetadata
from app.resource_service import enrich_resource
from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.classification_stubs import patch_web_classifier


@pytest.fixture(autouse=True)
def pause_automatic_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    """测试由显式调用控制进度，避免后台线程访问真实模型服务。"""

    async def idle(
        _database_url: str,
        _settings: object,
        stop_event: asyncio.Event,
    ) -> None:
        await stop_event.wait()

    monkeypatch.setattr("app.main.resource_classification_loop", idle)


class FakeJev:
    """按请求内容区分“文件夹对应分类”和“网页是否属于该分类”两类 Jev 请求。"""

    def __init__(self) -> None:
        self.mapping: dict[str, tuple[str, float]] = {}
        self.verify: dict[str, tuple[str, float]] = {}
        self.mapping_calls: list[str] = []
        self.verify_calls: list[dict[str, Any]] = []
        self.error: Exception | None = None

    def __call__(
        self,
        payload: dict[str, Any],
        _api_key: str,
        _base_url: str,
        _client: object,
    ) -> object:
        if self.error is not None:
            raise self.error
        state = payload["state"]
        if "url" not in state:
            # 标签请求用“#标签名”作键，和文件夹区分开。
            folder = state.get("bookmark_folder") or f"#{state['bookmark_tag']}"
            self.mapping_calls.append(folder)
            choice, confidence = self.mapping.get(folder, ("none", 0.9))
        else:
            self.verify_calls.append(state)
            choice, confidence = self.verify.get(state["title"], ("none", 0.9))
        return {"answers": {"category": {"choice": choice, "confidence": confidence}}}


@pytest.fixture
def jev(monkeypatch: pytest.MonkeyPatch) -> FakeJev:
    fake = FakeJev()
    monkeypatch.setattr("app.bookmark_folder_classification._post_jev", fake)
    return fake


@pytest.fixture
def full_classifier(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """完整分类流程的替身，记录被送去完整分类的网页标题。"""

    titles: list[str] = []

    def classify(metadata: ResourceMetadata, *_args: object) -> CategoryDecision:
        titles.append(metadata.page_title or "")
        return CategoryDecision(
            "tool",
            "工具与服务",
            0.9,
            "jev",
            ("工具",),
            assessment={
                "status": "classified",
                "reason_code": "accepted",
                "confidence": 0.9,
                "threshold": 0.7,
                "candidates": [],
                "input_source": "metadata",
                "input_excerpt": None,
                "model": "typesafe/jev",
                "attempted_at": "2026-10-16T00:00:00+00:00",
            },
        )

    patch_web_classifier(monkeypatch, classify)
    return titles


def configure_jev(client: TestClient) -> None:
    response = client.put(
        "/api/v1/model-settings/jev",
        json={
            "model": "typesafe/jev",
            "api_key": "test-folder-key",
            "base_url": "https://relay.example/v1",
        },
    )
    assert response.status_code == 200


def create_category(client: TestClient, name: str) -> str:
    response = client.post("/api/v1/resource-categories", json={"name": name})
    assert response.status_code == 201
    return response.json()["code"]


def create_bookmark(
    client: TestClient,
    title: str,
    folder: str | None,
    **values: object,
) -> str:
    response = client.post(
        "/api/v1/memos",
        json={
            "client_id": str(uuid4()),
            "type": "resource",
            "title": title,
            "body": title,
            "source_url": f"https://example.com/{uuid4().hex}",
        },
    )
    assert response.status_code == 201
    memo_id = response.json()["id"]
    with client.app.state.database.session_factory() as session:
        memo = session.get(Memo, memo_id)
        memo.link_health_status = "healthy"
        memo.resource_metadata_status = "ready"
        memo.resource_page_title = title
        memo.resource_import_folder = folder
        for key, value in values.items():
            setattr(memo, key, value)
        session.commit()
    return memo_id


def read_memo(client: TestClient, memo_id: str) -> Memo:
    with client.app.state.database.session_factory() as session:
        memo = session.get(Memo, memo_id)
        session.expunge(memo)
        return memo


def run_jobs(client: TestClient) -> int:
    settings = client.app.state.settings
    return run_pending_classification_jobs(settings.database_url, settings)


def test_meaningful_folder_path_strips_browser_roots() -> None:
    assert meaningful_folder_path("书签栏 /开发/ 前端") == "开发 / 前端"
    assert meaningful_folder_path("Bookmarks bar/Dev Tools") == "Dev Tools"
    assert meaningful_folder_path("其他书签") is None
    assert meaningful_folder_path("书签栏 ") is None
    assert meaningful_folder_path(None) is None
    # 只去掉开头的浏览器根目录，用户自己起的同名子文件夹保留。
    assert meaningful_folder_path("书签栏/学习/收藏夹") == "学习 / 收藏夹"


def test_confirmed_folder_keeps_category_without_full_classification(
    client: TestClient,
    jev: FakeJev,
    full_classifier: list[str],
) -> None:
    configure_jev(client)
    frontend = create_category(client, "前端开发")
    jev.mapping["开发 / 前端"] = (frontend, 0.92)
    jev.verify["React 文档"] = (frontend, 0.88)
    memo_id = create_bookmark(client, "React 文档", "书签栏 /开发/前端")

    assert run_jobs(client) == 1
    memo = read_memo(client, memo_id)
    assert memo.resource_category == frontend
    assert memo.resource_category_source == "jev"
    assert memo.resource_ai_classified_at is not None
    evidence = memo.resource_ai_assessment["bookmark_folder"]
    assert evidence["verdict"] == "kept"
    assert evidence["folder"] == "开发 / 前端"
    assert evidence["category_code"] == frontend
    assert full_classifier == []
    # 第二步请求带上网页内容和原文件夹，只给出对应分类和“不属于”两个选项。
    assert jev.verify_calls[0]["bookmark_folder"] == "开发 / 前端"
    state = client.get(f"/api/v1/memos/{memo_id}").json()
    assert state["resource_ai_assessment"]["bookmark_folder"]["verdict"] == "kept"


def test_rejected_folder_falls_back_to_full_classification(
    client: TestClient,
    jev: FakeJev,
    full_classifier: list[str],
) -> None:
    configure_jev(client)
    frontend = create_category(client, "前端开发")
    jev.mapping["开发 / 前端"] = (frontend, 0.92)
    jev.verify["外卖优惠券"] = ("none", 0.95)
    memo_id = create_bookmark(client, "外卖优惠券", "书签栏/开发/前端")

    assert run_jobs(client) == 1
    memo = read_memo(client, memo_id)
    assert full_classifier == ["外卖优惠券"]
    assert memo.resource_category == "tool"
    evidence = memo.resource_ai_assessment["bookmark_folder"]
    assert evidence["verdict"] == "rejected"
    assert evidence["category_code"] == frontend


def test_low_confidence_verification_is_not_kept(
    client: TestClient,
    jev: FakeJev,
    full_classifier: list[str],
) -> None:
    configure_jev(client)
    frontend = create_category(client, "前端开发")
    jev.mapping["前端"] = (frontend, 0.92)
    jev.verify["拿不准的网页"] = (frontend, 0.4)
    memo_id = create_bookmark(client, "拿不准的网页", "书签栏/前端")

    run_jobs(client)
    memo = read_memo(client, memo_id)
    assert full_classifier == ["拿不准的网页"]
    assert memo.resource_ai_assessment["bookmark_folder"]["verdict"] == "rejected"
    assert memo.resource_ai_assessment["bookmark_folder"]["confidence"] == 0.4


def test_folder_mapping_is_cached_and_invalidated_by_template_change(
    client: TestClient,
    jev: FakeJev,
    full_classifier: list[str],
) -> None:
    configure_jev(client)
    create_category(client, "前端开发")
    first = create_bookmark(client, "稍后读一", "书签栏/稍后读")
    create_bookmark(client, "稍后读二", "书签栏/稍后读")

    assert run_jobs(client) == 2
    # 同一文件夹只判断一次；没有对应分类时网页照常完整分类。
    assert jev.mapping_calls == ["稍后读"]
    assert jev.verify_calls == []
    assert sorted(full_classifier) == ["稍后读一", "稍后读二"]
    evidence = read_memo(client, first).resource_ai_assessment["bookmark_folder"]
    assert evidence == {
        "folder": "稍后读",
        "category_code": None,
        "category_label": None,
        "verdict": "unmapped",
        "confidence": None,
        "kind": "folder",
        "mapping_source": "jev",
    }

    create_category(client, "阅读清单")
    create_bookmark(client, "稍后读三", "书签栏/稍后读")
    run_jobs(client)
    assert jev.mapping_calls == ["稍后读", "稍后读"]
    with client.app.state.database.session_factory() as session:
        rows = session.scalars(select(BookmarkFolderCategory)).all()
        fingerprint = categories_fingerprint(
            classification_categories(session, client.app.state.settings.local_user_id)
        )
    # 旧模板下的结果被替换，不会越积越多。
    assert [row.categories_fingerprint for row in rows] == [fingerprint]


def test_root_only_folder_skips_folder_check(
    client: TestClient,
    jev: FakeJev,
    full_classifier: list[str],
) -> None:
    configure_jev(client)
    memo_id = create_bookmark(client, "书签栏网页", "书签栏 ")

    run_jobs(client)
    assert jev.mapping_calls == []
    assert full_classifier == ["书签栏网页"]
    assert "bookmark_folder" not in read_memo(client, memo_id).resource_ai_assessment


def test_folder_service_failure_pauses_job(
    client: TestClient,
    jev: FakeJev,
    full_classifier: list[str],
) -> None:
    configure_jev(client)
    memo_id = create_bookmark(client, "网页", "书签栏/工具")
    request = httpx.Request("POST", "https://relay.example/v1/systemone")
    jev.error = httpx.HTTPStatusError(
        "unavailable",
        request=request,
        response=httpx.Response(503, request=request),
    )

    run_jobs(client)
    memo = read_memo(client, memo_id)
    assert memo.resource_ai_classified_at is None
    assert full_classifier == []
    with client.app.state.database.session_factory() as session:
        job = session.get(
            ResourceClassificationJob, client.app.state.settings.local_user_id
        )
        assert job.processed_count == 0
        assert job.error and "Jev" in job.error


def test_retry_by_folder_requeues_imported_pages(
    client: TestClient,
    jev: FakeJev,
    full_classifier: list[str],
) -> None:
    configure_jev(client)
    frontend = create_category(client, "前端开发")
    ai_page = create_bookmark(client, "Vue 文档", "书签栏/前端")
    rule_page = create_bookmark(client, "CSS 技巧", "书签栏/前端")
    manual_page = create_bookmark(client, "手动归类", "书签栏/前端")
    root_page = create_bookmark(client, "根目录", "书签栏")
    plain_page = create_bookmark(client, "不是书签", None)
    # 首轮文件夹对应上了分类，但网页被判定不符，先走完整分类。
    jev.mapping["前端"] = (frontend, 0.9)
    run_jobs(client)
    full_classifier.clear()
    jev.mapping_calls.clear()
    with client.app.state.database.session_factory() as session:
        session.get(Memo, rule_page).resource_category_source = "rule"
        session.get(Memo, rule_page).resource_ai_classified_at = None
        session.get(Memo, manual_page).resource_category_source = "manual"
        session.commit()

    state = client.get("/api/v1/resource-classification").json()
    assert state["folder_retry_count"] == 2

    jev.verify["Vue 文档"] = (frontend, 0.9)
    jev.verify["CSS 技巧"] = (frontend, 0.9)
    response = client.post("/api/v1/resource-classification/folders/retry")
    assert response.status_code == 202
    job = response.json()["job"]
    assert job["total_count"] == 2
    assert job["automatic"] is False

    run_jobs(client)
    assert read_memo(client, ai_page).resource_category == frontend
    assert read_memo(client, rule_page).resource_category == frontend
    assert read_memo(client, manual_page).resource_category_source == "manual"
    assert full_classifier == []
    # 映射结果已缓存，重新判断不必再问文件夹含义。
    assert jev.mapping_calls == []
    for memo_id in (root_page, plain_page):
        assert read_memo(client, memo_id).resource_category == "tool"


def test_retry_by_folder_requires_jev(client: TestClient) -> None:
    create_bookmark(client, "网页", "书签栏/工具")
    response = client.put(
        "/api/v1/model-settings/deepseek",
        json={
            "model": "deepseek-chat",
            "api_key": "test-deepseek-key",
            "base_url": "https://deepseek.example/v1",
        },
    )
    assert response.status_code == 200
    response = client.post("/api/v1/resource-classification/folders/retry")
    assert response.status_code == 400
    assert "Jev" in response.json()["detail"]


def test_rejected_verdict_keeps_confidence(
    client: TestClient,
    jev: FakeJev,
    full_classifier: list[str],
) -> None:
    configure_jev(client)
    frontend = create_category(client, "前端开发")
    jev.mapping["前端"] = (frontend, 0.9)
    jev.verify["优惠券"] = ("none", 0.95)
    memo_id = create_bookmark(client, "优惠券", "书签栏/前端")

    run_jobs(client)
    evidence = read_memo(client, memo_id).resource_ai_assessment["bookmark_folder"]
    assert evidence["verdict"] == "rejected"
    assert evidence["confidence"] == 0.95


def test_full_classification_choosing_rejected_category_goes_to_review(
    client: TestClient,
    jev: FakeJev,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_jev(client)
    frontend = create_category(client, "前端开发")
    jev.mapping["前端"] = (frontend, 0.9)
    jev.verify["两头不一致"] = ("none", 0.8)

    def classify(_metadata: ResourceMetadata, *_args: object) -> CategoryDecision:
        return CategoryDecision(
            frontend,
            "前端开发",
            0.9,
            "jev",
            ("前端开发",),
            assessment={
                "status": "classified",
                "reason_code": "accepted",
                "confidence": 0.9,
                "threshold": 0.7,
                "candidates": [
                    {"code": frontend, "label": "前端开发", "probability": 0.9},
                ],
                "input_source": "metadata",
                "input_excerpt": None,
                "model": "typesafe/jev",
                "attempted_at": "2026-10-16T00:00:00+00:00",
            },
        )

    patch_web_classifier(monkeypatch, classify)
    memo_id = create_bookmark(client, "两头不一致", "书签栏/前端")
    run_jobs(client)

    memo = read_memo(client, memo_id)
    # 两次判断结论相反：不写入分类，保留原分类等用户确认。
    assert memo.resource_category != frontend
    assert memo.resource_ai_confirmation_pending is True
    assert memo.resource_ai_assessment["reason_code"] == "folder_conflict"
    assert memo.resource_ai_assessment["bookmark_folder"]["verdict"] == "rejected"
    review = client.get(
        "/api/v1/resource-classification/review",
        params={"reason": "folder_conflict"},
    ).json()
    assert [item["id"] for item in review["items"]] == [memo_id]


def test_bookmark_tags_are_imported_and_used_as_original_category(
    client: TestClient,
    jev: FakeJev,
    full_classifier: list[str],
) -> None:
    configure_jev(client)
    frontend = create_category(client, "前端开发")
    jev.mapping["#前端"] = (frontend, 0.9)
    jev.verify["Svelte 教程"] = (frontend, 0.9)
    response = client.post(
        "/api/v1/bookmark-imports",
        json={
            "items": [
                {
                    "client_item_id": "firefox-1",
                    "title": "Svelte 教程",
                    "url": "https://svelte.example.com/tutorial",
                    "folder_path": "书签菜单",
                    "tags": [" 前端 ", "前端", "", "教程"],
                }
            ]
        },
    )
    assert response.status_code in {200, 201, 202}
    with client.app.state.database.session_factory() as session:
        memo = session.scalar(select(Memo).where(Memo.title == "Svelte 教程"))
        memo_id = memo.id
        assert memo.tags == ["前端", "教程"]
        assert memo.resource_import_tags == ["前端", "教程"]
        # 测试环境不抓取网页，直接标为可分类。
        memo.link_health_status = "healthy"
        memo.resource_page_title = "Svelte 教程"
        session.commit()

    run_jobs(client)
    memo = read_memo(client, memo_id)
    evidence = memo.resource_ai_assessment["bookmark_folder"]
    assert memo.resource_category == frontend
    assert evidence["kind"] == "tag"
    assert evidence["folder"] == "前端"
    # 根目录不算原归类，只问了第一个标签就对应上了。
    assert jev.mapping_calls == ["#前端"]
    assert full_classifier == []


def test_mapping_overview_map_override_and_retry(
    client: TestClient,
    jev: FakeJev,
    full_classifier: list[str],
) -> None:
    configure_jev(client)
    frontend = create_category(client, "前端开发")
    tools = create_category(client, "效率工具")
    pages = {
        "Vue": create_bookmark(
            client, "Vue", "书签栏/前端", resource_category_source="rule"
        ),
        "Vite": create_bookmark(
            client, "Vite", "书签栏/前端", resource_category_source="rule"
        ),
        "Todo": create_bookmark(
            client, "Todo", "书签栏/杂项", resource_category_source="rule"
        ),
        "Note": create_bookmark(
            client, "Note", "书签栏/稍后读", resource_category_source="rule"
        ),
    }
    with client.app.state.database.session_factory() as session:
        for memo_id in pages.values():
            session.get(Memo, memo_id).resource_ai_auto_pending = False
        session.commit()

    overview = client.get("/api/v1/resource-classification/folders").json()
    assert overview["pending_count"] == 3
    assert overview["page_count"] == 4
    assert overview["retry_count"] == 0
    assert overview["items"][0] == {
        "key": "前端",
        "kind": "folder",
        "text": "前端",
        "page_count": 2,
        "status": "pending",
        "source": None,
        "category_code": None,
        "category_label": None,
        "confidence": None,
    }
    assert {"code": frontend, "label": "前端开发"} in overview["categories"]

    jev.mapping["前端"] = (frontend, 0.88)
    mapped = client.post(
        "/api/v1/resource-classification/folders/map", params={"limit": 2}
    ).json()
    assert mapped["pending_count"] == 1
    mapped = client.post("/api/v1/resource-classification/folders/map").json()
    assert mapped["pending_count"] == 0
    assert jev.mapping_calls == ["前端", "杂项", "稍后读"]
    by_key = {item["key"]: item for item in mapped["items"]}
    assert by_key["前端"]["status"] == "mapped"
    assert by_key["前端"]["confidence"] == 0.88
    assert by_key["杂项"]["status"] == "unmapped"
    assert mapped["retry_count"] == 2

    # 手动把「杂项」指定为效率工具，把「前端」设为不沿用。
    overridden = client.put(
        "/api/v1/resource-classification/folders/override",
        json={"key": "杂项", "mode": "category", "category_code": tools},
    ).json()
    by_key = {item["key"]: item for item in overridden["items"]}
    assert by_key["杂项"]["source"] == "manual"
    assert by_key["杂项"]["category_label"] == "效率工具"
    overridden = client.put(
        "/api/v1/resource-classification/folders/override",
        json={"key": "前端", "mode": "skip"},
    ).json()
    assert overridden["retry_count"] == 1
    invalid = client.put(
        "/api/v1/resource-classification/folders/override",
        json={"key": "前端", "mode": "category", "category_code": "missing"},
    )
    assert invalid.status_code == 422

    jev.verify["Todo"] = (tools, 0.9)
    response = client.post("/api/v1/resource-classification/folders/retry")
    assert response.json()["job"]["total_count"] == 1
    run_jobs(client)
    assert read_memo(client, pages["Todo"]).resource_category == tools
    assert (
        read_memo(client, pages["Todo"]).resource_ai_assessment["bookmark_folder"][
            "mapping_source"
        ]
        == "manual"
    )
    # 文件夹判断过后不会再问。
    assert jev.mapping_calls == ["前端", "杂项", "稍后读"]

    # 恢复由 Jev 判断后，「前端」重新沿用缓存的结果。
    restored = client.put(
        "/api/v1/resource-classification/folders/override",
        json={"key": "前端", "mode": "auto"},
    ).json()
    assert {item["key"]: item for item in restored["items"]}["前端"]["source"] == "jev"


def test_folder_mapping_requires_jev(client: TestClient) -> None:
    create_bookmark(client, "网页", "书签栏/工具")
    response = client.post("/api/v1/resource-classification/folders/map")
    assert response.status_code == 400


def test_single_page_refresh_checks_folder(
    client: TestClient,
    jev: FakeJev,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_jev(client)
    frontend = create_category(client, "前端开发")
    jev.mapping["前端"] = (frontend, 0.9)
    jev.verify["Angular"] = (frontend, 0.9)
    calls: list[str] = []

    def classify(metadata: ResourceMetadata, **_kwargs: object) -> CategoryDecision:
        calls.append(metadata.page_title or "")
        return CategoryDecision("tool", "工具与服务", 0.9, "jev", ())

    monkeypatch.setattr("app.resource_service.classify_resource", classify)
    memo_id = create_bookmark(client, "Angular", "书签栏/前端")
    settings = client.app.state.settings
    with client.app.state.database.session_factory() as session:
        memo = enrich_resource(
            session,
            settings.local_user_id,
            memo_id,
            settings,
            metadata_fetcher=lambda url: ResourceMetadata(
                url, "Angular", "框架文档", "Angular", None, 200
            ),
        )
        assert memo.resource_category == frontend
        assert memo.resource_page_title == "Angular"
        assert memo.resource_ai_assessment["bookmark_folder"]["verdict"] == "kept"
    assert calls == []
