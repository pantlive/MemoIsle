const PAGE_MESSAGE_SOURCE = "memoisle-web";
const SET_ACCESS_TOKEN_MESSAGE = "set-access-token";
const WEB_CONTEXT_MESSAGE = "web-context";
const EXTENSION_MESSAGE_SOURCE = "memoisle-extension";
const ACCESS_TOKEN_SYNCED_MESSAGE = "access-token-synced";
const READY_MESSAGE = "ready";
const REQUEST_WEB_CONTEXT_MESSAGE = "request-web-context";

function notifyPage(message) {
  if (typeof window.postMessage !== "function") {
    return;
  }
  window.postMessage(message, window.location.origin);
}

function notifyAccessTokenSynced(requestId, ok) {
  if (!requestId) {
    return;
  }
  notifyPage({
    source: EXTENSION_MESSAGE_SOURCE,
    type: ACCESS_TOKEN_SYNCED_MESSAGE,
    requestId,
    ok,
  });
}

function reportWebContext(webOrigin, apiBaseUrl) {
  try {
    // 只登记本页所在的源；后台还会按发送者地址再复核一次，页面无法替别的源登记。
    const response = chrome.runtime.sendMessage({
      type: "set-web-context",
      webOrigin:
        typeof webOrigin === "string" && webOrigin ? webOrigin : window.location.origin,
      apiBaseUrl: typeof apiBaseUrl === "string" && apiBaseUrl ? apiBaseUrl : null,
    });
    response?.catch?.(() => {
      // 扩展正在重载时消息可能失败，下一次页面加载会再次登记。
    });
  } catch {
    // 扩展正在重载时可能暂时无法通信。
  }
}

function forwardAccessToken(message) {
  const { accessToken, requestId, webOrigin, apiBaseUrl } = message;
  try {
    // 凭证和地址一起登记，避免并发消息把刚学到的 API 地址覆盖为空。
    const response = chrome.runtime.sendMessage({
      type: SET_ACCESS_TOKEN_MESSAGE,
      accessToken,
      webOrigin:
        typeof webOrigin === "string" && webOrigin ? webOrigin : window.location.origin,
      apiBaseUrl: typeof apiBaseUrl === "string" && apiBaseUrl ? apiBaseUrl : null,
    });
    if (response && typeof response.catch === "function") {
      response.then(
        (result) => notifyAccessTokenSynced(requestId, result?.ok === true),
        () => notifyAccessTokenSynced(requestId, false),
      );
    } else if (requestId) {
      notifyAccessTokenSynced(requestId, false);
    } else {
      response?.catch?.(() => {
        // 扩展正在重载时消息可能失败，下一次页面登录会再次同步。
      });
    }
  } catch {
    // 扩展正在重载时可能暂时无法通信。
    notifyAccessTokenSynced(requestId, false);
  }
}

window.addEventListener("message", (event) => {
  if (
    event.source !== window ||
    event.origin !== window.location.origin ||
    event.data?.source !== PAGE_MESSAGE_SOURCE
  ) {
    return;
  }
  if (event.data.type === WEB_CONTEXT_MESSAGE) {
    // 页面回答「你部署在哪、API 在哪」，扩展据此打开正确的地址。
    reportWebContext(event.data.webOrigin, event.data.apiBaseUrl);
    return;
  }
  if (event.data.type !== SET_ACCESS_TOKEN_MESSAGE) {
    return;
  }
  const accessToken = event.data.accessToken;
  if (accessToken !== null && typeof accessToken !== "string") {
    return;
  }
  forwardAccessToken(event.data);
});

// 页面一加载就先登记地址：即使还没登录，右键收藏后也能打开正在运行的 Web 地址。
reportWebContext();
// 告知已打开的 MemoIsle 页面扩展已经注入；页面可据此重发当前登录凭证与地址。
notifyPage({
  source: EXTENSION_MESSAGE_SOURCE,
  type: READY_MESSAGE,
});
notifyPage({
  source: EXTENSION_MESSAGE_SOURCE,
  type: REQUEST_WEB_CONTEXT_MESSAGE,
});
