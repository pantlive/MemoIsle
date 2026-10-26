import assert from "node:assert/strict";
import { randomUUID, webcrypto } from "node:crypto";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";
import { storeBackground } from "../scripts/build-store-package.mjs";

const backgroundSource = await readFile(
  new URL("../background.js", import.meta.url),
  "utf8",
);
const contentSource = await readFile(
  new URL("../content.js", import.meta.url),
  "utf8",
);
const manifest = JSON.parse(
  await readFile(new URL("../manifest.json", import.meta.url), "utf8"),
);

function jsonValue(value) {
  return JSON.parse(JSON.stringify(value));
}

// 默认图片响应使用的 PNG 魔数，便于断言「按原始字节上传」。
const DEFAULT_IMAGE_BYTES = new Uint8Array([
  0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a,
  0x00, 0x00, 0x00, 0x0d, 0x49, 0x48, 0x44, 0x52,
]);

function createHarness({
  activeTab = {
    url: "https://developer.mozilla.org/zh-CN/docs/Web/API",
    title: "Web API",
    favIconUrl: "https://developer.mozilla.org/favicon.ico",
  },
  openTabs,
  bookmarkTree,
  historyItems,
  historySearch,
  fetchImpl,
  backgroundScript = backgroundSource,
  storedConfig = {},
  storedWebContext = null,
  storedAccessToken = "test-access-token",
  storedHistoryState = null,
  idleState = "active",
  // 传入上一个后台实例的本地存储，模拟后台被回收后重新唤醒。
  sharedLocalStore = null,
  notificationResult = "memoisle-capture-result",
  selectedText = "",
  createImageBitmap,
  OffscreenCanvas,
} = {}) {
  const listeners = {};
  const messageListeners = [];
  const alarms = new Map();
  // 用对象包一层，测试中途可以切换闲置状态。
  const idle = { state: idleState };
  const localStore = sharedLocalStore ?? {};
  if (storedWebContext) {
    localStore.memoisle_web_context = jsonValue(storedWebContext);
  }
  if (storedAccessToken) {
    localStore.memoisle_access_token = storedAccessToken;
  }
  if (storedHistoryState) {
    localStore.memoisle_history_sync_state = jsonValue(storedHistoryState);
  }
  const resolvedOpenTabs = openTabs ?? [activeTab];
  const calls = {
    contextMenus: [],
    contextMenuRemovals: 0,
    fetches: [],
    queries: [],
    bookmarkReads: 0,
    historyQueries: [],
    alarmsCreated: [],
    alarmsCleared: [],
    tabsCreated: [],
    notificationsCreated: [],
    notificationsCleared: [],
    badges: [],
    scriptExecutions: [],
  };
  const resolvedFetch = fetchImpl ?? (async (url, options = {}) => {
    calls.fetches.push({ url, options });
    const requestUrl = String(url);
    const method = String(options.method || "GET").toUpperCase();
    if (method === "GET") {
      // 右键收藏图片时会 GET 图片地址，返回带 PNG 魔数的字节。
      return {
        ok: true,
        status: 200,
        headers: {
          get(name) {
            return String(name).toLowerCase() === "content-type" ? "image/png" : null;
          },
        },
        async arrayBuffer() {
          return DEFAULT_IMAGE_BYTES.slice().buffer;
        },
      };
    }
    if (/\/memos\/[^/]+\/image(?:\?|$)/.test(requestUrl)) {
      // 图片上传成功会返回版本 +1 的 Memo。
      return {
        ok: true,
        status: 200,
        async json() {
          return { id: "memo-created", version: 2 };
        },
      };
    }
    const body = JSON.parse(options.body ?? "{}");
    if (requestUrl.endsWith("/memos")) {
      // 默认响应回显请求里的 client_id，表示本次为新建收藏。
      return {
        ok: true,
        status: 201,
        async json() {
          return {
            id: "memo-created",
            version: 1,
            client_id: body.client_id,
            title: body.source_title ?? "",
          };
        },
      };
    }
    if (requestUrl.endsWith("/browser-history/sync")) {
      // 服务端会回显最终使用的设备 ID，扩展据此固定后续同步的归属。
      return {
        ok: true,
        status: 200,
        async json() {
          return {
            synced_count: Array.isArray(body.visits) ? body.visits.length : 0,
            total_count: 1,
            device_id: body.device_id,
            possible_same_device_id: null,
          };
        },
      };
    }
    return { ok: true, status: 200, async json() { return {}; } };
  });
  const chrome = {
    runtime: {
      id: "abcdefghijklmnopabcdefghijklmnop",
      lastError: null,
      getURL(path) {
        return `chrome-extension://abcdefghijklmnopabcdefghijklmnop/${path}`;
      },
      async getPlatformInfo() {
        return { os: "mac", arch: "arm64", nacl_arch: "arm64" };
      },
      onInstalled: {
        addListener(callback) {
          listeners.installed = callback;
        },
      },
      onStartup: {
        addListener(callback) {
          listeners.startup = callback;
        },
      },
      onMessage: {
        addListener(callback) {
          messageListeners.push(callback);
          // 浏览器会把消息发给所有监听者，任意一个返回 true 就保持通道。
          listeners.message = (message, sender, sendResponse) => {
            let keepAlive = false;
            for (const listener of messageListeners) {
              if (listener(message, sender, sendResponse) === true) {
                keepAlive = true;
              }
            }
            return keepAlive;
          };
        },
      },
    },
    scripting: {
      async executeScript(details) {
        calls.scriptExecutions.push(jsonValue({ target: details.target }));
        return [{ result: selectedText }];
      },
    },
    bookmarks: {
      get(id, callback) {
        const found = [];
        const walk = (nodes, parentId) => {
          for (const node of nodes || []) {
            if (String(node.id) === String(id)) {
              found.push({ ...node, parentId: node.parentId ?? parentId });
            }
            walk(node.children, node.id);
          }
        };
        walk(bookmarkTree ?? [], undefined);
        callback(found);
      },
      getTree(callback) {
        calls.bookmarkReads += 1;
        callback(bookmarkTree ?? [{ id: "0", title: "", children: [] }]);
      },
      onCreated: {
        addListener(callback) {
          listeners.bookmarkCreated = callback;
        },
      },
      onChanged: {
        addListener(callback) {
          listeners.bookmarkChanged = callback;
        },
      },
      onMoved: {
        addListener(callback) {
          listeners.bookmarkMoved = callback;
        },
      },
      onRemoved: {
        addListener(callback) {
          listeners.bookmarkRemoved = callback;
        },
      },
      onImportEnded: {
        addListener(callback) {
          listeners.bookmarkImportEnded = callback;
        },
      },
    },
    history: {
      search(query, callback) {
        calls.historyQueries.push(jsonValue(query));
        const items = historyItems ?? [];
        if (historySearch) {
          // 需要模拟「按窗口返回、单次有上限」时由用例提供实现。
          callback(historySearch(query, items));
          return;
        }
        // 默认按 chrome.history.search 的语义过滤：时间窗 + 条数上限。
        const start = Number(query.startTime) || 0;
        const end = Number(query.endTime) || Date.now();
        const limit = Number(query.maxResults) || 100;
        callback(
          items
            .filter(
              (item) =>
                item.lastVisitTime >= start && item.lastVisitTime <= end,
            )
            .sort((left, right) => right.lastVisitTime - left.lastVisitTime)
            .slice(0, limit),
        );
      },
      onVisitRemoved: {
        addListener(callback) {
          listeners.historyRemoved = callback;
        },
      },
    },
    storage: {
      sync: {
        async get(keys) {
          if (Array.isArray(keys)) {
            const result = {};
            for (const key of keys) {
              if (Object.hasOwn(storedConfig, key)) {
                result[key] = storedConfig[key];
              }
            }
            return result;
          }
          return { ...keys, ...storedConfig };
        },
      },
      local: {
        async get(key) {
          const keys = Array.isArray(key) ? key : [key];
          const result = {};
          for (const item of keys) {
            if (Object.hasOwn(localStore, item)) {
              result[item] = jsonValue(localStore[item]);
            }
          }
          return result;
        },
        async set(values) {
          Object.assign(localStore, jsonValue(values));
        },
        async remove(key) {
          delete localStore[key];
        },
      },
    },
    contextMenus: {
      create(options) {
        calls.contextMenus.push(jsonValue(options));
      },
      removeAll(callback) {
        calls.contextMenuRemovals += 1;
        callback();
      },
      onClicked: {
        addListener(callback) {
          listeners.contextMenu = callback;
        },
      },
    },
    action: {
      onClicked: {
        addListener(callback) {
          listeners.action = callback;
        },
      },
      async setBadgeText(options) {
        calls.badges.push({ text: options.text });
      },
      async setBadgeBackgroundColor() {
        calls.badges.push({ backgroundColor: true });
      },
    },
    alarms: {
      async get(name) {
        return alarms.get(name);
      },
      create(name, info) {
        alarms.set(name, { name, ...info });
        calls.alarmsCreated.push({ name, ...info });
      },
      async clear(name) {
        calls.alarmsCleared.push(name);
        return alarms.delete(name);
      },
      onAlarm: {
        addListener(callback) {
          listeners.alarm = callback;
        },
      },
    },
    idle: {
      setDetectionInterval(seconds) {
        calls.idleInterval = seconds;
      },
      async queryState() {
        return idle.state;
      },
      onStateChanged: {
        addListener(callback) {
          listeners.idleChanged = callback;
        },
      },
    },
    notifications: {
      create(id, options, callback) {
        calls.notificationsCreated.push({ id, options: jsonValue(options) });
        callback(notificationResult);
      },
      clear(id) {
        calls.notificationsCleared.push(id);
      },
      onButtonClicked: {
        addListener(callback) {
          listeners.notificationButton = callback;
        },
      },
      onClicked: {
        addListener(callback) {
          listeners.notificationClicked = callback;
        },
      },
    },
    commands: {
      onCommand: {
        addListener(callback) {
          listeners.command = callback;
        },
      },
    },
    tabs: {
      query(query, callback) {
        calls.queries.push(jsonValue(query));
        callback(query.active ? [activeTab] : resolvedOpenTabs);
      },
      async create(options) {
        calls.tabsCreated.push(jsonValue(options));
      },
      onCreated: {
        addListener(callback) {
          listeners.tabCreated = callback;
        },
      },
      onUpdated: {
        addListener(callback) {
          listeners.tabUpdated = callback;
        },
      },
      onActivated: {
        addListener(callback) {
          listeners.tabActivated = callback;
        },
      },
      onRemoved: {
        addListener(callback) {
          listeners.tabRemoved = callback;
        },
      },
    },
  };

  vm.runInContext(
    backgroundScript,
    vm.createContext({
      URL,
      AbortController,
      chrome,
      console,
      crypto: { randomUUID, subtle: webcrypto.subtle },
      // vm 上下文没有全局 TextEncoder，指纹计算依赖它。
      TextEncoder,
      fetch: resolvedFetch,
      clearTimeout,
      // 后台的重试计时器不能拖住测试进程：服务端一直失败时扩展会持续重试，
      // 真实浏览器里后台会被回收，测试进程里没有这个机制。unref 不影响按时触发。
      setTimeout: (callback, delay, ...rest) => {
        const timer = setTimeout(callback, delay, ...rest);
        timer.unref?.();
        return timer;
      },
      Blob,
      // 默认不提供压缩 API，便于覆盖「无法压缩」的降级路径。
      createImageBitmap,
      OffscreenCanvas,
    }),
    { filename: "background.js" },
  );

  return { calls, listeners, localStore, alarms, idle };
}

