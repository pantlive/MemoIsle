import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  ApiError,
  clearBrowserHistory,
  createMemo,
  deleteBrowserHistoryDevice,
  listBrowserHistory,
  mergeBrowserHistoryDevice,
  renameBrowserHistoryDevice,
  syncBrowserExtension,
} from "./api";
import ResourceMonogram from "./ResourceIcon";
import type {
  BrowserHistoryDevice,
  BrowserHistoryEntry,
  BrowserHistoryListResponse,
  Memo,
} from "./types";
import { sourceHost } from "./webUrl";
import Icon from "./Icon";

// 每页条数；服务端单页上限 1000，翻页没有总量限制。
const PAGE_SIZE = 200;
// 默认只展示最近 30 天；在设置里打开「搜索更久的历史」后才能换更长的窗口。
const DEFAULT_WINDOW_DAYS = 30;
const SEARCH_DEBOUNCE_MS = 250;

// 窗口选项：0 表示不限时间。
const WINDOW_OPTIONS: Array<{ value: number; label: string }> = [
  { value: 30, label: "最近 30 天" },
  { value: 90, label: "最近 90 天" },
  { value: 365, label: "最近一年" },
  { value: 0, label: "全部时间" },
];

const dayFormatter = new Intl.DateTimeFormat("zh-CN", {
  year: "numeric",
  month: "long",
  day: "numeric",
  weekday: "short",
});

// 把 YYYY-MM-DD 变成「10月21日 周二」，跨年时也带上年份。
function formatDayLabel(value: string): string {
  const [year, month, day] = value.split("-").map(Number);
  if (!year || !month || !day) {
    return value;
  }
  try {
    return dayFormatter.format(new Date(year, month - 1, day));
  } catch {
    return value;
  }
}

// 把 ISO 时间换算成本地日期，与服务端分块用的时区一致。
function localDayKey(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value.slice(0, 10);
  }
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

