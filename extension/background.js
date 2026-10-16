const DEFAULT_CONFIG = {
  apiBaseUrl: "http://127.0.0.1:8000/api/v1",
  webBaseUrl: "http://localhost:5173/",
};
const MAX_SYNCED_BOOKMARKS = 5000;
const MAX_SELECTED_TEXT_LENGTH = 10000;
const ACCESS_TOKEN_STORAGE_KEY = "memoisle_access_token";
const WEB_CONTEXT_STORAGE_KEY = "memoisle_web_context";
const BOOKMARK_SYNC_STATE_STORAGE_KEY = "memoisle_bookmark_sync_state";
const CAPTURE_NOTIFICATION_ID = "memoisle-capture-result";
const PAGE_MENU_ID = "memoisle-capture-page";
const IMAGE_MENU_ID = "memoisle-capture-image";
// 图片相关的独立通知 ID，避免与「撤销 / 查看资料」按钮状态互相干扰。
const IMAGE_NOTIFICATION_ID = "memoisle-image-notice";
const MAX_IMAGE_BYTES = 20 * 1024 * 1024;
const MAX_IMAGE_SIDE = 12000;
const MAX_IMAGE_PIXELS = 50_000_000;
const MAX_IMAGE_TITLE_LENGTH = 200;
const MAX_IMAGE_NOTICE_LENGTH = 300;
const DEFAULT_IMAGE_TITLE = "网页图片";
const ACCEPTED_IMAGE_MIMES = new Set([
  "image/png",
  "image/jpeg",
  "image/webp",
  "image/gif",
]);
const IMAGE_MIME_LABELS = {
  "image/png": "PNG",
  "image/jpeg": "JPEG",
  "image/webp": "WebP",
  "image/gif": "GIF",
};
// 压缩时先按画质递减，再整体缩小，直到满足字节上限。
const IMAGE_COMPRESS_QUALITIES = [0.9, 0.8, 0.7, 0.6, 0.55];
const IMAGE_COMPRESS_SHRINK = 0.75;
const IMAGE_COMPRESS_MAX_ROUNDS = 5;
// 本地开发端口由 DevDeck 之类的启动器动态分配，扩展信任这段端口上的 MemoIsle Web。
// 修改这里时必须同步 manifest.json 的 content_scripts.matches。
const LOCAL_WEB_PORTS = [5173, 5174, 5175, 5176, 5177, 5178];
const LOCAL_WEB_HOSTS = ["localhost", "127.0.0.1"];
const LOCAL_WEB_ORIGINS = new Set(
  LOCAL_WEB_HOSTS.flatMap((host) =>
    LOCAL_WEB_PORTS.map((port) => `http://${host}:${port}`),
  ),
);
let bookmarkSyncTimer = null;
let bookmarkFullSyncTimer = null;
let bookmarkRetryTimer = null;
let tabSyncTimer = null;
const TAB_SYNC_DEBOUNCE_MS = 400;
const TAB_SYNC_FETCH_TIMEOUT_MS = 2_500;
const CAPTURE_FETCH_TIMEOUT_MS = 12_000;
let bookmarkSyncChain = Promise.resolve();
let bookmarkChangeSequence = 0;
const pendingBookmarkChanges = new Map();
// 最近一次由扩展直接收藏的条目，用于通知里的撤销动作。
let lastCapturedMemo = null;

function normalizeClientId(value) {
  return String(value || "").replaceAll("-", "").toLowerCase();
}

function readHttpOrigin(value) {
  try {
    const parsed = new URL(String(value || "").trim());
    if (!["http:", "https:"].includes(parsed.protocol)) {
      return null;
    }
    return parsed.origin;
  } catch {
    return null;
  }
}

function normalizeApiBaseUrl(value) {
  try {
    const parsed = new URL(String(value || "").trim());
    if (!["http:", "https:"].includes(parsed.protocol)) {
      return null;
    }
    if (parsed.username || parsed.password || parsed.search || parsed.hash) {
      return null;
    }
    return parsed.toString().replace(/\/$/, "");
  } catch {
    return null;
  }
}

function isTrustedWebSender(tabUrl, webBaseUrl) {
  try {
    const tabOrigin = new URL(tabUrl).origin;
    const configured = new URL(webBaseUrl);
    if (tabOrigin === configured.origin) {
      return true;
    }
    const configuredHost = configured.hostname.toLowerCase();
    const isLocalWeb =
      configuredHost === "localhost" || configuredHost === "127.0.0.1";
    return isLocalWeb && LOCAL_WEB_ORIGINS.has(tabOrigin);
  } catch {
    return false;
  }
}

function isPrivateIpv4(hostname) {
  const parts = hostname.split(".").map((part) => Number(part));
  if (parts.length !== 4 || parts.some((part) => !Number.isInteger(part))) {
    return false;
  }
  return (
    parts[0] === 10 ||
    parts[0] === 127 ||
    (parts[0] === 169 && parts[1] === 254) ||
    (parts[0] === 172 && parts[1] >= 16 && parts[1] <= 31) ||
    (parts[0] === 192 && parts[1] === 168)
  );
}

function isSupportedPage(pageUrl) {
  try {
    const parsed = new URL(pageUrl);
    const hostname = parsed.hostname.toLowerCase().replace(/\.$/, "");
    if (!["http:", "https:"].includes(parsed.protocol) || !hostname) {
      return false;
    }
    if (
      hostname === "localhost" ||
      hostname.endsWith(".localhost") ||
      isPrivateIpv4(hostname) ||
      hostname === "::1" ||
      hostname.startsWith("fc") ||
      hostname.startsWith("fd") ||
      hostname.startsWith("fe80:")
    ) {
      return false;
    }
    return true;
  } catch {
    return false;
  }
}

function sanitizeSelectedText(value) {
  // 只保留用户明确选中的文字，不读取页面正文或其他 DOM 内容。
  return String(value || "")
    .replaceAll("\u0000", "")
    .trim()
    .slice(0, MAX_SELECTED_TEXT_LENGTH);
}

async function readSelectedText(tabId) {
  if (!Number.isInteger(tabId) || !chrome.scripting?.executeScript) {
    return "";
  }
  try {
    const results = await chrome.scripting.executeScript({
      target: { tabId },
      func: () => window.getSelection?.().toString() || "",
    });
    return sanitizeSelectedText(results?.[0]?.result);
  } catch {
    // 页面拒绝脚本注入时仍可收藏网址，不阻断主流程。
    return "";
  }
}

