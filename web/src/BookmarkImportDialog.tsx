import {
  type ChangeEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import {
  createBookmarkImport,
  getCurrentBrowserBookmarks,
  getBookmarkImport,
  previewBookmarkImport,
  retryBookmarkImport,
  undoBookmarkImport,
} from "./api";
import { parseChromeBookmarksFile } from "./bookmarkImport";
import type {
  BookmarkImportBatch,
  BookmarkImportPreview,
  BookmarkInput,
  BookmarkPreviewItem,
} from "./types";

interface BookmarkImportDialogProps {
  onClose: () => void;
  onImported: () => void;
}

function itemStatusLabel(item: BookmarkPreviewItem): string {
  if (item.status === "valid") {
    return "可导入";
  }
  if (item.error_code === "already_saved") {
    return "资料库已有";
  }
  if (item.error_code === "duplicate_in_file") {
    return "文件内重复";
  }
  return "链接无效";
}

function batchStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    pending: "等待导入",
    processing: "正在导入",
    completed: "导入完成",
    partial_failed: "部分项目失败",
    undone: "已撤销导入",
  };
  return labels[status] ?? status;
}

export default function BookmarkImportDialog({
  onClose,
  onImported,
}: BookmarkImportDialogProps) {
  const [sourceLabel, setSourceLabel] = useState("");
  const [items, setItems] = useState<BookmarkInput[]>([]);
  const [preview, setPreview] = useState<BookmarkImportPreview | null>(null);
  const [batch, setBatch] = useState<BookmarkImportBatch | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const notifiedBatchRef = useRef<string | null>(null);
  const initialReadStartedRef = useRef(false);

  const previewGroups = useMemo(() => {
    const groups = new Map<string, BookmarkPreviewItem[]>();
    for (const item of preview?.items ?? []) {
      const folder = item.folder_path || "未分类文件夹";
      const current = groups.get(folder) ?? [];
      current.push(item);
      groups.set(folder, current);
    }
    return Array.from(groups.entries());
  }, [preview]);

  const loadCurrentBrowserBookmarks = useCallback(async () => {
    setBusy(true);
    setError("");
    setPreview(null);
    setBatch(null);
    try {
      const snapshot = await getCurrentBrowserBookmarks();
      if (!snapshot.extension_connected) {
        throw new Error(
          "尚未收到浏览器书签。请重新下载或加载新版扩展，允许读取书签后重试。",
        );
      }
      if (snapshot.items.length === 0) {
        throw new Error("当前浏览器没有可读取的书签，也可以使用下方 HTML 备用导入。");
      }
      const result = await previewBookmarkImport(snapshot.items);
      const syncedAt = snapshot.synced_at
        ? new Date(snapshot.synced_at).toLocaleString()
        : "刚刚";
      const truncatedLabel = snapshot.truncated
        ? ` · 仅预览前 ${snapshot.items.length} 条`
        : "";
      setSourceLabel(
        `当前浏览器 · 共 ${snapshot.total_count} 条 · 同步于 ${syncedAt}${truncatedLabel}`,
      );
      setItems(snapshot.items);
      setPreview(result);
    } catch (browserError) {
      setError(
        browserError instanceof Error
          ? browserError.message
          : "读取当前浏览器书签失败。",
      );
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    if (initialReadStartedRef.current) {
      return;
    }
    initialReadStartedRef.current = true;
    void loadCurrentBrowserBookmarks();
  }, [loadCurrentBrowserBookmarks]);

  useEffect(() => {
    if (!batch || !["pending", "processing"].includes(batch.status)) {
      return;
    }
    const timer = window.setTimeout(async () => {
      try {
        const latest = await getBookmarkImport(batch.id);
        setBatch(latest);
      } catch (pollError) {
        setError(pollError instanceof Error ? pollError.message : "读取导入进度失败。");
      }
    }, 900);
    return () => window.clearTimeout(timer);
  }, [batch]);

  useEffect(() => {
    if (
      batch &&
      ["completed", "partial_failed"].includes(batch.status) &&
      notifiedBatchRef.current !== batch.id
    ) {
      notifiedBatchRef.current = batch.id;
      onImported();
    }
  }, [batch, onImported]);

  const handleFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }
    setBusy(true);
    setError("");
    setPreview(null);
    setBatch(null);
    try {
      // HTML 仅在浏览器本地解析，服务端只接收结构化书签字段。
      const parsedItems = await parseChromeBookmarksFile(file);
      const result = await previewBookmarkImport(parsedItems);
      setSourceLabel(`${file.name} · HTML 备用导入`);
      setItems(parsedItems);
      setPreview(result);
    } catch (fileError) {
      setError(fileError instanceof Error ? fileError.message : "读取书签文件失败。");
    } finally {
      setBusy(false);
      event.target.value = "";
    }
  };

  const handleImport = async () => {
    if (!preview?.valid_count || busy) {
      return;
    }
    setBusy(true);
    setError("");
    try {
      const createdBatch = await createBookmarkImport(items);
      notifiedBatchRef.current = null;
      setBatch(createdBatch);
    } catch (importError) {
      setError(importError instanceof Error ? importError.message : "创建导入任务失败。");
    } finally {
      setBusy(false);
    }
  };

  const handleRetry = async () => {
    if (!batch || busy) {
      return;
    }
    setBusy(true);
    setError("");
    try {
      setBatch(await retryBookmarkImport(batch.id));
    } catch (retryError) {
      setError(retryError instanceof Error ? retryError.message : "重试失败。");
    } finally {
      setBusy(false);
    }
  };

  const handleUndo = async () => {
    if (!batch || busy) {
      return;
    }
    const confirmed = window.confirm(
      "撤销后，本批导入且未编辑的资料会移入回收站；已经编辑的资料会保留。继续吗？",
    );
    if (!confirmed) {
      return;
    }
    setBusy(true);
    setError("");
    try {
      setBatch(await undoBookmarkImport(batch.id));
      onImported();
    } catch (undoError) {
      setError(undoError instanceof Error ? undoError.message : "撤销失败。");
    } finally {
      setBusy(false);
    }
  };

  const chooseAnotherSource = () => {
    setSourceLabel("");
    setItems([]);
    setPreview(null);
    setBatch(null);
    setError("");
  };

  return (
    <div className="dialog-backdrop" role="presentation">
      <section
        className="bookmark-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="bookmark-import-title"
      >
        <div className="dialog-header">
          <div>
            <span className="type-label">当前浏览器</span>
            <h2 id="bookmark-import-title">导入浏览器书签</h2>
          </div>
          <button className="icon-button" aria-label="关闭书签导入" onClick={onClose}>
            ×
          </button>
        </div>

        {!preview && !batch && (
          <div className="bookmark-source-options">
            <section className="browser-bookmark-source">
              <span aria-hidden="true">◎</span>
              <div>
                <strong>
                  {busy ? "正在读取并检查当前浏览器书签…" : "从当前浏览器直接读取"}
                </strong>
                <small>新版扩展只同步书签标题、网址和文件夹，不读取浏览历史或页面内容。</small>
              </div>
              <button
                type="button"
                disabled={busy}
                onClick={() => void loadCurrentBrowserBookmarks()}
              >
                {busy ? "读取中…" : "重新读取"}
              </button>
            </section>
            <div className="bookmark-source-divider"><span>备用方式</span></div>
            <label className="bookmark-file-picker compact">
              <span aria-hidden="true">⇧</span>
              <span>
                <strong>选择 Chrome 导出的书签 HTML</strong>
                <small>适合未安装新版扩展时使用；原始文件不会上传。</small>
              </span>
              <input
                type="file"
                accept=".html,text/html"
                disabled={busy}
                onChange={(event) => void handleFile(event)}
              />
            </label>
          </div>
        )}

        {preview && !batch && (
          <>
            <div className="bookmark-summary">
              <div><strong>{preview.total_count}</strong><span>读取总数</span></div>
              <div className="success"><strong>{preview.valid_count}</strong><span>可导入</span></div>
              <div><strong>{preview.duplicate_count}</strong><span>重复跳过</span></div>
              <div className={preview.invalid_count ? "danger" : ""}>
                <strong>{preview.invalid_count}</strong><span>无法导入</span>
              </div>
            </div>
            <p className="bookmark-file-name">{sourceLabel} · 保留原文件夹用于追溯，最终分类由系统自动判断。</p>
            <div className="bookmark-preview-list">
              {previewGroups.map(([folder, folderItems]) => (
                <section key={folder}>
                  <h3>{folder}<span>{folderItems.length} 条</span></h3>
                  {folderItems.slice(0, 8).map((item) => (
                    <div className={`bookmark-preview-row ${item.status}`} key={item.client_item_id}>
                      <span><strong>{item.title || "未命名书签"}</strong><small>{item.url}</small></span>
                      <em>{itemStatusLabel(item)}</em>
                    </div>
                  ))}
                  {folderItems.length > 8 && <p>另有 {folderItems.length - 8} 条，将按相同规则处理。</p>}
                </section>
              ))}
            </div>
            <div className="dialog-actions">
              <button type="button" onClick={chooseAnotherSource}>重新选择</button>
              <button
                type="button"
                className="primary"
                disabled={busy || preview.valid_count === 0}
                onClick={() => void handleImport()}
              >
                {busy ? "正在创建导入任务…" : `确认导入 ${preview.valid_count} 条`}
              </button>
            </div>
          </>
        )}

        {batch && (
          <>
            <div className="bookmark-progress-heading">
              <div>
                <span className={`batch-status ${batch.status}`}>{batchStatusLabel(batch.status)}</span>
                <strong>{batch.imported_count} / {batch.valid_count}</strong>
              </div>
              <progress max={Math.max(batch.valid_count, 1)} value={batch.imported_count} />
            </div>
            <div className="bookmark-summary compact">
              <div className="success"><strong>{batch.imported_count}</strong><span>已导入</span></div>
              <div><strong>{batch.duplicate_count}</strong><span>已跳过</span></div>
              <div className={batch.invalid_count ? "danger" : ""}><strong>{batch.invalid_count}</strong><span>链接无效</span></div>
              <div className={batch.failed_count ? "danger" : ""}><strong>{batch.failed_count}</strong><span>处理失败</span></div>
            </div>
            {batch.failed_count > 0 && (
              <div className="bookmark-failures">
                {batch.items.filter((item) => item.status === "failed").map((item) => (
                  <span key={item.client_item_id}>{item.title || item.source_url}</span>
                ))}
              </div>
            )}
            <p className="bookmark-progress-note">
              已导入资料可以立即搜索；网页信息与自动分类会在后台继续更新。
            </p>
            <div className="dialog-actions">
              {batch.failed_count > 0 && batch.status !== "undone" && (
                <button type="button" disabled={busy} onClick={() => void handleRetry()}>
                  {busy ? "正在重试…" : "重试失败项目"}
                </button>
              )}
              {batch.imported_count > 0 && batch.status !== "undone" && (
                <button type="button" className="danger-button" disabled={busy} onClick={() => void handleUndo()}>
                  撤销本批导入
                </button>
              )}
              <button type="button" className="primary" onClick={onClose}>完成</button>
            </div>
          </>
        )}

        {error && <div className="dialog-error" role="alert">{error}</div>}
      </section>
    </div>
  );
}