async function waitFor(
  predicate,
  message = "等待扩展异步动作超时",
  timeoutMs = 5_000,
) {
  // 书签同步带有 400ms 防抖，必须按真实时间轮询，不能只让出 setImmediate。
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (predicate()) {
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
  assert.fail(message);
}

test("安装时注册最小化的网页与图片右键菜单", () => {
  const harness = createHarness();

  harness.listeners.installed();

  // 先清空再注册，保证扩展更新时不会出现 duplicate id。
  assert.equal(harness.calls.contextMenuRemovals, 1);
  assert.deepEqual(harness.calls.contextMenus, [
    {
      id: "memoisle-capture-page",
      title: "收藏到 MemoIsle",
      contexts: ["page", "selection"],
    },
    {
      id: "memoisle-capture-image",
      title: "收藏图片到 MemoIsle",
      contexts: ["image"],
    },
  ]);
});

test("扩展清单声明图片收藏所需的任意站点权限", () => {
  assert.equal(manifest.version, "0.5.1");
  assert.equal(manifest.host_permissions.includes("<all_urls>"), true);
  assert.equal(manifest.host_permissions.includes("http://127.0.0.1:8000/*"), true);
  assert.equal(manifest.host_permissions.includes("http://localhost:8000/*"), true);
  assert.match(manifest.description, /图片/);
});

test("扩展清单允许读取当前浏览器打开的标签页", () => {
  assert.equal(manifest.permissions.includes("tabs"), true);
});

test("扩展清单允许仅在用户触发时读取当前页选中文本", () => {
  assert.equal(manifest.permissions.includes("activeTab"), true);
  assert.equal(manifest.permissions.includes("scripting"), true);
});

test("扩展清单明确申请读取当前浏览器书签", () => {
  assert.equal(manifest.permissions.includes("bookmarks"), true);
});

test("扩展清单申请通知权限并声明图标资源", () => {
  assert.equal(manifest.permissions.includes("notifications"), true);
  assert.deepEqual(manifest.icons, {
    16: "icons/icon16.png",
    32: "icons/icon32.png",
    48: "icons/icon48.png",
    128: "icons/icon128.png",
  });
  assert.deepEqual(manifest.action.default_icon, manifest.icons);
});

test("扩展清单只在本地 MemoIsle 页面接收登录凭证", () => {
  // 端口范围要与 background.js 的 LOCAL_WEB_PORTS 保持一致。
  const expectedMatches = [];
  for (const host of ["localhost", "127.0.0.1"]) {
    for (const port of [5173, 5174, 5175, 5176, 5177, 5178]) {
      expectedMatches.push(`http://${host}:${port}/*`);
    }
  }
  assert.deepEqual(manifest.content_scripts, [
    {
      matches: expectedMatches,
      js: ["content.js"],
      run_at: "document_start",
    },
  ]);
});

test("正式包从网站接收登录凭证并把同步请求发送到 VPS", async () => {
  const origin = "https://memo.17115859.xyz:9443";
  const harness = createHarness({
    backgroundScript: storeBackground(
      backgroundSource, new URL(origin), new URL(`${origin}/api/v1`),
    ),
    storedAccessToken: null,
    storedWebContext: {
      webBaseUrl: "http://localhost:5174",
      apiBaseUrl: "http://localhost:5174/api/v1",
    },
  });
  const response = await new Promise((resolve) => {
    harness.listeners.message({
      type: "set-access-token",
      accessToken: "vps-test-access-token",
      webOrigin: origin,
      apiBaseUrl: `${origin}/api/v1`,
    }, { tab: { url: `${origin}/` } }, resolve);
  });
  assert.deepEqual(jsonValue(response), { ok: true });
  assert.equal(harness.localStore.memoisle_access_token, "vps-test-access-token");
  assert.equal(harness.localStore.memoisle_web_context.webBaseUrl, origin);
  assert.ok(harness.calls.fetches.some((call) => call.url.endsWith("/browser-tabs/sync")));
  assert.ok(harness.calls.fetches.every((call) => call.url.startsWith(`${origin}/api/v1/`)));
});

test("正式包不接受其他网站或其他端口发来的登录凭证", async () => {
  const origin = "https://memo.17115859.xyz:9443";
  for (const sender of [
    "https://memo.17115859.xyz",
    "https://memo.17115859.xyz:8443",
    "http://memo.17115859.xyz:9443",
    "https://untrusted.example",
    "http://localhost:5173",
  ]) {
    const harness = createHarness({
      backgroundScript: storeBackground(
        backgroundSource, new URL(origin), new URL(`${origin}/api/v1`),
      ),
      storedAccessToken: null,
    });
    const response = await new Promise((resolve) => {
      harness.listeners.message({
        type: "set-access-token",
        accessToken: "untrusted-test-token",
        webOrigin: sender,
        apiBaseUrl: `${sender}/api/v1`,
      }, { tab: { url: `${sender}/` } }, resolve);
    });
    assert.deepEqual(jsonValue(response), { ok: false }, sender);
    assert.equal(harness.localStore.memoisle_access_token, undefined);
    assert.equal(harness.calls.fetches.length, 0);
  }
});

test("本地 MemoIsle 页面会把登录凭证和地址转发给扩展后台", () => {
  let messageHandler;
  const forwardedMessages = [];
  const window = {
    addEventListener(type, callback) {
      if (type === "message") {
        messageHandler = callback;
      }
    },
    location: { origin: "http://localhost:5174" },
    postMessage() {},
  };
  const chrome = {
    runtime: {
      sendMessage(message) {
        forwardedMessages.push(jsonValue(message));
        return Promise.resolve();
      },
    },
  };

  vm.runInContext(
    contentSource,
    vm.createContext({ chrome, window }),
    { filename: "content.js" },
  );

  // 页面加载即登记本页地址，此时还不知道 API 地址。
  assert.deepEqual(forwardedMessages.at(-1), {
    type: "set-web-context",
    webOrigin: "http://localhost:5174",
    apiBaseUrl: null,
  });

  messageHandler({
    source: window,
    origin: "http://localhost:5174",
    data: {
      source: "memoisle-web",
      type: "set-access-token",
      accessToken: "test-access-token",
      webOrigin: "http://localhost:5174",
      apiBaseUrl: "http://localhost:5174/api/v1",
    },
  });

  // 登录凭证与本页 API 地址通过同一条后台消息登记。
  assert.equal(forwardedMessages.length, 2);
  assert.deepEqual(forwardedMessages.at(-1), {
    type: "set-access-token",
    accessToken: "test-access-token",
    webOrigin: "http://localhost:5174",
    apiBaseUrl: "http://localhost:5174/api/v1",
  });
});

test("内容脚本会把页面回答的 API 地址转给扩展后台", () => {
  let messageHandler;
  const forwardedMessages = [];
  const window = {
    addEventListener(type, callback) {
      if (type === "message") {
        messageHandler = callback;
      }
    },
    location: { origin: "http://127.0.0.1:5176" },
    postMessage() {},
  };
  const chrome = {
    runtime: {
      sendMessage(message) {
        forwardedMessages.push(jsonValue(message));
        return Promise.resolve();
      },
    },
  };

  vm.runInContext(
    contentSource,
    vm.createContext({ chrome, window }),
    { filename: "content.js" },
  );
  messageHandler({
    source: window,
    origin: "http://127.0.0.1:5176",
    data: {
      source: "memoisle-web",
      type: "web-context",
      webOrigin: "http://127.0.0.1:5176",
      apiBaseUrl: "http://127.0.0.1:5176/api/v1",
    },
  });

  assert.deepEqual(forwardedMessages.at(-1), {
    type: "set-web-context",
    webOrigin: "http://127.0.0.1:5176",
    apiBaseUrl: "http://127.0.0.1:5176/api/v1",
  });
});

test("内容脚本忽略其他源窗口发来的登录凭证", () => {
  let messageHandler;
  const forwardedMessages = [];
  const window = {
    addEventListener(type, callback) {
      if (type === "message") {
        messageHandler = callback;
      }
    },
    location: { origin: "http://localhost:5174" },
    postMessage() {},
  };
  const otherWindow = {};
  const chrome = {
    runtime: {
      sendMessage(message) {
        forwardedMessages.push(jsonValue(message));
        return Promise.resolve();
      },
    },
  };

  vm.runInContext(
    contentSource,
    vm.createContext({ chrome, window }),
    { filename: "content.js" },
  );
  const reportedAtLoad = forwardedMessages.length;
  messageHandler({
    source: otherWindow,
    origin: "http://localhost:5174",
    data: {
      source: "memoisle-web",
      type: "set-access-token",
      accessToken: "stolen-token",
    },
  });
  messageHandler({
    source: window,
    origin: "http://127.0.0.1:9999",
    data: {
      source: "memoisle-web",
      type: "set-access-token",
      accessToken: "stolen-token",
    },
  });

  // 加载时登记的地址之外，不应再有任何凭证或地址被转发。
  assert.equal(forwardedMessages.length, reportedAtLoad);
});

test("安装后直接读取书签树并同步标题、网址和文件夹", async () => {
  const harness = createHarness({
    bookmarkTree: [
      {
        id: "0",
        title: "",
        children: [
          {
            id: "1",
            title: "书签栏",
            children: [
              {
                id: "10",
                title: "学习资料",
                children: [
                  {
                    id: "42",
                    title: "PyTorch 文档",
                    url: "https://pytorch.org/docs/stable/",
                  },
                ],
              },
            ],
          },
        ],
      },
    ],
  });

  harness.listeners.installed();
  await waitFor(() => harness.calls.fetches.some((item) =>
    item.url.endsWith("/browser-bookmarks/sync"),
  ));

  const request = harness.calls.fetches.find((item) =>
    item.url.endsWith("/browser-bookmarks/sync"),
  );
  assert.ok(request);
  assert.equal(harness.calls.bookmarkReads, 1);
  assert.deepEqual(JSON.parse(request.options.body), {
    extension_id: "abcdefghijklmnopabcdefghijklmnop",
    items: [
      {
        client_item_id: "chrome:42",
        title: "PyTorch 文档",
        url: "https://pytorch.org/docs/stable/",
        folder_path: "书签栏 / 学习资料",
      },
    ],
    total_count: 1,
  });
});

test("相同登录凭证重连时同步标签页且不重复上传书签", async () => {
  const harness = createHarness();
  const response = await new Promise((resolve) => {
    const keepAlive = harness.listeners.message(
      {
        type: "set-access-token",
        accessToken: "test-access-token",
      },
      { tab: { url: "http://localhost:5174/" } },
      resolve,
    );
    assert.equal(keepAlive, true);
  });

  assert.deepEqual(jsonValue(response), { ok: true });
  const request = harness.calls.fetches.find((item) =>
    item.url.endsWith("/browser-tabs/sync"),
  );
  assert.ok(request);
  assert.equal(request.options.headers.Authorization, "Bearer test-access-token");
  assert.equal(harness.calls.fetches.some((item) =>
    item.url.endsWith("/browser-bookmarks/sync"),
  ), false);
});

test("浏览器完成批量书签导入后刷新完整快照", async () => {
  const harness = createHarness();

  harness.listeners.bookmarkImportEnded();
  await waitFor(() => harness.calls.fetches.some((item) =>
    item.url.endsWith("/browser-bookmarks/sync"),
  ));

  assert.equal(harness.calls.bookmarkReads, 1);
});

test("点击扩展图标会把当前网页直接收藏进资料库并提示", async () => {
  const harness = createHarness({
    openTabs: [
      {
        id: 7,
        windowId: 1,
        url: "https://developer.mozilla.org/zh-CN/docs/Web/API",
        title: "Web API",
        favIconUrl: "https://developer.mozilla.org/favicon.ico",
      },
      {
        id: 8,
        windowId: 1,
        url: "https://example.com/course",
        title: "公开课程",
        favIconUrl: "https://example.com/favicon.ico",
      },
      {
        id: 9,
        windowId: 1,
        url: "chrome://extensions",
        title: "扩展",
      },
    ],
  });

  harness.listeners.action({
    id: 7,
    windowId: 1,
    url: "https://example.com/learning?id=42",
    title: "学习资料",
    favIconUrl: "https://example.com/favicon.ico",
  });
  await waitFor(() => harness.calls.fetches.length >= 2);
  await waitFor(() => harness.calls.notificationsCreated.length === 1);

  // 直达收藏成功，不应再打开 Web 表单页。
  assert.equal(harness.calls.tabsCreated.length, 0);

  const syncRequest = harness.calls.fetches.find((item) =>
    item.url.endsWith("/browser-tabs/sync"),
  );
  assert.ok(syncRequest);
  assert.equal(syncRequest.options.method, "POST");
  const syncBody = JSON.parse(syncRequest.options.body);
  assert.deepEqual(syncBody.tabs, [
    {
      tab_id: 7,
      window_id: 1,
      page_url: "https://developer.mozilla.org/zh-CN/docs/Web/API",
      page_title: "Web API",
      favicon_url: "https://developer.mozilla.org/favicon.ico",
    },
    {
      tab_id: 8,
      window_id: 1,
      page_url: "https://example.com/course",
      page_title: "公开课程",
      favicon_url: "https://example.com/favicon.ico",
    },
  ]);

  const request = harness.calls.fetches.find((item) =>
    item.url.endsWith("/memos"),
  );
  assert.ok(request);
  assert.equal(request.url, "http://127.0.0.1:8000/api/v1/memos");
  assert.equal(request.options.method, "POST");
  assert.deepEqual(jsonValue(request.options.headers), {
    "Content-Type": "application/json",
    Authorization: "Bearer test-access-token",
  });
  const body = JSON.parse(request.options.body);
  assert.match(
    body.client_id,
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i,
  );
  assert.equal(body.type, "resource");
  assert.equal(body.body, "https://example.com/learning?id=42");
  assert.equal(body.source_url, "https://example.com/learning?id=42");
  assert.equal(body.source_title, "学习资料");
  assert.deepEqual(body.tags, []);

  const notice = harness.calls.notificationsCreated[0].options;
  assert.equal(notice.type, "basic");
  assert.equal(
    notice.iconUrl,
    "chrome-extension://abcdefghijklmnopabcdefghijklmnop/icons/icon128.png",
  );
  assert.equal(notice.title, "已收藏到 MemoIsle");
  assert.equal(notice.message, "学习资料");
  assert.deepEqual(notice.buttons, [{ title: "撤销" }, { title: "查看资料" }]);
  assert.ok(harness.calls.badges.some((badge) => badge.text === "✓"));
});

test("点击扩展图标会把用户选中的文本保存为网页正文", async () => {
  const harness = createHarness({
    selectedText: "  这是用户明确选中的重点内容。  ",
  });

  harness.listeners.action({
    id: 7,
    windowId: 1,
    url: "https://example.com/article",
    title: "文章标题",
  });
  await waitFor(() => harness.calls.notificationsCreated.length === 1);

  const request = harness.calls.fetches.find((item) =>
    item.url.endsWith("/memos"),
  );
  assert.ok(request);
  const body = JSON.parse(request.options.body);
  assert.equal(body.body, "这是用户明确选中的重点内容。");
  assert.equal(body.source_url, "https://example.com/article");
  assert.equal(
    harness.calls.scriptExecutions[0].target.tabId,
    7,
  );
  assert.equal(
    harness.calls.notificationsCreated[0].options.title,
    "已摘录到 MemoIsle",
  );
});

test("右键菜单携带选中文本时不再额外读取页面内容", async () => {
  const harness = createHarness();

  harness.listeners.contextMenu(
    {
      menuItemId: "memoisle-capture-page",
      selectionText: "右键选中的段落",
    },
    {
      id: 8,
      windowId: 1,
      url: "https://example.com/guide",
      title: "指南",
    },
  );
  await waitFor(() => harness.calls.notificationsCreated.length === 1);

  const request = harness.calls.fetches.find((item) =>
    item.url.endsWith("/memos"),
  );
  assert.ok(request);
  assert.equal(JSON.parse(request.options.body).body, "右键选中的段落");
  assert.equal(harness.calls.scriptExecutions.length, 0);
});

test("标签页同步迟迟不返回时右键收藏仍能完成", async () => {
  let finishSync;
  const syncResponse = new Promise((resolve) => {
    finishSync = resolve;
  });
  const harness = createHarness({
    fetchImpl: async (url, options) => {
      if (String(url).endsWith("/browser-tabs/sync")) {
        return syncResponse;
      }
      const body = JSON.parse(options.body);
      return {
        ok: true,
        status: 201,
        async json() {
          return { id: "memo-created", version: 1, client_id: body.client_id };
        },
      };
    },
  });

  try {
    harness.listeners.contextMenu(
      { menuItemId: "memoisle-capture-page" },
      { id: 7, url: "https://github.com/getpaseo/paseo", title: "Paseo" },
    );
    // 保持同步请求未完成，确认收藏不再依赖全浏览器快照的响应。
    await waitFor(
      () => harness.calls.notificationsCreated.length === 1,
      "收藏被标签页同步阻塞",
      300,
    );
    assert.equal(harness.calls.tabsCreated.length, 0);
    assert.equal(harness.calls.notificationsCreated[0].options.title, "已收藏到 MemoIsle");
  } finally {
    finishSync({ ok: true, status: 200 });
  }
});

test("重复右键收藏 Paseo 网页会处理后端 409 并保留原资料", async () => {
  let savedMemo = null;
  let createAttempts = 0;
  const harness = createHarness({
    fetchImpl: async (url, options) => {
      if (!String(url).endsWith("/memos")) {
        return { ok: true, status: 200 };
      }
      createAttempts += 1;
      if (savedMemo) {
        return {
          ok: false,
          status: 409,
          async json() {
            return { detail: { code: "duplicate_resource", current: savedMemo } };
          },
        };
      }
      const body = JSON.parse(options.body);
      assert.equal(body.source_url, "https://github.com/getpaseo/paseo");
      savedMemo = { id: "memo-paseo", version: 1, client_id: body.client_id };
      return { ok: true, status: 201, async json() { return savedMemo; } };
    },
  });
  const tab = { id: 7, url: "https://github.com/getpaseo/paseo", title: "Paseo" };
  const info = { menuItemId: "memoisle-capture-page" };

  harness.listeners.contextMenu(info, tab);
  await waitFor(() => harness.calls.notificationsCreated.length === 1);
  harness.listeners.contextMenu(info, tab);
  await waitFor(() =>
    harness.calls.notificationsCreated.length === 2 || harness.calls.tabsCreated.length > 0,
  );

  assert.equal(harness.calls.tabsCreated.length, 0);
  assert.equal(createAttempts, 2);
  const notice = harness.calls.notificationsCreated[1].options;
  assert.equal(notice.title, "网页已在资料库中");
  assert.deepEqual(notice.buttons, [{ title: "查看资料" }]);
  assert.ok(harness.calls.badges.some((badge) => badge.text === "="));
  // 去重结果的第一个按钮只能查看，不能把原资料移入回收站。
  harness.listeners.notificationButton("memoisle-capture-result", 0);
  await waitFor(() => harness.calls.tabsCreated.length === 1);
  assert.equal(createAttempts, 2);
});

test("无有效原资料的 409 不能提示收藏成功", async (context) => {
  const details = [
    { code: "duplicate_resource" },
    { code: "duplicate_resource", current: {} },
    { code: "other_conflict", current: { id: "memo-existing", version: 1 } },
  ];
  for (const detail of details) {
    await context.test(JSON.stringify(detail), async () => {
      const harness = createHarness({
        fetchImpl: async () => ({
          ok: false,
          status: 409,
          async json() { return { detail }; },
        }),
      });
      harness.listeners.contextMenu(
        { menuItemId: "memoisle-capture-page" },
        { url: "https://github.com/getpaseo/paseo", title: "Paseo" },
      );
      await waitFor(() => harness.calls.tabsCreated.length === 1);
      assert.equal(harness.calls.notificationsCreated.length, 0);
      assert.equal(
        new URL(harness.calls.tabsCreated[0].url).searchParams.get("memoisle_capture_error"),
        "capture_failed",
      );
    });
  }
});

test("快捷键与右键菜单只在明确触发时直接收藏当前页", async () => {
  const shortcutHarness = createHarness();

  shortcutHarness.listeners.command("unrelated-command");
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(shortcutHarness.calls.queries.length, 0);
  assert.equal(shortcutHarness.calls.fetches.length, 0);

  shortcutHarness.listeners.command("capture-current-page");
  await waitFor(() =>
    shortcutHarness.calls.fetches.some((item) => item.url.endsWith("/memos")),
  );
  assert.deepEqual(shortcutHarness.calls.queries.slice(-2), [
    { active: true, currentWindow: true },
    {},
  ]);
  assert.equal(shortcutHarness.calls.fetches.length, 2);
  assert.equal(shortcutHarness.calls.tabsCreated.length, 0);

  const contextHarness = createHarness();
  contextHarness.listeners.contextMenu({ menuItemId: "unrelated" }, {});
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(contextHarness.calls.fetches.length, 0);

  contextHarness.listeners.contextMenu(
    { menuItemId: "memoisle-capture-page" },
    {
      url: "https://example.org/article",
      title: "Article",
    },
  );
  await waitFor(() =>
    contextHarness.calls.fetches.some((item) => item.url.endsWith("/memos")),
  );
  assert.equal(contextHarness.calls.fetches.length, 2);
  assert.equal(contextHarness.calls.tabsCreated.length, 0);
});

test("浏览器标签页变化会刷新当前打开网页快照", async () => {
  const harness = createHarness();

  harness.listeners.tabCreated();
  harness.listeners.tabUpdated(7, { status: "complete" }, {});
  harness.listeners.tabActivated({ tabId: 7, windowId: 1 });
  harness.listeners.tabRemoved(7, { windowId: 1, isWindowClosing: false });
  await waitFor(() => harness.calls.fetches.length === 1);

  assert.equal(
    harness.calls.fetches.every((request) =>
      request.url.endsWith("/browser-tabs/sync"),
    ),
    true,
  );

  await new Promise((resolve) => setTimeout(resolve, 450));
  harness.listeners.tabCreated();
  await waitFor(() => harness.calls.fetches.length === 2);
});

test("扩展清单申请读取浏览历史", () => {
  assert.equal(manifest.permissions.includes("history"), true);
});

test("首次同步会上传全部浏览历史并带设备标识", async () => {
  const harness = createHarness({
    historyItems: [
      {
        url: "https://example.com/guide",
        title: "指南",
        lastVisitTime: Date.parse("2026-10-20T08:00:00Z"),
        visitCount: 3,
      },
      {
        // 浏览器内部页与本地地址不应上报。
        url: "chrome://extensions",
        title: "扩展",
        lastVisitTime: Date.parse("2026-10-20T09:00:00Z"),
        visitCount: 1,
      },
      {
        url: "http://127.0.0.1/admin",
        title: "本地",
        lastVisitTime: Date.parse("2026-10-20T09:30:00Z"),
        visitCount: 1,
      },
    ],
  });

  harness.listeners.installed();
  await waitFor(() =>
    harness.calls.fetches.some((item) => item.url.endsWith("/browser-history/sync")),
  );

  const request = harness.calls.fetches.find((item) =>
    item.url.endsWith("/browser-history/sync"),
  );
  assert.ok(request);
  const body = JSON.parse(request.options.body);
  assert.equal(body.extension_id, "abcdefghijklmnopabcdefghijklmnop");
  // 同一账号多台电脑靠 device_id 区分。
  assert.match(body.device_id, /^[0-9a-f]{32}$/);
  assert.equal(typeof body.device_name, "string");
  assert.equal(body.visits.length, 1);
  assert.deepEqual(body.visits[0], {
    page_url: "https://example.com/guide",
    page_title: "指南",
    favicon_url: null,
    visited_at: "2026-10-20T08:00:00.000Z",
    visit_count: 3,
  });

  // 全量备份：会先二分定位最早记录，再按时间窗往回扫。
  assert.ok(harness.calls.historyQueries.length > 1);
  assert.equal(typeof harness.localStore.memoisle_history_sync_state.since, "number");
  // 历史只有一条（10-20），补完就没有更早的了，不应留下断点。
  assert.equal(
    harness.localStore.memoisle_history_sync_state.backfillCursor,
    undefined,
  );
  // 设备标识首次生成后固定下来，后续同步复用同一个。
  assert.match(harness.localStore.memoisle_device_id, /^[0-9a-f]{32}$/);
});

test("已有游标时只读取游标之后的浏览记录", async () => {
  const since = Date.parse("2026-10-20T10:00:00Z");
  const harness = createHarness({
    historyItems: [
      {
        url: "https://example.com/new",
        title: "新页面",
        lastVisitTime: since + 60_000,
        visitCount: 1,
      },
    ],
    storedHistoryState: { since },
  });

  harness.listeners.tabUpdated(7, { url: "https://example.com/new" }, {});
  await waitFor(() =>
    harness.calls.fetches.some((item) => item.url.endsWith("/browser-history/sync")),
  );

  // 增量读取沿用保存的游标，不重新回填 30 天。
  assert.equal(harness.calls.historyQueries.at(-1).startTime, since);
});

test("地址变化才触发历史同步，标题变化不会", async () => {
  const harness = createHarness();

  harness.listeners.tabUpdated(7, { title: "新标题" }, {});
  await new Promise((resolve) => setTimeout(resolve, 1_600));
  assert.equal(harness.calls.historyQueries.length, 0);
  assert.equal(
    harness.calls.fetches.some((item) => item.url.endsWith("/browser-history/sync")),
    false,
  );
});

test("还没有登录凭证时不读取浏览器历史", async () => {
  const harness = createHarness({
    storedAccessToken: null,
    historyItems: [
      {
        url: "https://example.com/guide",
        title: "指南",
        lastVisitTime: Date.now(),
        visitCount: 1,
      },
    ],
  });

  harness.listeners.tabUpdated(7, { url: "https://example.com/other" }, {});
  await new Promise((resolve) => setTimeout(resolve, 1_600));

  assert.equal(harness.calls.historyQueries.length, 0);
  assert.equal(
    harness.calls.fetches.some((item) => item.url.endsWith("/browser-history/sync")),
    false,
  );
});

test("登录后立即同步历史，退出登录清掉游标", async () => {
  // 初始未登录，登录动作才算「凭证变化」，才会补一次 30 天基线。
  const harness = createHarness({ historyItems: [], storedAccessToken: null });

  await new Promise((resolve) => {
    harness.listeners.message(
      { type: "set-access-token", accessToken: "test-access-token" },
      { tab: { url: "http://localhost:5174/" } },
      resolve,
    );
  });
  // 分段回填会连续查询多个时间窗，等游标写入后再断言。
  await waitFor(() => typeof harness.localStore.memoisle_history_sync_state?.since === "number");
  assert.ok(harness.calls.historyQueries.length >= 1);

  await new Promise((resolve) => {
    harness.listeners.message(
      { type: "set-access-token", accessToken: null },
      { tab: { url: "http://localhost:5174/" } },
      resolve,
    );
  });
  assert.equal(harness.localStore.memoisle_history_sync_state, undefined);
});

test("浏览器清空历史时同步清空服务端记录", async () => {
  const harness = createHarness();

  harness.listeners.historyRemoved({ allHistory: true, urls: [] });
  await waitFor(() =>
    harness.calls.fetches.some((item) => item.url.endsWith("/browser-history/sync")),
  );

  const request = harness.calls.fetches.find((item) =>
    item.url.endsWith("/browser-history/sync"),
  );
  const body = JSON.parse(request.options.body);
  assert.equal(body.replace_all, true);
  assert.deepEqual(body.visits, []);
});

test("只删除个别网址时不整库清空", async () => {
  const harness = createHarness();

  harness.listeners.historyRemoved({ allHistory: false, urls: ["https://example.com/"] });
  await new Promise((resolve) => setTimeout(resolve, 100));
  assert.equal(
    harness.calls.fetches.some((item) => item.url.endsWith("/browser-history/sync")),
    false,
  );
});

test("内部页、本地文件和内网地址不会提交空资料", async (context) => {
  const unsupportedUrls = [
    "chrome://extensions",
    "file:///C:/private.txt",
    "http://localhost/admin",
    "http://127.0.0.1/private",
    "http://192.168.1.10/internal",
    "ftp://example.com/file",
  ];

  for (const pageUrl of unsupportedUrls) {
    await context.test(pageUrl, async () => {
      const harness = createHarness();
      harness.listeners.action({ url: pageUrl, title: "不支持" });
      await waitFor(() => harness.calls.tabsCreated.length === 1);

      assert.equal(harness.calls.fetches.length, 0);
      const openedUrl = new URL(harness.calls.tabsCreated[0].url);
      assert.equal(
        openedUrl.searchParams.get("memoisle_capture_error"),
        "unsupported_page",
      );
    });
  }
});

test("后端拒绝、登录失效和连接失败会给 Web 明确错误", async (context) => {
  const cases = [
    { status: 422, errorCode: "unsupported_page" },
    { status: 401, errorCode: "not_authenticated" },
    { status: 500, errorCode: "capture_failed" },
    { status: null, errorCode: "connection_failed" },
  ];

  for (const currentCase of cases) {
    await context.test(currentCase.errorCode, async () => {
      const harness = createHarness({
        fetchImpl: async () => {
          if (currentCase.status === null) {
            throw new Error("connection refused");
          }
          return {
            ok: false,
            status: currentCase.status,
            async json() {
              return {};
            },
          };
        },
      });

      harness.listeners.action({
        url: "https://example.com/article",
        title: "Article",
      });
      await waitFor(() => harness.calls.tabsCreated.length === 1);

      const openedUrl = new URL(harness.calls.tabsCreated[0].url);
      assert.equal(
        openedUrl.searchParams.get("memoisle_capture_error"),
        currentCase.errorCode,
      );
      assert.equal(openedUrl.searchParams.has("memoisle_capture"), false);
    });
  }
});

test("扩展还没有登录凭证时会直接引导 Web 登录", async () => {
  const harness = createHarness({ storedAccessToken: null });

  harness.listeners.action({
    url: "https://example.com/article",
    title: "Article",
  });
  await waitFor(() => harness.calls.tabsCreated.length === 1);

  assert.equal(
    harness.calls.fetches.some((item) => item.url.endsWith("/memos")),
    false,
  );
  const openedUrl = new URL(harness.calls.tabsCreated[0].url);
  assert.equal(
    openedUrl.searchParams.get("memoisle_capture_error"),
    "not_authenticated",
  );
});

test("自定义 API 地址会用于一键收藏请求", async () => {
  const harness = createHarness({
    storedConfig: {
      apiBaseUrl: "https://api.memoisle.test/api/v1/",
      webBaseUrl: "https://memoisle.test/capture?from=extension",
    },
  });

  harness.listeners.action({
    url: "https://example.com/tool",
    title: "Tool",
  });
  await waitFor(() =>
    harness.calls.fetches.some((item) => item.url.endsWith("/memos")),
  );

  assert.equal(harness.calls.tabsCreated.length, 0);
  const captureRequest = harness.calls.fetches.find((item) =>
    item.url.endsWith("/memos"),
  );
  assert.equal(captureRequest.url, "https://api.memoisle.test/api/v1/memos");
});

test("页面登记的地址会替换内置默认端口", async () => {
  const harness = createHarness({
    storedWebContext: {
      webBaseUrl: "http://localhost:5174",
      apiBaseUrl: "http://localhost:5174/api/v1",
    },
  });

  harness.listeners.action({
    url: "https://example.com/tool",
    title: "Tool",
  });
  await waitFor(() =>
    harness.calls.fetches.some((item) => item.url.endsWith("/memos")),
  );

  const captureRequest = harness.calls.fetches.find((item) =>
    item.url.endsWith("/memos"),
  );
  // 默认是 127.0.0.1:8000，页面登记后应改为 Vite 代理地址。
  assert.equal(captureRequest.url, "http://localhost:5174/api/v1/memos");
});

test("连接失败时按页面登记的地址打开 Web 并带上尝试过的 API 地址", async () => {
  const harness = createHarness({
    storedWebContext: {
      webBaseUrl: "http://127.0.0.1:5175",
      apiBaseUrl: "http://127.0.0.1:5175/api/v1",
    },
    fetchImpl: async () => {
      throw new TypeError("Failed to fetch");
    },
  });

  harness.listeners.action({
    url: "https://example.com/tool",
    title: "Tool",
  });
  await waitFor(() => harness.calls.tabsCreated.length === 1);

  const openedUrl = new URL(harness.calls.tabsCreated[0].url);
  assert.equal(openedUrl.origin, "http://127.0.0.1:5175");
  assert.equal(
    openedUrl.searchParams.get("memoisle_capture_error"),
    "connection_failed",
  );
  assert.equal(
    openedUrl.searchParams.get("memoisle_capture_api"),
    "http://127.0.0.1:5175/api/v1",
  );
});

test("显式配置的地址优先于页面登记的地址", async () => {
  const harness = createHarness({
    storedConfig: {
      apiBaseUrl: "https://api.memoisle.test/api/v1",
      webBaseUrl: "https://memoisle.test/",
    },
    storedWebContext: {
      webBaseUrl: "http://localhost:5174",
      apiBaseUrl: "http://localhost:5174/api/v1",
    },
  });

  harness.listeners.action({
    url: "https://example.com/tool",
    title: "Tool",
  });
  await waitFor(() =>
    harness.calls.fetches.some((item) => item.url.endsWith("/memos")),
  );

  const captureRequest = harness.calls.fetches.find((item) =>
    item.url.endsWith("/memos"),
  );
  assert.equal(captureRequest.url, "https://api.memoisle.test/api/v1/memos");
});

test("页面登记的跨源 API 地址不会被采用", async () => {
  const harness = createHarness({
    storedWebContext: {
      webBaseUrl: "http://localhost:5174",
      apiBaseUrl: "https://api.evil.test/api/v1",
    },
  });

  harness.listeners.action({
    url: "https://example.com/tool",
    title: "Tool",
  });
  await waitFor(() =>
    harness.calls.fetches.some((item) => item.url.endsWith("/memos")),
  );

  const captureRequest = harness.calls.fetches.find((item) =>
    item.url.endsWith("/memos"),
  );
  // 本地开发地址只接受同源 API，跨源地址必须由用户显式配置。
  assert.equal(captureRequest.url, "http://127.0.0.1:8000/api/v1/memos");
});

test("显式配置过的 Web 源可以登记跨源 API 地址", async () => {
  const harness = createHarness({
    storedConfig: { webBaseUrl: "https://memoisle.test/" },
    storedWebContext: {
      webBaseUrl: "https://memoisle.test",
      apiBaseUrl: "https://api.memoisle.test/api/v1",
    },
  });

  harness.listeners.action({
    url: "https://example.com/tool",
    title: "Tool",
  });
  await waitFor(() =>
    harness.calls.fetches.some((item) => item.url.endsWith("/memos")),
  );

  const captureRequest = harness.calls.fetches.find((item) =>
    item.url.endsWith("/memos"),
  );
  assert.equal(captureRequest.url, "https://api.memoisle.test/api/v1/memos");
});

test("内容脚本登记的 Web 地址会立刻用于一键收藏", async () => {
  const harness = createHarness();

  const response = await new Promise((resolve) => {
    const keepAlive = harness.listeners.message(
      {
        type: "set-web-context",
        webOrigin: "http://localhost:5176",
        apiBaseUrl: "http://localhost:5176/api/v1",
      },
      { tab: { url: "http://localhost:5176/" } },
      resolve,
    );
    assert.equal(keepAlive, true);
  });
  assert.deepEqual(jsonValue(response), { ok: true });
  assert.deepEqual(jsonValue(harness.localStore.memoisle_web_context), {
    webBaseUrl: "http://localhost:5176",
    apiBaseUrl: "http://localhost:5176/api/v1",
    updatedAt: harness.localStore.memoisle_web_context.updatedAt,
  });

  harness.listeners.action({
    url: "https://example.com/tool",
    title: "Tool",
  });
  await waitFor(() =>
    harness.calls.fetches.some((item) => item.url.endsWith("/memos")),
  );

  const captureRequest = harness.calls.fetches.find((item) =>
    item.url.endsWith("/memos"),
  );
  assert.equal(captureRequest.url, "http://localhost:5176/api/v1/memos");
});

test("内容脚本加载和登录同时发生时收藏仍使用本页 API 地址", async () => {
  const harness = createHarness({
    storedWebContext: {
      webBaseUrl: "http://localhost:5173",
      apiBaseUrl: "http://localhost:5173/api/v1",
    },
  });
  let messageHandler;
  const pendingMessages = [];
  const window = {
    location: { origin: "http://localhost:5174" },
    addEventListener(_type, callback) { messageHandler = callback; },
    postMessage() {},
  };
  const chrome = {
    runtime: {
      sendMessage(message) {
        const response = new Promise((resolve) => {
          harness.listeners.message(message, { tab: { url: "http://localhost:5174/" } }, resolve);
        });
        pendingMessages.push(response);
        return response;
      },
    },
  };
  vm.runInContext(contentSource, vm.createContext({ chrome, window }));
  // 不等待页面加载时的来源登记，复现内容脚本与登录消息并发到达后台。
  messageHandler({
    source: window,
    origin: window.location.origin,
    data: {
      source: "memoisle-web",
      type: "set-access-token",
      accessToken: "test-access-token",
      webOrigin: window.location.origin,
      apiBaseUrl: "http://localhost:5174/api/v1",
    },
  });
  await Promise.all(pendingMessages);

  assert.equal(harness.localStore.memoisle_web_context.apiBaseUrl, "http://localhost:5174/api/v1");
  harness.listeners.contextMenu(
    { menuItemId: "memoisle-capture-page" },
    { url: "https://github.com/getpaseo/paseo", title: "Paseo" },
  );
  await waitFor(() => harness.calls.notificationsCreated.length === 1);
  assert.equal(
    harness.calls.fetches.find((item) => item.url.endsWith("/memos")).url,
    "http://localhost:5174/api/v1/memos",
  );
});

test("非 MemoIsle 页面不能登记 Web 地址", async () => {
  const harness = createHarness();

  const response = await new Promise((resolve) => {
    harness.listeners.message(
      {
        type: "set-web-context",
        webOrigin: "https://evil.test",
        apiBaseUrl: "https://evil.test/api/v1",
      },
      { tab: { url: "https://evil.test/" } },
      resolve,
    );
  });
  assert.deepEqual(jsonValue(response), { ok: false });
  assert.equal(harness.localStore.memoisle_web_context, undefined);

  harness.listeners.action({
    url: "https://example.com/tool",
    title: "Tool",
  });
  await waitFor(() =>
    harness.calls.fetches.some((item) => item.url.endsWith("/memos")),
  );
  const captureRequest = harness.calls.fetches.find((item) =>
    item.url.endsWith("/memos"),
  );
  assert.equal(captureRequest.url, "http://127.0.0.1:8000/api/v1/memos");
});

test("页面不能替其他源登记 Web 地址", async () => {
  const harness = createHarness();

  const response = await new Promise((resolve) => {
    harness.listeners.message(
      {
        type: "set-web-context",
        webOrigin: "http://localhost:5177",
        apiBaseUrl: "http://localhost:5177/api/v1",
      },
      { tab: { url: "http://localhost:5174/" } },
      resolve,
    );
  });

  assert.deepEqual(jsonValue(response), { ok: false });
  assert.equal(harness.localStore.memoisle_web_context, undefined);
});

test("只报来源时会沿用同一来源上一次登记的 API 地址", async () => {
  const harness = createHarness({
    storedWebContext: {
      webBaseUrl: "http://localhost:5174",
      apiBaseUrl: "http://localhost:5174/api/v1",
    },
  });

  const response = await new Promise((resolve) => {
    harness.listeners.message(
      { type: "set-web-context", webOrigin: "http://localhost:5174" },
      { tab: { url: "http://localhost:5174/" } },
      resolve,
    );
  });

  assert.deepEqual(jsonValue(response), { ok: true });
  assert.equal(
    harness.localStore.memoisle_web_context.apiBaseUrl,
    "http://localhost:5174/api/v1",
  );
});

test("换到另一个本地端口时会清掉上一个来源的 API 地址", async () => {
  const harness = createHarness({
    storedWebContext: {
      webBaseUrl: "http://localhost:5174",
      apiBaseUrl: "http://localhost:5174/api/v1",
    },
  });

  const response = await new Promise((resolve) => {
    harness.listeners.message(
      { type: "set-web-context", webOrigin: "http://localhost:5175" },
      { tab: { url: "http://localhost:5175/" } },
      resolve,
    );
  });

  assert.deepEqual(jsonValue(response), { ok: true });
  assert.deepEqual(jsonValue(harness.localStore.memoisle_web_context), {
    webBaseUrl: "http://localhost:5175",
    apiBaseUrl: null,
    updatedAt: harness.localStore.memoisle_web_context.updatedAt,
  });
});

test("旧版本登记的非法地址会被忽略", async () => {
  const harness = createHarness({
    storedWebContext: {
      webBaseUrl: "file:///etc/passwd",
      apiBaseUrl: "not-a-url",
    },
  });

  harness.listeners.action({
    url: "https://example.com/tool",
    title: "Tool",
  });
  await waitFor(() =>
    harness.calls.fetches.some((item) => item.url.endsWith("/memos")),
  );

  const captureRequest = harness.calls.fetches.find((item) =>
    item.url.endsWith("/memos"),
  );
  assert.equal(captureRequest.url, "http://127.0.0.1:8000/api/v1/memos");
});

test("后端返回带连字符的 client_id 仍视为新建收藏", async () => {
  const harness = createHarness({
    fetchImpl: async (url, options) => {
      const body = JSON.parse(options.body ?? "{}");
      if (String(url).endsWith("/memos")) {
        const hex = String(body.client_id || "").replaceAll("-", "");
        const hyphenated = [
          hex.slice(0, 8),
          hex.slice(8, 12),
          hex.slice(12, 16),
          hex.slice(16, 20),
          hex.slice(20),
        ].join("-");
        return {
          ok: true,
          status: 201,
          async json() {
            return {
              id: "memo-created",
              version: 1,
              client_id: hyphenated,
              title: body.source_title ?? "",
            };
          },
        };
      }
      if (requestUrl.endsWith("/browser-history/sync")) {
      // 服务端会回显最终使用的设备 ID，扩展据此固定后续同步的归属。
      return {
        ok: true,
        status: 200,
        async json() {
          return {
            synced_count: Array.isArray(body.visits) ? body.visits.length : 0,
            total_count: 1,
            device_id: body.device_id,
            possible_same_device_id: null,
          };
        },
      };
    }
    return { ok: true, status: 200, async json() { return {}; } };
    },
  });

  harness.listeners.action({
    url: "https://example.com/article",
    title: "Article",
  });
  await waitFor(() => harness.calls.notificationsCreated.length === 1);

  const notice = harness.calls.notificationsCreated[0].options;
  assert.equal(notice.title, "已收藏到 MemoIsle");
  assert.deepEqual(notice.buttons, [{ title: "撤销" }, { title: "查看资料" }]);
});

test("非 MemoIsle Web 来源不能写入扩展登录凭证", async () => {
  const harness = createHarness({ storedAccessToken: null });
  const response = await new Promise((resolve) => {
    const keepAlive = harness.listeners.message(
      {
        type: "set-access-token",
        accessToken: "stolen-token",
      },
      { tab: { url: "http://localhost:9999/" } },
      resolve,
    );
    assert.equal(keepAlive, true);
  });

  assert.deepEqual(jsonValue(response), { ok: false });
  harness.listeners.action({
    url: "https://example.com/article",
    title: "Article",
  });
  await waitFor(() => harness.calls.tabsCreated.length === 1);
  const openedUrl = new URL(harness.calls.tabsCreated[0].url);
  assert.equal(
    openedUrl.searchParams.get("memoisle_capture_error"),
    "not_authenticated",
  );
});

test("网页已在资料库时提示定位原条目且不提供撤销", async () => {
  const harness = createHarness({
    fetchImpl: async (url, options) => {
      const body = JSON.parse(options.body ?? "{}");
      if (String(url).endsWith("/memos")) {
        return {
          ok: true,
          status: 200,
          async json() {
            return {
              id: "memo-existing",
              version: 3,
              client_id: "existing-client-id",
              title: body.source_title ?? "",
            };
          },
        };
      }
      if (requestUrl.endsWith("/browser-history/sync")) {
      // 服务端会回显最终使用的设备 ID，扩展据此固定后续同步的归属。
      return {
        ok: true,
        status: 200,
        async json() {
          return {
            synced_count: Array.isArray(body.visits) ? body.visits.length : 0,
            total_count: 1,
            device_id: body.device_id,
            possible_same_device_id: null,
          };
        },
      };
    }
    return { ok: true, status: 200, async json() { return {}; } };
    },
  });

  harness.listeners.action({
    url: "https://example.com/article",
    title: "Article",
  });
  await waitFor(() => harness.calls.notificationsCreated.length === 1);

  const notice = harness.calls.notificationsCreated[0].options;
  assert.equal(notice.title, "网页已在资料库中");
  assert.deepEqual(notice.buttons, [{ title: "查看资料" }]);
  assert.ok(harness.calls.badges.some((badge) => badge.text === "="));
});

test("点击通知的撤销会删除刚收藏的网页", async () => {
  const harness = createHarness();

  harness.listeners.action({
    url: "https://example.com/article",
    title: "Article",
  });
  await waitFor(() => harness.calls.notificationsCreated.length === 1);

  harness.listeners.notificationButton("memoisle-capture-result", 0);
  await waitFor(() =>
    harness.calls.fetches.some((item) =>
      item.url.endsWith("/memos/memo-created"),
    ),
  );

  const undoRequest = harness.calls.fetches.find((item) =>
    item.url.endsWith("/memos/memo-created"),
  );
  assert.equal(undoRequest.options.method, "PATCH");
  assert.equal(
    undoRequest.options.headers.Authorization,
    "Bearer test-access-token",
  );
  assert.deepEqual(JSON.parse(undoRequest.options.body), {
    expected_version: 1,
    status: "trashed",
  });
  assert.deepEqual(harness.calls.notificationsCleared, [
    "memoisle-capture-result",
  ]);
  await waitFor(() => harness.calls.badges.some((badge) => badge.text === "↩"));
});

test("通知的查看资料会用配置的 Web 地址打开资料库", async () => {
  const harness = createHarness({
    storedConfig: {
      webBaseUrl: "https://memoisle.test/capture?from=extension",
    },
  });

  harness.listeners.action({
    url: "https://example.com/article",
    title: "Article",
  });
  await waitFor(() => harness.calls.notificationsCreated.length === 1);

  harness.listeners.notificationButton("memoisle-capture-result", 1);
  await waitFor(() => harness.calls.tabsCreated.length === 1);
  const openedUrl = new URL(harness.calls.tabsCreated[0].url);
  assert.equal(openedUrl.searchParams.get("from"), "extension");
  assert.equal(openedUrl.searchParams.has("memoisle_capture"), false);
  assert.equal(openedUrl.searchParams.has("memoisle_capture_error"), false);
});

test("右键收藏网页图片会创建图片资料并上传原始字节", async () => {
  const harness = createHarness();

  harness.listeners.contextMenu(
    {
      menuItemId: "memoisle-capture-image",
      srcUrl: "https://cdn.example.com/photos/%E7%8C%AB%E5%92%AA.png?w=800",
      pageUrl: "https://example.com/gallery",
    },
    { id: 8, windowId: 1, url: "https://example.com/gallery", title: "图库" },
  );
  await waitFor(() => harness.calls.notificationsCreated.length === 1);

  const createRequest = harness.calls.fetches.find((item) =>
    item.url.endsWith("/memos"),
  );
  assert.ok(createRequest);
  assert.equal(createRequest.options.method, "POST");
  assert.deepEqual(jsonValue(createRequest.options.headers), {
    "Content-Type": "application/json",
    Authorization: "Bearer test-access-token",
  });
  const body = JSON.parse(createRequest.options.body);
  assert.match(
    body.client_id,
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i,
  );
  assert.equal(body.type, "image");
  assert.equal(body.title, "猫咪");
  assert.equal(body.body, "");
  assert.equal(body.source_url, "https://example.com/gallery");
  assert.equal(body.source_title, "图库");
  assert.deepEqual(body.tags, []);

  const uploadRequest = harness.calls.fetches.find((item) =>
    item.url.includes("/image?"),
  );
  assert.ok(uploadRequest);
  assert.equal(
    uploadRequest.url,
    "http://127.0.0.1:8000/api/v1/memos/memo-created/image?expected_version=1",
  );
  assert.equal(uploadRequest.options.method, "POST");
  assert.equal(uploadRequest.options.headers["Content-Type"], "image/png");
  assert.equal(
    uploadRequest.options.headers.Authorization,
    "Bearer test-access-token",
  );
  assert.deepEqual(Array.from(uploadRequest.options.body), [
    0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a,
    0x00, 0x00, 0x00, 0x0d, 0x49, 0x48, 0x44, 0x52,
  ]);

  const notice = harness.calls.notificationsCreated[0];
  assert.equal(notice.id, "memoisle-capture-result");
  assert.equal(notice.options.title, "已收藏图片到 MemoIsle");
  assert.equal(notice.options.message, "猫咪");
  assert.deepEqual(notice.options.buttons, [
    { title: "撤销" },
    { title: "查看资料" },
  ]);
  assert.ok(harness.calls.badges.some((badge) => badge.text === "✓"));
});

test("超大图片会先压缩再上传并在通知里提示压缩结果", async () => {
  const gifBytes = new Uint8Array(4096);
  gifBytes.set([0x47, 0x49, 0x46, 0x38, 0x39, 0x61], 0);
  const compressedBytes = new Uint8Array(1024);
  let convertToBlobCalls = 0;
  let requestedWidth = 0;
  const requests = [];

  class FakeOffscreenCanvas {
    constructor(width, height) {
      this.width = width;
      this.height = height;
    }

    getContext() {
      return { drawImage() {} };
    }

    async convertToBlob({ type }) {
      convertToBlobCalls += 1;
      requestedWidth = this.width;
      return new Blob([compressedBytes], { type });
    }
  }

  const harness = createHarness({
    createImageBitmap: async () => ({
      width: 14400,
      height: 9000,
      close() {},
    }),
    OffscreenCanvas: FakeOffscreenCanvas,
    fetchImpl: async (url, options = {}) => {
      requests.push({ url: String(url), options });
      if (String(url).includes("/image?")) {
        return {
          ok: true,
          status: 200,
          async json() {
            return { id: "memo-image", version: 2 };
          },
        };
      }
      if (String(url).endsWith("/memos")) {
        return {
          ok: true,
          status: 201,
          async json() {
            return { id: "memo-image", version: 1 };
          },
        };
      }
      return {
        ok: true,
        status: 200,
        headers: { get: () => "image/gif" },
        async arrayBuffer() {
          return gifBytes.slice().buffer;
        },
      };
    },
  });

  harness.listeners.contextMenu(
    {
      menuItemId: "memoisle-capture-image",
      srcUrl: "https://cdn.example.com/huge.gif",
      pageUrl: "https://example.com/gallery",
    },
    { id: 8, windowId: 1, url: "https://example.com/gallery", title: "图库" },
  );
  await waitFor(() => harness.calls.notificationsCreated.length === 1);

  const uploadRequest = requests.find((item) => item.url.includes("/image?"));
  assert.ok(uploadRequest);
  assert.equal(uploadRequest.options.headers["Content-Type"], "image/webp");
  assert.equal(uploadRequest.options.body.length, 1024);
  assert.ok(convertToBlobCalls >= 1);
  // 14400 × 9000 同时超过单边与总像素上限，压缩后按 0.75 缩小到 8944 × 5590。
  assert.equal(requestedWidth, 8944);

  const notice = harness.calls.notificationsCreated[0].options;
  assert.equal(notice.title, "已收藏图片到 MemoIsle");
  assert.match(notice.message, /^huge。/);
  assert.match(notice.message, /已自动压缩后上传/);
  assert.match(notice.message, /4\.0 KB → 1\.0 KB/);
  assert.match(notice.message, /尺寸 14400 × 9000 → 8944 × 5590/);
  assert.match(notice.message, /格式 GIF → WebP/);
  assert.match(notice.message, /动图已转为静态图，仅保留第一帧/);
  assert.deepEqual(notice.buttons, [
    { title: "撤销" },
    { title: "查看资料" },
  ]);
});

test("不支持的图片格式会提示错误且不创建资料", async () => {
  const svgBytes = new TextEncoder().encode(
    '<svg xmlns="http://www.w3.org/2000/svg"></svg>',
  );
  const harness = createHarness({
    fetchImpl: async () => ({
      ok: true,
      status: 200,
      headers: { get: () => "image/svg+xml" },
      async arrayBuffer() {
        return svgBytes.slice().buffer;
      },
    }),
  });

  harness.listeners.contextMenu(
    {
      menuItemId: "memoisle-capture-image",
      srcUrl: "https://cdn.example.com/logo.svg",
      pageUrl: "https://example.com/",
    },
    { id: 8, windowId: 1, url: "https://example.com/", title: "首页" },
  );
  await waitFor(() => harness.calls.notificationsCreated.length === 1);

  assert.equal(
    harness.calls.fetches.some((item) => item.url.endsWith("/memos")),
    false,
  );
  const notice = harness.calls.notificationsCreated[0];
  assert.equal(notice.id, "memoisle-image-notice");
  assert.equal(notice.options.title, "无法收藏图片");
  assert.match(notice.options.message, /格式不被支持/);
});

test("blob: 页面临时图片会明确提示无法读取", async () => {
  const harness = createHarness();

  harness.listeners.contextMenu(
    {
      menuItemId: "memoisle-capture-image",
      srcUrl: "blob:https://example.com/8f6f8d2c",
      pageUrl: "https://example.com/",
    },
    { id: 8, windowId: 1, url: "https://example.com/", title: "首页" },
  );
  await waitFor(() => harness.calls.notificationsCreated.length === 1);

  assert.equal(harness.calls.fetches.length, 0);
  assert.equal(harness.calls.tabsCreated.length, 0);
  const notice = harness.calls.notificationsCreated[0];
  assert.equal(notice.id, "memoisle-image-notice");
  assert.match(notice.options.message, /页面临时图片/);
  assert.match(notice.options.message, /无法直接读取/);
  assert.match(notice.options.message, /网页端收藏/);
});

test("没有登录凭证时右键收藏图片会引导登录且不请求图片", async () => {
  const harness = createHarness({ storedAccessToken: null });

  harness.listeners.contextMenu(
    {
      menuItemId: "memoisle-capture-image",
      srcUrl: "https://cdn.example.com/a.png",
      pageUrl: "https://example.com/",
    },
    { id: 8, windowId: 1, url: "https://example.com/", title: "首页" },
  );
  await waitFor(() => harness.calls.tabsCreated.length === 1);

  assert.equal(harness.calls.fetches.length, 0);
  const openedUrl = new URL(harness.calls.tabsCreated[0].url);
  assert.equal(
    openedUrl.searchParams.get("memoisle_capture_error"),
    "not_authenticated",
  );
  assert.equal(openedUrl.searchParams.has("memoisle_capture"), false);
  assert.equal(harness.calls.notificationsCreated.length, 1);
  assert.equal(
    harness.calls.notificationsCreated[0].id,
    "memoisle-image-notice",
  );
  assert.match(
    harness.calls.notificationsCreated[0].options.message,
    /登录/,
  );
});

test("图片上传返回 401 时引导重新登录", async () => {
  const pngBytes = new Uint8Array([
    0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a,
  ]);
  const harness = createHarness({
    fetchImpl: async (url) => {
      if (String(url).includes("/image?")) {
        return { ok: false, status: 401, async json() { return {}; } };
      }
      if (String(url).endsWith("/memos")) {
        return {
          ok: true,
          status: 201,
          async json() {
            return { id: "memo-image", version: 1 };
          },
        };
      }
      return {
        ok: true,
        status: 200,
        headers: { get: () => "image/png" },
        async arrayBuffer() {
          return pngBytes.slice().buffer;
        },
      };
    },
  });

  harness.listeners.contextMenu(
    {
      menuItemId: "memoisle-capture-image",
      srcUrl: "https://cdn.example.com/a.png",
      pageUrl: "https://example.com/",
    },
    { id: 8, windowId: 1, url: "https://example.com/", title: "首页" },
  );
  await waitFor(() => harness.calls.tabsCreated.length === 1);

  const openedUrl = new URL(harness.calls.tabsCreated[0].url);
  assert.equal(
    openedUrl.searchParams.get("memoisle_capture_error"),
    "not_authenticated",
  );
  // 上传失败时不应弹出「已收藏」通知。
  assert.equal(harness.calls.notificationsCreated.length, 0);
});

test("回填按时间窗分段，超过单次上限的时段用二分补齐", async () => {
  const now = Date.now();
  const dayMs = 24 * 60 * 60 * 1000;
  // 3500 条记录均匀散布在最近 30 天内，单次查询上限只有 1000。
  const everything = Array.from({ length: 3_500 }, (_, index) => ({
    url: `https://archive.example/p${index}`,
    title: `记录 ${index}`,
    lastVisitTime: now - 1_000 - index * Math.floor((29 * dayMs) / 3_500),
    visitCount: 1,
  }));

  const harness = createHarness({
    historyItems: everything,
    // 按窗口真正过滤并截断，模拟 chrome.history.search 的行为。
    historySearch(query) {
      const start = Number(query.startTime) || 0;
      const end = Number(query.endTime) || Date.now();
      return everything
        .filter((item) => item.lastVisitTime >= start && item.lastVisitTime <= end)
        .sort((left, right) => right.lastVisitTime - left.lastVisitTime)
        .slice(0, Number(query.maxResults) || 100);
    },
  });

  harness.listeners.installed();
  // 等回填真正跑完：所有记录都提交过，而不是「游标一写就断言」。
  // 游标在第一批提交后就写入了，只看它会在一半时提前返回。
  const syncedCount = () =>
    harness.calls.fetches
      .filter((item) => item.url.endsWith("/browser-history/sync"))
      .reduce(
        (total, call) => total + JSON.parse(call.options.body).visits.length,
        0,
      );
  await waitFor(() => syncedCount() >= 3_500, 30_000);

  const syncCalls = harness.calls.fetches.filter((item) =>
    item.url.endsWith("/browser-history/sync"),
  );
  let synced = 0;
  for (const call of syncCalls) {
    synced += JSON.parse(call.options.body).visits.length;
  }

  // 单次查询最多 1000 条，但分窗加二分应当把 3500 条全部取到。
  assert.equal(synced, 3_500, "30 天内的记录应当被完整回填");
  assert.ok(syncCalls.length >= 2, "回填应当分批提交");
  assert.ok(harness.calls.historyQueries.length > 1, "回填应当多次分窗查询");
  // 每批请求不超过服务端单次上限 500 条。
  for (const call of syncCalls) {
    assert.ok(JSON.parse(call.options.body).visits.length <= 500);
  }
});

test("回填总量受上限约束，且优先保留最近访问", async () => {
  const now = Date.now();
  const dayMs = 24 * 60 * 60 * 1000;
  // 3 万条，远超 2 万条的回填预算。
  const everything = Array.from({ length: 30_000 }, (_, index) => ({
    url: `https://bulk.example/p${index}`,
    title: `记录 ${index}`,
    lastVisitTime: now - 1_000 - index * Math.floor((29 * dayMs) / 30_000),
    visitCount: 1,
  }));

  const harness = createHarness({
    historyItems: everything,
    historySearch(query) {
      const start = Number(query.startTime) || 0;
      const end = Number(query.endTime) || Date.now();
      return everything
        .filter((item) => item.lastVisitTime >= start && item.lastVisitTime <= end)
        .sort((left, right) => right.lastVisitTime - left.lastVisitTime)
        .slice(0, Number(query.maxResults) || 100);
    },
  });

  harness.listeners.installed();
  await waitFor(
    () => typeof harness.localStore.memoisle_history_sync_state?.since === "number",
    60_000,
  );

  const syncedUrls = new Set();
  for (const call of harness.calls.fetches) {
    if (!call.url.endsWith("/browser-history/sync")) continue;
    for (const visit of JSON.parse(call.options.body).visits) {
      syncedUrls.add(visit.page_url);
    }
  }

  assert.ok(syncedUrls.size <= 20_000, `不应超过回填预算，实际 ${syncedUrls.size}`);
  // 最近的一条一定在里面，最老的一条应当被舍弃。
  assert.equal(syncedUrls.has(everything[0].url), true);
  assert.equal(syncedUrls.has(everything.at(-1).url), false);
});

test("上报历史时带机器指纹和安装标识", async () => {
  const harness = createHarness({
    historyItems: [
      { url: "https://example.com/a", title: "A", lastVisitTime: Date.now(), visitCount: 1 },
    ],
  });
  await harness.listeners.installed();
  await waitFor(() =>
    harness.calls.fetches.some((item) => item.url.endsWith("/browser-history/sync")),
  );

  const request = harness.calls.fetches.find((item) =>
    item.url.endsWith("/browser-history/sync"),
  );
  const body = JSON.parse(request.options.body);
  // 指纹是 SHA-256 十六进制，重装扩展后仍然不变。
  assert.match(body.hardware_key, /^[0-9a-f]{64}$/);
  // 安装标识每次安装都会重新生成。
  assert.match(body.install_id, /^[0-9a-f]{32}$/);
  // 设备 ID 必须是随机主键，不能拿指纹当 ID：
  // 两台同款电脑指纹相同，用指纹当 ID 会让它们一开始就撞成同一台。
  assert.match(body.device_id, /^[0-9a-f]{32}$/);
  assert.notEqual(body.device_id, body.hardware_key.slice(0, 32));
});

test("服务端派发新设备 ID 后会记住它", async () => {
  const harness = createHarness({
    historyItems: [
      { url: "https://example.com/a", title: "A", lastVisitTime: Date.now(), visitCount: 1 },
    ],
    fetchImpl: async (url) => {
      const target = String(url);
      if (target.endsWith("/browser-history/sync")) {
        return new Response(
          JSON.stringify({
            synced_count: 1,
            total_count: 1,
            device_id: "server-assigned-id",
            possible_same_device_id: "mac-original",
          }),
          { status: 200, headers: { "content-type": "application/json" } },
        );
      }
      return new Response("{}", { status: 200 });
    },
  });
  await harness.listeners.installed();
  await waitFor(
    () => harness.localStore.memoisle_device_id === "server-assigned-id",
    3000,
  );
});


// 几年的历史，单轮回填补不完，需要多轮推进。
function multiYearHistory(now) {
  const dayMs = 24 * 60 * 60 * 1000;
  return Array.from({ length: 400 }, (_, index) => ({
    url: `https://archive.example/y${index}`,
    title: `旧记录 ${index}`,
    // 每 5 天一条，覆盖约 5.5 年；单轮最多扫 30 个 7 天窗口（约 7 个月）。
    lastVisitTime: now - 1_000 - index * 5 * dayMs,
    visitCount: 1,
  }));
}

function syncedVisitCount(harness) {
  return harness.calls.fetches
    .filter((item) => item.url.endsWith("/browser-history/sync"))
    .reduce((total, call) => total + JSON.parse(call.options.body).visits.length, 0);
}

test("回填没补完时注册闹钟，不再依赖会被回收的 setTimeout", async () => {
  const harness = createHarness({ historyItems: multiYearHistory(Date.now()) });
  harness.listeners.installed();
  await waitFor(
    () => harness.localStore.memoisle_history_sync_state?.backfillCursor > 0,
    "首轮回填应留下断点",
    10_000,
  );
  await waitFor(() => harness.alarms.has("memoisle-history-backfill"));
  assert.equal(harness.calls.alarmsCreated[0].periodInMinutes, 5);
  // 闲置检测阈值已设置。
  assert.equal(harness.calls.idleInterval, 300);
});

test("电脑闲置时连续推进回填直到补完，并撤掉闹钟", async () => {
  const items = multiYearHistory(Date.now());
  const harness = createHarness({ historyItems: items, idleState: "active" });
  harness.listeners.installed();
  await waitFor(
    () => harness.localStore.memoisle_history_sync_state?.backfillCursor > 0,
    "首轮回填应留下断点",
    10_000,
  );
  const afterFirstRound = syncedVisitCount(harness);
  assert.ok(afterFirstRound < items.length, "首轮不应一次补完");

  // 用户离开电脑：一次闲置事件就应连续跑多轮直到补完。
  harness.idle.state = "idle";
  harness.listeners.idleChanged("idle");
  await waitFor(
    () => harness.localStore.memoisle_history_sync_state?.backfillCursor === undefined,
    "闲置时应补完全部历史",
    20_000,
  );
  assert.equal(syncedVisitCount(harness), items.length);
  await waitFor(() => !harness.alarms.has("memoisle-history-backfill"));
  assert.ok(harness.calls.alarmsCleared.includes("memoisle-history-backfill"));
});

test("用户在用电脑时，闹钟触发也不做大批量回填", async () => {
  const harness = createHarness({
    historyItems: multiYearHistory(Date.now()),
    idleState: "active",
  });
  harness.listeners.installed();
  await waitFor(
    () => harness.localStore.memoisle_history_sync_state?.backfillCursor > 0,
    "首轮回填应留下断点",
    10_000,
  );
  const cursor = harness.localStore.memoisle_history_sync_state.backfillCursor;
  const before = syncedVisitCount(harness);

  harness.listeners.alarm({ name: "memoisle-history-backfill" });
  await new Promise((resolve) => setTimeout(resolve, 200));

  assert.equal(syncedVisitCount(harness), before);
  assert.equal(harness.localStore.memoisle_history_sync_state.backfillCursor, cursor);
});

test("锁屏后闹钟触发会继续推进回填", async () => {
  const harness = createHarness({ historyItems: multiYearHistory(Date.now()) });
  harness.listeners.installed();
  await waitFor(
    () => harness.localStore.memoisle_history_sync_state?.backfillCursor > 0,
    "首轮回填应留下断点",
    10_000,
  );
  const cursor = harness.localStore.memoisle_history_sync_state.backfillCursor;

  // 一直锁屏时没有新的状态变化事件，靠闹钟续跑。
  harness.idle.state = "locked";
  harness.listeners.alarm({ name: "memoisle-history-backfill" });
  await waitFor(
    () => {
      const next = harness.localStore.memoisle_history_sync_state?.backfillCursor;
      return next === undefined || next < cursor;
    },
    "锁屏时闹钟应推进断点",
    20_000,
  );
});

test("待发送的浏览记录会落盘，后台重启后接着发出", async () => {
  const visitTime = Date.now() - 60_000;
  const historyItems = [
    { url: "https://example.com/pending", title: "待发送", lastVisitTime: visitTime, visitCount: 1 },
  ];
  // 第一个后台实例：服务端暂时不可用，记录留在队列里。
  const first = createHarness({
    historyItems,
    storedHistoryState: { since: visitTime - 1_000 },
    fetchImpl: async (url) => {
      if (String(url).endsWith("/browser-history/sync")) {
        return { ok: false, status: 503, async json() { return {}; } };
      }
      return { ok: true, status: 200, async json() { return {}; } };
    },
  });
  first.listeners.tabUpdated(1, { url: "https://example.com/pending" }, {});
  await waitFor(
    () => (first.localStore.memoisle_pending_queues?.history ?? []).some(
      (visit) => visit.page_url === "https://example.com/pending",
    ),
    "发送失败的记录应写进本地存储",
    5_000,
  );

  // 后台被回收后重新唤醒：内存清空，只剩本地存储。
  const second = createHarness({
    historyItems: [],
    storedAccessToken: null,
    sharedLocalStore: first.localStore,
  });
  await waitFor(
    () => second.calls.fetches.some((item) => item.url.endsWith("/browser-history/sync")),
    "重启后应自动重发落盘的记录",
    5_000,
  );
  const body = JSON.parse(
    second.calls.fetches.find((item) => item.url.endsWith("/browser-history/sync")).options.body,
  );
  assert.deepEqual(body.visits.map((visit) => visit.page_url), ["https://example.com/pending"]);
  await waitFor(
    () => second.localStore.memoisle_pending_queues === undefined,
    "发送成功后应清掉落盘队列",
    5_000,
  );
});

test("发送途中后台被回收，这一批也不会丢", async () => {
  const visitTime = Date.now() - 60_000;
  let releaseRequest;
  const first = createHarness({
    historyItems: [
      { url: "https://example.com/in-flight", title: "在途", lastVisitTime: visitTime, visitCount: 1 },
    ],
    storedHistoryState: { since: visitTime - 1_000 },
    // 请求一直不返回，模拟发送途中后台被回收。
    fetchImpl: async (url) => {
      if (String(url).endsWith("/browser-history/sync")) {
        await new Promise((resolve) => { releaseRequest = resolve; });
      }
      return { ok: true, status: 200, async json() { return {}; } };
    },
  });
  first.listeners.tabUpdated(1, { url: "https://example.com/in-flight" }, {});
  await waitFor(() => typeof releaseRequest === "function", "请求应已发出", 5_000);
  // 等落盘的去抖写入完成。
  await new Promise((resolve) => setTimeout(resolve, 120));

  const saved = first.localStore.memoisle_pending_queues?.history ?? [];
  assert.deepEqual(saved.map((visit) => visit.page_url), ["https://example.com/in-flight"]);
  releaseRequest();
});

test("书签改动发送失败后落盘，后台重启后重新提交", async () => {
  const bookmarkTree = [
    { id: "0", title: "", children: [{ id: "1", title: "书签栏", parentId: "0", children: [] }] },
  ];
  const first = createHarness({
    bookmarkTree,
    // 已有完整同步的版本号，书签改动才会走增量队列。
    sharedLocalStore: {
      memoisle_bookmark_sync_state: { revision: 3, totalCount: 0, itemIds: [] },
    },
    fetchImpl: async () => ({ ok: false, status: 503, async json() { return {}; } }),
  });
  first.listeners.bookmarkCreated("42", {
    id: "42",
    title: "新书签",
    url: "https://example.com/new-bookmark",
    parentId: "1",
  });
  await waitFor(
    () => (first.localStore.memoisle_pending_queues?.bookmarks ?? []).length > 0,
    "书签改动应写进本地存储",
    5_000,
  );
  const savedSequence = first.localStore.memoisle_pending_queues.bookmarkSequence;
  assert.ok(savedSequence >= 1);

  const second = createHarness({
    bookmarkTree,
    storedAccessToken: null,
    sharedLocalStore: first.localStore,
  });
  await waitFor(
    () => second.calls.fetches.some((item) => item.url.endsWith("/browser-bookmarks/delta")),
    "重启后应重新提交书签增量",
    5_000,
  );
  const delta = JSON.parse(
    second.calls.fetches.find((item) => item.url.endsWith("/browser-bookmarks/delta")).options.body,
  );
  assert.deepEqual(delta.changes.map((change) => change.client_item_id), ["chrome:42"]);
  assert.equal(delta.changes[0].item.folder_path, "书签栏");
});

test("退出登录时同时清掉落盘的待发记录", async () => {
  const harness = createHarness({
    sharedLocalStore: {
      memoisle_access_token: "test-access-token",
      memoisle_pending_queues: {
        history: [{ page_url: "https://example.com/old-account", page_title: "旧账号", visit_count: 1 }],
        bookmarks: [],
        bookmarkSequence: 0,
      },
    },
    fetchImpl: async () => ({ ok: false, status: 503, async json() { return {}; } }),
  });
  await new Promise((resolve) => setTimeout(resolve, 50));
  await new Promise((resolve) => {
    harness.listeners.message(
      { type: "set-access-token", accessToken: null },
      { url: "http://localhost:5173/", tab: { url: "http://localhost:5173/" } },
      resolve,
    );
  });
  assert.equal(harness.localStore.memoisle_pending_queues, undefined);
});
