"""电子书任务 API 测试。"""

from __future__ import annotations

from app import cloud_account_service
from app.cloud_drive.base import AccountInfo
from app.config import Settings
from fastapi.testclient import TestClient


def _bind_aliyun(
    client: TestClient,
    monkeypatch,
) -> str:
    """通过接口绑定一个阿里云盘账号，返回账号 id。"""

    def fake_verify(
        provider: str,
        credential: str,
        *,
        settings: Settings,
        http_client: object | None = None,
    ) -> AccountInfo:
        return AccountInfo(provider=provider, display_name="测试云盘")

    monkeypatch.setattr(cloud_account_service, "verify_credential", fake_verify)
    response = client.post(
        "/api/v1/cloud-accounts",
        json={"provider": "aliyun", "credential": '{"access_token": "t"}'},
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_ebooks_api_requires_bound_cloud_account(
    client: TestClient,
    monkeypatch,
) -> None:
    """没有绑定云盘时提交电子书链接会被拒绝。"""

    monkeypatch.setattr(
        "app.api.process_ebook_job_in_background",
        lambda *args, **kwargs: None,
    )
    response = client.post(
        "/api/v1/ebooks/jobs",
        json={"url": "https://example.com/books/a.epub"},
    )
    assert response.status_code == 422
    assert "云盘" in response.json()["detail"]


def test_ebooks_api_submit_list_and_retry(
    client: TestClient,
    monkeypatch,
) -> None:
    """提交任务、列出任务、查询单个任务与重试的完整流程。"""

    account_id = _bind_aliyun(client, monkeypatch)
    assert account_id
    monkeypatch.setattr(
        "app.api.process_ebook_job_in_background",
        lambda *args, **kwargs: None,
    )

    created = client.post(
        "/api/v1/ebooks/jobs",
        json={
            "url": "https://example.com/books/rust.epub",
            "tags": ["编程"],
            "collections": ["技术书"],
            "note": "同事推荐",
        },
    )
    assert created.status_code == 201
    job = created.json()
    assert job["mode"] == "upload"
    assert job["provider"] == "aliyun"
    assert job["status"] == "pending"
    assert job["progress"] == 0
    assert job["target_folder"] == "/MemoIsle/电子书"

    listing = client.get("/api/v1/ebooks/jobs")
    assert listing.status_code == 200
    assert [item["id"] for item in listing.json()] == [job["id"]]

    single = client.get(f"/api/v1/ebooks/jobs/{job['id']}")
    assert single.status_code == 200
    assert single.json()["id"] == job["id"]

    retried = client.post(f"/api/v1/ebooks/jobs/{job['id']}/retry")
    # 排队中的任务不允许重试，否则同一本书会被上传两次。
    assert retried.status_code == 409

    missing = client.get(
        "/api/v1/ebooks/jobs/00000000-0000-0000-0000-0000000000aa",
    )
    assert missing.status_code == 404


def test_ebooks_api_classifies_share_link(
    client: TestClient,
    monkeypatch,
) -> None:
    """云盘分享链接被识别为转存模式，并保留提取码。"""

    _bind_aliyun(client, monkeypatch)
    monkeypatch.setattr(
        "app.api.process_ebook_job_in_background",
        lambda *args, **kwargs: None,
    )

    created = client.post(
        "/api/v1/ebooks/jobs",
        json={"url": "https://pan.baidu.com/s/1xyz?pwd=abcd", "provider": "aliyun"},
    )
    assert created.status_code == 201
    job = created.json()
    assert job["provider"] == "aliyun"
    assert job["mode"] == "transfer"


def test_ebooks_api_rejects_unsupported_link(
    client: TestClient,
    monkeypatch,
) -> None:
    """非 http(s) 链接被拒绝。"""

    _bind_aliyun(client, monkeypatch)
    response = client.post(
        "/api/v1/ebooks/jobs",
        json={"url": "ftp://example.com/book.epub"},
    )
    assert response.status_code == 422


def test_ebook_memo_exposes_cloud_reference(
    client: TestClient,
    monkeypatch,
) -> None:
    """任务跑通后，资料接口要返回云盘引用与快照，客户端才看得到存到哪了。"""

    from app.cloud_drive.aliyun import AliyunDriveClient

    from tests.test_aliyun_client import FakeAliyunHttp, FakeResponse, drive_info

    _bind_aliyun(client, monkeypatch)

    def list_handler(body: dict | None) -> FakeResponse:
        parent = (body or {}).get("parent_file_id")
        if parent == "root" and "share_token" not in (body or {}):
            return FakeResponse(
                200,
                {
                    "items": [
                        {"file_id": "f-books", "name": "MemoIsle", "type": "folder"},
                    ]
                },
            )
        if parent == "f-books":
            return FakeResponse(200, {"items": []})
        return FakeResponse(
            200,
            {"items": [{"file_id": "s-1", "name": "重构.epub", "type": "file"}]},
        )

    http = FakeAliyunHttp(
        {
            "getDriveInfo": drive_info(),
            "openFile/list": list_handler,
            "openFile/create": FakeResponse(200, {"file_id": "f-ebooks"}),
            "getShareToken": FakeResponse(200, {"share_token": "st-1"}),
            "openFile/copy": FakeResponse(
                200,
                {
                    "file_id": "f-copied",
                    "name": "重构.epub",
                    "path": "/MemoIsle/电子书/重构.epub",
                    "size": 3072,
                },
            ),
            "openFile/get": FakeResponse(
                200,
                {
                    "file_id": "f-copied",
                    "name": "重构.epub",
                    "path": "/MemoIsle/电子书/重构.epub",
                    "size": 3072,
                    "content_hash": "hash-refactor",
                },
            ),
        }
    )
    monkeypatch.setattr(
        "app.ebook_service.build_cloud_client",
        lambda provider, credential, **_: AliyunDriveClient(
            credential,
            http_client=http,
        ),
    )

    created = client.post(
        "/api/v1/ebooks/jobs",
        json={"url": "https://www.alipan.com/s/abc123", "tags": ["工程"]},
    )
    assert created.status_code == 201
    job_id = created.json()["id"]

    job = client.get(f"/api/v1/ebooks/jobs/{job_id}").json()
    assert job["status"] == "success", job["error"]
    assert job["cloud_path"] == "/MemoIsle/电子书/重构.epub"

    memos = client.get("/api/v1/memos", params={"type": "resource"}).json()["items"]
    assert len(memos) == 1
    memo = memos[0]
    assert memo["id"] == job["memo_id"]
    assert memo["ebook_provider"] == "aliyun"
    assert memo["ebook_file_id"] == "f-copied"
    assert memo["ebook_path"] == "/MemoIsle/电子书/重构.epub"
    assert memo["ebook_format"] == "epub"
    assert memo["ebook_size_bytes"] == 3072
    assert memo["ebook_snapshot"]["content_hash"] == "hash-refactor"
    assert memo["tags"] == ["工程"]
    assert memo["resource_kind"] == "book"
    # 电子书不参与网页巡检。
    assert memo["link_next_check_at"] is None
