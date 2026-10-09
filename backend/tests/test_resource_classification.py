"""批量网页模型分类的完成标记、恢复、账号隔离和并发保护测试。"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from uuid import uuid4

import httpx
import pytest
from app.auth_service import create_dev_session
from app.category_service import classification_categories
from app.link_health_service import check_resource_link
from app.models import Memo, ResourceClassificationJob
from app.resource_classification_policy import apply_classification_health_gate
from app.resource_classification_quality import (
    UncertainClassificationError,
    parse_jev_assessment,
)
from app.resource_classification_retry import ClassificationServiceFailure
from app.resource_classification_service import (
    classification_state,
    process_classification_job,
    queue_automatic_classifications,
    record_service_failure,
    resume_classification_job,
    run_pending_classification_jobs,
    start_classification_job,
)
from app.resource_processing import (
    CategoryDecision,
    ResourceFetchError,
    ResourceMetadata,
    UnsafeResourceUrlError,
    classify_resource_with_jev,
)
from app.resource_service import (
    apply_category,
    enrich_resource,
    reclassify_user_rule_resources,
)
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def pause_automatic_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    """测试由显式调用控制进度，避免后台线程访问真实模型服务。"""

    async def idle(
        _database_url: str,
        _settings: object,
        stop_event: asyncio.Event,
    ) -> None:
        """保持生命周期结构，在测试退出时立即结束。"""

        await stop_event.wait()

    monkeypatch.setattr("app.main.resource_classification_loop", idle)


def create_resource(client: TestClient, title: str = "测试网页") -> str:
    """通过真实 API 创建当前账号的独立网页收藏。"""

    response = client.post(
        "/api/v1/memos",
        json={
            "client_id": str(uuid4()),
            "type": "resource",
            "title": title,
            "body": "用户的私人备注不会发送给模型",
            "source_url": f"https://example.com/{uuid4().hex}",
        },
    )
    assert response.status_code == 201
    memo_id = response.json()["id"]
    with client.app.state.database.session_factory() as session:
        # 已有网页测试使用抓取成功的条目，新导入的未巡检情形另行验证。
        memo = session.get(Memo, memo_id)
        memo.link_health_status = "healthy"
        memo.resource_metadata_status = "ready"
        session.commit()
    return memo_id


def configure_jev(client: TestClient) -> None:
    """保存模拟账号模型配置，测试不包含真实凭据。"""

    assert (
        client.put(
            "/api/v1/model-settings/jev",
            json={
                "model": "typesafe/jev",
                "api_key": "test-batch-classification-key",
                "base_url": "https://relay.example/v1",
            },
        ).status_code
        == 200
    )


def tool_decision() -> CategoryDecision:
    """返回模型成功选择已有模板的结果。"""

    return CategoryDecision("tool", "工具与服务", 0.9, "jev", ("工具",))


def test_jev_classification_accepts_relay_slower_than_eight_seconds(
    client: TestClient,
) -> None:
    """模拟实际中转超过八秒的有效响应，避免误判服务不可用。"""

    settings = client.app.state.settings
    with client.app.state.database.session_factory() as session:
        categories = classification_categories(session, settings.local_user_id)

    def respond(request: httpx.Request) -> httpx.Response:
        """根据请求超时模拟中转九秒后响应，不让测试实际等待九秒。"""

        if request.extensions["timeout"]["read"] < 9.0:
            raise httpx.ReadTimeout("slow_relay", request=request)
        return httpx.Response(
            200,
            json={
                "answers": {
                    "category": {
                        "choice": categories[0].code,
                        "confidence": 0.9,
                    }
                },
            },
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as model_client:
        decision = classify_resource_with_jev(
            ResourceMetadata(
                "https://example.com",
                "验收网页",
                None,
                "Example",
                None,
                200,
            ),
            categories,
            "test-key",
            "https://relay.example/v1",
            "typesafe/jev",
            0.7,
            client=model_client,
        )
    assert decision.source == "jev"


@pytest.mark.parametrize("health_status", ["failed", "healthy"])
def test_rule_removal_does_not_send_review_held_pages_to_models(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    health_status: str,
) -> None:
    """规则删除后仍等待人工确认，后台恢复正常也不能绕过准入限制。"""

    configure_jev(client)
    memo_id = create_resource(client)
    calls: list[str] = []

    def classify(metadata: ResourceMetadata, **kwargs: object) -> CategoryDecision:
        """保留本地分类回退，同时验证两个模型均未收到调用凭证。"""

        assert kwargs["jev_api_key"] is None
        assert kwargs["llm_api_key"] is None
        calls.append(metadata.final_url)
        return CategoryDecision("article", "文章", 0.5, "rule", ())

    monkeypatch.setattr("app.resource_service.classify_resource", classify)
    with client.app.state.database.session_factory() as session:
        memo = session.get(Memo, memo_id)
        memo.resource_category_source = "user_rule"
        memo.link_health_status = health_status
        memo.resource_ai_review_required = True
        session.commit()
        reclassify_user_rule_resources(
            session,
            client.app.state.settings.local_user_id,
            client.app.state.settings,
        )
        assert memo.resource_ai_classified_at is None
        assert memo.resource_ai_review_required is True
    assert len(calls) == 1


def test_batch_processes_rules_once_and_skips_completed(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """已有规则结果仍进入模型，成功后新任务不再发送这些网页。"""

    configure_jev(client)
    memo_ids = [create_resource(client, name) for name in ("工具主页", "资料主页")]
    settings = client.app.state.settings
    with client.app.state.database.session_factory() as session:
        for memo_id in memo_ids:
            memo = session.get(Memo, memo_id)
            assert memo is not None
            memo.resource_category_source = "rule"
        session.commit()
    calls: list[ResourceMetadata] = []

    def classify(metadata: ResourceMetadata, *args: object) -> CategoryDecision:
        """验证使用账号中转配置，只发送网页允许的元数据。"""

        assert args[1:4] == (
            "test-batch-classification-key",
            "https://relay.example/v1",
            "typesafe/jev",
        )
        assert not hasattr(metadata, "body")
        calls.append(metadata)
        return tool_decision()

    monkeypatch.setattr(
        "app.resource_classification_service.classify_resource_with_jev",
        classify,
    )
    first = client.post("/api/v1/resource-classification")
    assert first.status_code == 202
    first_id = first.json()["job"]["id"]
    repeated = client.post("/api/v1/resource-classification")
    assert repeated.json()["job"]["id"] == first_id
    with client.app.state.database.session_factory() as session:
        assert (
            process_classification_job(session, settings.local_user_id, settings) == 2
        )
    state = client.get("/api/v1/resource-classification").json()
    assert state["pending_count"] == 0
    assert state["classified_count"] == 2
    assert state["job"]["succeeded_count"] == 2
    assert state["job"]["status"] == "completed"
    assert "memo_ids" not in state["job"]
    for memo_id in memo_ids:
        memo = client.get(f"/api/v1/memos/{memo_id}").json()
        assert memo["resource_category_source"] == "jev"
        assert memo["resource_ai_classified_at"] is not None
    client.post("/api/v1/resource-classification")
    with client.app.state.database.session_factory() as session:
        assert (
            process_classification_job(session, settings.local_user_id, settings) == 0
        )
    assert len(calls) == 2


@pytest.mark.parametrize("source", ["manual", "user_rule", "jev", "llm"])
def test_preserves_protected_and_legacy_ai_categories(
    client: TestClient,
    source: str,
) -> None:
    """手动与用户规则分类保留，旧版模型结果即使缺少时间标记也跳过。"""

    memo_id = create_resource(client)
    with client.app.state.database.session_factory() as session:
        memo = session.get(Memo, memo_id)
        assert memo is not None
        memo.resource_category_source = source
        memo.resource_category = "article"
        session.commit()
    state = client.post("/api/v1/resource-classification").json()
    assert state["pending_count"] == 0
    assert state["job"]["total_count"] == 0
    assert state["job"]["status"] == "completed"
    assert (
        client.get(f"/api/v1/memos/{memo_id}").json()["resource_category"] == "article"
    )


def test_requires_jev_and_does_not_fallback_to_rules(client: TestClient) -> None:
    """模型不可用时不能把规则处理算成大模型分类完成。"""

    memo_id = create_resource(client)
    response = client.post("/api/v1/resource-classification")
    assert response.status_code == 400
    assert "配置并启用 Jev" in response.json()["detail"]
    assert (
        client.get(f"/api/v1/memos/{memo_id}").json()["resource_ai_classified_at"]
        is None
    )


def test_uncertain_result_remains_retryable_without_repeating_success(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """低置信度保留原结果，下次仅重试失败条目。"""

    configure_jev(client)
    create_resource(client, "明确网页")
    uncertain_id = create_resource(client, "不确定网页")
    calls: list[str | None] = []
    first_run = True

    def classify(metadata: ResourceMetadata, *_args: object) -> CategoryDecision:
        """第一次模糊条目失败，第二次得到可接受分类。"""

        calls.append(metadata.page_title)
        if first_run and metadata.page_title == "不确定网页":
            raise ValueError("uncertain_or_invalid_jev_category")
        return tool_decision()

    monkeypatch.setattr(
        "app.resource_classification_service.classify_resource_with_jev",
        classify,
    )
    settings = client.app.state.settings
    with client.app.state.database.session_factory() as session:
        start_classification_job(session, settings.local_user_id, settings)
        process_classification_job(session, settings.local_user_id, settings)
        state = classification_state(session, settings.local_user_id)
        assert state.job is not None
        assert state.job.failed_count == 1
        assert state.pending_count == 1
        assert session.get(Memo, uncertain_id).resource_ai_classified_at is None
    first_run = False
    with client.app.state.database.session_factory() as session:
        job = start_classification_job(session, settings.local_user_id, settings)
        assert job.total_count == 1
        assert (
            process_classification_job(session, settings.local_user_id, settings) == 1
        )
    assert calls.count("明确网页") == 1
    assert calls.count("不确定网页") == 2


@pytest.mark.parametrize("status", [400, 401, 402, 403, 404, 422, 501])
def test_service_failure_stops_batch_and_hides_secrets(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    status: int,
) -> None:
    """服务级故障暂停整批，避免为其余条目反复发出失败请求。"""

    configure_jev(client)
    for _index in range(3):
        create_resource(client)
    calls = 0

    def classify(_metadata: ResourceMetadata, *_args: object) -> CategoryDecision:
        """上游故意包含凭据信息，用户可见错误必须隐藏原文。"""

        nonlocal calls
        calls += 1
        request = httpx.Request("POST", "https://relay.example/v1/systemone")
        response = httpx.Response(status, request=request, text="private-upstream-key")
        raise httpx.HTTPStatusError(
            "private-upstream-key", request=request, response=response
        )

    monkeypatch.setattr(
        "app.resource_classification_service.classify_resource_with_jev",
        classify,
    )
    settings = client.app.state.settings
    with client.app.state.database.session_factory() as session:
        start_classification_job(session, settings.local_user_id, settings)
        assert (
            process_classification_job(session, settings.local_user_id, settings) == 0
        )
    response = client.get("/api/v1/resource-classification")
    assert response.json()["job"]["status"] == "failed"
    assert response.json()["pending_count"] == 3
    assert "private-upstream-key" not in response.text
    assert calls == 1


def test_resume_preserves_progress_and_does_not_repeat_processed_items(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """模拟进程退出后用新会话恢复，完成时间与进度共同保留。"""

    configure_jev(client)
    for _index in range(2):
        create_resource(client)
    stopped = False
    calls = 0

    def classify(_metadata: ResourceMetadata, *_args: object) -> CategoryDecision:
        """第一次成功后触发退出，供后续会话恢复。"""

        nonlocal stopped, calls
        calls += 1
        stopped = True
        return tool_decision()

    def should_stop() -> bool:
        """反映服务的退出事件。"""

        return stopped

    monkeypatch.setattr(
        "app.resource_classification_service.classify_resource_with_jev",
        classify,
    )
    settings = client.app.state.settings
    with client.app.state.database.session_factory() as session:
        start_classification_job(session, settings.local_user_id, settings)
        assert (
            process_classification_job(
                session, settings.local_user_id, settings, should_stop
            )
            == 1
        )
        job = session.get(ResourceClassificationJob, settings.local_user_id)
        assert job.status == "pending"
        assert job.processed_count == 1
        # 模拟非正常退出时遗留的过期租约。
        job.status = "processing"
        job.worker_token = "old-worker"
        job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()
    with client.app.state.database.session_factory() as session:
        assert (
            process_classification_job(session, settings.local_user_id, settings) == 1
        )
        state = classification_state(session, settings.local_user_id)
        assert state.job.status == "completed"
        assert state.job.succeeded_count == 2
    assert calls == 2


def test_active_worker_lease_prevents_duplicate_model_requests(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """另一工作线程不能在模型请求进行中领取相同任务。"""

    configure_jev(client)
    create_resource(client)
    settings = client.app.state.settings
    calls = 0

    def classify(_metadata: ResourceMetadata, *_args: object) -> CategoryDecision:
        """模型响应前让另一个会话尝试恢复同一任务。"""

        nonlocal calls
        calls += 1
        with client.app.state.database.session_factory() as other:
            assert (
                process_classification_job(other, settings.local_user_id, settings) == 0
            )
        return tool_decision()

    monkeypatch.setattr(
        "app.resource_classification_service.classify_resource_with_jev",
        classify,
    )
    with client.app.state.database.session_factory() as session:
        start_classification_job(session, settings.local_user_id, settings)
        assert (
            process_classification_job(session, settings.local_user_id, settings) == 1
        )
    assert calls == 1


def test_manual_edit_during_model_request_is_not_overwritten(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """模型请求期间用户的手动修改通过乐观锁保护。"""

    configure_jev(client)
    memo_id = create_resource(client)
    settings = client.app.state.settings

    def classify(_metadata: ResourceMetadata, *_args: object) -> CategoryDecision:
        """模拟用户在等待推理时把网页改为文章类。"""

        with client.app.state.database.session_factory() as other:
            memo = other.get(Memo, memo_id)
            memo.resource_category = "article"
            memo.resource_category_source = "manual"
            memo.version += 1
            other.commit()
        return tool_decision()

    monkeypatch.setattr(
        "app.resource_classification_service.classify_resource_with_jev",
        classify,
    )
    with client.app.state.database.session_factory() as session:
        start_classification_job(session, settings.local_user_id, settings)
        process_classification_job(session, settings.local_user_id, settings)
    memo = client.get(f"/api/v1/memos/{memo_id}").json()
    assert memo["resource_category"] == "article"
    assert memo["resource_category_source"] == "manual"
    assert memo["resource_ai_classified_at"] is None
    assert (
        client.get("/api/v1/resource-classification").json()["job"]["skipped_count"]
        == 1
    )


def test_job_and_resource_counts_are_isolated_by_account(client: TestClient) -> None:
    """真实登录账号不能读取或启动其他用户的网页任务。"""

    configure_jev(client)
    create_resource(client)
    settings = client.app.state.settings
    with client.app.state.database.session_factory() as session:
        own = create_dev_session(session, settings).token
        other = create_dev_session(
            session,
            replace(settings, local_user_id=str(uuid4())),
        ).token
        start_classification_job(session, settings.local_user_id, settings)
    client.app.state.settings = replace(settings, auth_dev_mode=False)
    assert client.get("/api/v1/resource-classification").status_code == 401
    assert client.post("/api/v1/resource-classification").status_code == 401
    other_headers = {"Authorization": f"Bearer {other}"}
    other_state = client.get(
        "/api/v1/resource-classification", headers=other_headers
    ).json()
    assert other_state["pending_count"] == 0
    assert other_state["job"] is None
    client.post("/api/v1/resource-classification", headers=other_headers)
    own_state = client.get(
        "/api/v1/resource-classification",
        headers={"Authorization": f"Bearer {own}"},
    ).json()
    assert own_state["pending_count"] == 1
    assert own_state["job"]["total_count"] == 1


@pytest.mark.parametrize("source", ["rule", "fallback", "jev", "llm"])
def test_regular_enrichment_marks_only_successful_ai_results(
    client: TestClient,
    source: str,
) -> None:
    """正常网页处理也记录完成时间，规则回退不算大模型已处理。"""

    memo_id = create_resource(client)
    with client.app.state.database.session_factory() as session:
        memo = session.get(Memo, memo_id)
        apply_category(memo, replace(tool_decision(), source=source))
        session.commit()
        assert (memo.resource_ai_classified_at is not None) == (
            source in {"jev", "llm"}
        )


def test_trash_ebooks_and_other_memo_types_do_not_enter_queue(
    client: TestClient,
) -> None:
    """全部网页不包含已删除资料、云盘电子书和其他收藏类型。"""

    excluded = [create_resource(client) for _index in range(4)]
    with client.app.state.database.session_factory() as session:
        session.get(Memo, excluded[0]).status = "trashed"
        session.get(Memo, excluded[1]).ebook_provider = "aliyun"
        session.get(Memo, excluded[2]).type = "idea"
        session.get(Memo, excluded[3]).source_url = None
        session.commit()
    state = client.get("/api/v1/resource-classification").json()
    assert state["pending_count"] == 0
    assert state["classified_count"] == 0


def test_url_change_invalidates_previous_completion_marker(
    client: TestClient,
) -> None:
    """网址替换后是新的网页，需要允许其重新进行模型分类。"""

    memo_id = create_resource(client)
    with client.app.state.database.session_factory() as session:
        memo = session.get(Memo, memo_id)
        apply_category(memo, tool_decision())
        session.commit()
    memo = client.get(f"/api/v1/memos/{memo_id}").json()
    response = client.patch(
        f"/api/v1/memos/{memo_id}",
        json={
            "expected_version": memo["version"],
            "source_url": "https://example.com/a-new-webpage",
        },
    )
    assert response.status_code == 200
    assert response.json()["resource_ai_classified_at"] is None
    state = client.get("/api/v1/resource-classification").json()
    assert state["pending_count"] == 0
    assert state["deferred_count"] == 1


def test_sqlite_upgrade_backfills_existing_model_classification(
    client: TestClient,
) -> None:
    """旧库升级时补记已成功的模型结果，避免全部网页重新收费。"""

    memo_id = create_resource(client)
    database = client.app.state.database
    with database.session_factory() as session:
        memo = session.get(Memo, memo_id)
        memo.resource_category_source = "jev"
        session.commit()
    with database.engine.begin() as connection:
        connection.exec_driver_sql(
            "ALTER TABLE memo DROP COLUMN resource_ai_classified_at"
        )
    database.create_schema()
    with database.session_factory() as session:
        memo = session.get(Memo, memo_id)
        assert memo.resource_ai_classified_at == memo.updated_at
    database.create_schema()
    assert (
        client.get(f"/api/v1/memos/{memo_id}").json()["resource_ai_classified_at"]
        is not None
    )


@pytest.mark.parametrize(
    "health_status",
    [
        "failed",
        "redirected",
        "changed",
        "auth_required",
        "temporary_failure",
        "ignored",
        "unchecked",
    ],
)
def test_review_webpages_are_not_sent_to_model(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    health_status: str,
) -> None:
    """全部巡检待确认项被排除，不受巡检列表 200 条上限影响。"""

    memo_id = create_resource(client)
    with client.app.state.database.session_factory() as session:
        memo = session.get(Memo, memo_id)
        memo.link_health_status = health_status
        apply_classification_health_gate(memo)
        session.commit()
    response = client.post("/api/v1/resource-classification")
    assert response.status_code == 202
    state = response.json()
    assert state["pending_count"] == 0
    assert state["deferred_count"] == 1
    assert state["job"]["total_count"] == 0


def test_queued_webpage_is_skipped_when_health_changes(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """排队后才进入巡检中心的网页也不能调用模型。"""

    configure_jev(client)
    memo_id = create_resource(client)
    settings = client.app.state.settings
    calls = 0

    def classify(_metadata: ResourceMetadata, *_args: object) -> CategoryDecision:
        """记录任何意外发生的模型调用。"""

        nonlocal calls
        calls += 1
        return tool_decision()

    monkeypatch.setattr(
        "app.resource_classification_service.classify_resource_with_jev", classify
    )
    with client.app.state.database.session_factory() as session:
        start_classification_job(session, settings.local_user_id, settings)
        memo = session.get(Memo, memo_id)
        memo.link_health_status = "auth_required"
        apply_classification_health_gate(memo)
        session.commit()
        process_classification_job(session, settings.local_user_id, settings)
        assert (
            session.get(ResourceClassificationJob, settings.local_user_id).skipped_count
            == 1
        )
        assert session.get(Memo, memo_id).resource_ai_classified_at is None
    assert calls == 0


def test_automatic_recovery_still_requires_manual_confirmation(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """后台巡检恢复正常不能自动分类；明确人工确认后才自动排队。"""

    configure_jev(client)
    memo_id = create_resource(client)
    settings = client.app.state.settings

    def fetch(url: str) -> ResourceMetadata:
        """提供不发生重定向且元数据稳定的成功巡检结果。"""

        return ResourceMetadata(url, "可保留的网页", "公开描述", "Example", None, 200)

    def classify(_metadata: ResourceMetadata, *_args: object) -> CategoryDecision:
        """人工确认后模拟有效的模型分类。"""

        return tool_decision()

    monkeypatch.setattr(
        "app.resource_classification_service.classify_resource_with_jev", classify
    )
    with client.app.state.database.session_factory() as session:
        memo = session.get(Memo, memo_id)
        memo.link_health_status = "temporary_failure"
        apply_classification_health_gate(memo)
        session.commit()
        memo = check_resource_link(
            session, settings.local_user_id, memo_id, settings, fetcher=fetch
        )
        assert memo.link_health_status == "healthy"
        assert memo.resource_ai_review_required is True
        assert queue_automatic_classifications(session, settings) == 0
        center = client.get("/api/v1/resources/link-health").json()
        assert center["counts"]["review_pending"] == 1
        assert [item["id"] for item in center["items"]] == [memo_id]
        assert center["items"][0]["resource_ai_review_required"] is True
        memo = check_resource_link(
            session,
            settings.local_user_id,
            memo_id,
            settings,
            fetcher=fetch,
            force=True,
            review_confirmed=True,
        )
        assert memo.resource_ai_review_required is False
        assert client.get("/api/v1/resources/link-health").json()["items"] == []
        assert queue_automatic_classifications(session, settings) == 1
        process_classification_job(session, settings.local_user_id, settings)
        assert session.get(Memo, memo_id).resource_ai_classified_at is not None


def test_health_change_during_inference_prevents_category_write(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """推理期间发现巡检异常，提交结果时也必须再次遵守确认门槛。"""

    configure_jev(client)
    memo_id = create_resource(client)
    settings = client.app.state.settings

    def classify(_metadata: ResourceMetadata, *_args: object) -> CategoryDecision:
        """模拟正在推理的网页刚刚被巡检识别为失效。"""

        with client.app.state.database.session_factory() as other:
            memo = other.get(Memo, memo_id)
            memo.link_health_status = "failed"
            apply_classification_health_gate(memo)
            other.commit()
        return tool_decision()

    monkeypatch.setattr(
        "app.resource_classification_service.classify_resource_with_jev",
        classify,
    )
    with client.app.state.database.session_factory() as session:
        start_classification_job(session, settings.local_user_id, settings)
        process_classification_job(session, settings.local_user_id, settings)
        assert session.get(Memo, memo_id).resource_ai_classified_at is None
        assert (
            session.get(ResourceClassificationJob, settings.local_user_id).skipped_count
            == 1
        )


def test_review_schema_upgrade_holds_all_old_actionable_webpages(
    client: TestClient,
) -> None:
    """旧库升级后，待确认网页持续暂缓，原有任务默认仍为手动任务。"""

    memo_id = create_resource(client)
    database = client.app.state.database
    with database.session_factory() as session:
        session.get(Memo, memo_id).link_health_status = "failed"
        session.commit()
    with database.engine.begin() as connection:
        connection.exec_driver_sql(
            "ALTER TABLE memo DROP COLUMN resource_ai_review_required"
        )
        connection.exec_driver_sql(
            "ALTER TABLE resource_classification_job DROP COLUMN automatic"
        )
    database.create_schema()
    with database.session_factory() as session:
        assert session.get(Memo, memo_id).resource_ai_review_required is True
        assert (
            classification_state(
                session, client.app.state.settings.local_user_id
            ).pending_count
            == 0
        )
        # 已有字段但确认标记丢失时，重启也能按巡检事实修复。
        session.get(Memo, memo_id).resource_ai_review_required = False
        session.commit()
    database.create_schema()
    with database.session_factory() as session:
        assert session.get(Memo, memo_id).resource_ai_review_required is True


def test_new_imports_are_detected_and_classified_automatically(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """不点击批量按钮也会自动发现新网页，之后只处理新增加的条目。"""

    configure_jev(client)
    for _index in range(3):
        create_resource(client)
    calls = 0

    def classify(_metadata: ResourceMetadata, *_args: object) -> CategoryDecision:
        """统计后台自动分类的调用数量。"""

        nonlocal calls
        calls += 1
        return tool_decision()

    monkeypatch.setattr(
        "app.resource_classification_service.classify_resource_with_jev", classify
    )
    settings = client.app.state.settings
    assert client.get("/api/v1/resource-classification").json()["job"] is None
    assert run_pending_classification_jobs(settings.database_url, settings) == 3
    state = client.get("/api/v1/resource-classification").json()
    assert state["job"]["automatic"] is True
    assert state["classified_count"] == 3
    assert run_pending_classification_jobs(settings.database_url, settings) == 0
    create_resource(client)
    assert run_pending_classification_jobs(settings.database_url, settings) == 1
    assert calls == 4


def test_uncertain_auto_classification_is_not_retried_in_a_loop(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """不确定网页不会被自动检测反复收费，仍允许用户手动重试。"""

    configure_jev(client)
    memo_id = create_resource(client)
    calls = 0

    def classify(_metadata: ResourceMetadata, *_args: object) -> CategoryDecision:
        """模拟置信度不足，原分类保持有效。"""

        nonlocal calls
        calls += 1
        raise ValueError("uncertain_or_invalid_jev_category")

    monkeypatch.setattr(
        "app.resource_classification_service.classify_resource_with_jev", classify
    )
    settings = client.app.state.settings
    assert run_pending_classification_jobs(settings.database_url, settings) == 1
    assert run_pending_classification_jobs(settings.database_url, settings) == 0
    with client.app.state.database.session_factory() as session:
        memo = session.get(Memo, memo_id)
        assert memo.resource_ai_auto_pending is False
        assert memo.resource_ai_classified_at is None
        start_classification_job(session, settings.local_user_id, settings)
        process_classification_job(session, settings.local_user_id, settings)
    assert calls == 2


def test_auto_queue_waits_when_provider_has_failed(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """模型服务故障后停止自动重试，避免每次后台轮询再次请求。"""

    configure_jev(client)
    create_resource(client)
    calls = 0

    def classify(_metadata: ResourceMetadata, *_args: object) -> CategoryDecision:
        """模拟凭据失效，自动轮询不能再次发送认证失败请求。"""

        nonlocal calls
        calls += 1
        request = httpx.Request("POST", "https://relay.example/v1/systemone")
        raise httpx.HTTPStatusError(
            "private-upstream-key",
            request=request,
            response=httpx.Response(401, request=request),
        )

    monkeypatch.setattr(
        "app.resource_classification_service.classify_resource_with_jev", classify
    )
    settings = client.app.state.settings
    run_pending_classification_jobs(settings.database_url, settings)
    run_pending_classification_jobs(settings.database_url, settings)
    assert calls == 1
    assert (
        client.get("/api/v1/resource-classification").json()["job"]["status"]
        == "failed"
    )


def make_retry_due(client: TestClient) -> None:
    """模拟等待时间已经过去，测试不实际休眠五秒或十五秒。"""

    with client.app.state.database.session_factory() as session:
        job = session.get(
            ResourceClassificationJob, client.app.state.settings.local_user_id
        )
        assert job.next_retry_at is not None
        job.next_retry_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()


@pytest.mark.parametrize("excerpt", ["公开的工具介绍和使用说明。", None])
def test_quality_content_is_cached_across_provider_retries(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    excerpt: str | None,
) -> None:
    """正文只补充一次；即使页面没有正文，服务重试也复用缓存。"""

    configure_jev(client)
    memo_id = create_resource(client)
    settings = replace(client.app.state.settings, resource_enrichment_enabled=True)
    fetch_calls = model_calls = 0

    def fetch(url: str, **kwargs: object) -> ResourceMetadata:
        """补充受限公开内容，记录抓取次数。"""

        nonlocal fetch_calls
        fetch_calls += 1
        assert kwargs["include_text_excerpt"] is True
        return ResourceMetadata(
            url, "公开网页", None, "Example", None, 200, text_excerpt=excerpt
        )

    def classify(metadata: ResourceMetadata, *_args: object) -> CategoryDecision:
        """首次服务超时，随后成功，所有请求使用相同公开内容。"""

        nonlocal model_calls
        model_calls += 1
        assert (metadata.text_excerpt or None) == excerpt
        if model_calls == 1:
            raise httpx.ReadTimeout("private-key")
        _, assessment = parse_jev_assessment(
            {
                "answers": {
                    "category": {
                        "choice": "tool",
                        "confidence": 0.95,
                    }
                }
            },
            {"tool": "工具与服务"},
            0.7,
            "typesafe/jev",
            bool(excerpt),
            excerpt,
        )
        return replace(tool_decision(), assessment=assessment)

    monkeypatch.setattr(
        "app.resource_classification_service.fetch_resource_metadata", fetch
    )
    monkeypatch.setattr(
        "app.resource_classification_service.classify_resource_with_jev", classify
    )
    assert run_pending_classification_jobs(settings.database_url, settings) == 0
    make_retry_due(client)
    assert run_pending_classification_jobs(settings.database_url, settings) == 1
    memo = client.get(f"/api/v1/memos/{memo_id}").json()
    assert fetch_calls == 1 and model_calls == 2
    assert memo["resource_text_excerpt"] == (excerpt or "")
    assert memo["resource_ai_assessment"]["status"] == "classified"
    assert memo["resource_ai_assessment"]["input_excerpt"] == excerpt
    assert memo["resource_ai_classified_at"] is not None
    assert run_pending_classification_jobs(settings.database_url, settings) == 0
    assert fetch_calls == 1 and model_calls == 2


def test_uncertain_quality_evidence_preserves_category_and_is_reset_on_url_change(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """候选与原因按账号保存，低置信度不改分类，换网址后清除旧依据。"""

    configure_jev(client)
    memo_id = create_resource(client)
    original = client.get(f"/api/v1/memos/{memo_id}").json()

    def classify(metadata: ResourceMetadata, *_args: object) -> CategoryDecision:
        """低置信度仍带有可供用户核对的模板候选。"""

        parse_jev_assessment(
            {
                "answers": {
                    "category": {
                        "choice": "tool",
                        "confidence": 0.4,
                        "probabilities": {"tool": 0.6, "article": 0.4},
                    }
                }
            },
            {"tool": "工具与服务", "article": "文章阅读"},
            0.7,
            "typesafe/jev",
            bool(metadata.text_excerpt),
            metadata.text_excerpt,
        )
        raise AssertionError("低置信度不得接受")

    monkeypatch.setattr(
        "app.resource_classification_service.classify_resource_with_jev", classify
    )
    settings = client.app.state.settings
    run_pending_classification_jobs(settings.database_url, settings)
    after = client.get(f"/api/v1/memos/{memo_id}").json()
    assert after["resource_category"] == original["resource_category"]
    assert after["resource_category_source"] == original["resource_category_source"]
    assert after["resource_ai_classified_at"] is None
    assert after["version"] > original["version"]
    assessment = after["resource_ai_assessment"]
    assert assessment["reason_code"] == "low_confidence"
    assert assessment["confidence"] == 0.4 and assessment["threshold"] == 0.7
    assert assessment["candidates"][0]["code"] == "tool"
    assert assessment["candidates"][0]["probability"] == 0.6
    response = client.patch(
        f"/api/v1/memos/{memo_id}",
        json={
            "expected_version": after["version"],
            "source_url": "https://example.com/new-page",
        },
    )
    assert response.status_code == 200
    assert response.json()["resource_ai_assessment"] is None
    assert response.json()["resource_text_excerpt"] is None


@pytest.mark.parametrize(
    "problem,status",
    [
        ("forbidden", "auth_required"),
        ("unavailable", "temporary_failure"),
        ("redirect", "redirected"),
        ("changed", "changed"),
        ("private", "temporary_failure"),
    ],
)
def test_quality_fetch_health_problem_defers_without_model_request(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    problem: str,
    status: str,
) -> None:
    """补正文发现新的巡检问题时排队待人工确认，绝不发送模型请求。"""

    configure_jev(client)
    memo_id = create_resource(client)
    settings = replace(client.app.state.settings, resource_enrichment_enabled=True)
    if problem == "changed":
        with client.app.state.database.session_factory() as session:
            session.get(
                Memo, memo_id
            ).link_metadata_fingerprint = "previous-fingerprint"
            session.commit()

    def fetch(url: str, **_kwargs: object) -> ResourceMetadata:
        """返回可重现的网络、跳转或内容变化情形。"""

        if problem == "forbidden":
            raise ResourceFetchError("http_403", 403)
        if problem == "unavailable":
            raise ResourceFetchError("http_503", 503)
        if problem == "private":
            raise UnsafeResourceUrlError("non_public_ip")
        return ResourceMetadata(
            url + "/redirect" if problem == "redirect" else url,
            "新的内容",
            None,
            "Example",
            None,
            200,
            text_excerpt="公开正文",
        )

    def classify(_metadata: ResourceMetadata, *_args: object) -> CategoryDecision:
        """巡检尚未确认时调用模型属于错误。"""

        raise AssertionError("待巡检确认网页不能调用模型")

    monkeypatch.setattr(
        "app.resource_classification_service.fetch_resource_metadata", fetch
    )
    monkeypatch.setattr(
        "app.resource_classification_service.classify_resource_with_jev", classify
    )
    assert run_pending_classification_jobs(settings.database_url, settings) == 1
    after = client.get(f"/api/v1/memos/{memo_id}").json()
    assert after["link_health_status"] == status
    assert after["resource_ai_review_required"] is True
    assert after["resource_ai_classified_at"] is None
    state = client.get("/api/v1/resource-classification").json()
    assert state["deferred_count"] == 1
    assert state["job"]["skipped_count"] == 1
    assert state["job"]["failed_count"] == 0


def test_edit_during_content_fetch_cannot_attach_old_text_or_call_model(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """补正文期间更换网址，旧正文和旧分类都不得写入新页面。"""

    configure_jev(client)
    memo_id = create_resource(client)
    settings = replace(client.app.state.settings, resource_enrichment_enabled=True)

    def fetch(url: str, **_kwargs: object) -> ResourceMetadata:
        """模拟另一设备在网络等待期间更换网址。"""

        with client.app.state.database.session_factory() as other:
            memo = other.get(Memo, memo_id)
            memo.source_url = "https://example.com/replaced"
            memo.version += 1
            other.commit()
        return ResourceMetadata(
            url, "旧网页", None, "Example", None, 200, text_excerpt="旧网址正文不能写入"
        )

    def classify(_metadata: ResourceMetadata, *_args: object) -> CategoryDecision:
        """版本已改变后不得调用旧输入的模型。"""

        raise AssertionError("旧输入已失效")

    monkeypatch.setattr(
        "app.resource_classification_service.fetch_resource_metadata", fetch
    )
    monkeypatch.setattr(
        "app.resource_classification_service.classify_resource_with_jev", classify
    )
    run_pending_classification_jobs(settings.database_url, settings)
    after = client.get(f"/api/v1/memos/{memo_id}").json()
    assert after["source_url"] == "https://example.com/replaced"
    assert after["resource_text_excerpt"] is None
    assert after["resource_ai_assessment"] is None


def test_uncertain_result_after_manual_edit_is_skipped_not_saved(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """未确定结果也遵守版本检查，不覆盖人工分类或保存过期候选。"""

    configure_jev(client)
    memo_id = create_resource(client)

    def classify(_metadata: ResourceMetadata, *_args: object) -> CategoryDecision:
        """模拟模型等待期间的人工归类。"""

        with client.app.state.database.session_factory() as other:
            memo = other.get(Memo, memo_id)
            memo.resource_category = "article"
            memo.resource_category_source = "manual"
            memo.version += 1
            other.commit()
        parse_jev_assessment(
            {
                "answers": {
                    "category": {
                        "choice": "tool",
                        "confidence": 0.4,
                    }
                }
            },
            {"tool": "工具与服务"},
            0.7,
            "typesafe/jev",
            False,
        )
        raise AssertionError("低置信度不得接受")

    monkeypatch.setattr(
        "app.resource_classification_service.classify_resource_with_jev", classify
    )
    settings = client.app.state.settings
    run_pending_classification_jobs(settings.database_url, settings)
    after = client.get(f"/api/v1/memos/{memo_id}").json()
    assert after["resource_category"] == "article"
    assert after["resource_ai_assessment"] is None
    job = client.get("/api/v1/resource-classification").json()["job"]
    assert job["skipped_count"] == 1 and job["failed_count"] == 0


def test_quality_schema_upgrade_does_not_reclassify_completed_pages(
    client: TestClient,
) -> None:
    """原库补充证据字段不会清除完成标记、原分类或队列游标。"""

    configure_jev(client)
    memo_id = create_resource(client)
    database = client.app.state.database
    settings = client.app.state.settings
    with database.session_factory() as session:
        job = start_classification_job(session, settings.local_user_id, settings)
        job.status = "completed"
        job.processed_count = job.succeeded_count = 1
        memo = session.get(Memo, memo_id)
        memo.resource_ai_classified_at = datetime.now(UTC)
        memo.resource_category_source = "jev"
        memo.resource_category = "tool"
        session.commit()
        job_id, marker, version = job.id, memo.resource_ai_classified_at, memo.version
    with database.engine.begin() as connection:
        for column in ("resource_text_excerpt", "resource_ai_assessment"):
            connection.exec_driver_sql(f"ALTER TABLE memo DROP COLUMN {column}")
    database.create_schema()
    database.create_schema()
    with database.session_factory() as session:
        memo = session.get(Memo, memo_id)
        job = session.get(ResourceClassificationJob, settings.local_user_id)
        assert memo.resource_category == "tool"
        assert memo.resource_ai_classified_at.replace(tzinfo=UTC) == marker
        assert (
            memo.resource_ai_assessment is None and memo.resource_text_excerpt is None
        )
        assert memo.version == version
        assert job.id == job_id and job.processed_count == job.succeeded_count == 1
        assert classification_state(session, settings.local_user_id).pending_count == 0


def test_classification_criteria_distinguish_same_name_in_different_parents(
    client: TestClient,
) -> None:
    """同名子类别在模型模板中携带完整路径，避免只传相同的叶子名称。"""

    expected: dict[str, str] = {}
    for name in ("研发", "生活"):
        parent = client.post("/api/v1/resource-categories", json={"name": name})
        assert parent.status_code == 201
        child = client.post(
            "/api/v1/resource-categories",
            json={
                "name": "教程",
                "parent_code": parent.json()["code"],
            },
        )
        assert child.status_code == 201
        expected[child.json()["code"]] = f"{name} / 教程"
    with client.app.state.database.session_factory() as session:
        actual = {
            category.code: category.path
            for category in classification_categories(
                session,
                client.app.state.settings.local_user_id,
            )
        }
        for code, path in expected.items():
            assert actual[code] == path


def test_classification_input_snapshot_survives_later_metadata_refresh(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """以后刷新正文也不能改变已保存的模型判断依据或重复请求模型。"""

    configure_jev(client)
    memo_id = create_resource(client)
    old_excerpt = "当时用于归类的工具介绍。"
    with client.app.state.database.session_factory() as session:
        session.get(Memo, memo_id).resource_text_excerpt = old_excerpt
        session.commit()

    def classify(metadata: ResourceMetadata, *_args: object) -> CategoryDecision:
        """成功判断保留当次输入快照。"""

        _, assessment = parse_jev_assessment(
            {
                "answers": {
                    "category": {
                        "choice": "tool",
                        "confidence": 0.95,
                    }
                }
            },
            {"tool": "工具与服务"},
            0.7,
            "typesafe/jev",
            True,
            metadata.text_excerpt,
        )
        return replace(tool_decision(), assessment=assessment)

    monkeypatch.setattr(
        "app.resource_classification_service.classify_resource_with_jev", classify
    )
    settings = client.app.state.settings
    run_pending_classification_jobs(settings.database_url, settings)

    def fetch(url: str) -> ResourceMetadata:
        """随后公开网页正文有所更新。"""

        return ResourceMetadata(
            url,
            "新版网页",
            None,
            "Example",
            None,
            200,
            text_excerpt="新的网页正文与之前不同。",
        )

    with client.app.state.database.session_factory() as session:
        updated = enrich_resource(
            session, settings.local_user_id, memo_id, settings, metadata_fetcher=fetch
        )
        assert updated.resource_text_excerpt != old_excerpt
        assert updated.resource_ai_assessment["input_excerpt"] == old_excerpt
        assert updated.resource_ai_classified_at is not None


def test_single_page_refresh_preserves_category_when_jev_is_uncertain(
    client: TestClient,
) -> None:
    """单页刷新与批量处理一致，未确定的模型结果不能覆盖旧规则分类。"""

    memo_id = create_resource(client)
    settings = client.app.state.settings
    with pytest.raises(UncertainClassificationError) as raised:
        parse_jev_assessment(
            {
                "answers": {
                    "category": {
                        "choice": "tool",
                        "confidence": 0.4,
                    }
                }
            },
            {"tool": "工具与服务"},
            0.7,
            "typesafe/jev",
            False,
        )
    assessment = raised.value.assessment

    def fetch(url: str) -> ResourceMetadata:
        """重新获取公开元数据。"""

        return ResourceMetadata(url, "新网页标题", None, "Example", None, 200)

    def classify(_metadata: ResourceMetadata) -> CategoryDecision:
        """模型不确定时提供规则回退及本次证据。"""

        return replace(tool_decision(), source="rule", assessment=assessment)

    with client.app.state.database.session_factory() as session:
        memo = session.get(Memo, memo_id)
        memo.resource_category = "article"
        memo.resource_category_source = "rule"
        session.commit()
        updated = enrich_resource(
            session,
            settings.local_user_id,
            memo_id,
            settings,
            metadata_fetcher=fetch,
            classifier=classify,
        )
        assert updated.resource_category == "article"
        assert updated.resource_category_source == "rule"
        assert updated.resource_category_status == "ready"
        assert updated.resource_ai_classified_at is None
        assert updated.resource_ai_assessment["reason_code"] == "low_confidence"


def test_retry_wait_cannot_be_bypassed_by_repeated_resume_or_start(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """重复点击接口不能清除尚未到期的等待或增加上游请求。"""

    configure_jev(client)
    create_resource(client)

    def classify(_metadata: ResourceMetadata, *_args: object) -> CategoryDecision:
        """模拟请求超时，等待由任务表持久化。"""

        raise httpx.ReadTimeout("private-key")

    monkeypatch.setattr(
        "app.resource_classification_service.classify_resource_with_jev", classify
    )
    settings = client.app.state.settings
    run_pending_classification_jobs(settings.database_url, settings)
    before = client.get("/api/v1/resource-classification").json()["job"]
    for endpoint in (
        "/api/v1/resource-classification/resume",
        "/api/v1/resource-classification",
    ):
        response = client.post(endpoint)
        assert response.status_code == 202
        after = response.json()["job"]
        assert after["id"] == before["id"]
        assert after["retry_count"] == before["retry_count"] == 1
        assert after["next_retry_at"] == before["next_retry_at"]
        assert after["processed_count"] == 0


def test_long_retry_after_pauses_without_requesting_too_early(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """等待超过五分钟时明确暂停，不能把服务要求截短后继续请求。"""

    configure_jev(client)
    create_resource(client)
    calls = 0

    def classify(_metadata: ResourceMetadata, *_args: object) -> CategoryDecision:
        """上游要求等待六百秒。"""

        nonlocal calls
        calls += 1
        request = httpx.Request("POST", "https://relay.example/v1/systemone")
        response = httpx.Response(429, request=request, headers={"Retry-After": "600"})
        raise httpx.HTTPStatusError("private-key", request=request, response=response)

    monkeypatch.setattr(
        "app.resource_classification_service.classify_resource_with_jev", classify
    )
    settings = client.app.state.settings
    run_pending_classification_jobs(settings.database_url, settings)
    job = client.get("/api/v1/resource-classification").json()["job"]
    assert job["status"] == "failed"
    assert job["retry_count"] == 0
    assert job["next_retry_at"] is None
    assert "等待超过五分钟" in job["error"]
    assert "已自动重试" not in job["error"]
    run_pending_classification_jobs(settings.database_url, settings)
    assert calls == 1


def test_stale_worker_error_cannot_change_current_owner(client: TestClient) -> None:
    """过期工作线程的错误不覆盖新领取者的租约、进度或重试计数。"""

    configure_jev(client)
    create_resource(client)
    settings = client.app.state.settings
    with client.app.state.database.session_factory() as session:
        job = start_classification_job(session, settings.local_user_id, settings)
        job.status = "processing"
        job.worker_token = "new-worker"
        session.commit()
        job_id = job.id
        record_service_failure(
            session,
            settings.local_user_id,
            job_id,
            "old-worker",
            ClassificationServiceFailure("timeout", "超时", True),
        )
        session.refresh(job)
        assert job.status == "processing"
        assert job.worker_token == "new-worker"
        assert job.retry_count == 0
        assert job.error is None
        assert job.next_retry_at is None


@pytest.mark.parametrize(
    "failure", ["timeout", "network", 408, 429, 500, 502, 503, 504]
)
def test_transient_failure_has_persistent_bounded_retries(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    failure: str | int,
) -> None:
    """临时错误等待后重试两次，游标始终不动，耗尽后停止新导入的自动调用。"""

    configure_jev(client)
    memo_id = create_resource(client)
    calls = 0

    def classify(_metadata: ResourceMetadata, *_args: object) -> CategoryDecision:
        """模拟网络异常或上游临时 HTTP 错误，原始消息包含不可公开内容。"""

        nonlocal calls
        calls += 1
        request = httpx.Request("POST", "https://relay.example/v1/systemone")
        if failure == "timeout":
            raise httpx.ReadTimeout("private-upstream-key", request=request)
        if failure == "network":
            raise httpx.ConnectError("private-upstream-key", request=request)
        response = httpx.Response(
            int(failure), request=request, text="private-upstream-key"
        )
        raise httpx.HTTPStatusError(
            "private-upstream-key", request=request, response=response
        )

    monkeypatch.setattr(
        "app.resource_classification_service.classify_resource_with_jev", classify
    )
    settings = client.app.state.settings
    assert run_pending_classification_jobs(settings.database_url, settings) == 0
    first = client.get("/api/v1/resource-classification").json()["job"]
    assert first["status"] == "pending"
    assert first["retry_count"] == 1
    assert first["next_retry_at"].endswith("Z")
    assert first["processed_count"] == first["failed_count"] == 0
    assert first["retry_limit"] == 2
    assert run_pending_classification_jobs(settings.database_url, settings) == 0
    assert calls == 1
    for expected_count in (2, 3):
        make_retry_due(client)
        assert run_pending_classification_jobs(settings.database_url, settings) == 0
        assert calls == expected_count
    state = client.get("/api/v1/resource-classification")
    job = state.json()["job"]
    assert job["id"] == first["id"]
    assert job["status"] == "failed"
    assert job["processed_count"] == job["succeeded_count"] == job["failed_count"] == 0
    assert job["retry_count"] == 2
    assert job["next_retry_at"] is None
    assert "已自动重试 2 次" in job["error"]
    assert "private-upstream-key" not in state.text
    create_resource(client, "暂停期间的新导入")
    assert run_pending_classification_jobs(settings.database_url, settings) == 0
    assert calls == 3
    assert (
        client.get(f"/api/v1/memos/{memo_id}").json()["resource_ai_classified_at"]
        is None
    )


def test_retry_after_survives_restart_and_recovers_without_repeating_success(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """服务要求的等待日期在新连接中仍有效，恢复时保留之前成功的进度。"""

    configure_jev(client)
    create_resource(client, "之前成功")
    create_resource(client, "限流网页")
    settings = client.app.state.settings
    calls: list[str] = []

    def classify(metadata: ResourceMetadata, *_args: object) -> CategoryDecision:
        """仅第二个网页第一次触发限流，此后恢复正常。"""

        calls.append(metadata.page_title or "")
        if metadata.page_title == "限流网页" and calls.count("限流网页") == 1:
            request = httpx.Request("POST", "https://relay.example/v1/systemone")
            response = httpx.Response(
                429,
                request=request,
                headers={
                    "Retry-After": format_datetime(
                        datetime.now(UTC) + timedelta(seconds=75), usegmt=True
                    ),
                },
            )
            raise httpx.HTTPStatusError(
                "private-upstream-key", request=request, response=response
            )
        return tool_decision()

    monkeypatch.setattr(
        "app.resource_classification_service.classify_resource_with_jev", classify
    )
    assert run_pending_classification_jobs(settings.database_url, settings) == 1
    before = client.get("/api/v1/resource-classification").json()["job"]
    assert before["processed_count"] == before["succeeded_count"] == 1
    wait_until = datetime.fromisoformat(before["next_retry_at"].replace("Z", "+00:00"))
    assert (wait_until - datetime.now(UTC)).total_seconds() > 70
    assert run_pending_classification_jobs(settings.database_url, settings) == 0
    assert calls == ["之前成功", "限流网页"]
    make_retry_due(client)
    assert run_pending_classification_jobs(settings.database_url, settings) == 1
    after = client.get("/api/v1/resource-classification").json()["job"]
    assert after["id"] == before["id"]
    assert after["status"] == "completed"
    assert after["processed_count"] == after["succeeded_count"] == 2
    assert after["retry_count"] == 0
    assert after["error_code"] is None
    assert after["error"] is None
    assert calls == ["之前成功", "限流网页", "限流网页"]


@pytest.mark.parametrize(
    "endpoint",
    ["/api/v1/resource-classification/resume", "/api/v1/resource-classification"],
)
def test_manual_resume_keeps_queue_and_never_replays_uncertain_or_successful_pages(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    endpoint: str,
) -> None:
    """新旧客户端继续任务都保持游标，不会重新请求此前未确定的条目。"""

    configure_jev(client)
    for name in ("已成功", "已未确定", "服务失败", "尚未处理"):
        create_resource(client, name)
    settings = client.app.state.settings
    recovered = False
    calls: list[str] = []

    def classify(metadata: ResourceMetadata, *_args: object) -> CategoryDecision:
        """模拟先成功、再未确定、再认证失败；恢复后剩余两条均成功。"""

        calls.append(metadata.page_title or "")
        if metadata.page_title == "已未确定":
            raise ValueError("uncertain_or_invalid_jev_category")
        if metadata.page_title == "服务失败" and not recovered:
            request = httpx.Request("POST", "https://relay.example/v1/systemone")
            raise httpx.HTTPStatusError(
                "private-upstream-key",
                request=request,
                response=httpx.Response(401, request=request),
            )
        return tool_decision()

    monkeypatch.setattr(
        "app.resource_classification_service.classify_resource_with_jev", classify
    )
    client.post("/api/v1/resource-classification").raise_for_status()
    assert run_pending_classification_jobs(settings.database_url, settings) == 2
    original = client.get("/api/v1/resource-classification").json()["job"]
    assert original["status"] == "failed"
    assert original["error_code"] == "authentication"
    assert original["processed_count"] == 2
    recovered = True
    response = client.post(endpoint)
    assert response.status_code == 202
    resumed = response.json()["job"]
    assert resumed["id"] == original["id"]
    assert resumed["total_count"] == 4
    assert resumed["processed_count"] == 2
    assert resumed["succeeded_count"] == resumed["failed_count"] == 1
    assert resumed["created_at"] == original["created_at"]
    assert client.post(endpoint).json()["job"]["id"] == original["id"]
    assert run_pending_classification_jobs(settings.database_url, settings) == 2
    final = client.get("/api/v1/resource-classification").json()["job"]
    assert final["id"] == original["id"]
    assert final["status"] == "completed"
    assert final["succeeded_count"] == 3
    assert final["failed_count"] == 1
    assert calls == ["已成功", "已未确定", "服务失败", "服务失败", "尚未处理"]
    assert client.post("/api/v1/resource-classification/resume").status_code == 409


def test_retry_still_honors_new_health_review_hold(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """重试等待期间网页被巡检判为异常，恢复后跳过，不再次发送模型请求。"""

    configure_jev(client)
    memo_id = create_resource(client)
    calls = 0

    def classify(_metadata: ResourceMetadata, *_args: object) -> CategoryDecision:
        """第一次请求超时，之后是否还能调用由巡检状态决定。"""

        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("private-upstream-key")

    monkeypatch.setattr(
        "app.resource_classification_service.classify_resource_with_jev", classify
    )
    settings = client.app.state.settings
    run_pending_classification_jobs(settings.database_url, settings)
    with client.app.state.database.session_factory() as session:
        memo = session.get(Memo, memo_id)
        memo.link_health_status = "failed"
        apply_classification_health_gate(memo)
        session.commit()
    make_retry_due(client)
    assert run_pending_classification_jobs(settings.database_url, settings) == 1
    job = client.get("/api/v1/resource-classification").json()["job"]
    assert job["status"] == "completed"
    assert job["skipped_count"] == 1
    assert job["retry_count"] == 0
    assert calls == 1


def test_resume_is_account_scoped_and_new_imports_continue_after_recovery(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """其他账号不能继续本人的任务，恢复完成后主动接续暂停期间的新导入。"""

    configure_jev(client)
    create_resource(client, "旧任务网页")
    settings = client.app.state.settings
    with client.app.state.database.session_factory() as session:
        own = create_dev_session(session, settings).token
        other = create_dev_session(
            session, replace(settings, local_user_id=str(uuid4()))
        ).token
        job = start_classification_job(session, settings.local_user_id, settings)
        original_id = job.id
        job.status = "failed"
        job.error_code = "authentication"
        job.error = "Jev 认证失败"
        session.commit()
    create_resource(client, "暂停期间的新导入")
    client.app.state.settings = replace(settings, auth_dev_mode=False)
    assert client.post("/api/v1/resource-classification/resume").status_code == 401
    assert (
        client.post(
            "/api/v1/resource-classification/resume",
            headers={"Authorization": f"Bearer {other}"},
        ).status_code
        == 409
    )
    response = client.post(
        "/api/v1/resource-classification/resume",
        headers={"Authorization": f"Bearer {own}"},
    )
    assert response.status_code == 202
    assert response.json()["job"]["id"] == original_id
    assert response.json()["job"]["total_count"] == 1
    calls: list[str] = []

    def classify(metadata: ResourceMetadata, *_args: object) -> CategoryDecision:
        """恢复后模拟模型服务正常。"""

        calls.append(metadata.page_title or "")
        return tool_decision()

    monkeypatch.setattr(
        "app.resource_classification_service.classify_resource_with_jev", classify
    )
    assert run_pending_classification_jobs(settings.database_url, settings) == 1
    assert run_pending_classification_jobs(settings.database_url, settings) == 1
    assert run_pending_classification_jobs(settings.database_url, settings) == 0
    assert calls == ["旧任务网页", "暂停期间的新导入"]


def test_retry_schema_upgrade_preserves_failed_job_progress(client: TestClient) -> None:
    """补充重试字段及重复迁移都不丢失历史失败任务的队列和游标。"""

    configure_jev(client)
    for index in range(3):
        create_resource(client, f"迁移网页 {index}")
    database = client.app.state.database
    settings = client.app.state.settings
    with database.session_factory() as session:
        job = start_classification_job(session, settings.local_user_id, settings)
        job.status = "failed"
        job.processed_count = 2
        job.succeeded_count = job.failed_count = 1
        original_id = job.id
        original_queue = list(job.memo_ids)
        session.commit()
    with database.engine.begin() as connection:
        for column in ("retry_count", "error_code", "next_retry_at"):
            connection.exec_driver_sql(
                f"ALTER TABLE resource_classification_job DROP COLUMN {column}"
            )
    database.create_schema()
    database.create_schema()
    with database.session_factory() as session:
        job = session.get(ResourceClassificationJob, settings.local_user_id)
        assert job.id == original_id
        assert job.memo_ids == original_queue
        assert job.status == "failed"
        assert job.processed_count == 2
        assert job.succeeded_count == job.failed_count == 1
        assert job.retry_count == 0
        resumed = resume_classification_job(session, settings.local_user_id, settings)
        assert resumed.processed_count == 2
        assert resumed.memo_ids == original_queue


@pytest.mark.parametrize("outcome", ["failed", "redirected"])
def test_enrichment_defers_model_calls_for_review_webpages(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    outcome: str,
) -> None:
    """新导入网页的访问异常或跳转也必须先等待用户筛选。"""

    configure_jev(client)
    memo_id = create_resource(client)
    settings = client.app.state.settings
    calls = 0

    def model_request(*_args: object, **_kwargs: object) -> httpx.Response:
        """捕获任何不应发生的外部模型请求。"""

        nonlocal calls
        calls += 1
        return httpx.Response(500)

    def fetch(url: str) -> ResourceMetadata:
        """分别模拟访问失败和需要采用新网址的网页。"""

        if outcome == "failed":
            raise ResourceFetchError("http_403", 403)
        return ResourceMetadata(
            url + "/redirected", "网页标题", None, "Example", None, 200
        )

    monkeypatch.setattr("app.resource_processing.httpx.post", model_request)
    with client.app.state.database.session_factory() as session:
        memo = enrich_resource(
            session, settings.local_user_id, memo_id, settings, metadata_fetcher=fetch
        )
        assert memo.resource_ai_review_required is True
        assert memo.resource_ai_classified_at is None
        assert classification_state(session, settings.local_user_id).pending_count == 0
    assert calls == 0


def test_successful_model_classification_is_not_repeated_on_metadata_refresh(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """元数据刷新也跳过已成功分类的网页，避免另一队列重复调用模型。"""

    configure_jev(client)
    memo_id = create_resource(client)
    settings = client.app.state.settings
    calls = 0

    def model_request(*_args: object, **_kwargs: object) -> httpx.Response:
        """返回正式 Jev Choice 格式的可接受分类。"""

        nonlocal calls
        calls += 1
        request = httpx.Request("POST", "https://relay.example/v1/systemone")
        return httpx.Response(
            200,
            request=request,
            json={"answers": {"category": {"choice": "tool", "confidence": 0.9}}},
        )

    def fetch(url: str) -> ResourceMetadata:
        """提供可正常访问的元数据。"""

        return ResourceMetadata(url, "工具主页", None, "Example", None, 200)

    monkeypatch.setattr("app.resource_processing.httpx.post", model_request)
    with client.app.state.database.session_factory() as session:
        first = enrich_resource(
            session, settings.local_user_id, memo_id, settings, metadata_fetcher=fetch
        )
        timestamp = first.resource_ai_classified_at
        second = enrich_resource(
            session, settings.local_user_id, memo_id, settings, metadata_fetcher=fetch
        )
        assert second.resource_ai_classified_at == timestamp
    assert calls == 1


def test_bookmark_enrichment_feeds_auto_classification_queue(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """书签导入先抓取元数据，随后自动分类不需要用户再次点击。"""

    configure_jev(client)
    memo_id = create_resource(client)
    settings = client.app.state.settings
    calls = 0

    def model_request(*_args: object, **_kwargs: object) -> httpx.Response:
        """真实格式的模型响应，由自动队列调用。"""

        nonlocal calls
        calls += 1
        request = httpx.Request("POST", "https://relay.example/v1/systemone")
        return httpx.Response(
            200,
            request=request,
            json={"answers": {"category": {"choice": "tool", "confidence": 0.9}}},
        )

    def fetch(url: str) -> ResourceMetadata:
        """从书签 URL 获取可用元数据。"""

        return ResourceMetadata(url, "书签主页", None, "Example", None, 200)

    monkeypatch.setattr("app.resource_processing.httpx.post", model_request)
    with client.app.state.database.session_factory() as session:
        memo = session.get(Memo, memo_id)
        memo.resource_import_batch_id = str(uuid4())
        memo.link_health_status = "unchecked"
        session.commit()
        enriched = enrich_resource(
            session, settings.local_user_id, memo_id, settings, metadata_fetcher=fetch
        )
        assert enriched.link_health_status == "healthy"
        assert enriched.resource_ai_auto_pending is True
        assert calls == 0
    assert run_pending_classification_jobs(settings.database_url, settings) == 1
    assert calls == 1
