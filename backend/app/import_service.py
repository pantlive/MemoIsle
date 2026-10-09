"""完整资料备份导入。"""

from __future__ import annotations

import csv
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from io import StringIO
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.category_service import CategoryCodeNotFoundError, assign_memo_categories
from app.models import Memo
from app.schemas import (
    MemoCreate,
    MemoStatus,
    MemoType,
    ResourceKind,
    ResourceProcessStatus,
    ResourceReadingStatus,
)
from app.service import (
    ResourceDuplicateError,
    WordDuplicateError,
    create_memo,
)
from app.word_import_service import (
    _bool_value,
    _list_value,
    _lookup_value,
    _text_value,
    _uuid_value,
)

MAX_LIBRARY_IMPORT_BYTES = 10 * 1024 * 1024
MAX_LIBRARY_IMPORT_ROWS = 5_000
SUPPORTED_LIBRARY_IMPORT_FORMATS = frozenset({"json", "csv"})


class LibraryImportFormatError(ValueError):
    """完整备份文件格式或编码不正确。"""


class LibraryImportTooLargeError(LibraryImportFormatError):
    """完整备份文件或条数超过安全上限。"""


@dataclass(frozen=True, slots=True)
class LibraryImportRecord:
    """带原始行号的待导入条目。"""

    row_number: int
    values: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class LibraryImportResult:
    """完整备份导入统计。"""

    total_count: int
    imported_count: int
    duplicate_count: int
    skipped_count: int
    failed_count: int
    errors: tuple[tuple[int, str], ...]


def parse_library_import(content: bytes, file_format: str) -> list[LibraryImportRecord]:
    """解析 MemoIsle JSON 或 CSV 导出文件。"""

    if len(content) > MAX_LIBRARY_IMPORT_BYTES:
        raise LibraryImportTooLargeError("备份文件不能超过 10 MB")
    normalized_format = file_format.strip().lower()
    if normalized_format not in SUPPORTED_LIBRARY_IMPORT_FORMATS:
        raise LibraryImportFormatError("完整备份只支持 JSON 或 CSV")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise LibraryImportFormatError("备份文件必须使用 UTF-8 编码") from error
    if not text.strip():
        raise LibraryImportFormatError("备份文件不能为空")
    if normalized_format == "json":
        return _parse_json_records(text)
    return _parse_csv_records(text)


def import_library_memos(
    session: Session,
    user_id: str,
    records: list[LibraryImportRecord],
) -> LibraryImportResult:
    """把备份条目写入当前账号，按 client_id、词形和网址去重。"""

    imported_count = 0
    duplicate_count = 0
    skipped_count = 0
    failed_count = 0
    errors: list[tuple[int, str]] = []
    for record in records:
        try:
            payload = build_library_import_payload(record)
        except (TypeError, ValueError) as error:
            failed_count += 1
            if len(errors) < 50:
                message = str(error).strip() or "字段校验失败"
                errors.append((record.row_number, message[:200]))
            continue

        existing = session.scalar(
            select(Memo).where(
                Memo.user_id == user_id,
                Memo.client_id == str(payload.client_id),
            )
        )
        if existing is not None:
            duplicate_count += 1
            continue
        try:
            memo = create_memo(session, user_id, payload)
        except WordDuplicateError:
            duplicate_count += 1
            continue
        except ResourceDuplicateError:
            duplicate_count += 1
            continue
        _apply_imported_fields(session, user_id, memo, record.values)
        session.commit()
        imported_count += 1
    return LibraryImportResult(
        total_count=len(records),
        imported_count=imported_count,
        duplicate_count=duplicate_count,
        skipped_count=skipped_count,
        failed_count=failed_count,
        errors=tuple(errors),
    )