async function readStoredWebContext() {
  const stored = await chrome.storage.local.get(WEB_CONTEXT_STORAGE_KEY);
  const context = stored?.[WEB_CONTEXT_STORAGE_KEY];
  if (!context || typeof context !== "object") {
    return null;
  }
  const webBaseUrl = readHttpOrigin(context.webBaseUrl);
  if (!webBaseUrl) {
    return null;
  }
  return { webBaseUrl, apiBaseUrl: normalizeApiBaseUrl(context.apiBaseUrl) };
}

async function saveWebContext(webBaseUrl, apiBaseUrl) {
  await chrome.storage.local.set({
    [WEB_CONTEXT_STORAGE_KEY]: {
      webBaseUrl,
      apiBaseUrl: apiBaseUrl || null,
      updatedAt: new Date().toISOString(),
    },
  });
}

// 只有真正跑过内容脚本的 MemoIsle 页面才能登记地址，且只能登记自己所在的源。
async function rememberWebContext(sender, message, config) {
  const senderOrigin = readHttpOrigin(sender?.tab?.url);
  if (!senderOrigin || !isTrustedWebSender(sender.tab.url, config.webBaseUrl)) {
    return false;
  }
  const reportedOrigin = readHttpOrigin(message?.webOrigin) || senderOrigin;
  if (reportedOrigin !== senderOrigin) {
    return false;
  }
  const previous = await readStoredWebContext();
  const sameOriginAsBefore = previous?.webBaseUrl === senderOrigin;
  const reportedApiBaseUrl = normalizeApiBaseUrl(message?.apiBaseUrl);
  // 页面只报来源不报 API 地址时，沿用同一来源上一次登记的 API 地址。
  const apiBaseUrl =
    reportedApiBaseUrl || (sameOriginAsBefore ? previous.apiBaseUrl : null);
  if (sameOriginAsBefore && previous.apiBaseUrl === apiBaseUrl) {
    return true;
  }
  await saveWebContext(senderOrigin, apiBaseUrl);
  return true;
}

function pickLearnedApiBaseUrl(context, learnedWebBaseUrl, explicitWebBaseUrl) {
  if (!context?.apiBaseUrl || !learnedWebBaseUrl) {
    return null;
  }
  if (readHttpOrigin(context.apiBaseUrl) === readHttpOrigin(learnedWebBaseUrl)) {
    // 本地开发走 Vite 代理，页面与 API 同源，直接沿用。
    return context.apiBaseUrl;
  }
  // 跨源 API 只在用户显式配置过同一个 Web 地址时才采用，避免被同机其他服务冒充。
  if (
    explicitWebBaseUrl &&
    readHttpOrigin(explicitWebBaseUrl) === readHttpOrigin(learnedWebBaseUrl)
  ) {
    return context.apiBaseUrl;
  }
  return null;
}

async function readConfig() {
  const [stored, context] = await Promise.all([
    chrome.storage.sync.get(["apiBaseUrl", "webBaseUrl"]),
    readStoredWebContext(),
  ]);
  const explicitApiBaseUrl = normalizeApiBaseUrl(stored?.apiBaseUrl);
  const explicitWebBaseUrl =
    typeof stored?.webBaseUrl === "string" && stored.webBaseUrl.trim()
      ? stored.webBaseUrl.trim()
      : null;
  const learnedWebBaseUrl =
    context &&
    isTrustedWebSender(
      context.webBaseUrl,
      explicitWebBaseUrl || DEFAULT_CONFIG.webBaseUrl,
    )
      ? context.webBaseUrl
      : null;
  return {
    // 显式配置 > 页面登记的地址 > 内置默认值。
    apiBaseUrl:
      explicitApiBaseUrl ||
      pickLearnedApiBaseUrl(context, learnedWebBaseUrl, explicitWebBaseUrl) ||
      DEFAULT_CONFIG.apiBaseUrl,
    webBaseUrl:
      explicitWebBaseUrl || learnedWebBaseUrl || DEFAULT_CONFIG.webBaseUrl,
  };
}

async function readAccessToken() {
  const stored = await chrome.storage.local.get(ACCESS_TOKEN_STORAGE_KEY);
  const accessToken = stored?.[ACCESS_TOKEN_STORAGE_KEY];
  if (typeof accessToken !== "string" || !accessToken.trim()) {
    return null;
  }
  return accessToken.trim();
}

async function requestHeaders() {
  const headers = { "Content-Type": "application/json" };
  const accessToken = await readAccessToken();
  if (accessToken) {
    headers.Authorization = `Bearer ${accessToken}`;
  }
  return headers;
}

