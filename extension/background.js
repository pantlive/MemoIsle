const DEFAULT_CONFIG = {
  apiBaseUrl: "http://127.0.0.1:8000/api/v1",
  webBaseUrl: "http://localhost:5173/",
};
const MAX_SYNCED_BOOKMARKS = 5000;
const MAX_SELECTED_TEXT_LENGTH = 10000;
const ACCESS_TOKEN_STORAGE_KEY = "memoisle_access_token";
const WEB_CONTEXT_STORAGE_KEY = "memoisle_web_context";
const BOOKMARK_SYNC_STATE_STORAGE_KEY = "memoisle_bookmark_sync_state";
const HISTORY_SYNC_STATE_STORAGE_KEY = "memoisle_history_sync_state";
const DEVICE_ID_STORAGE_KEY = "memoisle_device_id";
// 回填从最早的历史开始，一直补到当前；用断点游标分批推进，
// 关掉浏览器后下次从断点继续，不会每次从头扫。
const HISTORY_BACKFILL_BATCH_MS = 7 * 24 * 60 * 60 * 1000;
// 单轮回填最多推进这么多条，剩下的交给下一轮，避免卡住后台。
const HISTORY_BACKFILL_MAX_TOTAL = 20_000;
// 单轮最多扫这么多个时间窗（每个 7 天）。30 个窗口约覆盖 7 个月，
// 更早的历史分多轮推进，每轮工作量有限，不会让后台任务长时间占着不放。
const HISTORY_BACKFILL_MAX_WINDOWS = 30;
// 回填没补完时注册的闹钟。不能用 setTimeout 续跑：MV3 后台空闲约 30 秒
// 就会被回收，计时器随之消失；chrome.alarms 能把已休眠的后台重新唤醒。
const HISTORY_BACKFILL_ALARM = "memoisle-history-backfill";
const HISTORY_BACKFILL_ALARM_MINUTES = 5;
// 键盘鼠标这么久没动就算闲置；锁屏立刻算。闲置时才做大批量回填。
const HISTORY_IDLE_DETECTION_SECONDS = 5 * 60;
// 单次唤醒最多连续跑这么久，留出余量，避开后台单次事件约 5 分钟的上限。
const HISTORY_IDLE_RUN_BUDGET_MS = 4 * 60 * 1000;
// 增量同步时最多读取多少条历史（只覆盖上次同步之后的时间段）。
const HISTORY_INCREMENTAL_MAX_TOTAL = 5_000;
// chrome.history.search 一次最多返回这么多条。回填时按时间窗分段拉取，
// 每窗取 1000 条，直到把整个区间走完，不会因为单次上限漏掉记录。
const HISTORY_QUERY_PAGE_SIZE = 1000;
// 单个时间窗的跨度。命中上限就二分窗口继续拆，避免一条一条往前挪。
const HISTORY_BACKFILL_WINDOW_MS = 7 * 24 * 60 * 60 * 1000;
// 窗口拆到这个粒度（1 小时）还超上限，说明该时段访问极多：
// 只保留最近的 1000 条并继续往前，避免无限细分卡死。
const HISTORY_BACKFILL_MIN_WINDOW_MS = 60 * 60 * 1000;
// 单次请求条数与清单里的上限保持一致（服务端最多 500 条）。
const HISTORY_BATCH_SIZE = 200;
const HISTORY_SYNC_DEBOUNCE_MS = 1_500;
const HISTORY_SYNC_FETCH_TIMEOUT_MS = 8_000;
const HISTORY_MAX_URL_LENGTH = 2048;
const HISTORY_MAX_TITLE_LENGTH = 300;
// 两次同步之间留一分钟重叠，避免浏览器写入历史与扩展读取之间存在时差。
const HISTORY_SYNC_OVERLAP_MS = 60_000;
const HISTORY_RETRY_DELAY_MS = 60_000;
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
let historySyncTimer = null;
let historySyncChain = Promise.resolve();
// 待上报的访问，按网址去重；同一网址只保留最近一次访问。
const pendingHistoryVisits = new Map();
const HISTORY_PENDING_LIMIT = 2_000;
const TAB_SYNC_DEBOUNCE_MS = 400;
const TAB_SYNC_FETCH_TIMEOUT_MS = 2_500;
const CAPTURE_FETCH_TIMEOUT_MS = 12_000;
let bookmarkSyncChain = Promise.resolve();
let bookmarkChangeSequence = 0;
const pendingBookmarkChanges = new Map();