def build_library_import_payload(record: LibraryImportRecord) -> MemoCreate:
    """把导出行转换成创建条目请求。"""

    values = record.values
    import_error = _lookup_value(values, "_import_error")
    if import_error:
        raise ValueError(str(import_error))
    memo_type = _memo_type(_lookup_value(values, "type"))
    title = _text_value(_lookup_value(values, "title"))
    body = _text_value(_lookup_value(values, "body")) or title
    if not body:
        raise ValueError("缺少正文")
    source_url = _text_value(_lookup_value(values, "source_url"))
    if memo_type == MemoType.RESOURCE and not source_url:
        raise ValueError("网页资料必须提供来源链接")
    if memo_type == MemoType.WORD and not title:
        raise ValueError("英语单词必须提供词形")
    return MemoCreate(
        client_id=_uuid_value(_lookup_value(values, "client_id")),
        type=memo_type,
        title=title,
        body=body,
        transcript=_text_value(_lookup_value(values, "transcript")),
        source_url=source_url,
        source_title=_text_value(_lookup_value(values, "source_title")),
        word_phonetic=_text_value(_lookup_value(values, "word_phonetic")),
        word_meaning=_text_value(
            _lookup_value(values, "word_meaning", "meaning"),
        ) or (body if memo_type == MemoType.WORD else None),
        word_example=_text_value(_lookup_value(values, "word_example", "example")),
        tags=_list_value(_lookup_value(values, "tags")),
        collections=_list_value(_lookup_value(values, "collections")),
        resource_kind=_enum_value(
            _lookup_value(values, "resource_kind"),
            ResourceKind,
        ),
        resource_reading_status=_enum_value(
            _lookup_value(values, "resource_reading_status"),
            ResourceReadingStatus,
        ),
        starred=_bool_value(_lookup_value(values, "starred") or False),
    )


def _parse_json_records(text: str) -> list[LibraryImportRecord]:
    """解析 MemoIsle JSON 导出对象或条目数组。"""

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise LibraryImportFormatError("JSON 文件格式不正确") from error
    if isinstance(payload, Mapping):
        records = payload.get("memos")
        export_format = payload.get("format")
        if export_format not in {None, "memoisle-json"}:
            raise LibraryImportFormatError("不是 MemoIsle JSON 备份文件")
    else:
        records = payload
    if not isinstance(records, list):
        raise LibraryImportFormatError("JSON 文件必须包含 memos 数组")
    if len(records) > MAX_LIBRARY_IMPORT_ROWS:
        raise LibraryImportTooLargeError("完整备份最多支持 5000 条")
    parsed: list[LibraryImportRecord] = []
    for row_number, value in enumerate(records, start=1):
        if isinstance(value, Mapping):
            parsed.append(LibraryImportRecord(row_number, dict(value)))
        else:
            parsed.append(
                LibraryImportRecord(
                    row_number,
                    {"_import_error": "每条数据必须是对象"},
                )
            )
    return parsed


def _parse_csv_records(text: str) -> list[LibraryImportRecord]:
    """解析导出 CSV，列表字段按 JSON 文本还原。"""

    reader = csv.DictReader(StringIO(text, newline=""))
    if not reader.fieldnames:
        raise LibraryImportFormatError("CSV 文件必须包含表头")
    parsed: list[LibraryImportRecord] = []
    for row_number, row in enumerate(reader, start=2):
        if len(parsed) >= MAX_LIBRARY_IMPORT_ROWS:
            raise LibraryImportTooLargeError("完整备份最多支持 5000 条")
        values = {
            str(key).strip(): _decode_csv_cell(value)
            for key, value in row.items()
            if key is not None
        }
        parsed.append(LibraryImportRecord(row_number, values))
    return parsed


def _decode_csv_cell(value: Any) -> Any:
    """还原导出 CSV 里用 JSON 保存的数组和对象。"""

    if not isinstance(value, str):
        return value
    cleaned = value.strip()
    if not cleaned or cleaned[0] not in {"[", "{"}:
        return value
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return value


def _memo_type(value: Any) -> MemoType:
    """读取条目类型。"""

    text = _text_value(value)
    if not text:
        raise ValueError("缺少类型")
    try:
        return MemoType(text)
    except ValueError as error:
        raise ValueError("类型无效") from error


def _enum_value(value: Any, enum_type: type) -> Any:
    """把文本转换成枚举，无法识别时忽略。"""

    text = _text_value(value)
    if not text:
        return None
    try:
        return enum_type(text)
    except ValueError:
        return None


