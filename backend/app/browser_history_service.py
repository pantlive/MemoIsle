"""浏览器浏览历史同步与查询业务。"""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, date, datetime, time, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

from sqlalchemy import (
    and_,
    delete,
    distinct,
    exists,
    func,
    or_,
    select,
    tuple_,
    update,
)
from sqlalchemy.orm import Session, aliased

from app.database import commit_with_retry
from app.models import BrowserHistoryEntry, BrowserHistorySyncState, User
from app.resource_lookup import existing_resource_urls
from app.resource_processing import validate_browser_tab_url
from app.schemas import (
    BrowserHistoryDayGroup,
    BrowserHistoryDeviceRead,
    BrowserHistoryEntryRead,
    BrowserHistoryListResponse,
    BrowserHistorySettingsUpdate,
    BrowserHistorySyncRequest,
    BrowserHistorySyncResponse,
)
from app.url_normalization import canonicalize_resource_url

# 历史记录长期保留，默认列表与搜索只覆盖最近 30 天，避免旧记录淹没最近浏览。
HISTORY_WINDOW_DAYS = 30
# 在设置里打开「搜索更久的历史」后可以选的窗口；0 表示不限时间。
HISTORY_WINDOWS = (90, 365, 0)
# 每页最多 1000 条；翻页没有总量上限，翻到哪算哪。
MAX_HISTORY_PAGE_SIZE = 1000
# 超过这个 offset 后，OFFSET 分页要先扫过前面所有行才能定位。
# 前端可以改用 next_cursor（按 (last_visited_at, id) 定位），代价与深度无关。
CURSOR_PAGING_OFFSET_THRESHOLD = 1000
# 前端时区偏移的合法范围（分钟），超出按 UTC 处理。
_MAX_TZ_OFFSET_MINUTES = 14 * 60


class BrowserHistoryOriginError(PermissionError):
    """扩展来源与声明的扩展标识不一致。"""


def history_url_key(page_url: str) -> str:
    """把规范化网址压成固定长度摘要，作为去重键。

    直接给 page_url 建唯一索引在 MySQL 上会超过索引长度上限，
    摘要同时也要能进 SQLite 的普通唯一约束。
    """

    return hashlib.sha256(page_url.encode("utf-8")).hexdigest()


def _as_utc(value: datetime) -> datetime:
    """兼容 SQLite 返回的无时区时间。"""

    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _local_day_key(value: datetime, offset_minutes: int) -> str:
    """把 UTC 访问时间换算成前端所在时区的日期（YYYY-MM-DD）。"""

    shifted = _as_utc(value) + timedelta(minutes=offset_minutes)
    return shifted.date().isoformat()


def encode_history_cursor(last_visited_at: datetime, entry_id: str) -> str:
    """把「上一页最后一行」的排序键编码成 URL 安全的游标。"""

    payload = json.dumps(
        [_as_utc(last_visited_at).isoformat(), entry_id],
        separators=(",", ":"),
    )
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")


def decode_history_cursor(value: str) -> tuple[datetime, str] | None:
    """解析游标；格式不对时返回 ``None``，由调用方退回 offset 分页。"""

    try:
        raw = base64.urlsafe_b64decode(value.encode("ascii")).decode("utf-8")
        parsed = json.loads(raw)
        visited_at = datetime.fromisoformat(str(parsed[0]))
        entry_id = str(parsed[1])
    except (ValueError, TypeError, KeyError, IndexError, UnicodeDecodeError):
        return None
    if not entry_id:
        return None
    return _as_utc(visited_at), entry_id


def _history_total(
    session: Session,
    user_id: str,
    device_id: str | None = None,
) -> int:
    """统计历史条数，只在首次同步或清空后调用。

    传 ``device_id`` 时只数这台设备，否则数整个账号。
    """

    query = (
        select(func.count())
        .select_from(BrowserHistoryEntry)
        .where(BrowserHistoryEntry.user_id == user_id)
    )
    if device_id is not None:
        query = query.where(BrowserHistoryEntry.device_id == device_id)
    return int(session.scalar(query) or 0)


def _sync_state(
    session: Session,
    user_id: str,
    device_id: str,
) -> BrowserHistorySyncState | None:
    """读取某台设备最近一次同步状态。"""

    return session.scalar(
        select(BrowserHistorySyncState).where(
            BrowserHistorySyncState.user_id == user_id,
            BrowserHistorySyncState.device_id == device_id,
        )
    )


