"""邮件发送渠道测试。"""

from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from email import policy
from email.parser import BytesParser
from pathlib import Path
from typing import Any

import pytest
from app.config import Settings
from app.email_service import send_verification_code_email


def create_email_settings(tmp_path: Path) -> Settings:
    """创建不包含真实凭据的邮件测试配置。"""

    return Settings(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'email.db'}",
        cors_origins=("http://localhost:5173",),
        local_user_id="00000000-0000-0000-0000-000000000001",
        auth_token_secret="test-auth-token-secret",
        audio_directory=tmp_path / "audio",
        email_outbox_directory=tmp_path / "email-outbox",
        email_provider="auto",
        resource_enrichment_enabled=False,
        resource_health_monitor_enabled=False,
    )


def test_agently_cli_confirmation_flow(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """AgentlyMail 应先获取确认令牌，再带令牌完成发送。"""

    calls: list[list[str]] = []
    responses = [
        {
            "ok": True,
            "data": {
                "confirmation_required": True,
                "confirmation_token": "ctk_test",
            },
        },
        {"ok": True, "data": {"sent": True}},
    ]

    def fake_which(_: str) -> str:
        """模拟系统中已安装 AgentlyMail CLI。"""

        return "/usr/local/bin/agently-cli"

    def fake_run(
        command: list[str],
        **_: Any,
    ) -> subprocess.CompletedProcess[str]:
        """返回两阶段 CLI 的模拟 JSON 响应。"""

        calls.append(command)
        response = responses[len(calls) - 1]
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(response),
            stderr="",
        )

    monkeypatch.setattr("app.email_service.shutil.which", fake_which)
    monkeypatch.setattr("app.email_service.subprocess.run", fake_run)

    send_verification_code_email(
        create_email_settings(tmp_path),
        "receiver@example.com",
        "123456",
    )

    assert len(calls) == 2
    assert calls[0][0] == "/usr/local/bin/agently-cli"
    assert calls[0][1:4] == ["message", "+send", "--to"]
    assert any("123456" in argument for argument in calls[0])
    assert "--confirmation-token" not in calls[0]
    assert calls[1][-2:] == ["--confirmation-token", "ctk_test"]


def test_dev_mode_auto_writes_outbox_even_if_agently_cli_exists(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """开发模式默认写出箱，避免本机 agently-cli 把验证码发走。"""

    def fake_which(_: str) -> str:
        """模拟系统中已安装 AgentlyMail CLI。"""

        return "/usr/local/bin/agently-cli"

    def fake_run(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        """开发模式不应调用 AgentlyMail。"""

        raise AssertionError("开发模式不应调用 agently-cli")

    monkeypatch.setattr("app.email_service.shutil.which", fake_which)
    monkeypatch.setattr("app.email_service.subprocess.run", fake_run)

    settings = replace(create_email_settings(tmp_path), auth_dev_mode=True)
    send_verification_code_email(settings, "receiver@example.com", "123456")

    outbox_files = list((tmp_path / "email-outbox").glob("*.eml"))
    assert len(outbox_files) == 1
    message = BytesParser(policy=policy.default).parsebytes(
        outbox_files[0].read_bytes(),
    )
    body = message.get_body(preferencelist=("plain",)).get_content()
    assert "123456" in body


def test_smtp_uses_username_as_sender_and_passes_timeout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """SMTP 未单独配置发件人时复用用户名，并传递连接超时。"""

    calls: dict[str, Any] = {}

    class FakeSmtp:
        """记录 SMTP 调用而不连接真实服务器。"""

        def __init__(self, host: str, port: int, timeout: float) -> None:
            calls.update(host=host, port=port, timeout=timeout)

        def __enter__(self) -> FakeSmtp:
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

        def ehlo(self) -> None:
            calls["ehlo"] = True

        def starttls(self) -> None:
            calls["starttls"] = True

        def login(self, username: str, password: str) -> None:
            calls["login"] = (username, password)

        def send_message(self, message: Any) -> None:
            calls["message"] = message

    monkeypatch.setattr("app.email_service.smtplib.SMTP", FakeSmtp)
    settings = replace(
        create_email_settings(tmp_path),
        email_provider="smtp",
        smtp_host="smtp.example.com",
        smtp_username="sender@example.com",
        smtp_use_tls=True,
        smtp_timeout_seconds=7.5,
    )

    send_verification_code_email(settings, "receiver@example.com", "123456")

    assert calls["host"] == "smtp.example.com"
    assert calls["port"] == 587
    assert calls["timeout"] == 7.5
    assert calls["starttls"] is True
    assert calls["login"] == ("sender@example.com", "")
    assert calls["message"]["From"] == "sender@example.com"
