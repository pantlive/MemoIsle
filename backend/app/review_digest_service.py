"""每周摘要与随机漫游（P1-10）。

摘要只读现有字段推算，不新增事件表：
- 新增收藏按 ``created_at``；
- 复习过的单词按 ``last_review_at``（同一个词一周内复习多次只算一次）；
- 打开过的网页资料按 ``resource_last_opened_at``。

随机漫游从资料库里随机挑一条未删除的条目，帮助重新遇见很久没看的内容；
客户端可以传入最近看过的 ID 避免连续抽到同一条。
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Memo
from app.schemas import MemoStatus, MemoType

WEEKLY_DAYS = 7
TOP_TAG_LIMIT = 5
HIGHLIGHT_LIMIT = 5
# 随机漫游最多排除的最近条目数，避免超长 IN 列表。
MAX_RANDOM_EXCLUDE = 50


def _visible(user_id: str):
    return (Memo.user_id == user_id, Memo.status != MemoStatus.TRASHED)


def weekly_summary(
    session: Session,
    user_id: str,
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    """统计最近七天的收藏、复习与阅读情况。"""

    current = now or datetime.now(UTC)
    since = current - timedelta(days=WEEKLY_DAYS)
    created_rows = session.execute(
        select(Memo.type, func.count(Memo.id))
        .where(*_visible(user_id), Memo.created_at >= since)
        .group_by(Memo.type)
    ).all()
    created_by_type = {memo_type.value: 0 for memo_type in MemoType}
    for memo_type, count in created_rows:
        created_by_type[MemoType(memo_type).value] = int(count)

    reviewed_words = session.scalar(
        select(func.count(Memo.id)).where(
            *_visible(user_id),
            Memo.type == MemoType.WORD,
            Memo.last_review_at >= since,
        )
    )
    opened_resources = session.scalar(
        select(func.count(Memo.id)).where(
            *_visible(user_id),
            Memo.type == MemoType.RESOURCE,
            Memo.resource_last_opened_at >= since,
        )
    )
    inbox_remaining = session.scalar(
        select(func.count(Memo.id)).where(
            Memo.user_id == user_id,
            Memo.status == MemoStatus.INBOX,
        )
    )

    recent = list(
        session.scalars(
            select(Memo)
            .where(*_visible(user_id), Memo.created_at >= since)
            .order_by(Memo.created_at.desc(), Memo.id.desc())
        )
    )
    tag_counter: Counter[str] = Counter()
    for memo in recent:
        # 手动标签优先；同一条目里的重复标签只计一次。
        tag_counter.update({tag for tag in (memo.tags or []) if tag})
    return {
        "since": since,
        "until": current,
        "created_total": sum(created_by_type.values()),
        "created_by_type": created_by_type,
        "reviewed_words": int(reviewed_words or 0),
        "opened_resources": int(opened_resources or 0),
        "inbox_remaining": int(inbox_remaining or 0),
        "top_tags": [
            {"tag": tag, "count": count}
            for tag, count in tag_counter.most_common(TOP_TAG_LIMIT)
        ],
        "highlights": recent[:HIGHLIGHT_LIMIT],
    }


def random_memo(
    session: Session,
    user_id: str,
    *,
    memo_type: MemoType | None = None,
    exclude_ids: list[str] | None = None,
) -> Memo | None:
    """随机挑一条未删除的条目；排除后没有可选条目时忽略排除再抽一次。"""

    base = select(Memo).where(*_visible(user_id))
    if memo_type is not None:
        base = base.where(Memo.type == memo_type)
    excluded = [value for value in (exclude_ids or []) if value][:MAX_RANDOM_EXCLUDE]
    if excluded:
        picked = session.scalar(
            base.where(Memo.id.not_in(excluded)).order_by(func.random()).limit(1)
        )
        if picked is not None:
            return picked
    return session.scalar(base.order_by(func.random()).limit(1))
