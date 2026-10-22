"""电子书任务：链接判定、转存/上传流程与快照落库测试。"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from app.cloud_account_service import encrypt_credential
from app.cloud_drive.base import CloudDriveError, FileMeta, FileRef
from app.config import Settings
from app.database import Database
from app.ebook_service import (
    EbookJobStateError,
    EbookLinkError,
    classify_ebook_link,
    create_ebook_job,
    ebook_format_from_name,
    get_ebook_job,
    recover_running_ebook_jobs,
    retry_ebook_job,
    run_ebook_job,
)
from app.models import CloudAccount, EbookTransferJob, Memo
from app.schemas import MemoType, ResourceKind

PUBLIC_IP = "93.184.216.34"


def public_resolver(_hostname: str, _port: int) -> list[str]:
    """测试用地址解析：始终返回公网地址。"""

    return [PUBLIC_IP]


class FakeDrive:
    """最小云盘客户端替身。"""

    def __init__(
        self,
        *,
        refs: list[FileRef] | None = None,
        meta: FileMeta | None = None,
        error: CloudDriveError | None = None,
    ) -> None:
        self.provider = "aliyun"
        self.refs = refs or []
        self.meta = meta
        self.error = error
        self.uploaded: list[tuple[Path, str, str | None]] = []
        self.transfers: list[tuple[str, str | None, str]] = []

    def ensure_folder(self, path: str) -> str:
        return "folder-1"

    def transfer_share(
        self,
        share_url: str,
        password: str | None,
        target_folder_id: str,
    ) -> list[FileRef]:
        self.transfers.append((share_url, password, target_folder_id))
        if self.error is not None:
            raise self.error
        return self.refs

    def upload_file(
        self,
        local_path: Path,
        target_folder_id: str,
        name: str | None = None,
    ) -> FileRef:
        self.uploaded.append((local_path, target_folder_id, name))
        if self.error is not None:
            raise self.error
        return self.refs[0]

    def get_file_meta(self, file_id: str) -> FileMeta:
        if self.meta is None:
            raise CloudDriveError("未实现")
        return self.meta


class FakeDownloadResponse:
    """最小化的流式响应替身。"""

    def __init__(
        self,
        payload: bytes = b"",
        *,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        redirect_to: str | None = None,
    ) -> None:
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}
        self._redirect_to = redirect_to
        self.closed = False

    @property
    def is_redirect(self) -> bool:
        return self._redirect_to is not None

    def iter_bytes(self, chunk_size: int | None = None) -> Iterator[bytes]:
        step = chunk_size or len(self._payload) or 1
        for index in range(0, len(self._payload), step):
            yield self._payload[index : index + step]

    def close(self) -> None:
        self.closed = True


class FakeDownloadClient:
    """按 URL 返回预置响应的下载客户端。"""

    def __init__(self, responses: dict[str, FakeDownloadResponse]) -> None:
        self._responses = responses
        self.requested: list[str] = []

    def build_request(
        self,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
    ) -> tuple[str, str]:
        return (method, url)

    def send(
        self,
        request: tuple[str, str],
        stream: bool = False,
    ) -> FakeDownloadResponse:
        url = request[1]
        self.requested.append(url)
        if url not in self._responses:
            raise AssertionError(f"未预期的下载地址：{url}")
        return self._responses[url]


@pytest.fixture
def session_settings(tmp_path: Path) -> Iterator[tuple[object, Settings]]:
    """独立数据库会话与配置。"""

    settings = Settings(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'ebook.db'}",
        cors_origins=("http://localhost:5173",),
        local_user_id="00000000-0000-0000-0000-000000000001",
        auth_dev_mode=True,
        auth_token_secret="test-secret",
        audio_directory=tmp_path / "audio",
        image_directory=tmp_path / "images",
        resource_enrichment_enabled=False,
        resource_health_monitor_enabled=False,
        word_dictionary_enabled=False,
        ebook_max_bytes=8,
    )
    database = Database(settings.database_url)
    database.create_schema()
    with database.session_factory() as session:
        account = CloudAccount(
            id=str(uuid4()),
            user_id=settings.local_user_id,
            provider="aliyun",
            display_name="测试云盘",
            credential_cipher=encrypt_credential(
                settings,
                '{"access_token": "access-token-1234"}',
            ),
            credential_hint="...1234",
            default_folder="/MemoIsle/电子书",
            status="active",
        )
        session.add(account)
        session.commit()
        yield session, settings
    database.dispose()


def test_classify_ebook_link_variants() -> None:
    """云盘分享与普通直链分别判定，并提取提取码。"""

    aliyun = classify_ebook_link("https://www.alipan.com/s/abc123")
    assert (aliyun.provider, aliyun.mode) == ("aliyun", "transfer")

    baidu = classify_ebook_link("https://pan.baidu.com/s/1xyz?pwd=abcd")
    assert (baidu.provider, baidu.mode, baidu.share_password) == (
        "baidu",
        "transfer",
        "abcd",
    )

    direct = classify_ebook_link("https://example.com/books/rust.epub")
    assert (direct.provider, direct.mode) == (None, "upload")

    with pytest.raises(EbookLinkError):
        classify_ebook_link("ftp://example.com/book.epub")


def test_ebook_format_from_name() -> None:
    """常见电子书后缀可识别，其他返回 None。"""

    assert ebook_format_from_name("Rust 程序设计.epub") == "epub"
    assert ebook_format_from_name("book.PDF") == "pdf"
    assert ebook_format_from_name("archive.zip") is None


def test_create_ebook_job_requires_bound_account(session_settings) -> None:
    """未绑定对应云盘时不能提交任务。"""

    session, settings = session_settings
    with pytest.raises(EbookLinkError):
        create_ebook_job(
            session,
            settings.local_user_id,
            url="https://pan.baidu.com/s/1xyz?pwd=abcd",
            settings=settings,
        )


def test_run_ebook_job_transfer_creates_memo(session_settings) -> None:
    """云盘分享链接走转存，成功后写入 Memo 与快照。"""

    session, settings = session_settings
    job = create_ebook_job(
        session,
        settings.local_user_id,
        url="https://www.alipan.com/s/abc123",
        settings=settings,
        tags=["编程"],
        collections=["技术书"],
        note="同事推荐",
    )
    assert job.mode == "transfer"
    assert job.provider == "aliyun"

    drive = FakeDrive(
        refs=[
            FileRef(
                file_id="file-1",
                name="Rust 程序设计.epub",
                path="/MemoIsle/电子书/Rust 程序设计.epub",
                size_bytes=1234,
            )
        ],
        meta=FileMeta(
            file_id="file-1",
            name="Rust 程序设计.epub",
            path="/MemoIsle/电子书/Rust 程序设计.epub",
            size_bytes=1234,
            content_hash="hash-1",
        ),
    )

    done = run_ebook_job(
        session,
        settings.local_user_id,
        job.id,
        settings=settings,
        client=drive,
    )

    assert done.status == "success"
    assert done.progress == 100
    assert done.memo_id is not None
    assert drive.transfers == [("https://www.alipan.com/s/abc123", None, "folder-1")]

    memo = session.get(Memo, done.memo_id)
    assert memo is not None
    assert memo.type == MemoType.RESOURCE
    assert memo.resource_kind == ResourceKind.BOOK
    assert memo.title == "Rust 程序设计.epub"
    assert memo.ebook_provider == "aliyun"
    assert memo.ebook_file_id == "file-1"
    assert memo.ebook_format == "epub"
    assert memo.ebook_size_bytes == 1234
    assert memo.ebook_snapshot == {
        "file_id": "file-1",
        "name": "Rust 程序设计.epub",
        "path": "/MemoIsle/电子书/Rust 程序设计.epub",
        "size_bytes": 1234,
        "content_hash": "hash-1",
        "category": None,
        "thumbnail": None,
        "updated_at": None,
    }
    assert memo.tags == ["编程"]
    assert memo.collections == ["技术书"]


def test_run_ebook_job_upload_downloads_and_cleans_temp(session_settings) -> None:
    """普通直链先下载再上传，临时文件在任务结束后删除。"""

    session, settings = session_settings
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
                    "content-type": "application/epub+zip",
                    "content-disposition": 'attachment; filename="golang.epub"',
                    "content-length": "4",
                },
            )
        }
    )
    drive = FakeDrive(
        refs=[
            FileRef(
                file_id="file-2",
                name="golang.epub",
                path="/MemoIsle/电子书/golang.epub",
                size_bytes=4,
            )
        ],
    )

    done = run_ebook_job(
        session,
        settings.local_user_id,
        job.id,
        settings=settings,
        client=drive,
        download_client=download_client,
        resolver=public_resolver,
    )

    assert done.status == "success"
    uploaded_path, folder_id, name = drive.uploaded[0]
    assert folder_id == "folder-1"
    assert name == "golang.epub"
    assert not uploaded_path.exists()

    memo = session.get(Memo, done.memo_id)
    assert memo is not None
    assert memo.ebook_format == "epub"
    assert memo.title == "golang.epub"


def test_run_ebook_job_rejects_oversized_download(session_settings) -> None:
    """超过配置上限的直链下载失败并保留失败原因。"""

    session, settings = session_settings
    job = create_ebook_job(
        session,
        settings.local_user_id,
        url="https://example.com/books/huge.epub",
        settings=settings,
    )
    download_client = FakeDownloadClient(
        {
            "https://example.com/books/huge.epub": FakeDownloadResponse(
                b"0123456789abcdef",
                headers={"content-length": "16"},
            )
        }
    )

    done = run_ebook_job(
        session,
        settings.local_user_id,
        job.id,
        settings=settings,
        client=FakeDrive(),
        download_client=download_client,
        resolver=public_resolver,
    )

    assert done.status == "failed"
    assert done.error is not None
    assert "上限" in done.error


def test_run_ebook_job_records_cloud_failure(session_settings) -> None:
    """云盘报错时任务标记失败，且不产生 Memo。"""

    session, settings = session_settings
    job = create_ebook_job(
        session,
        settings.local_user_id,
        url="https://www.alipan.com/s/broken",
        settings=settings,
    )
    drive = FakeDrive(error=CloudDriveError("分享已失效"))

    done = run_ebook_job(
        session,
        settings.local_user_id,
        job.id,
        settings=settings,
        client=drive,
    )

    assert done.status == "failed"
    assert done.error == "分享已失效"
    assert session.query(Memo).count() == 0


def test_retry_ebook_job_requires_failed_state(session_settings) -> None:
    """只有失败任务可以重试；排队中与已完成都要拒绝。"""

    session, settings = session_settings
    job = create_ebook_job(
        session,
        settings.local_user_id,
        url="https://www.alipan.com/s/retry",
        settings=settings,
    )
    # 排队中：拒绝，避免重复派发。
    with pytest.raises(EbookJobStateError):
        retry_ebook_job(session, settings.local_user_id, job.id)

    done = run_ebook_job(
        session,
        settings.local_user_id,
        job.id,
        settings=settings,
        client=FakeDrive(error=CloudDriveError("限流")),
    )
    assert done.status == "failed"

    retried = retry_ebook_job(session, settings.local_user_id, job.id)
    assert retried.status == "pending"
    assert retried.error is None

    finished = run_ebook_job(
        session,
        settings.local_user_id,
        job.id,
        settings=settings,
        client=FakeDrive(
            refs=[FileRef(file_id="f", name="a.epub", path="/a.epub")],
        ),
    )
    assert finished.status == "success"
    with pytest.raises(EbookJobStateError):
        retry_ebook_job(session, settings.local_user_id, job.id)


def test_run_ebook_job_refuses_already_running(session_settings) -> None:
    """执行中的任务不能被第二次执行（后台线程与启动恢复可能同时碰到它）。"""

    session, settings = session_settings
    job = create_ebook_job(
        session,
        settings.local_user_id,
        url="https://www.alipan.com/s/running",
        settings=settings,
    )
    job.status = "running"
    session.commit()

    with pytest.raises(EbookJobStateError):
        run_ebook_job(
            session,
            settings.local_user_id,
            job.id,
            settings=settings,
            client=FakeDrive(),
        )


def test_recover_running_ebook_jobs_requeues(session_settings) -> None:
    """进程退出时残留的执行中任务会退回排队，不会永远卡住。"""

    session, settings = session_settings
    job = create_ebook_job(
        session,
        settings.local_user_id,
        url="https://www.alipan.com/s/stuck",
        settings=settings,
    )
    job.status = "running"
    job.stage = "上传中"
    job.progress = 60
    session.commit()

    recovered = recover_running_ebook_jobs(session)

    assert recovered == 1
    session.refresh(job)
    assert job.status == "pending"
    assert job.stage == "排队中"


def test_get_ebook_job_isolated_by_user(session_settings) -> None:
    """任务按用户隔离，其他用户读不到。"""

    session, settings = session_settings
    job = create_ebook_job(
        session,
        settings.local_user_id,
        url="https://www.alipan.com/s/iso",
        settings=settings,
    )
    assert session.get(EbookTransferJob, job.id) is not None
    from app.ebook_service import EbookJobNotFoundError

    with pytest.raises(EbookJobNotFoundError):
        get_ebook_job(session, "00000000-0000-0000-0000-0000000000ff", job.id)


def test_undecryptable_credential_fails_job_instead_of_hanging(
    session_settings,
) -> None:
    """凭据解密失败时任务必须进入失败终态并可重试，不能卡在执行中。"""

    import dataclasses

    session, settings = session_settings
    job = create_ebook_job(
        session,
        settings.local_user_id,
        url="https://www.alipan.com/s/abc123",
        settings=settings,
    )
    # 密钥变更后，已落库的云盘凭据无法解密。
    rotated = dataclasses.replace(
        settings,
        auth_token_secret="rotated-secret",
        cloud_credential_secret="rotated-secret",
    )

    result = run_ebook_job(session, settings.local_user_id, job.id, settings=rotated)

    assert result.status == "failed"
    assert "重新绑定" in (result.error or "")
    # 失败终态才能被用户重试。
    retried = retry_ebook_job(session, settings.local_user_id, job.id)
    assert retried.status == "pending"


def test_unexpected_error_still_writes_failed_state(session_settings) -> None:
    """白名单外的异常同样要写失败终态。"""

    class ExplodingDrive(FakeDrive):
        def ensure_folder(self, path: str) -> str:
            raise RuntimeError("boom")

    session, settings = session_settings
    job = create_ebook_job(
        session,
        settings.local_user_id,
        url="https://www.alipan.com/s/abc123",
        settings=settings,
    )

    result = run_ebook_job(
        session,
        settings.local_user_id,
        job.id,
        settings=settings,
        client=ExplodingDrive(),
    )

    assert result.status == "failed"
    assert result.error == "内部错误：RuntimeError"


def test_retry_after_cloud_write_does_not_upload_again(session_settings) -> None:
    """文件已写进云盘、后续步骤失败时，重试复用引用而不再转存。"""

    class FailingMetaDrive(FakeDrive):
        fail_meta = True

        def get_file_meta(self, file_id: str) -> FileMeta:
            if self.fail_meta:
                raise RuntimeError("元数据接口宕机")
            return super().get_file_meta(file_id)

    session, settings = session_settings
    job = create_ebook_job(
        session,
        settings.local_user_id,
        url="https://www.alipan.com/s/abc123",
        settings=settings,
    )
    reference = FileRef(
        file_id="file-1",
        name="Rust.epub",
        path="/MemoIsle/电子书/Rust.epub",
    )
    drive = FailingMetaDrive(refs=[reference])

    first = run_ebook_job(
        session,
        settings.local_user_id,
        job.id,
        settings=settings,
        client=drive,
    )
    assert first.status == "failed"
    assert first.cloud_file_id == "file-1"
    assert len(drive.transfers) == 1

    retry_ebook_job(session, settings.local_user_id, job.id)
    drive.fail_meta = False
    second = run_ebook_job(
        session,
        settings.local_user_id,
        job.id,
        settings=settings,
        client=drive,
    )

    assert second.status == "success"
    # 第二次没有再转存。
    assert len(drive.transfers) == 1
    memo = session.get(Memo, second.memo_id)
    assert memo.ebook_file_id == "file-1"
    assert memo.title == "Rust.epub"
