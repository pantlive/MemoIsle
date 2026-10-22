"""应用配置。"""

from __future__ import annotations

import logging
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sqlalchemy.engine import make_url

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATABASE_PATH = PROJECT_ROOT.parent / "data" / "memoisle.db"
DEFAULT_AUDIO_DIRECTORY = PROJECT_ROOT.parent / "data" / "audio"
DEFAULT_IMAGE_DIRECTORY = PROJECT_ROOT.parent / "data" / "images"
DEFAULT_SANOTTS_CACHE_DIRECTORY = PROJECT_ROOT.parent / "data" / "sanotts"
DEFAULT_EMAIL_OUTBOX_DIRECTORY = PROJECT_ROOT.parent / "data" / "email_outbox"
DEFAULT_WORD_DICTIONARY_BASE_URL = (
    "https://freedictionaryapi.com/api/v1/entries/en"
)
DEFAULT_WORD_DICTIONARY_FALLBACK_BASE_URL = (
    "https://api.dictionaryapi.dev/api/v2/entries/en"
)
DEFAULT_WORD_BILINGUAL_DICTIONARY_URL = "https://dict.youdao.com/jsonapi"
DEFAULT_WORD_BILINGUAL_SUGGEST_URL = "https://dict.youdao.com/suggest"
EmailProvider = Literal["auto", "agently", "smtp", "outbox"]
TtsProvider = Literal["auto", "sanotts", "none"]
ImageOcrProvider = Literal["none", "local", "llm", "auto"]

IMAGE_OCR_PROVIDERS: frozenset[str] = frozenset({"none", "local", "llm", "auto"})


def normalize_image_ocr_provider(value: str | None) -> str:
    """读取图片 OCR 渠道；无法识别时回退为 none，避免误开外部调用。"""

    normalized = (value or "").strip().lower()
    return normalized if normalized in IMAGE_OCR_PROVIDERS else "none"


def auth_secret_file(database_url: str) -> Path:
    """登录密钥文件位置：SQLite 放在数据库旁，其他数据库放默认数据目录。"""

    url = make_url(database_url)
    in_memory = url.database in (None, "", ":memory:")
    if url.get_backend_name() == "sqlite" and not in_memory:
        return Path(url.database).parent / ".memoisle-auth.key"
    return DEFAULT_DATABASE_PATH.parent / ".memoisle-auth.key"


