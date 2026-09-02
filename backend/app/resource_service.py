"""网页资料元数据与分类业务。"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.category_service import classification_categories, classification_rules
from app.config import Settings
from app.database import Database
from app.models import Memo
from app.resource_processing import (
    CategoryDecision,
    ResourceFetchError,
    ResourceMetadata,
    UnsafeResourceUrlError,
    classify_resource,
    classify_resource_by_user_rules,
    fetch_resource_metadata,
)
from app.schemas import MemoType, ResourceProcessStatus
from app.service import MemoNotFoundError, MemoTypeError, get_memo

MetadataFetcher = Callable[[str], ResourceMetadata]
ResourceClassifier = Callable[[ResourceMetadata], CategoryDecision]


def metadata_fingerprint(metadata: ResourceMetadata) -> str:
    """计算允许持久化元数据的稳定摘要。"""

    payload = json.dumps(
        {
            "final_url": metadata.final_url,
            "title": metadata.page_title,
            "description": metadata.description,
            "site_name": metadata.site_name,
            "image_url": metadata.image_url,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def fallback_metadata(memo: Memo) -> ResourceMetadata:
    """在网页抓取失败时用已有公开字段继续规则分类。"""

    source_url = memo.source_url or ""
    hostname = (urlsplit(source_url).hostname or "").removeprefix("www.")
    return ResourceMetadata(
        final_url=source_url,
        page_title=memo.resource_page_title or memo.source_title or memo.title,
        description=memo.resource_description,
        site_name=memo.resource_site_name or hostname or None,
        favicon_url=memo.resource_favicon_url,
        http_status=0,
        image_url=memo.resource_image_url,
    )


def safe_favicon_url(value: str | None) -> str | None:
    """只保留可由客户端识别的 HTTP(S) 图标地址。"""

    if value is None:
        return None
    parsed = urlsplit(value)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return None
    if parsed.username is not None or parsed.password is not None:
        return None
    return value[:2048]


def safe_resource_image_url(value: str | None) -> str | None:
    """只保留可由客户端安全加载的 HTTP(S) 封面地址。"""

    return safe_favicon_url(value)


def apply_category(memo: Memo, decision: CategoryDecision) -> None:
    """将自动分类结果写入条目。"""

    if memo.resource_category_source == "manual":
        return
    memo.resource_category = decision.category
    memo.resource_category_label = decision.category_label
    memo.resource_category_status = ResourceProcessStatus.READY
    memo.resource_category_confidence = decision.confidence
    memo.resource_category_source = decision.source
    memo.resource_auto_tags = list(decision.auto_tags)


def mark_processing(session: Session, memo: Memo) -> None:
    """将资料标记为后台处理中。"""

    now = datetime.now(UTC)
    memo.resource_metadata_status = ResourceProcessStatus.PROCESSING
    if memo.resource_category_source != "manual":
        memo.resource_category_status = ResourceProcessStatus.PROCESSING
    memo.updated_at = now
    memo.version += 1
    session.commit()


def enrich_resource(
    session: Session,
    user_id: str,
    memo_id: str,
    settings: Settings,
    metadata_fetcher: MetadataFetcher | None = None,
    classifier: ResourceClassifier | None = None,
) -> Memo:
    """抓取公开元数据、自动分类并更新基础巡检状态。"""

    memo = get_memo(session, user_id, memo_id)
    if memo.type != MemoType.RESOURCE or memo.source_url is None:
        raise MemoTypeError("只有网页资料可以执行元数据处理")
    mark_processing(session, memo)

    fetch_error: ResourceFetchError | UnsafeResourceUrlError | None = None
    try:
        if metadata_fetcher is None:
            metadata = fetch_resource_metadata(
                memo.source_url,
                timeout_seconds=settings.resource_fetch_timeout_seconds,
                max_bytes=settings.resource_fetch_max_bytes,
            )
        else:
            metadata = metadata_fetcher(memo.source_url)
    except (ResourceFetchError, UnsafeResourceUrlError) as error:
        fetch_error = error
        metadata = fallback_metadata(memo)

    if classifier is None:
        decision = classify_resource(
            metadata,
            llm_base_url=settings.llm_base_url,
            llm_api_key=settings.llm_api_key,
            llm_model=settings.llm_model,
            user_rules=classification_rules(session, user_id),
            category_options=classification_categories(session, user_id),
        )
    else:
        decision = classifier(metadata)

    now = datetime.now(UTC)
    if fetch_error is None:
        memo.resource_page_title = metadata.page_title
        memo.resource_description = metadata.description
        memo.resource_site_name = metadata.site_name
        memo.resource_favicon_url = safe_favicon_url(metadata.favicon_url)
        memo.resource_image_url = safe_resource_image_url(metadata.image_url)
        memo.resource_metadata_status = ResourceProcessStatus.READY
        memo.resource_metadata_error = None
        memo.resource_last_enriched_at = now
        if metadata.page_title and not memo.resource_title_user_defined:
            memo.title = metadata.page_title[:200]
            memo.source_title = metadata.page_title[:200]
        memo.link_health_status = (
            "redirected"
            if metadata.final_url != memo.source_url
            else "healthy"
        )
        memo.link_health_http_status = metadata.http_status
        memo.link_health_error = None
        memo.link_last_checked_at = now
        memo.link_last_success_at = now
        memo.link_next_check_at = now + timedelta(
            hours=settings.resource_health_interval_hours,
        )
        memo.link_consecutive_failures = 0
        memo.link_effective_url = metadata.final_url
        memo.link_metadata_fingerprint = metadata_fingerprint(metadata)
    else:
        error_code = (
            fetch_error.code
            if isinstance(fetch_error, ResourceFetchError)
            else str(fetch_error)
        )
        http_status = (
            fetch_error.http_status
            if isinstance(fetch_error, ResourceFetchError)
            else None
        )
        memo.resource_metadata_status = ResourceProcessStatus.FAILED
        memo.resource_metadata_error = error_code[:100]
        memo.link_health_http_status = http_status
        memo.link_health_error = error_code[:100]
        memo.link_last_checked_at = now
        memo.link_consecutive_failures += 1
        if http_status in {401, 403}:
            memo.link_health_status = "auth_required"
        else:
            memo.link_health_status = "temporary_failure"
        memo.link_next_check_at = now + timedelta(hours=24)

    apply_category(memo, decision)
    memo.updated_at = now
    memo.version += 1
    session.commit()
    session.refresh(memo)
    return memo


def enrich_resource_in_background(
    database_url: str,
    user_id: str,
    memo_id: str,
    settings: Settings,
) -> None:
    """使用独立会话执行 FastAPI 后台任务。"""

    database = Database(database_url)
    try:
        with database.session_factory() as session:
            try:
                enrich_resource(session, user_id, memo_id, settings)
            except (MemoNotFoundError, MemoTypeError):
                # 条目可能在任务执行前被删除或改型，此时安全结束。
                return
    finally:
        database.dispose()


def run_pending_resource_enrichments(
    database_url: str,
    settings: Settings,
    limit: int = 20,
) -> int:
    """恢复服务重启后遗留的网页元数据与分类任务。"""

    database = Database(database_url)
    processed_count = 0
    try:
        with database.session_factory() as session:
            pending_memos = list(
                session.scalars(
                    select(Memo)
                    .where(
                        Memo.type == MemoType.RESOURCE,
                        Memo.status != "trashed",
                        Memo.resource_metadata_status.in_({
                            ResourceProcessStatus.PENDING,
                            ResourceProcessStatus.PROCESSING,
                        }),
                    )
                    .order_by(Memo.updated_at.asc())
                    .limit(limit)
                ).all()
            )
            for memo in pending_memos:
                if memo.resource_metadata_status == ResourceProcessStatus.PROCESSING:
                    # 上一次进程可能在提交结果前退出，允许本轮恢复。
                    memo.resource_metadata_status = ResourceProcessStatus.PENDING
                    session.commit()
                try:
                    enrich_resource(session, memo.user_id, memo.id, settings)
                    processed_count += 1
                except (MemoNotFoundError, MemoTypeError):
                    continue
                except Exception:  # noqa: BLE001
                    # 单条异常不能杀死后台恢复循环，标记后等待人工重试。
                    session.rollback()
                    failed_memo = session.get(Memo, memo.id)
                    if failed_memo is not None:
                        failed_memo.resource_metadata_status = (
                            ResourceProcessStatus.FAILED
                        )
                        failed_memo.resource_metadata_error = "worker_error"
                        failed_memo.updated_at = datetime.now(UTC)
                        session.commit()
    finally:
        database.dispose()
    return processed_count


def apply_user_category_rules(
    session: Session,
    user_id: str,
) -> int:
    """把当前启用的用户规则应用到已有网页资料，不访问原网页。"""

    user_rules = classification_rules(session, user_id)
    if not user_rules:
        return 0
    resources = session.scalars(
        select(Memo).where(
            Memo.user_id == user_id,
            Memo.type == MemoType.RESOURCE,
            Memo.status != "trashed",
        )
    )
    changed_count = 0
    for memo in resources:
        if memo.resource_category_source == "manual":
            continue
        decision = classify_resource_by_user_rules(
            fallback_metadata(memo),
            user_rules,
        )
        if decision is None:
            continue
        previous_values = (
            memo.resource_category,
            memo.resource_category_label,
            memo.resource_category_source,
            memo.resource_auto_tags,
        )
        apply_category(memo, decision)
        current_values = (
            memo.resource_category,
            memo.resource_category_label,
            memo.resource_category_source,
            memo.resource_auto_tags,
        )
        if previous_values != current_values:
            memo.updated_at = datetime.now(UTC)
            memo.version += 1
            changed_count += 1
    session.commit()
    return changed_count


def apply_user_category_rules_in_background(
    database_url: str,
    user_id: str,
) -> None:
    """在独立会话中批量应用用户分类规则。"""

    database = Database(database_url)
    try:
        with database.session_factory() as session:
            apply_user_category_rules(session, user_id)
    finally:
        database.dispose()


def reclassify_user_rule_resources(
    session: Session,
    user_id: str,
    settings: Settings,
) -> int:
    """规则发生变化后重新判断曾由用户规则分类的资料。"""

    user_rules = classification_rules(session, user_id)
    categories = classification_categories(session, user_id)
    resources = session.scalars(
        select(Memo).where(
            Memo.user_id == user_id,
            Memo.type == MemoType.RESOURCE,
            Memo.status != "trashed",
            Memo.resource_category_source == "user_rule",
        )
    )
    changed_count = 0
    for memo in resources:
        if memo.resource_category_source == "manual":
            continue
        decision = classify_resource(
            fallback_metadata(memo),
            llm_base_url=settings.llm_base_url,
            llm_api_key=settings.llm_api_key,
            llm_model=settings.llm_model,
            user_rules=user_rules,
            category_options=categories,
        )
        previous_values = (
            memo.resource_category,
            memo.resource_category_label,
            memo.resource_category_source,
            memo.resource_auto_tags,
        )
        apply_category(memo, decision)
        current_values = (
            memo.resource_category,
            memo.resource_category_label,
            memo.resource_category_source,
            memo.resource_auto_tags,
        )
        if previous_values != current_values:
            memo.updated_at = datetime.now(UTC)
            memo.version += 1
            changed_count += 1
    session.commit()
    return changed_count


def reclassify_user_rule_resources_in_background(
    database_url: str,
    user_id: str,
    settings: Settings,
) -> None:
    """在独立会话中重新处理用户规则产生的资料。"""

    database = Database(database_url)
    try:
        with database.session_factory() as session:
            reclassify_user_rule_resources(session, user_id, settings)
    finally:
        database.dispose()
