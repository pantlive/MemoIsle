"""浏览器扩展网页捕获与打开标签页快照业务。"""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BrowserCapture, BrowserOpenTab
from app.resource_processing import validate_public_resource_url
from app.schemas import (
    BrowserCaptureContext,
    BrowserCaptureCreate,
    BrowserCaptureCreated,
    BrowserTabSyncRequest,
)

PublicUrlValidator = Callable[[str], str]
OPEN_TAB_STALE_AFTER = timedelta(minutes=10)


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


def _upsert_open_tab(
    session: Session,
    user_id: str,
    extension_id: str,
    tab_id: int,
    window_id: int | None,
    page_url: str,
    page_title: str,
    favicon_url: str | None,
    now: datetime,
) -> BrowserOpenTab:
    """更新一个当前打开的浏览器标签页快照。"""

    page = session.scalar(
        select(BrowserOpenTab).where(
            BrowserOpenTab.user_id == user_id,
            BrowserOpenTab.extension_id == extension_id,
            BrowserOpenTab.tab_id == tab_id,
        )
    )
    if page is None:
        page = BrowserOpenTab(
            id=str(uuid4()),
            user_id=user_id,
            extension_id=extension_id,
            tab_id=tab_id,
            window_id=window_id,
            page_url=page_url,
            page_title=safe_capture_title(page_title, page_url),
            favicon_url=favicon_url,
            status="open",
            last_seen_at=now,
        )
        session.add(page)
        return page

    page.window_id = window_id
    page.page_url = page_url
    page.page_title = safe_capture_title(page_title, page_url)
    page.favicon_url = favicon_url
    page.status = "open"
    page.last_seen_at = now
    return page


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
    # 扩展点击当前页时顺便更新该标签页，完整快照由扩展事件持续同步。
    if payload.tab_id is not None:
        _upsert_open_tab(
            session,
            user_id,
            payload.extension_id,
            payload.tab_id,
            payload.window_id,
            page_url,
            payload.page_title,
            favicon_url,
            now,
        )
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


def sync_open_browser_tabs(
    session: Session,
    user_id: str,
    payload: BrowserTabSyncRequest,
    request_origin: str | None,
    url_validator: PublicUrlValidator = validate_public_resource_url,
) -> int:
    """同步当前浏览器所有可收藏的 HTTP(S) 标签页。"""

    expected_origin = f"chrome-extension://{payload.extension_id}"
    if request_origin != expected_origin:
        raise BrowserCaptureOriginError
    now = datetime.now(UTC)
    existing_pages = session.scalars(
        select(BrowserOpenTab).where(
            BrowserOpenTab.user_id == user_id,
            BrowserOpenTab.extension_id == payload.extension_id,
        )
    ).all()
    seen_tab_ids: set[int] = set()
    synced_count = 0
    for tab in payload.tabs:
        if tab.tab_id in seen_tab_ids:
            continue
        try:
            page_url = url_validator(tab.page_url)
        except (OSError, ValueError):
            # chrome://、file://、本地地址等不进入网页资料选择器。
            continue
        favicon_url: str | None = None
        if tab.favicon_url:
            try:
                favicon_url = url_validator(tab.favicon_url)
            except (OSError, ValueError):
                # 图标不可用不应阻止当前打开网页进入选择器。
                favicon_url = None
        _upsert_open_tab(
            session,
            user_id,
            payload.extension_id,
            tab.tab_id,
            tab.window_id,
            page_url,
            tab.page_title,
            favicon_url,
            now,
        )
        seen_tab_ids.add(tab.tab_id)
        synced_count += 1

    # 快照中缺失的标签页已关闭，Web 下次输入 @ 时不会继续展示。
    for page in existing_pages:
        if page.tab_id not in seen_tab_ids:
            page.status = "closed"
    session.commit()
    return synced_count


def list_open_browser_tabs(
    session: Session,
    user_id: str,
    limit: int = 20,
) -> list[BrowserOpenTab]:
    """读取扩展最近同步的当前打开网页。"""

    stale_before = datetime.now(UTC) - OPEN_TAB_STALE_AFTER
    query = (
        select(BrowserOpenTab)
        .where(
            BrowserOpenTab.user_id == user_id,
            BrowserOpenTab.status == "open",
            BrowserOpenTab.last_seen_at >= stale_before,
        )
        .order_by(
            BrowserOpenTab.last_seen_at.desc(),
            BrowserOpenTab.id.desc(),
        )
        .limit(limit)
    )
    return list(session.scalars(query).all())


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