// 两个待发送队列落盘保存。MV3 后台空闲约 30 秒就会被回收，只放内存里的话，
// 还没发出去的书签改动和浏览记录会随之丢失。
const PENDING_QUEUE_STORAGE_KEY = "memoisle_pending_queues";
// 已从内存队列取出、正在发送的批次。落盘时一并写入：
// 发送途中后台被回收，这批也能在下次恢复后重发（服务端按网址/ID 去重，重发安全）。
const inFlightHistoryVisits = new Map();
const inFlightBookmarkChanges = new Map();
let pendingQueuePersistTimer = null;
// 恢复完成前不能落盘，否则会用空队列覆盖掉上次保存的内容。
let pendingQueuesRestored = false;
const pendingQueuesReady = restorePendingQueues();

function persistPendingQueues() {
  if (!pendingQueuesRestored) {
    return;
  }
  if (pendingQueuePersistTimer !== null) {
    return;
  }
  // 同一轮事件里的多次改动合并成一次写入。
  pendingQueuePersistTimer = setTimeout(() => {
    pendingQueuePersistTimer = null;
    void writePendingQueues();
  }, 50);
}

async function writePendingQueues() {
  // 内存里的新改动优先：同一网址/书签在两边都有时，用待发队列里那份。
  const history = new Map(inFlightHistoryVisits);
  for (const [key, visit] of pendingHistoryVisits) {
    history.set(key, visit);
  }
  const bookmarks = new Map(inFlightBookmarkChanges);
  for (const [key, change] of pendingBookmarkChanges) {
    bookmarks.set(key, change);
  }
  if (history.size === 0 && bookmarks.size === 0) {
    await chrome.storage.local.remove(PENDING_QUEUE_STORAGE_KEY);
    return;
  }
  await chrome.storage.local.set({
    [PENDING_QUEUE_STORAGE_KEY]: {
      history: [...history.values()].slice(0, HISTORY_PENDING_LIMIT),
      bookmarks: [...bookmarks.values()],
      bookmarkSequence: bookmarkChangeSequence,
    },
  });
}

