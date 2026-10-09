"""百度网盘客户端测试（假 HTTP，不发真实请求）。"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
from app.cloud_drive.baidu import BaiduPanClient, parse_baidu_credential
from app.cloud_drive.base import (
    CredentialInvalidError,
    QuotaExceededError,
    RateLimitedError,
    ShareLinkInvalidError,
)

COOKIE = '{"bduss": "bduss-value", "stoken": "stoken-value", "access_token": "at-1"}'
SHARE_PAGE = (
    '<html><script>var yunData = {"shareid":123456,"uk":987654,'
    '"share_uk":"987654"};</script></html>'
)


class FakeResponse:
    """最小化的 httpx.Response 替身。"""

    def __init__(
        self,
        status_code: int = 200,
        payload: Any = None,
        text: str = "",
    ) -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text

    def json(self) -> Any:
        return self._payload


class FakeBaiduHttp:
    """按 URL 片段路由的假客户端。"""

    def __init__(self, routes: dict[str, Any]) -> None:
        self._routes = routes
        self.calls: list[dict[str, Any]] = []

    def request(
        self,
        method: str,
        url: str,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        **_extra: Any,
    ) -> FakeResponse:
        call = {
            "method": method,
            "url": url,
            "params": params or {},
            "data": data or {},
            "files": files,
            "headers": headers or {},
        }
        self.calls.append(call)
        for fragment, handler in self._routes.items():
            if fragment in url:
                return handler(call) if callable(handler) else handler
        raise AssertionError(f"未预期的请求地址：{url}")

    def calls_to(self, fragment: str) -> list[dict[str, Any]]:
        return [call for call in self.calls if fragment in call["url"]]


def quota(payload: dict[str, Any] | None = None) -> FakeResponse:
    return FakeResponse(
        200,
        payload or {"errno": 0, "netdisk_name": "我的网盘", "uk": 987654},
    )


def test_parse_credential_variants() -> None:
    """JSON、cookie 串与纯 BDUSS 都能解析。"""

    loaded = parse_baidu_credential(COOKIE)
    assert (loaded.bduss, loaded.stoken, loaded.access_token) == (
        "bduss-value",
        "stoken-value",
        "at-1",
    )

    cookie = parse_baidu_credential("BDUSS=abc; STOKEN=def; other=1")
    assert (cookie.bduss, cookie.stoken) == ("abc", "def")

    plain = parse_baidu_credential("plain-bduss")
    assert plain.bduss == "plain-bduss"


def test_missing_bduss_is_rejected() -> None:
    """没有 BDUSS 时直接失败，不发请求。"""

    with pytest.raises(CredentialInvalidError):
        BaiduPanClient("{}").check_credential()


def test_check_credential_reads_name_and_token() -> None:
    """校验时读取昵称并缓存 bdstoken。"""

    http = FakeBaiduHttp(
        {
            "/api/quota": quota(),
            "/api/gettemplatevariable": FakeResponse(
                200,
                {"errno": 0, "result": {"bdstoken": "token-1"}},
            ),
        }
    )
    client = BaiduPanClient(COOKIE, http_client=http)

    info = client.check_credential()

    assert info.display_name == "我的网盘"
    assert client._bdstoken == "token-1"
    assert client._uk == "987654"
    quota_call = http.calls_to("/api/quota")[0]
    assert "BDUSS=bduss-value" in quota_call["headers"]["Cookie"]


def test_error_mapping() -> None:
    """errno 映射到对应异常类型。"""

    cases = [
        (-6, CredentialInvalidError),
        (-10, QuotaExceededError),
        (-8, RateLimitedError),
    ]
    for errno, expected in cases:
        http = FakeBaiduHttp(
            {"/api/quota": FakeResponse(200, {"errno": errno, "errmsg": "x"})}
        )
        with pytest.raises(expected):
            BaiduPanClient(COOKIE, http_client=http).check_credential()


def test_ensure_folder_reuses_and_creates() -> None:
    """已有目录复用，缺失目录用 bdstoken 创建。"""

    def list_handler(call: dict[str, Any]) -> FakeResponse:
        directory = call["params"].get("dir")
        if directory == "/":
            return FakeResponse(
                200,
                {
                    "errno": 0,
                    "list": [
                        {
                            "fs_id": 1,
                            "path": "/MemoIsle",
                            "server_filename": "MemoIsle",
                            "isdir": 1,
                        }
                    ],
                },
            )
        return FakeResponse(200, {"errno": 0, "list": []})

    http = FakeBaiduHttp(
        {
            "/api/quota": quota(),
            "/api/gettemplatevariable": FakeResponse(
                200,
                {"errno": 0, "result": {"bdstoken": "token-1"}},
            ),
            "/api/list": list_handler,
            "/api/create": FakeResponse(200, {"errno": 0, "fs_id": 2}),
        }
    )
    client = BaiduPanClient(COOKIE, http_client=http)

    path = client.ensure_folder("/MemoIsle/电子书")

    assert path == "/MemoIsle/电子书"
    creates = http.calls_to("/api/create")
    assert len(creates) == 1
    assert creates[0]["data"]["path"] == "/MemoIsle/电子书"
    assert creates[0]["data"]["isdir"] == "1"
    assert creates[0]["params"]["bdstoken"] == "token-1"


def test_transfer_share_verifies_and_copies() -> None:
    """分享转存：校验提取码 → 解析分享页 → 列出 → 转存。"""

    def share_list(call: dict[str, Any]) -> FakeResponse:
        assert call["params"]["shareid"] == "123456"
        assert call["params"]["uk"] == "987654"
        return FakeResponse(
            200,
            {
                "errno": 0,
                "list": [
                    {"fs_id": 11, "server_filename": "a.epub", "isdir": 0},
                    {"fs_id": 12, "server_filename": "目录", "isdir": 1},
                ],
            },
        )

    http = FakeBaiduHttp(
        {
            "/api/quota": quota(),
            "/api/gettemplatevariable": FakeResponse(
                200,
                {"errno": 0, "result": {"bdstoken": "token-1"}},
            ),
            "/share/verify": FakeResponse(200, {"errno": 0, "randsk": "sekey-1"}),
            "/s/": FakeResponse(200, {}, text=SHARE_PAGE),
            "/share/list": share_list,
            "/share/transfer": FakeResponse(
                200,
                {
                    "errno": 0,
                    "info": [
                        {
                            "fs_id": 21,
                            "path": "/MemoIsle/电子书/a.epub",
                            "server_filename": "a.epub",
                            "size": 10,
                        }
                    ],
                },
            ),
        }
    )
    client = BaiduPanClient(COOKIE, http_client=http)

    refs = client.transfer_share(
        "https://pan.baidu.com/s/1abcdEF?pwd=xyz1",
        "xyz1",
        "/MemoIsle/电子书",
    )

    assert [ref.file_id for ref in refs] == ["21"]
    assert refs[0].path == "/MemoIsle/电子书/a.epub"

    verify_call = http.calls_to("/share/verify")[0]
    assert verify_call["params"]["surl"] == "1abcdEF"
    assert verify_call["data"]["pwd"] == "xyz1"

    transfer_call = http.calls_to("/share/transfer")[0]
    assert transfer_call["data"]["fsidlist"] == "[11]"
    assert transfer_call["data"]["path"] == "/MemoIsle/电子书"
    assert transfer_call["params"]["sekey"] == "sekey-1"


def test_transfer_share_requires_files() -> None:
    """分享里没有文件时给出明确错误。"""

    http = FakeBaiduHttp(
        {
            "/api/quota": quota(),
            "/api/gettemplatevariable": FakeResponse(
                200,
                {"errno": 0, "result": {"bdstoken": "token-1"}},
            ),
            "/s/": FakeResponse(200, {}, text=SHARE_PAGE),
            "/share/list": FakeResponse(200, {"errno": 0, "list": []}),
        }
    )
    with pytest.raises(ShareLinkInvalidError):
        BaiduPanClient(COOKIE, http_client=http).transfer_share(
            "https://pan.baidu.com/s/1empty",
            None,
            "/MemoIsle/电子书",
        )


def test_upload_requires_access_token(tmp_path: Path) -> None:
    """只给 cookie 时上传给出明确错误，而不是静默失败。"""

    source = tmp_path / "a.epub"
    source.write_bytes(b"book")

    http = FakeBaiduHttp(
        {
            "/api/quota": quota(),
            "/api/gettemplatevariable": FakeResponse(
                200,
                {"errno": 0, "result": {"bdstoken": "token-1"}},
            ),
        }
    )
    client = BaiduPanClient('{"bduss": "b"}', http_client=http)

    with pytest.raises(CredentialInvalidError) as error:
        client.upload_file(source, "/MemoIsle/电子书", "a.epub")
    assert "access_token" in str(error.value)


def test_upload_file_precreates_uploads_and_commits(tmp_path: Path) -> None:
    """上传：precreate → superfile2 → create → 回读元数据。"""

    source = tmp_path / "a.epub"
    payload = b"book-bytes"
    source.write_bytes(payload)
    expected_block = hashlib.md5(payload).hexdigest()

    http = FakeBaiduHttp(
        {
            "/api/quota": quota(),
            "/api/gettemplatevariable": FakeResponse(
                200,
                {"errno": 0, "result": {"bdstoken": "token-1"}},
            ),
            "/api/precreate": FakeResponse(200, {"errno": 0, "uploadid": "up-1"}),
            "superfile2": FakeResponse(200, {"errno": 0}),
            "/api/create": FakeResponse(200, {"errno": 0, "fs_id": 33}),
            "/api/filemetas": FakeResponse(
                200,
                {
                    "errno": 0,
                    "info": [
                        {
                            "fs_id": 33,
                            "path": "/MemoIsle/电子书/a.epub",
                            "server_filename": "a.epub",
                            "size": len(payload),
                            "md5": expected_block,
                        }
                    ],
                },
            ),
        }
    )
    client = BaiduPanClient(COOKIE, http_client=http)

    ref = client.upload_file(source, "/MemoIsle/电子书", "a.epub")

    assert ref.file_id == "33"
    assert ref.path == "/MemoIsle/电子书/a.epub"
    assert ref.size_bytes == len(payload)

    precreate = http.calls_to("/api/precreate")[0]
    assert precreate["data"]["path"] == "/MemoIsle/电子书/a.epub"
    assert precreate["data"]["size"] == str(len(payload))
    assert json_blocks(precreate["data"]["block_list"]) == [expected_block]

    parts = http.calls_to("superfile2")
    assert len(parts) == 1
    assert parts[0]["params"]["partseq"] == "0"
    assert parts[0]["params"]["uploadid"] == "up-1"
    assert parts[0]["files"]["file"][1] == payload

    commit = http.calls_to("/api/create")[0]
    assert commit["data"]["uploadid"] == "up-1"
    assert json_blocks(commit["data"]["block_list"]) == [expected_block]


def json_blocks(value: Any) -> list[str]:
    import json

    loaded = json.loads(value)
    assert isinstance(loaded, list)
    return loaded
