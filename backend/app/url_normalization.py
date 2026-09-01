"""网页收藏网址规范化工具。"""

from __future__ import annotations

from urllib.parse import SplitResult, urlsplit, urlunsplit


def canonicalize_resource_url(value: str) -> str:
    """生成用于资料去重的 HTTP(S) 网址规范形式。"""

    cleaned = value.strip()
    try:
        parsed = urlsplit(cleaned)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as error:
        raise ValueError("invalid_url") from error
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"} or not hostname:
        raise ValueError("invalid_url")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("embedded_credentials")
    try:
        normalized_host = hostname.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError as error:
        raise ValueError("invalid_hostname") from error
    if not normalized_host or any(character.isspace() for character in normalized_host):
        raise ValueError("invalid_hostname")
    display_host = (
        f"[{normalized_host}]" if ":" in normalized_host else normalized_host
    )
    default_port = 443 if scheme == "https" else 80
    netloc = display_host if port in {None, default_port} else f"{display_host}:{port}"
    normalized = SplitResult(
        scheme=scheme,
        netloc=netloc,
        path=parsed.path or "/",
        query=parsed.query,
        fragment="",
    )
    return urlunsplit(normalized)
