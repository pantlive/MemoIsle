"""百度网盘适配层（网页接口 + BDUSS cookie）。

凭据来源：用户在设置页粘贴浏览器登录态，支持：

1. `{"bduss": "...", "stoken": "...", "access_token": "..."}`；
2. 浏览器 cookie 串（自动提取 `BDUSS` / `STOKEN`）；
3. 纯 `BDUSS` 字符串。

已知限制（不掩盖）：
- 目录、列表、元数据、分享转存只用 cookie 即可；
- **上传**走 PCS `superfile2`，官方要求应用的 `access_token`。只给 cookie 时百度可能
  返回 403，此时需要用户补一个开放平台应用的 access_token。代码里把它作为可选字段，
  缺失时给出明确错误而不是静默失败。
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

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

PAN_BASE = "https://pan.baidu.com"
PCS_BASE = "https://d.pcs.baidu.com"
APP_ID = "250528"
CHANNEL = "chunlei"
UPLOAD_PART_BYTES = 4 * 1024 * 1024
LIST_PAGE_LIMIT = 1000
SHARE_ERROR_CODES: frozenset[int] = frozenset({-9, 12, -62, 105, 110})
QUOTA_ERROR_CODES: frozenset[int] = frozenset({-10, 12})
CREDENTIAL_ERROR_CODES: frozenset[int] = frozenset({-6, 2, -7})
RATE_LIMIT_ERROR_CODES: frozenset[int] = frozenset({-8, 112})


@dataclass(frozen=True)
class BaiduCredential:
    """百度网盘凭据。"""

    bduss: str = ""
    stoken: str = ""
    access_token: str = ""

    def cookie_header(self) -> str:
        parts = [f"BDUSS={self.bduss}"]
        if self.stoken:
            parts.append(f"STOKEN={self.stoken}")
        return "; ".join(parts)


def parse_baidu_credential(raw: str) -> BaiduCredential:
    """解析用户粘贴的凭据文本。"""

    text = (raw or "").strip()
    if not text:
        return BaiduCredential()
    if text.startswith("{"):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return BaiduCredential()
        if not isinstance(data, dict):
            return BaiduCredential()
        return BaiduCredential(
            bduss=_as_text(data.get("bduss")) or _as_text(data.get("BDUSS")),
            stoken=_as_text(data.get("stoken")) or _as_text(data.get("STOKEN")),
            access_token=_as_text(data.get("access_token")),
        )
    cookies = _parse_cookie_string(text)
    if cookies:
        return BaiduCredential(
            bduss=cookies.get("BDUSS", ""),
            stoken=cookies.get("STOKEN", ""),
            access_token=cookies.get("access_token", ""),
        )
    return BaiduCredential(bduss=text)


class BaiduPanClient:
    """百度网盘客户端。"""

    provider = "baidu"

    def __init__(
        self,
        credential: str | BaiduCredential,
        *,
        timeout: float = 30.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._credential = (
            parse_baidu_credential(credential)
            if isinstance(credential, str)
            else credential
        )
        self._timeout = timeout
        self._http = http_client
        self._bdstoken: str = ""
        self._uk: str = ""

    # ---------------------------------------------------------------- 基础设施

    def _client(self) -> httpx.Client:
        if self._http is not None:
            return self._http
        return httpx.Client(timeout=self._timeout, trust_env=False)

    def _common_params(self) -> dict[str, str]:
        params = {
            "channel": CHANNEL,
            "web": "1",
            "app_id": APP_ID,
            "clienttype": "0",
        }
        if self._bdstoken:
            params["bdstoken"] = self._bdstoken
        return params

    def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        with_cookie: bool = True,
    ) -> dict[str, Any]:
        """发一次请求并统一处理 errno。"""

        headers: dict[str, str] = {}
        if with_cookie:
            if not self._credential.bduss:
                raise CredentialInvalidError("百度网盘凭据缺少 BDUSS，请重新粘贴登录态")
            headers["Cookie"] = self._credential.cookie_header()
        try:
            response = self._client().request(
                method,
                url,
                params=params,
                data=data,
                files=files,
                headers=headers,
            )
        except httpx.HTTPError as error:
            raise CloudDriveError(f"无法连接百度网盘：{error}") from error
        if response.status_code == 401 or response.status_code == 403:
            raise CredentialInvalidError("百度网盘凭据已失效，请重新粘贴 BDUSS")
        if response.status_code == 429:
            raise RateLimitedError("百度网盘限流，请稍后重试")
        if response.status_code >= 400:
            raise CloudDriveError(f"百度网盘请求失败（HTTP {response.status_code}）")
        try:
            payload = response.json()
        except ValueError as error:
            raise CloudDriveError("百度网盘返回了无法解析的响应") from error
        if not isinstance(payload, dict):
            raise CloudDriveError("百度网盘返回了非预期结构")
        errno = payload.get("errno")
        if errno not in (0, None):
            raise _map_errno(int(errno), _as_text(payload.get("errmsg")))
        return payload

    def _api(self, path: str, **kwargs: Any) -> dict[str, Any]:
        params = {**self._common_params(), **(kwargs.pop("params", None) or {})}
        return self._request("GET", f"{PAN_BASE}{path}", params=params, **kwargs)

    # ---------------------------------------------------------------- 凭据

    def check_credential(self) -> AccountInfo:
        """用 cookie 换账号信息，并缓存 bdstoken / uk。"""

        payload = self._api(
            "/api/quota",
            params={"checkfree": "1", "checkexpire": "1"},
        )
        self._uk = _as_text(payload.get("uk"))
        self._bdstoken = self._fetch_bdstoken()
        display_name = (
            _as_text(payload.get("netdisk_name"))
            or _as_text(payload.get("baidu_name"))
            or "百度网盘用户"
        )
        return AccountInfo(
            provider=self.provider,
            display_name=display_name,
            raw=payload,
        )

    def _fetch_bdstoken(self) -> str:
        """取 bdstoken：写操作（建目录、转存、上传）都需要它。"""

        payload = self._api(
            "/api/gettemplatevariable",
            params={"fields": json.dumps(["bdstoken"])},
        )
        result = payload.get("result")
        if isinstance(result, dict):
            return _as_text(result.get("bdstoken"))
        return ""

    def _ensure_token(self) -> None:
        if not self._bdstoken:
            self.check_credential()

    # ---------------------------------------------------------------- 目录

    def list_dir(self, directory: str) -> list[dict[str, Any]]:
        """列出目录下全部条目。"""

        payload = self._api(
            "/api/list",
            params={
                "dir": directory,
                "order": "name",
                "desc": "0",
                "showempty": "0",
                "page": "1",
                "num": str(LIST_PAGE_LIMIT),
            },
        )
        items = payload.get("list")
        if not isinstance(items, list):
            return []
        return [item for item in items if isinstance(item, dict)]

    def ensure_folder(self, path: str) -> str:
        """按 /a/b/c 逐级确保目录存在，返回最后一级的绝对路径。"""

        segments = [item for item in (path or "").split("/") if item.strip()]
        current = ""
        for segment in segments:
            name = segment.strip()
            listing = self.list_dir(current or "/")
            existing = next(
                (
                    item
                    for item in listing
                    if item.get("isdir") == 1
                    and _as_text(item.get("server_filename")) == name
                ),
                None,
            )
            if existing is not None:
                current = _as_text(existing.get("path")) or f"{current}/{name}"
                continue
            current = f"{current}/{name}"
            self._create_folder(current)
        return current or "/"

    def _create_folder(self, path: str) -> None:
        self._ensure_token()
        self._request(
            "POST",
            f"{PAN_BASE}/api/create",
            params={**self._common_params(), "a": "commit"},
            data={
                "path": path,
                "isdir": "1",
                "block_list": "[]",
                "rtype": "3",
            },
        )

    # ---------------------------------------------------------------- 元数据

    def get_file_meta_by_path(self, path: str) -> FileMeta:
        """按路径读取文件元数据。"""

        payload = self._api(
            "/api/filemetas",
            params={"target": json.dumps([path]), "dlink": "1"},
        )
        info = payload.get("info")
        first = info[0] if isinstance(info, list) and info else {}
        if not isinstance(first, dict):
            first = {}
        return FileMeta(
            file_id=_as_text(first.get("fs_id")),
            name=_as_text(first.get("server_filename")),
            path=_as_text(first.get("path")) or path,
            size_bytes=_as_int(first.get("size")),
            content_hash=_as_text(first.get("md5")) or None,
            category=_as_text(first.get("category")) or None,
            thumbnail=(
                _as_text(first["thumbs"].get("url3"))
                if isinstance(first.get("thumbs"), dict)
                else None
            ),
            updated_at=_as_text(first.get("server_mtime")) or None,
            raw=first,
        )

    def get_file_meta(self, file_id: str) -> FileMeta:
        """适配层统一接口按 file_id 读取；百度以路径为主，这里走 fs_id 反查列表。"""

        payload = self._api(
            "/api/filemetas",
            params={"target": json.dumps([file_id]), "dlink": "1"},
        )
        info = payload.get("info")
        first = info[0] if isinstance(info, list) and info else {}
        if not isinstance(first, dict):
            first = {}
        return FileMeta(
            file_id=_as_text(first.get("fs_id")) or file_id,
            name=_as_text(first.get("server_filename")),
            path=_as_text(first.get("path")),
            size_bytes=_as_int(first.get("size")),
            content_hash=_as_text(first.get("md5")) or None,
            raw=first,
        )

    # ---------------------------------------------------------------- 转存

    def transfer_share(
        self,
        share_url: str,
        password: str | None,
        target_folder_id: str,
    ) -> list[FileRef]:
        """把百度分享链接里的文件转存到目标目录（target_folder_id 为绝对路径）。"""

        self._ensure_token()
        surl = _share_surl(share_url)
        if not surl:
            raise ShareLinkInvalidError("无法从链接里解析出百度分享标识")

        sekey = ""
        if password:
            verified = self._request(
                "POST",
                f"{PAN_BASE}/share/verify",
                params={
                    **self._common_params(),
                    "surl": surl,
                    "t": str(int(time.time() * 1000)),
                },
                data={"pwd": password, "vcode": "", "vcode_str": ""},
            )
            sekey = _as_text(verified.get("randsk"))

        share_meta = self._fetch_share_page(surl)
        uk, share_id = share_meta
        if not uk or not share_id:
            raise ShareLinkInvalidError("分享页面解析失败，链接可能已失效")

        listed = self._api(
            "/share/list",
            params={
                "uk": uk,
                "shareid": share_id,
                "order": "other",
                "desc": "1",
                "showempty": "0",
                "page": "1",
                "num": str(LIST_PAGE_LIMIT),
                "dir": "/",
                "t": str(int(time.time() * 1000)),
            },
        )
        items = listed.get("list")
        file_ids = [
            _as_text(item.get("fs_id"))
            for item in (items if isinstance(items, list) else [])
            if isinstance(item, dict) and item.get("isdir") != 1
        ]
        file_ids = [item for item in file_ids if item]
        if not file_ids:
            raise ShareLinkInvalidError("分享里没有可转存的文件")

        transfer_params: dict[str, Any] = {
            **self._common_params(),
            "shareid": share_id,
            "from": uk,
            "ondup": "newcopy",
        }
        if sekey:
            transfer_params["sekey"] = sekey
        transferred = self._request(
            "POST",
            f"{PAN_BASE}/share/transfer",
            params=transfer_params,
            data={
                "fsidlist": json.dumps([int(item) for item in file_ids]),
                "path": target_folder_id,
            },
        )
        infos = transferred.get("info")
        refs: list[FileRef] = []
        for item in infos if isinstance(infos, list) else []:
            if not isinstance(item, dict):
                continue
            refs.append(
                FileRef(
                    file_id=_as_text(item.get("fs_id")),
                    name=_as_text(item.get("server_filename"))
                    or Path(_as_text(item.get("path"))).name,
                    path=_as_text(item.get("path")),
                    size_bytes=_as_int(item.get("size")),
                    parent_id=target_folder_id,
                )
            )
        if not refs:
            raise ShareLinkInvalidError("转存没有返回文件信息")
        return refs

    def _fetch_share_page(self, surl: str) -> tuple[str, str]:
        """访问分享页并解析 uk 与 shareid。"""

        headers = {"Cookie": self._credential.cookie_header()}
        try:
            response = self._client().request(
                "GET",
                f"{PAN_BASE}/s/{surl}",
                headers=headers,
                follow_redirects=True,
            )
        except httpx.HTTPError as error:
            raise ShareLinkInvalidError(f"无法打开分享页面：{error}") from error
        html = response.text or ""
        uk_match = re.search(r'"uk"\s*:\s*"?(\d+)"?', html)
        id_match = re.search(r'"shareid"\s*:\s*"?(\d+)"?', html)
        return (
            uk_match.group(1) if uk_match else "",
            id_match.group(1) if id_match else "",
        )

    # ---------------------------------------------------------------- 上传

    def upload_file(
        self,
        local_path: Path,
        target_folder_id: str,
        name: str | None = None,
    ) -> FileRef:
        """分片上传：precreate → superfile2 → create。"""

        path = Path(local_path)
        file_name = name or path.name
        remote_path = f"{target_folder_id.rstrip('/')}/{file_name}"
        size_bytes = path.stat().st_size
        block_list = _block_md5_list(path)
        self._ensure_token()
        if not self._credential.access_token:
            raise CredentialInvalidError(
                "百度网盘上传需要开放平台应用的 access_token，"
                "请把它和 BDUSS 一起粘贴",
            )

        precreated = self._request(
            "POST",
            f"{PAN_BASE}/api/precreate",
            params=self._common_params(),
            data={
                "path": remote_path,
                "size": str(size_bytes),
                "isdir": "0",
                "block_list": json.dumps(block_list),
                "rtype": "3",
            },
        )
        upload_id = _as_text(precreated.get("uploadid"))
        if not upload_id:
            raise CloudDriveError("百度网盘未返回上传会话")

        with path.open("rb") as handle:
            index = 0
            while True:
                chunk = handle.read(UPLOAD_PART_BYTES)
                if not chunk and index > 0:
                    break
                self._upload_part(remote_path, upload_id, index, chunk, file_name)
                index += 1
                if len(chunk) < UPLOAD_PART_BYTES:
                    break

        created = self._request(
            "POST",
            f"{PAN_BASE}/api/create",
            params={**self._common_params(), "a": "commit"},
            data={
                "path": remote_path,
                "size": str(size_bytes),
                "isdir": "0",
                "block_list": json.dumps(block_list),
                "uploadid": upload_id,
                "rtype": "3",
            },
        )
        file_id = _as_text(created.get("fs_id"))
        meta = self.get_file_meta_by_path(remote_path)
        return FileRef(
            file_id=file_id or meta.file_id,
            name=meta.name or file_name,
            path=meta.path or remote_path,
            size_bytes=meta.size_bytes if meta.size_bytes is not None else size_bytes,
            parent_id=target_folder_id,
        )

    def _upload_part(
        self,
        remote_path: str,
        upload_id: str,
        part_index: int,
        chunk: bytes,
        file_name: str,
    ) -> None:
        self._request(
            "POST",
            f"{PCS_BASE}/rest/2.0/pcs/superfile2",
            params={
                "method": "upload",
                "access_token": self._credential.access_token,
                "type": "tmpfile",
                "path": remote_path,
                "uploadid": upload_id,
                "partseq": str(part_index),
            },
            files={"file": (file_name, chunk, "application/octet-stream")},
        )


# --------------------------------------------------------------------- 工具


def _share_surl(share_url: str) -> str:
    """从分享链接里取出 surl（/s/1xxxx 里的 1xxxx）。"""

    cleaned = (share_url or "").strip()
    if not cleaned:
        return ""
    parsed = urlsplit(cleaned)
    query = parse_qs(parsed.query)
    if query.get("surl"):
        return query["surl"][0].lstrip("/")
    path = parsed.path or cleaned
    marker = "/s/"
    if marker in path:
        return path.split(marker, 1)[1].split("/", 1)[0].strip()
    return ""


def _block_md5_list(path: Path) -> list[str]:
    """按 4MB 分块计算 MD5，供秒传与完整性校验使用。"""

    blocks: list[str] = []
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(UPLOAD_PART_BYTES)
            if not chunk:
                break
            blocks.append(hashlib.md5(chunk).hexdigest())
    return blocks


def _map_errno(errno: int, errmsg: str) -> CloudDriveError:
    """把百度 errno 映射成统一异常。"""

    if errno in SHARE_ERROR_CODES:
        return ShareLinkInvalidError(errmsg or "分享链接失效或提取码错误")
    if errno in QUOTA_ERROR_CODES:
        return QuotaExceededError(errmsg or "百度网盘空间不足")
    if errno in RATE_LIMIT_ERROR_CODES:
        return RateLimitedError(errmsg or "百度网盘限流，请稍后重试")
    if errno in CREDENTIAL_ERROR_CODES:
        return CredentialInvalidError(errmsg or "百度网盘凭据已失效，请重新粘贴")
    return CloudDriveError(errmsg or f"百度网盘接口返回错误（errno={errno}）")


def _as_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, int):
        return str(value)
    return ""


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_cookie_string(text: str) -> dict[str, str]:
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
