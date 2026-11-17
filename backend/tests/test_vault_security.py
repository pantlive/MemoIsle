"""密码库二次验证：网页白名单和 4 小时，手机 24 小时且不限制 IP。"""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from email import message_from_bytes
from email.policy import default as email_default_policy
from pathlib import Path

import pytest
from app.models import User, VaultAccessGrant, VaultChallenge, VaultSecuritySetting
from app.vault_security_service import (
    VAULT_CLIENT_COOKIE,
    client_ip,
    totp_at,
    verify_totp,
)
from fastapi.testclient import TestClient
from sqlalchemy import select

OWNER_EMAIL = "vault-owner@example.com"
WEB_IP = "203.0.113.10"
OTHER_IP = "198.51.100.20"


def _use_ip(monkeypatch: pytest.MonkeyPatch, ip: str) -> None:
    monkeypatch.setattr("app.vault_security_service.client_ip", lambda _request: ip)


def _set_vault_cookie(client: TestClient, token: str) -> None:
    """TestClient 主机名没有点，带 domain 的 Cookie 不会被送回去。"""

    for cookie in list(client.cookies.jar):
        if cookie.name == VAULT_CLIENT_COOKIE:
            client.cookies.jar.clear(cookie.domain, cookie.path, cookie.name)
    client.cookies.set(VAULT_CLIENT_COOKIE, token)


def _keep_vault_cookie(client: TestClient) -> None:
    """把验证接口写下的 Cookie 改成不带域名，后续请求才会带上。"""

    def _rebind(response: object) -> None:
        del response
        token = None
        for cookie in list(client.cookies.jar):
            if cookie.name == VAULT_CLIENT_COOKIE and cookie.value:
                token = cookie.value
        if token:
            _set_vault_cookie(client, token)

    client.event_hooks["response"].append(_rebind)


@pytest.fixture
def vault_client(client: TestClient, tmp_path: Path) -> TestClient:
    """固定白名单、开发收件箱和可立即重发的验证码。"""

    settings = client.app.state.settings
    client.app.state.settings = replace(
        settings,
        vault_web_ip_allowlist=f"{WEB_IP}/32",
        email_outbox_directory=tmp_path / "outbox",
        auth_verification_code_resend_seconds=0,
        auth_dev_mode=True,
    )
    with client.app.state.database.session_factory() as session:
        user = session.get(User, settings.local_user_id)
        if user is None:
            user = User(
                id=settings.local_user_id,
                display_name="密码库测试",
                email=OWNER_EMAIL,
                email_verified=True,
            )
            session.add(user)
        else:
            user.email = OWNER_EMAIL
            user.email_verified = True
        session.commit()
    _keep_vault_cookie(client)
    return client


def _outbox(client: TestClient) -> list[str]:
    directory = Path(client.app.state.settings.email_outbox_directory)
    if not directory.exists():
        return []
    bodies: list[str] = []
    files = sorted(directory.glob("*.eml"), key=lambda path: path.stat().st_mtime_ns)
    for path in files:
        message = message_from_bytes(path.read_bytes(), policy=email_default_policy)
        content = message.get_content()
        bodies.append(content if isinstance(content, str) else str(content))
    return bodies


def _latest_code(client: TestClient) -> str:
    match = None
    for body in _outbox(client):
        match = re.search(r"验证码：(\d{6})", body) or match
    assert match is not None
    return match.group(1)


def _verify_email(
    client: TestClient,
    headers: dict[str, str] | None = None,
) -> dict[str, object]:
    sent = client.post("/api/v1/vault/access/code", headers=headers)
    assert sent.status_code == 200, sent.text
    verified = client.post(
        "/api/v1/vault/access/verify",
        headers=headers,
        json={"method": "email", "code": _latest_code(client)},
    )
    assert verified.status_code == 200, verified.text
    return verified.json()


def _dump_secrets(client: TestClient) -> str:
    chunks: list[str] = []
    with client.app.state.database.session_factory() as session:
        for model in (VaultAccessGrant, VaultChallenge, VaultSecuritySetting):
            for row in session.scalars(select(model)):
                chunks.append(repr(dict(row.__dict__)))
    return "\n".join(chunks)


