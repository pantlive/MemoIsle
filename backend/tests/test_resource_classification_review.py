"""分类确认的完整分页、人工决策、账号隔离及并发保护测试。"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.auth_service import create_dev_session
from app.models import Memo, ResourceClassificationJob
from app.resource_classification_quality import (
    ClassificationAssessment,
    UncertainClassificationError,
    parse_jev_assessment,
)
from app.resource_classification_service import (
    run_pending_classification_jobs,
    start_classification_job,
)
from app.resource_processing import CategoryDecision, ResourceMetadata
from app.resource_service import apply_category, enrich_resource
from fastapi.testclient import TestClient

from tests.classification_stubs import patch_web_classifier

REVIEW_URL = "/api/v1/resource-classification/review"


@pytest.fixture(autouse=True)
def pause_automatic_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    """只允许显式驱动测试队列，避免后台网络请求。"""

    async def idle(
        _database_url: str,
        _settings: object,
        stop_event: asyncio.Event,
    ) -> None:
        """在测试生命周期结束时退出。"""

        await stop_event.wait()

    monkeypatch.setattr("app.main.resource_classification_loop", idle)


def uncertain_assessment(
    code: str = "tool",
    confidence: float = 0.4,
) -> ClassificationAssessment:
    """从真实解析器生成可信的低置信度候选证据。"""

    with pytest.raises(UncertainClassificationError) as caught:
        parse_jev_assessment(
            {
                "answers": {
                    "category": {
                        "choice": code,
                        "confidence": confidence,
                        "probabilities": {code: 0.6, "article": 0.4},
                    }
                }
            },
            {code: "候选工具", "article": "文章阅读"},
            0.7,
            "typesafe/jev",
            True,
            "公开的工具介绍与文章内容摘要",
        )
    return caught.value.assessment


def seed_reviews(
    client: TestClient,
    count: int = 1,
    legacy: bool = False,
) -> list[str]:
    """直接保存隔离数据，验证两百条以上的真实数据库分页。"""

    ids = [str(uuid4()) for _ in range(count)]
    with client.app.state.database.session_factory() as session:
        session.add_all(
            [
                Memo(
                    id=memo_id,
                    user_id=client.app.state.settings.local_user_id,
                    client_id=str(uuid4()),
                    type="resource",
                    title=f"复核网页 {index}",
                    body="不能出现在确认列表的私人备注",
                    source_url=f"https://example.com/review/{index}",
                    resource_metadata_status="ready",
                    link_health_status="healthy",
                    resource_category="tool",
                    resource_categories=["tool", "article"],
                    resource_category_label="工具与服务",
                    resource_category_source="rule",
                    resource_category_status="ready",
                    resource_category_confidence=0.8,
                    resource_auto_tags=["原标签"],
                    resource_ai_auto_pending=False,
                    resource_ai_confirmation_pending=True,
                    resource_ai_assessment=None if legacy else uncertain_assessment(),
                )
                for index, memo_id in enumerate(ids)
            ]
        )
        session.commit()
    return ids


def seed_pending_resource(client: TestClient, title: str = "尚未分类网页") -> str:
    """插入一条普通待处理网页，不进入确认中心。"""

    memo_id = str(uuid4())
    with client.app.state.database.session_factory() as session:
        session.add(
            Memo(
                id=memo_id,
                user_id=client.app.state.settings.local_user_id,
                client_id=str(uuid4()),
                type="resource",
                title=title,
                body="",
                source_url=f"https://example.com/pending/{memo_id}",
                resource_metadata_status="ready",
                link_health_status="healthy",
                resource_category="other",
                resource_category_label="其他",
                resource_category_source="fallback",
                resource_category_status="ready",
            )
        )
        session.commit()
    return memo_id


def selection(client: TestClient, memo_id: str) -> dict[str, object]:
    """使用用户当前看到的版本构建确认请求。"""

    memo = client.get(f"/api/v1/memos/{memo_id}").json()
    return {"memo_id": memo_id, "expected_version": memo["version"]}


def configure_jev(client: TestClient) -> None:
    """队列测试只使用模拟配置，不访问真实中转。"""

    response = client.put(
        "/api/v1/model-settings/jev",
        json={
            "model": "typesafe/jev",
            "api_key": "review-test-fake-key",
            "base_url": "https://relay.example/v1",
        },
    )
    assert response.status_code == 200


def test_review_pagination_filters_and_private_fields(client: TestClient) -> None:
    """全量分页超过两百条，组合筛选正确且不返回私人备注。"""

    ids = seed_reviews(client, 231)
    seed_reviews(client, legacy=True)
    with client.app.state.database.session_factory() as session:
        memo = session.get(Memo, ids[0])
        memo.title = "进度 100%_完成"
        memo.resource_ai_assessment = uncertain_assessment(confidence=0.2)
        session.commit()
    seen: set[str] = set()
    for offset in range(0, 232, 50):
        response = client.get(REVIEW_URL, params={"offset": offset})
        assert response.status_code == 200
        data = response.json()
        assert data["total_count"] == 232
        assert len(data["items"]) == min(50, 232 - offset)
        assert not seen.intersection(item["id"] for item in data["items"])
        seen.update(item["id"] for item in data["items"])
        assert "私人备注" not in response.text
        assert all("body" not in item for item in data["items"])
    assert len(seen) == 232
    filtered = client.get(
        REVIEW_URL,
        params={
            "query": "%_",
            "reason": "low_confidence",
            "candidate_code": "tool",
            "max_confidence": 0.3,
        },
    ).json()
    assert [item["id"] for item in filtered["items"]] == [ids[0]]
    assert (
        client.get(
            REVIEW_URL,
            params={
                "reason": "legacy",
                "candidate_code": "_none",
            },
        ).json()["total_count"]
        == 1
    )
    assert (
        client.get(REVIEW_URL, params={"max_confidence": 0.3}).json()["total_count"]
        == 1
    )


@pytest.mark.parametrize(
    "change",
    [
        {"link_health_status": "failed"},
        {"status": "trashed"},
        {"ebook_provider": "baidu"},
        {"type": "idea"},
        {"resource_category_source": "manual"},
        {"resource_category_source": "user_rule"},
        {"resource_ai_classified_at": datetime.now(UTC)},
    ],
)
def test_review_does_not_bypass_health_or_protected_resources(
    client: TestClient,
    change: dict[str, object],
) -> None:
    """分类确认不得处理确认失效、改动手动分类或处理非网页条目。"""

    memo_id = seed_reviews(client)[0]
    with client.app.state.database.session_factory() as session:
        memo = session.get(Memo, memo_id)
        for field, value in change.items():
            setattr(memo, field, value)
        session.commit()
    assert client.get(REVIEW_URL).json()["total_count"] == 0
    result = client.post(
        f"{REVIEW_URL}/confirm",
        json={
            "action": "keep",
            "items": [selection(client, memo_id)],
        },
    ).json()
    assert result["updated_count"] == 0
    assert result["results"][0]["reason"] == "not_pending"
    assert (
        client.get(f"/api/v1/memos/{memo_id}").json()["resource_ai_confirmation"]
        is None
    )


def test_adopt_secondary_candidate_preserves_original_evidence(
    client: TestClient,
) -> None:
    """采纳第二候选记作人工决策，保留模型原始低置信度依据。"""

    memo_id = seed_reviews(client)[0]
    before = client.get(f"/api/v1/memos/{memo_id}").json()
    result = client.post(
        f"{REVIEW_URL}/confirm",
        json={
            "action": "adopt",
            "items": [
                {
                    **selection(client, memo_id),
                    "candidate_code": "article",
                }
            ],
        },
    ).json()
    assert result["updated_count"] == 1
    after = client.get(f"/api/v1/memos/{memo_id}").json()
    assert after["version"] == before["version"] + 1
    assert after["resource_category_source"] == "manual"
    assert after["resource_categories"] == ["article"]
    assert after["resource_ai_assessment"] == before["resource_ai_assessment"]
    assert after["resource_ai_classified_at"] is None
    assert after["resource_ai_confirmation"]["action"] == "adopt"
    assert after["resource_ai_confirmation"]["category_label"] == "文章阅读"
    assert after["resource_ai_confirmation_pending"] is False
    assert client.get(REVIEW_URL).json()["total_count"] == 0


def test_keep_preserves_all_categories_and_stops_automatic_processing(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """保留原分类仍形成持久确认，不让模型或规则覆盖原多类别。"""

    memo_id = seed_reviews(client, legacy=True)[0]
    before = client.get(f"/api/v1/memos/{memo_id}").json()
    assert (
        client.post(
            f"{REVIEW_URL}/confirm",
            json={
                "action": "keep",
                "items": [selection(client, memo_id)],
            },
        ).json()["updated_count"]
        == 1
    )
    after = client.get(f"/api/v1/memos/{memo_id}").json()
    for field in (
        "resource_category",
        "resource_categories",
        "resource_auto_tags",
        "resource_category_source",
        "resource_category_confidence",
        "resource_category_status",
        "resource_ai_assessment",
    ):
        assert after[field] == before[field]
    state = client.get("/api/v1/resource-classification").json()
    assert state["pending_count"] == state["review_count"] == 0
    assert state["protected_count"] == 1 and state["classified_count"] == 0
    with client.app.state.database.session_factory() as session:
        memo = session.get(Memo, memo_id)
        apply_category(memo, CategoryDecision("learning", "学习资料", 0.9, "jev", ()))
        session.commit()
    assert (
        client.get(f"/api/v1/memos/{memo_id}").json()["resource_categories"]
        == before["resource_categories"]
    )
    configure_jev(client)

    def classify_without_model(
        _metadata: ResourceMetadata,
        **kwargs: object,
    ) -> CategoryDecision:
        """已经确认的网页刷新资料时不能向模型传递调用凭据。"""

        assert kwargs["jev_api_key"] is None and kwargs["llm_api_key"] is None
        return CategoryDecision("learning", "学习资料", 0.8, "rule", ())

    monkeypatch.setattr(
        "app.resource_service.classify_resource", classify_without_model
    )
    settings = client.app.state.settings
    with client.app.state.database.session_factory() as session:
        enriched = enrich_resource(
            session,
            settings.local_user_id,
            memo_id,
            settings,
            metadata_fetcher=lambda url: ResourceMetadata(
                url, None, None, None, None, 200
            ),
            review_confirmed=True,
        )
        assert enriched.resource_categories == before["resource_categories"]
        assert not enriched.resource_ai_auto_pending
    assert (
        client.post("/api/v1/resource-classification").json()["job"]["total_count"] == 0
    )


def test_assign_legacy_and_new_reviews_without_model_calls(client: TestClient) -> None:
    """无候选的历史条目也能批量指定现有分类，不伪造模型完成标记。"""

    ids = seed_reviews(client) + seed_reviews(client, legacy=True)
    response = client.post(
        f"{REVIEW_URL}/confirm",
        json={
            "action": "assign",
            "category_code": "learning",
            "items": [selection(client, memo_id) for memo_id in ids],
        },
    )
    assert response.status_code == 200 and response.json()["updated_count"] == 2
    for memo_id in ids:
        memo = client.get(f"/api/v1/memos/{memo_id}").json()
        assert memo["resource_category"] == "learning"
        assert memo["resource_ai_classified_at"] is None
        assert memo["resource_ai_confirmation"]["action"] == "assign"


def test_partial_confirmation_reports_conflict_missing_and_forged_candidate(
    client: TestClient,
) -> None:
    """混合批次只更新有效选项，不能伪造候选或覆盖过期版本。"""

    ids = seed_reviews(client, 3)
    legacy = seed_reviews(client, legacy=True)[0]
    items = [selection(client, memo_id) for memo_id in [*ids, legacy]]
    items[1]["expected_version"] = 99
    items[2]["candidate_code"] = "learning"
    items.append({"memo_id": str(uuid4()), "expected_version": 1})
    result = client.post(
        f"{REVIEW_URL}/confirm",
        json={
            "action": "adopt",
            "items": items,
        },
    ).json()
    assert result["updated_count"] == 1 and result["skipped_count"] == 4
    assert [item["reason"] for item in result["results"]] == [
        None,
        "conflict",
        "no_candidate",
        "no_candidate",
        "missing",
    ]
    replay = client.post(
        f"{REVIEW_URL}/confirm",
        json={
            "action": "keep",
            "items": [items[0]],
        },
    ).json()
    assert replay["updated_count"] == 0
    assert replay["results"][0]["reason"] == "conflict"


def test_template_changes_are_reflected_and_disabled_candidate_is_skipped(
    client: TestClient,
) -> None:
    """当前模板路径随重命名更新，停用模板仍可查看依据但不能采纳。"""

    category = client.post(
        "/api/v1/resource-categories",
        json={
            "name": "历史名称",
        },
    ).json()
    memo_id = seed_reviews(client)[0]
    with client.app.state.database.session_factory() as session:
        session.get(Memo, memo_id).resource_ai_assessment = uncertain_assessment(
            category["code"]
        )
        session.commit()
    client.patch(
        f"/api/v1/resource-categories/{category['id']}",
        json={
            "expected_version": category["version"],
            "name": "当前名称",
            "is_active": False,
        },
    ).raise_for_status()
    candidate = client.get(REVIEW_URL).json()["items"][0]["candidates"][0]
    assert candidate["label"] == "当前名称" and candidate["available"] is False
    result = client.post(
        f"{REVIEW_URL}/confirm",
        json={
            "action": "adopt",
            "items": [selection(client, memo_id)],
        },
    ).json()
    assert result["results"][0]["reason"] == "category_unavailable"
    assert (
        client.post(
            f"{REVIEW_URL}/confirm",
            json={
                "action": "assign",
                "category_code": category["code"],
                "items": [selection(client, memo_id)],
            },
        ).status_code
        == 400
    )


def test_review_account_isolation_and_authentication(client: TestClient) -> None:
    """其他账号不能看到、确认本人条目或使用本人的私人模板。"""

    memo_id = seed_reviews(client)[0]
    category = client.post(
        "/api/v1/resource-categories", json={"name": "个人分类"}
    ).json()
    item = selection(client, memo_id)
    settings = client.app.state.settings
    with client.app.state.database.session_factory() as session:
        own = create_dev_session(session, settings).token
        other = create_dev_session(
            session, replace(settings, local_user_id=str(uuid4()))
        ).token
    client.app.state.settings = replace(settings, auth_dev_mode=False)
    assert client.get(REVIEW_URL).status_code == 401
    assert client.post(f"{REVIEW_URL}/retry").status_code == 401
    assert (
        client.post(
            f"{REVIEW_URL}/confirm", json={"action": "keep", "items": [item]}
        ).status_code
        == 401
    )
    headers = {"Authorization": f"Bearer {other}"}
    assert client.get(REVIEW_URL, headers=headers).json()["total_count"] == 0
    result = client.post(
        f"{REVIEW_URL}/confirm",
        headers=headers,
        json={
            "action": "keep",
            "items": [item],
        },
    ).json()
    assert result["results"][0]["reason"] == "missing"
    assert (
        client.post(
            f"{REVIEW_URL}/confirm",
            headers=headers,
            json={
                "action": "assign",
                "category_code": category["code"],
                "items": [item],
            },
        ).status_code
        == 400
    )
    assert (
        client.get(REVIEW_URL, headers={"Authorization": f"Bearer {own}"}).json()[
            "total_count"
        ]
        == 1
    )
    retry = client.post(
        f"{REVIEW_URL}/retry",
        headers={"Authorization": f"Bearer {other}"},
    )
    assert retry.status_code == 202
    assert retry.json()["review_count"] == 0
    assert (
        client.get(REVIEW_URL, headers={"Authorization": f"Bearer {own}"}).json()[
            "total_count"
        ]
        == 1
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"action": "assign"},
        {"action": "keep", "category_code": "tool"},
        {"action": "unexpected"},
        {"action": "keep", "items": []},
        {"action": "keep", "duplicate": True},
    ],
)
def test_invalid_confirmation_payload_is_rejected(
    client: TestClient,
    payload: dict[str, object],
) -> None:
    """请求字段不符合操作要求时不产生任何确认。"""

    memo_id = seed_reviews(client)[0]
    item = selection(client, memo_id)
    data = {"items": [item], **payload}
    if data.pop("duplicate", False):
        data["items"] = [item, item]
    assert client.post(f"{REVIEW_URL}/confirm", json=data).status_code == 422
    assert client.get(REVIEW_URL).json()["total_count"] == 1


@pytest.mark.parametrize(
    "change",
    [
        {"source_url": "https://example.com/new-page"},
        {"resource_categories": ["article"]},
        {"type": "idea"},
    ],
)
def test_explicit_edit_resets_confirmation(
    client: TestClient,
    change: dict[str, object],
) -> None:
    """更换网址、条目类型或手动改分类后不沿用旧确认依据。"""

    memo_id = seed_reviews(client)[0]
    client.post(
        f"{REVIEW_URL}/confirm",
        json={
            "action": "keep",
            "items": [selection(client, memo_id)],
        },
    ).raise_for_status()
    current = client.get(f"/api/v1/memos/{memo_id}").json()
    response = client.patch(
        f"/api/v1/memos/{memo_id}",
        json={
            "expected_version": current["version"],
            **change,
        },
    )
    assert response.status_code == 200
    assert response.json()["resource_ai_confirmation"] is None
    assert response.json()["resource_ai_confirmation_pending"] is False


def test_model_response_cannot_overwrite_intervening_confirmation(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """模型请求途中用户保留分类，晚到响应不能覆盖决策或计为成功。"""

    memo_id = seed_reviews(client)[0]
    configure_jev(client)
    client.post("/api/v1/resource-classification").raise_for_status()

    def classify(
        _metadata: ResourceMetadata, *_args: object, **_kwargs: object
    ) -> CategoryDecision:
        """模型返回之前通过独立事务完成用户确认。"""

        result = client.post(
            f"{REVIEW_URL}/confirm",
            json={
                "action": "keep",
                "items": [selection(client, memo_id)],
            },
        )
        assert result.json()["updated_count"] == 1
        return CategoryDecision("learning", "学习资料", 0.9, "jev", ())

    patch_web_classifier(monkeypatch, classify)
    settings = client.app.state.settings
    run_pending_classification_jobs(settings.database_url, settings)
    memo = client.get(f"/api/v1/memos/{memo_id}").json()
    assert memo["resource_category"] == "tool"
    assert memo["resource_ai_confirmation"]["action"] == "keep"
    job = client.get("/api/v1/resource-classification").json()["job"]
    assert job["skipped_count"] == 1 and job["succeeded_count"] == 0


@pytest.mark.parametrize("stage", ["fetch", "classify", "model"])
def test_enrichment_cannot_overwrite_intervening_confirmation(
    client: TestClient,
    stage: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """单页刷新途中完成确认，晚到的正文和分类不能覆盖用户所见版本。"""

    memo_id = seed_reviews(client)[0]
    settings = client.app.state.settings
    confirmed_version = 0

    def confirm() -> None:
        """在独立接口事务确认当前版本，模拟请求期间的用户操作。"""

        nonlocal confirmed_version
        item = selection(client, memo_id)
        result = client.post(
            f"{REVIEW_URL}/confirm",
            json={
                "action": "keep",
                "items": [item],
            },
        )
        assert result.json()["updated_count"] == 1
        confirmed_version = int(item["expected_version"]) + 1

    def fetch(url: str) -> ResourceMetadata:
        """公开网页返回之前可发生确认。"""

        if stage == "fetch":
            confirm()
        return ResourceMetadata(url, "刷新得到的标题", "公开内容描述", None, None, 200)

    def classify(_metadata: ResourceMetadata) -> CategoryDecision:
        """单页模型响应返回之前可发生确认。"""

        if stage in {"classify", "model"}:
            confirm()
        return CategoryDecision("learning", "学习资料", 0.9, "jev", ())

    def automatic_classifier(
        metadata: ResourceMetadata,
        **kwargs: object,
    ) -> CategoryDecision:
        """实际配置读取链路也不能在等待模型时锁住用户确认事务。"""

        assert kwargs["jev_api_key"] == "review-test-fake-key"
        return classify(metadata)

    if stage == "model":
        configure_jev(client)
        monkeypatch.setattr(
            "app.resource_service.classify_resource", automatic_classifier
        )

    with client.app.state.database.session_factory() as session:
        enriched = enrich_resource(
            session,
            settings.local_user_id,
            memo_id,
            settings,
            metadata_fetcher=fetch,
            classifier=None if stage == "model" else classify,
        )
        assert enriched.resource_ai_confirmation["action"] == "keep"
        assert enriched.resource_category == "tool"
        assert enriched.resource_categories == ["tool", "article"]
        assert enriched.resource_ai_classified_at is None
        assert enriched.version == confirmed_version


def test_review_migration_recovers_only_attempted_eligible_legacy_rows(
    client: TestClient,
) -> None:
    """旧队列未确定条目进入复核，完成标记、未处理网页及原进度保留。"""

    ids = seed_reviews(client, 5, legacy=True)
    configure_jev(client)
    database = client.app.state.database
    settings = client.app.state.settings
    with database.session_factory() as session:
        job = start_classification_job(session, settings.local_user_id, settings)
        job.memo_ids = ids
        job.total_count = 5
        job.processed_count = 4
        job.succeeded_count = 1
        job.failed_count = 3
        session.get(Memo, ids[0]).resource_ai_classified_at = datetime.now(UTC)
        session.get(Memo, ids[2]).link_health_status = "failed"
        session.get(Memo, ids[2]).resource_ai_review_required = True
        session.get(Memo, ids[3]).resource_category_source = "manual"
        session.commit()
        job_id = job.id
    with database.engine.begin() as connection:
        for column in ("resource_ai_confirmation", "resource_ai_confirmation_pending"):
            connection.exec_driver_sql(f"ALTER TABLE memo DROP COLUMN {column}")
    database.create_schema()
    database.create_schema()
    data = client.get(REVIEW_URL).json()
    assert [item["id"] for item in data["items"]] == [ids[1]]
    assert data["items"][0]["assessment"] is None
    with database.session_factory() as session:
        job = session.get(ResourceClassificationJob, settings.local_user_id)
        assert job.id == job_id
        assert job.memo_ids == ids and job.processed_count == 4
        assert job.succeeded_count == 1 and job.failed_count == 3
        assert session.get(Memo, ids[0]).resource_ai_classified_at is not None
        assert not session.get(Memo, ids[4]).resource_ai_confirmation_pending
    client.post(
        f"{REVIEW_URL}/confirm",
        json={
            "action": "keep",
            "items": [selection(client, ids[1])],
        },
    ).raise_for_status()
    database.create_schema()
    assert client.get(REVIEW_URL).json()["total_count"] == 0
    assert (
        client.get(f"/api/v1/memos/{ids[1]}").json()["resource_ai_confirmation"][
            "action"
        ]
        == "keep"
    )


def test_retry_reviews_queues_only_pending_confirmations(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """重新分类只排队待确认网页，保留原分类直到模型给出新结果。"""

    review_ids = seed_reviews(client, 2)
    confirmed_id = seed_reviews(client)[0]
    pending_id = seed_pending_resource(client)
    client.post(
        f"{REVIEW_URL}/confirm",
        json={"action": "keep", "items": [selection(client, confirmed_id)]},
    ).raise_for_status()
    before = [client.get(f"/api/v1/memos/{memo_id}").json() for memo_id in review_ids]
    configure_jev(client)
    calls: list[str | None] = []

    def classify(metadata: ResourceMetadata, *_args: object) -> CategoryDecision:
        """待确认网页改为学习资料，证明队列确实再次请求模型。"""

        calls.append(metadata.page_title)
        return CategoryDecision("learning", "学习资料", 0.9, "jev", ("学习资料",))

    patch_web_classifier(monkeypatch, classify)
    response = client.post(f"{REVIEW_URL}/retry")
    assert response.status_code == 202
    state = response.json()
    assert state["review_count"] == 0
    assert state["job"]["total_count"] == 2
    assert state["job"]["processed_count"] == 0
    assert state["job"]["status"] == "pending"
    with client.app.state.database.session_factory() as session:
        job = session.get(
            ResourceClassificationJob, client.app.state.settings.local_user_id
        )
        assert set(job.memo_ids) == set(review_ids)
        assert pending_id not in job.memo_ids
        assert confirmed_id not in job.memo_ids
    for memo_id, snapshot in zip(review_ids, before, strict=True):
        current = client.get(f"/api/v1/memos/{memo_id}").json()
        assert current["resource_ai_confirmation_pending"] is False
        assert current["resource_category"] == snapshot["resource_category"]
        assert current["resource_categories"] == snapshot["resource_categories"]
        assert current["resource_category_source"] == "rule"
        assert current["resource_ai_classified_at"] is None
        assert current["version"] == snapshot["version"]
    settings = client.app.state.settings
    assert run_pending_classification_jobs(settings.database_url, settings) == 2
    assert sorted(calls) == ["复核网页 0", "复核网页 1"]
    for memo_id in review_ids:
        memo = client.get(f"/api/v1/memos/{memo_id}").json()
        assert memo["resource_category"] == "learning"
        assert memo["resource_category_source"] == "jev"
        assert memo["resource_ai_classified_at"] is not None
        assert memo["resource_ai_confirmation_pending"] is False
    pending = client.get(f"/api/v1/memos/{pending_id}").json()
    assert pending["resource_category_source"] == "fallback"
    assert pending["resource_ai_classified_at"] is None
    confirmed = client.get(f"/api/v1/memos/{confirmed_id}").json()
    assert confirmed["resource_ai_confirmation"]["action"] == "keep"
    assert client.get("/api/v1/resource-classification").json()["review_count"] == 0


def test_retry_reviews_requires_model_and_rejects_active_job(
    client: TestClient,
) -> None:
    """未配置模型时不改队列；任务进行中拒绝重新分类待确认网页。"""

    review_id = seed_reviews(client)[0]
    missing = client.post(f"{REVIEW_URL}/retry")
    assert missing.status_code == 400
    assert "配置并启用 DeepSeek 或 Jev" in missing.json()["detail"]
    assert client.get(REVIEW_URL).json()["total_count"] == 1
    configure_jev(client)
    seed_pending_resource(client)
    started = client.post("/api/v1/resource-classification")
    assert started.status_code == 202
    assert started.json()["job"]["status"] in {"pending", "processing"}
    blocked = client.post(f"{REVIEW_URL}/retry")
    assert blocked.status_code == 409
    assert "还在进行" in blocked.json()["detail"]
    assert client.get(REVIEW_URL).json()["items"][0]["id"] == review_id


def test_retry_reviews_replaces_failed_job_instead_of_resuming(
    client: TestClient,
) -> None:
    """暂停任务再跑待确认时新建队列，不继续原游标里已失败的条目。"""

    review_ids = seed_reviews(client, 2)
    pending_id = seed_pending_resource(client)
    configure_jev(client)
    settings = client.app.state.settings
    with client.app.state.database.session_factory() as session:
        job = start_classification_job(session, settings.local_user_id, settings)
        original_id = job.id
        original_queue = list(job.memo_ids)
        job.status = "failed"
        job.processed_count = 2
        job.failed_count = 2
        session.commit()
    assert set(original_queue) == set([*review_ids, pending_id])
    response = client.post(f"{REVIEW_URL}/retry")
    assert response.status_code == 202
    replaced = response.json()["job"]
    assert replaced["id"] != original_id
    assert replaced["total_count"] == 2
    assert replaced["processed_count"] == replaced["failed_count"] == 0
    with client.app.state.database.session_factory() as session:
        job = session.get(ResourceClassificationJob, settings.local_user_id)
        assert job.id == replaced["id"]
        assert set(job.memo_ids) == set(review_ids)
        assert pending_id not in job.memo_ids


def test_retry_reviews_empty_queue_does_not_clobber_failed_job(
    client: TestClient,
) -> None:
    """没有待确认网页时保持可继续的暂停任务。"""

    pending_id = seed_pending_resource(client)
    configure_jev(client)
    settings = client.app.state.settings
    with client.app.state.database.session_factory() as session:
        job = start_classification_job(session, settings.local_user_id, settings)
        original_id = job.id
        job.status = "failed"
        job.processed_count = 0
        session.commit()
    empty = client.post(f"{REVIEW_URL}/retry")
    assert empty.status_code == 202
    assert empty.json()["job"]["id"] == original_id
    assert empty.json()["job"]["status"] == "failed"
    assert empty.json()["review_count"] == 0
    none = client.post(f"{REVIEW_URL}/retry")
    # 第二次仍是同一暂停任务，不会改成空的已完成任务。
    assert none.json()["job"]["id"] == original_id
    with client.app.state.database.session_factory() as session:
        job = session.get(ResourceClassificationJob, settings.local_user_id)
        assert job.memo_ids == [pending_id]


def test_retry_reviews_empty_without_job_returns_completed_state(
    client: TestClient,
) -> None:
    """没有任务也没有待确认网页时返回空的已完成进度。"""

    response = client.post(f"{REVIEW_URL}/retry")
    assert response.status_code == 202
    state = response.json()
    assert state["review_count"] == 0
    assert state["job"]["total_count"] == 0
    assert state["job"]["status"] == "completed"
