"""浏览器扩展一次性网页捕获测试。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.browser_capture_service import create_browser_capture, sync_open_browser_tabs
from app.models import BrowserBookmarkSnapshot, BrowserOpenTab
from app.schemas import (
    BrowserCaptureCreate,
    BrowserCaptureCreated,
    BrowserTabSyncRequest,
)
from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from sqlalchemy import select
from sqlalchemy.orm import Session

EXTENSION_ID = "a" * 32
EXTENSION_ORIGIN = f"chrome-extension://{EXTENSION_ID}"


def capture_payload() -> dict[str, object]:
    """生成扩展当前页授权请求。"""

    return {
        "extension_id": EXTENSION_ID,
        "tab_id": 42,
        "window_id": 1,
        "nonce": "0123456789abcdef0123456789abcdef",
        "page_url": "https://public.example/guide",
        "page_title": "公开网页指南",
        "favicon_url": "https://public.example/favicon.png",
    }


def test_browser_capture_is_single_use(
    client: TestClient,
    monkeypatch: MonkeyPatch,
) -> None:
    """扩展来源匹配时可签发令牌，Web 只能成功交换一次。"""

    def create_without_dns(
        session: Session,
        user_id: str,
        payload: BrowserCaptureCreate,
        request_origin: str | None,
    ) -> BrowserCaptureCreated:
        return create_browser_capture(
            session,
            user_id,
            payload,
            request_origin,
            url_validator=lambda url: url,
        )

    def sync_without_dns(
        session: Session,
        user_id: str,
        payload: BrowserTabSyncRequest,
        request_origin: str | None,
    ) -> int:
        def validate_tab_url(url: str) -> str:
            if url.startswith("http://127.0.0.1/"):
                raise ValueError("private_url")
            return url

        return sync_open_browser_tabs(
            session,
            user_id,
            payload,
            request_origin,
            url_validator=validate_tab_url,
        )

    monkeypatch.setattr("app.api.create_browser_capture", create_without_dns)
    monkeypatch.setattr("app.api.sync_open_browser_tabs", sync_without_dns)
    created_response = client.post(
        "/api/v1/browser-captures",
        headers={"Origin": EXTENSION_ORIGIN},
        json=capture_payload(),
    )
    assert created_response.status_code == 201

    sync_response = client.post(
        "/api/v1/browser-tabs/sync",
        headers={"Origin": EXTENSION_ORIGIN},
        json={
            "extension_id": EXTENSION_ID,
            "tabs": [
                {
                    "tab_id": 42,
                    "window_id": 1,
                    "page_url": "https://public.example/guide",
                    "page_title": "公开网页指南",
                    "favicon_url": "https://public.example/favicon.png",
                },
                {
                    "tab_id": 43,
                    "window_id": 1,
                    "page_url": "https://public.example/course",
                    "page_title": "公开课程",
                },
                {
                    "tab_id": 44,
                    "window_id": 1,
                    "page_url": "http://127.0.0.1/private",
                    "page_title": "不应展示",
                },
            ],
        },
    )
    assert sync_response.status_code == 200
    assert sync_response.json()["synced_count"] == 2
    open_tabs = client.get("/api/v1/browser-tabs/open").json()["items"]
    assert {tab["page_title"] for tab in open_tabs} == {"公开网页指南", "公开课程"}

    close_snapshot_response = client.post(
        "/api/v1/browser-tabs/sync",
        headers={"Origin": EXTENSION_ORIGIN},
        json={
            "extension_id": EXTENSION_ID,
            "tabs": [
                {
                    "tab_id": 42,
                    "window_id": 1,
                    "page_url": "https://public.example/guide",
                    "page_title": "公开网页指南",
                },
            ],
        },
    )
    assert close_snapshot_response.status_code == 200
    remaining_tabs = client.get("/api/v1/browser-tabs/open").json()["items"]
    assert [tab["page_title"] for tab in remaining_tabs] == ["公开网页指南"]

    with client.app.state.database.session_factory() as session:
        stale_tab = session.scalar(
            select(BrowserOpenTab).where(BrowserOpenTab.status == "open")
        )
        assert stale_tab is not None
        stale_tab.last_seen_at = datetime.now(UTC) - timedelta(minutes=11)
        session.commit()
    assert client.get("/api/v1/browser-tabs/open").json()["items"] == []

    token = created_response.json()["token"]
    assert token not in str(client.app.state.database.engine.url)

    exchange_response = client.post(
        "/api/v1/browser-captures/exchange",
        json={"token": token},
    )
    assert exchange_response.status_code == 200
    assert exchange_response.json() == {
        "page_url": "https://public.example/guide",
        "page_title": "公开网页指南",
        "favicon_url": "https://public.example/favicon.png",
        "nonce": "0123456789abcdef0123456789abcdef",
    }

    consumed_response = client.post(
        "/api/v1/browser-captures/exchange",
        json={"token": token},
    )
    assert consumed_response.status_code == 409


def test_browser_capture_rejects_spoofed_origin_and_private_page(
    client: TestClient,
) -> None:
    """伪造扩展来源和内网当前页都不能生成网页附件。"""

    spoofed_response = client.post(
        "/api/v1/browser-captures",
        headers={"Origin": f"chrome-extension://{'b' * 32}"},
        json=capture_payload(),
    )
    assert spoofed_response.status_code == 403

    spoofed_sync_response = client.post(
        "/api/v1/browser-tabs/sync",
        headers={"Origin": f"chrome-extension://{'b' * 32}"},
        json={"extension_id": EXTENSION_ID, "tabs": []},
    )
    assert spoofed_sync_response.status_code == 403

    private_payload = capture_payload()
    private_payload["page_url"] = "http://127.0.0.1/private"
    private_response = client.post(
        "/api/v1/browser-captures",
        headers={"Origin": EXTENSION_ORIGIN},
        json=private_payload,
    )
    assert private_response.status_code == 422


def test_browser_extension_syncs_bookmarks_for_direct_web_import(
    client: TestClient,
) -> None:
    """扩展书签快照可由 Web 直接读取，并由下一次完整快照替换。"""

    empty_response = client.get("/api/v1/browser-bookmarks/current")
    assert empty_response.status_code == 200
    assert empty_response.json() == {
        "extension_connected": False,
        "synced_at": None,
        "total_count": 0,
        "truncated": False,
        "items": [],
    }

    sync_response = client.post(
        "/api/v1/browser-bookmarks/sync",
        headers={"Origin": EXTENSION_ORIGIN},
        json={
            "extension_id": EXTENSION_ID,
            "total_count": 2,
            "items": [
                {
                    "client_item_id": "chrome:41",
                    "title": " PyTorch 文档 ",
                    "url": "https://pytorch.org/docs/stable/",
                    "folder_path": "书签栏 / 学习资料",
                },
                {
                    "client_item_id": "chrome:42",
                    "title": "文章",
                    "url": "https://example.com/article",
                    "folder_path": "其他书签",
                },
            ],
        },
    )
    assert sync_response.status_code == 200
    assert sync_response.json() == {"synced_count": 2, "truncated": False}

    current = client.get("/api/v1/browser-bookmarks/current").json()
    assert current["extension_connected"] is True
    assert current["total_count"] == 2
    assert current["truncated"] is False
    assert current["synced_at"].endswith("Z")
    assert current["items"] == [
        {
            "client_item_id": "chrome:41",
            "title": "PyTorch 文档",
            "url": "https://pytorch.org/docs/stable/",
            "folder_path": "书签栏 / 学习资料",
        },
        {
            "client_item_id": "chrome:42",
            "title": "文章",
            "url": "https://example.com/article",
            "folder_path": "其他书签",
        },
    ]

    replacement_response = client.post(
        "/api/v1/browser-bookmarks/sync",
        headers={"Origin": EXTENSION_ORIGIN},
        json={
            "extension_id": EXTENSION_ID,
            "total_count": 5_001,
            "items": [
                {
                    "client_item_id": "chrome:99",
                    "title": "最新书签",
                    "url": "https://example.com/latest",
                }
            ],
        },
    )
    assert replacement_response.json() == {"synced_count": 1, "truncated": True}
    latest = client.get("/api/v1/browser-bookmarks/current").json()
    assert latest["items"][0]["client_item_id"] == "chrome:99"
    assert latest["truncated"] is True

    with client.app.state.database.session_factory() as session:
        snapshots = session.scalars(select(BrowserBookmarkSnapshot)).all()
        assert len(snapshots) == 1


def test_browser_bookmark_sync_rejects_spoofed_extension_origin(
    client: TestClient,
) -> None:
    """Web 页面或其他扩展不能伪造当前浏览器书签快照。"""

    response = client.post(
        "/api/v1/browser-bookmarks/sync",
        headers={"Origin": f"chrome-extension://{'b' * 32}"},
        json={
            "extension_id": EXTENSION_ID,
            "total_count": 0,
            "items": [],
        },
    )
    assert response.status_code == 403