async function fetchWithTimeout(url, options = {}, timeoutMs) {
  if (typeof AbortController !== "function" || !timeoutMs) {
    return fetch(url, options);
  }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

function scheduleOpenTabSync() {
  if (tabSyncTimer !== null) {
    clearTimeout(tabSyncTimer);
  }
  tabSyncTimer = setTimeout(() => {
    tabSyncTimer = null;
    void syncOpenTabs();
  }, TAB_SYNC_DEBOUNCE_MS);
}

function enqueueBookmarkSync(operation) {
  bookmarkSyncChain = bookmarkSyncChain.then(operation, operation);
  return bookmarkSyncChain;
}

async function readBookmarkSyncState() {
  const stored = await chrome.storage.local.get(BOOKMARK_SYNC_STATE_STORAGE_KEY);
  const state = stored?.[BOOKMARK_SYNC_STATE_STORAGE_KEY];
  if (
    !state ||
    !Number.isInteger(state.revision) ||
    !Number.isInteger(state.totalCount) ||
    state.totalCount < 0
  ) {
    return null;
  }
  return {
    revision: state.revision,
    totalCount: state.totalCount,
    itemIds: Array.isArray(state.itemIds)
      ? state.itemIds.map((itemId) => String(itemId))
      : [],
  };
}

async function saveBookmarkSyncState(state) {
  await chrome.storage.local.set({
    [BOOKMARK_SYNC_STATE_STORAGE_KEY]: {
      revision: state.revision,
      totalCount: state.totalCount,
      itemIds: [...new Set(state.itemIds)].slice(0, MAX_SYNCED_BOOKMARKS),
    },
  });
}

async function clearBookmarkSyncState() {
  await chrome.storage.local.remove(BOOKMARK_SYNC_STATE_STORAGE_KEY);
}

async function openWebCapture(config, token, errorCode, attemptedApiBaseUrl = null) {
  const target = new URL(config.webBaseUrl);
  if (token) {
    target.searchParams.set("memoisle_capture", token);
  }
  if (errorCode) {
    target.searchParams.set("memoisle_capture_error", errorCode);
  }
  if (errorCode === "connection_failed" && attemptedApiBaseUrl) {
    // 带上扩展实际尝试的地址，便于确认后端端口或地址是否对得上。
    target.searchParams.set("memoisle_capture_api", attemptedApiBaseUrl);
  }
  await chrome.tabs.create({ url: target.toString() });
}

function isHttpUrl(value) {
  try {
    return ["http:", "https:"].includes(new URL(String(value || "")).protocol);
  } catch {
    return false;
  }
}

// 以下图片相关函数保持纯粹、无 chrome/DOM 依赖，便于评审与单元测试。

function isImageOverLimits(byteCount, width = null, height = null) {
  if (Number.isFinite(byteCount) && byteCount > MAX_IMAGE_BYTES) {
    return true;
  }
  const widthKnown = Number.isFinite(width) && width > 0;
  const heightKnown = Number.isFinite(height) && height > 0;
  if (widthKnown && width > MAX_IMAGE_SIDE) {
    return true;
  }
  if (heightKnown && height > MAX_IMAGE_SIDE) {
    return true;
  }
  if (widthKnown && heightKnown && width * height > MAX_IMAGE_PIXELS) {
    return true;
  }
  return false;
}

function sniffImageMime(bytes) {
  const view = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes || []);
  const startsWith = (...signature) =>
    view.length >= signature.length &&
    signature.every((byte, index) => view[index] === byte);
  if (startsWith(0x89, 0x50, 0x4e, 0x47)) {
    return "image/png";
  }
  if (startsWith(0xff, 0xd8, 0xff)) {
    return "image/jpeg";
  }
  if (startsWith(0x47, 0x49, 0x46, 0x38)) {
    return "image/gif";
  }
  // RIFF....WEBP
  if (
    startsWith(0x52, 0x49, 0x46, 0x46) &&
    view.length >= 12 &&
    view[8] === 0x57 &&
    view[9] === 0x45 &&
    view[10] === 0x42 &&
    view[11] === 0x50
  ) {
    return "image/webp";
  }
  return null;
}

function imageTitleFromUrl(url) {
  try {
    const parsed = new URL(String(url || ""));
    if (parsed.protocol === "data:") {
      return DEFAULT_IMAGE_TITLE;
    }
    const segments = parsed.pathname.split("/").filter(Boolean);
    const rawName = segments[segments.length - 1] || "";
    let name = rawName;
    try {
      name = decodeURIComponent(rawName);
    } catch {
      name = rawName;
    }
    const withoutExtension = name.replace(/\.[A-Za-z0-9]{1,8}$/, "").trim();
    const title = (withoutExtension || name).trim();
    return title ? title.slice(0, MAX_IMAGE_TITLE_LENGTH) : DEFAULT_IMAGE_TITLE;
  } catch {
    return DEFAULT_IMAGE_TITLE;
  }
}

function formatImageBytes(bytes) {
  const value = Number(bytes);
  if (!Number.isFinite(value) || value <= 0) {
    return "0 B";
  }
  if (value < 1024) {
    return `${Math.round(value)} B`;
  }
  const units = ["KB", "MB", "GB"];
  let size = value / 1024;
  let unitIndex = 0;
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }
  return `${size.toFixed(1)} ${units[unitIndex]}`;
}

function imageMimeLabel(mime) {
  return IMAGE_MIME_LABELS[mime] || String(mime || "").replace("image/", "").toUpperCase();
}

function describeImageCompression(result) {
  if (!result) {
    return "";
  }
  const segments = [];
  if (
    Number.isFinite(result.originalBytes) &&
    Number.isFinite(result.finalBytes) &&
    result.originalBytes !== result.finalBytes
  ) {
    segments.push(`${formatImageBytes(result.originalBytes)} → ${formatImageBytes(result.finalBytes)}`);
  }
  const dimensionsChanged =
    Number.isFinite(result.originalWidth) &&
    Number.isFinite(result.originalHeight) &&
    Number.isFinite(result.finalWidth) &&
    Number.isFinite(result.finalHeight) &&
    (result.originalWidth !== result.finalWidth ||
      result.originalHeight !== result.finalHeight);
  if (dimensionsChanged) {
    segments.push(
      `尺寸 ${result.originalWidth} × ${result.originalHeight} → ${result.finalWidth} × ${result.finalHeight}`,
    );
  }
  if (
    result.originalMime &&
    result.finalMime &&
    result.originalMime !== result.finalMime
  ) {
    segments.push(
      `格式 ${imageMimeLabel(result.originalMime)} → ${imageMimeLabel(result.finalMime)}`,
    );
  }
  if (result.originalMime === "image/gif") {
    // OffscreenCanvas 只解码第一帧，压缩后的 GIF 会变成静态图。
    segments.push("动图已转为静态图，仅保留第一帧");
  }
  if (segments.length === 0) {
    return "";
  }
  return `已自动压缩后上传：${segments.join("；")}`;
}

function scaleImageDimensions(width, height) {
  let scale = 1;
  const longestSide = Math.max(width, height);
  if (longestSide > MAX_IMAGE_SIDE) {
    scale = Math.min(scale, MAX_IMAGE_SIDE / longestSide);
  }
  if (width * height * scale * scale > MAX_IMAGE_PIXELS) {
    scale = Math.min(scale, Math.sqrt(MAX_IMAGE_PIXELS / (width * height)));
  }
  return {
    width: Math.max(1, Math.floor(width * scale)),
    height: Math.max(1, Math.floor(height * scale)),
  };
}

async function probeImageDimensions(bytes, mime) {
  try {
    const bitmap = await createImageBitmap(
      new Blob([bytes], { type: mime || "application/octet-stream" }),
    );
    const width = Number(bitmap?.width) || 0;
    const height = Number(bitmap?.height) || 0;
    if (typeof bitmap?.close === "function") {
      bitmap.close();
    }
    return width > 0 && height > 0 ? { width, height } : null;
  } catch {
    return null;
  }
}

async function pickImageEncoderMime(bitmap) {
  for (const type of ["image/webp", "image/jpeg"]) {
    try {
      const canvas = new OffscreenCanvas(1, 1);
      const context = canvas.getContext("2d");
      if (!context) {
        continue;
      }
      context.drawImage(bitmap, 0, 0, 1, 1);
      const probe = await canvas.convertToBlob({ type, quality: 0.8 });
      // 浏览器不支持目标编码时会回退到 PNG，此时继续尝试下一种格式。
      if (probe && probe.size > 0 && (!probe.type || probe.type === type)) {
        return type;
      }
    } catch {
      // 忽略探测异常，继续尝试下一种编码格式。
    }
  }
  return null;
}

