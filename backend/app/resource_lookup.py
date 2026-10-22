"""资料库已有网页网址查询。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Memo
from app.schemas import MemoStatus, MemoType


def existing_resource_urls(
    session: Session,
    user_id: str,
    canonical_urls: set[str] | None = None,
) -> dict[str, str]:
    """读取当前用户已有网页资料的规范网址与条目标识。

    规范化结果保存在 ``memo.canonical_url`` 上，并建有
    ``(user_id, canonical_url)`` 索引，因此这里不需要把全部资料读进内存
    再逐条比较。传入 ``canonical_urls`` 时只查这些网址，
    历史列表这类按页展示的场景就只做一次带索引的 IN 查询。
    """

    query = select(Memo.canonical_url, Memo.id).where(
        Memo.user_id == user_id,
        Memo.type == MemoType.RESOURCE,
        Memo.status != MemoStatus.TRASHED,
        Memo.canonical_url.is_not(None),
    )
    if canonical_urls is not None:
        if not canonical_urls:
            return {}
        query = query.where(Memo.canonical_url.in_(canonical_urls))

    result: dict[str, str] = {}
    for canonical_url, memo_id in session.execute(query).all():
        if canonical_url:
            result.setdefault(canonical_url, memo_id)
    return result