def test_items_are_blocked_until_verified(
    vault_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """没验证时只能看状态，不能读条目。"""

    _use_ip(monkeypatch, WEB_IP)
    assert vault_client.get("/api/v1/vault").status_code == 200
    access = vault_client.get("/api/v1/vault/access")
    assert access.status_code == 200
    assert access.json()["granted"] is False
    assert access.json()["totp_enabled"] is False
    denied = vault_client.get("/api/v1/vault/items")
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "vault_step_up_required"


def test_email_code_grants_four_hours_once(
    vault_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证码换 4 小时授权，读数据不延长，验证码不能再用第二次。"""

    _use_ip(monkeypatch, WEB_IP)
    granted = _verify_email(vault_client)
    assert granted["client_token"] is None
    assert granted["hours"] == 4
    raw_expires = str(granted["expires_at"]).replace("Z", "+00:00")
    expires_at = datetime.fromisoformat(raw_expires)
    remaining = expires_at - datetime.now(UTC)
    assert timedelta(hours=3, minutes=58) < remaining <= timedelta(hours=4, seconds=5)
    assert vault_client.get("/api/v1/vault/items").status_code == 404
    again = vault_client.get("/api/v1/vault/access").json()
    assert again["expires_at"] == granted["expires_at"]
    reused = vault_client.post(
        "/api/v1/vault/access/verify",
        json={"method": "email", "code": _latest_code(vault_client)},
    )
    assert reused.status_code == 403
    assert reused.json()["detail"]["code"] == "vault_code_invalid"


def test_ip_or_user_agent_change_requires_verification_again(
    vault_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """换 IP 或换浏览器都要重新验证。两个地址都在白名单里，所以不是被白名单拦住。"""

    vault_client.app.state.settings = replace(
        vault_client.app.state.settings,
        vault_web_ip_allowlist=f"{WEB_IP}/32,{OTHER_IP}/32",
    )
    _use_ip(monkeypatch, WEB_IP)
    _verify_email(vault_client)
    _use_ip(monkeypatch, OTHER_IP)
    assert vault_client.get("/api/v1/vault").status_code == 200
    moved = vault_client.get("/api/v1/vault/items")
    assert moved.status_code == 403
    assert moved.json()["detail"]["code"] == "vault_step_up_required"
    _use_ip(monkeypatch, WEB_IP)
    changed_browser = vault_client.get(
        "/api/v1/vault/items",
        headers={"User-Agent": "OtherBrowser/1.0"},
    )
    assert changed_browser.status_code == 403
    assert changed_browser.json()["detail"]["code"] == "vault_step_up_required"
    assert vault_client.get("/api/v1/vault/items").status_code == 404


def test_totp_cannot_be_used_before_it_is_confirmed(
    vault_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """没绑定身份验证器时不能用动态码。绑定后才能拿它换授权。"""

    _use_ip(monkeypatch, WEB_IP)
    early = vault_client.post(
        "/api/v1/vault/access/verify",
        json={"method": "totp", "code": "123456"},
    )
    assert early.status_code == 400
    assert early.json()["detail"]["code"] == "vault_totp_unavailable"
    _verify_email(vault_client)
    setup = vault_client.post("/api/v1/vault/totp/setup")
    assert setup.status_code == 200
    secret = setup.json()["secret"]
    assert secret
    assert "otpauth://totp/" in setup.json()["otpauth_uri"]
    assert vault_client.get("/api/v1/vault/security").json()["totp_enabled"] is False
    confirmed = vault_client.post(
        "/api/v1/vault/totp/confirm",
        json={"code": totp_at(secret, int(datetime.now(UTC).timestamp()) // 30)},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["totp_enabled"] is True
    stored = _dump_secrets(vault_client)
    assert secret not in stored
    vault_client.cookies.clear()
    granted = vault_client.post(
        "/api/v1/vault/access/verify",
        json={
            "method": "totp",
            "code": totp_at(secret, int(datetime.now(UTC).timestamp()) // 30),
        },
    )
    assert granted.status_code == 200
    assert granted.json()["granted"] is True
    previous_step = int(datetime.now(UTC).timestamp()) // 30 - 1
    assert verify_totp(secret, totp_at(secret, previous_step))
    assert not verify_totp(
        secret,
        totp_at(secret, int(datetime.now(UTC).timestamp()) // 30 - 2),
    )


def test_database_does_not_store_plaintext_ip_code_or_secret(
    vault_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证码、IP 和 TOTP 密钥只以哈希或密文落库。"""

    _use_ip(monkeypatch, WEB_IP)
    sent = vault_client.post("/api/v1/vault/access/code")
    assert sent.status_code == 200
    code = _latest_code(vault_client)
    verified = vault_client.post(
        "/api/v1/vault/access/verify",
        json={"method": "email", "code": code},
    )
    assert verified.status_code == 200
    setup = vault_client.post("/api/v1/vault/totp/setup")
    secret = setup.json()["secret"]
    stored = _dump_secrets(vault_client)
    assert WEB_IP not in stored
    assert code not in stored
    assert secret not in stored
    assert "gAAAA" in stored


def test_mobile_grant_lasts_a_day_and_ignores_ip(
    vault_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """手机端 24 小时，换 IP 仍然有效；空的网页白名单也不拦截手机。"""

    vault_client.app.state.settings = replace(
        vault_client.app.state.settings,
        vault_web_ip_allowlist="",
    )
    _use_ip(monkeypatch, WEB_IP)
    blocked = vault_client.get("/api/v1/vault")
    assert blocked.status_code == 403
    assert blocked.json()["detail"]["code"] == "vault_ip_allowlist_empty"
    mobile = {"X-MemoIsle-Client": "mobile"}
    assert vault_client.get("/api/v1/vault", headers=mobile).status_code == 200
    sent = vault_client.post("/api/v1/vault/access/code", headers=mobile)
    assert sent.status_code == 200
    verified = vault_client.post(
        "/api/v1/vault/access/verify",
        headers=mobile,
        json={"method": "email", "code": _latest_code(vault_client)},
    )
    assert verified.status_code == 200
    body = verified.json()
    assert body["hours"] == 24
    assert body["client_type"] == "mobile"
    token = body["client_token"]
    assert isinstance(token, str) and token
    expires_at = datetime.fromisoformat(body["expires_at"].replace("Z", "+00:00"))
    remaining = expires_at - datetime.now(UTC)
    assert timedelta(hours=23, minutes=58) < remaining <= timedelta(hours=24, seconds=5)
    mobile_token = {**mobile, "X-MemoIsle-Vault-Client": token}
    same_ip = vault_client.get("/api/v1/vault/items", headers=mobile_token)
    assert same_ip.status_code == 404
    _use_ip(monkeypatch, OTHER_IP)
    moved_ip = vault_client.get("/api/v1/vault/items", headers=mobile_token)
    assert moved_ip.status_code == 404
    access = vault_client.get("/api/v1/vault/access", headers=mobile_token).json()
    assert access["granted"] is True
    assert access["expires_at"] == body["expires_at"]


def test_allowlist_is_the_union_of_environment_and_settings(
    vault_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """环境变量是兜底，设置页只能追加。清空用户条目删不掉环境变量里的地址。"""

    _use_ip(monkeypatch, WEB_IP)
    _verify_email(vault_client)
    saved = vault_client.put(
        "/api/v1/vault/security",
        json={"user_allowlist": [f"{OTHER_IP}/32", f"{WEB_IP}/32", "not-an-ip"]},
    )
    assert saved.status_code == 422
    saved = vault_client.put(
        "/api/v1/vault/security",
        json={"user_allowlist": [f"{OTHER_IP}/32", f"{WEB_IP}/32"]},
    )
    assert saved.status_code == 200
    security = saved.json()
    assert security["env_allowlist"] == [f"{WEB_IP}/32"]
    assert security["user_allowlist"] == [f"{OTHER_IP}/32"]
    _use_ip(monkeypatch, OTHER_IP)
    assert vault_client.get("/api/v1/vault").status_code == 200
    cleared = vault_client.put("/api/v1/vault/security", json={"user_allowlist": []})
    assert cleared.status_code == 403
    _use_ip(monkeypatch, WEB_IP)
    cleared = vault_client.put("/api/v1/vault/security", json={"user_allowlist": []})
    assert cleared.status_code == 200
    assert cleared.json()["env_allowlist"] == [f"{WEB_IP}/32"]
    assert cleared.json()["user_allowlist"] == []
    _use_ip(monkeypatch, OTHER_IP)
    blocked = vault_client.get("/api/v1/vault")
    assert blocked.status_code == 403
    assert blocked.json()["detail"]["code"] == "vault_ip_blocked"


def _alert_messages(client: TestClient) -> list[str]:
    return [body for body in _outbox(client) if "有一次验证没有通过" in body]


def test_wrong_master_password_alert_is_throttled_in_the_same_window(
    vault_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """主密码输错发一封报警；同一有效期内再失败不再各发一封。"""

    _use_ip(monkeypatch, WEB_IP)
    before = len(_alert_messages(vault_client))
    reported = vault_client.post("/api/v1/vault/unlock-failed")
    assert reported.status_code == 200
    assert reported.json()["sent"] is True
    alerts = _alert_messages(vault_client)
    assert len(alerts) == before + 1
    assert WEB_IP in alerts[-1]
    assert "主密码不正确" in alerts[-1]
    assert "网页" in alerts[-1]
    vault_client.post("/api/v1/vault/access/code")
    rejected = vault_client.post(
        "/api/v1/vault/access/verify",
        json={"method": "email", "code": "000000"},
    )
    assert rejected.status_code == 403
    assert rejected.json()["detail"]["code"] == "vault_code_invalid"
    assert len(_alert_messages(vault_client)) == before + 1
    assert "000000" not in "\n".join(_outbox(vault_client))
    again = vault_client.post("/api/v1/vault/unlock-failed")
    assert again.status_code == 200
    assert again.json()["sent"] is False
    assert len(_alert_messages(vault_client)) == before + 1


def test_totp_locks_after_repeated_failures_and_throttles_alerts(
    vault_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """动态码连续输错达到上限后锁定，正确的码也被拒绝，报警只发一封。"""

    _use_ip(monkeypatch, WEB_IP)
    _verify_email(vault_client)
    setup = vault_client.post("/api/v1/vault/totp/setup")
    assert setup.status_code == 200
    secret = setup.json()["secret"]
    current = totp_at(secret, int(datetime.now(UTC).timestamp()) // 30)
    confirmed = vault_client.post(
        "/api/v1/vault/totp/confirm",
        json={"code": current},
    )
    assert confirmed.status_code == 200
    limit = vault_client.app.state.settings.auth_verification_code_max_attempts
    before = len(_alert_messages(vault_client))
    statuses: list[tuple[int, str]] = []
    for _ in range(limit):
        rejected = vault_client.post(
            "/api/v1/vault/access/verify",
            json={"method": "totp", "code": "000000"},
        )
        statuses.append((rejected.status_code, rejected.json()["detail"]["code"]))
    assert statuses[:-1] == [(403, "vault_code_invalid")] * (limit - 1)
    assert statuses[-1] == (429, "vault_totp_locked")
    correct = vault_client.post(
        "/api/v1/vault/access/verify",
        json={"method": "totp", "code": current},
    )
    assert correct.status_code == 429
    assert correct.json()["detail"]["code"] == "vault_totp_locked"
    assert "Retry-After" in correct.headers
    alerts = _alert_messages(vault_client)
    assert len(alerts) == before + 1
    assert "身份验证器动态码不正确" in alerts[-1]
    assert secret not in alerts[-1]
    assert "000000" not in alerts[-1]
    for _ in range(3):
        reported = vault_client.post("/api/v1/vault/unlock-failed")
        assert reported.status_code == 200
        assert reported.json()["sent"] is False
    assert len(_alert_messages(vault_client)) == before + 1
    minutes = vault_client.app.state.settings.auth_verification_code_expire_minutes
    with vault_client.app.state.database.session_factory() as session:
        setting = session.get(
            VaultSecuritySetting,
            vault_client.app.state.settings.local_user_id,
        )
        assert setting is not None
        setting.totp_failure_window_started_at = datetime.now(UTC) - timedelta(
            minutes=minutes + 1,
        )
        session.commit()
    fresh = totp_at(secret, int(datetime.now(UTC).timestamp()) // 30)
    granted = vault_client.post(
        "/api/v1/vault/access/verify",
        json={"method": "totp", "code": fresh},
    )
    assert granted.status_code == 200
    assert granted.json()["granted"] is True


def test_logout_invalidates_the_grant(
    vault_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """退出后再登录是新会话，原来的客户端令牌不能继续用。"""

    _use_ip(monkeypatch, WEB_IP)
    first = vault_client.post("/api/v1/auth/dev-login")
    assert first.status_code == 200
    headers = {"Authorization": f"Bearer {first.json()['access_token']}"}
    _verify_email(vault_client, headers)
    assert vault_client.get("/api/v1/vault/items", headers=headers).status_code == 404
    assert vault_client.post("/api/v1/auth/logout", headers=headers).status_code == 200
    assert vault_client.get("/api/v1/vault/items", headers=headers).status_code == 401
    second = vault_client.post("/api/v1/auth/dev-login")
    headers = {"Authorization": f"Bearer {second.json()['access_token']}"}
    denied = vault_client.get("/api/v1/vault/items", headers=headers)
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "vault_step_up_required"


def test_forwarded_for_is_trusted_only_from_configured_proxies(
    vault_client: TestClient,
) -> None:
    """不可信的直连即使带了 X-Forwarded-For，也按它自己的地址处理。"""

    class _Peer:
        def __init__(self, host: str) -> None:
            self.host = host

    class _Request:
        def __init__(self, host: str, forwarded: str) -> None:
            self.client = _Peer(host)
            self.headers = {"x-forwarded-for": forwarded}
            self.app = vault_client.app

    vault_client.app.state.settings = replace(
        vault_client.app.state.settings,
        trusted_proxy_ips="127.0.0.1/32",
        vault_web_ip_allowlist=f"{WEB_IP}/32",
    )
    assert client_ip(_Request("198.51.100.9", WEB_IP)) == "198.51.100.9"  # type: ignore[arg-type]
    assert client_ip(_Request("127.0.0.1", WEB_IP)) == WEB_IP  # type: ignore[arg-type]
    assert client_ip(_Request("127.0.0.1", "not-an-ip")) is None  # type: ignore[arg-type]
    denied = vault_client.get("/api/v1/vault", headers={"X-Forwarded-For": WEB_IP})
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] in {
        "vault_ip_blocked",
        "vault_ip_allowlist_empty",
    }
