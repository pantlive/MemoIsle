"""电子书流水线与真实阿里云盘客户端的衔接测试。

这里不使用云盘替身：注入的是真实的 AliyunDriveClient，只把最底层的 HTTP
换成假客户端，因此服务层与适配层之间的参数、返回值假设都会被真实执行到。
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from app import ebook_service
from app.cloud_account_service import encrypt_credential
from app.cloud_drive.aliyun import AliyunDriveClient
from app.config import Settings
from app.database import Database
from app.ebook_service import create_ebook_job, run_ebook_job
from app.models import CloudAccount, Memo
from app.schemas import MemoType, ResourceKind, ResourceProcessStatus
from sqlalchemy import select

from tests.test_aliyun_client import FakeAliyunHttp, FakeResponse, drive_info
from tests.test_ebook_service import (
    FakeDownloadClient,
    FakeDownloadResponse,
    public_resolver,
)

CREDENTIAL = '{"access_token": "access-token-1234"}'


@pytest.fixture
def session_settings(tmp_path: Path) -> Iterator[tuple[object, Settings]]:
    """独立数据库会话与配置，并预置一个已绑定云盘。"""

    settings = Settings(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'pipeline.db'}",
        cors_origins=("http://localhost:5173",),
        local_user_id="00000000-0000-0000-0000-000000000001",
        auth_dev_mode=True,
        auth_token_secret="test-secret",
        audio_directory=tmp_path / "audio",
        image_directory=tmp_path / "images",
        resource_enrichment_enabled=False,
        resource_health_monitor_enabled=False,
        word_dictionary_enabled=False,
        ebook_max_bytes=1024,
    )
    database = Database(settings.database_url)
    database.create_schema()
    with database.session_factory() as session:
        session.add(
            CloudAccount(
                id=str(uuid4()),
                user_id=settings.local_user_id,
                provider="aliyun",
                display_name="测试云盘",
                credential_cipher=encrypt_credential(settings, CREDENTIAL),
                credential_hint="...1234",
                default_folder="/MemoIsle/电子书",
                status="active",
            )
        )
        session.commit()
        yield session, settings
    database.dispose()


def _use_real_client(monkeypatch: pytest.MonkeyPatch, http: FakeAliyunHttp) -> None:
    """让服务层构建真实的阿里云盘客户端，但底层 HTTP 走假客户端。"""

    monkeypatch.setattr(
        ebook_service,
        "build_cloud_client",
        lambda provider, credential, **_: AliyunDriveClient(
            credential,
            http_client=http,
        ),
    )


def test_share_link_pipeline_uses_real_client(
    session_settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """分享链接：真实客户端走 建目录 → 换令牌 → 转存 → 回读元数据，最终落库 Memo。"""

    session, settings = session_settings

    def list_handler(body: dict[str, object] | None) -> FakeResponse:
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
            {
                "items": [
                    {
                        "file_id": "s-1",
                        "name": "深入理解计算机系统.epub",
                        "type": "file",
                    },
                ]
            },
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
                    "name": "深入理解计算机系统.epub",
                    "path": "/MemoIsle/电子书/深入理解计算机系统.epub",
                    "size": 4096,
                },
            ),
            "openFile/get": FakeResponse(
                200,
                {
                    "file_id": "f-copied",
                    "name": "深入理解计算机系统.epub",
                    "path": "/MemoIsle/电子书/深入理解计算机系统.epub",
                    "size": 4096,
                    "content_hash": "hash-csapp",
                },
            ),
        }
    )
    _use_real_client(monkeypatch, http)

    job = create_ebook_job(
        session,
        settings.local_user_id,
        url="https://www.alipan.com/s/abc123",
        settings=settings,
        tags=["计算机"],
        collections=["技术书"],
    )
    assert job.mode == "transfer"

    done = run_ebook_job(
        session,
        settings.local_user_id,
        job.id,
        settings=settings,
    )

    assert done.status == "success", done.error
    assert done.cloud_file_id == "f-copied"
    assert done.cloud_path == "/MemoIsle/电子书/深入理解计算机系统.epub"

    memo = session.get(Memo, done.memo_id)
    assert memo is not None
    assert memo.resource_kind == ResourceKind.BOOK
    assert memo.ebook_file_id == "f-copied"
    assert memo.ebook_format == "epub"
    assert memo.ebook_size_bytes == 4096
    assert memo.ebook_snapshot is not None
    assert memo.ebook_snapshot["content_hash"] == "hash-csapp"
    assert memo.tags == ["计算机"]

    # 目录确实按 /MemoIsle/电子书 逐级创建。
    create_bodies = http.bodies_for("openFile/create")
    assert [body["name"] for body in create_bodies] == ["电子书"]
    assert create_bodies[0]["parent_file_id"] == "f-books"


def test_direct_link_pipeline_uses_real_client(
    session_settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """普通直链：真实客户端走 建目录 → 分片上传 → complete → 回读元数据。"""

    session, settings = session_settings

    def list_handler(body: dict[str, object] | None) -> FakeResponse:
        parent = (body or {}).get("parent_file_id")
        if parent == "root":
            return FakeResponse(
                200,
                {
                    "items": [
                        {"file_id": "f-books", "name": "MemoIsle", "type": "folder"},
                    ]
                },
            )
        return FakeResponse(
            200,
            {
                "items": [
                    {"file_id": "f-ebooks", "name": "电子书", "type": "folder"},
                ]
            },
        )

    http = FakeAliyunHttp(
        {
            "getDriveInfo": drive_info(),
            "openFile/list": list_handler,
            "openFile/create": FakeResponse(
                200,
                {
                    "file_id": "f-uploaded",
                    "upload_id": "upload-1",
                    "rapid_upload": False,
                    "part_info_list": [
                        {"part_number": 1, "upload_url": "https://upload.example/p1"},
                    ],
                },
            ),
            "upload.example": FakeResponse(200, {}),
            "openFile/complete": FakeResponse(200, {}),
            "openFile/get": FakeResponse(
                200,
                {
                    "file_id": "f-uploaded",
                    "name": "golang.epub",
                    "path": "/MemoIsle/电子书/golang.epub",
                    "size": 4,
                },
            ),
        }
    )
    _use_real_client(monkeypatch, http)

    job = create_ebook_job(
        session,
        settings.local_user_id,
        url="https://example.com/books/golang.epub",
        settings=settings,
    )
    assert job.mode == "upload"

    download_client = FakeDownloadClient(
        {
            "https://example.com/books/golang.epub": FakeDownloadResponse(
                b"book",
                headers={
                    "content-disposition": 'attachment; filename="golang.epub"',
                    "content-length": "4",
                },
            )
        }
    )

    done = run_ebook_job(
        session,
        settings.local_user_id,
        job.id,
        settings=settings,
        download_client=download_client,
        resolver=public_resolver,
    )

    assert done.status == "success", done.error
    assert done.cloud_file_id == "f-uploaded"

    memo = session.get(Memo, done.memo_id)
    assert memo is not None
    assert memo.title == "golang.epub"
    assert memo.ebook_format == "epub"

    # 两级目录都已存在，因此不应再创建目录，create 只用于上传文件本身。
    create_bodies = http.bodies_for("openFile/create")
    assert [body["name"] for body in create_bodies] == ["golang.epub"]
    assert create_bodies[0]["type"] == "file"
    assert create_bodies[0]["parent_file_id"] == "f-ebooks"
    assert create_bodies[0]["parent_file_id"] != "root"

    puts = [call for call in http.calls if call[0] == "PUT"]
    assert len(puts) == 1
    assert puts[0][3] == b"book"


def test_pipeline_reports_credential_failure_as_job_error(
    session_settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """云盘凭据失效时任务落库为失败，而不是抛出异常打断后台线程。"""

    session, settings = session_settings
    http = FakeAliyunHttp(
        {"getDriveInfo": FakeResponse(401, {"code": "TokenExpired"})}
    )
    _use_real_client(monkeypatch, http)

    job = create_ebook_job(
        session,
        settings.local_user_id,
        url="https://www.alipan.com/s/expired",
        settings=settings,
    )
    done = run_ebook_job(
        session,
        settings.local_user_id,
        job.id,
        settings=settings,
    )

    assert done.status == "failed"
    assert done.error is not None
    assert "阿里云盘" in done.error or "失效" in done.error
    assert session.query(Memo).count() == 0


def test_ebook_skips_web_enrichment_and_link_checks(
    session_settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """电子书不应被当成公开网页去抓取或巡检，但仍要完成规则分类。"""

    session, settings = session_settings

    def list_handler(body: dict[str, object] | None) -> FakeResponse:
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
            {
                "items": [
                    {"file_id": "s-1", "name": "算法导论.epub", "type": "file"},
                ]
            },
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
                    "name": "算法导论.epub",
                    "path": "/MemoIsle/电子书/算法导论.epub",
                    "size": 2048,
                },
            ),
            "openFile/get": FakeResponse(
                200,
                {
                    "file_id": "f-copied",
                    "name": "算法导论.epub",
                    "path": "/MemoIsle/电子书/算法导论.epub",
                    "size": 2048,
                },
            ),
        }
    )
    _use_real_client(monkeypatch, http)

    job = create_ebook_job(
        session,
        settings.local_user_id,
        url="https://www.alipan.com/s/abc123",
        settings=settings,
    )
    done = run_ebook_job(
        session,
        settings.local_user_id,
        job.id,
        settings=settings,
    )
    assert done.status == "success", done.error

    memo = session.get(Memo, done.memo_id)
    assert memo is not None
    assert memo.resource_metadata_status == ResourceProcessStatus.READY
    assert memo.link_next_check_at is None
    assert memo.resource_category_status == ResourceProcessStatus.READY
    assert memo.resource_category

    # 元数据 worker 的挑选条件不应命中电子书。
    enriching = list(
        session.scalars(
            select(Memo).where(
                Memo.type == MemoType.RESOURCE,
                Memo.resource_metadata_status.in_(
                    {ResourceProcessStatus.PENDING, ResourceProcessStatus.PROCESSING},
                ),
            )
        ).all()
    )
    assert enriching == []

    # 巡检 worker 的挑选条件同样不应命中。
    due = list(
        session.scalars(
            select(Memo).where(
                Memo.type == MemoType.RESOURCE,
                Memo.link_next_check_at.is_not(None),
            )
        ).all()
    )
    assert due == []
