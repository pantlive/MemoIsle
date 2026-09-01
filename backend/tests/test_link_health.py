"""网页链接健康巡检测试。"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from app.config import Settings
from app.database import Database
from app.link_health_service import (
    apply_link_health_action,
    check_resource_link,
    run_due_link_checks,
)
from app.models import Memo
from app.resource_processing import ResourceFetchError, ResourceMetadata
from app.schemas import (
    LinkHealthAction,
    LinkHealthActionRequest,
    MemoCreate,
    MemoType,
)
from app.service import create_memo
from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from sqlalchemy.orm import Session


def health_settings(tmp_path: Path, database: Database) -> Settings:
    """生成关闭后台线程的网页巡检测试配置。"""

    return Settings(
        database_url=database.database_url,
        cors_origins=("http://localhost:5173",),
        local_user_id="00000000-0000-0000-0000-000000000001",
        audio_directory=tmp_path / "audio",
        resource_enrichment_enabled=False,
        resource_health_monitor_enabled=False,
        resource_failure_threshold=3,
        resource_health_interval_hours=720,
    )


def test_link_check_uses_failure_threshold_and_detects_changes(tmp_path: Path) -> None:
    """连续三次确定性失败才进入失效组，恢复后可识别内容变化和跳转。"""

    database = Database(f"sqlite+pysqlite:///{tmp_path / 'health.db'}")
    database.create_schema()
    settings = health_settings(tmp_path, database)
    with database.session_factory() as session:
        memo = create_memo(
            session,
            settings.local_user_id,
            MemoCreate(
                client_id=uuid4(),
                type=MemoType.RESOURCE,
                body="稍后阅读",
                source_url="https://public.example/article",
                tags=[],
            ),
        )

        def missing_fetcher(_url: str) -> ResourceMetadata:
            raise ResourceFetchError("http_404", 404)

        for expected_failures in range(1, 4):
            memo = check_resource_link(
                session,
                settings.local_user_id,
                memo.id,
                settings,
                fetcher=missing_fetcher,
            )
            assert memo.link_consecutive_failures == expected_failures
        assert memo.link_health_status == "failed"

        first_metadata = ResourceMetadata(
            final_url=memo.source_url or "",
            page_title="文章第一版",
            description="内容摘要",
            site_name="Public Example",
            favicon_url=None,
            http_status=200,
        )
        memo = check_resource_link(
            session,
            settings.local_user_id,
            memo.id,
            settings,
            fetcher=lambda _url: first_metadata,
            force=True,
        )
        assert memo.link_health_status == "healthy"
        assert memo.link_consecutive_failures == 0

        changed_metadata = ResourceMetadata(
            final_url=memo.source_url or "",
            page_title="文章第二版",
            description="更新后的摘要",
            site_name="Public Example",
            favicon_url=None,
            http_status=200,
        )
        memo = check_resource_link(
            session,
            settings.local_user_id,
            memo.id,
            settings,
            fetcher=lambda _url: changed_metadata,
        )
        assert memo.link_health_status == "changed"
        memo = check_resource_link(
            session,
            settings.local_user_id,
            memo.id,
            settings,
            fetcher=lambda _url: changed_metadata,
        )
        assert memo.link_health_status == "changed"

        redirected_metadata = ResourceMetadata(
            final_url="https://public.example/new-article",
            page_title="文章第二版",
            description="更新后的摘要",
            site_name="Public Example",
            favicon_url=None,
            http_status=200,
        )
        memo = check_resource_link(
            session,
            settings.local_user_id,
            memo.id,
            settings,
            fetcher=lambda _url: redirected_metadata,
        )
        assert memo.link_health_status == "redirected"

        adopted = apply_link_health_action(
            session,
            settings.local_user_id,
            memo.id,
            LinkHealthActionRequest(
                expected_version=memo.version,
                action=LinkHealthAction.ADOPT_REDIRECT,
            ),
            settings,
        )
        assert adopted.source_url == "https://public.example/new-article"
        assert adopted.link_health_status == "unchecked"
    database.dispose()


def test_pending_enrichment_recovers_after_restart(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """服务重启后卡在 processing 的资料会重新进入处理。"""

    database = Database(f"sqlite+pysqlite:///{tmp_path / 'enrichment.db'}")
    database.create_schema()
    settings = health_settings(tmp_path, database)
    with database.session_factory() as session:
        memo = create_memo(
            session,
            settings.local_user_id,
            MemoCreate(
                client_id=uuid4(),
                type=MemoType.RESOURCE,
                body="等待分类",
                source_url="https://recover.example/page",
                tags=[],
            ),
        )
        memo.resource_metadata_status = "processing"
        session.commit()

    def recover_enrichment(
        session: Session,
        user_id: str,
        memo_id: str,
        _settings: Settings,
    ) -> Memo:
        recovered = session.get(Memo, memo_id)
        assert recovered is not None
        assert recovered.user_id == user_id
        recovered.resource_metadata_status = "ready"
        session.commit()
        return recovered

    monkeypatch.setattr("app.resource_service.enrich_resource", recover_enrichment)
    from app.resource_service import run_pending_resource_enrichments

    assert run_pending_resource_enrichments(database.database_url, settings) == 1
    with database.session_factory() as session:
        recovered = session.get(Memo, memo.id)
        assert recovered is not None
        assert recovered.resource_metadata_status == "ready"
    database.dispose()


def test_link_health_center_and_ignore_action(client: TestClient) -> None:
    """巡检中心显示失效网页，并允许忽略后移出默认待处理列表。"""

    created = client.post(
        "/api/v1/memos",
        json={
            "client_id": str(uuid4()),
            "type": "resource",
            "title": "已经失效的资料",
            "body": "等待处理",
            "source_url": "https://example.com/gone",
        },
    ).json()
    database = client.app.state.database
    with database.session_factory() as session:
        memo = session.get(Memo, created["id"])
        assert memo is not None
        memo.link_health_status = "failed"
        memo.link_health_error = "http_404"
        memo.link_health_http_status = 404
        memo.link_consecutive_failures = 3
        session.commit()

    center_response = client.get("/api/v1/resources/link-health")
    assert center_response.status_code == 200
    assert center_response.json()["counts"]["failed"] == 1
    assert center_response.json()["items"][0]["id"] == created["id"]

    ignore_response = client.post(
        f"/api/v1/resources/{created['id']}/link-health-actions",
        json={"expected_version": created["version"], "action": "ignore"},
    )
    assert ignore_response.status_code == 200
    assert ignore_response.json()["link_health_status"] == "ignored"

    refreshed_center = client.get("/api/v1/resources/link-health").json()
    assert refreshed_center["items"] == []
    assert refreshed_center["counts"]["ignored"] == 1


def test_due_scheduler_limits_each_host_per_round(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """后台轮询会处理到期资料，并限制同一轮重复访问相同站点。"""

    database = Database(f"sqlite+pysqlite:///{tmp_path / 'scheduler.db'}")
    database.create_schema()
    settings = health_settings(tmp_path, database)
    with database.session_factory() as session:
        for path_name in ("first", "second"):
            create_memo(
                session,
                settings.local_user_id,
                MemoCreate(
                    client_id=uuid4(),
                    type=MemoType.RESOURCE,
                    body="等待巡检",
                    source_url=f"https://same.example/{path_name}",
                    tags=[],
                ),
            )

    def successful_fetcher(url: str, **_kwargs: object) -> ResourceMetadata:
        return ResourceMetadata(
            final_url=url,
            page_title="正常网页",
            description=None,
            site_name="Same Example",
            favicon_url=None,
            http_status=200,
        )

    monkeypatch.setattr(
        "app.link_health_service.fetch_resource_metadata",
        successful_fetcher,
    )
    assert run_due_link_checks(database.database_url, settings) == 1
    with database.session_factory() as session:
        memos = list(session.query(Memo).order_by(Memo.created_at.asc()).all())
        assert sorted(memo.link_health_status for memo in memos) == [
            "healthy",
            "unchecked",
        ]
    database.dispose()
