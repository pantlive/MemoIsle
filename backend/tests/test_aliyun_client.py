"""阿里云盘 OpenAPI 客户端测试（假 HTTP，不发真实请求）。"""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path
from typing import Any

import pytest
from app.cloud_drive.aliyun import AliyunDriveClient, parse_aliyun_credential
from app.cloud_drive.base import (
    CloudDriveError,
    CredentialInvalidError,
    QuotaExceededError,
    RateLimitedError,
    ShareLinkInvalidError,
)

CREDENTIAL = '{"access_token": "access-token-1234"}'


class FakeResponse:
    """最小化的 httpx.Response 替身。"""

    def __init__(self, status_code: int = 200, payload: Any = None) -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self) -> Any:
        return self._payload


class FakeAliyunHttp:
    """按 URL 片段路由的假客户端，记录每次调用。"""

    def __init__(self, routes: dict[str, Any]) -> None:
        self._routes = routes
        self.calls: list[tuple[str, str, dict[str, Any] | None, bytes | None]] = []

    def post(
        self,
        url: str,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> FakeResponse:
        self.calls.append(("POST", url, json, None))
        return self._resolve(url, json)

    def put(
        self,
        url: str,
        content: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> FakeResponse:
        self.calls.append(("PUT", url, None, content))
        return self._resolve(url, None)

    def _resolve(self, url: str, body: dict[str, Any] | None) -> FakeResponse:
        for fragment, handler in self._routes.items():
            if fragment in url:
                return handler(body) if callable(handler) else handler
        raise AssertionError(f"未预期的请求地址：{url}")

    def bodies_for(self, fragment: str) -> list[dict[str, Any]]:
        return [
            body or {}
            for _method, url, body, _content in self.calls
            if fragment in url
        ]


def drive_info(payload: dict[str, Any] | None = None) -> FakeResponse:
    return FakeResponse(200, payload or {"default_drive_id": "drive-1", "name": "阿盘"})


def test_parse_credential_variants() -> None:
    """JSON、纯 token 与 cookie 串都能解析。"""

    refresh = parse_aliyun_credential(
        '{"refresh_token": "r1", "client_id": "c1", "client_secret": "s1"}'
    )
    assert refresh.has_refresh_path is True

    plain = parse_aliyun_credential("just-a-token")
    assert plain.refresh_token == "just-a-token"
    assert plain.has_refresh_path is False

    cookie = parse_aliyun_credential("foo=1; refresh_token=cookie-token; bar=2")
    assert cookie.refresh_token == "cookie-token"


def test_empty_credential_is_rejected() -> None:
    """空凭据直接失败，不发请求。"""

    with pytest.raises(CredentialInvalidError):
        AliyunDriveClient("   ").check_credential()


def test_check_credential_reads_drive_and_name() -> None:
    """校验凭据时记录默认云盘并返回昵称。"""

    http = FakeAliyunHttp({"getDriveInfo": drive_info()})
    client = AliyunDriveClient(CREDENTIAL, http_client=http)

    info = client.check_credential()

    assert info.display_name == "阿盘"
    assert info.provider == "aliyun"
    assert client._drive_id == "drive-1"


def test_check_credential_maps_unauthorized() -> None:
    """401 映射为凭据失效。"""

    http = FakeAliyunHttp({"getDriveInfo": FakeResponse(401, {"code": "TokenExpired"})})
    with pytest.raises(CredentialInvalidError):
        AliyunDriveClient(CREDENTIAL, http_client=http).check_credential()


def test_ensure_folder_reuses_and_creates(tmp_path: Path) -> None:
    """已有目录复用，缺失目录逐级创建。"""

    def list_handler(body: dict[str, Any] | None) -> FakeResponse:
        parent = (body or {}).get("parent_file_id")
        if parent == "root":
            return FakeResponse(
                200,
                {
                    "items": [
                        {"file_id": "f-books", "name": "MemoIsle", "type": "folder"},
                        {"file_id": "f-other", "name": "其他", "type": "folder"},
                    ]
                },
            )
        return FakeResponse(200, {"items": []})

    http = FakeAliyunHttp(
        {
            "getDriveInfo": drive_info(),
            "openFile/list": list_handler,
            "openFile/create": FakeResponse(200, {"file_id": "f-ebooks"}),
        }
    )
    client = AliyunDriveClient(CREDENTIAL, http_client=http)

    folder_id = client.ensure_folder("/MemoIsle/电子书")

    assert folder_id == "f-ebooks"
    creates = http.bodies_for("openFile/create")
    assert len(creates) == 1
    assert creates[0]["name"] == "电子书"
    assert creates[0]["parent_file_id"] == "f-books"
    assert creates[0]["type"] == "folder"


def test_upload_file_uploads_parts_and_completes(tmp_path: Path) -> None:
    """普通上传：创建 → 分片上传 → 完成 → 读取元数据。"""

    source = tmp_path / "rust.epub"
    payload = b"book-bytes"
    source.write_bytes(payload)

    http = FakeAliyunHttp(
        {
            "getDriveInfo": drive_info(),
            "openFile/create": FakeResponse(
                200,
                {
                    "file_id": "f-file",
                    "upload_id": "upload-1",
                    "rapid_upload": False,
                    "part_info_list": [
                        {"part_number": 1, "upload_url": "https://upload.example/part1"}
                    ],
                },
            ),
            "openFile/complete": FakeResponse(200, {}),
            "upload.example": FakeResponse(200, {}),
            "openFile/get": FakeResponse(
                200,
                {
                    "file_id": "f-file",
                    "name": "rust.epub",
                    "path": "/MemoIsle/电子书/rust.epub",
                    "size": len(payload),
                    "content_hash": "hash-1",
                },
            ),
        }
    )
    client = AliyunDriveClient(CREDENTIAL, http_client=http)

    ref = client.upload_file(source, "f-folder", "rust.epub")

    assert ref.file_id == "f-file"
    assert ref.path == "/MemoIsle/电子书/rust.epub"
    assert ref.size_bytes == len(payload)

    create_body = http.bodies_for("openFile/create")[0]
    assert create_body["parent_file_id"] == "f-folder"
    assert create_body["size"] == len(payload)
    assert create_body["part_info_list"] == [{"part_number": 1}]
    expected_proof = base64.b64encode(hashlib.sha1(payload[:1024]).digest()).decode()
    assert create_body["proof_code"] == expected_proof
    assert create_body["proof_version"] == "v1"

    puts = [call for call in http.calls if call[0] == "PUT"]
    assert len(puts) == 1
    assert puts[0][1] == "https://upload.example/part1"
    assert puts[0][3] == payload
    assert len(http.bodies_for("openFile/complete")) == 1


def test_upload_file_skips_transfer_on_rapid_upload(tmp_path: Path) -> None:
    """秒传命中时不发分片、不调用 complete。"""

    source = tmp_path / "dup.epub"
    source.write_bytes(b"same-bytes")

    http = FakeAliyunHttp(
        {
            "getDriveInfo": drive_info(),
            "openFile/create": FakeResponse(
                200,
                {"file_id": "f-dup", "rapid_upload": True},
            ),
            "openFile/get": FakeResponse(
                200,
                {
                    "file_id": "f-dup",
                    "name": "dup.epub",
                    "path": "/MemoIsle/电子书/dup.epub",
                    "size": 10,
                },
            ),
        }
    )
    client = AliyunDriveClient(CREDENTIAL, http_client=http)

    ref = client.upload_file(source, "f-folder", "dup.epub")

    assert ref.file_id == "f-dup"
    assert [call for call in http.calls if call[0] == "PUT"] == []
    assert http.bodies_for("openFile/complete") == []


def test_transfer_share_copies_files() -> None:
    """分享链接先换令牌，再列出文件并逐个转存。"""

    http = FakeAliyunHttp(
        {
            "getDriveInfo": drive_info(),
            "getShareToken": FakeResponse(200, {"share_token": "st-1"}),
            "openFile/list": FakeResponse(
                200,
                {
                    "items": [
                        {"file_id": "s-1", "name": "a.epub", "type": "file", "size": 7},
                        {"file_id": "s-dir", "name": "目录", "type": "folder"},
                    ]
                },
            ),
            "openFile/copy": FakeResponse(
                200,
                {
                    "file_id": "f-copied",
                    "name": "a.epub",
                    "path": "/MemoIsle/电子书/a.epub",
                    "size": 7,
                },
            ),
        }
    )
    client = AliyunDriveClient(CREDENTIAL, http_client=http)

    refs = client.transfer_share(
        "https://www.alipan.com/s/abc123?pwd=xyz",
        None,
        "f-folder",
    )

    assert [ref.file_id for ref in refs] == ["f-copied"]
    assert refs[0].path == "/MemoIsle/电子书/a.epub"

    token_body = http.bodies_for("getShareToken")[0]
    assert token_body["share_id"] == "abc123"

    copy_body = http.bodies_for("openFile/copy")[0]
    assert copy_body["to_parent_file_id"] == "f-folder"
    assert copy_body["share_token"] == "st-1"
    assert copy_body["file_id"] == "s-1"


def test_transfer_share_requires_files() -> None:
    """分享里没有文件时给出明确错误。"""

    http = FakeAliyunHttp(
        {
            "getDriveInfo": drive_info(),
            "getShareToken": FakeResponse(200, {"share_token": "st-1"}),
            "openFile/list": FakeResponse(200, {"items": []}),
        }
    )
    with pytest.raises(ShareLinkInvalidError):
        AliyunDriveClient(CREDENTIAL, http_client=http).transfer_share(
            "https://www.alipan.com/s/empty",
            None,
            "f-folder",
        )


def test_error_mapping_rate_limit_and_quota() -> None:
    """限流与空间不足映射成对应异常。"""

    limited = FakeAliyunHttp(
        {"getDriveInfo": FakeResponse(429, {"code": "TooManyRequests"})}
    )
    with pytest.raises(RateLimitedError):
        AliyunDriveClient(CREDENTIAL, http_client=limited).check_credential()

    full = FakeAliyunHttp(
        {"getDriveInfo": FakeResponse(200, {"default_drive_id": "d"})}
    )
    full._routes["openFile/create"] = FakeResponse(200, {"file_id": "f"})
    client = AliyunDriveClient(CREDENTIAL, http_client=full)
    client._drive_id = "d"

    failing = FakeAliyunHttp(
        {"openFile/create": FakeResponse(403, {"code": "QuotaExhausted"})}
    )
    failing_client = AliyunDriveClient(CREDENTIAL, http_client=failing)
    failing_client._drive_id = "d"

    with pytest.raises(QuotaExceededError):
        failing_client._create_folder("root", "新目录")


def test_missing_drive_id_is_reported() -> None:
    """接口没返回云盘 ID 时判定凭据不可用。"""

    http = FakeAliyunHttp({"getDriveInfo": FakeResponse(200, {"name": "阿盘"})})
    with pytest.raises(CredentialInvalidError):
        AliyunDriveClient(CREDENTIAL, http_client=http).check_credential()


def test_http_failure_maps_to_cloud_error() -> None:
    """网络异常映射为云盘错误而不是抛出底层异常。"""

    class BrokenHttp(FakeAliyunHttp):
        def post(self, url: str, json: Any = None, headers: Any = None):
            import httpx

            raise httpx.ConnectError("boom")

    client = AliyunDriveClient(CREDENTIAL, http_client=BrokenHttp({}))
    with pytest.raises(CloudDriveError):
        client.check_credential()
