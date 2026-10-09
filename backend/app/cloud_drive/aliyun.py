"""阿里云盘适配层（官方 OpenAPI）。

凭据来源：用户在设置页粘贴浏览器/开放平台登录态，支持三种形态：

1. `refresh_token` + `client_id` + `client_secret`：走官方 OpenAPI 换
   access_token（推荐）。
2. 仅 `access_token`：短期有效，过期后需要重新粘贴。
3. 浏览器 cookie 串：只提取其中的 refresh_token；网页端 x-signature 签名属于非官方接口，
   需要按真实抓包确认算法，本层不做猜测。

协议：https://openapi.alipan.com
"""

from __future__ import annotations

import base64
import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from app.cloud_drive.base import (
    AccountInfo,
    CloudDriveError,
    CredentialInvalidError,
    FileMeta,
    FileRef,
    QuotaExceededError,
    RateLimitedError,
    ShareLinkInvalidError,
)

OPENAPI_BASE = "https://openapi.alipan.com"
TOKEN_REFRESH_MARGIN_SECONDS = 300
ROOT_FILE_ID = "root"
LIST_PAGE_LIMIT = 100
# 官方要求分片不小于 100KB；1MB 在请求数与重试成本之间比较平衡。
UPLOAD_PART_BYTES = 1024 * 1024
PROOF_VERSION = "v1"


@dataclass(frozen=True)
class AliyunCredential:
    """阿里云盘凭据。"""

    refresh_token: str = ""
    access_token: str = ""
    client_id: str = ""
    client_secret: str = ""

    @property
    def has_refresh_path(self) -> bool:
        """是否具备用 refresh_token 换 access_token 的完整条件。"""

        return bool(self.refresh_token and self.client_id and self.client_secret)


def parse_aliyun_credential(raw: str) -> AliyunCredential:
    """解析用户粘贴的凭据文本。"""

    text = (raw or "").strip()
    if not text:
        return AliyunCredential()
    if text.startswith("{"):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return AliyunCredential()
        if not isinstance(data, dict):
            return AliyunCredential()
        return AliyunCredential(
            refresh_token=_as_text(data.get("refresh_token")),
            access_token=_as_text(data.get("access_token")),
            client_id=_as_text(data.get("client_id")),
            client_secret=_as_text(data.get("client_secret")),
        )
    cookies = _parse_cookie_string(text)
    if cookies:
        return AliyunCredential(
            refresh_token=(
                cookies.get("refresh_token") or cookies.get("token") or ""
            ),
            access_token=cookies.get("access_token") or "",
        )
    return AliyunCredential(refresh_token=text)


