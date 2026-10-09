"""网页分类的分页复核与批量人工确认，不调用模型或抓取网页。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import exists, func, or_, select, update
from sqlalchemy.orm import Session

from app.category_service import (
    SYSTEM_CATEGORY_CODES,
    category_code_exists,
    category_label,
    category_path,
    list_resource_category_options,
)
from app.models import Memo, ResourceCategoryTemplate
from app.resource_classification_quality import ClassificationConfirmation
from app.resource_classification_service import confirmation_filters
from app.schemas import (
    ResourceClassificationReviewCandidate,
    ResourceClassificationReviewItem,
    ResourceClassificationReviewList,
    ResourceClassificationReviewRequest,
    ResourceClassificationReviewResult,
    ResourceClassificationReviewResultItem,
)

ReviewReason = Literal[
    "low_confidence", "unknown_category", "invalid_response", "legacy"
]


def list_classification_reviews(
    session: Session,
    user_id: str,
    query: str = "",
    reason: ReviewReason | None = None,
    candidate_code: str | None = None,
    max_confidence: float | None = None,
    limit: int = 50,
    offset: int = 0,
) -> ResourceClassificationReviewList:
    """筛选完整队列后分页，不受网页列表或巡检列表的展示上限影响。"""

    filters = list(confirmation_filters(user_id))
    if query.strip():
        text = (
            query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        )
        pattern = f"%{text}%"
        filters.append(
            or_(
                Memo.title.ilike(pattern, escape="\\"),
                Memo.source_url.ilike(pattern, escape="\\"),
                Memo.resource_description.ilike(pattern, escape="\\"),
            )
        )
    if reason:
        filters.append(
            Memo.resource_ai_assessment["reason_code"].as_string().is_(None)
            if reason == "legacy"
            else Memo.resource_ai_assessment["reason_code"].as_string() == reason
        )
    if candidate_code:
        candidate = Memo.resource_ai_assessment["candidates"][0]["code"].as_string()
        filters.append(
            candidate.is_(None)
            if candidate_code == "_none"
            else candidate == candidate_code
        )
    if max_confidence is not None:
        filters.append(
            Memo.resource_ai_assessment["confidence"].as_float() <= max_confidence
        )
    total = session.scalar(select(func.count()).select_from(Memo).where(*filters)) or 0
    memos = session.scalars(
        select(Memo)
        .where(*filters)
        .order_by(
            Memo.updated_at.desc(),
            Memo.id.asc(),
        )
        .limit(limit)
        .offset(offset)
    ).all()
    options = {
        str(item["code"]): item
        for item in list_resource_category_options(session, user_id)
    }
    items: list[ResourceClassificationReviewItem] = []
    for memo in memos:
        candidates: list[ResourceClassificationReviewCandidate] = []
        if memo.resource_ai_assessment:
            for candidate in memo.resource_ai_assessment.get("candidates", []):
                option = options.get(candidate["code"])
                candidates.append(
                    ResourceClassificationReviewCandidate(
                        code=candidate["code"],
                        label=str(option["path"]) if option else candidate["label"],
                        probability=candidate["probability"],
                        available=bool(option and option["is_active"]),
                    )
                )
        current_codes = memo.resource_categories or (
            [memo.resource_category] if memo.resource_category else []
        )
        current_label = (
            "、".join(
                str(options[code]["path"])
                if code in options
                else (memo.resource_category_label or code)
                for code in current_codes
            )
            or None
        )
        items.append(
            ResourceClassificationReviewItem(
                id=memo.id,
                version=memo.version,
                title=memo.title,
                source_url=memo.source_url or "",
                current_category_label=current_label,
                assessment=memo.resource_ai_assessment,
                candidates=candidates,
            )
        )
    return ResourceClassificationReviewList(
        items=items, total_count=total, limit=limit, offset=offset
    )


def confirm_classification_reviews(
    session: Session,
    user_id: str,
    payload: ResourceClassificationReviewRequest,
) -> ResourceClassificationReviewResult:
    """按用户所见版本逐项确认，保护已修改、已处理及待巡检的网页。"""

    if payload.action == "assign" and not category_code_exists(
        session,
        user_id,
        payload.category_code or "",
        active_only=True,
    ):
        raise ValueError("指定的分类不存在或已停用")
    results: list[ResourceClassificationReviewResultItem] = []
    now = datetime.now(UTC)
    for selection in payload.items:
        memo_id = str(selection.memo_id)
        memo = session.scalar(
            select(Memo).where(Memo.id == memo_id, Memo.user_id == user_id)
        )
        reason: (
            Literal[
                "missing",
                "conflict",
                "not_pending",
                "no_candidate",
                "category_unavailable",
            ]
            | None
        ) = None
        code = memo.resource_category if memo else None
        if memo is None:
            reason = "missing"
        elif memo.version != selection.expected_version:
            reason = "conflict"
        elif (
            session.scalar(
                select(Memo.id).where(
                    Memo.id == memo_id, *confirmation_filters(user_id)
                )
            )
            is None
        ):
            reason = "not_pending"
        elif payload.action == "adopt":
            candidates = (memo.resource_ai_assessment or {}).get("candidates", [])
            code = selection.candidate_code or (
                candidates[0]["code"] if candidates else None
            )
            if not code or code not in {item["code"] for item in candidates}:
                reason = "no_candidate"
            elif not category_code_exists(session, user_id, code, active_only=True):
                reason = "category_unavailable"
        elif payload.action == "assign":
            code = payload.category_code
        if reason is None and memo is not None:
            confirmation: ClassificationConfirmation = {
                "action": payload.action,
                "confirmed_at": now.isoformat().replace("+00:00", "Z"),
                "category_code": code,
                "category_label": category_path(session, user_id, code)
                if code
                else None,
            }
            values: dict[str, object] = {
                "resource_ai_confirmation": confirmation,
                "resource_ai_confirmation_pending": False,
                "resource_ai_auto_pending": False,
                "updated_at": now,
                "version": Memo.version + 1,
            }
            guards = [
                Memo.id == memo_id,
                Memo.version == selection.expected_version,
                *confirmation_filters(user_id),
            ]
            if payload.action != "keep":
                assert code is not None
                values.update(
                    resource_category=code,
                    resource_category_label=category_label(session, user_id, code),
                    resource_categories=[code],
                    resource_category_source="manual",
                    resource_category_status="ready",
                    resource_category_confidence=1.0,
                )
                if code not in SYSTEM_CATEGORY_CODES:
                    # 分类在确认期间停用或删除时，不能保存过期的候选编码。
                    guards.append(
                        exists(
                            select(ResourceCategoryTemplate.id).where(
                                ResourceCategoryTemplate.user_id == user_id,
                                ResourceCategoryTemplate.code == code,
                                ResourceCategoryTemplate.is_active.is_(True),
                            )
                        )
                    )
            result = session.execute(update(Memo).where(*guards).values(**values))
            if result.rowcount != 1:
                reason = "conflict"
        results.append(
            ResourceClassificationReviewResultItem(
                memo_id=selection.memo_id,
                status="skipped" if reason else "updated",
                reason=reason,
            )
        )
    session.commit()
    updated = sum(item.status == "updated" for item in results)
    return ResourceClassificationReviewResult(
        updated_count=updated, skipped_count=len(results) - updated, results=results
    )