async function compressImageBytes(bytes, sourceMime, sourceDimensions) {
  if (
    typeof createImageBitmap !== "function" ||
    typeof OffscreenCanvas !== "function"
  ) {
    return null;
  }
  let bitmap;
  try {
    bitmap = await createImageBitmap(
      new Blob([bytes], { type: sourceMime || "application/octet-stream" }),
    );
  } catch {
    return null;
  }
  if (!bitmap) {
    return null;
  }
  try {
    const sourceWidth = Number(bitmap.width) || Number(sourceDimensions?.width) || 0;
    const sourceHeight = Number(bitmap.height) || Number(sourceDimensions?.height) || 0;
    if (!sourceWidth || !sourceHeight) {
      return null;
    }
    const targetMime = await pickImageEncoderMime(bitmap);
    if (!targetMime) {
      return null;
    }
    let target = scaleImageDimensions(sourceWidth, sourceHeight);

    for (let round = 0; round < IMAGE_COMPRESS_MAX_ROUNDS; round += 1) {
      let canvas;
      let context;
      try {
        canvas = new OffscreenCanvas(target.width, target.height);
        context = canvas.getContext("2d");
      } catch {
        return null;
      }
      if (!context) {
        return null;
      }
      try {
        context.drawImage(bitmap, 0, 0, target.width, target.height);
      } catch {
        return null;
      }

      for (const quality of IMAGE_COMPRESS_QUALITIES) {
        let blob;
        try {
          blob = await canvas.convertToBlob({ type: targetMime, quality });
        } catch {
          return null;
        }
        if (!blob || typeof blob.size !== "number") {
          return null;
        }
        if (blob.size <= MAX_IMAGE_BYTES) {
          const mime = ACCEPTED_IMAGE_MIMES.has(blob.type) ? blob.type : targetMime;
          return {
            bytes: new Uint8Array(await blob.arrayBuffer()),
            mime,
            compression: {
              originalBytes: bytes.byteLength ?? bytes.length ?? 0,
              finalBytes: blob.size,
              originalWidth: sourceWidth,
              originalHeight: sourceHeight,
              finalWidth: target.width,
              finalHeight: target.height,
              originalMime: sourceMime || null,
              finalMime: mime,
            },
          };
        }
      }

      target = {
        width: Math.max(1, Math.floor(target.width * IMAGE_COMPRESS_SHRINK)),
        height: Math.max(1, Math.floor(target.height * IMAGE_COMPRESS_SHRINK)),
      };
    }
    return null;
  } finally {
    if (typeof bitmap.close === "function") {
      bitmap.close();
    }
  }
}

async function prepareImageForUpload(bytes, mime) {
  const byteCount = bytes?.byteLength ?? bytes?.length ?? 0;
  let dimensions = null;
  if (typeof createImageBitmap === "function") {
    dimensions = await probeImageDimensions(bytes, mime);
  }
  if (!isImageOverLimits(byteCount, dimensions?.width ?? null, dimensions?.height ?? null)) {
    // 尺寸未知但字节数在范围内时按原图上传。
    return { bytes, mime, compression: null };
  }
  // 超过服务端限制时必须压缩，压缩能力不可用则交给上层提示改用 Web 端。
  return compressImageBytes(bytes, mime, dimensions);
}

async function readImageErrorDetail(response) {
  try {
    const payload = await response.json();
    const detail = payload?.detail;
    if (typeof detail === "string" && detail.trim()) {
      return detail.trim();
    }
    if (Array.isArray(detail)) {
      const first = detail
        .map((item) => (typeof item === "string" ? item : item?.msg))
        .find((item) => typeof item === "string" && item.trim());
      if (first) {
        return first.trim();
      }
    }
  } catch {
    // 忽略解析失败，使用默认文案。
  }
  return null;
}

function connectionFailureNotice(config) {
  // 带上实际尝试的地址，方便确认后端端口和扩展配置是否一致。
  return `无法连接 MemoIsle（${config?.apiBaseUrl || DEFAULT_CONFIG.apiBaseUrl}），请确认后端已启动，或先打开 MemoIsle 网页端后重试。`;
}

async function showImageNotice(title, message) {
  try {
    // 通知失败或系统禁用时静默降级，不影响用户操作。
    await new Promise((resolve) => {
      chrome.notifications.create(
        IMAGE_NOTIFICATION_ID,
        {
          type: "basic",
          iconUrl: chrome.runtime.getURL("icons/icon128.png"),
          title,
          message: String(message || "").slice(0, MAX_IMAGE_NOTICE_LENGTH),
        },
        resolve,
      );
    });
  } catch {
    // 忽略通知异常。
  }
}

function queryAllTabs() {
  return new Promise((resolve) => {
    chrome.tabs.query({}, resolve);
  });
}

function readBookmarkTree() {
  return new Promise((resolve, reject) => {
    chrome.bookmarks.getTree((nodes) => {
      const runtimeError = chrome.runtime.lastError;
      if (runtimeError) {
        reject(new Error(runtimeError.message));
        return;
      }
      resolve(nodes || []);
    });
  });
}

function flattenBookmarkTree(nodes) {
  const bookmarks = [];

  function visit(node, folderNames) {
    if (node?.url) {
      const pageUrl = String(node.url).trim();
      if (!pageUrl || pageUrl.length > 2048) {
        return;
      }
      bookmarks.push({
        client_item_id: `chrome:${String(node.id)}`.slice(0, 100),
        title: String(node.title || "").trim().slice(0, 300),
        url: pageUrl,
        folder_path: folderNames.join(" / ").slice(0, 1000) || null,
      });
      return;
    }

    const folderTitle = String(node?.title || "").trim();
    const nextFolders = folderTitle
      ? [...folderNames, folderTitle]
      : folderNames;
    for (const child of node?.children || []) {
      visit(child, nextFolders);
    }
  }

  for (const node of nodes || []) {
    visit(node, []);
  }
  return bookmarks;
}

