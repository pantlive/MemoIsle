import { useCallback, useEffect, useRef, useState, type ClipboardEvent, type DragEvent, type FormEvent } from "react";

import {
  ApiError, discardRelayItem, downloadRelayItem, pollRelayInbox, RELAY_WAIT_SECONDS,
  sendRelayFile, sendRelayText,
} from "./api";
import Icon from "./Icon";
import {
  clipboardImageFilename, formatBytes, formatRemaining, isRelayImage, pickClipboardImageType,
  relayDeviceLabels, relayFileError, relayTextError,
} from "./relay";
import type { RelayItem } from "./types";

const describe = (error: unknown): string => error instanceof Error ? error.message : "操作失败，请重试。";
const RETRY_BASE_MS = 2_000;
const RETRY_MAX_MS = 30_000;

/** 页面隐藏时挂起，重新可见或面板关闭（signal 中止）后继续。 */
function waitUntilVisible(signal: AbortSignal): Promise<void> {
  if (!document.hidden || signal.aborted) return Promise.resolve();
  return new Promise((resolve) => {
    const finish = () => {
      document.removeEventListener("visibilitychange", handle);
      signal.removeEventListener("abort", finish);
      resolve();
    };
    const handle = () => { if (!document.hidden) finish(); };
    document.addEventListener("visibilitychange", handle);
    signal.addEventListener("abort", finish);
  });
}

function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const timer = window.setTimeout(resolve, ms);
    signal.addEventListener("abort", () => { window.clearTimeout(timer); resolve(); }, { once: true });
  });
}

function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.rel = "noopener";
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  // 给浏览器留时间开始下载再释放。
  window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

function clipboardReadHint(error: unknown): string {
  if (error instanceof DOMException && (error.name === "NotAllowedError" || error.name === "SecurityError")) {
    return "没有读取剪贴板的权限，请允许后重试，或在本页按 Ctrl+V。";
  }
  if (error instanceof DOMException && error.name === "NotFoundError") {
    return "剪贴板里没有图片，请先截图或复制图片，也可以在本页按 Ctrl+V。";
  }
  return "无法读取剪贴板图片，请在本页按 Ctrl+V。";
}

function namedClipboardFile(blob: Blob, mime: string): File {
  const type = blob.type || mime || "image/png";
  const name = blob instanceof File && blob.name && blob.name !== "blob"
    ? blob.name
    : clipboardImageFilename(type, new Date());
  return blob instanceof File && blob.name && blob.name !== "blob"
    ? blob
    : new File([blob], name, { type });
}

function imageFilesFromPaste(data: DataTransfer | null): File[] {
  if (!data) return [];
  const fromFiles = Array.from(data.files).filter((file) => file.type.startsWith("image/"));
  const raw = fromFiles.length > 0
    ? fromFiles
    : Array.from(data.items)
      .filter((item) => item.kind === "file" && item.type.startsWith("image/"))
      .map((item) => item.getAsFile())
      .filter((file): file is File => file !== null);
  return raw.map((file) => namedClipboardFile(file, file.type));
}

/** Chrome 写剪贴板只接受 PNG；其它格式先画到 canvas 再转。 */
async function blobAsPng(blob: Blob, fallbackMime: string | null): Promise<Blob> {
  const mime = (blob.type || fallbackMime || "").split(";")[0].trim().toLowerCase();
  if (mime === "image/png") {
    return blob.type === "image/png" ? blob : new Blob([blob], { type: "image/png" });
  }
  const bitmap = await createImageBitmap(blob);
  try {
    const canvas = document.createElement("canvas");
    canvas.width = bitmap.width;
    canvas.height = bitmap.height;
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("无法转换图片格式。");
    ctx.drawImage(bitmap, 0, 0);
    const png = await new Promise<Blob>((resolve, reject) => {
      canvas.toBlob(
        (result) => (result ? resolve(result) : reject(new Error("无法转换成 PNG。"))),
        "image/png",
      );
    });
    return png;
  } finally {
    bitmap.close();
  }
}

