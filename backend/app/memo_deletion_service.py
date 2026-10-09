"""持久化删除通知及统一游标分页，保护离线同步不漏项。"""

from datetime import UTC, datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.models import Memo, MemoDeletion
from app.schemas import MemoDeletionRead, MemoRead, SyncResponse


def record_memo_deletion(session: Session, memo: Memo) -> None:
    """与条目删除同事务保存通知，绝不保存原收藏内容。"""

    session.add(
        MemoDeletion(
            memo_id=memo.id,
            user_id=memo.user_id,
            client_id=memo.client_id,
            deleted_at=datetime.now(UTC),
        )
    )


def utc_time(value: datetime) -> datetime:
    """合并 SQLite 时间与带时区时间时使用相同的 UTC 语义。"""

    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def sync_change_page(
    session: Session,
    user_id: str,
    cursor: datetime | None,
    cursor_id: str | None,
    limit: int,
) -> SyncResponse:
    """新增、修改和删除共用时间与标识游标，删除占用同一分页额度。"""

    requested_at = datetime.now(UTC)
    memos = select(Memo).where(Memo.user_id == user_id, Memo.updated_at <= requested_at)
    deletions = select(MemoDeletion).where(
        MemoDeletion.user_id == user_id,
        MemoDeletion.deleted_at <= requested_at,
    )
    if cursor is not None:
        if cursor_id:
            memos = memos.where(
                or_(
                    Memo.updated_at > cursor,
                    and_(
                        Memo.updated_at == cursor,
                        Memo.id > cursor_id,
                    ),
                )
            )
            deletions = deletions.where(
                or_(
                    MemoDeletion.deleted_at > cursor,
                    and_(
                        MemoDeletion.deleted_at == cursor,
                        MemoDeletion.memo_id > cursor_id,
                    ),
                )
            )
        else:
            memos = memos.where(Memo.updated_at > cursor)
            deletions = deletions.where(MemoDeletion.deleted_at > cursor)
    memo_rows = session.scalars(
        memos.order_by(Memo.updated_at, Memo.id).limit(limit + 1)
    ).all()
    deletion_rows = session.scalars(
        deletions.order_by(
            MemoDeletion.deleted_at,
            MemoDeletion.memo_id,
        ).limit(limit + 1)
    ).all()
    changes: list[tuple[datetime, str, Memo | MemoDeletion]] = [
        (utc_time(row.updated_at), row.id, row) for row in memo_rows
    ] + [(utc_time(row.deleted_at), row.memo_id, row) for row in deletion_rows]
    changes.sort(key=lambda item: (item[0], item[1]))
    page = changes[:limit]
    return SyncResponse(
        items=[
            MemoRead.model_validate(row) for _, _, row in page if isinstance(row, Memo)
        ],
        deleted_items=[
            MemoDeletionRead.model_validate(row)
            for _, _, row in page
            if isinstance(row, MemoDeletion)
        ],
        cursor=page[-1][0]
        if page
        else max(requested_at, utc_time(cursor))
        if cursor
        else requested_at,
        cursor_id=page[-1][1]
        if page
        else cursor_id
        if cursor and utc_time(cursor) > requested_at
        else None,
        has_more=len(changes) > limit,
    )
