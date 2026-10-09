"""个人资料的 CSV 与 Markdown 导出格式。"""

from __future__ import annotations

import csv
import json
from collections.abc import Sequence
from io import StringIO
from typing import Any

from app.models import Memo
from app.schemas import MemoRead

EXPORT_COLUMNS: tuple[str, ...] = tuple(MemoRead.model_fields)


def _memo_data(memo: Memo) -> dict[str, Any]:
    """把数据库模型转换成与 JSON 导出一致的公开字段。"""

    return MemoRead.model_validate(memo).model_dump(mode="json")


def _csv_value(value: Any) -> str:
    """把列表、字典和空值编码为稳定的 CSV 单元格。"""

    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)


def serialize_memos_csv(memos: Sequence[Memo]) -> str:
    """序列化完整条目字段，数组字段使用 JSON 文本保留结构。"""

    output = StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=list(EXPORT_COLUMNS),
        lineterminator="\n",
    )
    writer.writeheader()
    for memo in memos:
        data = _memo_data(memo)
        writer.writerow(
            {
                column: _csv_value(data.get(column))
                for column in EXPORT_COLUMNS
            }
        )
    return output.getvalue()


def _markdown_value(value: Any) -> str:
    """将字段转换成 Markdown 中安全且可读的文本。"""

    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value).replace("\r\n", "\n").replace("\r", "\n").strip()


def serialize_memos_markdown(memos: Sequence[Memo]) -> str:
    """生成便于阅读的 Markdown 资料备份。"""

    lines = [
        "# MemoIsle 数据导出",
        "",
        f"> 共 {len(memos)} 条内容；录音和图片文件未包含在此导出中。",
        "",
    ]
    for index, memo in enumerate(memos, start=1):
        data = _memo_data(memo)
        title = _markdown_value(data.get("title")) or "未命名内容"
        lines.extend([f"## {index}. {title}", ""])
        for key in (
            "type",
            "source_url",
            "source_title",
            "resource_site_name",
            "resource_category_label",
            "link_health_status",
            "word_phonetic",
            "word_meaning",
            "word_example",
            "image_mime_type",
            "image_width",
            "image_height",
            "image_size_bytes",
            "tags",
            "collections",
            "starred",
            "status",
            "created_at",
            "updated_at",
        ):
            value = _markdown_value(data.get(key))
            if value:
                lines.append(f"- **{key}**：{value}")
        body = _markdown_value(data.get("body"))
        if body:
            lines.extend(["", "### 正文", "", body, ""])
        transcript = _markdown_value(data.get("transcript"))
        if transcript:
            lines.extend(["", "### 转写", "", transcript])
        lines.append("---")
        lines.append("")
    return "\n".join(lines)
