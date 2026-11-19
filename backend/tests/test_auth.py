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
    """从开发收件箱读取最新一封六位注册验证码。"""

    files = sorted(
        outbox_directory.glob("*.eml"),
        key=lambda path: (path.stat().st_mtime, path.name),
        reverse=True,
    )
    for email_file in files:
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
    auth_invite_required: bool = True,
) -> TestClient:
    """创建隔离的认证测试客户端。"""

    database_path = tmp_path / "auth-test.db"
    settings = Settings(
        database_url=f"sqlite+pysqlite:///{database_path}",
        cors_origins=("http://localhost:5173",),
        web_base_url="http://localhost:5173",
        local_user_id="00000000-0000-0000-0000-000000000001",
        auth_dev_mode=auth_dev_mode,
        auth_invite_required=auth_invite_required,
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


def issue_invitation(client: TestClient) -> str:
    """注册引导账号并生成一次性邀请码。同一测试库只调用一次。"""

    from app.auth_service import create_invitation, register_with_password

    database: Database = client.app.state.database
    settings = client.app.state.settings
    with database.session_factory() as session:
        user = register_with_password(
            session,
            settings,
            "inviter@example.com",
            "inviter-password",
            "邀请人",
        )
        created = create_invitation(session, settings, user.id)
    return created.code


def register_with_invite(
    client: TestClient,
    tmp_path: Path,
    email: str,
    *,
    password: str,
    display_name: str | None = None,
    invite_code: str | None = None,
) -> dict[str, Any]:
    """先造出已有用户和邀请码，再走验证码注册。"""

    code = invite_code or issue_invitation(client)
    verification = client.post(
        "/api/v1/auth/verification-code",
        json={"email": email, "invite_code": code},
    )
    assert verification.status_code == 202, verification.text
    verification_code = read_outbox_verification_code(tmp_path / "email-outbox")
    payload: dict[str, Any] = {
        "email": email,
        "password": password,
        "confirm_password": password,
        "verification_code": verification_code,
        "invite_code": code,
    }
    if display_name is not None:
        payload["display_name"] = display_name
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_third_party_login_is_disabled_by_default(tmp_path: Path) -> None:
    """未显式开启时，即使配置了凭据也不开放微信、Google、Apple 登录。"""

    with create_auth_client(tmp_path) as client:
        providers = client.get("/api/v1/auth/providers").json()
        assert providers["email_login_enabled"] is True
        assert providers["invite_required"] is False
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

        monkeypatch.setattr(
            "app.routes.auth.exchange_authorization_code",
            fake_exchange,
        )
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
        registered = register_with_invite(
            client,
            tmp_path,
            "User@Example.com",
            password="memoisle-password",
            display_name="邮箱用户",
        )
        assert registered["user"]["display_name"] == "邮箱用户"
        assert registered["user"]["email"] == "user@example.com"
        assert registered["user"]["email_verified"] is True

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
        invite_code = issue_invitation(client)
        first = client.post(
            "/api/v1/auth/verification-code",
            json={"email": "resend@example.com", "invite_code": invite_code},
        )
        assert first.status_code == 202
        second = client.post(
            "/api/v1/auth/verification-code",
            json={"email": "resend@example.com", "invite_code": invite_code},
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
        register_with_invite(
            client,
            tmp_path,
            "reset@example.com",
            password="old-password",
        )
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
        register_with_invite(
            client,
            tmp_path,
            "limit@example.com",
            password="memoisle-password",
        )

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
    register_with_invite(
        client,
        tmp_path,
        email,
        password="pw-12345678",
    )


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


def _code_in_email(path: Path) -> str:
    """从一封邮件里取出六位注册验证码。"""

    message = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
    body = message.get_body(preferencelist=("plain",)).get_content()
    for line in body.splitlines():
        candidate = line.strip()
        if len(candidate) == 6 and candidate.isdigit():
            return candidate
    raise AssertionError("未找到注册验证码邮件")


def _request_code(
    client: TestClient,
    tmp_path: Path,
    email: str,
    invite_code: str | None = None,
) -> str:
    """发送验证码并只读取这次新产生的邮件。"""

    outbox = tmp_path / "email-outbox"
    before = set(outbox.glob("*.eml")) if outbox.exists() else set()
    payload: dict[str, str] = {"email": email}
    if invite_code is not None:
        payload["invite_code"] = invite_code
    response = client.post("/api/v1/auth/verification-code", json=payload)
    assert response.status_code == 202, response.text
    created = [path for path in outbox.glob("*.eml") if path not in before]
    assert len(created) == 1
    return _code_in_email(created[0])


def _register_open(
    client: TestClient,
    tmp_path: Path,
    email: str,
    password: str,
    display_name: str | None = None,
) -> None:
    """在还没有真实账号时，不带邀请码完成注册。"""

    verification_code = _request_code(client, tmp_path, email)
    payload: dict[str, str] = {
        "email": email,
        "password": password,
        "confirm_password": password,
        "verification_code": verification_code,
    }
    if display_name is not None:
        payload["display_name"] = display_name
    registered = client.post("/api/v1/auth/register", json=payload)
    assert registered.status_code == 201, registered.text


def test_auth_invite_required_follows_environment(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """布尔开关与现有环境变量使用同一套解析。"""

    monkeypatch.setenv(
        "MEMOISLE_DATABASE_URL",
        f"sqlite+pysqlite:///{tmp_path / 'invite-config.db'}",
    )
    monkeypatch.setenv("MEMOISLE_AUTH_TOKEN_SECRET", "test-auth-token-secret")
    monkeypatch.delenv("MEMOISLE_AUTH_INVITE_REQUIRED", raising=False)
    assert Settings.from_environment().auth_invite_required is True
    monkeypatch.setenv("MEMOISLE_AUTH_INVITE_REQUIRED", "no")
    assert Settings.from_environment().auth_invite_required is False
    monkeypatch.setenv("MEMOISLE_AUTH_INVITE_REQUIRED", "on")
    assert Settings.from_environment().auth_invite_required is True


def test_first_real_account_registers_without_invite(tmp_path: Path) -> None:
    """本地开发用户不算第一个真实账号，之后注册必须有邀请码。"""

    with create_auth_client(tmp_path, auth_dev_mode=True) as client:
        assert client.post("/api/v1/auth/dev-login").status_code == 200
        assert client.get("/api/v1/auth/providers").json()["invite_required"] is False
        _register_open(
            client,
            tmp_path,
            "first@example.com",
            "memoisle-password",
            "第一位",
        )
        assert client.get("/api/v1/auth/providers").json()["invite_required"] is True
        missing = client.post(
            "/api/v1/auth/verification-code",
            json={"email": "second@example.com"},
        )
        assert missing.status_code == 400
        assert missing.json()["detail"] == "邀请码无效或已被使用"


def test_invalid_invite_is_rejected_without_consuming_code(tmp_path: Path) -> None:
    """没有邀请码或邀请码错误时，验证码和注册都返回 400，且验证码不被消费。"""

    from app.models import AuthVerificationCode
    from sqlalchemy import select

    with create_auth_client(tmp_path, auth_dev_mode=True) as client:
        invite_code = issue_invitation(client)
        outbox = tmp_path / "email-outbox"
        before = set(outbox.glob("*.eml")) if outbox.exists() else set()
        for payload in (
            {"email": "guest@example.com"},
            {"email": "guest@example.com", "invite_code": "not-a-code"},
        ):
            rejected = client.post("/api/v1/auth/verification-code", json=payload)
            assert rejected.status_code == 400
            assert rejected.json()["detail"] == "邀请码无效或已被使用"
        assert set(outbox.glob("*.eml")) == before

        verification_code = _request_code(
            client,
            tmp_path,
            "guest@example.com",
            invite_code,
        )
        for invite in (None, "not-a-code"):
            body: dict[str, str] = {
                "email": "guest@example.com",
                "password": "memoisle-password",
                "confirm_password": "memoisle-password",
                "verification_code": verification_code,
            }
            if invite is not None:
                body["invite_code"] = invite
            rejected = client.post("/api/v1/auth/register", json=body)
            assert rejected.status_code == 400
            assert rejected.json()["detail"] == "邀请码无效或已被使用"
        database: Database = client.app.state.database
        with database.session_factory() as session:
            stored = session.scalar(
                select(AuthVerificationCode).where(
                    AuthVerificationCode.email == "guest@example.com",
                ),
            )
            assert stored is not None
            assert stored.consumed_at is None
        accepted = client.post(
            "/api/v1/auth/register",
            json={
                "email": "guest@example.com",
                "password": "memoisle-password",
                "confirm_password": "memoisle-password",
                "verification_code": verification_code,
                "invite_code": invite_code,
            },
        )
        assert accepted.status_code == 201


def test_invitation_code_can_register_only_one_account(tmp_path: Path) -> None:
    """同一个邀请码第二次使用返回 400。"""

    with create_auth_client(tmp_path, auth_dev_mode=True) as client:
        invite_code = issue_invitation(client)
        register_with_invite(
            client,
            tmp_path,
            "first-guest@example.com",
            password="memoisle-password",
            invite_code=invite_code,
        )
        reused = client.post(
            "/api/v1/auth/verification-code",
            json={
                "email": "second-guest@example.com",
                "invite_code": invite_code,
            },
        )
        assert reused.status_code == 400
        assert reused.json()["detail"] == "邀请码无效或已被使用"


def test_user_can_create_only_one_invitation(tmp_path: Path) -> None:
    """同一个用户第二次生成邀请码返回 409，使用前后的状态都正确。"""

    from app.models import User
    from sqlalchemy import select

    with create_auth_client(tmp_path, auth_dev_mode=True) as client:
        _register_open(
            client,
            tmp_path,
            "owner@example.com",
            "memoisle-password",
            "岛主",
        )
        login = client.post(
            "/api/v1/auth/login",
            json={"email": "owner@example.com", "password": "memoisle-password"},
        )
        assert login.status_code == 200
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        # 开发模式不带凭证会回退本地用户，用无效令牌确认接口要求登录。
        anonymous = client.get(
            "/api/v1/auth/invitations",
            headers={"Authorization": "Bearer not-a-session"},
        )
        assert anonymous.status_code == 401
        before = client.get("/api/v1/auth/invitations", headers=headers)
        assert before.status_code == 200
        assert before.json() == {
            "remaining": 1,
            "created_at": None,
            "used_at": None,
            "used_by_label": None,
        }
        created = client.post("/api/v1/auth/invitations", headers=headers)
        assert created.status_code == 201
        invite_code = created.json()["code"]
        assert len(invite_code) == 10
        assert invite_code == invite_code.upper()
        waiting = client.get("/api/v1/auth/invitations", headers=headers)
        assert waiting.status_code == 200
        assert waiting.json()["remaining"] == 0
        assert waiting.json()["created_at"]
        assert waiting.json()["used_at"] is None
        assert waiting.json()["used_by_label"] is None
        assert invite_code not in waiting.text
        register_with_invite(
            client,
            tmp_path,
            "friend@example.com",
            password="memoisle-password",
            display_name="新朋友",
            invite_code=invite_code,
        )
        used = client.get("/api/v1/auth/invitations", headers=headers)
        assert used.json()["remaining"] == 0
        assert used.json()["used_at"]
        assert used.json()["used_by_label"] == "新朋友"
        assert invite_code not in used.text
        duplicate = client.post("/api/v1/auth/invitations", headers=headers)
        assert duplicate.status_code == 409
        assert duplicate.json()["detail"] == "邀请机会已用完"

        database: Database = client.app.state.database
        with database.session_factory() as session:
            friend = session.scalar(
                select(User).where(User.email == "friend@example.com"),
            )
            assert friend is not None
            friend.display_name = ""
            session.commit()
        masked = client.get("/api/v1/auth/invitations", headers=headers)
        assert masked.json()["used_by_label"] == "f***@example.com"


def test_provider_login_cannot_skip_invitation(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """开启邀请制后，第三方登录不能新建账号，已有账号仍可登录。"""

    existing = ProviderProfile(
        provider=AuthProvider.GOOGLE,
        provider_user_id="existing-subject",
        display_name="已有用户",
        email="existing@example.com",
        email_verified=True,
    )
    holder = {"profile": existing}

    def fake_exchange(*_args: Any, **_kwargs: Any) -> ProviderProfile:
        return holder["profile"]

    monkeypatch.setattr(
        "app.routes.auth.exchange_authorization_code",
        fake_exchange,
    )
    with create_auth_client(tmp_path, oauth_login_enabled=True) as client:
        authorized = client.get(
            "/api/v1/auth/google/authorize",
            params={"redirect_to": "http://localhost:5173/"},
            follow_redirects=False,
        )
        state = authorized.headers["location"].split("state=", 1)[1].split("&", 1)[0]
        first = client.get(
            "/api/v1/auth/google/callback",
            params={"code": "authorization-code", "state": state},
            follow_redirects=False,
        )
        assert first.status_code == 303
        assert "access_token" in first.headers["location"]
        holder["profile"] = ProviderProfile(
            provider=AuthProvider.GOOGLE,
            provider_user_id="new-subject",
            display_name="新用户",
            email="new@example.com",
            email_verified=True,
        )
        blocked = client.get(
            "/api/v1/auth/google/callback",
            params={"code": "another-code", "state": state},
            follow_redirects=False,
        )
        fragment = parse_qs(urlsplit(blocked.headers["location"]).fragment)
        assert fragment["auth_error"][0] == (
            "当前仅支持邀请注册，请先用邀请码通过邮箱注册"
        )
        holder["profile"] = existing
        again = client.get(
            "/api/v1/auth/google/callback",
            params={"code": "return-code", "state": state},
            follow_redirects=False,
        )
        assert again.status_code == 303
        fragment = parse_qs(urlsplit(again.headers["location"]).fragment)
        token = fragment["access_token"][0]
        current = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert current.status_code == 200
        assert current.json()["email"] == "existing@example.com"


def test_disabling_invite_requirement_restores_open_registration(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """关闭开关后，邮箱注册和第三方新建账号都不再要邀请码。"""

    profile = ProviderProfile(
        provider=AuthProvider.GOOGLE,
        provider_user_id="open-subject",
        display_name="开放用户",
        email="open@example.com",
        email_verified=True,
    )
    monkeypatch.setattr(
        "app.routes.auth.exchange_authorization_code",
        lambda *_args, **_kwargs: profile,
    )
    with create_auth_client(
        tmp_path,
        auth_dev_mode=True,
        oauth_login_enabled=True,
        auth_invite_required=False,
    ) as client:
        _register_open(client, tmp_path, "one@example.com", "memoisle-password")
        _register_open(client, tmp_path, "two@example.com", "memoisle-password")
        assert client.get("/api/v1/auth/providers").json()["invite_required"] is False
        authorized = client.get(
            "/api/v1/auth/google/authorize",
            params={"redirect_to": "http://localhost:5173/"},
            follow_redirects=False,
        )
        state = authorized.headers["location"].split("state=", 1)[1].split("&", 1)[0]
        callback = client.get(
            "/api/v1/auth/google/callback",
            params={"code": "open-code", "state": state},
            follow_redirects=False,
        )
        assert callback.status_code == 303
        assert "access_token" in callback.headers["location"]


def test_only_one_session_can_consume_an_invitation(tmp_path: Path) -> None:
    """两个会话先后消费同一个邀请码时，只有先提交的成功。"""

    from app.auth_service import InvitationInvalidError, register_with_password

    with create_auth_client(tmp_path) as client:
        invite_code = issue_invitation(client)
        database: Database = client.app.state.database
        settings = client.app.state.settings
        sessions = [database.session_factory() for _ in range(2)]
        outcomes: list[str] = []
        try:
            for index, session in enumerate(sessions):
                try:
                    register_with_password(
                        session,
                        settings,
                        f"racer-{index}@example.com",
                        "password-123",
                        invite_code=invite_code,
                    )
                    outcomes.append("ok")
                except InvitationInvalidError:
                    outcomes.append("invalid")
        finally:
            for session in sessions:
                session.close()
        assert outcomes == ["ok", "invalid"]


def test_invite_code_match_ignores_case_and_whitespace(tmp_path: Path) -> None:
    """邀请码比对前会转成大写并去掉空白。"""

    with create_auth_client(tmp_path, auth_dev_mode=True) as client:
        invite_code = issue_invitation(client)
        messy = f" {invite_code[:5].lower()} {invite_code[5:].lower()} "
        register_with_invite(
            client,
            tmp_path,
            "spaced@example.com",
            password="memoisle-password",
            invite_code=messy,
        )


def test_invitation_inviter_is_unique(tmp_path: Path) -> None:
    """数据库唯一约束保证每个用户只有一条邀请记录。"""

    from app.models import AuthInvitation, User, utc_now
    from sqlalchemy.exc import IntegrityError

    database = Database(f"sqlite+pysqlite:///{tmp_path / 'invite-unique.db'}")
    database.create_schema()
    user_id = str(uuid4())
    now = utc_now()
    with database.session_factory() as session:
        session.add(User(id=user_id, display_name="邀请人"))
        session.add(
            AuthInvitation(
                id=str(uuid4()),
                inviter_user_id=user_id,
                code_hash="a" * 64,
                created_at=now,
            ),
        )
        session.commit()
        session.add(
            AuthInvitation(
                id=str(uuid4()),
                inviter_user_id=user_id,
                code_hash="b" * 64,
                created_at=now,
            ),
        )
        try:
            session.commit()
            raise AssertionError("应拒绝第二条邀请记录")
        except IntegrityError:
            session.rollback()
