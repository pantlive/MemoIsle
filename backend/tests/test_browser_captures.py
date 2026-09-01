"""浏览器扩展一次性网页捕获测试。"""

from __future__ import annotations

from app.browser_capture_service import create_browser_capture
from app.schemas import BrowserCaptureCreate, BrowserCaptureCreated
from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from sqlalchemy.orm import Session

EXTENSION_ID = "a" * 32
EXTENSION_ORIGIN = f"chrome-extension://{EXTENSION_ID}"


def capture_payload() -> dict[str, str]:
    """生成扩展当前页授权请求。"""

    return {
        "extension_id": EXTENSION_ID,
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

    monkeypatch.setattr("app.api.create_browser_capture", create_without_dns)
    created_response = client.post(
        "/api/v1/browser-captures",
        headers={"Origin": EXTENSION_ORIGIN},
        json=capture_payload(),
    )
    assert created_response.status_code == 201
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

    private_payload = capture_payload()
    private_payload["page_url"] = "http://127.0.0.1/private"
    private_response = client.post(
        "/api/v1/browser-captures",
        headers={"Origin": EXTENSION_ORIGIN},
        json=private_payload,
    )
    assert private_response.status_code == 422