async function restorePendingQueues() {
  try {
    const stored = await chrome.storage.local.get(PENDING_QUEUE_STORAGE_KEY);
    const saved = stored?.[PENDING_QUEUE_STORAGE_KEY];
    if (saved && typeof saved === "object") {
      for (const visit of Array.isArray(saved.history) ? saved.history : []) {
        // 恢复期间已经有新访问进来时，以内存里更新的为准。
        if (visit?.page_url && !pendingHistoryVisits.has(visit.page_url)) {
          pendingHistoryVisits.set(visit.page_url, visit);
        }
      }
      const savedSequence = Number(saved.bookmarkSequence) || 0;
      // 序号只能前进：恢复出来的旧改动不能比新改动的序号更大。
      bookmarkChangeSequence = Math.max(bookmarkChangeSequence, savedSequence);
      for (const change of Array.isArray(saved.bookmarks) ? saved.bookmarks : []) {
        if (change?.client_item_id && !pendingBookmarkChanges.has(change.client_item_id)) {
          pendingBookmarkChanges.set(change.client_item_id, change);
        }
      }
    }
  } catch {
    // 存储读不出来时按空队列继续，最坏情况等同于改动前的行为。
  } finally {
    pendingQueuesRestored = true;
  }
  if (pendingHistoryVisits.size > 0 || pendingBookmarkChanges.size > 0) {
    // 恢复期间可能已有新改动，需要把合并结果写回去。
    persistPendingQueues();
  }
  return pendingHistoryVisits.size + pendingBookmarkChanges.size;
}
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
  persistPendingQueues();
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
  persistPendingQueues();
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
    inFlightBookmarkChanges.set(change.client_item_id, change);
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
    // 服务端确认收到后才把这批从落盘队列里去掉。
  } catch (error) {
    // 网络故障时恢复未被更新事件覆盖的变更，稍后用完整快照重新校准。
    for (const change of batch) {
      const current = pendingBookmarkChanges.get(change.client_item_id);
      if (!current || current.generation < change.generation) {
        pendingBookmarkChanges.set(change.client_item_id, change);
      }
    }
    throw error;
  } finally {
    // 成功、失败（已放回待发队列）或改走完整同步，这批都不再算在途。
    for (const change of batch) {
      if (inFlightBookmarkChanges.get(change.client_item_id) === change) {
        inFlightBookmarkChanges.delete(change.client_item_id);
      }
    }
    persistPendingQueues();
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

function queryHistory(options) {
  return new Promise((resolve) => {
    if (typeof chrome.history?.search !== "function") {
      // 用户未授予 history 权限时静默跳过，不影响收藏和书签同步。
      resolve([]);
      return;
    }
    chrome.history.search(options, (results) => {
      if (chrome.runtime.lastError) {
        resolve([]);
        return;
      }
      resolve(Array.isArray(results) ? results : []);
    });
  });
}

function normalizeHistoryVisit(item) {
  const pageUrl = String(item?.url || "").trim();
  if (!pageUrl || pageUrl.length > HISTORY_MAX_URL_LENGTH) {
    return null;
  }
  if (!isSupportedPage(pageUrl)) {
    return null;
  }
  const visitedAt = Number(item?.lastVisitTime);
  const visitCount = Number(item?.visitCount);
  return {
    page_url: pageUrl,
    page_title: String(item?.title || "").trim().slice(0, HISTORY_MAX_TITLE_LENGTH),
    favicon_url: null,
    visited_at: Number.isFinite(visitedAt) && visitedAt > 0
      ? new Date(visitedAt).toISOString()
      : null,
    // 浏览器给出该网址的累计访问次数，服务端取较大值，重复上报不会虚增。
    visit_count:
      Number.isInteger(visitCount) && visitCount > 0 ? visitCount : 1,
  };
}

function readDeviceName() {
  // 用平台信息给设备一个可读名字，方便在 Web 端区分来源。
  // 注意：扩展的 service worker 与测试环境都不保证有 navigator，必须判类型。
  const platform = String(
    (typeof navigator !== "undefined" &&
      (navigator.userAgentData?.platform || navigator.platform)) ||
      "",
  );
  const normalized = platform.toLowerCase();
  if (normalized.includes("mac")) {
    return "Mac";
  }
  if (normalized.includes("win")) {
    return "Windows";
  }
  if (normalized.includes("linux")) {
    return "Linux";
  }
  if (normalized.includes("android")) {
    return "Android";
  }
  if (normalized.includes("ios") || normalized.includes("iphone")) {
    return "iOS";
  }
  return platform ? platform.slice(0, 40) : "浏览器";
}

const DEVICE_INSTALL_ID_STORAGE_KEY = "memoisle_device_install_id";

// 用 SHA-256 生成稳定标识。
async function sha256Hex(value) {
  const data = new TextEncoder().encode(value);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return [...new Uint8Array(digest)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

// 机器指纹：由「重装扩展后仍然不变」的属性算出。
//
// 注意这**不是**唯一标识：两台同型号、同系统、同时区、同语言的电脑会算出
// 完全相同的值。它只用来回答「这次安装像不像之前那台机器」，
// 最终是合并还是并列由用户在界面上确认。
// 浏览器拿不到 MAC 地址（没有 API，且系统会随机化 MAC），不要试图找替代。
async function readHardwareKey() {
  // 只收集「service worker 里真的读得到」的信号。
  // 网页端常见的屏幕尺寸、字体列表、matchMedia 在 MV3 的 worker 里都是
  // undefined（没有 DOM），不要写进去，否则只会得到常量。
  const parts = [];
  try {
    const info = await chrome.runtime.getPlatformInfo();
    parts.push(info.os, info.arch, info.nacl_arch ?? "");
  } catch {
    parts.push("unknown");
  }
  // 区域格式：时区、日历、数字系统、周起始日。
  // 这些反映系统区域设置，出厂相同的机器也可能因为用户改过设置而不同。
  try {
    const resolved = Intl.DateTimeFormat().resolvedOptions();
    parts.push(
      String(resolved.timeZone ?? ""),
      String(resolved.calendar ?? ""),
      String(resolved.numberingSystem ?? ""),
    );
  } catch {
    parts.push("", "", "");
  }
  try {
    // 周起始日能反映地区习惯（周日起 / 周一起）。
    const locale = new Intl.Locale(
      Intl.DateTimeFormat().resolvedOptions().locale,
    );
    parts.push(String(locale.weekInfo?.firstDay ?? ""));
  } catch {
    parts.push("");
  }
  // 语言列表的顺序也是信号：用户自己调整过优先级就会不同。
  try {
    parts.push((navigator?.languages ?? []).join(","));
  } catch {
    parts.push("");
  }
  try {
    parts.push(String(navigator?.hardwareConcurrency ?? ""));
  } catch {
    parts.push("");
  }
  try {
    parts.push(String(navigator?.deviceMemory ?? ""));
  } catch {
    parts.push("");
  }
  return sha256Hex(parts.join("|"));
}

async function readInstallId() {
  const stored = await chrome.storage.local.get(DEVICE_INSTALL_ID_STORAGE_KEY);
  const existing = stored?.[DEVICE_INSTALL_ID_STORAGE_KEY];
  if (typeof existing === "string" && existing.trim()) {
    return existing.trim();
  }
  // 每次安装（含重装）都会生成新的，用来区分「重装」和「另一台电脑」。
  const generated = String(crypto.randomUUID()).replaceAll("-", "");
  await chrome.storage.local.set({
    [DEVICE_INSTALL_ID_STORAGE_KEY]: generated,
  });
  return generated;
}

async function readDeviceId() {
  const stored = await chrome.storage.local.get(DEVICE_ID_STORAGE_KEY);
  const existing = stored?.[DEVICE_ID_STORAGE_KEY];
  if (typeof existing === "string" && existing.trim()) {
    return existing.trim();
  }
  // 设备 ID 必须是随机的，不能拿指纹当主键：
  // 两台同款电脑指纹相同，用指纹当 ID 会让它们一开始就撞成同一台。
  // 指纹只在「ID 丢了」的时候作为找回线索。
  const generated = String(crypto.randomUUID()).replaceAll("-", "");
  await chrome.storage.local.set({ [DEVICE_ID_STORAGE_KEY]: generated });
  return generated;
}

async function rememberDeviceId(deviceId) {
  // 服务端分配了不同的设备 ID（指纹撞车）时，跟着它走，
  // 否则每次同步都会被判定成「新设备」。
  if (typeof deviceId !== "string" || !deviceId.trim()) {
    return;
  }
  const current = await chrome.storage.local.get(DEVICE_ID_STORAGE_KEY);
  if (current?.[DEVICE_ID_STORAGE_KEY] === deviceId) {
    return;
  }
  await chrome.storage.local.set({ [DEVICE_ID_STORAGE_KEY]: deviceId });
}

async function readHistorySyncState() {
  const stored = await chrome.storage.local.get(HISTORY_SYNC_STATE_STORAGE_KEY);
  const state = stored?.[HISTORY_SYNC_STATE_STORAGE_KEY];
  if (!state || typeof state !== "object") {
    return null;
  }
  const since = Number(state.since);
  // backfillCursor 是「还没补到的更早时间点」；为空表示最早的历史也补完了。
  const backfillCursor = Number(state.backfillCursor);
  return {
    since: Number.isFinite(since) && since >= 0 ? since : null,
    backfillCursor:
      Number.isFinite(backfillCursor) && backfillCursor > 0
        ? backfillCursor
        : null,
  };
}

async function saveHistorySyncState({ since, backfillCursor }) {
  await chrome.storage.local.set({
    [HISTORY_SYNC_STATE_STORAGE_KEY]: {
      ...(Number.isFinite(since) ? { since } : {}),
      ...(Number.isFinite(backfillCursor) && backfillCursor > 0
        ? { backfillCursor }
        : {}),
    },
  });
}

async function clearHistorySyncState() {
  await chrome.storage.local.remove(HISTORY_SYNC_STATE_STORAGE_KEY);
}

function enqueueHistorySync(operation) {
  historySyncChain = historySyncChain.then(operation, operation);
  return historySyncChain;
}

async function postHistoryVisits(config, visits, replaceAll = false) {
  // 带上设备标识：同一账号的多台电脑各存各的，互不覆盖。
  const [deviceId, hardwareKey, installId, headers] = await Promise.all([
    readDeviceId(),
    readHardwareKey().catch(() => ""),
    readInstallId().catch(() => ""),
    requestHeaders(),
  ]);
  const response = await fetchWithTimeout(
    `${config.apiBaseUrl}/browser-history/sync`,
    {
      method: "POST",
      headers,
      body: JSON.stringify({
        extension_id: chrome.runtime.id,
        device_id: deviceId,
        device_name: readDeviceName(),
        hardware_key: hardwareKey,
        install_id: installId,
        visits,
        replace_all: replaceAll,
      }),
    },
    HISTORY_SYNC_FETCH_TIMEOUT_MS,
  );
  if (!response.ok) {
    throw new Error(`浏览历史同步失败（${response.status}）`);
  }
  // 服务端可能因为指纹撞车派了新的设备 ID，记住它，
  // 否则下一次同步又会被当成新设备。
  // 注意不能依赖 response.clone()：测试替身与部分环境只实现了 json()。
  try {
    const body = await response.json();
    await rememberDeviceId(body?.device_id);
  } catch {
    // 响应体解析失败不影响同步本身。
  }
  return response;
}

async function flushHistoryVisits(config) {
  if (pendingHistoryVisits.size === 0) {
    return;
  }
  const batch = [...pendingHistoryVisits.values()].slice(0, HISTORY_BATCH_SIZE);
  for (const visit of batch) {
    inFlightHistoryVisits.set(visit.page_url, visit);
    pendingHistoryVisits.delete(visit.page_url);
  }
  try {
    await postHistoryVisits(config, batch);
    // 服务端确认收到后才从落盘队列去掉；中途被回收时这批还在盘上，下次重发。
    for (const visit of batch) {
      if (inFlightHistoryVisits.get(visit.page_url) === visit) {
        inFlightHistoryVisits.delete(visit.page_url);
      }
    }
    persistPendingQueues();
    // 以本批最新访问时间作为游标，下次只读这之后的历史。
    const latest = batch.reduce((max, visit) => {
      const visitedAt = new Date(visit.visited_at || 0).getTime();
      return Number.isFinite(visitedAt) && visitedAt > max ? visitedAt : max;
    }, 0);
    if (latest > 0) {
      const state = await readHistorySyncState();
      if (!state?.since || latest > state.since) {
        // 只推进增量游标，回填断点由 backfillHistory 负责。
        await saveHistorySyncState({
          since: latest - HISTORY_SYNC_OVERLAP_MS,
          backfillCursor: state?.backfillCursor,
        });
      }
    }
    if (pendingHistoryVisits.size > 0) {
      // 单次最多 500 条，剩余的分批继续发送。
      await flushHistoryVisits(config);
    }
  } catch (error) {
    // 失败时把本批放回队列，等下一次触发再试。
    for (const visit of batch) {
      inFlightHistoryVisits.delete(visit.page_url);
      if (!pendingHistoryVisits.has(visit.page_url)) {
        pendingHistoryVisits.set(visit.page_url, visit);
      }
    }
    persistPendingQueues();
    throw error;
  }
}

async function syncHistory(config = null) {
  const resolvedConfig = config || await readConfig();
  const headers = await requestHeaders();
  if (!headers.Authorization) {
    // 还没登录时不读浏览器历史，避免把本地记录留在内存里。
    return;
  }
  const state = await readHistorySyncState();
  if (state === null) {
    await runBackfillExclusive(resolvedConfig);
    return;
  }
  // 还没补完更早的历史时，每轮先继续往前推进一段，再处理最近的新访问。
  if (state.backfillCursor) {
    await runBackfillExclusive(resolvedConfig);
  }
  const since = state.since ?? Date.now() - HISTORY_SYNC_OVERLAP_MS;
  // chrome.history.search 按访问时间倒序返回，超出上限时保留最近的。
  // 截断必须发生在入队之前，否则等于没限制。
  const visits = (await readRecentHistory(since)).slice(
    0,
    HISTORY_INCREMENTAL_MAX_TOTAL,
  );
  for (const visit of visits) {
    pendingHistoryVisits.set(visit.page_url, visit);
  }
  if (pendingHistoryVisits.size > HISTORY_PENDING_LIMIT) {
    // 长时间没用 MemoIsle 后历史会积压，只保留最近的部分。
    const ordered = [...pendingHistoryVisits.values()]
      .sort((left, right) => String(right.visited_at).localeCompare(String(left.visited_at)));
    pendingHistoryVisits.clear();
    for (const visit of ordered.slice(0, HISTORY_PENDING_LIMIT)) {
      pendingHistoryVisits.set(visit.page_url, visit);
    }
  }
  persistPendingQueues();
  await enqueueHistorySync(() => flushHistoryVisits(resolvedConfig));
}

async function readRecentHistory(since, until = Date.now()) {
  const results = await queryHistory({
    text: "",
    startTime: Math.max(0, since),
    endTime: until,
    maxResults: HISTORY_QUERY_PAGE_SIZE,
  });
  return results.map(normalizeHistoryVisit).filter(Boolean);
}

// 从一个时间窗里收集访问记录。命中单次上限就把窗口二分继续拆，
// 拆到最小粒度仍超限时保留最近的 1000 条，然后继续往前一个窗口。
async function collectHistoryWindow(start, end, collected, budget) {
  if (collected.size >= budget || start >= end) {
    return;
  }
  const visits = await readRecentHistory(start, end);
  const hitLimit = visits.length >= HISTORY_QUERY_PAGE_SIZE;
  if (!hitLimit || end - start <= HISTORY_BACKFILL_MIN_WINDOW_MS) {
    // 窗口已取完，或已经拆到最小粒度（此时收下能拿到的部分，避免死循环）。
    // 逐条判断预算，保证不会整窗超出上限。
    for (const visit of visits) {
      if (collected.size >= budget) {
        return;
      }
      collected.set(visit.page_url, visit);
    }
    return;
  }
  // 二分：先补后半段（更近），再补前半段（更早）。
  // 预算耗尽时优先保住最近访问的记录，旧记录才被舍弃。
  const middle = start + Math.floor((end - start) / 2);
  await collectHistoryWindow(middle, end, collected, budget);
  await collectHistoryWindow(start, middle, collected, budget);
}

// 找出浏览器里最早一条历史的访问时间，避免从「1970 年」开始空扫。
//
// 判据统一是「[0, mid] 里有没有记录」：有就把上界收到 mid，没有就抬高下界。
// 从 1970 到现在约 1000 小时量级，二分 20 次左右即可收敛到 1 小时精度，
// 查询次数只和跨度有关，和历史条目多少无关。
async function findHistoryStartTime(now = Date.now()) {
  // 只问「这段区间里有没有记录」。注意不能用 maxResults 采样后取最小值：
  // chrome.history.search 按访问时间**倒序**返回，截断后拿到的是最新的几条，
  // 最小值并不是区间里最早的那条，会把回填范围缩到只剩最近一小段。
  const hasRecordIn = async (from, to) => {
    const results = await queryHistory({
      text: "",
      startTime: from,
      endTime: to,
      maxResults: 1,
    });
    return results.length > 0;
  };

  if (!(await hasRecordIn(0, now))) {
    // 浏览器里一条历史都没有。
    return null;
  }
  // 二分：问「[low, middle] 里有没有记录」，有就把上界收到 middle，
  // 没有就抬高下界，最终收敛到最早那条记录所在的 1 小时区间。
  //
  // 起点从「30 年前」开始而不是 1970：绝大多数人的历史都在这个范围内，
  // 跨度小三分之一，查询次数也更少；真有更老的记录时下界会自然退到 0。
  let low = Math.max(0, now - 30 * 365 * 24 * 60 * 60 * 1000);
  let high = now;
  if (!(await hasRecordIn(0, low))) {
    // 30 年内没有记录，把下界退回 1970 再二分。
    low = 0;
  }
  while (high - low > HISTORY_BACKFILL_MIN_WINDOW_MS) {
    const middle = low + Math.floor((high - low) / 2);
    if (await hasRecordIn(low, middle)) {
      high = middle;
    } else {
      low = middle;
    }
  }
  // 收敛到的是「有记录的那个 1 小时窗口的上沿」，最早记录可能落在窗口内部。
  // 回填循环用 `end > earliest` 作边界，若直接返回 high，这个窗口里
  // 早于 high 的记录会被整段跳过。往下再让出一个最小窗口，确保覆盖到它。
  return Math.max(0, high - HISTORY_BACKFILL_MIN_WINDOW_MS);
}

async function backfillHistory(config) {
  // 备份浏览器的「全部」历史：先定位最早记录，再从当前时刻往回逐轮扫描，
  // 每轮记录断点，下次接着往更早推进，直到覆盖到最早那条为止。
  const now = Date.now();
  const previous = await readHistorySyncState();
  // 断点：上一轮已经补到的最早时间点。没有就表示还没开始补。
  const upperBound = previous?.backfillCursor ?? now;
  const earliest = await findHistoryStartTime(now);
  const collected = new Map();
  // 本轮扫到的最早时间点；null 表示已经一路扫到最早的历史。
  let scannedTo = upperBound;
  let windowsScanned = 0;

  for (let end = upperBound; end > earliest; end -= HISTORY_BACKFILL_WINDOW_MS) {
    if (collected.size >= HISTORY_BACKFILL_MAX_TOTAL) {
      break;
    }
    const start = Math.max(earliest, end - HISTORY_BACKFILL_WINDOW_MS);
    await collectHistoryWindow(
      start,
      end,
      collected,
      HISTORY_BACKFILL_MAX_TOTAL,
    );
    scannedTo = start;
    windowsScanned += 1;
    if (windowsScanned >= HISTORY_BACKFILL_MAX_WINDOWS) {
      // 本轮工作量到顶，剩下的更早历史留给下一轮（断点已记录）。
      break;
    }
  }
  // 预算用完说明后面还有更早的记录，留下断点下次继续；
  // 否则已经扫到最早，清空断点表示全量备份完成。
  const backfillCursor = scannedTo > earliest ? scannedTo : null;

  if (collected.size === 0) {
    // 这一轮没扫到任何记录（可能历史很稀疏），基线仍然推进。
    await saveHistorySyncState({
      since: previous?.since ?? now - HISTORY_SYNC_OVERLAP_MS,
      backfillCursor,
    });
    await updateBackfillAlarm(Boolean(backfillCursor));
    return;
  }

  await enqueueHistorySync(async () => {
    for (const visit of collected.values()) {
      pendingHistoryVisits.set(visit.page_url, visit);
    }
    persistPendingQueues();
    await flushHistoryVisits(config);
    await saveHistorySyncState({
      // 增量游标只在第一次回填时初始化，之后由 flushHistoryVisits 推进。
      since:
        previous?.since ??
        Math.max(0, upperBound - HISTORY_SYNC_OVERLAP_MS),
      backfillCursor,
    });
  });
  // 还有更早的历史没补完就挂上闹钟，补完就撤掉。
  await updateBackfillAlarm(Boolean(backfillCursor));
}

// 同一时刻只跑一轮回填：浏览触发的小轮次和闲置时的大批量可能同时到来，
// 并发会把同一段历史扫两遍。
let backfillInFlight = null;

function runBackfillExclusive(config) {
  if (!backfillInFlight) {
    backfillInFlight = backfillHistory(config).finally(() => {
      backfillInFlight = null;
    });
  }
  return backfillInFlight;
}

async function updateBackfillAlarm(pending) {
  if (!chrome.alarms) {
    return;
  }
  if (!pending) {
    await chrome.alarms.clear(HISTORY_BACKFILL_ALARM);
    return;
  }
  const existing = await chrome.alarms.get(HISTORY_BACKFILL_ALARM);
  if (!existing) {
    chrome.alarms.create(HISTORY_BACKFILL_ALARM, {
      periodInMinutes: HISTORY_BACKFILL_ALARM_MINUTES,
    });
  }
}

async function readIdleState() {
  if (!chrome.idle?.queryState) {
    // 没有闲置检测能力时不做大批量回填，只保留浏览时的小轮次。
    return "active";
  }
  return chrome.idle.queryState(HISTORY_IDLE_DETECTION_SECONDS);
}

// 电脑闲置或锁屏时连续推进回填，直到补完、用户回来或本次时间用完。
async function runIdleBackfill() {
  if (backfillInFlight) {
    return;
  }
  if ((await readIdleState()) === "active") {
    return;
  }
  const headers = await requestHeaders();
  if (!headers.Authorization) {
    return;
  }
  const config = await readConfig();
  const deadline = Date.now() + HISTORY_IDLE_RUN_BUDGET_MS;
  while (Date.now() < deadline) {
    const state = await readHistorySyncState();
    if (state !== null && !state.backfillCursor) {
      await updateBackfillAlarm(false);
      return;
    }
    await runBackfillExclusive(config);
    if ((await readIdleState()) === "active") {
      // 用户回来用电脑了，剩下的留给下一次闲置。
      return;
    }
  }
}

function scheduleHistorySync(delayMs = HISTORY_SYNC_DEBOUNCE_MS) {
  if (historySyncTimer !== null) {
    return;
  }
  historySyncTimer = setTimeout(() => {
    historySyncTimer = null;
    void syncHistory().catch(() => {
      // 连接失败时退避重试；重复触发不会叠加多个定时器。
      scheduleHistorySync(HISTORY_RETRY_DELAY_MS);
    });
  }, delayMs);
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
        // 换账号后历史游标也要重来，否则新账号会漏掉这之前的浏览记录。
        await clearHistorySyncState();
      }
      // 登录成功后立即刷新快照，避免 Web 读取到旧的未授权结果。
      // 网页轮询只刷新标签页，避免重复上传书签或等待大型书签树导致握手超时。
      if (previous[ACCESS_TOKEN_STORAGE_KEY] !== accessToken) {
        void syncBookmarks(resolvedConfig);
        void syncHistory(resolvedConfig).catch(() => {});
      }
      await syncOpenTabs(resolvedConfig);
    } else {
      await chrome.storage.local.remove(ACCESS_TOKEN_STORAGE_KEY);
      // 退出登录后清空游标，下次登录重新补 30 天基线。
      await clearHistorySyncState();
      pendingHistoryVisits.clear();
      inFlightHistoryVisits.clear();
      // 退出登录后不能留着上一个账号的待发记录，立刻落盘而不是等去抖。
      await writePendingQueues();
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
    syncHistory(config).catch(() => {}),
  ]));
});