/**
 * 网页与手机互传文字、图片或小文件。服务端只在内存里转发，取走即删，10 分钟内有效。
 * 面板打开期间循环长轮询收件箱，页面隐藏时暂停。
 */
export default function RelayPanel() {
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [pollError, setPollError] = useState("");
  const [items, setItems] = useState<RelayItem[]>([]);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const fileInput = useRef<HTMLInputElement>(null);
  // 首次收到时按服务端给的剩余秒数算出本地截止时间，倒计时不受两端时钟偏差影响。
  const deadlines = useRef(new Map<string, number>());
  const knownIds = useRef<string[]>([]);

  const applyItems = useCallback((next: RelayItem[]) => {
    const receivedAt = Date.now();
    const ids = new Set(next.map((item) => item.id));
    for (const id of deadlines.current.keys()) {
      if (!ids.has(id)) deadlines.current.delete(id);
    }
    for (const item of next) {
      if (!deadlines.current.has(item.id)) {
        deadlines.current.set(item.id, receivedAt + item.expires_in * 1000);
      }
    }
    knownIds.current = next.map((item) => item.id);
    setItems(next);
    setNow(receivedAt);
  }, []);

  const removeLocal = useCallback((id: string) => {
    setItems((current) => {
      const next = current.filter((item) => item.id !== id);
      knownIds.current = next.map((item) => item.id);
      return next;
    });
    deadlines.current.delete(id);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const stopped = () => controller.signal.aborted;
    void (async () => {
      let failures = 0;
      while (!stopped()) {
        await waitUntilVisible(controller.signal);
        if (stopped()) return;
        try {
          const next = await pollRelayInbox(RELAY_WAIT_SECONDS, knownIds.current, controller.signal);
          if (stopped()) return;
          failures = 0;
          setPollError("");
          applyItems(next);
        } catch (caught) {
          if (stopped()) return;
          // 登录失效由全局处理（请求层已清掉令牌），这里不再重试。
          if (caught instanceof ApiError && caught.status === 401) {
            setPollError("登录已失效，请重新登录。");
            return;
          }
          failures += 1;
          setPollError("与服务器的连接中断，正在重试…");
          await sleep(Math.min(RETRY_MAX_MS, RETRY_BASE_MS * failures), controller.signal);
        }
      }
    })();
    return () => controller.abort();
  }, [applyItems]);

  // 有待接收内容时每秒刷新倒计时。
  useEffect(() => {
    if (items.length === 0) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, [items.length]);

  async function submitText(event?: FormEvent<HTMLFormElement>): Promise<void> {
    event?.preventDefault();
    if (sending) return;
    const problem = relayTextError(text);
    if (problem) { setError(problem); setNotice(""); return; }
    setSending(true); setError(""); setNotice("");
    try {
      await sendRelayText(text);
      setText("");
      setNotice("文字已发给手机，10 分钟内在手机上打开「传输」即可接收。");
    } catch (caught) {
      setError(describe(caught));
    } finally {
      setSending(false);
    }
  }

  async function sendFiles(files: File[]): Promise<void> {
    if (sending || files.length === 0) return;
    const problem = files.map(relayFileError).find(Boolean);
    if (problem) { setError(problem); setNotice(""); return; }
    setSending(true); setError(""); setNotice("");
    let sent = 0;
    try {
      for (const file of files) {
        setNotice(`正在发送「${file.name}」（${formatBytes(file.size)}）…`);
        await sendRelayFile(file);
        sent += 1;
      }
      setNotice(sent === 1
        ? `「${files[0].name}」已发给手机，10 分钟内有效。`
        : `${sent} 个文件已发给手机，10 分钟内有效。`);
    } catch (caught) {
      setNotice(sent > 0 ? `已发送 ${sent} 个文件。` : "");
      setError(describe(caught));
    } finally {
      setSending(false);
    }
  }

  async function pasteClipboardImage(): Promise<void> {
    if (sending) return;
    setError(""); setNotice("");
    if (!navigator.clipboard?.read) {
      setError("当前浏览器无法读取剪贴板图片（需要 HTTPS 或 localhost），请在本页按 Ctrl+V。");
      return;
    }
    try {
      const items = await navigator.clipboard.read();
      const files: File[] = [];
      for (const item of items) {
        const type = pickClipboardImageType(item.types);
        if (!type) continue;
        try {
          const blob = await item.getType(type);
          if (blob.size > 0) files.push(namedClipboardFile(blob, type));
        } catch {
          // 这一项不是可读的图片，继续看下一项。
        }
      }
      if (files.length === 0) {
        setError("剪贴板里没有图片，请先截图或复制图片，也可以在本页按 Ctrl+V。");
        return;
      }
      await sendFiles(files);
    } catch (caught) {
      setError(clipboardReadHint(caught));
    }
  }

  function handlePaste(event: ClipboardEvent<HTMLElement>): void {
    const files = imageFilesFromPaste(event.clipboardData);
    if (files.length === 0) return;
    event.preventDefault();
    void sendFiles(files);
  }

  async function download(item: RelayItem): Promise<void> {
    setBusyId(item.id); setError("");
    try {
      const blob = await downloadRelayItem(item.id);
      saveBlob(blob, item.filename ?? "file");
      removeLocal(item.id);
      setNotice(`已保存「${item.filename ?? "file"}」，服务端已删除这份内容。`);
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 404) {
        removeLocal(item.id);
        setError("这份内容已被取走或已过期。");
      } else {
        setError(describe(caught));
      }
    } finally {
      setBusyId(null);
    }
  }

  async function copyAndRemove(item: RelayItem): Promise<void> {
    if (item.text === null) return;
    setBusyId(item.id); setError("");
    try {
      await navigator.clipboard.writeText(item.text);
    } catch {
      setBusyId(null);
      setError("浏览器不允许写入剪贴板，请手动选中文字复制。");
      return;
    }
    try {
      await discardRelayItem(item.id);
    } catch (caught) {
      if (!(caught instanceof ApiError && caught.status === 404)) {
        setError(`已复制，但没能从服务端移除：${describe(caught)}`);
      }
    }
    removeLocal(item.id);
    setNotice("已复制到剪贴板，服务端已删除这段文字。");
    setBusyId(null);
  }

  async function copyImage(item: RelayItem): Promise<void> {
    setBusyId(item.id); setError(""); setNotice("");
    let original: Blob | undefined;
    const pngPromise = (async () => {
      original = await downloadRelayItem(item.id);
      return blobAsPng(original, item.mime_type);
    })();

    const fallbackDownload = async (reason: string) => {
      try {
        const blob = original ?? await pngPromise;
        saveBlob(blob, item.filename ?? "image");
        removeLocal(item.id);
        setError(`无法写入剪贴板，已改为下载。${reason ? ` ${reason}` : ""}`);
      } catch (caught) {
        if (caught instanceof ApiError && caught.status === 404) {
          removeLocal(item.id);
          setError("这份内容已被取走或已过期。");
        } else {
          setError(describe(caught));
        }
      }
    };

    try {
      if (typeof ClipboardItem === "undefined" || !navigator.clipboard?.write) {
        await fallbackDownload("当前浏览器不支持写入剪贴板图片。");
        return;
      }
      // ClipboardItem 必须在用户点击的同步栈里构造，Safari 才会保留用户手势。
      await navigator.clipboard.write([new ClipboardItem({ "image/png": pngPromise })]);
      removeLocal(item.id);
      setNotice("图片已复制到剪贴板，服务端已删除。");
    } catch (caught) {
      const downloadError = await pngPromise.then(() => null, (error: unknown) => error);
      if (downloadError instanceof ApiError && downloadError.status === 404) {
        removeLocal(item.id);
        setError("这份内容已被取走或已过期。");
      } else {
        await fallbackDownload(caught instanceof Error ? caught.message : "写入失败。");
      }
    } finally {
      setBusyId(null);
    }
  }

  async function discard(item: RelayItem): Promise<void> {
    setBusyId(item.id); setError("");
    try {
      await discardRelayItem(item.id);
      setNotice("已忽略。");
    } catch (caught) {
      if (!(caught instanceof ApiError && caught.status === 404)) {
        setError(describe(caught));
        setBusyId(null);
        return;
      }
    }
    removeLocal(item.id);
    setBusyId(null);
  }

  function handleDrop(event: DragEvent<HTMLElement>): void {
    event.preventDefault();
    setDragging(false);
    void sendFiles(Array.from(event.dataTransfer.files));
  }

  const visible = items.filter((item) => (deadlines.current.get(item.id) ?? 0) > now);

  return <section className="relay-panel" aria-label="传输" onPaste={handlePaste}>
    <div className="page-heading"><div><h1>传输</h1>
      <p className="page-subtitle">网页和手机互传文字、图片、小文件；服务器只转发不保存，10 分钟内有效</p></div></div>

    <form className="relay-card relay-send" onSubmit={(event) => void submitText(event)}>
      <h2>发给手机</h2>
      <label className="sr-only" htmlFor="relay-text">要发送的文字</label>
      <textarea id="relay-text" value={text} rows={4} readOnly={sending}
        placeholder="粘贴链接、验证码或一段文字，Ctrl + Enter 发送"
        onChange={(event) => { setText(event.target.value); setError(""); }}
        onKeyDown={(event) => {
          if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
            event.preventDefault();
            void submitText();
          }
        }} />
      <div className="relay-actions">
        <button className="primary" disabled={sending || !text.trim()}><Icon name="arrowRight" size={16} /> 发送文字</button>
        <button type="button" className="primary" disabled={sending} onClick={() => void pasteClipboardImage()}>
          <Icon name="image" size={16} /> 粘贴剪贴板图片
        </button>
        <button type="button" disabled={sending} onClick={() => fileInput.current?.click()}>
          <Icon name="upload" size={16} /> 选择文件
        </button>
        <input ref={fileInput} type="file" multiple hidden aria-label="选择要发送的文件"
          onChange={(event) => {
            const files = Array.from(event.currentTarget.files ?? []);
            event.currentTarget.value = "";
            void sendFiles(files);
          }} />
      </div>
      <div className={`relay-drop${dragging ? " active" : ""}`} aria-hidden="true"
        onDragOver={(event) => { event.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}>
        把文件拖到这里发送（单个不超过 20 MB），也可按 Ctrl+V 发送剪贴板图片
      </div>
      {notice && <p role="status" className="relay-notice">{notice}</p>}
      {error && <p role="alert" className="relay-error">{error}</p>}
    </form>

    <div className="relay-card">
      <h2>收到的内容 <small>{pollError || "保持此页打开即可自动接收"}</small></h2>
      {visible.length === 0 ? <p className="relay-empty">暂时没有。在手机上打开「传输」发送文字、图片或文件后，会自动出现在这里。</p>
        : <ul className="relay-items">
          {visible.map((item) => {
            const remaining = ((deadlines.current.get(item.id) ?? now) - now) / 1000;
            const busy = busyId === item.id;
            return <li key={item.id} className="relay-item">
              <div className="relay-item-info">
                <small>来自{relayDeviceLabels[item.source]} · {formatBytes(item.size)} · 剩余 {formatRemaining(remaining)}</small>
                {item.kind === "text"
                  ? <pre>{item.text}</pre>
                  : <strong>{item.filename ?? "file"}</strong>}
              </div>
              <div className="relay-actions">
                {item.kind === "text"
                  ? <button className="primary" disabled={busy} onClick={() => void copyAndRemove(item)}><Icon name="copy" size={16} /> 复制</button>
                  : isRelayImage(item)
                    ? <>
                      <button className="primary" disabled={busy} onClick={() => void copyImage(item)}>
                        <Icon name="copy" size={16} /> 复制图片
                      </button>
                      <button disabled={busy} onClick={() => void download(item)}>
                        <Icon name="download" size={16} /> 下载
                      </button>
                    </>
                    : <button className="primary" disabled={busy} onClick={() => void download(item)}><Icon name="download" size={16} /> 下载</button>}
                <button disabled={busy} onClick={() => void discard(item)}>忽略</button>
              </div>
            </li>;
          })}
        </ul>}
    </div>
  </section>;
}
