import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const backgroundSource = await readFile(
  new URL("../background.js", import.meta.url),
  "utf8",
);
const manifest = JSON.parse(
  await readFile(new URL("../manifest.json", import.meta.url), "utf8"),
);

function jsonValue(value) {
  return JSON.parse(JSON.stringify(value));
}

function createHarness({
  activeTab = {
    url: "https://developer.mozilla.org/zh-CN/docs/Web/API",
    title: "Web API",
    favIconUrl: "https://developer.mozilla.org/favicon.ico",
  },
  openTabs,
  fetchImpl,
  storedConfig = {},
} = {}) {
  const listeners = {};
  const resolvedOpenTabs = openTabs ?? [activeTab];
  const calls = {
    contextMenus: [],
    fetches: [],
    queries: [],
    tabsCreated: [],
  };
  const resolvedFetch = fetchImpl ?? (async (url, options) => {
    calls.fetches.push({ url, options });
    return {
      ok: true,
      status: 201,
      async json() {
        return { token: "capture-token" };
      },
    };
  });
  const chrome = {
    runtime: {
      id: "abcdefghijklmnopabcdefghijklmnop",
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
    },
    storage: {
      sync: {
        async get(defaults) {
          return { ...defaults, ...storedConfig };
        },
      },
    },
    contextMenus: {
      create(options) {
        calls.contextMenus.push(jsonValue(options));
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
    backgroundSource,
    vm.createContext({
      URL,
      chrome,
      console,
      crypto: { randomUUID },
      fetch: resolvedFetch,
    }),
    { filename: "background.js" },
  );

  return { calls, listeners };
}

async function waitFor(predicate, message = "等待扩展异步动作超时") {
  for (let attempt = 0; attempt < 50; attempt += 1) {
    if (predicate()) {
      return;
    }
    await new Promise((resolve) => setImmediate(resolve));
  }
  assert.fail(message);
}

test("安装时注册最小化的网页右键菜单", () => {
  const harness = createHarness();

  harness.listeners.installed();

  assert.deepEqual(harness.calls.contextMenus, [
    {
      id: "memoisle-capture-page",
      title: "收藏到 MemoIsle",
      contexts: ["page"],
    },
  ]);
});

test("扩展清单允许读取当前浏览器打开的标签页", () => {
  assert.equal(manifest.permissions.includes("tabs"), true);
});

test("点击扩展图标会同步当前浏览器网页并打开带一次性令牌的 Web", async () => {
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
  await waitFor(() => harness.calls.tabsCreated.length === 1);

  assert.equal(harness.calls.fetches.length, 2);
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
    item.url.endsWith("/browser-captures"),
  );
  assert.ok(request);
  assert.equal(
    request.url,
    "http://127.0.0.1:8000/api/v1/browser-captures",
  );
  assert.equal(request.options.method, "POST");
  assert.deepEqual(jsonValue(request.options.headers), {
    "Content-Type": "application/json",
  });
  const body = JSON.parse(request.options.body);
  assert.equal(body.extension_id, "abcdefghijklmnopabcdefghijklmnop");
  assert.equal(body.tab_id, 7);
  assert.equal(body.window_id, 1);
  assert.equal(body.page_url, "https://example.com/learning?id=42");
  assert.equal(body.page_title, "学习资料");
  assert.equal(body.favicon_url, "https://example.com/favicon.ico");
  assert.match(body.nonce, /^[0-9a-f]{32}$/);

  const openedUrl = new URL(harness.calls.tabsCreated[0].url);
  assert.equal(openedUrl.origin, "http://localhost:5173");
  assert.equal(openedUrl.searchParams.get("memoisle_capture"), "capture-token");
});

test("快捷键与右键菜单只在明确触发时捕获当前页", async () => {
  const shortcutHarness = createHarness();

  shortcutHarness.listeners.command("unrelated-command");
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(shortcutHarness.calls.queries.length, 0);

  shortcutHarness.listeners.command("capture-current-page");
  await waitFor(() => shortcutHarness.calls.tabsCreated.length === 1);
  assert.deepEqual(shortcutHarness.calls.queries.slice(-2), [
    { active: true, currentWindow: true },
    {},
  ]);
  assert.equal(shortcutHarness.calls.fetches.length, 2);

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
  await waitFor(() => contextHarness.calls.tabsCreated.length === 1);
  assert.equal(contextHarness.calls.fetches.length, 2);
});

test("浏览器标签页变化会刷新当前打开网页快照", async () => {
  const harness = createHarness();

  harness.listeners.tabCreated();
  await waitFor(() => harness.calls.fetches.length === 1);
  harness.listeners.tabUpdated(7, { status: "complete" }, {});
  await waitFor(() => harness.calls.fetches.length === 2);
  harness.listeners.tabActivated({ tabId: 7, windowId: 1 });
  await waitFor(() => harness.calls.fetches.length === 3);
  harness.listeners.tabRemoved(7, { windowId: 1, isWindowClosing: false });
  await waitFor(() => harness.calls.fetches.length === 4);

  assert.equal(
    harness.calls.fetches.every((request) =>
      request.url.endsWith("/browser-tabs/sync"),
    ),
    true,
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

test("后端拒绝、服务异常和连接失败会给 Web 明确错误", async (context) => {
  const cases = [
    { status: 422, errorCode: "unsupported_page" },
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

test("自定义 API 与 Web 地址会被正确使用", async () => {
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
  await waitFor(() => harness.calls.tabsCreated.length === 1);

  assert.equal(harness.calls.fetches.length, 2);
  const captureRequest = harness.calls.fetches.find((item) =>
    item.url.endsWith("/browser-captures"),
  );
  assert.ok(captureRequest);
  assert.equal(
    captureRequest.url,
    "https://api.memoisle.test/api/v1/browser-captures",
  );
  const openedUrl = new URL(harness.calls.tabsCreated[0].url);
  assert.equal(openedUrl.searchParams.get("from"), "extension");
  assert.equal(openedUrl.searchParams.get("memoisle_capture"), "capture-token");
});