// 后台被唤醒时，把上次没发完的改动接着发出去。
void pendingQueuesReady.then(async (restored) => {
  if (restored === 0) {
    return;
  }
  const config = await readConfig();
  if (pendingBookmarkChanges.size > 0) {
    void enqueueBookmarkSync(() => flushBookmarkChanges()).catch(() => {
      scheduleBookmarkRetry();
    });
  }
  if (pendingHistoryVisits.size > 0) {
    const headers = await requestHeaders();
    if (headers.Authorization) {
      void enqueueHistorySync(() => flushHistoryVisits(config)).catch(() => {});
    }
  }
}).catch(() => {});

if (chrome.idle?.setDetectionInterval) {
  chrome.idle.setDetectionInterval(HISTORY_IDLE_DETECTION_SECONDS);
}

// 闲置/锁屏的那一刻立刻开始，不必等下一次闹钟。
chrome.idle?.onStateChanged?.addListener((state) => {
  if (state === "idle" || state === "locked") {
    void runIdleBackfill().catch(() => {});
  }
});

// 闹钟兜底：一直处于闲置时不会再有状态变化事件，靠它每隔几分钟续跑一段。
chrome.alarms?.onAlarm?.addListener((alarm) => {
  if (alarm.name === HISTORY_BACKFILL_ALARM) {
    void runIdleBackfill().catch(() => {});
  }
});

