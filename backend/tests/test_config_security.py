"""登录密钥的启动期行为。"""

from __future__ import annotations

from pathlib import Path

import pytest


def _env(monkeypatch: pytest.MonkeyPatch, database: Path) -> None:
    monkeypatch.delenv("MEMOISLE_AUTH_TOKEN_SECRET", raising=False)
    monkeypatch.delenv("MEMOISLE_CLOUD_CREDENTIAL_SECRET", raising=False)
    monkeypatch.setenv("MEMOISLE_DATABASE_URL", f"sqlite+pysqlite:///{database}")


def test_unset_auth_secret_survives_restart(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """未配置登录密钥时，重启后必须拿到同一个密钥。

    早期实现每次启动随机生成，重启后会话失效、云盘凭据永久无法解密。
    """

    from app.config import Settings

    _env(monkeypatch, tmp_path / "memoisle.db")
    first = Settings.from_environment()
    second = Settings.from_environment()

    assert first.auth_token_secret == second.auth_token_secret
    assert first.cloud_credential_secret == second.cloud_credential_secret
    key_file = tmp_path / ".memoisle-auth.key"
    assert key_file.read_text(encoding="utf-8").strip() == first.auth_token_secret
    # 密钥文件只允许属主读写。
    assert key_file.stat().st_mode & 0o777 == 0o600


def test_explicit_auth_secret_wins_and_no_file_written(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """显式配置时直接使用，云盘密钥沿用它，不写密钥文件。"""

    from app.config import Settings

    _env(monkeypatch, tmp_path / "memoisle.db")
    monkeypatch.setenv("MEMOISLE_AUTH_TOKEN_SECRET", "fixed-login-secret")

    settings = Settings.from_environment()

    assert settings.auth_token_secret == "fixed-login-secret"
    assert settings.cloud_credential_secret == "fixed-login-secret"
    assert not (tmp_path / ".memoisle-auth.key").exists()