async function performFullBookmarkSync(config = null) {
  const generationAtRead = bookmarkChangeSequence;
  const resolvedConfig = config || await readConfig();
  const allBookmarks = flattenBookmarkTree(await readBookmarkTree());
  const headers = await requestHeaders();
  const response = await fetch(`${resolvedConfig.apiBaseUrl}/browser-bookmarks/sync`, {
    method: "POST",
    headers,
    body: JSON.stringify({
      extension_id: chrome.runtime.id,
      items: allBookmarks.slice(0, MAX_SYNCED_BOOKMARKS),
      total_count: allBookmarks.length,
    }),
  });
  if (!response.ok) {
    throw new Error(`书签完整同步失败（${response.status}）`);
  }
  const result = await response.json();
  if (!Number.isInteger(result.revision)) {
    // 兼容尚未升级的服务端，禁止继续用不可信游标发送增量。
    await clearBookmarkSyncState();
    return;
  }
  await saveBookmarkSyncState({
    revision: result.revision,
    totalCount: allBookmarks.length,
    itemIds: allBookmarks
      .slice(0, MAX_SYNCED_BOOKMARKS)
      .map((item) => item.client_item_id),
  });
  // 完整快照已经包含读树时之前发生的事件，读树之后的新事件继续保留。
  for (const [clientItemId, change] of pendingBookmarkChanges) {
    if (change.generation <= generationAtRead) {
      pendingBookmarkChanges.delete(clientItemId);
    }
  }
}

async function syncBookmarks(config = null) {
  try {
    await enqueueBookmarkSync(() => performFullBookmarkSync(config));
  } catch {
    scheduleBookmarkRetry();
    // 书签同步失败不影响当前页捕获和 @网页 标签页同步。
  }
}

function scheduleBookmarkRetry() {
  if (bookmarkRetryTimer !== null) {
    return;
  }
  bookmarkRetryTimer = setTimeout(() => {
    bookmarkRetryTimer = null;
    void enqueueBookmarkSync(() => performFullBookmarkSync()).catch(() => {
      scheduleBookmarkRetry();
    });
  }, 5_000);
}

function scheduleFullBookmarkSync() {
  if (bookmarkSyncTimer !== null) {
    clearTimeout(bookmarkSyncTimer);
    bookmarkSyncTimer = null;
  }
  if (bookmarkFullSyncTimer !== null) {
    clearTimeout(bookmarkFullSyncTimer);
  }
  // 文件夹移动、批量导入或文件夹删除会影响多个后代路径，必须重建快照。
  bookmarkFullSyncTimer = setTimeout(() => {
    bookmarkFullSyncTimer = null;
    void enqueueBookmarkSync(() => performFullBookmarkSync()).catch(() => {
      scheduleBookmarkRetry();
    });
  }, 400);
}

function queueBookmarkChange(change) {
  const previous = pendingBookmarkChanges.get(change.client_item_id);
  bookmarkChangeSequence += 1;
  pendingBookmarkChanges.set(change.client_item_id, {
    ...change,
    generation: bookmarkChangeSequence,
    countDelta: (previous?.countDelta || 0) + (change.countDelta || 0),
  });
  if (bookmarkFullSyncTimer !== null) {
    clearTimeout(bookmarkFullSyncTimer);
    bookmarkFullSyncTimer = null;
  }
  if (bookmarkSyncTimer !== null) {
    clearTimeout(bookmarkSyncTimer);
  }
  // 连续事件合并后再发送，避免一次拖拽产生大量请求。
  bookmarkSyncTimer = setTimeout(() => {
    bookmarkSyncTimer = null;
    void enqueueBookmarkSync(() => flushBookmarkChanges()).catch(() => {
      scheduleBookmarkRetry();
    });
  }, 400);
}

async function flushBookmarkChanges() {
  const batch = [...pendingBookmarkChanges.values()];
  if (batch.length === 0) {
    return;
  }
  for (const change of batch) {
    if (pendingBookmarkChanges.get(change.client_item_id)?.generation === change.generation) {
      pendingBookmarkChanges.delete(change.client_item_id);
    }
  }
  try {
    const state = await readBookmarkSyncState();
    if (state === null) {
      await performFullBookmarkSync();
      return;
    }
    const totalCount = Math.max(
      0,
      state.totalCount + batch.reduce((sum, change) => sum + change.countDelta, 0),
    );
    const response = await fetch(`${(await readConfig()).apiBaseUrl}/browser-bookmarks/delta`, {
      method: "POST",
      headers: await requestHeaders(),
      body: JSON.stringify({
        extension_id: chrome.runtime.id,
        base_revision: state.revision,
        total_count: totalCount,
        changes: batch.map((change) => ({
          action: change.action,
          client_item_id: change.client_item_id,
          ...(change.item ? { item: change.item } : {}),
        })),
      }),
    });
    if (response.status === 404 || response.status === 409) {
      // 旧服务端或其他设备已推进版本时，以本地浏览器当前树为准重建。
      await performFullBookmarkSync();
      return;
    }
    if (!response.ok) {
      throw new Error(`书签增量同步失败（${response.status}）`);
    }
    const result = await response.json();
    if (!Number.isInteger(result.revision)) {
      await performFullBookmarkSync();
      return;
    }
    const itemIds = new Set(state.itemIds);
    batch.forEach((change) => {
      if (change.action === "remove") {
        itemIds.delete(change.client_item_id);
      } else {
        itemIds.add(change.client_item_id);
      }
    });
    await saveBookmarkSyncState({
      revision: result.revision,
      totalCount: Number.isInteger(result.total_count) ? result.total_count : totalCount,
      itemIds: [...itemIds],
    });
  } catch (error) {
    // 网络故障时恢复未被更新事件覆盖的变更，稍后用完整快照重新校准。
    for (const change of batch) {
      const current = pendingBookmarkChanges.get(change.client_item_id);
      if (!current || current.generation < change.generation) {
        pendingBookmarkChanges.set(change.client_item_id, change);
      }
    }
    throw error;
  }
}

function scheduleBookmarkSync() {
  scheduleFullBookmarkSync();
}

function readBookmarkNode(id) {
  return new Promise((resolve, reject) => {
    chrome.bookmarks.get(String(id), (nodes) => {
      const runtimeError = chrome.runtime.lastError;
      if (runtimeError) {
        reject(new Error(runtimeError.message));
        return;
      }
      resolve(nodes?.[0] || null);
    });
  });
}

async function readBookmarkFolderPath(parentId) {
  const folderNames = [];
  let currentId = parentId;
  while (currentId) {
    const node = await readBookmarkNode(currentId);
    if (!node) {
      break;
    }
    const title = String(node.title || "").trim();
    if (title) {
      folderNames.unshift(title);
    }
    if (!node.parentId || node.parentId === node.id) {
      break;
    }
    currentId = node.parentId;
  }
  return folderNames.join(" / ").slice(0, 1_000) || null;
}

