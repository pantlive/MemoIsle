"""账号认证接口测试。"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from app.auth_service import ProviderProfile
from app.config import Settings
from app.database import Database
from app.main import create_app
from app.schemas import AuthProvider
from fastapi.testclient import TestClient
from pytest import MonkeyPatch


def create_auth_client(
    tmp_path: Path,
    *,
    auth_dev_mode: bool = False,
) -> TestClient:
    """创建隔离的第三方登录测试客户端。"""

    database_path = tmp_path / "auth-test.db"
    settings = Settings(
        database_url=f"sqlite+pysqlite:///{database_path}",
        cors_origins=("http://localhost:5173",),
        local_user_id="00000000-0000-0000-0000-000000000001",
        auth_dev_mode=auth_dev_mode,
        auth_token_secret="test-auth-token-secret",
        google_client_id="google-client-id",
        google_client_secret="google-client-secret",
        wechat_app_id="wechat-app-id",
        wechat_app_secret="wechat-app-secret",
        apple_client_id="apple-client-id",
        apple_client_secret="apple-client-secret",
        audio_directory=tmp_path / "audio",
        resource_enrichment_enabled=False,
        resource_health_monitor_enabled=False,
    )
    app = create_app(settings=settings, database=Database(settings.database_url))
    return TestClient(app)


def test_third_party_login_issues_bearer_session(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Google 授权码应转换为可撤销的 Bearer 会话。"""

    with create_auth_client(tmp_path) as client:
        providers = client.get("/api/v1/auth/providers").json()
        assert providers["dev_login_available"] is False
        assert {
            item["provider"]: item["enabled"] for item in providers["providers"]
        } == {"google": True, "wechat": True, "apple": True}

        unauthorized = client.get("/api/v1/memos")
        assert unauthorized.status_code == 401

        response = client.get(
            "/api/v1/auth/google/authorize",
            params={"redirect_to": "http://localhost:5173/"},
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert response.headers["location"].startswith(
            "https://accounts.google.com/o/oauth2/v2/auth",
        )
        assert "redirect_uri=http%3A" in response.headers["location"]
        state = response.headers["location"].split("state=", 1)[1].split("&", 1)[0]

        mobile_response = client.get(
            "/api/v1/auth/google/authorize",
            params={"redirect_to": "memoisle://auth/callback"},
            follow_redirects=False,
        )
        assert mobile_response.status_code == 302

        def fake_exchange(
            *_args: Any,
            **_kwargs: Any,
        ) -> ProviderProfile:
            """模拟 Google 已完成授权码交换。"""

            return ProviderProfile(
                provider=AuthProvider.GOOGLE,
                provider_user_id="google-subject",
                display_name="Google 用户",
                email="user@example.com",
                email_verified=True,
            )

        monkeypatch.setattr("app.api.exchange_authorization_code", fake_exchange)
        callback = client.get(
            "/api/v1/auth/google/callback",
            params={"code": "authorization-code", "state": state},
            follow_redirects=False,
        )
        assert callback.status_code == 303
        fragment = parse_qs(urlsplit(callback.headers["location"]).fragment)
        access_token = fragment["access_token"][0]
        headers = {"Authorization": f"Bearer {access_token}"}

        current_user = client.get("/api/v1/auth/me", headers=headers)
        assert current_user.status_code == 200
        assert current_user.json()["email"] == "user@example.com"

        created = client.post(
            "/api/v1/memos",
            headers=headers,
            json={
                "client_id": str(uuid4()),
                "type": "idea",
                "body": "登录后创建的灵感。",
            },
        )
        assert created.status_code == 201

        logout = client.post("/api/v1/auth/logout", headers=headers)
        assert logout.status_code == 200
        assert logout.json()["revoked"] is True
        assert client.get("/api/v1/auth/me", headers=headers).status_code == 401


def test_dev_login_is_available_only_when_enabled(tmp_path: Path) -> None:
    """本地开发登录必须显式开启。"""

    with create_auth_client(tmp_path / "disabled", auth_dev_mode=False) as client:
        assert client.post("/api/v1/auth/dev-login").status_code == 404

    with create_auth_client(tmp_path / "enabled", auth_dev_mode=True) as client:
        response = client.post("/api/v1/auth/dev-login")
        assert response.status_code == 200
        token = response.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        assert client.get("/api/v1/auth/me", headers=headers).status_code == 200


def test_email_register_login_and_reject_wrong_password(tmp_path: Path) -> None:
    """邮箱账号支持注册、登录和错误密码拒绝。"""

    with create_auth_client(tmp_path) as client:
        register = client.post(
            "/api/v1/auth/register",
            json={
                "email": "User@Example.com",
                "password": "memoisle-password",
                "confirm_password": "memoisle-password",
                "display_name": "邮箱用户",
            },
        )
        assert register.status_code == 201
        assert register.json()["user"]["display_name"] == "邮箱用户"
        token = register.json()["access_token"]
        assert (
            client.get(
                "/api/v1/auth/me",
                headers={"Authorization": f"Bearer {token}"},
            ).status_code
            == 200
        )

        duplicate = client.post(
            "/api/v1/auth/register",
            json={
                "email": "user@example.com",
                "password": "another-password",
                "confirm_password": "another-password",
            },
        )
        assert duplicate.status_code == 409

        mismatched_password = client.post(
            "/api/v1/auth/register",
            json={
                "email": "another@example.com",
                "password": "memoisle-password",
                "confirm_password": "different-password",
            },
        )
        assert mismatched_password.status_code == 422

        login = client.post(
            "/api/v1/auth/login",
            json={"email": "user@example.com", "password": "memoisle-password"},
        )
        assert login.status_code == 200
        assert login.json()["access_token"]

        wrong_password = client.post(
            "/api/v1/auth/login",
            json={"email": "user@example.com", "password": "wrong-password"},
        )
        assert wrong_password.status_code == 401

        unknown_email = client.post(
            "/api/v1/auth/login",
            json={"email": "unknown@example.com", "password": "wrong-password"},
        )
        assert unknown_email.status_code == 401
