"""分类重试策略的等待时间、错误区分及敏感信息保护测试。"""

from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest
from app.resource_classification_retry import (
    ClassificationServiceFailure,
    classify_service_failure,
    retry_after_seconds,
    retry_delay_seconds,
)


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("75", 75.0),
        ("-5", 0.0),
        ("", None),
        ("bad", None),
        ("nan", None),
        ("inf", None),
    ],
)
def test_retry_after_numeric_or_invalid(
    header: str,
    expected: float | None,
) -> None:
    """有效秒数参与等待，无效或非有限值使用本地退避。"""

    response = httpx.Response(429, headers={"Retry-After": header})
    assert retry_after_seconds(response, datetime.now(UTC)) == expected


def test_retry_after_date_and_backoff() -> None:
    """HTTP 日期及服务端较长等待覆盖本地的五秒、十五秒退避。"""

    now = datetime(2026, 10, 2, tzinfo=UTC)
    response = httpx.Response(
        429,
        headers={
            "Retry-After": format_datetime(now + timedelta(seconds=120), usegmt=True),
        },
    )
    delay = retry_after_seconds(response, now)
    assert delay == 120
    failure = ClassificationServiceFailure("rate_limited", "限流", True, delay)
    assert retry_delay_seconds(failure, 1) == 120
    assert retry_delay_seconds(failure, 2) == 120
    failure = ClassificationServiceFailure("timeout", "超时", True)
    assert retry_delay_seconds(failure, 1) == 5
    assert retry_delay_seconds(failure, 2) == 15


@pytest.mark.parametrize("field", ["code", "type"])
def test_quota_error_is_terminal_even_when_http_status_is_429(field: str) -> None:
    """额度不足不能当作限流反复收费，原始服务消息不得出现在提示中。"""

    request = httpx.Request("POST", "https://relay.example/v1/systemone")
    response = httpx.Response(
        429,
        request=request,
        json={
            "error": {field: "insufficient_quota", "message": "private-key"},
        },
    )
    error = httpx.HTTPStatusError("private-key", request=request, response=response)
    failure = classify_service_failure(error, datetime.now(UTC))
    assert failure.code == "quota_exhausted"
    assert not failure.retryable
    assert "HTTP 429" in failure.message
    assert "private-key" not in failure.message


@pytest.mark.parametrize(
    "body",
    [
        [],
        {"error": "secret"},
        {
            "error": {
                "code": "rate_limit_exceeded",
                "message": "private-key",
            }
        },
    ],
)
def test_unknown_error_body_does_not_change_rate_limit_policy(body: object) -> None:
    """未知格式不推断额度情况，也不公开上游响应正文。"""

    request = httpx.Request("POST", "https://relay.example/v1/systemone")
    response = httpx.Response(429, request=request, json=body)
    error = httpx.HTTPStatusError("private-key", request=request, response=response)
    failure = classify_service_failure(error, datetime.now(UTC))
    assert failure.code == "rate_limited"
    assert failure.retryable
    assert "private-key" not in failure.message


@pytest.mark.parametrize(
    "error",
    [
        httpx.InvalidURL("private-key"),
        httpx.UnsupportedProtocol("private-key"),
        httpx.LocalProtocolError("private-key"),
    ],
)
def test_invalid_request_configuration_is_terminal(
    error: httpx.HTTPError | httpx.InvalidURL,
) -> None:
    """无效地址或协议需要修正设置，不以网络故障自动重试。"""

    failure = classify_service_failure(error, datetime.now(UTC))
    assert failure.code == "invalid_request"
    assert not failure.retryable
    assert "private-key" not in failure.message