function todayInputValue(): string {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${month}-${day}`;
}

function windowLabel(days: number | null): string {
  if (days === null) {
    return "全部时间";
  }
  return days === 365 ? "最近一年" : `最近 ${days} 天`;
}

const visitedFormatter = new Intl.DateTimeFormat("zh-CN", {
  month: "numeric",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

function formatVisited(value: string): string {
  try {
    return visitedFormatter.format(new Date(value));
  } catch {
    return value;
  }
}

function describeChange(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return fallback;
}

interface BrowserHistoryDialogProps {
  onClose: () => void;
  /** 新收藏成功或定位到已有资料后回调，用于刷新列表与计数。 */
  onSaved: (memo: Memo) => void;
  /** 点击「已收藏」时打开资料库里对应的条目。 */
  onOpenSaved: (memoId: string) => void;
  /** 打开设置页，用来开启「搜索更久的历史」。 */
  onOpenSettings: () => void;
}

export default function BrowserHistoryDialog({
  onClose,
  onSaved,
  onOpenSaved,
  onOpenSettings,
}: BrowserHistoryDialogProps) {
  const [snapshot, setSnapshot] = useState<BrowserHistoryListResponse | null>(null);
  const [entries, setEntries] = useState<BrowserHistoryEntry[]>([]);
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  // 当前选择的时间窗口；是否真的放宽由服务端按账号设置决定。
  const [windowDays, setWindowDays] = useState(DEFAULT_WINDOW_DAYS);
  // 按日期精确查询；两个都为空时用上面的天数窗口。
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  // 按设备筛选；空表示合并同一账号下的所有电脑。
  const [deviceFilter, setDeviceFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState("");
  const [savingUrl, setSavingUrl] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const requestIdRef = useRef(0);
  const savedUrlsRef = useRef<Map<string, string>>(new Map());

  useEffect(() => {
    const timer = window.setTimeout(
      () => setDebouncedSearch(search.trim()),
      SEARCH_DEBOUNCE_MS,
    );
    return () => window.clearTimeout(timer);
  }, [search]);

  const loadHistory = useCallback(async () => {
    const requestId = ++requestIdRef.current;
    setLoading(true);
    setError("");
    try {
      const response = await listBrowserHistory({
        query: debouncedSearch || undefined,
        days: windowDays,
        limit: PAGE_SIZE,
        dateFrom: dateFrom || undefined,
        dateTo: dateTo || dateFrom || undefined,
        deviceId: deviceFilter || undefined,
      });
      if (requestId !== requestIdRef.current) {
        return;
      }
      setSnapshot(response);
      setEntries(response.items);
      // 服务端可能把窗口收敛到 30 天（例如开关刚被关掉），让选择器跟随实际值。
      const applied = response.window_days ?? 0;
      if (response.extended_search_enabled && applied !== windowDays) {
        setWindowDays(applied);
      }
    } catch (loadError) {
      if (requestId !== requestIdRef.current) {
        return;
      }
      setError(describeChange(loadError, "读取浏览历史失败。"));
      setSnapshot(null);
      setEntries([]);
    } finally {
      if (requestId === requestIdRef.current) {
        setLoading(false);
      }
    }
  }, [debouncedSearch, windowDays, dateFrom, dateTo, deviceFilter]);

  useEffect(() => {
    // 首次打开面板时唤醒扩展，确保刚登录或刚重载也能读到最新记录。
    void syncBrowserExtension();
  }, []);

  useEffect(() => {
    void loadHistory();
  }, [loadHistory]);

  const loadMore = async () => {
    if (loadingMore) {
      return;
    }
    setLoadingMore(true);
    setError("");
    try {
      // 有 next_cursor 就走游标：深翻页开销与翻到多深无关。
      // 没有游标（旧服务端或浅翻）才退回 offset。
      const nextCursor = snapshot?.next_cursor ?? null;
      const response = await listBrowserHistory({
        query: debouncedSearch || undefined,
        days: windowDays,
        limit: PAGE_SIZE,
        // 用服务端给的下一页起点，避免本地去重后 offset 偏移错位。
        offset: nextCursor ? undefined : snapshot?.next_offset ?? entries.length,
        cursor: nextCursor ?? undefined,
        dateFrom: dateFrom || undefined,
        dateTo: dateTo || dateFrom || undefined,
        deviceId: deviceFilter || undefined,
      });
      setSnapshot(response);
      // 分页期间历史可能又新增，按网址去重避免重复行。
      setEntries((current) => {
        const seen = new Set(current.map((entry) => entry.page_url));
        return [
          ...current,
          ...response.items.filter((entry) => !seen.has(entry.page_url)),
        ];
      });
    } catch (loadError) {
      setError(describeChange(loadError, "继续读取浏览历史失败。"));
    } finally {
      setLoadingMore(false);
    }
  };

  const saveEntry = async (entry: BrowserHistoryEntry) => {
    // 已收藏时按钮改为「查看资料」，这里只处理首次收藏。
    if (entry.saved_memo_id || savedUrlsRef.current.has(entry.page_url)) {
      return;
    }
    setSavingUrl(entry.page_url);
    setError("");
    setNotice("");
    try {
      const title = entry.page_title.trim() || sourceHost(entry.page_url);
      const memo = await createMemo({
        type: "resource",
        body: entry.page_url,
        source_url: entry.page_url,
        source_title: entry.page_title.trim() || undefined,
        tags: [],
      });
      savedUrlsRef.current.set(entry.page_url, memo.id);
      setEntries((current) =>
        current.map((item) =>
          item.page_url === entry.page_url
            ? { ...item, saved_memo_id: memo.id }
            : item,
        ),
      );
      setNotice(`已把「${title}」收进资料库。`);
      onSaved(memo);
    } catch (saveError) {
      if (
        saveError instanceof ApiError &&
        saveError.code === "duplicate_resource" &&
        saveError.current
      ) {
        // 其他设备/窗口先收藏过，定位到已有条目而不是报错。
        const existing = saveError.current;
        savedUrlsRef.current.set(entry.page_url, existing.id);
        setEntries((current) =>
          current.map((item) =>
            item.page_url === entry.page_url
              ? { ...item, saved_memo_id: existing.id }
              : item,
          ),
        );
        setNotice("这条网页已经在资料库里，已定位到原有条目。");
        onSaved(existing);
      } else {
        setError(describeChange(saveError, "收藏这条浏览记录失败。"));
      }
    } finally {
      setSavingUrl(null);
    }
  };

  const savedCount = useMemo(
    () => entries.filter((entry) => entry.saved_memo_id).length,
    [entries],
  );
  // 优先用服务端分好的块；翻页时按日期把新条目并进已有的块。
  const groupedEntries = useMemo(() => {
    const map = new Map<string, BrowserHistoryEntry[]>();
    for (const entry of entries) {
      const key = localDayKey(entry.last_visited_at);
      const bucket = map.get(key);
      if (bucket) {
        bucket.push(entry);
      } else {
        map.set(key, [entry]);
      }
    }
    return [...map.entries()]
      .sort((left, right) => (left[0] < right[0] ? 1 : -1))
      .map(([date, items]) => ({ date, items }));
  }, [entries]);
  // 服务端用 offset 翻页，翻到哪算哪，没有总量上限。
  const hasMore = snapshot?.has_more ?? false;
  // 服务端会按账号设置收敛窗口，这里以它返回的开关为准。
  const extendedEnabled = snapshot?.extended_search_enabled ?? false;
  const devices = snapshot?.devices ?? [];
  // 首次请求返回前先用本地选择，避免闪一下「全部时间」。
  const dateRangeActive = Boolean(dateFrom);
  const activeWindowLabel = dateRangeActive
    ? dateFrom === (dateTo || dateFrom)
      ? formatDayLabel(dateFrom)
      : `${formatDayLabel(dateFrom)} 至 ${formatDayLabel(dateTo || dateFrom)}`
    : windowLabel(snapshot ? snapshot.window_days : windowDays);
  const [clearing, setClearing] = useState(false);
  const [managingDevices, setManagingDevices] = useState(false);

  // 设备管理：改名、合并、删除。
  const refreshDevices = async () => {
    const response = await listBrowserHistory({
      limit: snapshot?.page_size ?? 200,
      days: windowDays,
      dateFrom: dateFrom || undefined,
      dateTo: dateTo || dateFrom || undefined,
      deviceId: deviceFilter || undefined,
    });
    setSnapshot(response);
  };

  const renameDevice = async (deviceId: string, deviceName: string) => {
    setError("");
    try {
      await renameBrowserHistoryDevice(deviceId, deviceName);
      await refreshDevices();
      setNotice(`设备已改名为「${deviceName}」。`);
    } catch (renameError) {
      setError(describeChange(renameError, "重命名设备失败。"));
    }
  };

  const mergeDevice = async (deviceId: string, targetDeviceId: string) => {
    const source = devices.find((item) => item.device_id === deviceId);
    const target = devices.find((item) => item.device_id === targetDeviceId);
    if (
      !window.confirm(
        `把「${source?.device_name || deviceId}」的历史并进「${target?.device_name || targetDeviceId}」？\n\n` +
          "合并后两台会变成一台，重复网址的访问次数会相加。确认它们确实是同一台机器再继续。",
      )
    ) {
      return;
    }
    setError("");
    try {
      await mergeBrowserHistoryDevice(deviceId, targetDeviceId);
      if (deviceFilter === deviceId) {
        setDeviceFilter(targetDeviceId);
      }
      await refreshDevices();
      setNotice("已合并为同一台设备。");
    } catch (mergeError) {
      setError(describeChange(mergeError, "合并设备失败。"));
    }
  };

  const removeDevice = async (device: BrowserHistoryDevice) => {
    const label = device.device_name || device.device_id;
    if (
      !window.confirm(
        `删除设备「${label}」及其 ${device.total_count} 条历史？\n\n` +
          "只影响这台设备，其他电脑的记录不受影响。已经收藏进资料库的网页也不会被删除。",
      )
    ) {
      return;
    }
    setError("");
    try {
      await deleteBrowserHistoryDevice(device.device_id);
      if (deviceFilter === device.device_id) {
        setDeviceFilter("");
      }
      await refreshDevices();
      setNotice(`已删除设备「${label}」。`);
    } catch (deleteError) {
      setError(describeChange(deleteError, "删除设备失败。"));
    }
  };

  useEffect(() => {
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [onClose]);

  const clearHistory = async () => {
    if (
      !window.confirm(
        "清空后服务端保存的全部浏览历史都会删除，已经收藏进资料库的网页不受影响。继续吗？",
      )
    ) {
      return;
    }
    setClearing(true);
    setError("");
    setNotice("");
    try {
      await clearBrowserHistory();
      setSnapshot((current) =>
        current
          ? { ...current, total_count: 0, items: [], synced_at: null }
          : current,
      );
      setEntries([]);
      setNotice("浏览历史已清空。浏览器里新产生的访问会在下次同步时重新出现。");
    } catch (clearError) {
      setError(describeChange(clearError, "清空浏览历史失败。"));
    } finally {
      setClearing(false);
    }
  };

  return (
    <div className="dialog-backdrop" role="presentation">
      <section
        className="history-dialog dialog-shell"
        role="dialog"
        aria-modal="true"
        aria-labelledby="history-dialog-title"
      >
        <div className="dialog-header">
          <div>
            <span className="type-label"><Icon name="history" size={16} /> 浏览历史</span>
            <h2 id="history-dialog-title">最近浏览的网页</h2>
            <p>
              {snapshot?.extension_connected
                ? `扩展最近同步于 ${
                    snapshot.synced_at ? formatVisited(snapshot.synced_at) : "未知时间"
                  } · 本页显示 ${entries.length} 条`
                : "还没有收到扩展同步的浏览记录，请确认已安装并登录新版扩展。"}
            </p>
          </div>
          <button className="icon-button" aria-label="关闭浏览历史" onClick={onClose}>
            <Icon name="close" size={16} />
          </button>
        </div>

        <div className="dialog-body">
        <div className="history-toolbar">
          <label className="search-box history-search">
            <Icon name="search" size={18} />
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder={`搜索${activeWindowLabel}历史里的标题或网址`}
              maxLength={200}
              aria-label="搜索浏览历史"
            />
            {search && (
              <button type="button" aria-label="清除搜索" onClick={() => setSearch("")}>
                <Icon name="close" size={14} />
              </button>
            )}
          </label>
          {extendedEnabled ? (
            <label className="history-window">
              时间范围
              <select
                value={windowDays}
                onChange={(event) => {
                  // 选天数就清掉日期区间，两种筛选不叠加。
                  setWindowDays(Number(event.target.value));
                  setDateFrom("");
                  setDateTo("");
                }}
                disabled={loading}
              >
                {WINDOW_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
          ) : (
            <button
              type="button"
              className="history-window-hint"
              onClick={onOpenSettings}
              title="在设置里打开「搜索更久的历史」后可以按 90 天、一年或全部时间检索"
            >
              只看最近 30 天 · 在设置里开启更久
            </button>
          )}
        </div>

        <div className="history-dates">
          <label>
            从
            <input
              type="date"
              value={dateFrom}
              max={dateTo || todayInputValue()}
              onChange={(event) => {
                setDateFrom(event.target.value);
                if (dateTo && event.target.value > dateTo) {
                  setDateTo(event.target.value);
                }
              }}
              aria-label="起始日期"
            />
          </label>
          <label>
            到
            <input
              type="date"
              value={dateTo}
              min={dateFrom || undefined}
              max={todayInputValue()}
              onChange={(event) => setDateTo(event.target.value)}
              aria-label="结束日期"
              disabled={!dateFrom}
            />
          </label>
          {dateFrom && (
            <button
              type="button"
              className="history-dates-clear"
              onClick={() => {
                setDateFrom("");
                setDateTo("");
              }}
            >
              清除日期
            </button>
          )}
          {!dateFrom && (
            <span className="history-dates-hint">
              也可以只选某一天，查那一天的浏览记录
            </span>
          )}
        </div>

        {/* 多台电脑同步到同一账号时，各自的记录分开存，可在这里切换查看。 */}
        {devices.length > 1 && (
          <div className="history-devices" role="group" aria-label="按设备筛选">
            <button
              type="button"
              className={deviceFilter === "" ? "active" : ""}
              onClick={() => setDeviceFilter("")}
            >
              全部设备
            </button>
            {devices.map((device) => (
              <button
                type="button"
                key={device.device_id}
                className={deviceFilter === device.device_id ? "active" : ""}
                onClick={() => setDeviceFilter(device.device_id)}
                title={`${device.total_count} 条 · 最近同步 ${formatVisited(device.synced_at)}`}
              >
                {device.device_name || device.device_id.slice(0, 8)}
                <small>{device.total_count}</small>
              </button>
            ))}
            <button
              type="button"
              className="history-device-manage"
              onClick={() => setManagingDevices((current) => !current)}
            >
              {managingDevices ? "收起" : "管理设备"}
            </button>
          </div>
        )}

        {/* 设备管理：改名、确认「同一台机器重装」、删除不再同步的设备。 */}
        {managingDevices && devices.length > 0 && (
          <ul className="history-device-list">
            {devices.map((device) => (
              <li key={device.device_id}>
                <div className="history-device-main">
                  <input
                    aria-label={`重命名 ${device.device_name || device.device_id}`}
                    defaultValue={device.device_name}
                    maxLength={120}
                    onBlur={(event) => {
                      const next = event.target.value.trim();
                      if (next && next !== device.device_name) {
                        void renameDevice(device.device_id, next);
                      }
                    }}
                  />
                  <small>
                    {device.total_count} 条 · 最近同步 {formatVisited(device.synced_at)}
                  </small>
                </div>
                {device.possible_same_device_id && (
                  <button
                    type="button"
                    className="history-device-merge"
                    onClick={() =>
                      void mergeDevice(device.device_id, device.possible_same_device_id!)
                    }
                  >
                    像是同一台机器？合并
                  </button>
                )}
                <button
                  type="button"
                  className="history-device-delete"
                  onClick={() => void removeDevice(device)}
                >
                  删除
                </button>
              </li>
            ))}
          </ul>
        )}

        <p className="history-hint">
          {extendedEnabled
            ? `历史记录全部保留在你的资料库里，当前按「${activeWindowLabel}」展示，共 ${snapshot?.total_count ?? 0} 条；其中 ${savedCount} 条已收藏。`
            : `历史记录全部保留在你的资料库里，默认只展示最近 30 天，共 ${snapshot?.total_count ?? 0} 条；其中 ${savedCount} 条已收藏。`}
        </p>

        {hasMore && (
          <p className="history-notice">
            还有 {Math.max(0, (snapshot?.total_count ?? 0) - entries.length)} 条更早的记录，继续翻页即可查看。
          </p>
        )}

        {notice && <p className="history-notice">{notice}</p>}

        <div className="history-list">
          {loading && <div className="history-empty">正在读取浏览历史……</div>}
          {!loading && entries.length === 0 && !error && (
            <div className="history-empty">
              {debouncedSearch
                ? `${activeWindowLabel}里没有标题或网址包含“${debouncedSearch}”的记录。`
                : `${activeWindowLabel}还没有浏览记录。打开一些网页后，扩展会自动同步到这里。`}
            </div>
          )}
          {!loading &&
            groupedEntries.map((group) => (
              <section className="history-day" key={group.date}>
                <h3 className="history-day-heading">
                  <span>{formatDayLabel(group.date)}</span>
                  <small>{group.items.length} 条</small>
                </h3>
                {group.items.map((entry) => {
                  const saved = Boolean(entry.saved_memo_id);
                  return (
                    <article className="history-row" key={entry.id}>
                      <span className="history-icon" aria-hidden="true">
                        {entry.favicon_url ? (
                          <img src={entry.favicon_url} alt="" />
                        ) : (
                          <ResourceMonogram sourceUrl={entry.page_url} size={16} />
                        )}
                      </span>
                      <div className="history-row-main">
                        <a
                          href={entry.page_url}
                          target="_blank"
                          rel="noreferrer"
                          title={entry.page_url}
                        >
                          {entry.page_title || sourceHost(entry.page_url)}
                        </a>
                        <small>
                          {sourceHost(entry.page_url)} · 最近访问{" "}
                          {formatVisited(entry.last_visited_at)} · 共{" "}
                          {entry.visit_count} 次
                          {/* 合并视图下标出来源设备，单设备视图下不必重复。 */}
                          {!deviceFilter && entry.device_name
                            ? ` · ${entry.device_name}`
                            : ""}
                        </small>
                      </div>
                      <button
                        type="button"
                        className={`history-save${saved ? " saved" : ""}`}
                        disabled={!saved && savingUrl === entry.page_url}
                        onClick={() => {
                          if (saved && entry.saved_memo_id) {
                            // 已收藏的直接跳到资料库条目，省去手动搜索。
                            onOpenSaved(entry.saved_memo_id);
                            onClose();
                            return;
                          }
                          void saveEntry(entry);
                        }}
                        title={saved ? "在资料库中查看" : "收藏到 MemoIsle"}
                      >
                        {saved
                          ? "已收藏"
                          : savingUrl === entry.page_url
                            ? "收藏中…"
                            : "收藏"}
                      </button>
                    </article>
                  );
                })}
              </section>
            ))}
        </div>
        </div>

        <div className="dialog-actions">
          {hasMore && (
            <button type="button" className="ghost" onClick={() => void loadMore()} disabled={loadingMore}>
              {loadingMore
                ? "加载中…"
                : `加载下一页（已显示 ${entries.length} / ${snapshot?.total_count ?? 0}）`}
            </button>
          )}
          {/* 清空只删历史，已经收藏进资料库的网页不会被动到。 */}
          <button
            type="button"
            className="danger-button"
            onClick={() => void clearHistory()}
            disabled={clearing || entries.length === 0}
          >
            {clearing ? "清空中…" : "清空历史"}
          </button>
          <button type="button" className="primary" onClick={onClose}>
            关闭
          </button>
        </div>
        {error && <div className="dialog-error" role="alert">{error}</div>}
      </section>
    </div>
  );
}
