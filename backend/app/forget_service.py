"""易忘事项：文字、图片和文件的增删改查，按账号隔离。"""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Iterable
from pathlib import Path
from uuid import uuid4

from sqlalchemy import func, insert, literal, select, update
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.orm.exc import StaleDataError

from app.database import commit_with_retry
from app.models import ForgetAttachment, ForgetItem, User, utc_now
from app.relay_service import clean_filename, clean_mime_type
from app.schemas import ForgetItemCreate, ForgetItemUpdate
from app.service import MAX_IMAGE_BYTES, ImageValidationError, decode_image

logger = logging.getLogger(__name__)

MAX_FORGET_ITEMS = 2_000
MAX_FORGET_ATTACHMENTS = 20
_USER_DIR_NAME = re.compile(r"^[0-9A-Za-z_-]{1,64}$")
_STORAGE_NAME = re.compile(r"^[0-9a-f]{32}$")


class ForgetItemNotFoundError(LookupError):
    """事项不存在或不属于当前账号。"""


class ForgetAttachmentNotFoundError(LookupError):
    """附件不存在或不属于当前账号。"""


class ForgetItemLimitError(RuntimeError):
    """事项条数超出上限。"""


class ForgetAttachmentLimitError(RuntimeError):
    """单条事项的附件数量超出上限。"""


class ForgetPayloadTooLargeError(RuntimeError):
    """单个附件超过 20 MB。"""


class ForgetVersionConflictError(RuntimeError):
    """版本号已过期，附带服务端当前内容。"""

    def __init__(self, current: ForgetItem) -> None:
        super().__init__("这条事项已在其他设备修改，请刷新后重试")
        self.current = current


def list_items(
    session: Session,
    user_id: str,
    *,
    query: str | None = None,
    limit: int = MAX_FORGET_ITEMS,
    offset: int = 0,
) -> list[ForgetItem]:
    """列出事项。q 同时匹配标题和正文，置顶的在前。"""

    statement = select(ForgetItem).where(ForgetItem.user_id == user_id)
    cleaned = (query or "").strip()
    if cleaned:
        pattern = _like_pattern(cleaned)
        statement = statement.where(
            ForgetItem.title.ilike(pattern, escape="\\")
            | ForgetItem.content.ilike(pattern, escape="\\")
        )
    statement = (
        statement.options(selectinload(ForgetItem.attachments))
        .order_by(
            ForgetItem.pinned.desc(),
            ForgetItem.updated_at.desc(),
            ForgetItem.id.desc(),
        )
        .limit(max(1, min(limit, MAX_FORGET_ITEMS)))
        .offset(max(0, offset))
    )
    return list(session.scalars(statement))


def create_item(
    session: Session,
    user_id: str,
    payload: ForgetItemCreate,
) -> ForgetItem:
    """新建一条事项；超过条数上限时拒绝。"""

    session.execute(select(User.id).where(User.id == user_id).with_for_update())
    count = (
        select(func.count())
        .select_from(ForgetItem)
        .where(ForgetItem.user_id == user_id)
        .scalar_subquery()
    )
    item_id = str(uuid4())
    now = utc_now()
    fields = dict(
        id=item_id,
        user_id=user_id,
        version=1,
        created_at=now,
        updated_at=now,
        **payload.model_dump(),
    )
    result = session.execute(
        insert(ForgetItem).from_select(
            list(fields),
            select(*(literal(value) for value in fields.values())).where(
                count < MAX_FORGET_ITEMS
            ),
        )
    )
    if result.rowcount == 0:
        session.rollback()
        raise ForgetItemLimitError
    commit_with_retry(session)
    return _get_item(session, user_id, item_id)


def update_item(
    session: Session,
    user_id: str,
    item_id: str,
    payload: ForgetItemUpdate,
) -> ForgetItem:
    """按版本号改标题、正文和置顶。"""

    item = _get_item(session, user_id, item_id)
    if item.version != payload.expected_version:
        raise ForgetVersionConflictError(item)
    for field, value in payload.model_dump(exclude={"expected_version"}).items():
        setattr(item, field, value)
    item.version += 1
    try:
        commit_with_retry(session)
    except StaleDataError as error:
        session.rollback()
        raise ForgetVersionConflictError(
            _get_item(session, user_id, item_id)
        ) from error
    session.refresh(item)
    return item


def delete_item(
    session: Session,
    user_id: str,
    item_id: str,
    expected_version: int,
    directory: Path,
) -> None:
    """按版本号直接删除事项。数据库提交成功后再删磁盘文件。"""

    item = _get_item(session, user_id, item_id)
    if item.version != expected_version:
        raise ForgetVersionConflictError(item)
    paths = [
        _stored_path(directory, user_id, attachment.storage_name)
        for attachment in item.attachments
    ]
    session.delete(item)
    try:
        commit_with_retry(session)
    except StaleDataError as error:
        session.rollback()
        raise ForgetVersionConflictError(
            _get_item(session, user_id, item_id)
        ) from error
    _remove_files(path for path in paths if path is not None)


