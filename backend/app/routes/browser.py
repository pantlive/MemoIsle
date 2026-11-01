"""浏览器扩展同步：一键收藏、打开的标签页、书签与浏览历史。"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import (
    APIRouter,
    HTTPException,
    Query,
    Request,
    status,
)
from fastapi.responses import Response
from sqlalchemy.exc import OperationalError

from app.browser_capture_service import (
    BrowserBookmarkRevisionConflictError,
    BrowserCaptureConsumedError,
    BrowserCaptureExpiredError,
    BrowserCaptureNotFoundError,
    BrowserCaptureOriginError,
    create_browser_capture,
    exchange_browser_capture,
    list_open_browser_tabs,
    read_browser_bookmark_snapshot,
    sync_browser_bookmark_delta,
    sync_browser_bookmarks,
    sync_open_browser_tabs,
)
from app.browser_history_service import (
    BrowserHistoryOriginError,
    HistoryDeviceMergeError,
    HistoryDeviceNotFoundError,
    clear_browser_history,
    delete_history_device,
    history_extended_search_enabled,
    list_browser_history,
    merge_history_devices,
    rename_history_device,
    sync_browser_history,
    update_history_extended_search,
)
from app.database import is_sqlite_lock_error
from app.resource_processing import UnsafeResourceUrlError
from app.routes.deps import SessionDependency, UserDependency
from app.schemas import (
    BrowserBookmarkDeltaSyncRequest,
    BrowserBookmarkSnapshotRead,
    BrowserBookmarkSyncRequest,
    BrowserBookmarkSyncResponse,
    BrowserCaptureContext,
    BrowserCaptureCreate,
    BrowserCaptureCreated,
    BrowserCaptureExchangeRequest,
    BrowserHistoryDeviceMerge,
    BrowserHistoryDeviceRead,
    BrowserHistoryDeviceUpdate,
    BrowserHistoryListResponse,
    BrowserHistorySettingsRead,
    BrowserHistorySettingsUpdate,
    BrowserHistorySyncRequest,
    BrowserHistorySyncResponse,
    BrowserOpenTabListResponse,
    BrowserOpenTabRead,
    BrowserTabSyncRequest,
    BrowserTabSyncResponse,
)

router = APIRouter()

# 记录「这台机器」的设备 ID Cookie。一年有效，覆盖绝大多数重装场景。
# 由服务端下发 HttpOnly，避免页面脚本读取，也避开 Safari 对 JS Cookie 的 7 天限制。
HISTORY_DEVICE_COOKIE = "memoisle_device"
HISTORY_DEVICE_COOKIE_MAX_AGE = 365 * 24 * 60 * 60


@router.post(
    "/browser-captures",
    response_model=BrowserCaptureCreated,
    status_code=status.HTTP_201_CREATED,
    tags=["browser-captures"],
)
def create_browser_capture_route(
    payload: BrowserCaptureCreate,
    request: Request,
    session: SessionDependency,
    user_id: UserDependency,
) -> BrowserCaptureCreated:
    """接收扩展明确授权的当前页并签发短时一次性凭据。"""

    try:
        return create_browser_capture(
            session,
            user_id,
            payload,
            request.headers.get("origin"),
        )
    except BrowserCaptureOriginError as error:
        raise HTTPException(status_code=403, detail="浏览器扩展来源不匹配") from error
    except (UnsafeResourceUrlError, ValueError) as error:
        raise HTTPException(status_code=422, detail="当前网页不支持收藏") from error


@router.post(
    "/browser-captures/exchange",
    response_model=BrowserCaptureContext,
    tags=["browser-captures"],
)
def exchange_browser_capture_route(
    payload: BrowserCaptureExchangeRequest,
    session: SessionDependency,
    user_id: UserDependency,
) -> BrowserCaptureContext:
    """由 Web 一次性换取扩展授权的网页附件。"""

    try:
        return exchange_browser_capture(session, user_id, payload.token)
    except BrowserCaptureNotFoundError as error:
        raise HTTPException(status_code=404, detail="网页授权不存在") from error
    except BrowserCaptureExpiredError as error:
        raise HTTPException(
            status_code=410,
            detail="网页授权已过期，请重新点击扩展",
        ) from error
    except BrowserCaptureConsumedError as error:
        raise HTTPException(status_code=409, detail="网页授权已经使用") from error


@router.post(
    "/browser-tabs/sync",
    response_model=BrowserTabSyncResponse,
    tags=["browser-tabs"],
)
def sync_browser_tabs_route(
    payload: BrowserTabSyncRequest,
    request: Request,
    session: SessionDependency,
    user_id: UserDependency,
) -> BrowserTabSyncResponse:
    """接收扩展同步的当前浏览器打开标签页快照。"""

    try:
        synced_count = sync_open_browser_tabs(
            session,
            user_id,
            payload,
            request.headers.get("origin"),
        )
    except BrowserCaptureOriginError as error:
        raise HTTPException(status_code=403, detail="浏览器扩展来源不匹配") from error
    except (ValueError, OSError) as error:
        raise HTTPException(status_code=422, detail="浏览器标签页快照无效") from error
    except OperationalError as error:
        if is_sqlite_lock_error(error):
            raise HTTPException(
                status_code=503,
                detail="浏览器标签页同步繁忙",
            ) from error
        raise
    return BrowserTabSyncResponse(synced_count=synced_count)


@router.get(
    "/browser-tabs/open",
    response_model=BrowserOpenTabListResponse,
    tags=["browser-tabs"],
)
def list_open_browser_tabs_route(
    session: SessionDependency,
    user_id: UserDependency,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> BrowserOpenTabListResponse:
    """读取当前浏览器正在打开、且可安全收藏的网页。"""

    items = list_open_browser_tabs(session, user_id, limit=limit)
    return BrowserOpenTabListResponse(
        items=[BrowserOpenTabRead.model_validate(item) for item in items]
    )


@router.post(
    "/browser-bookmarks/sync",
    response_model=BrowserBookmarkSyncResponse,
    tags=["browser-bookmarks"],
)
def sync_browser_bookmarks_route(
    payload: BrowserBookmarkSyncRequest,
    request: Request,
    session: SessionDependency,
    user_id: UserDependency,
) -> BrowserBookmarkSyncResponse:
    """接收扩展直接读取的当前浏览器书签树快照。"""

    try:
        snapshot = sync_browser_bookmarks(
            session,
            user_id,
            payload,
            request.headers.get("origin"),
        )
    except BrowserCaptureOriginError as error:
        raise HTTPException(status_code=403, detail="浏览器扩展来源不匹配") from error
    return BrowserBookmarkSyncResponse(
        synced_count=len(snapshot.bookmarks),
        truncated=snapshot.truncated,
        total_count=snapshot.total_count,
        revision=snapshot.revision,
    )


@router.post(
    "/browser-bookmarks/delta",
    response_model=BrowserBookmarkSyncResponse,
    tags=["browser-bookmarks"],
)
def sync_browser_bookmark_delta_route(
    payload: BrowserBookmarkDeltaSyncRequest,
    request: Request,
    session: SessionDependency,
    user_id: UserDependency,
) -> BrowserBookmarkSyncResponse:
    """应用扩展书签增量；版本落后时要求扩展重新上传完整快照。"""

    try:
        snapshot = sync_browser_bookmark_delta(
            session,
            user_id,
            payload,
            request.headers.get("origin"),
        )
    except BrowserBookmarkRevisionConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "bookmark_revision_conflict",
                "message": "书签快照已在其他设备更新，请重新同步",
            },
        ) from error
    except BrowserCaptureOriginError as error:
        raise HTTPException(status_code=403, detail="浏览器扩展来源不匹配") from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return BrowserBookmarkSyncResponse(
        synced_count=len(snapshot.bookmarks),
        truncated=snapshot.truncated,
        total_count=snapshot.total_count,
        revision=snapshot.revision,
    )


@router.get(
    "/browser-bookmarks/current",
    response_model=BrowserBookmarkSnapshotRead,
    tags=["browser-bookmarks"],
)
def read_browser_bookmarks_route(
    session: SessionDependency,
    user_id: UserDependency,
) -> BrowserBookmarkSnapshotRead:
    """向 Web 返回最近一次扩展同步的浏览器书签。"""

    return read_browser_bookmark_snapshot(session, user_id)


@router.post(
    "/browser-history/sync",
    response_model=BrowserHistorySyncResponse,
    tags=["browser-history"],
)
def sync_browser_history_route(
    payload: BrowserHistorySyncRequest,
    request: Request,
    response: Response,
    session: SessionDependency,
    user_id: UserDependency,
) -> BrowserHistorySyncResponse:
    """接收扩展上报的浏览器历史记录。"""

    # 设备 ID 同时写一份到 Cookie：扩展被卸载时 chrome.storage.local 会被清空，
    # 而 Cookie 不会，重装后靠它认出「还是这台机器」。
    # 由服务端下发 HttpOnly，避免页面脚本读取，也避开 Safari 对 JS Cookie
    # 的 7 天限制。
    cookie_device_id = request.cookies.get(HISTORY_DEVICE_COOKIE)
    try:
        result = sync_browser_history(
            session,
            user_id,
            payload,
            request.headers.get("origin"),
            cookie_device_id=cookie_device_id,
        )
    except BrowserHistoryOriginError as error:
        raise HTTPException(status_code=403, detail="浏览器扩展来源不匹配") from error
    if result.device_id and result.device_id != cookie_device_id:
        response.set_cookie(
            HISTORY_DEVICE_COOKIE,
            result.device_id,
            max_age=HISTORY_DEVICE_COOKIE_MAX_AGE,
            httponly=True,
            samesite="lax",
            # 扩展与 API 同站请求，无需跨站 Cookie。
            secure=request.url.scheme == "https",
            path="/",
        )
    return result


@router.get(
    "/browser-history",
    response_model=BrowserHistoryListResponse,
    tags=["browser-history"],
)
def list_browser_history_route(
    session: SessionDependency,
    user_id: UserDependency,
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
    days: Annotated[int | None, Query(ge=0, le=3650)] = None,
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
    tz_offset: Annotated[int | None, Query(ge=-840, le=840)] = None,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
    device_id: Annotated[str | None, Query(max_length=64)] = None,
) -> BrowserHistoryListResponse:
    """向 Web 返回浏览历史；默认 30 天，只有账号开启扩展搜索才放宽。

    ``days=0`` 表示不限时间，同样需要账号已打开「搜索更久的历史」。
    ``from`` / ``to`` 按本地日期精确筛选，优先于天数窗口；
    ``tz_offset`` 是浏览器时区相对 UTC 的分钟数，用来划分「某一天」。
    深翻页时改传上一页返回的 ``next_cursor``，查询开销不再随深度增长。
    ``device_id`` 只看某台设备；不传则按网址合并同一账号下所有设备。
    """

    return list_browser_history(
        session,
        user_id,
        query_text=q,
        limit=limit,
        offset=offset,
        days=days,
        date_from=date_from,
        date_to=date_to,
        tz_offset_minutes=tz_offset,
        cursor=cursor,
        device_id=device_id,
    )


@router.get(
    "/browser-history/settings",
    response_model=BrowserHistorySettingsRead,
    tags=["browser-history"],
)
def read_browser_history_settings_route(
    session: SessionDependency,
    user_id: UserDependency,
) -> BrowserHistorySettingsRead:
    """读取账号是否允许搜索更久的浏览历史。"""

    return BrowserHistorySettingsRead(
        extended_search_enabled=history_extended_search_enabled(session, user_id),
    )


@router.patch(
    "/browser-history/settings",
    response_model=BrowserHistorySettingsRead,
    tags=["browser-history"],
)
def update_browser_history_settings_route(
    payload: BrowserHistorySettingsUpdate,
    session: SessionDependency,
    user_id: UserDependency,
) -> BrowserHistorySettingsRead:
    """打开或关闭「搜索更久的历史」。"""

    return BrowserHistorySettingsRead(
        extended_search_enabled=update_history_extended_search(
            session,
            user_id,
            payload,
        ),
    )


@router.delete(
    "/browser-history",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["browser-history"],
)
def clear_browser_history_route(
    session: SessionDependency,
    user_id: UserDependency,
) -> Response:
    """清空当前账号的浏览历史；已收藏进资料库的网页不受影响。"""

    clear_browser_history(session, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch(
    "/browser-history/devices/{device_id}",
    response_model=BrowserHistoryDeviceRead,
    tags=["browser-history"],
)
def rename_browser_history_device_route(
    device_id: str,
    payload: BrowserHistoryDeviceUpdate,
    session: SessionDependency,
    user_id: UserDependency,
) -> BrowserHistoryDeviceRead:
    """给设备改名，便于区分两台同款电脑。"""

    try:
        state = rename_history_device(
            session,
            user_id,
            device_id,
            payload.device_name,
        )
    except HistoryDeviceNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="设备不存在。",
        ) from error
    return BrowserHistoryDeviceRead(
        device_id=state.device_id,
        device_name=state.device_name,
        total_count=state.total_count,
        synced_at=state.synced_at,
    )


@router.delete(
    "/browser-history/devices/{device_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["browser-history"],
)
def delete_browser_history_device_route(
    device_id: str,
    session: SessionDependency,
    user_id: UserDependency,
) -> Response:
    """删除一台设备及其历史，其他设备不受影响。"""

    try:
        delete_history_device(session, user_id, device_id)
    except HistoryDeviceNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="设备不存在。",
        ) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/browser-history/devices/{device_id}/merge",
    response_model=BrowserHistorySyncResponse,
    tags=["browser-history"],
)
def merge_browser_history_device_route(
    device_id: str,
    payload: BrowserHistoryDeviceMerge,
    session: SessionDependency,
    user_id: UserDependency,
) -> BrowserHistorySyncResponse:
    """把一台设备的历史并进另一台，用于确认「同一台机器重装」。"""

    try:
        moved, total = merge_history_devices(
            session,
            user_id,
            device_id,
            payload.target_device_id,
        )
    except HistoryDeviceNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="设备不存在。",
        ) from error
    except HistoryDeviceMergeError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="不能把设备合并到它自己。",
        ) from error
    return BrowserHistorySyncResponse(
        synced_count=moved,
        total_count=total,
        device_id=payload.target_device_id,
    )