class AliyunDriveClient:
    """阿里云盘客户端。"""

    provider = "aliyun"

    def __init__(
        self,
        credential: str | AliyunCredential,
        *,
        timeout: float = 30.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._credential = (
            parse_aliyun_credential(credential)
            if isinstance(credential, str)
            else credential
        )
        self._timeout = timeout
        self._http = http_client
        self._access_token = self._credential.access_token
        self._access_expires_at = 0.0
        self._drive_id: str = ""

    # ---------------------------------------------------------------- 基础设施

    def _client(self) -> httpx.Client:
        if self._http is not None:
            return self._http
        return httpx.Client(timeout=self._timeout, trust_env=False)

    def _refresh_access_token(self) -> str:
        """用 refresh_token 换 access_token。"""

        if not self._credential.has_refresh_path:
            raise CredentialInvalidError(
                "阿里云盘凭据需要 refresh_token 与其配套的 client_id / client_secret，"
                "或一个尚未过期的 access_token",
            )
        data = self._send(
            "POST",
            f"{OPENAPI_BASE}/oauth/access_token",
            json_body={
                "client_id": self._credential.client_id,
                "client_secret": self._credential.client_secret,
                "grant_type": "refresh_token",
                "refresh_token": self._credential.refresh_token,
            },
            authorized=False,
        )
        token = _as_text(data.get("access_token"))
        if not token:
            raise CredentialInvalidError(
                "阿里云盘未返回 access_token，请重新粘贴登录态",
            )
        self._access_token = token
        expires_in = _as_int(data.get("expires_in")) or 7200
        self._access_expires_at = time.time() + max(
            expires_in - TOKEN_REFRESH_MARGIN_SECONDS,
            60,
        )
        return token

    def _token(self) -> str:
        if self._access_token and (
            not self._access_expires_at or time.time() < self._access_expires_at
        ):
            return self._access_token
        if self._credential.has_refresh_path:
            return self._refresh_access_token()
        if self._access_token:
            return self._access_token
        raise CredentialInvalidError("阿里云盘凭据为空，请先在设置页绑定云盘")

    def _send(
        self,
        method: str,
        url: str,
        *,
        json_body: dict[str, Any] | None = None,
        content: bytes | None = None,
        authorized: bool = True,
    ) -> dict[str, Any]:
        """发一次请求，并把 HTTP 错误映射成领域异常。"""

        headers: dict[str, str] = {}
        if authorized:
            headers["Authorization"] = f"Bearer {self._token()}"
        if json_body is not None:
            headers["Content-Type"] = "application/json"
        try:
            if method == "PUT":
                response = self._client().put(url, content=content, headers=headers)
            else:
                response = self._client().post(
                    url,
                    json=json_body,
                    headers=headers,
                )
        except httpx.HTTPError as error:
            raise CloudDriveError(f"无法连接阿里云盘：{error}") from error
        body = _json_or_empty(response)
        if response.status_code >= 400:
            raise _map_error(response.status_code, body)
        return body

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._send("POST", f"{OPENAPI_BASE}{path}", json_body=payload)

    def _ensure_drive_id(self) -> str:
        if not self._drive_id:
            self.check_credential()
        return self._drive_id

    # ---------------------------------------------------------------- 凭据

    def check_credential(self) -> AccountInfo:
        """校验凭据并记录默认云盘 ID。"""

        data = self._post("/adrive/v1.0/user/getDriveInfo", {})
        drive_id = (
            _as_text(data.get("default_drive_id"))
            or _as_text(data.get("resource_drive_id"))
            or _as_text(data.get("backup_drive_id"))
        )
        if not drive_id:
            raise CredentialInvalidError("阿里云盘未返回可用云盘，请重新粘贴登录态")
        self._drive_id = drive_id
        display_name = (
            _as_text(data.get("name"))
            or _as_text(data.get("nick_name"))
            or "阿里云盘用户"
        )
        return AccountInfo(
            provider=self.provider,
            display_name=display_name,
            raw=data,
        )

    # ---------------------------------------------------------------- 目录

    def _list_children(self, parent_file_id: str) -> list[dict[str, Any]]:
        """列出目录下全部子项（自动翻页）。"""

        drive_id = self._ensure_drive_id()
        items: list[dict[str, Any]] = []
        marker = ""
        while True:
            payload: dict[str, Any] = {
                "drive_id": drive_id,
                "parent_file_id": parent_file_id,
                "limit": LIST_PAGE_LIMIT,
                "order_by": "name",
                "order_direction": "ASC",
            }
            if marker:
                payload["marker"] = marker
            data = self._post("/adrive/v1.0/openFile/list", payload)
            page_items = data.get("items")
            if isinstance(page_items, list):
                items.extend(item for item in page_items if isinstance(item, dict))
            marker = _as_text(data.get("next_marker"))
            if not marker:
                return items

    def _child_folder_id(self, parent_file_id: str, name: str) -> str | None:
        for item in self._list_children(parent_file_id):
            if item.get("type") != "folder":
                continue
            if _as_text(item.get("name")) == name:
                return _as_text(item.get("file_id")) or None
        return None

    def _create_folder(self, parent_file_id: str, name: str) -> str:
        data = self._post(
            "/adrive/v1.0/openFile/create",
            {
                "drive_id": self._ensure_drive_id(),
                "parent_file_id": parent_file_id,
                "name": name,
                "type": "folder",
                "check_name_mode": "refuse",
            },
        )
        file_id = _as_text(data.get("file_id"))
        if not file_id:
            raise CloudDriveError("阿里云盘未返回新建目录 ID")
        return file_id

    def ensure_folder(self, path: str) -> str:
        """按 /a/b/c 逐级确保目录存在，返回最后一级目录 ID。"""

        segments = [item for item in (path or "").split("/") if item.strip()]
        current = ROOT_FILE_ID
        for segment in segments:
            name = segment.strip()
            existing = self._child_folder_id(current, name)
            current = existing or self._create_folder(current, name)
        return current

    # ---------------------------------------------------------------- 元数据

    def get_file_meta(self, file_id: str) -> FileMeta:
        """读取文件元数据。"""

        data = self._post(
            "/adrive/v1.0/openFile/get",
            {"drive_id": self._ensure_drive_id(), "file_id": file_id},
        )
        return FileMeta(
            file_id=_as_text(data.get("file_id")) or file_id,
            name=_as_text(data.get("name")),
            path=_as_text(data.get("path")),
            size_bytes=_as_int(data.get("size")),
            content_hash=_as_text(data.get("content_hash")) or None,
            category=_as_text(data.get("category")) or None,
            thumbnail=_as_text(data.get("thumbnail")) or None,
            updated_at=_as_text(data.get("updated_at")) or None,
            raw=data,
        )

    # ---------------------------------------------------------------- 转存

    def transfer_share(
        self,
        share_url: str,
        password: str | None,
        target_folder_id: str,
    ) -> list[FileRef]:
        """把分享链接里的文件转存到目标目录。"""

        share_id = _share_id_from_url(share_url)
        token_data = self._post(
            "/adrive/v1.0/openFile/getShareToken",
            {"share_id": share_id, "share_pwd": password or ""},
        )
        share_token = _as_text(token_data.get("share_token"))
        if not share_token:
            raise ShareLinkInvalidError("无法获取分享令牌，请检查链接与提取码")

        listed = self._post(
            "/adrive/v1.0/openFile/list",
            {
                "share_id": share_id,
                "share_token": share_token,
                "parent_file_id": ROOT_FILE_ID,
                "limit": LIST_PAGE_LIMIT,
            },
        )
        items = listed.get("items")
        if not isinstance(items, list) or not items:
            raise ShareLinkInvalidError("分享里没有可转存的文件")

        refs: list[FileRef] = []
        for item in items:
            if not isinstance(item, dict) or item.get("type") == "folder":
                continue
            file_id = _as_text(item.get("file_id"))
            if not file_id:
                continue
            copied = self._post(
                "/adrive/v1.0/openFile/copy",
                {
                    "drive_id": self._ensure_drive_id(),
                    "file_id": file_id,
                    "to_parent_file_id": target_folder_id,
                    "share_id": share_id,
                    "share_token": share_token,
                    "auto_rename": True,
                },
            )
            refs.append(
                FileRef(
                    file_id=_as_text(copied.get("file_id")) or file_id,
                    name=_as_text(copied.get("name")) or _as_text(item.get("name")),
                    path=_as_text(copied.get("path")),
                    size_bytes=_as_int(copied.get("size"))
                    or _as_int(item.get("size")),
                    parent_id=target_folder_id,
                )
            )
        if not refs:
            raise ShareLinkInvalidError("分享里没有可转存的文件")
        return refs

    # ---------------------------------------------------------------- 上传

    def upload_file(
        self,
        local_path: Path,
        target_folder_id: str,
        name: str | None = None,
    ) -> FileRef:
        """分片上传本地文件；命中秒传时跳过实际上传。"""

        path = Path(local_path)
        file_name = name or path.name
        size_bytes = path.stat().st_size
        part_count = max(1, -(-size_bytes // UPLOAD_PART_BYTES))

        created = self._post(
            "/adrive/v1.0/openFile/create",
            {
                "drive_id": self._ensure_drive_id(),
                "parent_file_id": target_folder_id,
                "name": file_name,
                "type": "file",
                "size": size_bytes,
                "check_name_mode": "auto_rename",
                "part_info_list": [
                    {"part_number": index + 1} for index in range(part_count)
                ],
                "proof_code": _proof_code(path),
                "proof_version": PROOF_VERSION,
            },
        )
        file_id = _as_text(created.get("file_id"))
        if not file_id:
            raise CloudDriveError("阿里云盘未返回文件 ID")

        if not created.get("rapid_upload"):
            upload_id = _as_text(created.get("upload_id"))
            if not upload_id:
                raise CloudDriveError("阿里云盘未返回上传会话")
            self._upload_parts(path, created.get("part_info_list"))
            self._post(
                "/adrive/v1.0/openFile/complete",
                {
                    "drive_id": self._ensure_drive_id(),
                    "file_id": file_id,
                    "upload_id": upload_id,
                },
            )

        meta = self.get_file_meta(file_id)
        return FileRef(
            file_id=file_id,
            name=meta.name or file_name,
            path=meta.path,
            size_bytes=meta.size_bytes if meta.size_bytes is not None else size_bytes,
            parent_id=target_folder_id,
        )

    def _upload_parts(self, path: Path, part_info: Any) -> None:
        """按 create 返回的分片地址逐个上传。"""

        if not isinstance(part_info, list) or not part_info:
            raise CloudDriveError("阿里云盘未返回分片上传地址")
        with path.open("rb") as handle:
            for index, part in enumerate(part_info, start=1):
                if not isinstance(part, dict):
                    continue
                upload_url = _as_text(part.get("upload_url"))
                if not upload_url:
                    raise CloudDriveError("阿里云盘分片地址为空")
                chunk = handle.read(UPLOAD_PART_BYTES)
                self._send("PUT", upload_url, content=chunk, authorized=False)
                if not chunk and index > 0:
                    # 空文件也需要一次 PUT，避免服务端分片缺失。
                    break
        return None


# --------------------------------------------------------------------- 工具


def _share_id_from_url(share_url: str) -> str:
    """从分享链接里取出 share_id。"""

    cleaned = (share_url or "").strip()
    marker = "/s/"
    if marker in cleaned:
        tail = cleaned.split(marker, 1)[1]
        return tail.split("?", 1)[0].split("/", 1)[0].strip()
    return cleaned.rstrip("/").rsplit("/", 1)[-1].strip()


def _proof_code(path: Path) -> str:
    """秒传校验码：前 1KB 内容的 SHA1。"""

    with path.open("rb") as handle:
        head = handle.read(1024)
    return base64.b64encode(hashlib.sha1(head).digest()).decode("ascii")


def _json_or_empty(response: Any) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


SHARE_ERROR_CODES: frozenset[str] = frozenset(
    {"ShareLinkExpired", "ShareLinkNotFound", "SharePasswordError", "InvalidSharePwd"},
)
QUOTA_ERROR_CODES: frozenset[str] = frozenset(
    {"QuotaExhausted", "SpaceNotEnough", "InsufficientStorage"},
)
RATE_LIMIT_CODES: frozenset[str] = frozenset({"TooManyRequests", "Throttling"})
CREDENTIAL_ERROR_CODES: frozenset[str] = frozenset(
    {"AccessTokenInvalid", "RefreshTokenInvalid", "TokenExpired"},
)


def _map_error(status_code: int, body: dict[str, Any]) -> CloudDriveError:
    """把阿里云盘错误映射成统一异常。

    先看业务错误码再看 HTTP 状态：403 既可能是凭据失效，也可能是空间不足。
    错误码本身不适合直接给用户看，服务端没给 message 时补一句中文说明。
    """

    code = _as_text(body.get("code"))
    server_message = _as_text(body.get("message"))
    if code in SHARE_ERROR_CODES:
        return ShareLinkInvalidError(server_message or "分享链接失效或提取码错误")
    if code in QUOTA_ERROR_CODES:
        return QuotaExceededError(server_message or "阿里云盘空间不足")
    if code in RATE_LIMIT_CODES or status_code == 429:
        return RateLimitedError(server_message or "阿里云盘限流，请稍后重试")
    if status_code in (401, 403) or code in CREDENTIAL_ERROR_CODES:
        return CredentialInvalidError(
            server_message or "阿里云盘凭据已失效，请重新粘贴登录态",
        )
    return CloudDriveError(server_message or code or "阿里云盘接口调用失败")


def _as_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_cookie_string(text: str) -> dict[str, str]:
    """把 cookie 串解析成字典；不像 cookie 时返回空字典。"""

    if "=" not in text:
        return {}
    cookies: dict[str, str] = {}
    for chunk in text.replace("\n", ";").split(";"):
        if "=" not in chunk:
            continue
        key, _, value = chunk.partition("=")
        cleaned_key = key.strip()
        if cleaned_key:
            cookies[cleaned_key] = value.strip()
    return cookies
