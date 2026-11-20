import { useCallback, useEffect, useRef, useState } from "react";

import {
  ApiError,
  createForgetItem,
  deleteForgetAttachment,
  deleteForgetItem,
  downloadForgetAttachment,
  listForgetItems,
  updateForgetItem,
  uploadForgetAttachment,
} from "./api";
import {
  FORGET_CONTENT_MAX,
  FORGET_MAX_ATTACHMENTS,
  FORGET_TITLE_MAX,
  forgetDisplayTitle,
  forgetFileError,
  forgetTextError,
  forgetTextLength,
  formatForgetBytes,
  isForgetImage,
  type ForgetAttachment,
  type ForgetItem,
} from "./forget";
import Icon from "./Icon";

const describe = (error: unknown): string =>
  error instanceof Error ? error.message : "操作失败，请重试。";

function ForgetThumb({ itemId, attachment }: { itemId: string; attachment: ForgetAttachment }) {
  const [url, setUrl] = useState("");
  useEffect(() => {
    let objectUrl = "";
    let cancelled = false;
    void downloadForgetAttachment(itemId, attachment.id)
      .then((blob) => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
      })
      .catch(() => {
        if (!cancelled) setUrl("");
      });
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [attachment.id, itemId]);
  if (!url) return <span className="forget-thumb pending" aria-hidden="true" />;
  return <img src={url} alt={attachment.original_name} />;
}

