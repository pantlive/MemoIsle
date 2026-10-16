"""网页资料元数据与分类业务。"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

import httpx
from sqlalchemy import inspect, select, update
from sqlalchemy.orm import Session

from app.bookmark_folder_classification import (
    check_bookmark_folder,
    folder_conflict_assessment,
    with_folder_evidence,
)
from app.category_service import (
    category_exemplars,
    category_rejected_examples,
    classification_categories,
    classification_rules,
)
from app.config import Settings
from app.database import Database
from app.model_settings_service import resolve_model_settings
from app.models import Memo, User
from app.resource_classification_policy import (
    apply_classification_health_gate,
    health_allows_ai_classification,
)
from app.resource_classification_quality import BookmarkFolderEvidence
from app.resource_processing import (
    CategoryDecision,
    ClassificationCategory,
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
        text_excerpt=memo.resource_text_excerpt,
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


def _category_assignment_state(memo: Memo) -> tuple[object, ...]:
    """比较主分类和附加分类，避免 extras 变化时漏加 version。"""

    return (
        memo.resource_category,
        memo.resource_category_label,
        memo.resource_category_source,
        tuple(memo.resource_categories or []),
        tuple(memo.resource_auto_tags or []),
    )


def apply_category(memo: Memo, decision: CategoryDecision) -> None:
    """将自动分类结果写入条目。"""

    if (
        memo.resource_category_source == "manual"
        or memo.resource_ai_confirmation is not None
    ):
        return
    if (
        decision.assessment is not None
        and decision.assessment["status"] == "uncertain"
        and memo.resource_category is not None
    ):
        # 单页刷新同样保留原分类，只保存新的未确定依据，不覆盖已有结果。
        memo.resource_ai_assessment = decision.assessment
        memo.resource_ai_confirmation_pending = True
        memo.resource_ai_auto_pending = False
        memo.resource_category_status = ResourceProcessStatus.READY
        return
    codes = list(dict.fromkeys([decision.category, *decision.extra_categories]))
    memo.resource_category = codes[0]
    memo.resource_category_label = decision.category_label
    memo.resource_categories = codes
    memo.resource_category_status = ResourceProcessStatus.READY
    memo.resource_category_confidence = decision.confidence
    memo.resource_category_source = decision.source
    memo.resource_auto_tags = list(decision.auto_tags)
    if decision.assessment is not None:
        memo.resource_ai_assessment = decision.assessment
        memo.resource_ai_confirmation_pending = (
            decision.assessment["status"] == "uncertain"
        )
    if decision.source in {"jev", "llm"}:
        # 只标记真实成功的模型分类，规则回退和失败仍可批量重试。
        if memo.resource_ai_classified_at is None:
            memo.resource_ai_classified_at = datetime.now(UTC)
        memo.resource_ai_auto_pending = False


def mark_processing(session: Session, memo: Memo) -> None:
    """将资料标记为后台处理中。"""

    now = datetime.now(UTC)
    memo.resource_metadata_status = ResourceProcessStatus.PROCESSING
    if (
        memo.resource_category_source != "manual"
        and memo.resource_ai_confirmation is None
    ):
        memo.resource_category_status = ResourceProcessStatus.PROCESSING
    memo.updated_at = now
    memo.version += 1
    session.commit()


def _check_folder_isolated(
    session: Session,
    user_id: str,
    memo: Memo,
    metadata: ResourceMetadata,
    categories: Sequence[ClassificationCategory],
    settings: Settings,
) -> tuple[CategoryDecision | None, BookmarkFolderEvidence | None]:
    """用独立会话读写文件夹缓存，不提交主会话里尚未写入的元数据。"""

    assert settings.jev_api_key is not None
    with Session(bind=session.get_bind()) as folder_session:
        try:
            return check_bookmark_folder(
                folder_session,
                user_id,
                memo.resource_import_folder,
                metadata,
                categories,
                settings.jev_api_key,
                settings.jev_base_url,
                settings.jev_model,
                settings.jev_min_confidence,
                tags=list(memo.resource_import_tags or []),
            )
        except (httpx.HTTPError, httpx.InvalidURL):
            # 单页刷新不因模型故障失败，照常走完整分类。
            return None, None


def enrich_resource(
    session: Session,
    user_id: str,
    memo_id: str,
    settings: Settings,
    metadata_fetcher: MetadataFetcher | None = None,
    classifier: ResourceClassifier | None = None,
    review_confirmed: bool = False,
) -> Memo:
    """抓取公开元数据、自动分类并更新基础巡检状态。"""

    memo = get_memo(session, user_id, memo_id)
    if memo.type != MemoType.RESOURCE or memo.source_url is None:
        raise MemoTypeError("只有网页资料可以执行元数据处理")
    mark_processing(session, memo)
    processing_version = memo.version
    processing_url = memo.source_url

    fetch_error: ResourceFetchError | UnsafeResourceUrlError | None = None
    try:
        if metadata_fetcher is None:
            metadata = fetch_resource_metadata(
                memo.source_url,
                timeout_seconds=settings.resource_fetch_timeout_seconds,
                max_bytes=settings.resource_fetch_max_bytes,
                include_text_excerpt=True,
            )
        else:
            metadata = metadata_fetcher(memo.source_url)
    except (ResourceFetchError, UnsafeResourceUrlError) as error:
        fetch_error = error
        metadata = fallback_metadata(memo)

    # 抓取期间发生确认或编辑时，直接返回最新版本，不再请求分类模型。
    session.rollback()
    memo = get_memo(session, user_id, memo_id)
    if memo.version != processing_version:
        return memo

    now = datetime.now(UTC)
    user = session.get(User, user_id)
    health_interval_hours = max(
        1,
        user.link_health_interval_hours
        if user is not None
        else settings.resource_health_interval_hours,
    )
    if fetch_error is None:
        memo.resource_page_title = metadata.page_title
        memo.resource_description = metadata.description
        memo.resource_text_excerpt = metadata.text_excerpt or ""
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
            hours=health_interval_hours,
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
        memo.link_next_check_at = now + timedelta(hours=health_interval_hours)

    # 先写入巡检结果；确认失效的网页只保留规则分类。
    apply_classification_health_gate(memo, review_confirmed)
    if (
        memo.resource_ai_classified_at is not None
        and memo.resource_category_source in {"jev", "llm"}
        and memo.resource_category is not None
    ):
        decision = CategoryDecision(
            category=memo.resource_category,
            category_label=memo.resource_category_label or memo.resource_category,
            confidence=memo.resource_category_confidence or 0.0,
            source=memo.resource_category_source,
            auto_tags=tuple(memo.resource_auto_tags),
            extra_categories=tuple(
                code for code in memo.resource_categories
                if code != memo.resource_category
            ),
        )
    elif classifier is None:
        # 判定期间禁止自动刷写：刷写会清空 ORM 变更历史，导致后面按版本提交时
        # 丢掉刚写入的元数据；同时避免网络等待期间持有写锁。
        with session.no_autoflush:
            settings = resolve_model_settings(session, user_id, settings)
            user_rules = classification_rules(session, user_id)
            category_options = classification_categories(session, user_id)
            allow_model = (
                health_allows_ai_classification(memo)
                and memo.resource_category_source != "manual"
                and memo.resource_ai_classified_at is None
                and memo.resource_ai_confirmation is None
                # 书签批次先抓取元数据，再由独立自动队列分类，避免导入被模型阻塞。
                and memo.resource_import_batch_id is None
            )
            folder_decision = None
            folder_evidence = None
            if (
                allow_model
                and settings.jev_api_key
                and settings.jev_model
                and (memo.resource_import_folder or memo.resource_import_tags)
            ):
                folder_decision, folder_evidence = _check_folder_isolated(
                    session, user_id, memo, metadata, category_options, settings
                )
            if folder_decision is not None:
                decision = folder_decision
            else:
                decision = classify_resource(
                    metadata,
                    llm_base_url=settings.llm_base_url if allow_model else None,
                    llm_api_key=settings.llm_api_key if allow_model else None,
                    llm_model=settings.llm_model if allow_model else "",
                    user_rules=user_rules,
                    category_options=category_options,
                    jev_api_key=settings.jev_api_key if allow_model else None,
                    jev_base_url=settings.jev_base_url,
                    jev_model=settings.jev_model,
                    jev_min_confidence=settings.jev_min_confidence,
                    deepseek_api_key=settings.deepseek_api_key if allow_model else None,
                    deepseek_base_url=settings.deepseek_base_url,
                    deepseek_model=settings.deepseek_model,
                    deepseek_timeout_seconds=settings.deepseek_timeout_seconds,
                    classification_min_confidence=(
                        settings.classification_min_confidence
                    ),
                    exemplars=(
                        category_exemplars(session, user_id, category_options)
                        if allow_model
                        else None
                    ),
                    rejected_examples=(
                        category_rejected_examples(session, user_id, category_options)
                        if allow_model
                        else None
                    ),
                )
                conflict = folder_conflict_assessment(decision, folder_evidence)
                decision = (
                    replace(decision, assessment=conflict)
                    if conflict is not None
                    else with_folder_evidence(decision, folder_evidence)
                )
        if allow_model and (
            settings.jev_api_key
            or (settings.deepseek_api_key and settings.deepseek_model)
        ):
            # 单次自动尝试后不无限重试低置信度；手动批量重试仍可执行。
            memo.resource_ai_auto_pending = False
    else:
        decision = classifier(metadata)
    apply_category(memo, decision)
    memo.updated_at = now
    memo.version += 1
    values = {
        attribute.key: attribute.value
        for attribute in inspect(memo).attrs
        if attribute.history.has_changes()
    }
    # 丢弃 ORM 待写内容，再按处理前版本提交；晚到的抓取和模型响应不能覆盖确认。
    session.rollback()
    session.execute(
        update(Memo)
        .where(
            Memo.id == memo_id,
            Memo.user_id == user_id,
            Memo.type == MemoType.RESOURCE,
            Memo.status != "trashed",
            Memo.source_url == processing_url,
            Memo.version == processing_version,
        )
        .values(**values)
    )
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
        previous_values = _category_assignment_state(memo)
        apply_category(memo, decision)
        if previous_values != _category_assignment_state(memo):
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

    settings = resolve_model_settings(session, user_id, settings)
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
        # 删除或修改用户规则时，确认失效的网页不调用模型。
        allow_model = (
            health_allows_ai_classification(memo)
            and memo.resource_ai_classified_at is None
        )
        decision = classify_resource(
            fallback_metadata(memo),
            llm_base_url=settings.llm_base_url if allow_model else None,
            llm_api_key=settings.llm_api_key if allow_model else None,
            llm_model=settings.llm_model if allow_model else "",
            user_rules=user_rules,
            category_options=categories,
            jev_api_key=settings.jev_api_key if allow_model else None,
            jev_base_url=settings.jev_base_url,
            jev_model=settings.jev_model,
            jev_min_confidence=settings.jev_min_confidence,
            deepseek_api_key=settings.deepseek_api_key if allow_model else None,
            deepseek_base_url=settings.deepseek_base_url,
            deepseek_model=settings.deepseek_model,
            deepseek_timeout_seconds=settings.deepseek_timeout_seconds,
            classification_min_confidence=settings.classification_min_confidence,
            exemplars=(
                category_exemplars(session, user_id, categories)
                if allow_model
                else None
            ),
            rejected_examples=(
                category_rejected_examples(session, user_id, categories)
                if allow_model
                else None
            ),
        )
        previous_values = _category_assignment_state(memo)
        apply_category(memo, decision)
        if previous_values != _category_assignment_state(memo):
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