async function bookmarkInputFromNode(node) {
  if (!node?.url) {
    return null;
  }
  const url = String(node.url).trim();
  if (!url || url.length > 2_048) {
    return null;
  }
  return {
    client_item_id: `chrome:${String(node.id)}`.slice(0, 100),
    title: String(node.title || "").trim().slice(0, 300),
    url,
    folder_path: await readBookmarkFolderPath(node.parentId),
  };
}

async function queueBookmarkUpsert(id, node = null, countDelta = 0) {
  try {
    const resolvedNode = node?.url ? node : await readBookmarkNode(id);
    const item = await bookmarkInputFromNode(resolvedNode);
    if (!item) {
      // 文件夹标题变化会影响后代的路径，交给完整快照处理。
      scheduleFullBookmarkSync();
      return;
    }
    queueBookmarkChange({
      action: "upsert",
      client_item_id: item.client_item_id,
      item,
      countDelta,
    });
  } catch {
    scheduleFullBookmarkSync();
  }
}

async function queueBookmarkRemoval(id) {
  try {
    const state = await readBookmarkSyncState();
    const clientItemId = `chrome:${String(id)}`.slice(0, 100);
    if (!state || !state.itemIds.includes(clientItemId)) {
      // 未知 ID 可能是被删除的文件夹，无法只删除单个叶子节点。
      scheduleFullBookmarkSync();
      return;
    }
    queueBookmarkChange({
      action: "remove",
      client_item_id: clientItemId,
      countDelta: -1,
    });
  } catch {
    scheduleFullBookmarkSync();
  }
}

async function syncOpenTabs(config = null) {
  try {
    const resolvedConfig = config || await readConfig();
    const tabs = await queryAllTabs();
    const headers = await requestHeaders();
    const openTabs = tabs
      .filter((tab) => Number.isInteger(tab?.id) && isSupportedPage(tab.url))
      .map((tab) => ({
        tab_id: tab.id,
        window_id: Number.isInteger(tab.windowId) ? tab.windowId : null,
        page_url: tab.url,
        page_title: tab.title || "",
        favicon_url: tab.favIconUrl || null,
      }));
    await fetchWithTimeout(
      `${resolvedConfig.apiBaseUrl}/browser-tabs/sync`,
      {
        method: "POST",
        headers,
        body: JSON.stringify({
          extension_id: chrome.runtime.id,
          tabs: openTabs,
        }),
      },
      TAB_SYNC_FETCH_TIMEOUT_MS,
    );
  } catch {
    // 浏览器标签页同步失败不阻止当前页的一次性收藏流程。
  }
}

async function captureTab(tab, selectedTextOverride = null) {
  const config = await readConfig();
  if (!tab?.url || !isSupportedPage(tab.url)) {
    await openWebCapture(config, null, "unsupported_page");
    return;
  }

  // 标签页快照独立刷新，慢请求不应阻塞用户明确触发的收藏。
  void syncOpenTabs(config);

  const headers = await requestHeaders();
  if (!headers.Authorization) {
    // 还没有同步过登录凭证时，直接打开 Web 引导登录。
    await openWebCapture(config, null, "not_authenticated");
    return;
  }

  try {
    const selectedText =
      selectedTextOverride === null
        ? await readSelectedText(tab.id)
        : sanitizeSelectedText(selectedTextOverride);
    const clientId = crypto.randomUUID();
    const response = await fetchWithTimeout(
      `${config.apiBaseUrl}/memos`,
      {
        method: "POST",
        headers,
        body: JSON.stringify({
          client_id: clientId,
          type: "resource",
          body: selectedText || tab.url,
          source_url: tab.url,
          source_title: (tab.title || "").trim() || undefined,
          tags: [],
        }),
      },
      CAPTURE_FETCH_TIMEOUT_MS,
    );
    if (response.status === 401 || response.status === 403) {
      // 登录已失效，打开 Web 让用户重新登录。
      await openWebCapture(config, null, "not_authenticated");
      return;
    }
    if (response.status === 409) {
      // 后端以冲突响应返回已有资料，重复收藏应展示原条目而不是报错。
      const payload = await response.json().catch(() => null);
      const current = payload?.detail?.current;
      if (
        payload?.detail?.code === "duplicate_resource" &&
        typeof current?.id === "string" &&
        current.id.trim() &&
        Number.isInteger(current.version) &&
        current.version > 0
      ) {
        await showCaptureResult(config, tab, current, true, selectedText);
        return;
      }
    }
    if (!response.ok) {
      const errorCode =
        response.status === 422 ? "unsupported_page" : "capture_failed";
      await openWebCapture(config, null, errorCode);
      return;
    }
    const memo = await response.json();
    const duplicated =
      normalizeClientId(memo.client_id) !== normalizeClientId(clientId);
    await showCaptureResult(config, tab, memo, duplicated, selectedText);
  } catch {
    await openWebCapture(config, null, "connection_failed", config.apiBaseUrl);
  }
}

