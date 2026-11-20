"""下载响应里的 Content-Disposition，兼容中文文件名。

中转和易忘事项共用，避免两处各自拼响应头。
"""

from __future__ import annotations

from urllib.parse import quote


def content_disposition(filename: str, disposition: str = "attachment") -> str:
    """生成同时带 ASCII 回退名和 RFC 5987 UTF-8 文件名的响应头。"""

    kind = disposition if disposition in {"attachment", "inline"} else "attachment"
    ascii_name = filename.encode("ascii", "ignore").decode("ascii")
    for char in ('"', "\\", "\r", "\n"):
        ascii_name = ascii_name.replace(char, "")
    ascii_name = ascii_name.strip() or "file"
    return (
        f"{kind}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"
    )
