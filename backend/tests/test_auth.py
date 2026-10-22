"""账号认证接口测试。"""

from __future__ import annotations

from email import policy
from email.parser import BytesParser
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


def read_outbox_token(
    outbox_directory: Path,
    purpose: str,
) -> str:
    """从开发收件箱读取指定用途的一次性令牌。"""

    query_name = (
        "verification_token" if purpose == "verify_email" else "reset_token"
    )
    for email_file in sorted(outbox_directory.glob("*.eml")):
        message = BytesParser(policy=policy.default).parsebytes(
            email_file.read_bytes(),
        )
        body = message.get_body(preferencelist=("plain",)).get_content()
        if purpose == "verify_email" and "验证" not in body:
            continue
        if purpose == "password_reset" and "重置" not in body:
            continue
        for line in body.splitlines():
            if line.startswith(f"http://localhost:5173/?{query_name}="):
                return parse_qs(urlsplit(line.strip()).query)[query_name][0]
    raise AssertionError(f"未找到 {purpose} 邮件")


def read_outbox_verification_code(outbox_directory: Path) -> str:
    """从开发收件箱读取六位注册验证码。"""

    for email_file in sorted(outbox_directory.glob("*.eml")):
        message = BytesParser(policy=policy.default).parsebytes(
            email_file.read_bytes(),
        )
        body = message.get_body(preferencelist=("plain",)).get_content()
        if "注册验证码" not in body:
            continue
        for line in body.splitlines():
            candidate = line.strip()
            if len(candidate) == 6 and candidate.isdigit():
                return candidate
    raise AssertionError("未找到注册验证码邮件")


def create_auth_client(
    tmp_path: Path,
    *,
    auth_dev_mode: bool = False,
    oauth_login_enabled: bool = False,
) -> TestClient:
    """创建隔离的认证测试客户端。"""

    database_path = tmp_path / "auth-test.db"
    settings = Settings(
        database_url=f"sqlite+pysqlite:///{database_path}",
        cors_origins=("http://localhost:5173",),
        web_base_url="http://localhost:5173",
        local_user_id="00000000-0000-0000-0000-000000000001",
        auth_dev_mode=auth_dev_mode,
        auth_token_secret="test-auth-token-secret",
        google_client_id="google-client-id",
        google_client_secret="google-client-secret",
        wechat_app_id="wechat-app-id",
        wechat_app_secret="wechat-app-secret",
        apple_client_id="apple-client-id",
        apple_client_secret="apple-client-secret",
        oauth_login_enabled=oauth_login_enabled,
        audio_directory=tmp_path / "audio",
        email_outbox_directory=tmp_path / "email-outbox",
        email_provider="outbox",
        resource_enrichment_enabled=False,
        resource_health_monitor_enabled=False,
    )
    app = create_app(settings=settings, database=Database(settings.database_url))
    return TestClient(app)


def test_third_party_login_is_disabled_by_default(tmp_path: Path) -> None:
    """未显式开启时，即使配置了凭据也不开放微信、Google、Apple 登录。"""

    with create_auth_client(tmp_path) as client:
        providers = client.get("/api/v1/auth/providers").json()
        assert providers["email_login_enabled"] is True
        assert {
            item["provider"]: item["enabled"] for item in providers["providers"]
        } == {"google": False, "wechat": False, "apple": False}
        response = client.get(
            "/api/v1/auth/google/authorize",
            params={"redirect_to": "http://localhost:5173/"},
            follow_redirects=False,
        )
        assert response.status_code == 404