MAX_DEVICE_ID_LENGTH = 64


def _derived_device_id(device_id: str, install_id: str) -> str:
    """为「同一指纹的另一台机器」派生一个稳定且不冲突的设备标识。

    用 install_id 参与计算，同一个安装重试时会得到同一个 ID，
    不会每次同步都新建一台设备。
    """

    suffix = install_id[:8] or uuid4().hex[:8]
    room = MAX_DEVICE_ID_LENGTH - len(suffix) - 1
    return f"{device_id[:room]}-{suffix}"


def resolve_history_device(
    session: Session,
    user_id: str,
    device_id: str,
    hardware_key: str,
    install_id: str,
    cookie_device_id: str | None = None,
) -> tuple[str, str | None]:
    """决定这次上报落在哪台设备上，并给出「疑似同一台机器」的候选。

    返回 ``(实际设备 ID, 疑似同一台机器的设备 ID)``。

    两种情况需要用户确认：

    1. device_id 已知，但 install_id 变了 —— 扩展按机器指纹算出的 ID
       被另一台同款电脑用了（或反过来），两台机器不能混在一起。
    2. device_id 未知，但指纹能对上已有设备 —— 多半是重装扩展后又回来，
       历史应该并回原来那台而不是新建一台。
    """

    state = _sync_state(session, user_id, device_id)
    if state is None and cookie_device_id:
        # 扩展被卸载重装时 chrome.storage.local 会被清空，随机 ID 随之丢失。
        # Cookie 存在浏览器里、卸载扩展不会删除，所以它能认出「还是这台机器」。
        # 由服务端读 Cookie 并回写设备 ID，扩展不需要申请 cookies 权限。
        #
        # 恢复条件：Cookie 指向的设备存在，且指纹与本次上报一致。
        #
        # 不能用 install_id 判断 —— 重装后它必然是新值，用它比对等于永远
        # 不恢复，Cookie 就白存了。指纹才是重装后仍然不变的那个信号。
        #
        # Cookie 由服务端写在**这台机器的浏览器**里，另一台电脑不会有它。
        # 所以「带着这个 Cookie、却报了一个陌生 ID」只可能是这台机器重装
        # 或换了扩展实例，直接恢复即可，不需要再比对指纹 ——
        # 比对指纹反而会把「同款电脑指纹相同」的正常情况误判。
        cookie_state = _sync_state(session, user_id, cookie_device_id)
        if cookie_state is not None:
            return cookie_state.device_id, None
    if state is None:
        if not hardware_key:
            return device_id, None
        candidate = session.scalar(
            select(BrowserHistorySyncState)
            .where(
                BrowserHistorySyncState.user_id == user_id,
                BrowserHistorySyncState.hardware_key == hardware_key,
            )
            .order_by(
                BrowserHistorySyncState.synced_at.asc(),
                BrowserHistorySyncState.id.asc(),
            )
            .limit(1),
        )
        return device_id, (candidate.device_id if candidate is not None else None)
    if install_id and state.install_id and install_id != state.install_id:
        # 同一指纹下换了安装：派一个独立 ID，两个安装各存各的历史。
        return _derived_device_id(device_id, install_id), state.device_id
    return device_id, None


