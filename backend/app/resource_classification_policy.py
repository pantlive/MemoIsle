"""网页模型分类与人工巡检确认共用的准入规则。"""

from app.models import Memo

# 与巡检中心待处理筛选一致；忽略的条目同样暂缓模型调用。
REVIEW_HEALTH_STATUSES = frozenset(
    {
        "failed",
        "redirected",
        "changed",
        "auth_required",
        "temporary_failure",
    }
)


def health_allows_ai_classification(memo: Memo) -> bool:
    """网页可正常访问且没有未完成的人工确认，才允许调用分类模型。"""

    return memo.link_health_status == "healthy" and not memo.resource_ai_review_required


def apply_classification_health_gate(
    memo: Memo,
    review_confirmed: bool = False,
) -> None:
    """异常网页持续等待人工确认；后台自动恢复不清除确认标记。"""

    if memo.link_health_status in REVIEW_HEALTH_STATUSES | {"ignored"}:
        memo.resource_ai_review_required = True
    elif memo.link_health_status == "healthy" and review_confirmed:
        memo.resource_ai_review_required = False
        if (
            memo.resource_ai_classified_at is None
            and memo.resource_ai_confirmation is None
        ):
            # 用户确认保留且网页恢复正常后，主动排入自动分类。
            memo.resource_ai_auto_pending = True