def _datetime_value(value: Any) -> datetime | None:
    """解析导出中的 ISO 时间。"""

    text = _text_value(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _apply_imported_fields(
    session: Session,
    user_id: str,
    memo: Memo,
    values: Mapping[str, Any],
) -> None:
    """补全导出里有、创建接口未覆盖的字段。"""

    if _lookup_value(values, "_import_error"):
        raise ValueError(str(_lookup_value(values, "_import_error")))
    memo.starred = _bool_value(_lookup_value(values, "starred") or memo.starred)
    familiarity = _lookup_value(values, "familiarity")
    if isinstance(familiarity, int) and familiarity >= 0:
        memo.familiarity = familiarity
    review_count = _lookup_value(values, "review_count")
    if isinstance(review_count, int) and review_count >= 0:
        memo.review_count = review_count
    last_review_at = _datetime_value(_lookup_value(values, "last_review_at"))
    if last_review_at is not None:
        memo.last_review_at = last_review_at
    next_review_at = _datetime_value(_lookup_value(values, "next_review_at"))
    if next_review_at is not None:
        memo.next_review_at = next_review_at
    if memo.type == MemoType.RESOURCE:
        page_title = _text_value(_lookup_value(values, "resource_page_title"))
        if page_title:
            memo.resource_page_title = page_title
        description = _text_value(_lookup_value(values, "resource_description"))
        if description:
            memo.resource_description = description
        site_name = _text_value(_lookup_value(values, "resource_site_name"))
        if site_name:
            memo.resource_site_name = site_name
        favicon = _text_value(_lookup_value(values, "resource_favicon_url"))
        if favicon:
            memo.resource_favicon_url = favicon
        image = _text_value(_lookup_value(values, "resource_image_url"))
        if image:
            memo.resource_image_url = image
        kind = _enum_value(_lookup_value(values, "resource_kind"), ResourceKind)
        if kind is not None:
            memo.resource_kind = kind
        reading = _enum_value(
            _lookup_value(values, "resource_reading_status"),
            ResourceReadingStatus,
        )
        if reading is not None:
            memo.resource_reading_status = reading
        metadata_status = _enum_value(
            _lookup_value(values, "resource_metadata_status"),
            ResourceProcessStatus,
        )
        if metadata_status is not None:
            memo.resource_metadata_status = metadata_status
        category_codes = _list_value(_lookup_value(values, "resource_categories"))
        primary = _text_value(_lookup_value(values, "resource_category"))
        if primary and primary not in category_codes:
            category_codes = [primary, *category_codes]
        if category_codes:
            try:
                assign_memo_categories(
                    session,
                    user_id,
                    memo,
                    category_codes,
                    manual=True,
                )
            except CategoryCodeNotFoundError:
                memo.resource_category_label = _text_value(
                    _lookup_value(values, "resource_category_label"),
                )
    if memo.type == MemoType.IMAGE:
        # 图片二进制不随备份迁移，但已识别的文字与标签可以恢复并继续参与搜索。
        ocr_text = _text_value(_lookup_value(values, "image_ocr_text"))
        auto_tags = _list_value(_lookup_value(values, "image_auto_tags"))
        if ocr_text or auto_tags:
            memo.image_ocr_text = ocr_text or None
            memo.image_auto_tags = auto_tags
            memo.image_ocr_source = (
                _text_value(_lookup_value(values, "image_ocr_source")) or None
            )
            memo.image_ocr_status = "ready"
            memo.image_ocr_error = None
    status_text = _text_value(_lookup_value(values, "status"))
    if status_text:
        try:
            status = MemoStatus(status_text)
        except ValueError:
            status = None
        if status is not None and status != memo.status:
            previous = memo.status
            memo.status = status
            if status == MemoStatus.TRASHED and previous != MemoStatus.TRASHED:
                memo.deleted_at = (
                    _datetime_value(_lookup_value(values, "deleted_at"))
                    or datetime.now(UTC)
                )
                memo.status_before_trash = previous.value
            elif status != MemoStatus.TRASHED:
                memo.deleted_at = None
                memo.status_before_trash = None