def sync_browser_history(
    session: Session,
    user_id: str,
    payload: BrowserHistorySyncRequest,
    request_origin: str | None,
    url_validator=validate_browser_tab_url,
    cookie_device_id: str | None = None,
) -> BrowserHistorySyncResponse:
    """把扩展上报的浏览记录按网址合并进历史表。

    同一网址只保留一行，重复访问累加 ``visit_count`` 并刷新最后访问时间，
    因此扩展可以放心重发最近一段历史而不必精确去重。
    """

    expected_origin = f"chrome-extension://{payload.extension_id}"
    if request_origin != expected_origin:
        raise BrowserHistoryOriginError

    now = datetime.now(UTC)
    merged: dict[str, tuple[str, str, str | None, datetime, int]] = {}
    for visit in payload.visits:
        try:
            page_url = url_validator(visit.page_url)
        except (OSError, ValueError):
            # chrome://、file://、本地地址不进入历史列表。
            continue
        try:
            normalized_url = canonicalize_resource_url(page_url)
        except ValueError:
            continue
        visited_at = visit.visited_at or now
        visited_at = _as_utc(visited_at)
        if visited_at > now:
            # 浏览器时钟快于服务端时不写未来时间，避免排序出现「刚访问过」。
            visited_at = now
        key = history_url_key(normalized_url)
        previous = merged.get(key)
        if previous is None:
            merged[key] = (
                normalized_url,
                visit.page_title,
                visit.favicon_url,
                visited_at,
                visit.visit_count,
            )
            continue
        # 同一批里重复出现时保留更近的一次访问和更大的累计次数。
        merged[key] = (
            normalized_url,
            visit.page_title or previous[1],
            visit.favicon_url or previous[2],
            max(previous[3], visited_at),
            max(previous[4], visit.visit_count),
        )

    # 先确定归属设备：写条目之前就要定下来，否则会写错设备。
    device_id, possible_same_device_id = resolve_history_device(
        session,
        user_id,
        payload.device_id or "legacy",
        payload.hardware_key,
        payload.install_id,
        cookie_device_id,
    )
    if payload.replace_all:
        # 用户在浏览器里清空历史后，只清「这台设备」的记录。
        # 早期版本这里漏了 device_id，会误删同一账号其他电脑的历史。
        condition = (BrowserHistoryEntry.user_id == user_id) & (
            BrowserHistoryEntry.device_id == device_id
        )
        if merged:
            condition = condition & BrowserHistoryEntry.url_key.not_in(list(merged))
        session.execute(delete(BrowserHistoryEntry).where(condition))

    new_url_keys: list[str] = []
    if merged:
        # 去重范围限定在同一台设备：两台电脑访问同一网址各存一行。
        existing = {
            entry.url_key: entry
            for entry in session.scalars(
                select(BrowserHistoryEntry).where(
                    BrowserHistoryEntry.user_id == user_id,
                    BrowserHistoryEntry.device_id == device_id,
                    BrowserHistoryEntry.url_key.in_(list(merged)),
                )
            ).all()
        }
        for key, value in merged.items():
            page_url, title, favicon_url, visited_at, visit_count = value
            entry = existing.get(key)
            if entry is None:
                session.add(
                    BrowserHistoryEntry(
                        id=str(uuid4()),
                        user_id=user_id,
                        device_id=device_id,
                        url_key=key,
                        page_url=page_url,
                        page_title=title,
                        favicon_url=favicon_url,
                        visit_count=visit_count,
                        first_visited_at=visited_at,
                        last_visited_at=visited_at,
                    )
                )
                new_url_keys.append(key)
                continue
            entry.page_url = page_url
            # 标题和图标取最近一次访问的值，扩展上报的旧数据不覆盖新数据。
            if title:
                entry.page_title = title
            if favicon_url:
                entry.favicon_url = favicon_url
            # 浏览器给的是累计次数，重复上报同一段历史不会把计数越加越大。
            entry.visit_count = max(entry.visit_count, visit_count)
            entry.first_visited_at = min(
                _as_utc(entry.first_visited_at),
                visited_at,
            )
            entry.last_visited_at = max(
                _as_utc(entry.last_visited_at),
                visited_at,
            )

    state = _sync_state(session, user_id, device_id)
    if state is None:
        state = BrowserHistorySyncState(
            id=str(uuid4()),
            user_id=user_id,
            device_id=device_id,
            hardware_key=payload.hardware_key,
            install_id=payload.install_id,
            extension_id=payload.extension_id,
            device_name=payload.device_name,
            total_count=0,
        )
        session.add(state)
    state.synced_at = now
    state.extension_id = payload.extension_id
    if payload.hardware_key:
        state.hardware_key = payload.hardware_key
    if payload.install_id:
        state.install_id = payload.install_id
    if payload.device_name:
        # 设备名可能变（换了浏览器版本），跟着最后一次上报走。
        state.device_name = payload.device_name
    # 每次同步都 count 全表在历史几十万条时会明显变慢；
    # 首轮或清空后校准一次，其余情况只累加本次新增的网址数。
    if not state.total_count or payload.replace_all:
        state.total_count = _history_total(session, user_id, device_id)
    else:
        state.total_count += len(new_url_keys)
    commit_with_retry(session)
    return BrowserHistorySyncResponse(
        synced_count=len(merged),
        total_count=state.total_count,
        device_id=device_id,
        possible_same_device_id=possible_same_device_id,
    )


