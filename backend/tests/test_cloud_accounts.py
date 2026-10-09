"""云盘绑定与凭据校验测试。"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from app import cloud_account_service
from app.cloud_account_service import (
    CloudAccountExistsError,
    CloudCredentialRejectedError,
    create_cloud_account,
    decrypt_credential,
    encrypt_credential,
    list_cloud_accounts,
)
from app.cloud_drive import build_client
from app.cloud_drive.base import AccountInfo, CredentialInvalidError
from app.config import Settings
from app.database import Database
from app.models import CloudAccount
from fastapi.testclient import TestClient


class FakeResponse:
    """最小化的 httpx.Response 替身。"""

    def __init__(self, status_code: int = 200, payload: object = None) -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self) -> object:
        return self._payload


class FakeHttpClient:
    """按 URL 片段匹配响应的假客户端。"""

    def __init__(self, routes: dict[str, FakeResponse]) -> None:
        self._routes = routes
        self.calls: list[str] = []

    def post(self, url: str, **_: object) -> FakeResponse:
        self.calls.append(url)
        for fragment, response in self._routes.items():
            if fragment in url:
                return response
        raise AssertionError(f"未预期的请求地址：{url}")


@pytest.fixture
def session_settings(tmp_path: Path) -> Iterator[tuple[object, Settings]]:
    """提供独立的数据库会话与配置。"""

    settings = Settings(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'cloud.db'}",
        cors_origins=("http://localhost:5173",),
        local_user_id="00000000-0000-0000-0000-000000000001",
        auth_dev_mode=True,
        auth_token_secret="test-secret",
        audio_directory=tmp_path / "audio",
        image_directory=tmp_path / "images",
        resource_enrichment_enabled=False,
        resource_health_monitor_enabled=False,
        word_dictionary_enabled=False,
    )
    database = Database(settings.database_url)
    database.create_schema()
    with database.session_factory() as session:
        yield session, settings
    database.dispose()


def test_credential_is_encrypted_and_decryptable(session_settings) -> None:
    """凭据落库为密文，且可以用同一密钥解回。"""

    _session, settings = session_settings
    plaintext = '{"access_token": "access-token-abcdef"}'
    cipher = encrypt_credential(settings, plaintext)

    assert plaintext not in cipher
    assert decrypt_credential(settings, cipher) == plaintext


def test_create_cloud_account_validates_and_stores(session_settings) -> None:
    """校验通过的凭据可以绑定，且只暴露脱敏提示。"""

    session, settings = session_settings
    http_client = FakeHttpClient(
        {
            "getDriveInfo": FakeResponse(
                200,
                {"name": "我的阿里云盘", "default_drive_id": "drive-1"},
            ),
        },
    )
    credential = '{"access_token": "access-token-1234"}'

    account = create_cloud_account(
        session,
        settings.local_user_id,
        provider="aliyun",
        credential=credential,
        settings=settings,
        default_folder="books",
        http_client=http_client,
    )

    assert account.provider == "aliyun"
    assert account.display_name == "我的阿里云盘"
    assert account.credential_hint == "...1234"
    assert account.default_folder == "/books"
    assert account.status == "active"
    assert "access-token-1234" not in account.credential_cipher
    assert decrypt_credential(settings, account.credential_cipher) == credential
    accounts = list_cloud_accounts(session, settings.local_user_id)
    assert [item.id for item in accounts] == [account.id]


def test_create_cloud_account_rejects_repeated_provider(session_settings) -> None:
    """同一用户同一服务商只能绑定一次。"""

    session, settings = session_settings
    http_client = FakeHttpClient(
        {
            "getDriveInfo": FakeResponse(
                200,
                {"name": "阿里云盘", "default_drive_id": "drive-1"},
            )
        },
    )
    create_cloud_account(
        session,
        settings.local_user_id,
        provider="aliyun",
        credential='{"access_token": "access-token-1234"}',
        settings=settings,
        http_client=http_client,
    )

    with pytest.raises(CloudAccountExistsError):
        create_cloud_account(
            session,
            settings.local_user_id,
            provider="aliyun",
            credential='{"access_token": "access-token-5678"}',
            settings=settings,
            http_client=http_client,
        )


def test_create_cloud_account_rejects_invalid_credential(session_settings) -> None:
    """服务商拒绝凭据时绑定失败，且不落库。"""

    session, settings = session_settings
    http_client = FakeHttpClient({"getDriveInfo": FakeResponse(401, {})})

    with pytest.raises(CloudCredentialRejectedError):
        create_cloud_account(
            session,
            settings.local_user_id,
            provider="aliyun",
            credential='{"access_token": "access-token-1234"}',
            settings=settings,
            http_client=http_client,
        )

    assert session.query(CloudAccount).count() == 0


def test_aliyun_client_requires_usable_credential() -> None:
    """空凭据直接判定为不可用。"""

    client = build_client("aliyun", "   ")
    with pytest.raises(CredentialInvalidError):
        client.check_credential()


def test_cloud_accounts_api_flow(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """绑定、列出、重复绑定、重新校验与解绑的完整流程。"""

    def fake_verify(
        provider: str,
        credential: str,
        *,
        settings: Settings,
        http_client: object | None = None,
    ) -> AccountInfo:
        return AccountInfo(provider=provider, display_name="测试云盘")

    monkeypatch.setattr(
        cloud_account_service,
        "verify_credential",
        fake_verify,
    )

    created = client.post(
        "/api/v1/cloud-accounts",
        json={
            "provider": "aliyun",
            "credential": "refresh-token-abcdef",
            "default_folder": "/books",
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert body["provider"] == "aliyun"
    assert body["display_name"] == "测试云盘"
    assert body["credential_hint"] == "...cdef"
    assert body["default_folder"] == "/books"
    assert "credential" not in body
    assert "credential_cipher" not in body

    listing = client.get("/api/v1/cloud-accounts")
    assert listing.status_code == 200
    assert [item["id"] for item in listing.json()] == [body["id"]]

    duplicated = client.post(
        "/api/v1/cloud-accounts",
        json={"provider": "aliyun", "credential": "refresh-token-abcdef"},
    )
    assert duplicated.status_code == 409

    verified = client.post(f"/api/v1/cloud-accounts/{body['id']}/verify")
    assert verified.status_code == 200
    assert verified.json()["status"] == "active"

    deleted = client.delete(f"/api/v1/cloud-accounts/{body['id']}")
    assert deleted.status_code == 200
    assert client.get("/api/v1/cloud-accounts").json() == []


def test_cloud_accounts_api_rejects_unknown_provider(client: TestClient) -> None:
    """未支持的服务商直接被请求模型拒绝。"""

    response = client.post(
        "/api/v1/cloud-accounts",
        json={"provider": "weiyun", "credential": "x"},
    )
    assert response.status_code == 422


def test_cloud_accounts_api_requires_credential(client: TestClient) -> None:
    """空凭据被请求模型拒绝。"""

    response = client.post(
        "/api/v1/cloud-accounts",
        json={"provider": "aliyun", "credential": ""},
    )
    assert response.status_code == 422
