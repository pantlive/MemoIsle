"""网页分类服务错误的安全提示与有限重试策略。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from math import isfinite

import httpx

MAX_AUTOMATIC_RETRIES = 2
MAX_RETRY_DELAY_SECONDS = 300.0
TRANSIENT_HTTP_STATUSES = {408, 429, 500, 502, 503, 504}
QUOTA_ERROR_CODES = {
    "insufficient_quota",
    "quota_exceeded",
    "insufficient_credits",
    "credit_balance_too_low",
    "balance_exhausted",
    "billing_hard_limit_reached",
}


@dataclass(frozen=True, slots=True)
class ClassificationServiceFailure:
    """只包含固定安全文案，不保存上游响应、请求地址或凭据。"""

    code: str
    message: str
    retryable: bool = False
    retry_after_seconds: float | None = None


def retry_after_seconds(response: httpx.Response, now: datetime) -> float | None:
    """解析服务端建议等待的秒数或 HTTP 日期，无效值使用本地退避。"""

    value = response.headers.get("Retry-After", "").strip()
    if not value:
        return None
    try:
        delay = float(value)
    except ValueError:
        try:
            target = parsedate_to_datetime(value)
            if target.tzinfo is None:
                target = target.replace(tzinfo=UTC)
            delay = (target - now).total_seconds()
        except (ValueError, TypeError, OverflowError):
            return None
    return max(0.0, delay) if isfinite(delay) else None


def is_quota_error(response: httpx.Response) -> bool:
    """仅识别白名单错误代码，不展示或记录可能包含密钥的原始消息。"""

    try:
        body = response.json()
    except ValueError:
        return False
    if not isinstance(body, dict):
        return False
    error = body.get("error")
    if not isinstance(error, dict):
        return False
    return any(
        isinstance(value, str) and value.lower() in QUOTA_ERROR_CODES
        for value in (error.get("code"), error.get("type"))
    )


def classify_service_failure(
    error: httpx.HTTPError | httpx.InvalidURL,
    now: datetime,
) -> ClassificationServiceFailure:
    """区分认证、额度、配置和临时服务错误，并生成可公开的提示。"""

    if isinstance(error, httpx.TimeoutException):
        return ClassificationServiceFailure(
            "timeout",
            "Jev 请求超时，请检查网络或中转服务状态",
            True,
        )
    if isinstance(error, httpx.HTTPStatusError):
        response = error.response
        status = response.status_code
        if status == 402 or is_quota_error(response):
            return ClassificationServiceFailure(
                "quota_exhausted",
                f"Jev 额度不足（HTTP {status}），请检查服务账户余额",
            )
        if status in {401, 403}:
            return ClassificationServiceFailure(
                "authentication",
                f"Jev 认证或权限失败（HTTP {status}），请检查 API Key 和模型权限",
            )
        if status in TRANSIENT_HTTP_STATUSES:
            code = "rate_limited" if status == 429 else "service_unavailable"
            message = (
                f"Jev 请求被限流（HTTP {status}）"
                if status == 429
                else f"Jev 服务暂时不可用（HTTP {status}）"
            )
            return ClassificationServiceFailure(
                code,
                message,
                True,
                retry_after_seconds(response, now),
            )
        if status == 404:
            return ClassificationServiceFailure(
                "model_not_found",
                "Jev 模型或请求地址不存在（HTTP 404），请检查模型设置",
            )
        if status in {400, 422}:
            return ClassificationServiceFailure(
                "invalid_request",
                f"Jev 拒绝分类请求（HTTP {status}），请检查模型、接口协议和模板设置",
            )
        return ClassificationServiceFailure(
            "http_error",
            f"Jev 服务请求失败（HTTP {status}），请检查模型设置与服务状态",
        )
    if isinstance(
        error,
        (
            httpx.InvalidURL,
            httpx.UnsupportedProtocol,
            httpx.LocalProtocolError,
        ),
    ):
        return ClassificationServiceFailure(
            "invalid_request",
            "Jev 请求地址或请求配置无效，请检查模型设置",
        )
    if isinstance(error, httpx.TransportError):
        return ClassificationServiceFailure(
            "network",
            "Jev 网络连接失败，请检查网络或中转服务状态",
            True,
        )
    return ClassificationServiceFailure(
        "request_failed",
        "Jev 服务请求失败，请检查模型设置与连接",
    )


def retry_delay_seconds(
    failure: ClassificationServiceFailure,
    retry_number: int,
) -> float:
    """采用五秒、十五秒退避，并遵守服务端更长的等待要求。"""

    return max(5.0 * 3 ** (retry_number - 1), failure.retry_after_seconds or 0.0)