def history_extended_search_enabled(session: Session, user_id: str) -> bool:
    """账号是否允许搜索最近 30 天之前的浏览历史。"""

    user = session.get(User, user_id)
    return bool(user is not None and user.browser_history_extended_search)


def resolve_history_window(days: int | None, extended_enabled: bool) -> int | None:
    """把请求的窗口收敛到账号允许的范围。

    未开启扩展搜索时固定 30 天；开启后可选 30/90/365 天或全部
    （``0`` 表示不限时间，返回 ``None``）。其他值一律退回默认窗口，
    避免手改参数绕过设置翻出很久以前的数据。
    """

    if not extended_enabled:
        return HISTORY_WINDOW_DAYS
    if days is None:
        return HISTORY_WINDOW_DAYS
    if days == 0:
        return None
    if days in HISTORY_WINDOWS:
        return days
    return HISTORY_WINDOW_DAYS


def update_history_extended_search(
    session: Session,
    user_id: str,
    payload: BrowserHistorySettingsUpdate,
) -> bool:
    """保存「搜索更久的历史」开关。"""

    user = session.get(User, user_id)
    if user is None:
        # 开发模式还没建账号时补一条最小用户记录。
        user = User(id=user_id, display_name="本地开发用户")
        session.add(user)
    user.browser_history_extended_search = payload.extended_search_enabled
    commit_with_retry(session)
    session.refresh(user)
    return bool(user.browser_history_extended_search)


def _normalize_offset_minutes(value: int | None) -> int:
    """把前端的时区偏移收敛到合法范围，越界按 UTC 处理。"""

    if value is None:
        return 0
    return max(-_MAX_TZ_OFFSET_MINUTES, min(_MAX_TZ_OFFSET_MINUTES, value))


def _local_day_bounds(
    day: date,
    offset_minutes: int,
) -> tuple[datetime, datetime]:
    """把某个本地日期换算成 UTC 的起止区间。"""

    shift = timedelta(minutes=offset_minutes)
    start = datetime.combine(day, time.min, tzinfo=UTC) - shift
    return start, start + timedelta(days=1)


def _history_conditions(
    user_id: str,
    window_days: int | None,
    query_text: str | None,
    date_from: date | None,
    date_to: date | None,
    offset_minutes: int,
    device_id: str | None = None,
) -> list:
    """拼出历史查询条件；日期、关键词和设备可以叠加。"""

    conditions = [BrowserHistoryEntry.user_id == user_id]
    if device_id:
        conditions.append(BrowserHistoryEntry.device_id == device_id)
    if date_from is not None or date_to is not None:
        # 显式选了日期就按它查，不再叠加默认的 30 天窗口。
        if date_from is not None:
            conditions.append(
                BrowserHistoryEntry.last_visited_at
                >= _local_day_bounds(date_from, offset_minutes)[0],
            )
        if date_to is not None:
            conditions.append(
                BrowserHistoryEntry.last_visited_at
                < _local_day_bounds(date_to, offset_minutes)[1],
            )
    elif window_days is not None:
        conditions.append(
            BrowserHistoryEntry.last_visited_at
            >= datetime.now(UTC) - timedelta(days=window_days),
        )
    contains = (query_text or "").strip()
    if contains:
        escaped = (
            contains.replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )
        pattern = f"%{escaped}%"
        conditions.append(
            BrowserHistoryEntry.page_title.ilike(pattern, escape="\\")
            | BrowserHistoryEntry.page_url.ilike(pattern, escape="\\"),
        )
    return conditions


def _merged_conditions(conditions: list) -> list:
    """合并视图的筛选条件：每个网址只保留「最新的一行」。

    用 NOT EXISTS 排除存在更新行的记录，一个 url_key 恰好剩一行，
    于是 (last_visited_at, id) 的游标分页天然精确，不会跨页重复。
    索引 (user_id, url_key, last_visited_at) 让子查询走索引定位，
    实测 10 万行 0.38 ms，远快于 GROUP BY 的 73 ms。
    """

    newer = aliased(BrowserHistoryEntry)
    return [
        *conditions,
        ~exists(
            select(1)
            .select_from(newer)
            .where(
                newer.user_id == BrowserHistoryEntry.user_id,
                newer.url_key == BrowserHistoryEntry.url_key,
                or_(
                    newer.last_visited_at > BrowserHistoryEntry.last_visited_at,
                    and_(
                        newer.last_visited_at == BrowserHistoryEntry.last_visited_at,
                        newer.id > BrowserHistoryEntry.id,
                    ),
                ),
            )
            .correlate(BrowserHistoryEntry),
        ),
    ]