def test_third_party_login_issues_bearer_session(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """显式开启后，Google 授权码应转换为可撤销的 Bearer 会话。"""

    with create_auth_client(tmp_path, oauth_login_enabled=True) as client:
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
        assert current_user.json()["email_verified"] is True

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

    with create_auth_client(tmp_path, auth_dev_mode=True) as client:
        verification_request = client.post(
            "/api/v1/auth/verification-code",
            json={"email": "User@Example.com"},
        )
        assert verification_request.status_code == 202
        verification_code = read_outbox_verification_code(
            tmp_path / "email-outbox",
        )
        register = client.post(
            "/api/v1/auth/register",
            json={
                "email": "User@Example.com",
                "password": "memoisle-password",
                "confirm_password": "memoisle-password",
                "verification_code": verification_code,
                "display_name": "邮箱用户",
            },
        )
        assert register.status_code == 201
        assert register.json()["user"]["display_name"] == "邮箱用户"
        assert register.json()["user"]["email"] == "user@example.com"
        assert register.json()["user"]["email_verified"] is True

        login = client.post(
            "/api/v1/auth/login",
            json={"email": "user@example.com", "password": "memoisle-password"},
        )
        assert login.status_code == 200
        duplicate = client.post(
            "/api/v1/auth/register",
            json={
                "email": "user@example.com",
                "password": "another-password",
                "confirm_password": "another-password",
                "verification_code": "000000",
            },
        )
        assert duplicate.status_code == 409

        mismatched_password = client.post(
            "/api/v1/auth/register",
            json={
                "email": "another@example.com",
                "password": "memoisle-password",
                "confirm_password": "different-password",
                "verification_code": "000000",
            },
        )
        assert mismatched_password.status_code == 422

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


def test_verification_code_resend_is_rate_limited(tmp_path: Path) -> None:
    """同一邮箱在重发间隔内再次请求应返回 429。"""

    with create_auth_client(tmp_path, auth_dev_mode=True) as client:
        first = client.post(
            "/api/v1/auth/verification-code",
            json={"email": "resend@example.com"},
        )
        assert first.status_code == 202
        second = client.post(
            "/api/v1/auth/verification-code",
            json={"email": "resend@example.com"},
        )
        assert second.status_code == 429
        assert second.headers["Retry-After"]


def test_unconsumed_verification_code_is_unique_per_email(tmp_path: Path) -> None:
    """同一邮箱同时只能有一条未消费验证码。"""

    from datetime import timedelta

    from app.models import AuthVerificationCode, utc_now
    from sqlalchemy.exc import IntegrityError

    database = Database(f"sqlite+pysqlite:///{tmp_path / 'code.db'}")
    database.create_schema()
    now = utc_now()
    with database.session_factory() as session:
        session.add(
            AuthVerificationCode(
                id=str(uuid4()),
                email="unique@example.com",
                code_hash="a" * 64,
                sent_at=now,
                expires_at=now + timedelta(minutes=10),
                attempt_count=0,
            ),
        )
        session.commit()
        session.add(
            AuthVerificationCode(
                id=str(uuid4()),
                email="unique@example.com",
                code_hash="b" * 64,
                sent_at=now,
                expires_at=now + timedelta(minutes=10),
                attempt_count=0,
            ),
        )
        try:
            session.commit()
            raise AssertionError("应拒绝第二条未消费验证码")
        except IntegrityError:
            session.rollback()


def test_password_reset_updates_password_and_revokes_sessions(tmp_path: Path) -> None:
    """密码重置链接应更新密码、验证邮箱并撤销旧会话。"""

    with create_auth_client(tmp_path, auth_dev_mode=True) as client:
        verification_request = client.post(
            "/api/v1/auth/verification-code",
            json={"email": "reset@example.com"},
        )
        assert verification_request.status_code == 202
        verification_code = read_outbox_verification_code(
            tmp_path / "email-outbox",
        )
        register = client.post(
            "/api/v1/auth/register",
            json={
                "email": "reset@example.com",
                "password": "old-password",
                "confirm_password": "old-password",
                "verification_code": verification_code,
            },
        )
        assert register.status_code == 201
        old_session = client.post(
            "/api/v1/auth/login",
            json={"email": "reset@example.com", "password": "old-password"},
        )
        assert old_session.status_code == 200
        old_token = old_session.json()["access_token"]

        assert (
            client.post(
                "/api/v1/auth/password-reset/request",
                json={"email": "reset@example.com"},
            ).status_code
            == 202
        )
        assert (
            client.post(
                "/api/v1/auth/password-reset/request",
                json={"email": "unknown@example.com"},
            ).status_code
            == 202
        )
        reset_token = read_outbox_token(
            tmp_path / "email-outbox",
            "password_reset",
        )
        mismatched = client.post(
            "/api/v1/auth/password-reset",
            json={
                "token": reset_token,
                "password": "new-password",
                "confirm_password": "different-password",
            },
        )
        assert mismatched.status_code == 422

        reset = client.post(
            "/api/v1/auth/password-reset",
            json={
                "token": reset_token,
                "password": "new-password",
                "confirm_password": "new-password",
            },
        )
        assert reset.status_code == 200
        assert (
            client.get(
                "/api/v1/auth/me",
                headers={"Authorization": f"Bearer {old_token}"},
            ).status_code
            == 401
        )
        old_login = client.post(
            "/api/v1/auth/login",
            json={"email": "reset@example.com", "password": "old-password"},
        )
        assert old_login.status_code == 401
        new_login = client.post(
            "/api/v1/auth/login",
            json={"email": "reset@example.com", "password": "new-password"},
        )
        assert new_login.status_code == 200
        assert new_login.json()["user"]["email_verified"] is True


def test_login_is_rate_limited_after_repeated_failures(tmp_path: Path) -> None:
    """连续失败登录应触发临时限制。"""

    with create_auth_client(tmp_path, auth_dev_mode=True) as client:
        verification_request = client.post(
            "/api/v1/auth/verification-code",
            json={"email": "limit@example.com"},
        )
        assert verification_request.status_code == 202
        verification_code = read_outbox_verification_code(
            tmp_path / "email-outbox",
        )
        register = client.post(
            "/api/v1/auth/register",
            json={
                "email": "limit@example.com",
                "password": "memoisle-password",
                "confirm_password": "memoisle-password",
                "verification_code": verification_code,
            },
        )
        assert register.status_code == 201

        for _ in range(5):
            failed = client.post(
                "/api/v1/auth/login",
                json={"email": "limit@example.com", "password": "wrong-password"},
            )
            assert failed.status_code == 401

        limited = client.post(
            "/api/v1/auth/login",
            json={"email": "limit@example.com", "password": "memoisle-password"},
        )
        assert limited.status_code == 429
        assert limited.headers["Retry-After"] == "900"


def _register(client: TestClient, tmp_path: Path, email: str) -> None:
    client.post("/api/v1/auth/verification-code", json={"email": email})
    code = read_outbox_verification_code(tmp_path / "email-outbox")
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "pw-12345678",
            "confirm_password": "pw-12345678",
            "verification_code": code,
        },
    )
    assert response.status_code == 201


