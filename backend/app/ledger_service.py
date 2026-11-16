"""记账业务逻辑：收支流水的增删改查与月度汇总，全部按账号隔离。"""

from __future__ import annotations

from datetime import date
from uuid import uuid4

from sqlalchemy import func, insert, literal, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.config import Settings
from app.database import commit_with_retry
from app.ledger_llm import (
    LedgerLlmUnavailableError,
    ledger_llm_enabled,
    parse_with_llm,
)
from app.ledger_parser import parse_ledger_sentence
from app.models import LedgerEntry, User, utc_now
from app.schemas import (
    LedgerCategoryTotal,
    LedgerCategoryUsage,
    LedgerCurrencyTotal,
    LedgerEntryCreate,
    LedgerEntryUpdate,
    LedgerKind,
    LedgerParsedBy,
    LedgerQuickCreate,
    LedgerSummary,
)

MAX_LEDGER_ENTRIES = 50_000
DEFAULT_LIST_LIMIT = 1_000
MAX_LIST_LIMIT = 5_000


class LedgerEntryNotFoundError(LookupError):
    """记录不存在或不属于当前账号。"""


class LedgerLimitError(RuntimeError):
    """记录条数超出上限。"""


class LedgerVersionConflictError(RuntimeError):
    """版本号已过期，附带服务端当前内容。"""

    def __init__(self, current: LedgerEntry) -> None:
        super().__init__("这一笔已在其他设备修改，请刷新后重试")
        self.current = current


def month_range(month: str) -> tuple[date, date]:
    """把 YYYY-MM 换成 [当月 1 日, 下月 1 日)。"""

    year_text, _, month_text = month.partition("-")
    year, month_number = int(year_text), int(month_text)
    if not 1 <= month_number <= 12:
        raise ValueError("月份无效")
    start = date(year, month_number, 1)
    end = (
        date(year + 1, 1, 1) if month_number == 12 else date(year, month_number + 1, 1)
    )
    return start, end


def list_entries(
    session: Session,
    user_id: str,
    *,
    month: str | None = None,
    kind: LedgerKind | None = None,
    category: str | None = None,
    limit: int = DEFAULT_LIST_LIMIT,
    offset: int = 0,
) -> list[LedgerEntry]:
    """按月份、方向、分类筛选，按发生日期和记录时间倒序。"""

    statement = select(LedgerEntry).where(LedgerEntry.user_id == user_id)
    if month is not None:
        start, end = month_range(month)
        statement = statement.where(
            LedgerEntry.occurred_on >= start, LedgerEntry.occurred_on < end
        )
    if kind is not None:
        statement = statement.where(LedgerEntry.kind == kind)
    if category is not None and category.strip():
        statement = statement.where(LedgerEntry.category == category.strip())
    statement = (
        statement.order_by(
            LedgerEntry.occurred_on.desc(),
            LedgerEntry.created_at.desc(),
            LedgerEntry.id.desc(),
        )
        .limit(max(1, min(limit, MAX_LIST_LIMIT)))
        .offset(max(0, offset))
    )
    return list(session.scalars(statement))


def _get_entry(session: Session, user_id: str, entry_id: str) -> LedgerEntry:
    entry = session.scalar(
        select(LedgerEntry).where(
            LedgerEntry.id == entry_id, LedgerEntry.user_id == user_id
        )
    )
    if entry is None:
        raise LedgerEntryNotFoundError
    return entry


def create_entry(
    session: Session, user_id: str, payload: LedgerEntryCreate
) -> LedgerEntry:
    """新记一笔；超过条数上限时拒绝。"""

    # PostgreSQL 按账号串行校验配额；SQLite 在单条 INSERT 中原子检查。
    session.execute(select(User.id).where(User.id == user_id).with_for_update())
    count = (
        select(func.count())
        .select_from(LedgerEntry)
        .where(LedgerEntry.user_id == user_id)
        .scalar_subquery()
    )
    entry_id = str(uuid4())
    now = utc_now()
    fields = dict(
        id=entry_id,
        user_id=user_id,
        version=1,
        created_at=now,
        updated_at=now,
        **payload.model_dump(),
    )
    result = session.execute(
        insert(LedgerEntry).from_select(
            list(fields),
            select(*(literal(value) for value in fields.values())).where(
                count < MAX_LEDGER_ENTRIES
            ),
        )
    )
    if result.rowcount == 0:
        session.rollback()
        raise LedgerLimitError
    commit_with_retry(session)
    return _get_entry(session, user_id, entry_id)