def load_or_create_secret_file(path: Path) -> str:
    """读取私有密钥文件；不存在时原子创建（权限 0600），并发进程共用首个结果。

    目录不可写时退回进程内随机密钥并告警，而不是在 import 阶段让服务崩溃；
    这时重启后会话会失效，告警里提示显式配置环境变量。
    """

    try:
        if not path.exists():
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            temporary = path.with_name(f"{path.name}.{secrets.token_hex(8)}.tmp")
            try:
                with temporary.open("x", encoding="utf-8") as stream:
                    # 写入秘密前先收紧权限，再用硬链接原子发布完整文件。
                    temporary.chmod(0o600)
                    stream.write(secrets.token_urlsafe(32))
                try:
                    path.hardlink_to(temporary)
                except FileExistsError:
                    pass
            finally:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
        secret = path.read_text(encoding="utf-8").strip()
    except OSError as error:
        logger.warning(
            "无法读写登录密钥文件 %s（%s），本次使用临时密钥；"
            "重启后会话会失效，请设置 MEMOISLE_AUTH_TOKEN_SECRET",
            path,
            error,
        )
        return secrets.token_urlsafe(32)
    if not secret:
        raise ValueError(f"登录密钥文件为空：{path}")
    return secret


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
    image_directory: Path = DEFAULT_IMAGE_DIRECTORY
    tts_enabled: bool = True
    tts_provider: TtsProvider = "auto"
    sanotts_voice: str = "amy"
    sanotts_cache_directory: Path = DEFAULT_SANOTTS_CACHE_DIRECTORY
    tts_max_text_length: int = 2_000
    auth_dev_mode: bool = False
    auth_token_secret: str = ""
    # 云盘凭据加密密钥；未单独配置时回退到 auth_token_secret。
    # 生产环境需显式设置，否则进程重启后旧凭据无法解密，用户要重新粘贴。
    cloud_credential_secret: str = ""
    # 电子书：直链下载上限与超时；下载完成后立即上传云盘并删除本地临时文件。
    ebook_max_bytes: int = 2 * 1024 * 1024 * 1024
    ebook_download_timeout_seconds: float = 60.0
    auth_token_ttl_seconds: int = 30 * 24 * 60 * 60
    auth_mobile_redirect_uri: str = "memoisle://auth/callback"
    web_base_url: str = ""
    auth_login_rate_limit_attempts: int = 5
    auth_login_rate_limit_window_seconds: int = 15 * 60
    auth_email_verification_ttl_seconds: int = 24 * 60 * 60
    auth_password_reset_ttl_seconds: int = 30 * 60
    auth_verification_code_expire_minutes: int = 10
    auth_verification_code_resend_seconds: int = 60
    auth_verification_code_max_attempts: int = 5
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_address: str = ""
    smtp_use_tls: bool = True
    smtp_use_ssl: bool = False
    smtp_timeout_seconds: float = 15.0
    email_outbox_directory: Path = DEFAULT_EMAIL_OUTBOX_DIRECTORY
    email_provider: EmailProvider = "auto"
    agently_cli_path: str = "agently-cli"
    google_client_id: str = ""
    google_client_secret: str = ""
    wechat_app_id: str = ""
    wechat_app_secret: str = ""
    apple_client_id: str = ""
    apple_client_secret: str = ""
    oauth_login_enabled: bool = False
    resource_enrichment_enabled: bool = True
    resource_fetch_timeout_seconds: float = 6.0
    resource_fetch_max_bytes: int = 512 * 1024
    resource_health_monitor_enabled: bool = True
    resource_health_interval_hours: int = 30 * 24
    resource_failure_threshold: int = 3
    resource_worker_interval_seconds: int = 60
    trash_retention_days: int = 30
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str = ""
    llm_timeout_seconds: float = 30.0
    # 分类模板生成单独使用 DeepSeek，避免影响会议总结和图片视觉模型。
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_api_key: str | None = None
    deepseek_model: str = "deepseek-flash"
    deepseek_timeout_seconds: float = 60.0
    # Jev 只选择已有类别；与 DeepSeek 的模板生成凭证分别配置。
    jev_base_url: str = "https://api.typesafe.ai/v1"
    jev_api_key: str | None = None
    jev_model: str = "jev-1.13.0"
    jev_min_confidence: float = 0.7
    # 按分类口径判定时的最低置信度；低于它的结果进分类确认中心。
    classification_min_confidence: float = 0.7
    # 设置页凭据使用持久化加密密钥，默认与数据库保存在同一目录。
    model_credential_key_file: Path | None = None
    # 图片 OCR：none 关闭；local 只用本地引擎；llm 只用视觉大模型；
    # auto 本地优先、不可用时回退大模型。
    image_ocr_provider: str = "none"
    image_ocr_vision_model: str = ""
    image_ocr_timeout_seconds: float = 60.0
    image_ocr_max_tags: int = 8
    image_ocr_preview_max_side: int = 1600
    image_ocr_languages: str = "chi_sim+eng"
    word_dictionary_enabled: bool = True
    word_dictionary_base_url: str = DEFAULT_WORD_DICTIONARY_BASE_URL
    word_dictionary_fallback_base_url: str = (
        DEFAULT_WORD_DICTIONARY_FALLBACK_BASE_URL
    )
    word_dictionary_timeout_seconds: float = 6.0
    # 公共词典默认直连，避免本地代理无法转发 dictionaryapi.dev 导致查词超时。
    word_dictionary_trust_env: bool = False
    word_bilingual_enabled: bool = True
    word_bilingual_dictionary_url: str = DEFAULT_WORD_BILINGUAL_DICTIONARY_URL
    word_bilingual_suggest_url: str = DEFAULT_WORD_BILINGUAL_SUGGEST_URL

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
        if not auth_token_secret:
            # 未显式配置时持久化到数据库旁的私有文件，而不是每次启动随机生成：
            # 随机密钥会让重启后所有会话失效、云盘 refresh_token 永久无法解密，
            # 多 worker 部署时各进程的密钥也会不一致。
            auth_token_secret = load_or_create_secret_file(
                auth_secret_file(database_url),
            )
        created_token_secret = auth_token_secret
        # 云盘凭据默认与登录密钥同源；登录密钥已固定，重启后仍可解密。
        cloud_credential_secret = (
            os.environ.get("MEMOISLE_CLOUD_CREDENTIAL_SECRET", "")
            or created_token_secret
        )
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
        oauth_login_enabled = environment_flag(
            "MEMOISLE_OAUTH_LOGIN_ENABLED",
            False,
        )
        email_outbox_directory = Path(
            os.environ.get(
                "MEMOISLE_EMAIL_OUTBOX_DIRECTORY",
                DEFAULT_EMAIL_OUTBOX_DIRECTORY,
            ),
        )
        audio_directory = Path(
            os.environ.get("MEMOISLE_AUDIO_DIRECTORY", DEFAULT_AUDIO_DIRECTORY),
        )
        image_directory = Path(
            os.environ.get("MEMOISLE_IMAGE_DIRECTORY", DEFAULT_IMAGE_DIRECTORY),
        )
        sanotts_cache_directory = Path(
            os.environ.get(
                "MEMOISLE_SANOTTS_CACHE_DIRECTORY",
                DEFAULT_SANOTTS_CACHE_DIRECTORY,
            ),
        )
        tts_provider = os.environ.get(
            "MEMOISLE_TTS_PROVIDER",
            "auto",
        ).strip().lower()
        if tts_provider not in {"auto", "sanotts", "none"}:
            raise ValueError(
                "MEMOISLE_TTS_PROVIDER 必须是 auto、sanotts 或 none",
            )
        email_provider = os.environ.get(
            "MEMOISLE_EMAIL_PROVIDER",
            "auto",
        ).strip().lower()
        if email_provider not in {"auto", "agently", "smtp", "outbox"}:
            raise ValueError(
                "MEMOISLE_EMAIL_PROVIDER 必须是 auto、agently、smtp 或 outbox",
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
            auth_token_secret=created_token_secret,
            model_credential_key_file=(
                Path(os.environ["MEMOISLE_MODEL_CREDENTIAL_KEY_FILE"])
                if os.environ.get("MEMOISLE_MODEL_CREDENTIAL_KEY_FILE")
                else None
            ),
            cloud_credential_secret=cloud_credential_secret,
            ebook_max_bytes=max(
                1,
                int(
                    os.environ.get(
                        "MEMOISLE_EBOOK_MAX_BYTES",
                        str(2 * 1024 * 1024 * 1024),
                    ),
                ),
            ),
            ebook_download_timeout_seconds=max(
                1.0,
                float(
                    os.environ.get(
                        "MEMOISLE_EBOOK_DOWNLOAD_TIMEOUT_SECONDS",
                        "60",
                    ),
                ),
            ),
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
            auth_verification_code_expire_minutes=int(
                os.environ.get(
                    "MEMOISLE_AUTH_VERIFICATION_CODE_EXPIRE_MINUTES",
                    "10",
                ),
            ),
            auth_verification_code_resend_seconds=int(
                os.environ.get(
                    "MEMOISLE_AUTH_VERIFICATION_CODE_RESEND_SECONDS",
                    "60",
                ),
            ),
            auth_verification_code_max_attempts=int(
                os.environ.get(
                    "MEMOISLE_AUTH_VERIFICATION_CODE_MAX_ATTEMPTS",
                    "5",
                ),
            ),
            smtp_host=os.environ.get("MEMOISLE_SMTP_HOST", ""),
            smtp_port=int(os.environ.get("MEMOISLE_SMTP_PORT", "587")),
            smtp_username=os.environ.get("MEMOISLE_SMTP_USERNAME", ""),
            smtp_password=os.environ.get("MEMOISLE_SMTP_PASSWORD", ""),
            smtp_from_address=os.environ.get("MEMOISLE_SMTP_FROM_ADDRESS", ""),
            smtp_use_tls=environment_flag("MEMOISLE_SMTP_USE_TLS", True),
            smtp_use_ssl=environment_flag("MEMOISLE_SMTP_USE_SSL", False),
            smtp_timeout_seconds=max(
                1.0,
                float(os.environ.get("MEMOISLE_SMTP_TIMEOUT_SECONDS", "15")),
            ),
            email_outbox_directory=email_outbox_directory,
            email_provider=email_provider,
            agently_cli_path=os.environ.get(
                "MEMOISLE_AGENTLY_CLI_PATH",
                "agently-cli",
            ),
            google_client_id=google_client_id,
            google_client_secret=google_client_secret,
            wechat_app_id=wechat_app_id,
            wechat_app_secret=wechat_app_secret,
            apple_client_id=apple_client_id,
            apple_client_secret=apple_client_secret,
            oauth_login_enabled=oauth_login_enabled,
            audio_directory=audio_directory,
            image_directory=image_directory,
            tts_enabled=environment_flag("MEMOISLE_TTS_ENABLED", True),
            tts_provider=tts_provider,
            sanotts_voice=os.environ.get("MEMOISLE_SANOTTS_VOICE", "amy").strip(),
            sanotts_cache_directory=sanotts_cache_directory,
            tts_max_text_length=max(
                1,
                int(os.environ.get("MEMOISLE_TTS_MAX_TEXT_LENGTH", "2000")),
            ),
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
            trash_retention_days=max(
                1,
                int(os.environ.get("MEMOISLE_TRASH_RETENTION_DAYS", "30")),
            ),
            llm_base_url=os.environ.get("MEMOISLE_LLM_BASE_URL") or None,
            llm_api_key=os.environ.get("MEMOISLE_LLM_API_KEY") or None,
            llm_model=os.environ.get("MEMOISLE_LLM_MODEL", ""),
            llm_timeout_seconds=float(
                os.environ.get("MEMOISLE_LLM_TIMEOUT_SECONDS", "30"),
            ),
            deepseek_base_url=os.environ.get(
                "MEMOISLE_DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1",
            ).rstrip("/"),
            deepseek_api_key=(
                os.environ.get("MEMOISLE_DEEPSEEK_API_KEY")
                or os.environ.get("DEEPSEEK_API_KEY")
                or None
            ),
            deepseek_model=os.environ.get(
                "MEMOISLE_DEEPSEEK_MODEL", "deepseek-flash",
            ),
            deepseek_timeout_seconds=float(
                os.environ.get("MEMOISLE_DEEPSEEK_TIMEOUT_SECONDS", "60"),
            ),
            jev_base_url=os.environ.get(
                "MEMOISLE_JEV_BASE_URL", "https://api.typesafe.ai/v1",
            ).rstrip("/"),
            jev_api_key=(
                os.environ.get("MEMOISLE_JEV_API_KEY")
                or os.environ.get("TYPESAFE_API_KEY")
                or None
            ),
            jev_model=os.environ.get("MEMOISLE_JEV_MODEL", "jev-1.13.0"),
            jev_min_confidence=max(
                0.0,
                min(
                    1.0,
                    float(os.environ.get("MEMOISLE_JEV_MIN_CONFIDENCE", "0.7")),
                ),
            ),
            classification_min_confidence=max(
                0.0,
                min(
                    1.0,
                    float(
                        os.environ.get(
                            "MEMOISLE_CLASSIFICATION_MIN_CONFIDENCE", "0.7",
                        ),
                    ),
                ),
            ),
            image_ocr_provider=normalize_image_ocr_provider(
                os.environ.get("MEMOISLE_IMAGE_OCR_PROVIDER", "none"),
            ),
            image_ocr_vision_model=(
                os.environ.get("MEMOISLE_VISION_MODEL")
                or os.environ.get("MEMOISLE_IMAGE_OCR_MODEL")
                or ""
            ),
            image_ocr_timeout_seconds=float(
                os.environ.get("MEMOISLE_IMAGE_OCR_TIMEOUT_SECONDS", "60"),
            ),
            image_ocr_max_tags=max(
                1,
                min(
                    20,
                    int(os.environ.get("MEMOISLE_IMAGE_OCR_MAX_TAGS", "8")),
                ),
            ),
            image_ocr_preview_max_side=max(
                320,
                min(
                    4096,
                    int(
                        os.environ.get(
                            "MEMOISLE_IMAGE_OCR_PREVIEW_MAX_SIDE",
                            "1600",
                        ),
                    ),
                ),
            ),
            image_ocr_languages=os.environ.get(
                "MEMOISLE_IMAGE_OCR_LANGUAGES",
                "chi_sim+eng",
            ),
            word_dictionary_enabled=environment_flag(
                "MEMOISLE_WORD_DICTIONARY_ENABLED",
                True,
            ),
            word_dictionary_base_url=os.environ.get(
                "MEMOISLE_WORD_DICTIONARY_BASE_URL",
                DEFAULT_WORD_DICTIONARY_BASE_URL,
            ),
            word_dictionary_fallback_base_url=os.environ.get(
                "MEMOISLE_WORD_DICTIONARY_FALLBACK_BASE_URL",
                DEFAULT_WORD_DICTIONARY_FALLBACK_BASE_URL,
            ),
            word_dictionary_timeout_seconds=float(
                os.environ.get("MEMOISLE_WORD_DICTIONARY_TIMEOUT_SECONDS", "6"),
            ),
            word_dictionary_trust_env=environment_flag(
                "MEMOISLE_WORD_DICTIONARY_TRUST_ENV",
                False,
            ),
            word_bilingual_enabled=environment_flag(
                "MEMOISLE_WORD_BILINGUAL_ENABLED",
                True,
            ),
            word_bilingual_dictionary_url=os.environ.get(
                "MEMOISLE_WORD_BILINGUAL_DICTIONARY_URL",
                DEFAULT_WORD_BILINGUAL_DICTIONARY_URL,
            ),
            word_bilingual_suggest_url=os.environ.get(
                "MEMOISLE_WORD_BILINGUAL_SUGGEST_URL",
                DEFAULT_WORD_BILINGUAL_SUGGEST_URL,
            ),
        )