def test_password_reset_requests_are_throttled_per_account(tmp_path: Path) -> None:
    """匿名的重置请求不能对同一邮箱无限发信，也不能让已发链接失效。"""

    with create_auth_client(tmp_path, auth_dev_mode=True) as client:
        _register(client, tmp_path, "flood@example.com")
        outbox = tmp_path / "email-outbox"
        before = len(list(outbox.glob("*.eml")))

        statuses = {
            client.post(
                "/api/v1/auth/password-reset/request",
                json={"email": "flood@example.com"},
            ).status_code
            for _ in range(20)
        }

        # 接口始终返回成功，不暴露节流状态。
        assert statuses == {202}
        assert len(list(outbox.glob("*.eml"))) - before == 1
        # 第一封邮件里的链接仍然有效。
        token = read_outbox_token(outbox, "password_reset")
        reset = client.post(
            "/api/v1/auth/password-reset",
            json={
                "token": token,
                "password": "new-password-1",
                "confirm_password": "new-password-1",
            },
        )
        assert reset.status_code == 200


def test_reset_can_be_requested_again_after_cooldown(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """过了重发间隔可以再次请求。"""

    from datetime import timedelta

    import app.auth_service as auth_service

    with create_auth_client(tmp_path, auth_dev_mode=True) as client:
        _register(client, tmp_path, "later@example.com")
        outbox = tmp_path / "email-outbox"
        client.post(
            "/api/v1/auth/password-reset/request",
            json={"email": "later@example.com"},
        )
        sent = len(list(outbox.glob("*.eml")))

        real_now = auth_service.utc_now
        monkeypatch.setattr(
            auth_service,
            "utc_now",
            lambda: real_now() + timedelta(minutes=5),
        )
        client.post(
            "/api/v1/auth/password-reset/request",
            json={"email": "later@example.com"},
        )
        assert len(list(outbox.glob("*.eml"))) == sent + 1