def _merged_entry(entry: object, counts: tuple[int, datetime] | None) -> object:
    """把「最新一行」补成合并后的条目：次数求和、首访取最早。"""

    if counts is None:
        return entry
    total, first_visited_at = counts
    return SimpleNamespace(
        id=entry.id,
        url_key=entry.url_key,
        page_url=entry.page_url,
        page_title=entry.page_title,
        favicon_url=entry.favicon_url,
        visit_count=total or entry.visit_count,
        first_visited_at=(
            first_visited_at
            if first_visited_at is not None
            and _as_utc(first_visited_at) < _as_utc(entry.first_visited_at)
            else entry.first_visited_at
        ),
        last_visited_at=entry.last_visited_at,
        device_id=entry.device_id,
    )


def _merged_visit_counts(
    session: Session,
    user_id: str,
    conditions: list,
    url_keys: list[str],
) -> dict[str, tuple[int, datetime]]:
    """按网址汇总跨设备的访问次数与最早访问时间。

    只查当前这页出现的网址（不超过一页），走
    (user_id, url_key, last_visited_at) 索引逐条定位，代价与库大小无关。
    """

    if not url_keys:
        return {}
    rows = session.execute(
        select(
            BrowserHistoryEntry.url_key,
            func.sum(BrowserHistoryEntry.visit_count),
            func.min(BrowserHistoryEntry.first_visited_at),
        )
        .where(*conditions, BrowserHistoryEntry.url_key.in_(url_keys))
        .group_by(BrowserHistoryEntry.url_key),
    ).all()
    return {
        row[0]: (int(row[1] or 0), row[2])
        for row in rows
    }


def _possible_same_devices(
    device_states: list[BrowserHistorySyncState],
) -> dict[str, str]:
    """找出指纹相同的设备，给出「疑似同一台机器」的候选。

    指纹相同只有两种可能：同一台机器重装，或者两台配置完全一样的电脑。
    究竟哪种只能由用户判断，这里只负责把候选指出来。
    """

    by_hardware: dict[str, list[BrowserHistorySyncState]] = {}
    for state in device_states:
        if not state.hardware_key:
            # 老版本扩展没有指纹，不参与判断，避免误报。
            continue
        by_hardware.setdefault(state.hardware_key, []).append(state)
    hints: dict[str, str] = {}
    for group in by_hardware.values():
        if len(group) < 2:
            continue
        # 按创建先后排，最早的当作「原来那台」，其余都指向它。
        ordered = sorted(group, key=lambda item: (item.synced_at, item.id))
        original = ordered[0]
        for state in ordered[1:]:
            hints[state.device_id] = original.device_id
    return hints