chrome.runtime.onStartup.addListener(() => {
  void readConfig().then((config) => Promise.all([
    syncOpenTabs(config),
    syncBookmarks(config),
    syncHistory(config).catch(() => {}),
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
  if (changeInfo.url !== undefined) {
    // 只在地址真正变化时读一次历史，标题变化不产生新的访问记录。
    scheduleHistorySync();
  }
});

chrome.tabs.onActivated.addListener(() => {
  scheduleOpenTabSync();
});

chrome.tabs.onRemoved.addListener(() => {
  scheduleOpenTabSync();
});

// 用户在浏览器里清空历史时，把服务端的同账号记录一起清掉。
if (chrome.history?.onVisitRemoved) {
  chrome.history.onVisitRemoved.addListener((removed) => {
    if (!removed?.allHistory) {
      // 只删个别网址时改动很小，交给下一次增量同步即可。
      return;
    }
    void enqueueHistorySync(async () => {
      const config = await readConfig();
      const state = await readHistorySyncState();
      pendingHistoryVisits.clear();
      inFlightHistoryVisits.clear();
      await writePendingQueues();
      await postHistoryVisits(config, [], true);
      // 清空后增量游标归零，但保留回填断点，避免已备份的旧历史重扫。
      await saveHistorySyncState({
        since: Date.now() - HISTORY_SYNC_OVERLAP_MS,
        backfillCursor: state?.backfillCursor,
      });
    }).catch(() => {});
  });
}

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
