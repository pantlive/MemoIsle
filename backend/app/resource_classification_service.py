"""现有网页的持久化批量模型分类，支持跳过、并发保护和断点恢复。"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.category_service import (
    category_code_exists,
    classification_categories,
    classification_rules,
)
from app.config import Settings
from app.database import Database
from app.model_settings_service import resolve_model_settings
from app.models import Memo, ResourceClassificationJob
from app.resource_classification_policy import health_allows_ai_classification
from app.resource_classification_quality import (
    ClassificationAssessment,
    UncertainClassificationError,
    empty_assessment,
)
from app.resource_classification_retry import (
    MAX_AUTOMATIC_RETRIES,
    MAX_RETRY_DELAY_SECONDS,
    ClassificationServiceFailure,
    classify_service_failure,
    retry_delay_seconds,
)
from app.resource_processing import (
    CategoryDecision,
    ResourceFetchError,
    ResourceMetadata,
    UnsafeResourceUrlError,
    classify_resource_by_user_rules,
    classify_resource_with_jev,
    fetch_resource_metadata,
)
from app.resource_service import fallback_metadata, metadata_fingerprint
from app.schemas import (
    MemoType,
    ResourceClassificationJobRead,
    ResourceClassificationState,
)

ACTIVE_STATUSES = {"pending", "processing"}
AI_SOURCES = {"jev", "llm"}
PROTECTED_SOURCES = {"manual", "user_rule"}
LEASE_SECONDS = 60


class ResourceClassificationConfigurationError(ValueError):
    """模型配置不可用；错误消息可安全展示。"""


class ResourceClassificationStateError(ValueError):
    """当前账号没有可继续的暂停任务。"""


def never_stop() -> bool:
    """独立执行时默认不中断任务。"""

    return False


def resource_filters(user_id: str | None = None) -> tuple[ColumnElement[bool], ...]:
    """限定当前账号的有效网页，不包含回收站和云盘电子书文件。"""

    common = (
        Memo.type == MemoType.RESOURCE,
        Memo.status != "trashed",
        Memo.source_url.is_not(None),
        Memo.ebook_provider.is_(None),
    )
    return (*common, Memo.user_id == user_id) if user_id is not None else common


def pending_filters(automatic: bool = False) -> tuple[ColumnElement[bool], ...]:
    """规则分类不算完成模型处理；手动分类和明确用户规则优先保留。"""

    common = (
        Memo.link_health_status == "healthy",
        Memo.resource_ai_review_required.is_(False),
        Memo.resource_ai_classified_at.is_(None),
        Memo.resource_ai_confirmation.is_(None),
        or_(
            Memo.resource_category_source.is_(None),
            Memo.resource_category_source.not_in(AI_SOURCES | PROTECTED_SOURCES),
        ),
    )
    return (*common, Memo.resource_ai_auto_pending.is_(True)) if automatic else common


def confirmation_filters(user_id: str) -> tuple[ColumnElement[bool], ...]:
    """分类复核仅包含可处理的未确定网页，巡检确认独立进行。"""

    return (
        *resource_filters(user_id),
        *pending_filters(),
        Memo.resource_ai_confirmation_pending.is_(True),
    )


def classification_state(
    session: Session,
    user_id: str,
) -> ResourceClassificationState:
    """读取未处理数量与进度，不暴露队列、账号标识或凭据。"""

    filters = resource_filters(user_id)
    pending = (
        session.scalar(
            select(func.count()).select_from(Memo).where(*filters, *pending_filters()),
        )
        or 0
    )
    classified = (
        session.scalar(
            select(func.count())
            .select_from(Memo)
            .where(
                *filters,
                or_(
                    Memo.resource_ai_classified_at.is_not(None),
                    Memo.resource_category_source.in_(AI_SOURCES),
                ),
            ),
        )
        or 0
    )
    protected = (
        session.scalar(
            select(func.count())
            .select_from(Memo)
            .where(
                *filters,
                or_(
                    Memo.resource_category_source.in_(PROTECTED_SOURCES),
                    Memo.resource_ai_confirmation.is_not(None),
                ),
            ),
        )
        or 0
    )
    deferred = (
        session.scalar(
            select(func.count())
            .select_from(Memo)
            .where(
                *filters,
                or_(
                    Memo.link_health_status != "healthy",
                    Memo.resource_ai_review_required.is_(True),
                ),
            ),
        )
        or 0
    )
    job = session.get(ResourceClassificationJob, user_id)
    return ResourceClassificationState(
        pending_count=pending,
        classified_count=classified,
        protected_count=protected,
        deferred_count=deferred,
        review_count=session.scalar(
            select(func.count())
            .select_from(Memo)
            .where(*confirmation_filters(user_id)),
        )
        or 0,
        job=ResourceClassificationJobRead.model_validate(job) if job else None,
    )


def configured_settings(
    session: Session,
    user_id: str,
    settings: Settings,
) -> Settings:
    """验证分类模型可用；服务故障时不会改用规则伪装为完成。"""

    resolved = resolve_model_settings(session, user_id, settings)
    if not resolved.jev_api_key or not resolved.jev_model:
        raise ResourceClassificationConfigurationError(
            "请在设置 → 模型服务中配置并启用 Jev",
        )
    if len(classification_categories(session, user_id)) > 255:
        raise ResourceClassificationConfigurationError(
            "Jev 一次最多支持 255 个启用分类，请减少启用的模板",
        )
    return resolved


def start_classification_job(
    session: Session,
    user_id: str,
    settings: Settings,
    automatic: bool = False,
) -> ResourceClassificationJob:
    """固定本轮待处理条目，重复点击返回已有任务，避免重复调用模型。"""

    current = session.get(ResourceClassificationJob, user_id)
    if current is not None and current.status in ACTIVE_STATUSES:
        return current
    if current is not None and current.status == "failed":
        # 旧客户端仍使用启动接口时，也必须继续原队列而不是重新收费。
        return resume_classification_job(session, user_id, settings)
    memo_ids = list(
        session.scalars(
            select(Memo.id)
            .where(*resource_filters(user_id), *pending_filters(automatic))
            .order_by(Memo.created_at.asc(), Memo.id.asc()),
        ).all()
    )
    resolved = configured_settings(session, user_id, settings) if memo_ids else settings
    now = datetime.now(UTC)
    values = {
        "id": str(uuid4()),
        "status": "pending" if memo_ids else "completed",
        "model": resolved.jev_model,
        "automatic": automatic,
        "memo_ids": memo_ids,
        "total_count": len(memo_ids),
        "processed_count": 0,
        "succeeded_count": 0,
        "failed_count": 0,
        "skipped_count": 0,
        "error": None,
        "error_code": None,
        "retry_count": 0,
        "next_retry_at": None,
        "worker_token": None,
        "lease_expires_at": None,
        "created_at": now,
        "updated_at": now,
        "finished_at": None if memo_ids else now,
    }
    if current is None:
        session.add(ResourceClassificationJob(user_id=user_id, **values))
        try:
            session.commit()
        except IntegrityError:
            # 账号主键约束处理首次并发启动，沿用已经发布的任务。
            session.rollback()
    else:
        session.execute(
            update(ResourceClassificationJob)
            .where(
                ResourceClassificationJob.user_id == user_id,
                ResourceClassificationJob.id == current.id,
                ResourceClassificationJob.status.not_in(ACTIVE_STATUSES),
            )
            .values(**values),
        )
        session.commit()
    session.expire_all()
    job = session.get(ResourceClassificationJob, user_id)
    assert job is not None
    return job


def resume_classification_job(
    session: Session,
    user_id: str,
    settings: Settings,
) -> ResourceClassificationJob:
    """恢复失败位置，保留任务编号、队列、全部已处理计数和创建时间。"""

    current = session.get(ResourceClassificationJob, user_id)
    if current is not None and current.status in ACTIVE_STATUSES:
        return current
    if current is None or current.status != "failed":
        raise ResourceClassificationStateError("当前没有暂停的分类任务")
    resolved = configured_settings(session, user_id, settings)
    session.execute(
        update(ResourceClassificationJob)
        .where(
            ResourceClassificationJob.user_id == user_id,
            ResourceClassificationJob.id == current.id,
            ResourceClassificationJob.status == "failed",
        )
        .values(
            status="pending",
            model=resolved.jev_model,
            error=None,
            error_code=None,
            retry_count=0,
            next_retry_at=None,
            worker_token=None,
            lease_expires_at=None,
            finished_at=None,
            updated_at=datetime.now(UTC),
        )
    )
    session.commit()
    session.expire_all()
    job = session.get(ResourceClassificationJob, user_id)
    assert job is not None
    return job


def update_owned_job(
    session: Session,
    user_id: str,
    job_id: str,
    token: str,
    **values: object,
) -> bool:
    """只允许当前租约持有者更新任务，防止旧工作线程覆盖新任务。"""

    result = session.execute(
        update(ResourceClassificationJob)
        .where(
            ResourceClassificationJob.user_id == user_id,
            ResourceClassificationJob.id == job_id,
            ResourceClassificationJob.worker_token == token,
            ResourceClassificationJob.status == "processing",
        )
        .values(**values),
    )
    return result.rowcount == 1


def prepare_classification_metadata(
    session: Session,
    user_id: str,
    job_id: str,
    token: str,
    memo: Memo,
    settings: Settings,
) -> ResourceMetadata | None:
    """补充公开正文并缓存；发现新的巡检问题时暂缓，不调用模型。"""

    metadata = fallback_metadata(memo)
    if (
        not settings.resource_enrichment_enabled
        or memo.resource_text_excerpt is not None
    ):
        return metadata
    memo_id, version = memo.id, memo.version
    fingerprint = memo.link_metadata_fingerprint
    session.rollback()
    now = datetime.now(UTC)
    health_status: str | None = None
    http_status: int | None = None
    fetched: ResourceMetadata | None = None
    try:
        fetched = fetch_resource_metadata(
            metadata.final_url,
            timeout_seconds=settings.resource_fetch_timeout_seconds,
            max_bytes=settings.resource_fetch_max_bytes,
            include_text_excerpt=True,
        )
        http_status = fetched.http_status
        if fetched.final_url != metadata.final_url:
            health_status = "redirected"
        elif fingerprint and metadata_fingerprint(fetched) != fingerprint:
            health_status = "changed"
    except (ResourceFetchError, UnsafeResourceUrlError) as error:
        http_status = (
            error.http_status if isinstance(error, ResourceFetchError) else None
        )
        health_status = (
            "auth_required" if http_status in {401, 403} else "temporary_failure"
        )

    # 抓取和模型请求期间不持有数据库事务，写入前再次验证租约和版本。
    if not update_owned_job(session, user_id, job_id, token, updated_at=now):
        session.rollback()
        return None
    values: dict[str, object] = {"version": Memo.version + 1, "updated_at": now}
    if health_status:
        values.update(
            link_health_status=health_status,
            link_health_http_status=http_status,
            link_health_error="classification_content_fetch_failed"
            if fetched is None
            else None,
            link_effective_url=fetched.final_url if fetched else metadata.final_url,
            link_last_checked_at=now,
            resource_ai_review_required=True,
        )
    else:
        assert fetched is not None
        values.update(
            resource_text_excerpt=fetched.text_excerpt or "",
            resource_page_title=fetched.page_title or metadata.page_title,
            resource_description=fetched.description or metadata.description,
            resource_site_name=fetched.site_name or metadata.site_name,
            resource_last_enriched_at=now,
            link_metadata_fingerprint=metadata_fingerprint(fetched),
        )
    result = session.execute(
        update(Memo)
        .where(
            Memo.id == memo_id,
            *resource_filters(user_id),
            *pending_filters(),
            Memo.version == version,
        )
        .values(**values)
    )
    session.commit()
    if health_status or result.rowcount != 1:
        return None
    session.expire_all()
    current = session.get(Memo, memo_id)
    return fallback_metadata(current) if current is not None else None


def save_item_result(
    session: Session,
    user_id: str,
    job_id: str,
    token: str,
    memo_id: str,
    version: int | None,
    decision: CategoryDecision | None,
    failed: bool = False,
    assessment: ClassificationAssessment | None = None,
) -> bool:
    """条目结果和队列进度原子提交，避免重启后重复处理已完成网页。"""

    now = datetime.now(UTC)
    if not update_owned_job(session, user_id, job_id, token, updated_at=now):
        session.rollback()
        return False
    succeeded = False
    failure_saved = False
    if decision is not None and category_code_exists(
        session,
        user_id,
        decision.category,
        active_only=True,
    ):
        # 乐观锁保护处理期间的手动修改、删除和网址变更。
        result = session.execute(
            update(Memo)
            .where(
                Memo.id == memo_id,
                *resource_filters(user_id),
                *pending_filters(),
                Memo.version == version,
            )
            .values(
                resource_category=decision.category,
                resource_category_label=decision.category_label,
                resource_categories=[decision.category, *decision.extra_categories],
                resource_category_status="ready",
                resource_category_confidence=decision.confidence,
                resource_category_source=decision.source,
                resource_auto_tags=list(decision.auto_tags),
                resource_ai_classified_at=now
                if decision.source in AI_SOURCES
                else None,
                resource_ai_auto_pending=False,
                resource_ai_assessment=decision.assessment,
                resource_ai_confirmation_pending=False,
                updated_at=now,
                version=Memo.version + 1,
            )
        )
        succeeded = result.rowcount == 1 and decision.source in AI_SOURCES
    elif failed:
        # 自动尝试一次后保留原分类；仅人工触发的重试会再次请求此网页。
        result = session.execute(
            update(Memo)
            .where(
                Memo.id == memo_id,
                *resource_filters(user_id),
                *pending_filters(),
                Memo.version == version,
            )
            .values(
                resource_ai_auto_pending=False,
                resource_ai_assessment=assessment,
                resource_ai_confirmation_pending=True,
                version=Memo.version + 1,
                updated_at=now,
            )
        )
        failure_saved = result.rowcount == 1
    counter = (
        "succeeded_count"
        if succeeded
        else "failed_count"
        if failure_saved
        else "skipped_count"
    )
    update_owned_job(
        session,
        user_id,
        job_id,
        token,
        processed_count=ResourceClassificationJob.processed_count + 1,
        error=None,
        error_code=None,
        retry_count=0,
        next_retry_at=None,
        **{counter: getattr(ResourceClassificationJob, counter) + 1},
    )
    session.commit()
    return True


def record_service_failure(
    session: Session,
    user_id: str,
    job_id: str,
    token: str,
    failure: ClassificationServiceFailure,
) -> None:
    """只重试当前失败请求，等待期间释放租约和事务，不推进处理游标。"""

    session.expire_all()
    job = session.get(ResourceClassificationJob, user_id)
    if job is None or job.id != job_id or job.worker_token != token:
        return
    now = datetime.now(UTC)
    retry_number = job.retry_count + 1
    delay = retry_delay_seconds(failure, retry_number)
    can_retry = (
        failure.retryable
        and retry_number <= MAX_AUTOMATIC_RETRIES
        and delay <= MAX_RETRY_DELAY_SECONDS
    )
    message = failure.message
    if failure.retryable and not can_retry:
        message += (
            "；服务要求等待超过五分钟，任务已暂停，请稍后继续"
            if delay > MAX_RETRY_DELAY_SECONDS
            else (
                f"；已自动重试 {MAX_AUTOMATIC_RETRIES} 次，任务已暂停，可从当前位置继续"
            )
        )
    update_owned_job(
        session,
        user_id,
        job_id,
        token,
        status="pending" if can_retry else "failed",
        error=message,
        error_code=failure.code,
        retry_count=retry_number if can_retry else job.retry_count,
        next_retry_at=now + timedelta(seconds=delay) if can_retry else None,
        worker_token=None,
        lease_expires_at=None,
        finished_at=None if can_retry else now,
        updated_at=now,
    )
    session.commit()


def process_classification_job(
    session: Session,
    user_id: str,
    settings: Settings,
    stop_requested: Callable[[], bool] = never_stop,
) -> int:
    """串行调用 Jev 分类待处理网页；完成标记和任务进度持久化。"""

    now = datetime.now(UTC)
    token = str(uuid4())
    claimed = session.execute(
        update(ResourceClassificationJob)
        .where(
            ResourceClassificationJob.user_id == user_id,
            ResourceClassificationJob.status.in_(ACTIVE_STATUSES),
            or_(
                ResourceClassificationJob.next_retry_at.is_(None),
                ResourceClassificationJob.next_retry_at <= now,
            ),
            or_(
                ResourceClassificationJob.lease_expires_at.is_(None),
                ResourceClassificationJob.lease_expires_at <= now,
            ),
        )
        .values(
            status="processing",
            next_retry_at=None,
            worker_token=token,
            lease_expires_at=now + timedelta(seconds=LEASE_SECONDS),
            updated_at=now,
        )
    )
    session.commit()
    if claimed.rowcount != 1:
        return 0
    processed = 0
    while True:
        session.expire_all()
        job = session.get(ResourceClassificationJob, user_id)
        if job is None or job.worker_token != token:
            return processed
        job_id = job.id
        now = datetime.now(UTC)
        if stop_requested():
            update_owned_job(
                session,
                user_id,
                job_id,
                token,
                status="pending",
                worker_token=None,
                lease_expires_at=None,
                updated_at=now,
            )
            session.commit()
            return processed
        if job.processed_count >= job.total_count:
            update_owned_job(
                session,
                user_id,
                job_id,
                token,
                status="completed",
                worker_token=None,
                lease_expires_at=None,
                finished_at=now,
                updated_at=now,
            )
            session.commit()
            return processed
        memo_id = job.memo_ids[job.processed_count]
        renewed = update_owned_job(
            session,
            user_id,
            job_id,
            token,
            lease_expires_at=now + timedelta(seconds=LEASE_SECONDS),
            updated_at=now,
        )
        session.commit()
        if not renewed:
            return processed
        memo = session.get(Memo, memo_id)
        if (
            memo is None
            or memo.user_id != user_id
            or memo.type != MemoType.RESOURCE
            or memo.status == "trashed"
            or not memo.source_url
            or memo.ebook_provider is not None
            or memo.resource_ai_classified_at is not None
            or memo.resource_ai_confirmation is not None
            or memo.resource_category_source in AI_SOURCES | PROTECTED_SOURCES
            or not health_allows_ai_classification(memo)
        ):
            if not save_item_result(
                session,
                user_id,
                job_id,
                token,
                memo_id,
                None,
                None,
            ):
                return processed
            processed += 1
            continue
        metadata = fallback_metadata(memo)
        version = memo.version
        try:
            resolved = configured_settings(session, user_id, settings)
            categories = classification_categories(session, user_id)
            user_rule = classify_resource_by_user_rules(
                metadata,
                classification_rules(session, user_id),
            )
            if user_rule is not None:
                # 本轮开始后新增的明确用户规则仍然优先，不调用收费模型。
                if not save_item_result(
                    session,
                    user_id,
                    job_id,
                    token,
                    memo_id,
                    version,
                    user_rule,
                ):
                    return processed
                processed += 1
                continue
            metadata = prepare_classification_metadata(
                session,
                user_id,
                job_id,
                token,
                memo,
                resolved,
            )
            if metadata is None:
                if not save_item_result(
                    session,
                    user_id,
                    job_id,
                    token,
                    memo_id,
                    None,
                    None,
                ):
                    return processed
                processed += 1
                continue
            session.expire_all()
            memo = session.get(Memo, memo_id)
            if (
                memo is None
                or memo.status == "trashed"
                or memo.resource_category_source in AI_SOURCES | PROTECTED_SOURCES
                or memo.resource_ai_classified_at is not None
                or memo.resource_ai_confirmation is not None
                or not health_allows_ai_classification(memo)
            ):
                if not save_item_result(
                    session,
                    user_id,
                    job_id,
                    token,
                    memo_id,
                    None,
                    None,
                ):
                    return processed
                processed += 1
                continue
            version = memo.version
            user_rule = classify_resource_by_user_rules(
                metadata,
                classification_rules(session, user_id),
            )
            if user_rule is not None:
                if not save_item_result(
                    session,
                    user_id,
                    job_id,
                    token,
                    memo_id,
                    version,
                    user_rule,
                ):
                    return processed
                processed += 1
                continue
            session.rollback()
            decision = classify_resource_with_jev(
                metadata,
                categories,
                resolved.jev_api_key or "",
                resolved.jev_base_url,
                resolved.jev_model,
                resolved.jev_min_confidence,
            )
        except (
            ResourceClassificationConfigurationError,
            httpx.HTTPError,
            httpx.InvalidURL,
        ) as error:
            session.rollback()
            failure = (
                ClassificationServiceFailure("configuration", str(error))
                if isinstance(error, ResourceClassificationConfigurationError)
                else classify_service_failure(error, datetime.now(UTC))
            )
            record_service_failure(
                session,
                user_id,
                job_id,
                token,
                failure,
            )
            return processed
        except (KeyError, TypeError, ValueError) as error:
            session.rollback()
            # 不确定或无效类别保留原分类，不标记为完成，允许下次重试。
            if not save_item_result(
                session,
                user_id,
                job_id,
                token,
                memo_id,
                version,
                None,
                failed=True,
                assessment=error.assessment
                if isinstance(error, UncertainClassificationError)
                else empty_assessment(
                    "invalid_response",
                    resolved.jev_min_confidence,
                    resolved.jev_model,
                    bool(metadata.text_excerpt),
                    metadata.text_excerpt,
                ),
            ):
                return processed
        else:
            if not save_item_result(
                session,
                user_id,
                job_id,
                token,
                memo_id,
                version,
                decision,
            ):
                return processed
        processed += 1


def queue_automatic_classifications(session: Session, settings: Settings) -> int:
    """发现新导入或人工确认后的合格网页，自动启动所属账号的任务。"""

    user_ids = list(
        session.scalars(
            select(Memo.user_id)
            .where(
                *resource_filters(),
                *pending_filters(automatic=True),
            )
            .distinct(),
        ).all()
    )
    queued = 0
    for user_id in user_ids:
        current = session.get(ResourceClassificationJob, user_id)
        if current is not None and current.status in ACTIVE_STATUSES | {"failed"}:
            # 新导入将在本轮结束后继续；服务故障暂停时不反复重试上游。
            continue
        try:
            start_classification_job(session, user_id, settings, automatic=True)
        except ResourceClassificationConfigurationError:
            continue
        queued += 1
    return queued


def run_pending_classification_jobs(
    database_url: str,
    settings: Settings,
    stop_requested: Callable[[], bool] = never_stop,
) -> int:
    """恢复排队或租约过期的任务，账号之间独立处理。"""

    database = Database(database_url)
    processed = 0
    try:
        with database.session_factory() as session:
            queue_automatic_classifications(session, settings)
            user_ids = list(
                session.scalars(
                    select(ResourceClassificationJob.user_id).where(
                        ResourceClassificationJob.status.in_(ACTIVE_STATUSES),
                        or_(
                            ResourceClassificationJob.next_retry_at.is_(None),
                            ResourceClassificationJob.next_retry_at
                            <= datetime.now(UTC),
                        ),
                    ),
                ).all()
            )
            for user_id in user_ids:
                if stop_requested():
                    break
                processed += process_classification_job(
                    session,
                    user_id,
                    settings,
                    stop_requested,
                )
    finally:
        database.dispose()
    return processed


async def resource_classification_loop(
    database_url: str,
    settings: Settings,
    stop_event: asyncio.Event,
) -> None:
    """独立后台循环，关闭网页不打断分类，退出时释放任务供重启恢复。"""

    while not stop_event.is_set():
        await asyncio.to_thread(
            run_pending_classification_jobs,
            database_url,
            settings,
            stop_event.is_set,
        )
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=3.0)
        except TimeoutError:
            continue
