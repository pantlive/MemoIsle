"""Chrome 书签导入业务。"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import Database
from app.models import BookmarkImportBatch, BookmarkImportItem, Memo
from app.resource_service import run_pending_resource_enrichments
from app.schemas import (
    BookmarkImportBatchRead,
    BookmarkImportItemRead,
    BookmarkImportPreview,
    BookmarkImportRequest,
    BookmarkPreviewItem,
    MemoCreate,
    MemoStatus,
    MemoType,
    ResourceProcessStatus,
)
from app.service import create_memo
from app.url_normalization import canonicalize_resource_url


class BookmarkBatchNotFoundError(LookupError):
    """当前用户无法访问指定导入批次。"""


class BookmarkBatchStateError(ValueError):
    """导入批次当前状态不允许执行请求操作。"""


canonicalize_bookmark_url = canonicalize_resource_url


def _existing_resource_urls(session: Session, user_id: str) -> dict[str, str]:
    """读取当前用户已有网页资料的规范网址与条目标识。"""

    memos = session.scalars(
        select(Memo).where(
            Memo.user_id == user_id,
            Memo.type == MemoType.RESOURCE,
            Memo.status != MemoStatus.TRASHED,
            Memo.source_url.is_not(None),
        )
    ).all()
    result: dict[str, str] = {}
    for memo in memos:
        try:
            normalized_url = canonicalize_bookmark_url(memo.source_url or "")
        except ValueError:
            # 历史异常链接不应阻断整个书签预览。
            continue
        result.setdefault(normalized_url, memo.id)
    return result


def preview_bookmarks(
    session: Session,
    user_id: str,
    payload: BookmarkImportRequest,
) -> BookmarkImportPreview:
    """校验结构化书签，并同时识别资料库与文件内重复项。"""

    existing_urls = _existing_resource_urls(session, user_id)
    seen_urls: dict[str, str | None] = dict(existing_urls)
    preview_items: list[BookmarkPreviewItem] = []
    valid_count = 0
    duplicate_count = 0
    invalid_count = 0

    for item in payload.items:
        try:
            normalized_url = canonicalize_bookmark_url(item.url)
        except ValueError as error:
            invalid_count += 1
            preview_items.append(
                BookmarkPreviewItem(
                    client_item_id=item.client_item_id,
                    title=item.title,
                    url=item.url,
                    normalized_url=None,
                    folder_path=item.folder_path,
                    status="invalid",
                    error_code=str(error),
                )
            )
            continue

        if normalized_url in seen_urls:
            duplicate_count += 1
            existing_memo_id = seen_urls[normalized_url]
            preview_items.append(
                BookmarkPreviewItem(
                    client_item_id=item.client_item_id,
                    title=item.title,
                    url=item.url,
                    normalized_url=normalized_url,
                    folder_path=item.folder_path,
                    status="duplicate",
                    existing_memo_id=(
                        UUID(existing_memo_id) if existing_memo_id is not None else None
                    ),
                    error_code=(
                        "already_saved"
                        if existing_memo_id is not None
                        else "duplicate_in_file"
                    ),
                )
            )
            continue

        seen_urls[normalized_url] = None
        valid_count += 1
        preview_items.append(
            BookmarkPreviewItem(
                client_item_id=item.client_item_id,
                title=item.title,
                url=item.url,
                normalized_url=normalized_url,
                folder_path=item.folder_path,
                status="valid",
            )
        )

    return BookmarkImportPreview(
        total_count=len(payload.items),
        valid_count=valid_count,
        duplicate_count=duplicate_count,
        invalid_count=invalid_count,
        items=preview_items,
    )


def create_bookmark_batch(
    session: Session,
    user_id: str,
    payload: BookmarkImportRequest,
) -> BookmarkImportBatch:
    """确认预览结果并持久化一个可追踪的导入批次。"""

    preview = preview_bookmarks(session, user_id, payload)
    now = datetime.now(UTC)
    batch = BookmarkImportBatch(
        id=str(uuid4()),
        user_id=user_id,
        status="pending",
        total_count=preview.total_count,
        valid_count=preview.valid_count,
        duplicate_count=preview.duplicate_count,
        imported_count=0,
        failed_count=0,
        created_at=now,
        updated_at=now,
    )
    session.add(batch)
    session.flush()

    for source, item in zip(payload.items, preview.items, strict=True):
        # 无效项也进入批次，便于前端完整解释导入结果。
        persisted_status = "pending" if item.status == "valid" else item.status
        session.add(
            BookmarkImportItem(
                id=str(uuid4()),
                batch_id=batch.id,
                client_item_id=source.client_item_id,
                title=source.title,
                source_url=source.url,
                normalized_url=item.normalized_url or source.url.strip(),
                folder_path=source.folder_path,
                status=persisted_status,
                existing_memo_id=(
                    str(item.existing_memo_id)
                    if item.existing_memo_id is not None
                    else None
                ),
                error_code=item.error_code,
                created_at=now,
                updated_at=now,
            )
        )
    session.commit()
    session.refresh(batch)
    return batch


def _load_batch(
    session: Session,
    user_id: str,
    batch_id: str,
) -> BookmarkImportBatch:
    """读取属于当前用户的书签导入批次。"""

    batch = session.scalar(
        select(BookmarkImportBatch).where(
            BookmarkImportBatch.id == batch_id,
            BookmarkImportBatch.user_id == user_id,
        )
    )
    if batch is None:
        raise BookmarkBatchNotFoundError
    return batch


def _load_batch_items(session: Session, batch_id: str) -> list[BookmarkImportItem]:
    """按创建顺序读取一个批次的项目。"""

    return list(
        session.scalars(
            select(BookmarkImportItem)
            .where(BookmarkImportItem.batch_id == batch_id)
            .order_by(
                BookmarkImportItem.created_at.asc(),
                BookmarkImportItem.id.asc(),
            )
        ).all()
    )


def _refresh_batch_progress(
    session: Session,
    batch: BookmarkImportBatch,
) -> None:
    """从项目状态重新计算批次进度，避免重试造成计数漂移。"""

    items = _load_batch_items(session, batch.id)
    batch.imported_count = sum(item.status == "imported" for item in items)
    batch.duplicate_count = sum(item.status == "duplicate" for item in items)
    batch.failed_count = sum(item.status == "failed" for item in items)
    pending_count = sum(item.status in {"pending", "processing"} for item in items)
    if batch.undone_at is not None:
        batch.status = "undone"
    elif pending_count:
        batch.status = "processing"
    elif batch.failed_count:
        batch.status = "partial_failed"
    else:
        batch.status = "completed"
    batch.updated_at = datetime.now(UTC)


def _increment_batch_counter(
    session: Session,
    batch_id: str,
    field_name: str,
) -> None:
    """在单条处理提交时同步批次计数，供 Web 实时显示进度。"""

    batch = session.get(BookmarkImportBatch, batch_id)
    if batch is None:
        return
    current_value = int(getattr(batch, field_name))
    setattr(batch, field_name, current_value + 1)
    batch.updated_at = datetime.now(UTC)


def process_bookmark_batch(
    session: Session,
    user_id: str,
    batch_id: str,
    settings: Settings | None = None,
) -> BookmarkImportBatch:
    """导入批次中的待处理或失败书签，并为其启动自动分类。"""

    batch = _load_batch(session, user_id, batch_id)
    if batch.undone_at is not None:
        raise BookmarkBatchStateError("已撤销的导入不能继续处理")
    _refresh_batch_progress(session, batch)
    session.commit()

    known_urls = _existing_resource_urls(session, user_id)
    items = _load_batch_items(session, batch.id)
    for item in items:
        if (
            item.status == "duplicate"
            and item.existing_memo_id is not None
            and settings is not None
            and settings.resource_enrichment_enabled
        ):
            # 已有但尚未分类的资料也借本次导入重新进入处理队列。
            existing_memo = session.get(Memo, item.existing_memo_id)
            if (
                existing_memo is not None
                and existing_memo.resource_category_status != "ready"
            ):
                # 重新排队即可，不能让已有资料的联网抓取阻塞整批导入。
                existing_memo.resource_metadata_status = ResourceProcessStatus.PENDING
                if existing_memo.resource_category_source != "manual":
                    existing_memo.resource_category_status = (
                        ResourceProcessStatus.PENDING
                    )
                existing_memo.updated_at = datetime.now(UTC)
                existing_memo.version += 1
                session.commit()
            continue
        if item.status not in {"pending", "failed"}:
            continue
        item.status = "processing"
        item.error_code = None
        item.updated_at = datetime.now(UTC)
        session.commit()
        try:
            client_id = uuid5(UUID(batch.id), item.client_item_id)
            owned_memo = session.scalar(
                select(Memo).where(
                    Memo.user_id == user_id,
                    Memo.client_id == str(client_id),
                )
            )
            if owned_memo is not None:
                memo = owned_memo
            elif item.normalized_url in known_urls:
                item.status = "duplicate"
                item.existing_memo_id = known_urls[item.normalized_url]
                item.error_code = "already_saved"
                item.updated_at = datetime.now(UTC)
                _increment_batch_counter(
                    session,
                    batch.id,
                    "duplicate_count",
                )
                session.commit()
                continue
            else:
                cleaned_title = item.title.strip()[:200]
                memo = create_memo(
                    session,
                    user_id,
                    MemoCreate(
                        client_id=client_id,
                        type=MemoType.RESOURCE,
                        title=cleaned_title or None,
                        body=cleaned_title or "从 Chrome 书签导入",
                        source_url=item.normalized_url,
                        source_title=cleaned_title or None,
                        tags=[],
                    ),
                )

                if memo.client_id != str(client_id):
                    # 并发导入期间另一请求先写入相同网址，不能接管对方资料。
                    item.status = "duplicate"
                    item.existing_memo_id = memo.id
                    item.error_code = "already_saved"
                    item.updated_at = datetime.now(UTC)
                    known_urls[item.normalized_url] = memo.id
                    _increment_batch_counter(
                        session,
                        batch.id,
                        "duplicate_count",
                    )
                    session.commit()
                    continue

            memo.resource_import_folder = item.folder_path
            memo.resource_import_batch_id = batch.id
            memo.updated_at = datetime.now(UTC)
            item.status = "imported"
            item.memo_id = memo.id
            item.existing_memo_id = None
            item.error_code = None
            item.updated_at = datetime.now(UTC)
            known_urls[item.normalized_url] = memo.id
            _increment_batch_counter(
                session,
                batch.id,
                "imported_count",
            )
            session.commit()
        except Exception:  # noqa: BLE001
            # 单条异常只标记该项目，不能中断其余数千条书签。
            session.rollback()
            failed_item = session.get(BookmarkImportItem, item.id)
            if failed_item is not None:
                failed_item.status = "failed"
                failed_item.error_code = "import_failed"
                failed_item.updated_at = datetime.now(UTC)
                _increment_batch_counter(
                    session,
                    batch.id,
                    "failed_count",
                )
                session.commit()

    batch = _load_batch(session, user_id, batch_id)
    _refresh_batch_progress(session, batch)
    session.commit()
    session.refresh(batch)
    return batch


def process_bookmark_batch_in_background(
    database_url: str,
    user_id: str,
    batch_id: str,
    settings: Settings,
) -> None:
    """使用独立数据库会话执行书签批量导入。"""

    database = Database(database_url)
    imported = False
    try:
        with database.session_factory() as session:
            try:
                process_bookmark_batch(session, user_id, batch_id, settings)
                imported = True
            except (BookmarkBatchNotFoundError, BookmarkBatchStateError):
                return
    finally:
        database.dispose()
    if imported and settings.resource_enrichment_enabled:
        # 批次先完成并可搜索，再由独立队列继续抓取元数据和自动分类。
        run_pending_resource_enrichments(database_url, settings)


def run_pending_bookmark_imports(
    database_url: str,
    settings: Settings,
    limit: int = 10,
) -> int:
    """恢复服务重启前尚未完成的书签导入批次。"""

    database = Database(database_url)
    processed_count = 0
    try:
        with database.session_factory() as session:
            batches = list(
                session.scalars(
                    select(BookmarkImportBatch)
                    .where(
                        BookmarkImportBatch.status.in_({"pending", "processing"}),
                        BookmarkImportBatch.undone_at.is_(None),
                    )
                    .order_by(BookmarkImportBatch.created_at.asc())
                    .limit(limit)
                ).all()
            )
            batch_keys = [(batch.user_id, batch.id) for batch in batches]

            for user_id, batch_id in batch_keys:
                # 上一进程退出时遗留的 processing 项需要恢复为可幂等重试状态。
                for item in _load_batch_items(session, batch_id):
                    if item.status == "processing":
                        item.status = "pending"
                        item.error_code = None
                        item.updated_at = datetime.now(UTC)
                session.commit()
                try:
                    process_bookmark_batch(
                        session,
                        user_id,
                        batch_id,
                        settings,
                    )
                except (BookmarkBatchNotFoundError, BookmarkBatchStateError):
                    session.rollback()
                    continue
                except Exception:  # noqa: BLE001
                    # 单个异常批次不能阻止其他用户的待处理批次恢复。
                    session.rollback()
                    continue
                processed_count += 1
    finally:
        database.dispose()
    return processed_count


def read_bookmark_batch(
    session: Session,
    user_id: str,
    batch_id: str,
) -> BookmarkImportBatchRead:
    """返回批次及逐项目进度。"""

    batch = _load_batch(session, user_id, batch_id)
    items = _load_batch_items(session, batch.id)
    invalid_count = sum(item.status == "invalid" for item in items)
    return BookmarkImportBatchRead(
        id=UUID(batch.id),
        status=batch.status,
        total_count=batch.total_count,
        valid_count=batch.valid_count,
        duplicate_count=batch.duplicate_count,
        invalid_count=invalid_count,
        imported_count=batch.imported_count,
        failed_count=batch.failed_count,
        created_at=batch.created_at,
        updated_at=batch.updated_at,
        undone_at=batch.undone_at,
        items=[BookmarkImportItemRead.model_validate(item) for item in items],
    )


def retry_bookmark_batch(
    session: Session,
    user_id: str,
    batch_id: str,
    settings: Settings | None = None,
) -> BookmarkImportBatch:
    """仅重新处理一个批次中失败的项目。"""

    batch = _load_batch(session, user_id, batch_id)
    if batch.undone_at is not None:
        raise BookmarkBatchStateError("已撤销的导入不能重试")
    failed_items = [
        item for item in _load_batch_items(session, batch.id) if item.status == "failed"
    ]
    for item in failed_items:
        item.status = "pending"
        item.error_code = None
        item.updated_at = datetime.now(UTC)
    if failed_items:
        batch.status = "pending"
        batch.updated_at = datetime.now(UTC)
        session.commit()
    return process_bookmark_batch(session, user_id, batch_id, settings)


def undo_bookmark_batch(
    session: Session,
    user_id: str,
    batch_id: str,
) -> BookmarkImportBatch:
    """将本批导入且之后未被编辑的资料移入回收站。"""

    batch = _load_batch(session, user_id, batch_id)
    if batch.undone_at is not None:
        return batch
    now = datetime.now(UTC)
    imported_items = [
        item
        for item in _load_batch_items(session, batch.id)
        if item.status == "imported"
    ]
    for item in imported_items:
        memo = session.scalar(
            select(Memo).where(
                Memo.id == item.memo_id,
                Memo.user_id == user_id,
                Memo.resource_import_batch_id == batch.id,
            )
        )
        if memo is None:
            # 用户已经编辑过的导入资料会主动脱离批次并被保留。
            item.status = "retained"
            item.updated_at = now
            continue
        memo.status = MemoStatus.TRASHED
        memo.resource_import_batch_id = None
        memo.version += 1
        memo.updated_at = now
        item.status = "undone"
        item.updated_at = now

    batch.status = "undone"
    batch.undone_at = now
    batch.updated_at = now
    session.commit()
    session.refresh(batch)
    return batch