async function captureImage(info, tab) {
  const config = await readConfig();
  const token = await readAccessToken();
  if (!token) {
    // 还没有登录凭证时不请求图片，也不创建资料，直接引导 Web 登录。
    await showImageNotice(
      "请先登录 MemoIsle",
      "还没有登录 MemoIsle，请先在网页端登录后再收藏图片。",
    );
    await openWebCapture(config, null, "not_authenticated");
    return;
  }

  const srcUrl = String(info?.srcUrl || "").trim();
  let scheme = "";
  try {
    scheme = new URL(srcUrl).protocol;
  } catch {
    scheme = "";
  }
  if (!srcUrl || !["http:", "https:", "data:"].includes(scheme)) {
    if (scheme === "blob:") {
      await showImageNotice(
        "无法收藏图片",
        "这是页面临时图片，无法直接读取，请先另存或使用 MemoIsle 网页端收藏",
      );
    } else {
      await showImageNotice(
        "无法收藏图片",
        "不支持收藏这种地址的图片，请改用 MemoIsle 网页端收藏",
      );
    }
    return;
  }

  const unreadableMessage =
    "无法读取图片（可能受站点保护），可在 MemoIsle 网页端收藏";
  let response;
  try {
    // credentials: include 让需要登录态才能访问的图片也能按当前浏览器会话读取。
    response = await fetch(srcUrl, { credentials: "include" });
  } catch {
    await showImageNotice("无法收藏图片", unreadableMessage);
    return;
  }
  if (!response?.ok) {
    await showImageNotice("无法收藏图片", unreadableMessage);
    return;
  }

  let sourceBytes;
  try {
    sourceBytes = new Uint8Array(await response.arrayBuffer());
  } catch {
    await showImageNotice("无法收藏图片", unreadableMessage);
    return;
  }
  if (sourceBytes.byteLength === 0) {
    await showImageNotice("无法收藏图片", unreadableMessage);
    return;
  }

  // 先按魔数判断真实格式，再退回响应头，避免把伪装成图片的页面当成图片上传。
  const contentType = String(response.headers?.get?.("content-type") || "")
    .split(";")[0]
    .trim()
    .toLowerCase();
  const sourceMime =
    sniffImageMime(sourceBytes) ||
    (ACCEPTED_IMAGE_MIMES.has(contentType) ? contentType : null);
  if (!sourceMime) {
    await showImageNotice(
      "无法收藏图片",
      "图片格式不被支持，仅支持 PNG、JPEG、WebP、GIF，可在 MemoIsle 网页端收藏",
    );
    return;
  }

  const prepared = await prepareImageForUpload(sourceBytes, sourceMime);
  if (!prepared) {
    await showImageNotice(
      "图片过大，无法收藏",
      "图片超过 20 MB 或尺寸过大，当前浏览器无法自动压缩，请在 MemoIsle 网页端收藏",
    );
    return;
  }

  const title = imageTitleFromUrl(srcUrl);
  let memo;
  try {
    const createResponse = await fetch(`${config.apiBaseUrl}/memos`, {
      method: "POST",
      headers: await requestHeaders(),
      body: JSON.stringify({
        client_id: crypto.randomUUID(),
        type: "image",
        title,
        body: "",
        source_url: isHttpUrl(info?.pageUrl) ? info.pageUrl : undefined,
        source_title: (tab?.title || "").trim() || undefined,
        tags: [],
      }),
    });
    if (createResponse.status === 401 || createResponse.status === 403) {
      await openWebCapture(config, null, "not_authenticated");
      return;
    }
    if (!createResponse.ok) {
      await showImageNotice("无法收藏图片", `创建图片资料失败（${createResponse.status}）`);
      return;
    }
    memo = await createResponse.json();
  } catch {
    await showImageNotice("无法收藏图片", connectionFailureNotice(config));
    return;
  }
  if (!memo?.id) {
    await showImageNotice("无法收藏图片", connectionFailureNotice(config));
    return;
  }

  let uploadResponse;
  try {
    uploadResponse = await fetch(
      `${config.apiBaseUrl}/memos/${memo.id}/image?expected_version=${memo.version}`,
      {
        method: "POST",
        // 上传接口要求原始字节，不能复用 JSON 的 requestHeaders()。
        headers: {
          "Content-Type": prepared.mime,
          Authorization: `Bearer ${token}`,
        },
        body: prepared.bytes,
      },
    );
  } catch {
    await showImageNotice("图片上传失败", connectionFailureNotice(config));
    return;
  }

  if (uploadResponse.status === 401 || uploadResponse.status === 403) {
    await openWebCapture(config, null, "not_authenticated");
    return;
  }
  if (uploadResponse.status === 413) {
    await showImageNotice("图片超过 20 MB", "图片超过 20 MB，请在 MemoIsle 网页端压缩后再收藏");
    return;
  }
  if (uploadResponse.status === 409) {
    await showImageNotice("图片上传失败", "图片已在其他设备更新，请重试");
    return;
  }
  if (uploadResponse.status === 422) {
    const detail = await readImageErrorDetail(uploadResponse);
    await showImageNotice(
      "图片格式或尺寸不被支持",
      detail || "图片格式或尺寸不被支持，可在 MemoIsle 网页端收藏",
    );
    return;
  }
  if (!uploadResponse.ok) {
    await showImageNotice(
      "图片上传失败",
      `图片上传失败（${uploadResponse.status}），可在 MemoIsle 网页端收藏`,
    );
    return;
  }

  let uploaded = null;
  try {
    uploaded = await uploadResponse.json();
  } catch {
    uploaded = null;
  }
  const version = Number.isInteger(uploaded?.version)
    ? uploaded.version
    : Number.isInteger(memo.version)
      ? memo.version + 1
      : undefined;
  await showImageCaptureResult(title, prepared.compression, version, memo.id);
}

async function showImageCaptureResult(title, compression, version, memoId) {
  // 复用页面收藏的通知与撤销状态，撤销按钮可继续删除刚上传的图片资料。
  lastCapturedMemo = {
    id: memoId,
    version,
    deduplicated: false,
  };
  const reminder = describeImageCompression(compression);
  const message = reminder ? `${title}。${reminder}` : title;
  try {
    await new Promise((resolve) => {
      chrome.notifications.create(
        CAPTURE_NOTIFICATION_ID,
        {
          type: "basic",
          iconUrl: chrome.runtime.getURL("icons/icon128.png"),
          title: "已收藏图片到 MemoIsle",
          message: message.slice(0, MAX_IMAGE_NOTICE_LENGTH),
          buttons: [{ title: "撤销" }, { title: "查看资料" }],
        },
        resolve,
      );
    });
  } catch {
    // 忽略通知异常，不影响收藏结果。
  }
  await setCaptureBadge("✓");
  setTimeout(() => void setCaptureBadge(""), 3_000);
}

async function setCaptureBadge(text) {
  try {
    await chrome.action.setBadgeText({ text });
    await chrome.action.setBadgeBackgroundColor({ color: "#4A90D9" });
  } catch {
    // 角标更新失败不影响收藏结果本身。
  }
}

async function showCaptureResult(
  config,
  tab,
  memo,
  deduplicated,
  selectedText = "",
) {
  lastCapturedMemo = {
    id: memo.id,
    version: memo.version,
    deduplicated,
  };
  const pageTitle = (tab.title || tab.url).trim();
  const noticeMessage = selectedText
    ? `选中文本：${selectedText.slice(0, 70)}`
    : pageTitle;
  const notice = {
    type: "basic",
    iconUrl: chrome.runtime.getURL("icons/icon128.png"),
    title: deduplicated
      ? "网页已在资料库中"
      : selectedText
        ? "已摘录到 MemoIsle"
        : "已收藏到 MemoIsle",
    message: noticeMessage.slice(0, 80),
    buttons: deduplicated
      ? [{ title: "查看资料" }]
      : [{ title: "撤销" }, { title: "查看资料" }],
  };
  try {
    // 通知失败或系统禁用时静默降级，角标仍会提示收藏结果。
    await new Promise((resolve) => {
      chrome.notifications.create(CAPTURE_NOTIFICATION_ID, notice, resolve);
    });
  } catch {
    // 忽略通知异常，不影响收藏结果。
  }
  await setCaptureBadge(deduplicated ? "=" : "✓");
  setTimeout(() => void setCaptureBadge(""), 3_000);
}

