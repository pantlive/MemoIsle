"""浏览器扩展当前页捕获业务。"""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BrowserCapture
from app.resource_processing import validate_public_resource_url
from app.schemas import (
    BrowserCaptureContext,
    BrowserCaptureCreate,
    BrowserCaptureCreated,
)

PublicUrlValidator = Callable[[str], str]


class BrowserCaptureOriginError(PermissionError):
    """扩展来源与声明的扩展标识不一致。"""


class BrowserCaptureNotFoundError(LookupError):
    """一次性网页捕获凭据不存在。"""


class BrowserCaptureExpiredError(ValueError):
    """一次性网页捕获凭据已经过期。"""


class BrowserCaptureConsumedError(ValueError):
    """一次性网页捕获凭据已经使用。"""


def token_hash(token: str) -> str:
    """只持久化一次性令牌摘要。"""

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def as_utc(value: datetime) -> datetime:
    """兼容 SQLite 返回的无时区时间。"""

    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def safe_capture_title(title: str, page_url: str) -> str:
    """清理扩展标题，并在缺失时使用可识别域名。"""

    cleaned = " ".join(title.split()).strip()
    if cleaned:
        return cleaned[:300]
    return (urlsplit(page_url).hostname or "网页资料").removeprefix("www.")[:300]


def create_browser_capture(
    session: Session,
    user_id: str,
    payload: BrowserCaptureCreate,
    request_origin: str | None,
    url_validator: PublicUrlValidator = validate_public_resource_url,
) -> BrowserCaptureCreated:
    """校验扩展来源与公网目标，并签发五分钟一次性令牌。"""

    expected_origin = f"chrome-extension://{payload.extension_id}"
    if request_origin != expected_origin:
        raise BrowserCaptureOriginError
    if len(payload.nonce) < 16:
        raise ValueError("invalid_nonce")
    page_url = url_validator(payload.page_url)
    favicon_url: str | None = None
    if payload.favicon_url:
        try:
            favicon_url = url_validator(payload.favicon_url)
        except (OSError, ValueError):
            # 图标不可用不应阻止用户收藏当前网页。
            favicon_url = None

    token = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    expires_at = now + timedelta(minutes=5)
    session.add(
        BrowserCapture(
            id=str(uuid4()),
            user_id=user_id,
            extension_id=payload.extension_id,
            nonce=payload.nonce,
            token_hash=token_hash(token),
            page_url=page_url,
            page_title=safe_capture_title(payload.page_title, page_url),
            favicon_url=favicon_url,
            status="pending",
            created_at=now,
            expires_at=expires_at,
        )
    )
    session.commit()
    return BrowserCaptureCreated(token=token, expires_at=expires_at)


def exchange_browser_capture(
    session: Session,
    user_id: str,
    token: str,
) -> BrowserCaptureContext:
    """一次性消费扩展网页上下文。"""

    capture = session.scalar(
        select(BrowserCapture).where(
            BrowserCapture.user_id == user_id,
            BrowserCapture.token_hash == token_hash(token),
        )
    )
    if capture is None:
        raise BrowserCaptureNotFoundError
    if capture.status == "consumed" or capture.consumed_at is not None:
        raise BrowserCaptureConsumedError
    now = datetime.now(UTC)
    if as_utc(capture.expires_at) <= now:
        capture.status = "expired"
        session.commit()
        raise BrowserCaptureExpiredError

    capture.status = "consumed"
    capture.consumed_at = now
    session.commit()
    return BrowserCaptureContext(
        page_url=capture.page_url,
        page_title=capture.page_title,
        favicon_url=capture.favicon_url,
        nonce=capture.nonce,
    )
