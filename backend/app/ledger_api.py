"""记账接口：收支流水与月度汇总，明文保存，按账号隔离。"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.dependencies import get_current_user_id, get_session
from app.ledger_parser import LedgerParseError
from app.ledger_service import (
    DEFAULT_LIST_LIMIT,
    MAX_LIST_LIMIT,
    LedgerEntryNotFoundError,
    LedgerLimitError,
    LedgerVersionConflictError,
    create_entry,
    create_entry_from_sentence,
    delete_entry,
    list_categories,
    list_entries,
    summarize_month,
    update_entry,
)
from app.schemas import (
    LEDGER_CATEGORY_MAX_LENGTH,
    LEDGER_MONTH_PATTERN,
    LedgerCategoryUsage,
    LedgerEntryCreate,
    LedgerEntryRead,
    LedgerEntryUpdate,
    LedgerKind,
    LedgerQuickCreate,
    LedgerSummary,
)

router = APIRouter(prefix="/ledger", tags=["ledger"])
SessionDependency = Annotated[Session, Depends(get_session)]
UserDependency = Annotated[str, Depends(get_current_user_id)]
MonthQuery = Annotated[str, Query(pattern=LEDGER_MONTH_PATTERN)]


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="这一笔记录不存在或已删除")


def _conflict(error: LedgerVersionConflictError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "message": str(error),
            "code": "version_conflict",
            "current": LedgerEntryRead.model_validate(error.current).model_dump(
                mode="json"
            ),
        },
    )


@router.get("/entries", response_model=list[LedgerEntryRead])
def list_entries_route(
    session: SessionDependency,
    user_id: UserDependency,
    month: Annotated[str | None, Query(pattern=LEDGER_MONTH_PATTERN)] = None,
    kind: LedgerKind | None = None,
    category: Annotated[
        str | None, Query(max_length=LEDGER_CATEGORY_MAX_LENGTH)
    ] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIST_LIMIT)] = DEFAULT_LIST_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[LedgerEntryRead]:
    """按月份、方向、分类筛选流水，最新的在前。"""

    entries = list_entries(
        session,
        user_id,
        month=month,
        kind=kind,
        category=category,
        limit=limit,
        offset=offset,
    )
    return [LedgerEntryRead.model_validate(entry) for entry in entries]


@router.post(
    "/entries", response_model=LedgerEntryRead, status_code=status.HTTP_201_CREATED
)
def create_entry_route(
    payload: LedgerEntryCreate,
    session: SessionDependency,
    user_id: UserDependency,
) -> LedgerEntryRead:
    """新记一笔。"""

    try:
        entry = create_entry(session, user_id, payload)
    except LedgerLimitError as error:
        raise HTTPException(status_code=400, detail="记账记录数量已达上限") from error
    return LedgerEntryRead.model_validate(entry)


@router.post(
    "/quick", response_model=LedgerEntryRead, status_code=status.HTTP_201_CREATED
)
def quick_create_entry_route(
    payload: LedgerQuickCreate,
    session: SessionDependency,
    user_id: UserDependency,
) -> LedgerEntryRead:
    """一句话记一笔，如“今天早饭花了10元”；识别不出时返回 422 和中文提示。"""

    try:
        entry = create_entry_from_sentence(session, user_id, payload)
    except LedgerParseError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except LedgerLimitError as error:
        raise HTTPException(status_code=400, detail="记账记录数量已达上限") from error
    return LedgerEntryRead.model_validate(entry)


@router.put("/entries/{entry_id}", response_model=LedgerEntryRead)
def update_entry_route(
    entry_id: UUID,
    payload: LedgerEntryUpdate,
    session: SessionDependency,
    user_id: UserDependency,
) -> LedgerEntryRead:
    """带版本号修改一笔。"""

    try:
        entry = update_entry(session, user_id, str(entry_id), payload)
    except LedgerEntryNotFoundError as error:
        raise _not_found() from error
    except LedgerVersionConflictError as error:
        raise _conflict(error) from error
    return LedgerEntryRead.model_validate(entry)


@router.delete("/entries/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_entry_route(
    entry_id: UUID,
    session: SessionDependency,
    user_id: UserDependency,
    expected_version: Annotated[int, Query(ge=1)],
) -> Response:
    """带版本号永久删除一笔。"""

    try:
        delete_entry(session, user_id, str(entry_id), expected_version)
    except LedgerEntryNotFoundError as error:
        raise _not_found() from error
    except LedgerVersionConflictError as error:
        raise _conflict(error) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/summary", response_model=LedgerSummary)
def read_summary_route(
    session: SessionDependency,
    user_id: UserDependency,
    month: MonthQuery,
) -> LedgerSummary:
    """读取某月按币种分开的收支汇总和分类小计。"""

    return summarize_month(session, user_id, month)


@router.get("/categories", response_model=list[LedgerCategoryUsage])
def list_categories_route(
    session: SessionDependency,
    user_id: UserDependency,
) -> list[LedgerCategoryUsage]:
    """列出用过的分类。"""

    return list_categories(session, user_id)


__all__ = ["router"]
