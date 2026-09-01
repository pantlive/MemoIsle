"""网页链接健康巡检、调度与处理动作。"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import Database
from app.models import LinkHealthEvent, Memo
from app.resource_processing import (
    ResourceFetchError,
    ResourceMetadata,
    UnsafeResourceUrlError,
    fetch_resource_metadata,
)
from app.resource_service import (
    enrich_resource,
    metadata_fingerprint,
    run_pending_resource_enrichments,
)
from app.schemas import (
    LinkHealthAction,
    LinkHealthActionRequest,
    LinkHealthStatus,
    MemoStatus,
    MemoType,
    MemoUpdate,
)
from app.service import (
    MemoNotFoundError,
    MemoTypeError,
    MemoVersionConflictError,
    get_memo,
    update_memo,
)

HealthFetcher = Callable[[str], ResourceMetadata]
ACTIONABLE_HEALTH_STATUSES = {
    LinkHealthStatus.FAILED,
    LinkHealthStatus.REDIRECTED,
    LinkHealthStatus.CHANGED,
    LinkHealthStatus.AUTH_REQUIRED,
    LinkHealthStatus.TEMPORARY_FAILURE,
}


def _record_event(
    session: Session,
    memo: Memo,
    event_type: str,
) -> None:
    """记录一次自动巡检或用户处理动作。"""

    session.add(
        LinkHealthEvent(
            id=str(uuid4()),
            user_id=memo.user_id,
            memo_id=memo.id,
            event_type=event_type,
            health_status=str(memo.link_health_status),
            http_status=memo.link_health_http_status,
            error_code=memo.link_health_error,
            effective_url=memo.link_effective_url,
            created_at=datetime.now(UTC),
        )
    )


def _success_next_check(now: datetime, settings: Settings) -> datetime:
    """为成功巡检添加小幅随机抖动。"""

    base_hours = max(1, settings.resource_health_interval_hours)
    jitter_minutes = random.uniform(0, min(base_hours * 3, 360))
    return now + timedelta(hours=base_hours, minutes=jitter_minutes)


def _failure_next_check(
    now: datetime,
    consecutive_failures: int,
    settings: Settings,
) -> datetime:
    """按连续失败次数应用有上限的指数退避。"""

    retry_hours = min(
        max(1, settings.resource_health_interval_hours),
        6 * (2 ** max(0, consecutive_failures - 1)),
    )
    return now + timedelta(hours=retry_hours, minutes=random.uniform(0, 30))


def check_resource_link(
    session: Session,
    user_id: str,
    memo_id: str,
    settings: Settings,
    fetcher: HealthFetcher | None = None,
    expected_version: int | None = None,
    force: bool = False,
) -> Memo:
    """受限访问一条网页资料，并更新其健康状态。"""

    memo = get_memo(session, user_id, memo_id)
    if memo.type != MemoType.RESOURCE or memo.source_url is None:
        raise MemoTypeError("只有网页资料可以执行链接巡检")
    if expected_version is not None and memo.version != expected_version:
        raise MemoVersionConflictError(memo)
    if memo.link_health_status == LinkHealthStatus.IGNORED and not force:
        return memo

    now = datetime.now(UTC)
    try:
        metadata = (
            fetcher(memo.source_url)
            if fetcher is not None
            else fetch_resource_metadata(
                memo.source_url,
                timeout_seconds=settings.resource_fetch_timeout_seconds,
                max_bytes=settings.resource_fetch_max_bytes,
            )
        )
        current_fingerprint = metadata_fingerprint(metadata)
        if metadata.final_url != memo.source_url:
            health_status = LinkHealthStatus.REDIRECTED
        elif (
            memo.link_metadata_fingerprint is not None
            and memo.link_metadata_fingerprint != current_fingerprint
        ):
            health_status = LinkHealthStatus.CHANGED
        else:
            health_status = LinkHealthStatus.HEALTHY
        memo.link_health_status = health_status
        memo.link_health_http_status = metadata.http_status
        memo.link_health_error = None
        memo.link_last_checked_at = now
        memo.link_last_success_at = now
        memo.link_next_check_at = _success_next_check(now, settings)
        memo.link_consecutive_failures = 0
        memo.link_effective_url = metadata.final_url
        if health_status != LinkHealthStatus.CHANGED:
            # 内容变化需要持续提醒，直到用户确认更新资料信息。
            memo.link_metadata_fingerprint = current_fingerprint
    except (ResourceFetchError, UnsafeResourceUrlError) as error:
        http_status = (
            error.http_status if isinstance(error, ResourceFetchError) else None
        )
        error_code = error.code if isinstance(error, ResourceFetchError) else str(error)
        memo.link_consecutive_failures += 1
        if http_status in {401, 403}:
            health_status = LinkHealthStatus.AUTH_REQUIRED
        elif http_status == 429 or (http_status is not None and http_status >= 500):
            health_status = LinkHealthStatus.TEMPORARY_FAILURE
        elif memo.link_consecutive_failures >= settings.resource_failure_threshold:
            health_status = LinkHealthStatus.FAILED
        else:
            health_status = LinkHealthStatus.TEMPORARY_FAILURE
        memo.link_health_status = health_status
        memo.link_health_http_status = http_status
        memo.link_health_error = error_code[:100]
        memo.link_last_checked_at = now
        memo.link_next_check_at = _failure_next_check(
            now,
            memo.link_consecutive_failures,
            settings,
        )

    memo.version += 1
    memo.updated_at = now
    _record_event(session, memo, "automatic_check" if not force else "manual_check")
    session.commit()
    session.refresh(memo)
    return memo


def list_link_health_center(
    session: Session,
    user_id: str,
    health_status: LinkHealthStatus | None = None,
    limit: int = 200,
) -> tuple[list[Memo], dict[str, int]]:
    """读取巡检中心待处理资料，并汇总全部健康状态。"""

    all_resources = list(
        session.scalars(
            select(Memo).where(
                Memo.user_id == user_id,
                Memo.type == MemoType.RESOURCE,
                Memo.status != MemoStatus.TRASHED,
            )
        ).all()
    )
    counts = {status.value: 0 for status in LinkHealthStatus}
    for memo in all_resources:
        counts[str(memo.link_health_status)] = (
            counts.get(str(memo.link_health_status), 0) + 1
        )
    if health_status is None:
        selected = [
            memo
            for memo in all_resources
            if memo.link_health_status in ACTIONABLE_HEALTH_STATUSES
        ]
    else:
        selected = [
            memo
            for memo in all_resources
            if memo.link_health_status == health_status
        ]
    selected.sort(
        key=lambda memo: memo.link_last_checked_at or memo.updated_at,
        reverse=True,
    )
    return selected[:limit], counts


def apply_link_health_action(
    session: Session,
    user_id: str,
    memo_id: str,
    payload: LinkHealthActionRequest,
    settings: Settings,
) -> Memo:
    """执行重试、忽略、网址更新、元数据更新或删除动作。"""

    memo = get_memo(session, user_id, memo_id)
    if memo.type != MemoType.RESOURCE:
        raise MemoTypeError("只有网页资料可以处理巡检结果")
    if memo.version != payload.expected_version:
        raise MemoVersionConflictError(memo)

    if payload.action == LinkHealthAction.RETRY:
        result = check_resource_link(
            session,
            user_id,
            memo_id,
            settings,
            expected_version=payload.expected_version,
            force=True,
        )
    elif payload.action == LinkHealthAction.UPDATE_METADATA:
        result = enrich_resource(session, user_id, memo_id, settings)
    elif payload.action in {
        LinkHealthAction.ADOPT_REDIRECT,
        LinkHealthAction.UPDATE_URL,
    }:
        replacement_url = (
            memo.link_effective_url
            if payload.action == LinkHealthAction.ADOPT_REDIRECT
            else payload.new_url
        )
        if not replacement_url or replacement_url == memo.source_url:
            raise ValueError("没有可采用的新网址")
        result = update_memo(
            session,
            user_id,
            memo_id,
            MemoUpdate(
                expected_version=payload.expected_version,
                source_url=replacement_url,
            ),
        )
    elif payload.action == LinkHealthAction.DELETE:
        result = update_memo(
            session,
            user_id,
            memo_id,
            MemoUpdate(
                expected_version=payload.expected_version,
                status=MemoStatus.TRASHED,
            ),
        )
    else:
        now = datetime.now(UTC)
        if payload.action == LinkHealthAction.IGNORE:
            memo.link_health_status = LinkHealthStatus.IGNORED
            memo.link_next_check_at = None
        elif payload.action == LinkHealthAction.RESUME:
            memo.link_health_status = LinkHealthStatus.UNCHECKED
            memo.link_health_error = None
            memo.link_next_check_at = now
        memo.version += 1
        memo.updated_at = now
        session.commit()
        session.refresh(memo)
        result = memo

    _record_event(session, result, f"user_{payload.action.value}")
    session.commit()
    return result


def run_due_link_checks(database_url: str, settings: Settings) -> int:
    """顺序处理到期资料，并限制同一轮每个站点只访问一次。"""

    database = Database(database_url)
    checked_count = 0
    try:
        with database.session_factory() as session:
            now = datetime.now(UTC)
            due_memos = list(
                session.scalars(
                    select(Memo)
                    .where(
                        Memo.type == MemoType.RESOURCE,
                        Memo.status != MemoStatus.TRASHED,
                        Memo.link_health_status != LinkHealthStatus.IGNORED,
                        Memo.link_next_check_at.is_not(None),
                        Memo.link_next_check_at <= now,
                    )
                    .order_by(Memo.link_next_check_at.asc())
                    .limit(100)
                ).all()
            )
            visited_hosts: set[str] = set()
            for memo in due_memos:
                hostname = (urlsplit(memo.source_url or "").hostname or "").lower()
                if not hostname or hostname in visited_hosts:
                    continue
                visited_hosts.add(hostname)
                try:
                    check_resource_link(
                        session,
                        memo.user_id,
                        memo.id,
                        settings,
                    )
                except (MemoNotFoundError, MemoTypeError):
                    continue
                except Exception:  # noqa: BLE001
                    # 单条巡检异常不能终止后续站点的调度。
                    session.rollback()
                    continue
                checked_count += 1
    finally:
        database.dispose()
    return checked_count


async def link_health_monitor_loop(
    database_url: str,
    settings: Settings,
    stop_event: asyncio.Event,
) -> None:
    """应用生命周期内周期运行到期网页巡检。"""

    interval_seconds = max(5, settings.resource_worker_interval_seconds)
    while not stop_event.is_set():
        if settings.resource_enrichment_enabled:
            await asyncio.to_thread(
                run_pending_resource_enrichments,
                database_url,
                settings,
            )
        await asyncio.to_thread(run_due_link_checks, database_url, settings)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except TimeoutError:
            continue
