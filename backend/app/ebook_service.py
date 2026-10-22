"""电子书收藏：链接判定、转存/上传任务与元数据快照。

云盘协议差异全部在 app.cloud_drive 适配层，本模块只负责流程编排：

- 云盘分享链接 → 调适配层把文件转存到用户云盘目录；
- 普通直链 → 服务端受限下载到临时文件，再上传到用户云盘，随后删除临时文件。

MemoIsle 只保存云盘文件引用与元数据快照，不保存电子书本体。
"""

from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, unquote, urljoin, urlsplit
from uuid import UUID, uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.category_service import classification_categories, classification_rules
from app.cloud_account_service import (
    CloudCredentialRejectedError,
    build_cloud_client,
    decrypt_credential,
    get_account_for_provider,
    list_cloud_accounts,
    normalize_folder,
)
from app.cloud_drive import CloudDriveError, FileMeta, FileRef
from app.config import Settings
from app.database import Database
from app.models import CloudAccount, EbookTransferJob, Memo
from app.resource_processing import (
    AddressResolver,
    UnsafeResourceUrlError,
    classify_resource,
    validate_public_resource_url,
)
from app.resource_service import apply_category, fallback_metadata
from app.schemas import (
    MemoCreate,
    MemoType,
    ResourceKind,
    ResourceProcessStatus,
)
from app.service import ResourceDuplicateError, create_memo

logger = logging.getLogger(__name__)

# 云盘分享链接的域名特征；命中即走转存，否则按普通直链下载上传。
SHARE_HOSTS: dict[str, tuple[str, ...]] = {
    "aliyun": ("alipan.com", "aliyundrive.com", "aliyunpan.com"),
    "baidu": ("pan.baidu.com", "yun.baidu.com"),
}

EBOOK_EXTENSIONS: frozenset[str] = frozenset(
    {
        "epub",
        "pdf",
        "mobi",
        "azw",
        "azw3",
        "txt",
        "djvu",
        "fb2",
        "cbz",
        "cbr",
        "chm",
    },
)

DOWNLOAD_CHUNK_BYTES = 1024 * 1024
MAX_REDIRECTS = 3
DOWNLOAD_USER_AGENT = "MemoIsle/0.1 (+ebook collection)"
JOB_PENDING = "pending"
JOB_RUNNING = "running"
JOB_SUCCESS = "success"
JOB_FAILED = "failed"
RUNNING_STAGES = (JOB_PENDING, JOB_RUNNING)


class EbookJobNotFoundError(LookupError):
    """任务不存在或不属于当前用户。"""


class EbookJobStateError(ValueError):
    """任务当前状态不允许该操作。"""


class EbookLinkError(ValueError):
    """电子书链接缺失或格式不支持。"""


class EbookDownloadTooLargeError(ValueError):
    """直链文件超过配置的大小上限。"""


@dataclass(frozen=True)
class EbookLink:
    """链接判定结果。"""

    url: str
    provider: str | None
    mode: str
    share_password: str | None = None


def classify_ebook_link(url: str) -> EbookLink:
    """判断链接是云盘分享还是普通直链，并提取分享提取码。"""

    cleaned = (url or "").strip()
    parsed = urlsplit(cleaned)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise EbookLinkError("请填写 http(s) 开头的电子书链接")
    host = (parsed.hostname or "").rstrip(".").lower()
    query = parse_qs(parsed.query)
    password = next(
        (
            value
            for key in ("pwd", "password", "passcode")
            for value in query.get(key, [])
            if value.strip()
        ),
        None,
    )
    for provider, hosts in SHARE_HOSTS.items():
        if any(host == item or host.endswith(f".{item}") for item in hosts):
            return EbookLink(
                url=cleaned,
                provider=provider,
                mode="transfer",
                share_password=password,
            )
    return EbookLink(url=cleaned, provider=None, mode="upload")


def ebook_format_from_name(name: str) -> str | None:
    """从文件名推断电子书格式。"""

    suffix = Path(name).suffix.lstrip(".").lower()
    return suffix if suffix in EBOOK_EXTENSIONS else None


def _decode_filename(value: str | None) -> str | None:
    """从 Content-Disposition 里取出文件名。"""

    if not value:
        return None
    for chunk in value.split(";"):
        cleaned = chunk.strip()
        if not cleaned.lower().startswith("filename="):
            continue
        raw = cleaned.partition("=")[2].strip().strip('"')
        if not raw:
            continue
        if "''" in raw:
            raw = raw.split("''", 1)[1]
        return unquote(raw) or None
    return None


def _filename_from_url(url: str) -> str:
    """回退用 URL 末段作为文件名。"""

    path = urlsplit(url).path
    candidate = unquote(Path(path).name)
    return candidate or "ebook"


