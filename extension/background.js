const DEFAULT_CONFIG = {
  apiBaseUrl: "http://127.0.0.1:8000/api/v1",
  webBaseUrl: "http://localhost:5173/",
};

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

async function readConfig() {
  const stored = await chrome.storage.sync.get(DEFAULT_CONFIG);
  return {
    apiBaseUrl: String(stored.apiBaseUrl || DEFAULT_CONFIG.apiBaseUrl).replace(/\/$/, ""),
    webBaseUrl: String(stored.webBaseUrl || DEFAULT_CONFIG.webBaseUrl),
  };
}

async function openWebCapture(config, token, errorCode) {
  const target = new URL(config.webBaseUrl);
  if (token) {
    target.searchParams.set("memoisle_capture", token);
  }
  if (errorCode) {
    target.searchParams.set("memoisle_capture_error", errorCode);
  }
  await chrome.tabs.create({ url: target.toString() });
}

function queryAllTabs() {
  return new Promise((resolve) => {
    chrome.tabs.query({}, resolve);
  });
}

async function syncOpenTabs(config = null) {
  try {
    const resolvedConfig = config || await readConfig();
    const tabs = await queryAllTabs();
    const openTabs = tabs
      .filter((tab) => Number.isInteger(tab?.id) && isSupportedPage(tab.url))
      .map((tab) => ({
        tab_id: tab.id,
        window_id: Number.isInteger(tab.windowId) ? tab.windowId : null,
        page_url: tab.url,
        page_title: tab.title || "",
        favicon_url: tab.favIconUrl || null,
      }));
    await fetch(`${resolvedConfig.apiBaseUrl}/browser-tabs/sync`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        extension_id: chrome.runtime.id,
        tabs: openTabs,
      }),
    });
  } catch {
    // 浏览器标签页同步失败不阻止当前页的一次性收藏流程。
  }
}

async function captureTab(tab) {
  const config = await readConfig();
  if (!tab?.url || !isSupportedPage(tab.url)) {
    await openWebCapture(config, null, "unsupported_page");
    return;
  }

  await syncOpenTabs(config);

  try {
    const response = await fetch(`${config.apiBaseUrl}/browser-captures`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        extension_id: chrome.runtime.id,
        tab_id: Number.isInteger(tab.id) ? tab.id : null,
        window_id: Number.isInteger(tab.windowId) ? tab.windowId : null,
        nonce: crypto.randomUUID().replaceAll("-", ""),
        page_url: tab.url,
        page_title: tab.title || "",
        favicon_url: tab.favIconUrl || null,
      }),
    });
    if (!response.ok) {
      const errorCode = response.status === 422 ? "unsupported_page" : "capture_failed";
      await openWebCapture(config, null, errorCode);
      return;
    }
    const payload = await response.json();
    await openWebCapture(config, payload.token, null);
  } catch {
    await openWebCapture(config, null, "connection_failed");
  }
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "memoisle-capture-page",
    title: "收藏到 MemoIsle",
    contexts: ["page"],
  });
  void readConfig().then((config) => syncOpenTabs(config));
});

chrome.runtime.onStartup.addListener(() => {
  void readConfig().then((config) => syncOpenTabs(config));
});

chrome.tabs.onCreated.addListener(() => {
  void syncOpenTabs();
});

chrome.tabs.onUpdated.addListener((_tabId, changeInfo) => {
  if (
    changeInfo.url !== undefined ||
    changeInfo.title !== undefined ||
    changeInfo.favIconUrl !== undefined ||
    changeInfo.status === "complete"
  ) {
    void syncOpenTabs();
  }
});

chrome.tabs.onActivated.addListener(() => {
  void syncOpenTabs();
});

chrome.tabs.onRemoved.addListener(() => {
  void syncOpenTabs();
});

chrome.action.onClicked.addListener((tab) => {
  void captureTab(tab);
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId === "memoisle-capture-page") {
    void captureTab(tab);
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