def list_browser_history(
    session: Session,
    user_id: str,
    query_text: str | None = None,
    limit: int = 50,
    offset: int = 0,
    days: int | None = HISTORY_WINDOW_DAYS,
    date_from: date | None = None,
    date_to: date | None = None,
    tz_offset_minutes: int | None = None,
    cursor: str | None = None,
    device_id: str | None = None,
) -> BrowserHistoryListResponse:
    """读取浏览历史，按访问日期分组返回，并标出已收藏的网址。

    默认窗口是最近 30 天。更早的记录仍然留在库里，
    只有账号在设置里打开「搜索更久的历史」后才会进入列表和搜索。
    传入 ``date_from`` / ``date_to`` 时按本地日期精确查询，优先于天数窗口。
    每页最多 ``MAX_HISTORY_PAGE_SIZE`` 条，不设总量上限。

    不传 ``device_id`` 时按网址合并所有设备：同一网址只出现一行，
    访问次数是各设备之和，时间取最近一次，设备取最近访问的那台。
    传了就只看这台设备。

    分页有两种方式：``offset``（浅翻页便宜）和 ``cursor``（深翻页恒定开销）。
    传了 ``cursor`` 就忽略 ``offset``，按 ``(last_visited_at, id)`` 行值比较定位。
    """

    extended_enabled = history_extended_search_enabled(session, user_id)
    window_days = resolve_history_window(days, extended_enabled)
    offset_minutes = _normalize_offset_minutes(tz_offset_minutes)

    conditions = _history_conditions(
        user_id,
        window_days,
        query_text,
        date_from,
        date_to,
        offset_minutes,
        device_id,
    )
    # 每页条数由调用方决定，但不超过单页上限。
    page_size = min(max(limit, 1), MAX_HISTORY_PAGE_SIZE)
    page_offset = max(offset, 0)
    # 不筛选设备时同一网址可能来自多台电脑，需要按 url_key 合并成一行。
    merge_devices = not device_id

    query = select(
        BrowserHistoryEntry.id,
        BrowserHistoryEntry.url_key,
        BrowserHistoryEntry.page_url,
        BrowserHistoryEntry.page_title,
        BrowserHistoryEntry.favicon_url,
        BrowserHistoryEntry.visit_count,
        BrowserHistoryEntry.first_visited_at,
        BrowserHistoryEntry.last_visited_at,
        BrowserHistoryEntry.device_id,
    ).where(
        *(
            _merged_conditions(conditions)
            if merge_devices
            else conditions
        ),
    )
    cursor_key = decode_history_cursor(cursor) if cursor else None
    if cursor_key is not None:
        # 行值比较让 (last_visited_at, id) 整体走索引范围，与翻到多深无关。
        # 拆成 OR 会退化成整段扫描，实测在 50 万条时慢 40 倍。
        query = query.where(
            tuple_(BrowserHistoryEntry.last_visited_at, BrowserHistoryEntry.id)
            < tuple_(cursor_key[0], cursor_key[1]),
        )
    query = query.order_by(
        BrowserHistoryEntry.last_visited_at.desc(),
        BrowserHistoryEntry.id.desc(),
    )
    if cursor_key is None:
        # offset 分页：浅翻便宜，深翻要先跳过前面所有行。
        query = query.offset(page_offset)
    # 合并模式每个网址已只剩一行，取 page_size+1 就能判断有没有下一页。
    rows = session.execute(query.limit(page_size + 1)).all()
    has_more = len(rows) > page_size
    entries = rows[:page_size]
    if merge_devices and entries:
        # 访问次数要跨设备相加，只对当前这页的网址补一次汇总查询。
        counts = _merged_visit_counts(
            session,
            user_id,
            conditions,
            [entry.url_key for entry in entries],
        )
        entries = [
            _merged_entry(entry, counts.get(entry.url_key))
            for entry in entries
        ]
    cursor_anchor = entries[-1] if entries else None
    if not has_more:
        # 已经是最后一页，总数就是「已翻过的 + 本页」，不必再 count 全表。
        total = page_offset + len(entries)
    elif merge_devices:
        # 合并模式下总数要按网址去重，count(DISTINCT) 在几十万行时要 20 ms，
        # 只在确实有下一页时才付这个代价。
        total = int(
            session.scalar(
                select(func.count(distinct(BrowserHistoryEntry.url_key)))
                .select_from(BrowserHistoryEntry)
                .where(*conditions)
            )
            or 0,
        )
    else:
        # 只有确实还有下一页时才需要精确总数，用来显示进度和下一页起点。
        total = int(
            session.scalar(
                select(func.count())
                .select_from(BrowserHistoryEntry)
                .where(*conditions)
            )
            or 0,
        )

    # 设备列表：既用于条目的 device_name，也返回给前端做筛选。
    device_states = session.scalars(
        select(BrowserHistorySyncState)
        .where(BrowserHistorySyncState.user_id == user_id)
        .order_by(BrowserHistorySyncState.synced_at.desc()),
    ).all()
    device_names = {state.device_id: state.device_name for state in device_states}
    duplicate_hints = _possible_same_devices(device_states)

    # 只查当前这页出现的网址，避免每次翻页都把整个资料库读一遍。
    existing_urls = existing_resource_urls(
        session,
        user_id,
        canonical_urls={entry.page_url for entry in entries},
    )
    items: list[BrowserHistoryEntryRead] = []
    groups: list[BrowserHistoryDayGroup] = []
    for entry in entries:
        # 历史入库前已规范化，可直接与资料库的规范网址对照。
        saved_memo_id = existing_urls.get(entry.page_url)
        item = BrowserHistoryEntryRead(
            id=UUID(entry.id),
            page_url=entry.page_url,
            page_title=entry.page_title,
            favicon_url=entry.favicon_url,
            visit_count=entry.visit_count,
            first_visited_at=entry.first_visited_at,
            last_visited_at=entry.last_visited_at,
            saved_memo_id=UUID(saved_memo_id) if saved_memo_id else None,
            device_id=entry.device_id,
            device_name=device_names.get(entry.device_id, ""),
        )
        items.append(item)
        day_key = _local_day_key(entry.last_visited_at, offset_minutes)
        if groups and groups[-1].date == day_key:
            groups[-1].items.append(item)
            groups[-1].count += 1
        else:
            groups.append(
                BrowserHistoryDayGroup(date=day_key, count=1, items=[item]),
            )

    state = device_states[0] if device_states else None
    # offset 字段表示「本页从第几条开始」，游标分页时为 0。
    # 两种分页各自给出对应的下一页入口，前端按有没有 next_cursor 走。
    next_cursor = None
    if has_more and cursor_anchor is not None:
        # 该行是本页最后一行的原始行；合并视图下它也是该网址最新的一行。
        next_cursor = encode_history_cursor(
            cursor_anchor.last_visited_at,
            cursor_anchor.id,
        )
    return BrowserHistoryListResponse(
        extension_connected=state is not None,
        synced_at=state.synced_at if state is not None else None,
        total_count=total,
        items=items,
        days=groups,
        # 返回实际生效的窗口，前端据此显示「最近 N 天」或「全部时间」。
        window_days=window_days,
        extended_search_enabled=extended_enabled,
        # 分页信息：前端据此启用「下一页」并显示计数。
        page_size=page_size,
        offset=page_offset if cursor_key is None else 0,
        has_more=has_more,
        # 游标分页时不提供 offset 入口，避免前端两种模式混用导致跳行。
        next_offset=(
            page_offset + len(entries)
            if has_more and cursor_key is None
            else None
        ),
        next_cursor=next_cursor,
        devices=[
            BrowserHistoryDeviceRead(
                device_id=item.device_id,
                device_name=item.device_name,
                total_count=item.total_count,
                synced_at=item.synced_at,
                possible_same_device_id=duplicate_hints.get(item.device_id),
            )
            for item in device_states
        ],
        device_id=device_id or None,
    )