export default function ForgetPanel() {
  const [items, setItems] = useState<ForgetItem[]>([]);
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [version, setVersion] = useState<number | null>(null);
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [pinned, setPinned] = useState(false);
  const [attachments, setAttachments] = useState<ForgetAttachment[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [pendingDelete, setPendingDelete] = useState(false);
  const [pendingAttachment, setPendingAttachment] = useState<ForgetAttachment | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const reload = useCallback(async (nextQuery: string) => {
    setLoading(true);
    try {
      setItems(await listForgetItems(nextQuery));
      setError(null);
    } catch (reason) {
      setError(describe(reason));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void reload(query);
    }, 300);
    return () => window.clearTimeout(timer);
  }, [query, reload]);

  function applyItem(next: ForgetItem, syncText: boolean) {
    setItems((current) => {
      const exists = current.some((item) => item.id === next.id);
      return exists
        ? current.map((item) => (item.id === next.id ? next : item))
        : [next, ...current];
    });
    setSelectedId(next.id);
    setVersion(next.version);
    setAttachments(next.attachments);
    if (syncText) {
      setTitle(next.title);
      setContent(next.content);
      setPinned(next.pinned);
    }
  }

  function startNew() {
    setSelectedId(null);
    setVersion(null);
    setTitle("");
    setContent("");
    setPinned(false);
    setAttachments([]);
    setPendingDelete(false);
    setPendingAttachment(null);
    setError(null);
    setMessage(null);
  }

  function selectItem(item: ForgetItem) {
    setPendingDelete(false);
    setPendingAttachment(null);
    setError(null);
    setMessage(null);
    applyItem(item, true);
  }

  async function saveText() {
    const problem = forgetTextError(title, content);
    if (problem) {
      setError(problem);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const payload = { title, content, pinned };
      const saved = selectedId === null || version === null
        ? await createForgetItem(payload)
        : await updateForgetItem(selectedId, payload, version);
      applyItem(saved, true);
      setMessage(selectedId === null || version === null ? "已记下。" : "已保存。");
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 409) {
        setError("已在其他设备修改，正在重新读取。");
        await reload(query);
      } else {
        setError(describe(reason));
      }
    } finally {
      setBusy(false);
    }
  }

  async function ensureSaved(): Promise<string | null> {
    if (selectedId !== null && version !== null) return selectedId;
    const problem = forgetTextError(title, content);
    if (problem) {
      setError(problem);
      return null;
    }
    const created = await createForgetItem({ title, content, pinned });
    applyItem(created, true);
    return created.id;
  }

  async function uploadFiles(files: File[]) {
    if (files.length === 0 || busy) return;
    setBusy(true);
    setError(null);
    try {
      const itemId = await ensureSaved();
      if (itemId === null) return;
      let latest = attachments;
      for (const file of files) {
        const problem = forgetFileError(file);
        if (problem) {
          setError(`「${file.name || "未命名文件"}」${problem}`);
          continue;
        }
        if (latest.length >= FORGET_MAX_ATTACHMENTS) {
          setError("每条最多 20 个附件");
          break;
        }
        const updated = await uploadForgetAttachment(itemId, file);
        latest = updated.attachments;
        applyItem(updated, false);
      }
      setMessage("附件已保存。");
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 409) {
        setError("已在其他设备修改，正在重新读取。");
        await reload(query);
      } else {
        setError(describe(reason));
      }
    } finally {
      setBusy(false);
    }
  }

  async function confirmDeleteItem() {
    if (selectedId === null || version === null) return;
    setBusy(true);
    try {
      await deleteForgetItem(selectedId, version);
      setItems((current) => current.filter((item) => item.id !== selectedId));
      startNew();
      setMessage("已删除这条事项。");
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 409) {
        setError("已在其他设备修改，正在重新读取。");
        setPendingDelete(false);
        await reload(query);
      } else {
        setError(describe(reason));
      }
    } finally {
      setBusy(false);
    }
  }

  async function confirmDeleteAttachment() {
    if (selectedId === null || pendingAttachment === null) return;
    const attachment = pendingAttachment;
    setBusy(true);
    try {
      await deleteForgetAttachment(selectedId, attachment.id);
      setAttachments((current) => current.filter((item) => item.id !== attachment.id));
      setItems((current) =>
        current.map((item) =>
          item.id === selectedId
            ? { ...item, attachments: item.attachments.filter((row) => row.id !== attachment.id) }
            : item,
        ),
      );
      setPendingAttachment(null);
      setMessage("已删除附件。");
    } catch (reason) {
      setError(describe(reason));
    } finally {
      setBusy(false);
    }
  }

  async function download(attachment: ForgetAttachment) {
    if (selectedId === null) return;
    setError(null);
    try {
      const blob = await downloadForgetAttachment(selectedId, attachment.id);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = attachment.original_name || "file";
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (reason) {
      setError(describe(reason));
    }
  }

  return (
    <section className="forget-panel">
      <div className="page-heading">
        <div>
          <h1>易忘事项</h1>
          <p className="page-subtitle">容易忘掉的文字、图片和文件，放在这里。</p>
        </div>
        <button className="primary" type="button" onClick={startNew} disabled={busy}>
          <Icon name="plus" size={16} /> 新建
        </button>
      </div>
      {message && <p className="forget-notice" role="status">{message}</p>}
      {error && <p className="forget-error" role="alert">{error}</p>}
      <div className="forget-layout">
        <div className="forget-list-pane">
          <label className="forget-search">
            <Icon name="search" size={16} />
            <input
              aria-label="搜索易忘事项"
              value={query}
              placeholder="搜索标题或正文"
              onChange={(event) => setQuery(event.target.value)}
            />
          </label>
          {loading && items.length === 0 ? (
            <p className="forget-empty" role="status">正在读取…</p>
          ) : items.length === 0 ? (
            <p className="forget-empty">还没有事项。写下一句容易忘掉的话，或直接放上图片和文件。</p>
          ) : (
            <ul className="forget-list">
              {items.map((item) => (
                <li key={item.id}>
                  <button
                    type="button"
                    className={item.id === selectedId ? "active" : ""}
                    onClick={() => selectItem(item)}
                  >
                    <strong>{item.pinned ? "置顶 · " : ""}{forgetDisplayTitle(item.title)}</strong>
                    <small>
                      {item.attachments.length > 0 ? `${item.attachments.length} 个附件` : "没有附件"}
                      {item.content.trim() ? ` · ${item.content.trim().slice(0, 40)}` : ""}
                    </small>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
        <form
          className="forget-editor"
          onSubmit={(event) => {
            event.preventDefault();
            void saveText();
          }}
        >
          <label>
            标题
            <input
              aria-label="事项标题"
              value={title}
              maxLength={FORGET_TITLE_MAX + 20}
              onChange={(event) => setTitle(event.target.value)}
            />
            <small>{forgetTextLength(title.trim())}/{FORGET_TITLE_MAX}</small>
          </label>
          <label>
            正文
            <textarea
              aria-label="事项正文"
              value={content}
              rows={8}
              onChange={(event) => setContent(event.target.value)}
            />
            <small>{forgetTextLength(content.trim())}/{FORGET_CONTENT_MAX}</small>
          </label>
          <label className="forget-pin">
            <input
              type="checkbox"
              checked={pinned}
              onChange={(event) => setPinned(event.target.checked)}
            />
            置顶
          </label>
          <div className="forget-actions">
            <button className="primary" type="submit" disabled={busy}>
              {selectedId === null ? "记下" : "保存文字"}
            </button>
            {selectedId !== null && (
              <button
                className="danger-text"
                type="button"
                disabled={busy}
                onClick={() => setPendingDelete(true)}
              >
                删除这条
              </button>
            )}
          </div>
          <div
            className={dragOver ? "forget-drop active" : "forget-drop"}
            onDragOver={(event) => {
              event.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(event) => {
              event.preventDefault();
              setDragOver(false);
              void uploadFiles([...event.dataTransfer.files]);
            }}
          >
            <p>把图片或文件拖到这里，也可以一次选多个。单个不超过 20 MB，每条最多 20 个。</p>
            <button
              type="button"
              disabled={busy}
              onClick={() => fileInputRef.current?.click()}
            >
              <Icon name="upload" size={16} /> 选择图片或文件
            </button>
            <input
              ref={fileInputRef}
              className="sr-only"
              type="file"
              multiple
              aria-label="选择易忘事项附件"
              onChange={(event) => {
                const files = [...(event.target.files ?? [])];
                event.target.value = "";
                void uploadFiles(files);
              }}
            />
          </div>
          {attachments.length > 0 && (
            <ul className="forget-files">
              {attachments.map((attachment) => (
                <li key={attachment.id}>
                  {isForgetImage(attachment) && selectedId !== null ? (
                    <ForgetThumb itemId={selectedId} attachment={attachment} />
                  ) : (
                    <span className="forget-file-icon" aria-hidden="true">
                      <Icon name="folder" size={18} />
                    </span>
                  )}
                  <div>
                    <strong>{attachment.original_name}</strong>
                    <small>
                      {isForgetImage(attachment) ? "图片" : "文件"} · {formatForgetBytes(attachment.size)}
                    </small>
                  </div>
                  <button type="button" onClick={() => void download(attachment)}>下载</button>
                  <button
                    type="button"
                    className="danger-text"
                    onClick={() => setPendingAttachment(attachment)}
                  >
                    删除
                  </button>
                </li>
              ))}
            </ul>
          )}
        </form>
      </div>
      {pendingDelete && (
        <div className="forget-confirm" role="dialog" aria-modal="true" aria-labelledby="forget-delete-title">
          <div>
            <h2 id="forget-delete-title">删除这条事项？</h2>
            <p>文字和全部附件都会删掉，磁盘上的文件也会清掉。这不会进回收站。</p>
            <div className="forget-actions">
              <button type="button" onClick={() => setPendingDelete(false)} disabled={busy}>取消</button>
              <button className="primary" type="button" onClick={() => void confirmDeleteItem()} disabled={busy}>
                确认删除
              </button>
            </div>
          </div>
        </div>
      )}
      {pendingAttachment && (
        <div className="forget-confirm" role="dialog" aria-modal="true" aria-labelledby="forget-file-title">
          <div>
            <h2 id="forget-file-title">删除这个附件？</h2>
            <p>「{pendingAttachment.original_name}」会从这条事项和磁盘上一并删除。</p>
            <div className="forget-actions">
              <button type="button" onClick={() => setPendingAttachment(null)} disabled={busy}>取消</button>
              <button className="primary" type="button" onClick={() => void confirmDeleteAttachment()} disabled={busy}>
                确认删除
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