def download_direct_link(
    url: str,
    *,
    settings: Settings,
    client: httpx.Client | None = None,
    resolver: AddressResolver | None = None,
) -> tuple[Path, str]:
    """受限下载直链到临时文件，返回（临时路径，文件名）。

    每一次重定向都重新做公网地址校验，避免通过跳转访问内网。
    """

    httpx_client = client or httpx.Client(
        timeout=settings.ebook_download_timeout_seconds,
        follow_redirects=False,
        trust_env=False,
    )
    max_bytes = settings.ebook_max_bytes
    current_url = validate_public_resource_url(url, resolver)
    response: httpx.Response | None = None
    try:
        for _ in range(MAX_REDIRECTS + 1):
            request = httpx_client.build_request(
                "GET",
                current_url,
                headers={"User-Agent": DOWNLOAD_USER_AGENT},
            )
            response = httpx_client.send(request, stream=True)
            if response.is_redirect:
                location = response.headers.get("location")
                response.close()
                if not location:
                    raise EbookLinkError("链接跳转缺少目标地址")
                current_url = validate_public_resource_url(
                    urljoin(current_url, location),
                    resolver,
                )
                response = None
                continue
            break
        if response is None:
            raise EbookLinkError("链接跳转次数过多")
        if response.status_code >= 400:
            raise EbookLinkError(f"下载失败（HTTP {response.status_code}）")

        filename = _decode_filename(
            response.headers.get("content-disposition"),
        ) or _filename_from_url(current_url)

        declared_length = response.headers.get("content-length")
        if declared_length and declared_length.isdigit():
            if int(declared_length) > max_bytes:
                raise EbookDownloadTooLargeError("文件超过配置的大小上限")

        with tempfile.NamedTemporaryFile(
            prefix="memoisle-ebook-",
            suffix=Path(filename).suffix[:12],
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            total_bytes = 0
            for chunk in response.iter_bytes(DOWNLOAD_CHUNK_BYTES):
                total_bytes += len(chunk)
                if total_bytes > max_bytes:
                    raise EbookDownloadTooLargeError("文件超过配置的大小上限")
                handle.write(chunk)
    except httpx.HTTPError as error:
        raise EbookLinkError(f"下载失败：{error}") from error
    finally:
        if response is not None:
            response.close()
    return temp_path, filename


def create_ebook_job(
    session: Session,
    user_id: str,
    *,
    url: str,
    settings: Settings,
    provider: str | None = None,
    share_password: str | None = None,
    target_folder: str | None = None,
    tags: list[str] | None = None,
    collections: list[str] | None = None,
    note: str | None = None,
) -> EbookTransferJob:
    """提交电子书收藏任务：判定链接、确认云盘绑定后入队。"""

    link = classify_ebook_link(url)
    account = _resolve_account(session, user_id, provider or link.provider)
    job = EbookTransferJob(
        id=str(uuid4()),
        user_id=user_id,
        source_url=link.url,
        share_password=(share_password or link.share_password or None),
        provider=account.provider,
        mode=link.mode,
        status=JOB_PENDING,
        progress=0,
        stage="排队中",
        target_folder=normalize_folder(target_folder or account.default_folder),
        tags=list(tags or []),
        collections=list(collections or []),
        note=(note or "").strip() or None,
        attempts=0,
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def _resolve_account(
    session: Session,
    user_id: str,
    provider: str | None,
) -> CloudAccount:
    """选出本次任务使用的云盘绑定。"""

    if provider:
        account = get_account_for_provider(session, user_id, provider)
        if account is None:
            raise EbookLinkError(f"尚未绑定 {provider} 云盘，请先到设置页绑定")
        if account.status != "active":
            raise EbookLinkError("云盘凭据已失效，请重新绑定或校验")
        return account
    accounts = [
        item
        for item in list_cloud_accounts(session, user_id)
        if item.status == "active"
    ]
    if not accounts:
        raise EbookLinkError("尚未绑定可用的云盘，请先到设置页绑定")
    return accounts[0]


def get_ebook_job(session: Session, user_id: str, job_id: str) -> EbookTransferJob:
    """读取单个任务。"""

    job = session.scalar(
        select(EbookTransferJob).where(
            EbookTransferJob.id == job_id,
            EbookTransferJob.user_id == user_id,
        ),
    )
    if job is None:
        raise EbookJobNotFoundError("电子书任务不存在")
    return job


def list_ebook_jobs(
    session: Session,
    user_id: str,
    *,
    limit: int = 20,
) -> list[EbookTransferJob]:
    """按创建时间倒序列出任务。"""

    return list(
        session.scalars(
            select(EbookTransferJob)
            .where(EbookTransferJob.user_id == user_id)
            .order_by(EbookTransferJob.created_at.desc())
            .limit(limit),
        ).all(),
    )


def retry_ebook_job(session: Session, user_id: str, job_id: str) -> EbookTransferJob:
    """把失败任务重新排队。"""

    job = get_ebook_job(session, user_id, job_id)
    if job.status != JOB_FAILED:
        # 排队中或执行中的任务重复入队会导致同一本书被上传两次。
        raise EbookJobStateError("只有失败的任务可以重试")
    job.status = JOB_PENDING
    job.progress = 0
    job.stage = "排队中"
    job.error = None
    session.commit()
    session.refresh(job)
    return job


def run_ebook_job(
    session: Session,
    user_id: str,
    job_id: str,
    *,
    settings: Settings,
    client: object | None = None,
    download_client: httpx.Client | None = None,
    resolver: AddressResolver | None = None,
) -> EbookTransferJob:
    """执行一个电子书任务，成功时创建 Memo 并写入快照。"""

    job = get_ebook_job(session, user_id, job_id)
    if job.status == JOB_SUCCESS:
        raise EbookJobStateError("任务已经完成")
    if job.status == JOB_RUNNING:
        # 防止同一个任务被后台线程与启动恢复同时执行。
        raise EbookJobStateError("任务正在执行中")
    job.status = JOB_RUNNING
    job.attempts += 1
    job.stage = "准备云盘"
    job.error = None
    session.commit()

    temp_holder: list[Path] = []
    try:
        account = _resolve_account(session, user_id, job.provider)
        credential = decrypt_credential(settings, account.credential_cipher)
        drive = client or build_cloud_client(
            account.provider,
            credential,
            settings=settings,
        )
        if job.cloud_file_id:
            # 上一次已经把文件写进云盘，只是后续步骤失败：直接复用引用，
            # 不再转存/上传，否则每次重试都会在用户云盘里多出一份。
            cloud_path = job.cloud_path or ""
            refs = [
                FileRef(
                    file_id=job.cloud_file_id,
                    # 书名优先取云盘路径的文件名部分；get_file_meta 成功时会覆盖。
                    name=cloud_path.rstrip("/").rsplit("/", 1)[-1],
                    path=cloud_path,
                ),
            ]
        else:
            refs = _write_to_cloud(
                session,
                job,
                drive,
                settings=settings,
                download_client=download_client,
                resolver=resolver,
                temp_holder=temp_holder,
            )
        if not refs:
            raise CloudDriveError("云盘未返回任何文件")
        reference: FileRef = refs[0]
        # 文件一进云盘就记下引用，之后任何一步失败都能续上而不重复写入。
        job.cloud_file_id = reference.file_id
        job.cloud_path = reference.path or job.cloud_path
        job.stage = "写入资料库"
        job.progress = 85
        session.commit()
        meta = _safe_file_meta(drive, reference)
        memo = _create_ebook_memo(session, user_id, job, reference, meta)

        job.memo_id = memo.id
        job.cloud_file_id = reference.file_id
        job.cloud_path = reference.path or meta.path
        job.snapshot = meta.as_snapshot()
        job.status = JOB_SUCCESS
        job.progress = 100
        job.stage = "已完成"
        job.finished_at = datetime.now(UTC)
        session.commit()
        session.refresh(job)
        return job
    except (
        CloudDriveError,
        EbookLinkError,
        EbookDownloadTooLargeError,
        UnsafeResourceUrlError,
        CloudCredentialRejectedError,
    ) as error:
        return _mark_job_failed(session, job, str(error))
    except Exception as error:  # noqa: BLE001 - 任何退出路径都必须写终态
        # 已置为 running 的任务若异常穿出，会一直卡在执行中：用户不能重试，
        # 只有重启时被退回排队再失败一次。未预期错误记录堆栈后同样置为失败。
        logger.exception("电子书任务 %s 执行异常", job_id)
        return _mark_job_failed(session, job, f"内部错误：{type(error).__name__}")
    finally:
        for temp_path in temp_holder:
            # 电子书本体不留在服务端，任务结束即删除临时文件。
            temp_path.unlink(missing_ok=True)


def _write_to_cloud(
    session: Session,
    job: EbookTransferJob,
    drive: object,
    *,
    settings: Settings,
    download_client: httpx.Client | None,
    resolver: AddressResolver | None,
    temp_holder: list[Path],
) -> list[FileRef]:
    """把电子书写进用户云盘：分享链接转存，直链先下载再上传。"""

    folder_id = drive.ensure_folder(job.target_folder)
    job.stage = "转存中" if job.mode == "transfer" else "下载中"
    job.progress = 20
    session.commit()
    if job.mode == "transfer":
        return drive.transfer_share(job.source_url, job.share_password, folder_id)
    temp_path, filename = download_direct_link(
        job.source_url,
        settings=settings,
        client=download_client,
        resolver=resolver,
    )
    temp_holder.append(temp_path)
    job.stage = "上传中"
    job.progress = 60
    session.commit()
    return [drive.upload_file(temp_path, folder_id, filename)]


def _mark_job_failed(
    session: Session,
    job: EbookTransferJob,
    message: str,
) -> EbookTransferJob:
    """把任务写成失败终态；异常可能发生在事务中途，先回滚再写。"""

    job_id = job.id
    session.rollback()
    job = session.get(EbookTransferJob, job_id) or job
    job.status = JOB_FAILED
    job.stage = "失败"
    job.error = message[:500]
    job.finished_at = datetime.now(UTC)
    session.commit()
    session.refresh(job)
    return job


def _safe_file_meta(drive: object, reference: FileRef) -> FileMeta:
    """尽力读取文件元数据；适配层未实现时退回转存返回的引用。"""

    try:
        return drive.get_file_meta(reference.file_id)
    except CloudDriveError:
        return FileMeta(
            file_id=reference.file_id,
            name=reference.name,
            path=reference.path,
            size_bytes=reference.size_bytes,
        )


def _create_ebook_memo(
    session: Session,
    user_id: str,
    job: EbookTransferJob,
    reference: FileRef,
    meta: FileMeta,
) -> Memo:
    """为完成的电子书写入 Memo；重复链接直接复用已有资料。"""

    name = meta.name or reference.name or "电子书"
    title = name[:200]
    body = job.note or f"电子书：{name}"
    payload = MemoCreate(
        client_id=UUID(job.id),
        type=MemoType.RESOURCE,
        title=title,
        body=body[:50_000],
        source_url=job.source_url,
        source_title=title,
        resource_kind=ResourceKind.BOOK,
        tags=list(job.tags or []),
        collections=list(job.collections or []),
    )
    try:
        memo = create_memo(session, user_id, payload)
    except ResourceDuplicateError as error:
        memo = error.current
    memo.ebook_provider = job.provider
    memo.ebook_file_id = reference.file_id
    memo.ebook_path = reference.path or meta.path
    memo.ebook_format = ebook_format_from_name(name)
    memo.ebook_size_bytes = meta.size_bytes or reference.size_bytes
    memo.ebook_snapshot = meta.as_snapshot()
    _classify_ebook_inline(session, user_id, memo)
    session.commit()
    session.refresh(memo)
    return memo


def _classify_ebook_inline(session: Session, user_id: str, memo: Memo) -> None:
    """电子书不走网页抓取：直接标记元数据完成、退出巡检，并用已有信息做规则分类。

    云盘分享链接不是可巡检的公开网页，抓取它只会得到分享页或错误，
    既浪费请求又可能用分享页内容覆盖书名，因此这里就地收敛处理状态。
    """

    memo.resource_metadata_status = ResourceProcessStatus.READY
    memo.resource_metadata_error = None
    memo.link_next_check_at = None
    decision = classify_resource(
        fallback_metadata(memo),
        user_rules=classification_rules(session, user_id),
        category_options=classification_categories(session, user_id),
    )
    apply_category(memo, decision)


def process_ebook_job_in_background(
    database_url: str,
    user_id: str,
    job_id: str,
    settings: Settings,
) -> None:
    """使用独立数据库会话执行电子书任务。"""

    database = Database(database_url)
    try:
        with database.session_factory() as session:
            try:
                run_ebook_job(session, user_id, job_id, settings=settings)
            except (EbookJobNotFoundError, EbookJobStateError):
                return
    finally:
        database.dispose()


def recover_running_ebook_jobs(session: Session, limit: int = 50) -> int:
    """把进程退出时残留的「执行中」任务退回排队，避免它们永远卡住。"""

    stuck = list(
        session.scalars(
            select(EbookTransferJob)
            .where(EbookTransferJob.status == JOB_RUNNING)
            .order_by(EbookTransferJob.updated_at.asc())
            .limit(limit),
        ).all(),
    )
    for job in stuck:
        job.status = JOB_PENDING
        job.stage = "排队中"
    if stuck:
        session.commit()
    return len(stuck)


def run_pending_ebook_jobs(
    database_url: str,
    settings: Settings,
    limit: int = 5,
) -> int:
    """恢复服务重启前未完成的电子书任务。"""

    database = Database(database_url)
    processed_count = 0
    try:
        with database.session_factory() as session:
            # 上一次进程可能在任务执行中退出，先把它们退回排队再依次执行。
            recover_running_ebook_jobs(session)
            jobs = list(
                session.scalars(
                    select(EbookTransferJob)
                    .where(EbookTransferJob.status.in_(RUNNING_STAGES))
                    .order_by(EbookTransferJob.created_at.asc())
                    .limit(limit),
                ).all(),
            )
            job_keys = [(job.user_id, job.id) for job in jobs]
        for user_id, job_id in job_keys:
            process_ebook_job_in_background(database_url, user_id, job_id, settings)
            processed_count += 1
    finally:
        database.dispose()
    return processed_count
