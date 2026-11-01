"""资料库导出（JSON / CSV / Markdown）与导入。"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Annotated

from fastapi import (
    APIRouter,
    HTTPException,
    Query,
    Request,
)
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.category_service import (
    serialize_category_templates,
)
from app.config import Settings
from app.export_service import serialize_memos_csv, serialize_memos_markdown
from app.import_service import (
    MAX_LIBRARY_IMPORT_BYTES,
    LibraryImportFormatError,
    LibraryImportTooLargeError,
    import_library_memos,
    parse_library_import,
)
from app.models import Memo, User
from app.routes.deps import SessionDependency, SettingsDependency, UserDependency
from app.schemas import (
    AuthUserResponse,
    MemoRead,
    WordImportErrorRead,
    WordImportResponse,
)
from app.service import (
    list_memos_for_export,
    purge_expired_trash,
)

router = APIRouter()


def _prepare_export_data(
    session: Session,
    user_id: str,
    settings: Settings,
) -> tuple[User, list[Memo], datetime]:
    """清理过期回收站并读取当前账号可导出的数据。"""

    # 导出的数据必须遵循回收站保留期，避免把已永久删除内容重新带出。
    purge_expired_trash(
        session,
        settings.audio_directory,
        settings.image_directory,
        settings.trash_retention_days,
        user_id=user_id,
    )
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="当前用户不存在")
    exported_at = datetime.now(UTC)
    return user, list_memos_for_export(session, user_id), exported_at


async def _read_request_body_limited(request: Request, max_bytes: int) -> bytes:
    """按块读取请求体，超过上限立即中断，不依赖 Content-Length。"""

    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(status_code=413, detail="备份文件不能超过 10 MB")
        chunks.append(chunk)
    return b"".join(chunks)


def _export_headers(filename: str) -> dict[str, str]:
    """为私人导出响应设置下载文件名和缓存策略。"""

    return {
        "Cache-Control": "no-store",
        "Content-Disposition": f'attachment; filename="{filename}"',
    }


@router.get("/exports/json", tags=["exports"])
def export_json_route(
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> Response:
    """下载当前用户的 JSON 数据副本，不包含访问令牌和录音二进制。"""

    user, memos, exported_at = _prepare_export_data(session, user_id, settings)
    payload = {
        "format": "memoisle-json",
        "version": 1,
        "exported_at": exported_at.isoformat().replace("+00:00", "Z"),
        "audio_files_included": False,
        "image_files_included": False,
        "user": AuthUserResponse.model_validate(user).model_dump(mode="json"),
        "categories": serialize_category_templates(session, user_id),
        "memos": [
            MemoRead.model_validate(memo).model_dump(mode="json") for memo in memos
        ],
    }
    filename = f"memoisle-export-{exported_at.strftime('%Y%m%dT%H%M%SZ')}.json"
    # 不缓存私人数据；响应中只放可迁移的条目字段，不暴露内部音频存储名。
    return Response(
        content=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        media_type="application/json",
        headers=_export_headers(filename),
    )


@router.get("/exports/csv", tags=["exports"])
def export_csv_route(
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> Response:
    """下载当前用户的完整 CSV 数据副本。"""

    _, memos, exported_at = _prepare_export_data(session, user_id, settings)
    filename = f"memoisle-export-{exported_at.strftime('%Y%m%dT%H%M%SZ')}.csv"
    return Response(
        content=serialize_memos_csv(memos),
        media_type="text/csv; charset=utf-8",
        headers=_export_headers(filename),
    )


@router.get("/exports/markdown", tags=["exports"])
def export_markdown_route(
    session: SessionDependency,
    user_id: UserDependency,
    settings: SettingsDependency,
) -> Response:
    """下载当前用户的可读 Markdown 数据副本。"""

    _, memos, exported_at = _prepare_export_data(session, user_id, settings)
    filename = f"memoisle-export-{exported_at.strftime('%Y%m%dT%H%M%SZ')}.md"
    return Response(
        content=serialize_memos_markdown(memos),
        media_type="text/markdown; charset=utf-8",
        headers=_export_headers(filename),
    )


@router.post(
    "/imports",
    response_model=WordImportResponse,
    tags=["exports"],
)
async def import_library_route(
    request: Request,
    session: SessionDependency,
    user_id: UserDependency,
    file_format: Annotated[str, Query(alias="format")] = "json",
) -> WordImportResponse:
    """导入 JSON 或 CSV 备份，按 client_id、词形和网址跳过重复项。"""

    if file_format.strip().lower() == "markdown":
        raise HTTPException(
            status_code=422,
            detail="Markdown 仅供阅读，完整恢复请使用 JSON 或 CSV 备份",
        )
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared_size = int(content_length)
        except ValueError as error:
            raise HTTPException(
                status_code=400,
                detail="Content-Length 无效",
            ) from error
        if declared_size > MAX_LIBRARY_IMPORT_BYTES:
            raise HTTPException(status_code=413, detail="备份文件不能超过 10 MB")

    content = await _read_request_body_limited(request, MAX_LIBRARY_IMPORT_BYTES)
    try:
        parsed = parse_library_import(content, file_format)
        result = import_library_memos(session, user_id, parsed)
    except LibraryImportTooLargeError as error:
        raise HTTPException(status_code=413, detail=str(error)) from error
    except LibraryImportFormatError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return WordImportResponse(
        total_count=result.total_count,
        imported_count=result.imported_count,
        duplicate_count=result.duplicate_count,
        skipped_count=result.skipped_count,
        failed_count=result.failed_count,
        errors=[
            WordImportErrorRead(row=row, message=message)
            for row, message in result.errors
        ],
    )