class HistoryDeviceNotFoundError(LookupError):
    """设备不存在或不属于当前账号。"""


class HistoryDeviceMergeError(ValueError):
    """合并参数不合法，例如把自己并给自己。"""


def _require_device(
    session: Session,
    user_id: str,
    device_id: str,
) -> BrowserHistorySyncState:
    """取出一台属于该账号的设备，不存在就报错。"""

    state = _sync_state(session, user_id, device_id)
    if state is None:
        raise HistoryDeviceNotFoundError
    return state


def rename_history_device(
    session: Session,
    user_id: str,
    device_id: str,
    device_name: str,
) -> BrowserHistorySyncState:
    """给设备改名，方便区分两台同款电脑。"""

    state = _require_device(session, user_id, device_id)
    state.device_name = device_name
    commit_with_retry(session)
    return state


def delete_history_device(session: Session, user_id: str, device_id: str) -> int:
    """删除一台设备及其全部历史，返回删除条数。

    重装扩展后可能留下再也同步不到的旧设备，需要能单独清理。
    """

    _require_device(session, user_id, device_id)
    deleted = int(
        session.scalar(
            select(func.count())
            .select_from(BrowserHistoryEntry)
            .where(
                BrowserHistoryEntry.user_id == user_id,
                BrowserHistoryEntry.device_id == device_id,
            ),
        )
        or 0,
    )
    session.execute(
        delete(BrowserHistoryEntry).where(
            BrowserHistoryEntry.user_id == user_id,
            BrowserHistoryEntry.device_id == device_id,
        ),
    )
    session.execute(
        delete(BrowserHistorySyncState).where(
            BrowserHistorySyncState.user_id == user_id,
            BrowserHistorySyncState.device_id == device_id,
        ),
    )
    commit_with_retry(session)
    return deleted


