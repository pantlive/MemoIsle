"""修改登录密码的身份校验、会话撤销和失败限流回归测试。"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from app.auth_service import register_with_password, request_password_reset_token
from app.config import Settings
from app.database import Database
from app.main import create_app
from fastapi.testclient import TestClient


@pytest.fixture
def password_client(tmp_path: Path) -> Iterator[TestClient]:
    """使用关闭开发登录的隔离数据库，避免依赖真实账号或邮件服务。"""

    settings = Settings(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'password.db'}",
        cors_origins=(),
        local_user_id="development-user",
        audio_directory=tmp_path / "audio",
        image_directory=tmp_path / "images",
        auth_token_secret="password-change-test-secret",
        resource_enrichment_enabled=False,
        resource_health_monitor_enabled=False,
    )
    with TestClient(create_app(settings=settings)) as client:
        yield client


def create_account(
    client: TestClient,
    email: str = "owner@example.com",
) -> str:
    """直接准备测试账号，通过正常登录接口取得访问令牌。"""

    database: Database = client.app.state.database
    with database.session_factory() as session:
        register_with_password(
            session, client.app.state.settings, email, "original-password",
        )
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "original-password"},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def password_payload(current_password: str = "original-password") -> dict[str, str]:
    """生成与真实账号无关的修改密码请求。"""

    return {
        "current_password": current_password,
        "password": "replacement-password",
        "confirm_password": "replacement-password",
    }


def test_password_change_requires_login(password_client: TestClient) -> None:
    """没有 Bearer 会话不能修改密码。"""

    response = password_client.post(
        "/api/v1/auth/password-change", json=password_payload(),
    )
    assert response.status_code == 401


def test_password_change_revokes_own_sessions_and_reset_links(
    password_client: TestClient,
) -> None:
    """改密撤销自身全部会话及旧重置链接，其他账号继续有效。"""

    client = password_client
    token = create_account(client)
    other_token = create_account(client, "other@example.com")
    second_token = client.post(
        "/api/v1/auth/login",
        json={"email": "owner@example.com", "password": "original-password"},
    ).json()["access_token"]
    database: Database = client.app.state.database
    with database.session_factory() as session:
        reset_result = request_password_reset_token(
            session, client.app.state.settings, "owner@example.com",
        )
        assert reset_result is not None
        _, reset_token = reset_result

    response = client.post(
        "/api/v1/auth/password-change",
        headers={"Authorization": f"Bearer {token}"},
        json=password_payload(),
    )
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    for revoked in [token, second_token]:
        assert client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {revoked}"},
        ).status_code == 401
    assert client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {other_token}"},
    ).status_code == 200
    assert client.post(
        "/api/v1/auth/login",
        json={"email": "owner@example.com", "password": "original-password"},
    ).status_code == 401
    assert client.post(
        "/api/v1/auth/login",
        json={"email": "owner@example.com", "password": "replacement-password"},
    ).status_code == 200
    assert client.post(
        "/api/v1/auth/password-reset",
        json={
            "token": reset_token,
            "password": "third-password",
            "confirm_password": "third-password",
        },
    ).status_code == 400


def test_wrong_current_password_preserves_session_and_is_rate_limited(
    password_client: TestClient,
) -> None:
    """错误当前密码不退出有效会话，但连续猜测会被限流。"""

    client = password_client
    token = create_account(client)
    headers = {"Authorization": f"Bearer {token}"}
    for _ in range(5):
        response = client.post(
            "/api/v1/auth/password-change",
            headers=headers,
            json=password_payload("incorrect-password"),
        )
        assert response.status_code == 400
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 200
    limited = client.post(
        "/api/v1/auth/password-change", headers=headers, json=password_payload(),
    )
    assert limited.status_code == 429
    assert int(limited.headers["Retry-After"]) > 0


@pytest.mark.parametrize(
    "patch",
    [
        {"confirm_password": "different-password"},
        {"password": "short", "confirm_password": "short"},
        {"password": "original-password", "confirm_password": "original-password"},
    ],
)
def test_invalid_new_password_does_not_change_credentials(
    password_client: TestClient,
    patch: dict[str, str],
) -> None:
    """两次不一致、过短或与旧密码相同的请求不修改凭据。"""

    token = create_account(password_client)
    headers = {"Authorization": f"Bearer {token}"}
    response = password_client.post(
        "/api/v1/auth/password-change",
        headers=headers,
        json={**password_payload(), **patch},
    )
    assert response.status_code == 422
    assert password_client.post(
        "/api/v1/auth/login",
        json={"email": "owner@example.com", "password": "original-password"},
    ).status_code == 200
