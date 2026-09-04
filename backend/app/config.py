"""应用配置。"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATABASE_PATH = PROJECT_ROOT.parent / "data" / "memoisle.db"
DEFAULT_AUDIO_DIRECTORY = PROJECT_ROOT.parent / "data" / "audio"
DEFAULT_EMAIL_OUTBOX_DIRECTORY = PROJECT_ROOT.parent / "data" / "email_outbox"


def environment_flag(name: str, default: bool) -> bool:
    """读取常见布尔环境变量表达。"""

    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class Settings:
    """服务端运行配置。"""

    database_url: str
    cors_origins: tuple[str, ...]
    local_user_id: str
    audio_directory: Path
    auth_dev_mode: bool = False
    auth_token_secret: str = ""
    auth_token_ttl_seconds: int = 30 * 24 * 60 * 60
    auth_mobile_redirect_uri: str = "memoisle://auth/callback"
    web_base_url: str = ""
    auth_login_rate_limit_attempts: int = 5
    auth_login_rate_limit_window_seconds: int = 15 * 60
    auth_email_verification_ttl_seconds: int = 24 * 60 * 60
    auth_password_reset_ttl_seconds: int = 30 * 60
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_address: str = ""
    smtp_use_tls: bool = True
    smtp_use_ssl: bool = False
    email_outbox_directory: Path = DEFAULT_EMAIL_OUTBOX_DIRECTORY
    google_client_id: str = ""
    google_client_secret: str = ""
    wechat_app_id: str = ""
    wechat_app_secret: str = ""
    apple_client_id: str = ""
    apple_client_secret: str = ""
    resource_enrichment_enabled: bool = True
    resource_fetch_timeout_seconds: float = 6.0
    resource_fetch_max_bytes: int = 512 * 1024
    resource_health_monitor_enabled: bool = True
    resource_health_interval_hours: int = 30 * 24
    resource_failure_threshold: int = 3
    resource_worker_interval_seconds: int = 60
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str = ""
    word_dictionary_enabled: bool = True
    word_dictionary_base_url: str = "https://api.dictionaryapi.dev/api/v2/entries/en"
    word_dictionary_timeout_seconds: float = 6.0

    @classmethod
    def from_environment(cls) -> Settings:
        """从环境变量构造配置。"""

        database_url = os.environ.get(
            "MEMOISLE_DATABASE_URL",
            f"sqlite+pysqlite:///{DEFAULT_DATABASE_PATH}",
        )
        origins_text = os.environ.get(
            "MEMOISLE_CORS_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173",
        )
        cors_origins = tuple(
            origin.strip() for origin in origins_text.split(",") if origin.strip()
        )
        local_user_id = os.environ.get(
            "MEMOISLE_LOCAL_USER_ID",
            "00000000-0000-0000-0000-000000000001",
        )
        auth_dev_mode = environment_flag("MEMOISLE_AUTH_DEV_MODE", False)
        auth_token_secret = os.environ.get("MEMOISLE_AUTH_TOKEN_SECRET", "")
        auth_mobile_redirect_uri = os.environ.get(
            "MEMOISLE_AUTH_MOBILE_REDIRECT_URI",
            "memoisle://auth/callback",
        )
        cors_origin_list = [origin for origin in cors_origins if origin]
        google_client_id = os.environ.get("MEMOISLE_GOOGLE_CLIENT_ID", "")
        google_client_secret = os.environ.get("MEMOISLE_GOOGLE_CLIENT_SECRET", "")
        wechat_app_id = os.environ.get("MEMOISLE_WECHAT_APP_ID", "")
        wechat_app_secret = os.environ.get("MEMOISLE_WECHAT_APP_SECRET", "")
        apple_client_id = os.environ.get("MEMOISLE_APPLE_CLIENT_ID", "")
        apple_client_secret = os.environ.get("MEMOISLE_APPLE_CLIENT_SECRET", "")
        email_outbox_directory = Path(
            os.environ.get(
                "MEMOISLE_EMAIL_OUTBOX_DIRECTORY",
                DEFAULT_EMAIL_OUTBOX_DIRECTORY,
            ),
        )
        audio_directory = Path(
            os.environ.get("MEMOISLE_AUDIO_DIRECTORY", DEFAULT_AUDIO_DIRECTORY),
        )
        resource_enrichment_enabled = environment_flag(
            "MEMOISLE_RESOURCE_ENRICHMENT_ENABLED",
            True,
        )
        resource_health_monitor_enabled = environment_flag(
            "MEMOISLE_RESOURCE_HEALTH_MONITOR_ENABLED",
            True,
        )
        return cls(
            database_url=database_url,
            cors_origins=cors_origins,
            local_user_id=local_user_id,
            auth_dev_mode=auth_dev_mode,
            auth_token_secret=auth_token_secret or secrets.token_urlsafe(32),
            auth_token_ttl_seconds=int(
                os.environ.get("MEMOISLE_AUTH_TOKEN_TTL_SECONDS", "2592000"),
            ),
            auth_mobile_redirect_uri=auth_mobile_redirect_uri,
            web_base_url=os.environ.get(
                "MEMOISLE_WEB_BASE_URL",
                cors_origin_list[0] if cors_origin_list else "",
            ),
            auth_login_rate_limit_attempts=int(
                os.environ.get("MEMOISLE_AUTH_LOGIN_RATE_LIMIT_ATTEMPTS", "5"),
            ),
            auth_login_rate_limit_window_seconds=int(
                os.environ.get(
                    "MEMOISLE_AUTH_LOGIN_RATE_LIMIT_WINDOW_SECONDS",
                    "900",
                ),
            ),
            auth_email_verification_ttl_seconds=int(
                os.environ.get(
                    "MEMOISLE_AUTH_EMAIL_VERIFICATION_TTL_SECONDS",
                    str(24 * 60 * 60),
                ),
            ),
            auth_password_reset_ttl_seconds=int(
                os.environ.get(
                    "MEMOISLE_AUTH_PASSWORD_RESET_TTL_SECONDS",
                    str(30 * 60),
                ),
            ),
            smtp_host=os.environ.get("MEMOISLE_SMTP_HOST", ""),
            smtp_port=int(os.environ.get("MEMOISLE_SMTP_PORT", "587")),
            smtp_username=os.environ.get("MEMOISLE_SMTP_USERNAME", ""),
            smtp_password=os.environ.get("MEMOISLE_SMTP_PASSWORD", ""),
            smtp_from_address=os.environ.get("MEMOISLE_SMTP_FROM_ADDRESS", ""),
            smtp_use_tls=environment_flag("MEMOISLE_SMTP_USE_TLS", True),
            smtp_use_ssl=environment_flag("MEMOISLE_SMTP_USE_SSL", False),
            email_outbox_directory=email_outbox_directory,
            google_client_id=google_client_id,
            google_client_secret=google_client_secret,
            wechat_app_id=wechat_app_id,
            wechat_app_secret=wechat_app_secret,
            apple_client_id=apple_client_id,
            apple_client_secret=apple_client_secret,
            audio_directory=audio_directory,
            resource_enrichment_enabled=resource_enrichment_enabled,
            resource_health_monitor_enabled=resource_health_monitor_enabled,
            resource_fetch_timeout_seconds=float(
                os.environ.get("MEMOISLE_RESOURCE_FETCH_TIMEOUT_SECONDS", "6"),
            ),
            resource_fetch_max_bytes=int(
                os.environ.get(
                    "MEMOISLE_RESOURCE_FETCH_MAX_BYTES",
                    str(512 * 1024),
                ),
            ),
            resource_health_interval_hours=int(
                os.environ.get("MEMOISLE_RESOURCE_HEALTH_INTERVAL_HOURS", "720"),
            ),
            resource_failure_threshold=int(
                os.environ.get("MEMOISLE_RESOURCE_FAILURE_THRESHOLD", "3"),
            ),
            resource_worker_interval_seconds=int(
                os.environ.get("MEMOISLE_RESOURCE_WORKER_INTERVAL_SECONDS", "60"),
            ),
            llm_base_url=os.environ.get("MEMOISLE_LLM_BASE_URL") or None,
            llm_api_key=os.environ.get("MEMOISLE_LLM_API_KEY") or None,
            llm_model=os.environ.get("MEMOISLE_LLM_MODEL", ""),
            word_dictionary_enabled=environment_flag(
                "MEMOISLE_WORD_DICTIONARY_ENABLED",
                True,
            ),
            word_dictionary_base_url=os.environ.get(
                "MEMOISLE_WORD_DICTIONARY_BASE_URL",
                "https://api.dictionaryapi.dev/api/v2/entries/en",
            ),
            word_dictionary_timeout_seconds=float(
                os.environ.get("MEMOISLE_WORD_DICTIONARY_TIMEOUT_SECONDS", "6"),
            ),
        )