def merge_history_devices(
    session: Session,
    user_id: str,
    source_device_id: str,
    target_device_id: str,
) -> tuple[int, int]:
    """把一台设备的历史并进另一台，返回 ``(搬运条数, 目标设备总条数)``。

    用户在界面上确认「这是同一台机器重装」后调用：同一网址累加访问次数、
    时间取并集，只属于来源设备的网址改归目标设备，来源设备随之消失。
    用批量 SQL 完成，几十万条也能一次跑完。
    """

    if source_device_id == target_device_id:
        raise HistoryDeviceMergeError
    _require_device(session, user_id, source_device_id)
    _require_device(session, user_id, target_device_id)

    source = aliased(BrowserHistoryEntry)
    # 同一网址在两台设备上都有：把来源的累计次数和首末时间并进目标行。
    # SQLite 的 MIN/MAX 支持多参数，直接取两者极值。
    session.execute(
        update(BrowserHistoryEntry)
        .where(
            BrowserHistoryEntry.user_id == user_id,
            BrowserHistoryEntry.device_id == target_device_id,
            exists(
                select(1)
                .select_from(source)
                .where(
                    source.user_id == BrowserHistoryEntry.user_id,
                    source.device_id == source_device_id,
                    source.url_key == BrowserHistoryEntry.url_key,
                )
                .correlate(BrowserHistoryEntry),
            ),
        )
        .values(
            visit_count=BrowserHistoryEntry.visit_count
            + select(func.coalesce(func.sum(source.visit_count), 0))
            .where(
                source.user_id == BrowserHistoryEntry.user_id,
                source.device_id == source_device_id,
                source.url_key == BrowserHistoryEntry.url_key,
            )
            .correlate(BrowserHistoryEntry)
            .scalar_subquery(),
            first_visited_at=func.min(
                BrowserHistoryEntry.first_visited_at,
                select(func.min(source.first_visited_at))
                .where(
                    source.user_id == BrowserHistoryEntry.user_id,
                    source.device_id == source_device_id,
                    source.url_key == BrowserHistoryEntry.url_key,
                )
                .correlate(BrowserHistoryEntry)
                .scalar_subquery(),
            ),
            last_visited_at=func.max(
                BrowserHistoryEntry.last_visited_at,
                select(func.max(source.last_visited_at))
                .where(
                    source.user_id == BrowserHistoryEntry.user_id,
                    source.device_id == source_device_id,
                    source.url_key == BrowserHistoryEntry.url_key,
                )
                .correlate(BrowserHistoryEntry)
                .scalar_subquery(),
            ),
        ),
    )
    # 目标设备已有的网址，来源里的重复行直接删掉。
    session.execute(
        delete(BrowserHistoryEntry).where(
            BrowserHistoryEntry.user_id == user_id,
            BrowserHistoryEntry.device_id == source_device_id,
            BrowserHistoryEntry.url_key.in_(
                select(BrowserHistoryEntry.url_key).where(
                    BrowserHistoryEntry.user_id == user_id,
                    BrowserHistoryEntry.device_id == target_device_id,
                ),
            ),
        ),
    )
    # 剩下的都是目标设备没有的网址，改归属即可。
    moved = int(
        session.scalar(
            select(func.count())
            .select_from(BrowserHistoryEntry)
            .where(
                BrowserHistoryEntry.user_id == user_id,
                BrowserHistoryEntry.device_id == source_device_id,
            ),
        )
        or 0,
    )
    session.execute(
        update(BrowserHistoryEntry)
        .where(
            BrowserHistoryEntry.user_id == user_id,
            BrowserHistoryEntry.device_id == source_device_id,
        )
        .values(device_id=target_device_id),
    )

    session.execute(
        delete(BrowserHistorySyncState).where(
            BrowserHistorySyncState.user_id == user_id,
            BrowserHistorySyncState.device_id == source_device_id,
        ),
    )
    target = _require_device(session, user_id, target_device_id)
    # 合并后条数变了，重新校准。
    target.total_count = _history_total(session, user_id, target_device_id)
    commit_with_retry(session)
    return moved, target.total_count


def clear_browser_history(session: Session, user_id: str) -> int:
    """删除当前账号的全部浏览历史，返回删除条数。

    只清历史记录，不动已经收藏进资料库的网页。
    """

    # 批量 DELETE：几条 SQL 就能清空几万条，不必逐条加载成 ORM 对象。
    removed = session.execute(
        delete(BrowserHistoryEntry).where(BrowserHistoryEntry.user_id == user_id),
    ).rowcount
    session.execute(
        delete(BrowserHistorySyncState).where(
            BrowserHistorySyncState.user_id == user_id,
        ),
    )
    commit_with_retry(session)
    return int(removed or 0)
