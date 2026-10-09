"""英语单词批量导入的格式解析与字段清洗。"""

from __future__ import annotations

import csv
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from io import StringIO
from typing import Any
from uuid import UUID, uuid4

from app.schemas import MemoCreate

MAX_WORD_IMPORT_BYTES = 5 * 1024 * 1024
MAX_WORD_IMPORT_ROWS = 1_000
SUPPORTED_WORD_IMPORT_FORMATS = frozenset({"csv", "json"})


class WordImportFormatError(ValueError):
    """批量导入文件格式或编码不正确。"""


class WordImportTooLargeError(WordImportFormatError):
    """批量导入文件或行数超过安全上限。"""


@dataclass(frozen=True, slots=True)
class WordImportRecord:
    """带有原始行号的待导入记录。"""

    row_number: int
    values: Mapping[str, Any]


def parse_word_import(content: bytes, file_format: str) -> list[WordImportRecord]:
    """解析 JSON 或 CSV 单词文件，并保留错误提示所需的行号。"""

    if len(content) > MAX_WORD_IMPORT_BYTES:
        raise WordImportTooLargeError("单词导入文件不能超过 5 MB")
    normalized_format = file_format.strip().lower()
    if normalized_format not in SUPPORTED_WORD_IMPORT_FORMATS:
        raise WordImportFormatError("单词导入只支持 JSON 或 CSV")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise WordImportFormatError("单词导入文件必须使用 UTF-8 编码") from error
    if not text.strip():
        raise WordImportFormatError("单词导入文件不能为空")
    if normalized_format == "json":
        return _parse_json_records(text)
    return _parse_csv_records(text)


def _parse_json_records(text: str) -> list[WordImportRecord]:
    """解析单词数组或 MemoIsle JSON 导出对象。"""

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise WordImportFormatError("JSON 文件格式不正确") from error

    if isinstance(payload, Mapping):
        records = payload.get("memos", payload.get("words"))
    else:
        records = payload
    if not isinstance(records, list):
        raise WordImportFormatError("JSON 文件必须是数组，或包含 memos/words 数组")
    _ensure_row_limit(len(records))

    parsed: list[WordImportRecord] = []
    for row_number, value in enumerate(records, start=1):
        if isinstance(value, Mapping):
            parsed.append(WordImportRecord(row_number, dict(value)))
        else:
            # 保留错误行，接口可以在导入其他有效单词后返回具体失败原因。
            parsed.append(
                WordImportRecord(
                    row_number,
                    {"_import_error": "每条 JSON 数据必须是对象"},
                )
            )
    return parsed


def _parse_csv_records(text: str) -> list[WordImportRecord]:
    """解析带表头的 UTF-8 CSV 文件。"""

    reader = csv.DictReader(StringIO(text, newline=""))
    if not reader.fieldnames:
        raise WordImportFormatError("CSV 文件必须包含表头")
    normalized_fields = {
        field.strip().casefold()
        for field in reader.fieldnames
        if field is not None and field.strip()
    }
    if not normalized_fields.intersection({"title", "word", "lemma", "单词", "词形"}):
        raise WordImportFormatError("CSV 表头需要包含 title、word 或 lemma")

    parsed: list[WordImportRecord] = []
    for row_number, row in enumerate(reader, start=2):
        if len(parsed) >= MAX_WORD_IMPORT_ROWS:
            raise WordImportTooLargeError("单词导入最多支持 1000 行")
        values = {
            str(key).strip(): value
            for key, value in row.items()
            if key is not None
        }
        parsed.append(WordImportRecord(row_number, values))
    return parsed


def _ensure_row_limit(row_count: int) -> None:
    """限制一次导入的行数，避免请求占用过多内存和数据库时间。"""

    if row_count > MAX_WORD_IMPORT_ROWS:
        raise WordImportTooLargeError("单词导入最多支持 1000 条")


def _lookup_value(values: Mapping[str, Any], *names: str) -> Any:
    """按大小写不敏感的别名读取字段。"""

    normalized = {
        str(key).strip().casefold(): value for key, value in values.items()
    }
    for name in names:
        value = normalized.get(name.casefold())
        if value is not None:
            return value
    return None


def _text_value(value: Any) -> str | None:
    """把导入值转换成去除首尾空白的文本。"""

    if value is None:
        return None
    if isinstance(value, (dict, list, tuple, set)):
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _list_value(value: Any) -> list[str]:
    """兼容 JSON 数组、CSV JSON 单元格和逗号分隔标签。"""

    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        raw_values = value
    elif isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            return []
        try:
            decoded = json.loads(cleaned)
        except json.JSONDecodeError:
            decoded = None
        raw_values = (
            decoded
            if isinstance(decoded, list)
            else re.split(r"[,，\n]", cleaned)
        )
    else:
        raw_values = [value]
    return list(dict.fromkeys(
        text
        for item in raw_values
        if (text := _text_value(item)) is not None
    ))


def _bool_value(value: Any) -> bool:
    """读取常见的布尔值表示，未知值按 False 处理。"""

    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().casefold() in {"1", "true", "yes", "y", "是"}


def _uuid_value(value: Any) -> UUID:
    """保留有效 client_id，否则生成新的幂等标识。"""

    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value).strip())
    except (AttributeError, ValueError, TypeError):
        return uuid4()


def is_word_record(record: WordImportRecord) -> bool:
    """判断记录是否明确属于英语单词。未填写 type 时按单词处理。"""

    raw_type = _text_value(_lookup_value(record.values, "type", "类型"))
    return raw_type is None or raw_type.casefold() in {"word", "单词"}


def build_word_import_payload(record: WordImportRecord) -> MemoCreate:
    """把一行导入数据转换成现有的单词创建请求。"""

    import_error = _text_value(record.values.get("_import_error"))
    if import_error:
        raise ValueError(import_error)

    title = _text_value(
        _lookup_value(record.values, "title", "word", "lemma", "词形", "单词")
    )
    if title is None:
        raise ValueError("缺少单词词形")
    meaning = _text_value(
        _lookup_value(
            record.values,
            "word_meaning",
            "meaning",
            "definition",
            "释义",
        )
    )
    body = _text_value(_lookup_value(record.values, "body", "note", "备注"))
    resolved_body = meaning or body or title
    return MemoCreate.model_validate(
        {
            "client_id": _uuid_value(
                _lookup_value(record.values, "client_id", "客户端标识")
            ),
            "type": "word",
            "title": title,
            "body": resolved_body,
            "source_url": _text_value(
                _lookup_value(record.values, "source_url", "url", "来源链接")
            ),
            "source_title": _text_value(
                _lookup_value(record.values, "source_title", "来源标题")
            ),
            "word_phonetic": _text_value(
                _lookup_value(record.values, "word_phonetic", "phonetic", "音标")
            ),
            "word_meaning": meaning or body,
            "word_example": _text_value(
                _lookup_value(record.values, "word_example", "example", "例句")
            ),
            "tags": _list_value(_lookup_value(record.values, "tags", "标签")),
            "collections": _list_value(
                _lookup_value(record.values, "collections", "收藏夹")
            ),
            "starred": _bool_value(
                _lookup_value(record.values, "starred", "favorite", "星标")
            ),
        }
    )