def create_entry_from_sentence(
    session: Session,
    user_id: str,
    payload: LedgerQuickCreate,
    settings: Settings,
) -> tuple[LedgerEntry, LedgerParsedBy]:
    """一句话记一笔，识别后直接保存，返回新记录和识别方式。

    配置了本地模型时先让模型识别，失败、超时或结果不合格时退回规则；
    规则也识别不出时抛 LedgerParseError，不写入。
    """

    known = [(item.kind, item.category) for item in list_categories(session, user_id)]
    parsed: LedgerEntryCreate | None = None
    parsed_by: LedgerParsedBy = "rule"
    if ledger_llm_enabled(settings):
        # 先结束只读事务再等模型，等待期间不占着数据库连接；写入在模型返回后才加锁。
        session.rollback()
        try:
            parsed = parse_with_llm(payload.text, payload.today, known, settings)
            parsed_by = "llm"
        except LedgerLlmUnavailableError:
            parsed = None
    if parsed is None:
        parsed = parse_ledger_sentence(payload.text, payload.today, known)
    return create_entry(session, user_id, parsed), parsed_by


def update_entry(
    session: Session,
    user_id: str,
    entry_id: str,
    payload: LedgerEntryUpdate,
) -> LedgerEntry:
    """按版本号整条替换。"""

    entry = _get_entry(session, user_id, entry_id)
    if entry.version != payload.expected_version:
        raise LedgerVersionConflictError(entry)
    for field, value in payload.model_dump(exclude={"expected_version"}).items():
        setattr(entry, field, value)
    entry.version += 1
    try:
        commit_with_retry(session)
    except StaleDataError as error:
        # 写入期间有其他设备抢先保存，回滚后返回最新版本。
        session.rollback()
        raise LedgerVersionConflictError(
            _get_entry(session, user_id, entry_id)
        ) from error
    session.refresh(entry)
    return entry


def delete_entry(
    session: Session,
    user_id: str,
    entry_id: str,
    expected_version: int,
) -> None:
    """按版本号永久删除。"""

    entry = _get_entry(session, user_id, entry_id)
    if entry.version != expected_version:
        raise LedgerVersionConflictError(entry)
    session.delete(entry)
    try:
        commit_with_retry(session)
    except StaleDataError as error:
        session.rollback()
        raise LedgerVersionConflictError(
            _get_entry(session, user_id, entry_id)
        ) from error


def summarize_month(session: Session, user_id: str, month: str) -> LedgerSummary:
    """按币种分别统计收入、支出、结余，再按币种、方向和分类算小计。"""

    start, end = month_range(month)
    in_month = (
        LedgerEntry.user_id == user_id,
        LedgerEntry.occurred_on >= start,
        LedgerEntry.occurred_on < end,
    )
    rows = session.execute(
        select(
            LedgerEntry.currency,
            LedgerEntry.kind,
            LedgerEntry.category,
            func.sum(LedgerEntry.amount_cents),
            func.count(),
        )
        .where(*in_month)
        .group_by(LedgerEntry.currency, LedgerEntry.kind, LedgerEntry.category)
    ).all()

    totals: dict[str, dict[str, int]] = {}
    categories: list[LedgerCategoryTotal] = []
    for currency, kind, category, amount, count in rows:
        amount = int(amount or 0)
        bucket = totals.setdefault(currency, {"income": 0, "expense": 0, "count": 0})
        bucket[kind] += amount
        bucket["count"] += count
        categories.append(
            LedgerCategoryTotal(
                currency=currency,
                kind=kind,
                category=category,
                amount_cents=amount,
                entry_count=count,
            )
        )
    # 支出在前，同一方向按金额从大到小。
    categories.sort(
        key=lambda item: (
            item.currency,
            item.kind != "expense",
            -item.amount_cents,
            item.category,
        )
    )
    return LedgerSummary(
        month=month,
        totals=[
            LedgerCurrencyTotal(
                currency=currency,
                income_cents=bucket["income"],
                expense_cents=bucket["expense"],
                balance_cents=bucket["income"] - bucket["expense"],
                entry_count=bucket["count"],
            )
            for currency, bucket in sorted(totals.items())
        ],
        categories=categories,
    )


def list_categories(session: Session, user_id: str) -> list[LedgerCategoryUsage]:
    """列出用过的分类，常用的排在前面。"""

    count = func.count().label("entry_count")
    rows = session.execute(
        select(LedgerEntry.kind, LedgerEntry.category, count)
        .where(LedgerEntry.user_id == user_id)
        .group_by(LedgerEntry.kind, LedgerEntry.category)
        .order_by(count.desc(), LedgerEntry.category)
    ).all()
    return [
        LedgerCategoryUsage(kind=kind, category=category, entry_count=entry_count)
        for kind, category, entry_count in rows
    ]