async function undoLastCapture() {
  const target = lastCapturedMemo;
  if (!target || target.deduplicated) {
    return;
  }
  try {
    const config = await readConfig();
    const headers = await requestHeaders();
    const response = await fetch(`${config.apiBaseUrl}/memos/${target.id}`, {
      method: "PATCH",
      headers,
      body: JSON.stringify({
        expected_version: target.version,
        status: "trashed",
      }),
    });
    if (response.ok) {
      await setCaptureBadge("↩");
      setTimeout(() => void setCaptureBadge(""), 3_000);
    }
  } catch {
    // 撤销失败时保留通知，用户仍可在资料库中手动处理。
  }
  chrome.notifications.clear(CAPTURE_NOTIFICATION_ID);
  lastCapturedMemo = null;
}

function openMemoIsleFromNotification() {
  chrome.notifications.clear(CAPTURE_NOTIFICATION_ID);
  void readConfig().then((config) => openWebCapture(config, null, null));
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (
    !sender?.tab ||
    message?.type !== "set-access-token" ||
    (message.accessToken !== null && typeof message.accessToken !== "string")
  ) {
    return false;
  }

  const accessToken = message.accessToken?.trim() || null;
  void (async () => {
    const config = await readConfig();
    if (!isTrustedWebSender(sender.tab?.url, config.webBaseUrl)) {
      sendResponse({ ok: false });
      return;
    }
    // 先记住页面报出的地址，后面的同步和跳转都按最新地址走。
    const resolvedConfig = (await rememberWebContext(sender, message, config))
      ? await readConfig()
      : config;
    if (accessToken) {
      const previous = await chrome.storage.local.get(ACCESS_TOKEN_STORAGE_KEY);
      await chrome.storage.local.set({
        [ACCESS_TOKEN_STORAGE_KEY]: accessToken,
      });
      // 同一扩展可能切换账号，旧账号的书签版本不能用于新账号增量提交。
      if (previous[ACCESS_TOKEN_STORAGE_KEY] !== accessToken) {
        await clearBookmarkSyncState();
      }
      // 登录成功后立即刷新快照，避免 Web 读取到旧的未授权结果。
      // 网页轮询只刷新标签页，避免重复上传书签或等待大型书签树导致握手超时。
      if (previous[ACCESS_TOKEN_STORAGE_KEY] !== accessToken) {
        void syncBookmarks(resolvedConfig);
      }
      await syncOpenTabs(resolvedConfig);
    } else {
      await chrome.storage.local.remove(ACCESS_TOKEN_STORAGE_KEY);
    }
    sendResponse({ ok: true });
  })().catch(() => {
    sendResponse({ ok: false });
  });
  return true;
});

// 页面加载时内容脚本会先登记自己所在的 Web 地址，未登录也能让扩展知道该跳转到哪。
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!sender?.tab || message?.type !== "set-web-context") {
    return false;
  }
  void (async () => {
    const config = await readConfig();
    sendResponse({ ok: await rememberWebContext(sender, message, config) });
  })().catch(() => {
    sendResponse({ ok: false });
  });
  return true;
});

chrome.runtime.onInstalled.addListener(() => {
  // 先清空再注册，避免扩展更新时出现 duplicate id 错误。
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({
      id: PAGE_MENU_ID,
      title: "收藏到 MemoIsle",
      contexts: ["page", "selection"],
    });
    chrome.contextMenus.create({
      id: IMAGE_MENU_ID,
      title: "收藏图片到 MemoIsle",
      contexts: ["image"],
    });
  });
  void readConfig().then((config) => Promise.all([
    syncOpenTabs(config),
    syncBookmarks(config),
  ]));
});

chrome.runtime.onStartup.addListener(() => {
  void readConfig().then((config) => Promise.all([
    syncOpenTabs(config),
    syncBookmarks(config),
  ]));
});

chrome.bookmarks.onCreated.addListener((id, node) => {
  void queueBookmarkUpsert(id, node, 1);
});
chrome.bookmarks.onChanged.addListener((id) => {
  void queueBookmarkUpsert(id);
});
chrome.bookmarks.onMoved.addListener(scheduleBookmarkSync);
chrome.bookmarks.onRemoved.addListener((id) => {
  void queueBookmarkRemoval(id);
});
chrome.bookmarks.onImportEnded.addListener(() => {
  scheduleFullBookmarkSync();
});

chrome.tabs.onCreated.addListener(() => {
  scheduleOpenTabSync();
});

chrome.tabs.onUpdated.addListener((_tabId, changeInfo) => {
  if (
    changeInfo.url !== undefined ||
    changeInfo.title !== undefined ||
    changeInfo.favIconUrl !== undefined ||
    changeInfo.status === "complete"
  ) {
    scheduleOpenTabSync();
  }
});

chrome.tabs.onActivated.addListener(() => {
  scheduleOpenTabSync();
});

chrome.tabs.onRemoved.addListener(() => {
  scheduleOpenTabSync();
});

chrome.action.onClicked.addListener((tab) => {
  void captureTab(tab);
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId === PAGE_MENU_ID) {
    void captureTab(tab, info.selectionText ?? "");
    return;
  }
  if (info.menuItemId === IMAGE_MENU_ID) {
    void captureImage(info, tab);
  }
});

chrome.commands.onCommand.addListener((command) => {
  if (command !== "capture-current-page") {
    return;
  }
  chrome.tabs.query({ active: true, currentWindow: true }, ([tab]) => {
    void captureTab(tab);
  });
});

chrome.notifications.onButtonClicked.addListener((notificationId, buttonIndex) => {
  if (notificationId !== CAPTURE_NOTIFICATION_ID || !lastCapturedMemo) {
    return;
  }
  if (buttonIndex === 0 && !lastCapturedMemo.deduplicated) {
    // 按钮 0 是“撤销”，去重收藏没有该按钮。
    void undoLastCapture();
    return;
  }
  openMemoIsleFromNotification();
});

chrome.notifications.onClicked.addListener((notificationId) => {
  if (notificationId === CAPTURE_NOTIFICATION_ID) {
    openMemoIsleFromNotification();
  }
});
