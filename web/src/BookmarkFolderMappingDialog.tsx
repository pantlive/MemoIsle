import { type ReactNode, useEffect, useRef, useState } from "react";

import {
  getBookmarkFolderMappings,
  mapPendingBookmarkFolders,
  retryFolderClassifications,
  setBookmarkFolderOverride,
} from "./api";
import Icon from "./Icon";
import type { BookmarkFolderMapping, BookmarkFolderMappingList } from "./types";

const AUTO = "__auto";
const SKIP = "__skip";

function selectValue(item: BookmarkFolderMapping): string {
  if (item.source !== "manual") return AUTO;
  return item.category_code ?? SKIP;
}

function autoLabel(item: BookmarkFolderMapping): string {
  if (item.source === "manual") return "交给 Jev 判断";
  if (item.status === "pending") return "Jev 判断（还没判断）";
  if (item.status === "unmapped") return "Jev 判断：没有对应分类";
  const confidence = item.confidence === null ? "" : ` · ${(item.confidence * 100).toFixed(0)}%`;
  return `Jev 判断：${item.category_label}${confidence}`;
}

// 先把每个文件夹和书签标签对应到分类，让用户确认或改正，再逐条判断网页。
export default function BookmarkFolderMappingDialog({
  onClose,
  onStarted,
}: {
  onClose: () => void;
  onStarted: () => void;
}): ReactNode {
  const [list, setList] = useState<BookmarkFolderMappingList | null>(null);
  const [busy, setBusy] = useState(false);
  const [mapping, setMapping] = useState(false);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState<"all" | "mapped" | "unmapped" | "pending">("all");
  const stopRef = useRef(false);

  useEffect(() => {
    let cancelled = false;
    getBookmarkFolderMappings()
      .then((result) => { if (!cancelled) setList(result); })
      .catch((loadError: unknown) => {
        if (!cancelled) setError(loadError instanceof Error ? loadError.message : "读取书签文件夹失败");
      });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    const handleKey = (event: KeyboardEvent): void => {
      if (event.key === "Escape" && !busy && !mapping) onClose();
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [busy, mapping, onClose]);

  const runMapping = async (): Promise<void> => {
    if (mapping || !list?.pending_count) return;
    stopRef.current = false;
    setMapping(true);
    setError("");
    try {
      let current = list;
      // 每次只判断几个，便于显示进度，也能随时停下。
      while (current.pending_count > 0 && !stopRef.current) {
        current = await mapPendingBookmarkFolders(5);
        setList(current);
      }
    } catch (mapError) {
      setError(mapError instanceof Error ? mapError.message : "判断文件夹对应分类失败");
    } finally {
      setMapping(false);
    }
  };

  const changeOverride = async (item: BookmarkFolderMapping, value: string): Promise<void> => {
    setBusy(true);
    setError("");
    try {
      setList(await (
        value === AUTO
          ? setBookmarkFolderOverride(item.key, "auto")
          : value === SKIP
          ? setBookmarkFolderOverride(item.key, "skip")
          : setBookmarkFolderOverride(item.key, "category", value)
      ));
    } catch (overrideError) {
      setError(overrideError instanceof Error ? overrideError.message : "保存对应分类失败");
    } finally {
      setBusy(false);
    }
  };

  const startRetry = async (): Promise<void> => {
    if (!list?.retry_count || busy || mapping) return;
    if (!window.confirm(
      `逐条判断 ${list.retry_count} 条网页？\n\n`
      + "Jev 会结合网页内容判断它是否真的属于所在文件夹对应的分类：属于就沿用，不属于再走完整分类。"
      + "每条网页至少请求一次 Jev，会产生费用。人工确认和规则分类的网页不动。",
    )) return;
    setBusy(true);
    setError("");
    try {
      await retryFolderClassifications();
      onStarted();
      onClose();
    } catch (retryError) {
      setError(retryError instanceof Error ? retryError.message : "按书签文件夹重新判断失败");
      setBusy(false);
    }
  };

  const items = (list?.items ?? []).filter((item) => filter === "all" || item.status === filter);
  const judged = list ? list.items.length - list.pending_count : 0;

  return <div className="dialog-backdrop" role="presentation">
    <section className="classification-review-dialog folder-mapping-dialog dialog-shell" role="dialog" aria-modal="true" aria-labelledby="folder-mapping-title">
      <div className="dialog-header">
        <div>
          <span className="type-label"><Icon name="folder" size={16} /> 书签文件夹</span>
          <h2 id="folder-mapping-title">按书签文件夹重新判断</h2>
          <p>{
            "书签原来的归类在文件夹上（Firefox 书签还有标签）。先让 Jev 判断每个文件夹对应哪个分类，"
            + "你可以改正或设为不沿用；确认后再逐条判断网页，只有文件夹对应到分类的网页会参与。"
          }</p>
        </div>
        <button type="button" className="icon-button" aria-label="关闭" onClick={onClose} disabled={busy || mapping}>
          <Icon name="close" size={16} />
        </button>
      </div>

      <div className="dialog-body">
      {!list && !error && <p role="status">正在读取书签文件夹…</p>}
      {list && <>
        <div className="folder-mapping-summary">
          <span>{list.items.length} 个文件夹和标签，涉及 {list.page_count} 条网页</span>
          <span>已判断 {judged} / {list.items.length}</span>
          <span>可逐条判断 {list.retry_count} 条</span>
        </div>
        {list.pending_count > 0 && <div className="folder-mapping-step">
          <p>还有 {list.pending_count} 个没有判断对应分类，每个请求一次 Jev。</p>
          {mapping
            ? <button type="button" onClick={() => { stopRef.current = true; }}>停止（{judged} / {list.items.length}）</button>
            : <button type="button" className="folder-mapping-primary" onClick={() => void runMapping()} disabled={busy}>
              判断剩余 {list.pending_count} 个
            </button>}
        </div>}
        <div className="category-filter folder-mapping-filter" role="group" aria-label="按状态筛选">
          {([
            ["all", "全部"],
            ["mapped", "有对应分类"],
            ["unmapped", "不沿用"],
            ["pending", "未判断"],
          ] as const).map(([value, label]) => (
            <button
              key={value}
              type="button"
              className={filter === value ? "active" : ""}
              aria-pressed={filter === value}
              onClick={() => setFilter(value)}
            >
              {label} {value === "all" ? list.items.length : list.items.filter((item) => item.status === value).length}
            </button>
          ))}
        </div>
        {items.length === 0 && <p>没有符合条件的文件夹。</p>}
        <ul className="folder-mapping-list">
          {items.map((item) => <li key={item.key} className={item.status}>
            <div className="folder-mapping-name">
              <span className="folder-mapping-kind">{item.kind === "tag" ? "标签" : "文件夹"}</span>
              <strong>{item.text}</strong>
              <small>{item.page_count} 条网页</small>
            </div>
            <select
              aria-label={`「${item.text}」对应的分类`}
                value={selectValue(item)}
                disabled={busy || mapping}
                onChange={(event) => void changeOverride(item, event.target.value)}
              >
                <option value={AUTO}>{autoLabel(item)}</option>
                <option value={SKIP}>不沿用，照常分类</option>
                {list.categories.map((category) => (
                  <option key={category.code} value={category.code}>指定为：{category.label}</option>
                ))}
              </select>
          </li>)}
        </ul>
      </>}
      </div>
      <div className="dialog-actions">
        <button type="button" className="ghost" onClick={onClose} disabled={busy || mapping}>关闭</button>
        <button
          type="button"
          className="primary folder-mapping-primary"
          disabled={busy || mapping || !list?.retry_count}
          onClick={() => void startRetry()}
        >
          逐条判断 {list?.retry_count ?? 0} 条网页
        </button>
      </div>
      {error && <div className="dialog-error" role="alert">{error}</div>}
    </section>
  </div>;
}