def add_attachment(
    session: Session,
    user_id: str,
    item_id: str,
    content: bytes,
    filename: str,
    mime_type: str | None,
    directory: Path,
) -> ForgetItem:
    """保存一个附件。图片校验通过才记为 image，其余一律算 file。"""

    if len(content) > MAX_IMAGE_BYTES:
        raise ForgetPayloadTooLargeError
    if not content:
        raise ValueError("附件内容不能为空")
    item = _get_item(session, user_id, item_id)
    kind, mime = classify_attachment(content, mime_type)
    original_name = clean_filename(filename)
    stored = _write_attachment(directory, user_id, content)
    committed = False
    try:
        session.execute(
            select(ForgetItem.id)
            .where(ForgetItem.id == item.id, ForgetItem.user_id == user_id)
            .with_for_update()
        )
        count = (
            select(func.count())
            .select_from(ForgetAttachment)
            .where(ForgetAttachment.item_id == item.id)
            .scalar_subquery()
        )
        raw_position = session.scalar(
            select(func.coalesce(func.max(ForgetAttachment.position), -1)).where(
                ForgetAttachment.item_id == item.id
            )
        )
        position = (-1 if raw_position is None else int(raw_position)) + 1
        now = utc_now()
        fields = dict(
            id=str(uuid4()),
            item_id=item.id,
            user_id=user_id,
            kind=kind,
            storage_name=stored.name,
            original_name=original_name,
            mime=mime,
            size=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            position=position,
            created_at=now,
        )
        result = session.execute(
            insert(ForgetAttachment).from_select(
                list(fields),
                select(*(literal(value) for value in fields.values())).where(
                    count < MAX_FORGET_ATTACHMENTS
                ),
            )
        )
        if result.rowcount == 0:
            session.rollback()
            raise ForgetAttachmentLimitError
        session.execute(
            update(ForgetItem)
            .where(ForgetItem.id == item.id, ForgetItem.user_id == user_id)
            .values(updated_at=now)
        )
        commit_with_retry(session)
        committed = True
    finally:
        if not committed:
            _remove_files([stored])
    session.expire(item)
    return _get_item(session, user_id, item_id)


def delete_attachment(
    session: Session,
    user_id: str,
    item_id: str,
    attachment_id: str,
    directory: Path,
) -> None:
    """删除一个附件。数据库提交成功后再删磁盘文件。"""

    item = _get_item(session, user_id, item_id)
    attachment = _attachment_of(item, user_id, attachment_id)
    path = _stored_path(directory, user_id, attachment.storage_name)
    session.delete(attachment)
    session.execute(
        update(ForgetItem)
        .where(ForgetItem.id == item.id, ForgetItem.user_id == user_id)
        .values(updated_at=utc_now())
    )
    commit_with_retry(session)
    if path is not None:
        _remove_files([path])


def open_attachment(
    session: Session,
    user_id: str,
    item_id: str,
    attachment_id: str,
    directory: Path,
) -> tuple[ForgetAttachment, Path]:
    """打开属于当前账号的附件。文件缺失时与不存在同样返回找不到。"""

    item = _get_item(session, user_id, item_id)
    attachment = _attachment_of(item, user_id, attachment_id)
    path = _stored_path(directory, user_id, attachment.storage_name)
    if path is None or not path.is_file():
        raise ForgetAttachmentNotFoundError
    return attachment, path


def classify_attachment(content: bytes, mime_type: str | None) -> tuple[str, str]:
    """MIME 是图片且能通过现有图片校验时记为 image，否则记为 file。"""

    mime = clean_mime_type(mime_type)
    if mime == "image/jpg":
        mime = "image/jpeg"
    if mime.startswith("image/"):
        try:
            decode_image(content, mime)
        except ImageValidationError:
            return "file", mime
        return "image", mime
    return "file", mime


def _get_item(session: Session, user_id: str, item_id: str) -> ForgetItem:
    item = session.scalar(
        select(ForgetItem)
        .where(ForgetItem.id == item_id, ForgetItem.user_id == user_id)
        .options(selectinload(ForgetItem.attachments))
    )
    if item is None:
        raise ForgetItemNotFoundError
    return item


def _attachment_of(
    item: ForgetItem,
    user_id: str,
    attachment_id: str,
) -> ForgetAttachment:
    for attachment in item.attachments:
        if attachment.id == attachment_id and attachment.user_id == user_id:
            return attachment
    raise ForgetAttachmentNotFoundError


def _write_attachment(directory: Path, user_id: str, content: bytes) -> Path:
    folder = _user_directory(directory, user_id)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / uuid4().hex
    path.write_bytes(content)
    return path


def _user_directory(directory: Path, user_id: str) -> Path:
    if not _USER_DIR_NAME.fullmatch(user_id):
        raise ForgetItemNotFoundError
    root = directory.resolve()
    folder = (root / user_id).resolve()
    if folder.parent != root:
        raise ForgetItemNotFoundError
    return folder


def _stored_path(directory: Path, user_id: str, storage_name: str) -> Path | None:
    if not _STORAGE_NAME.fullmatch(storage_name):
        logger.warning("忽略非法的易忘附件存储名")
        return None
    try:
        folder = _user_directory(directory, user_id)
    except ForgetItemNotFoundError:
        return None
    path = (folder / storage_name).resolve()
    if path.parent != folder:
        return None
    return path


def _remove_files(paths: Iterable[Path]) -> None:
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError as error:
            logger.warning("删除易忘附件文件失败：%s（%s）", path, error)


def _like_pattern(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"
