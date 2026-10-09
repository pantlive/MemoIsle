"""只处理显式选择的版本，批量操作逐项返回结果。"""

from datetime import UTC, datetime

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Memo
from app.schemas import MemoBatchRequest, MemoBatchResult, MemoBatchResultItem
from app.service import (
    MemoNotFoundError,
    MemoNotTrashedError,
    MemoVersionConflictError,
    _restore_status_for,
    get_memo,
    permanently_delete_memo,
)


def apply_memo_batch(
    session: Session,
    user_id: str,
    settings: Settings,
    payload: MemoBatchRequest,
) -> MemoBatchResult:
    """冲突或状态变化的条目跳过，其他选择仍可完成。"""

    results: list[MemoBatchResultItem] = []
    for item in payload.items:
        memo_id = str(item.memo_id)
        reason = None
        try:
            memo = get_memo(session, user_id, memo_id)
            if memo.version != item.expected_version:
                raise MemoVersionConflictError(memo)
            if payload.action == "trash":
                if memo.status == "trashed":
                    raise MemoNotTrashedError("该条目已在回收站")
                values = {
                    "status": "trashed",
                    "deleted_at": datetime.now(UTC),
                    "status_before_trash": memo.status.value,
                }
            elif payload.action == "restore":
                if memo.status != "trashed":
                    raise MemoNotTrashedError("该条目不在回收站")
                values = {
                    "status": _restore_status_for(memo),
                    "deleted_at": None,
                    "status_before_trash": None,
                    "resource_import_batch_id": None,
                }
            else:
                permanently_delete_memo(
                    session,
                    user_id,
                    memo_id,
                    item.expected_version,
                    settings.audio_directory,
                    settings.image_directory,
                )
            if payload.action != "permanent":
                result = session.execute(
                    update(Memo)
                    .where(
                        Memo.id == memo_id,
                        Memo.user_id == user_id,
                        Memo.version == item.expected_version,
                        Memo.status == memo.status,
                    )
                    .values(
                        **values,
                        updated_at=datetime.now(UTC),
                        version=Memo.version + 1,
                    )
                )
                if result.rowcount != 1:
                    raise MemoVersionConflictError(memo)
                session.commit()
        except MemoNotFoundError:
            session.rollback()
            reason = "missing"
        except MemoVersionConflictError:
            session.rollback()
            reason = "conflict"
        except MemoNotTrashedError:
            session.rollback()
            reason = "not_applicable"
        results.append(
            MemoBatchResultItem(
                memo_id=item.memo_id,
                status="skipped" if reason else "updated",
                reason=reason,
            )
        )
    updated = sum(item.status == "updated" for item in results)
    return MemoBatchResult(
        updated_count=updated, skipped_count=len(results) - updated, results=results
    )
