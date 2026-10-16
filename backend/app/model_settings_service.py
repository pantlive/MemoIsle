"""模型配置、凭据加密与连接校验。"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import ModelProviderSetting, User
from app.schemas import (
    ModelConnectionResult,
    ModelProvider,
    ModelSettingRead,
    ModelSettingUpdate,
)


class ModelSettingError(ValueError):
    """配置或连接不可用；消息可安全显示给用户。"""


logger = logging.getLogger(__name__)
_UPSTREAM_ERROR_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,63}$")


def _upstream_error_tokens(response: httpx.Response) -> tuple[str | None, str | None]:
    """读取服务商错误信封中的 code/type，忽略可能含密钥的原文。"""

    try:
        payload = response.json()
    except ValueError:
        return None, None
    if not isinstance(payload, dict):
        return None, None
    error = payload.get("error")
    if not isinstance(error, dict):
        return None, None
    tokens: list[str | None] = []
    for key in ("code", "type"):
        value = error.get(key)
        if isinstance(value, str) and _UPSTREAM_ERROR_TOKEN.fullmatch(value):
            tokens.append(value)
        else:
            tokens.append(None)
    return tokens[0], tokens[1]


def describe_model_http_error(error: httpx.HTTPStatusError) -> str:
    """把上游 HTTP 错误收成可展示的原因，不回传响应正文。"""

    status = error.response.status_code
    upstream_code, upstream_type = _upstream_error_tokens(error.response)
    logger.info(
        "model connection test rejected status=%s code=%s type=%s",
        status,
        upstream_code,
        upstream_type,
    )
    if (
        status in {401, 403}
        or upstream_type == "authentication_error"
        or (upstream_code or "").upper() == "UNAUTHORIZED"
    ):
        if (upstream_code or "").lower() == "upgrade_required":
            return "当前套餐不能调用该模型接口，请升级服务商套餐后再试"
        return "认证失败，请检查 API Key"
    if status in {402, 429} or upstream_type == "rate_limit_error":
        return "额度不足或请求过于频繁，请检查服务账户"
    if (upstream_code or "").lower() == "unsupported_model":
        return "模型名称不受该服务支持，请对照服务商的模型列表修改"
    if status == 400:
        return "模型服务拒绝请求，请检查模型名称、请求地址和接口格式"
    return "模型服务请求失败，请检查模型名称和服务状态"


def _message_text(content: object) -> str:
    """兼容字符串和分段数组两种 Chat Completions 正文。"""

    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str) and item.strip():
                parts.append(item.strip())
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
        return "\n".join(parts)
    return ""


@dataclass(frozen=True)
class ProviderConfiguration:
    """单个账号实际生效的服务配置，仅在服务端使用。"""

    model: str
    base_url: str
    api_key: str | None = field(repr=False)
    enabled: bool
    source: Literal["account", "environment", "none"]
    has_custom_settings: bool
    error: str | None = None
    custom_base_url: str | None = None
    min_confidence: float | None = None


def request_origin(url: str) -> tuple[str, str | None, int]:
    """按协议、域名和端口比较接收凭据的服务。"""

    parsed = urlsplit(url)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return parsed.scheme, parsed.hostname, port


def credential_key_file(settings: Settings) -> Path:
    """确定持久化密钥位置，使进程重启后仍能解密。"""

    if settings.model_credential_key_file is not None:
        return settings.model_credential_key_file
    database_url = make_url(settings.database_url)
    if database_url.get_backend_name() == "sqlite" and database_url.database:
        if database_url.database != ":memory:":
            return Path(database_url.database).parent / ".memoisle-model.key"
    return settings.audio_directory.parent / ".memoisle-model.key"


def credential_cipher(settings: Settings) -> Fernet:
    """原子创建私有密钥文件；并发请求共用首次生成的密钥。"""

    path = credential_key_file(settings)
    try:
        if not path.exists():
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
            try:
                with temporary.open("xb") as stream:
                    # 写入秘密前限制权限，再原子发布完整文件。
                    temporary.chmod(0o600)
                    stream.write(Fernet.generate_key())
                try:
                    path.hardlink_to(temporary)
                except FileExistsError:
                    pass
            finally:
                temporary.unlink(missing_ok=True)
        return Fernet(path.read_bytes())
    except (OSError, ValueError) as error:
        raise ModelSettingError(
            "模型凭据存储不可用，请检查后端存储"
        ) from error


def get_provider_setting(
    session: Session,
    user_id: str,
    provider: ModelProvider,
) -> ModelProviderSetting | None:
    """读取当前账号的单个服务配置。"""

    return session.get(ModelProviderSetting, (user_id, provider.value))


def provider_configuration(
    session: Session,
    user_id: str,
    settings: Settings,
    provider: ModelProvider,
) -> ProviderConfiguration:
    """读取生效配置；损坏的账号凭据不会回退到其他密钥。"""

    prefix = provider.value
    model = getattr(settings, f"{prefix}_model")
    base_url = getattr(settings, f"{prefix}_base_url")
    api_key = getattr(settings, f"{prefix}_api_key")
    source: Literal["account", "environment", "none"] = (
        "environment" if api_key else "none"
    )
    enabled = True
    error_message: str | None = None
    saved = get_provider_setting(session, user_id, provider)
    custom_base_url = saved.base_url if saved is not None else None
    min_confidence = saved.min_confidence if saved is not None else None
    if saved is not None:
        model, enabled = saved.model, saved.enabled
        if custom_base_url:
            base_url = custom_base_url
            # 自定义服务缺少账号凭据时，不向它发送服务器默认密钥。
            if request_origin(base_url) != request_origin(
                getattr(settings, f"{prefix}_base_url"),
            ):
                api_key, source = None, "none"
        if saved.credential_cipher:
            api_key = None
            source = "account"
            try:
                api_key = (
                    credential_cipher(settings)
                    .decrypt(
                        saved.credential_cipher.encode("ascii"),
                    )
                    .decode("utf-8")
                )
            except (InvalidToken, ValueError, ModelSettingError):
                error_message = "保存的密钥无法读取，请重新填写 API Key"
    return ProviderConfiguration(
        model,
        base_url,
        api_key,
        enabled,
        source,
        saved is not None,
        error_message,
        custom_base_url=custom_base_url,
        min_confidence=min_confidence,
    )


def default_min_confidence(settings: Settings, provider: ModelProvider) -> float:
    """服务器默认的判定阈值；两个通道历史上各有默认值。"""

    if provider == ModelProvider.DEEPSEEK:
        return settings.classification_min_confidence
    return settings.jev_min_confidence


def read_model_setting(
    session: Session,
    user_id: str,
    settings: Settings,
    provider: ModelProvider,
) -> ModelSettingRead:
    """只返回配置状态与掩码，不暴露可调用的凭据。"""

    config = provider_configuration(session, user_id, settings, provider)
    key = config.api_key
    hint = ""
    if key:
        hint = f"••••{key[-4:]}" if len(key) > 8 else "••••"
    return ModelSettingRead(
        provider=provider,
        model=config.model,
        base_url=config.base_url,
        default_base_url=getattr(settings, f"{provider.value}_base_url"),
        custom_base_url=config.custom_base_url,
        enabled=config.enabled,
        has_api_key=bool(key),
        key_hint=hint,
        credential_source=config.source,
        has_custom_settings=config.has_custom_settings,
        error=config.error,
        min_confidence=(
            config.min_confidence
            if config.min_confidence is not None
            else default_min_confidence(settings, provider)
        ),
        default_min_confidence=default_min_confidence(settings, provider),
    )


def resolve_model_settings(
    session: Session,
    user_id: str,
    settings: Settings,
) -> Settings:
    """为一次请求或后台任务构造账号配置，避免修改共享设置。"""

    deepseek = provider_configuration(
        session,
        user_id,
        settings,
        ModelProvider.DEEPSEEK,
    )
    jev = provider_configuration(session, user_id, settings, ModelProvider.JEV)
    return replace(
        settings,
        deepseek_model=deepseek.model,
        deepseek_base_url=deepseek.base_url,
        deepseek_api_key=deepseek.api_key if deepseek.enabled else None,
        jev_model=jev.model,
        jev_base_url=jev.base_url,
        jev_api_key=jev.api_key if jev.enabled else None,
        classification_min_confidence=(
            deepseek.min_confidence
            if deepseek.min_confidence is not None
            else settings.classification_min_confidence
        ),
        jev_min_confidence=(
            jev.min_confidence
            if jev.min_confidence is not None
            else settings.jev_min_confidence
        ),
    )


def request_key(payload: ModelSettingUpdate) -> str | None:
    """校验新密钥；空白表示保留原凭据，错误不回显输入。"""

    key = payload.api_key.get_secret_value().strip() if payload.api_key else ""
    if (
        len(key) > 4_000
        or not key.isascii()
        or any(char.isspace() for char in key)
        or "\0" in key
    ):
        raise ModelSettingError("API Key 格式无效，请粘贴完整密钥")
    return key or None


def requested_configuration(
    current: ProviderConfiguration,
    settings: Settings,
    provider: ModelProvider,
    payload: ModelSettingUpdate,
) -> ProviderConfiguration:
    """计算未保存输入；切换服务时必须明确提供对应密钥。"""

    custom_url = (
        payload.base_url
        if "base_url" in payload.model_fields_set
        else current.custom_base_url
    )
    base_url = custom_url or getattr(
        settings,
        f"{provider.value}_base_url",
    )
    key = request_key(payload)
    if (
        request_origin(base_url) != request_origin(current.base_url)
        and not key
    ):
        raise ModelSettingError("更换服务地址时，请填写对应服务的 API Key")
    min_confidence = (
        payload.min_confidence
        if "min_confidence" in payload.model_fields_set
        else current.min_confidence
    )
    return replace(
        current,
        model=payload.model,
        enabled=payload.enabled,
        min_confidence=min_confidence,
        base_url=base_url,
        custom_base_url=custom_url,
        api_key=key or current.api_key,
        error=None if key else current.error,
    )


def save_model_setting(
    session: Session,
    user_id: str,
    settings: Settings,
    provider: ModelProvider,
    payload: ModelSettingUpdate,
) -> ModelSettingRead:
    """加密保存账号配置；模型名称更新不会清空已有密钥。"""

    current = provider_configuration(session, user_id, settings, provider)
    requested = requested_configuration(current, settings, provider, payload)
    key = request_key(payload)
    encrypted = (
        credential_cipher(settings).encrypt(key.encode()).decode("ascii")
        if key
        else None
    )
    # 显式开发模式可能尚未创建账号，保持外键关系有效。
    if settings.auth_dev_mode and user_id == settings.local_user_id:
        if session.get(User, user_id) is None:
            session.add(User(id=user_id, display_name="本地开发用户"))
            session.flush()
    saved = get_provider_setting(session, user_id, provider)
    if saved is None:
        saved = ModelProviderSetting(user_id=user_id, provider=provider.value)
        session.add(saved)
    saved.model = payload.model
    saved.enabled = payload.enabled
    saved.base_url = requested.custom_base_url
    saved.min_confidence = requested.min_confidence
    if encrypted is not None:
        saved.credential_cipher = encrypted
    session.commit()
    return read_model_setting(session, user_id, settings, provider)


def reset_model_setting(
    session: Session,
    user_id: str,
    settings: Settings,
    provider: ModelProvider,
) -> ModelSettingRead:
    """移除账号配置及凭据，恢复服务器默认配置。"""

    saved = get_provider_setting(session, user_id, provider)
    if saved is not None:
        session.delete(saved)
        session.commit()
    return read_model_setting(session, user_id, settings, provider)


def verify_model_connection(
    session: Session,
    user_id: str,
    settings: Settings,
    provider: ModelProvider,
    payload: ModelSettingUpdate | None = None,
    client: httpx.Client | None = None,
) -> ModelConnectionResult:
    """发送固定短文本测试实际模型接口，不读取收藏内容或保存输入。"""

    config = provider_configuration(session, user_id, settings, provider)
    if payload is not None:
        config = requested_configuration(config, settings, provider, payload)
    model, key = config.model, config.api_key
    if not key:
        raise ModelSettingError(config.error or "请先填写 API Key")
    if provider == ModelProvider.DEEPSEEK:
        endpoint = "/chat/completions"
        body = {
            "model": model,
            "messages": [{"role": "user", "content": "Reply OK."}],
            "thinking": {"type": "disabled"},
            # 中转服务可能保留推理模式，输出预算需涵盖推理和最终答复。
            "max_tokens": 256,
        }
    else:
        endpoint = "/systemone"
        body = {
            "model": model,
            "state": "This is a connection test.",
            "questions": {
                "test": {
                    "type": "choice",
                    "instructions": "Choose the connection test option.",
                    "criteria": {
                        "ok": "A connection test",
                        "other": "Content unrelated to a connection test",
                    },
                }
            },
        }
    owned_client = client is None
    timeout = (
        settings.deepseek_timeout_seconds
        if provider == ModelProvider.DEEPSEEK
        else 30.0
    )
    model_client = client if client is not None else httpx.Client(timeout=timeout)
    try:
        response = model_client.post(
            f"{config.base_url.rstrip('/')}{endpoint}",
            json=body,
            headers={"Authorization": f"Bearer {key}"},
        )
        response.raise_for_status()
        result = response.json()
        if provider == ModelProvider.DEEPSEEK:
            choice = result["choices"][0]
            content = _message_text(choice["message"]["content"])
            if not content:
                if choice.get("finish_reason") == "length":
                    raise ModelSettingError(
                        "模型已响应，但输出达到长度上限，未返回最终答复",
                    )
                raise ValueError("empty_response")
        elif result["answers"]["test"]["choice"] not in {"ok", "other"}:
            raise ValueError("invalid_choice")
    except ModelSettingError:
        raise
    except httpx.TimeoutException as error:
        raise ModelSettingError(
            "模型响应超时，请稍后重试或检查服务连接",
        ) from error
    except httpx.HTTPStatusError as error:
        raise ModelSettingError(describe_model_http_error(error)) from error
    except (
        httpx.HTTPError,
        KeyError,
        IndexError,
        TypeError,
        ValueError,
    ) as error:
        raise ModelSettingError(
            "连接失败或响应无效，请检查模型名称和服务状态",
        ) from error
    finally:
        if owned_client:
            model_client.close()
    return ModelConnectionResult(
        provider=provider,
        model=model,
        message="连接成功，模型接口可用",
    )
