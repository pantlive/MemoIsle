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
  syncBrowserExtension,
  undoBookmarkImport,
} from "./api";
import { parseChromeBookmarksFile } from "./bookmarkImport";
import type {
  BookmarkImportBatch,
  BookmarkImportPreview,
  BookmarkInput,
  BookmarkPreviewItem,
} from "./types";
import Icon from "./Icon";
import { t } from "./i18n";
import { useI18n } from "./I18nProvider";

interface BookmarkImportDialogProps {
  onClose: () => void;
  onImported: () => void;
}

function itemStatusLabel(item: BookmarkPreviewItem): string {
  if (item.status === "valid") {
    return t("可导入");
  }
  if (item.error_code === "already_saved") {
    return t("资料库已有");
  }
  if (item.error_code === "duplicate_in_file") {
    return t("文件内重复");
  }
  return t("链接无效");
}

function batchStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    pending: t("等待导入"),
    processing: t("正在导入"),
    completed: t("导入完成"),
    partial_failed: t("部分项目失败"),
    undone: t("已撤销导入"),
  };
  return labels[status] ?? status;
}

export default function BookmarkImportDialog({
  onClose,
  onImported,
}: BookmarkImportDialogProps) {
  const { t } = useI18n();
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
      const folder = item.folder_path || t("未分类文件夹");
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
      // 点击重读时主动让扩展携带当前用户凭证刷新一次快照。
      await syncBrowserExtension();
      const snapshot = await getCurrentBrowserBookmarks();
      if (!snapshot.extension_connected) {
        throw new Error(
          t("尚未收到浏览器书签。请在 chrome://extensions 重新加载新版扩展，刷新 MemoIsle 页面并确认已登录后重试。"),
        );
      }
      if (snapshot.items.length === 0) {
        throw new Error(t("当前浏览器没有可读取的书签，也可以使用下方 HTML 备用导入。"));
      }
      const result = await previewBookmarkImport(snapshot.items);
      const syncedAt = snapshot.synced_at
        ? new Date(snapshot.synced_at).toLocaleString()
        : t("刚刚");
      const truncatedLabel = snapshot.truncated
        ? t(" · 仅预览前 {length} 条", { length: snapshot.items.length })
        : "";
      setSourceLabel(
        t("当前浏览器 · 共 {total_count} 条 · 同步于 {syncedAt}{truncatedLabel}", { total_count: snapshot.total_count, syncedAt, truncatedLabel }),
      );
      setItems(snapshot.items);
      setPreview(result);
    } catch (browserError) {
      setError(
        browserError instanceof Error
          ? browserError.message
          : t("读取当前浏览器书签失败。"),
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
        setError(pollError instanceof Error ? pollError.message : t("读取导入进度失败。"));
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
      setSourceLabel(t("{name} · HTML 备用导入", { name: file.name }));
      setItems(parsedItems);
      setPreview(result);
    } catch (fileError) {
      setError(fileError instanceof Error ? fileError.message : t("读取书签文件失败。"));
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
      setError(importError instanceof Error ? importError.message : t("创建导入任务失败。"));
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
      setError(retryError instanceof Error ? retryError.message : t("重试失败。"));
    } finally {
      setBusy(false);
    }
  };

  const handleUndo = async () => {
    if (!batch || busy) {
      return;
    }
    const confirmed = window.confirm(
      t("撤销后，本批导入且未编辑的资料会移入回收站；已经编辑的资料会保留。继续吗？"),
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
      setError(undoError instanceof Error ? undoError.message : t("撤销失败。"));
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

  useEffect(() => {
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [onClose]);

  return (
    <div className="dialog-backdrop" role="presentation">
      <section
        className="bookmark-dialog dialog-shell"
        role="dialog"
        aria-modal="true"
        aria-labelledby="bookmark-import-title"
      >
        <div className="dialog-header">
          <div>
            <span className="type-label"><Icon name="bookmark" size={16} />{t(" 当前浏览器")}</span>
            <h2 id="bookmark-import-title">{t("导入浏览器书签")}</h2>
            <p>{t("从当前浏览器读取书签，或选择导出的 HTML 作为备用。")}</p>
          </div>
          <button className="icon-button" aria-label={t("关闭书签导入")} onClick={onClose}>
            <Icon name="close" size={16} />
          </button>
        </div>

        <div className="dialog-body">
        {!preview && !batch && (
          <div className="bookmark-source-options">
            <section className="browser-bookmark-source">
              <span aria-hidden="true"><Icon name="bookmark" size={20} /></span>
              <div>
                <strong>
                  {busy ? t("正在读取并检查当前浏览器书签…") : t("从当前浏览器直接读取")}
                </strong>
                <small>{t("新版扩展只同步书签标题、网址和文件夹，不读取浏览历史或页面内容。")}</small>
              </div>
              <button
                type="button"
                disabled={busy}
                onClick={() => void loadCurrentBrowserBookmarks()}
              >
                {busy ? t("读取中…") : t("重新读取")}
              </button>
            </section>
            <div className="bookmark-source-divider"><span>{t("备用方式")}</span></div>
            <label className="bookmark-file-picker compact">
              <span><Icon name="upload" size={20} /></span>
              <span>
                <strong>{t("选择浏览器导出的书签 HTML")}</strong>
                <small>{t("Chrome、Edge、Firefox 都可以，Firefox 书签的标签会一起保留；原始文件不会上传。")}</small>
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
              <div><strong>{preview.total_count}</strong><span>{t("读取总数")}</span></div>
              <div className="success"><strong>{preview.valid_count}</strong><span>{t("可导入")}</span></div>
              <div><strong>{preview.duplicate_count}</strong><span>{t("重复跳过")}</span></div>
              <div className={preview.invalid_count ? "danger" : ""}>
                <strong>{preview.invalid_count}</strong><span>{t("无法导入")}</span>
              </div>
            </div>
            <p className="bookmark-file-name">{t("{sourceLabel} · 原来的文件夹（和书签标签）会先交给 Jev 判断，正确就沿用对应的分类，否则由系统重新分类。", { sourceLabel })}</p>
            <div className="bookmark-preview-list">
              {previewGroups.map(([folder, folderItems]) => (
                <section key={folder}>
                  <h3>{folder}<span>{t("{length} 条", { length: folderItems.length })}</span></h3>
                  {folderItems.slice(0, 8).map((item) => (
                    <div className={`bookmark-preview-row ${item.status}`} key={item.client_item_id}>
                      <span><strong>{item.title || t("未命名书签")}</strong><small>{item.url}</small></span>
                      <em>{itemStatusLabel(item)}</em>
                    </div>
                  ))}
                  {folderItems.length > 8 && <p>{t("另有 {value} 条，将按相同规则处理。", { value: folderItems.length - 8 })}</p>}
                </section>
              ))}
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
              <div className="success"><strong>{batch.imported_count}</strong><span>{t("已导入")}</span></div>
              <div><strong>{batch.duplicate_count}</strong><span>{t("已跳过")}</span></div>
              <div className={batch.invalid_count ? "danger" : ""}><strong>{batch.invalid_count}</strong><span>{t("链接无效")}</span></div>
              <div className={batch.failed_count ? "danger" : ""}><strong>{batch.failed_count}</strong><span>{t("处理失败")}</span></div>
            </div>
            {batch.failed_count > 0 && (
              <div className="bookmark-failures">
                {batch.items.filter((item) => item.status === "failed").map((item) => (
                  <span key={item.client_item_id}>{item.title || item.source_url}</span>
                ))}
              </div>
            )}
            <p className="bookmark-progress-note">
              {t("已导入资料可以立即搜索；网页信息与自动分类会在后台继续更新。")}
            </p>
          </>
        )}
        </div>

        {preview && !batch && (
          <div className="dialog-actions">
            <button type="button" className="ghost" onClick={chooseAnotherSource}>{t("重新选择")}</button>
            <button
              type="button"
              className="primary"
              disabled={busy || preview.valid_count === 0}
              onClick={() => void handleImport()}
            >
              {busy ? t("正在创建导入任务…") : t("确认导入 {valid_count} 条", { valid_count: preview.valid_count })}
            </button>
          </div>
        )}

        {batch && (
          <div className="dialog-actions">
            {batch.failed_count > 0 && batch.status !== "undone" && (
              <button type="button" className="ghost" disabled={busy} onClick={() => void handleRetry()}>
                {busy ? t("正在重试…") : t("重试失败项目")}
              </button>
            )}
            {batch.imported_count > 0 && batch.status !== "undone" && (
              <button type="button" className="danger-button" disabled={busy} onClick={() => void handleUndo()}>
                {t("撤销本批导入")}
              </button>
            )}
            <button type="button" className="primary" onClick={onClose}>{t("完成")}</button>
          </div>
        )}

        {error && <div className="dialog-error" role="alert">{error}</div>}
      </section>
    </div>
  );
}
