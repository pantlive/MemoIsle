// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  discardRelayItem,
  downloadRelayItem,
  pollRelayInbox,
  relayFileUrl,
  relayInboxPath,
  sendRelayFile,
  sendRelayText,
} from "../api";
import { isStandaloneView, readAppRoute, routeHref } from "../appRoute";
import {
  clipboardImageFilename, formatBytes, formatRemaining, isRelayImage, pickClipboardImageType,
  relayFileError, relayTextError,
} from "../relay";
import { navigation } from "../workspaceViews";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

describe("传输页面路由", () => {
  it("relay 是不带条目的独立页面", () => {
    expect(readAppRoute("?view=relay&item=abc")).toEqual({ view: "relay", item: null });
    expect(isStandaloneView("relay")).toBe(true);
    expect(routeHref("https://x.test/?view=word&item=m1&keep=1", { view: "relay", item: "m1" })).toBe(
      "/?view=relay&keep=1",
    );
  });

  it("侧栏有「传输」入口", () => {
    expect(navigation.find((item) => item.action === "relay")?.label).toBe("传输");
  });
});

describe("传输接口参数", () => {
  it("收件箱地址带本端设备、等待秒数和已显示的条目", () => {
    expect(relayInboxPath(25)).toBe("/relay/inbox?device=web&wait=25");
    expect(relayInboxPath(99, ["a", "b"])).toBe("/relay/inbox?device=web&wait=25&known=a%2Cb");
    expect(relayInboxPath(-3)).toBe("/relay/inbox?device=web&wait=0");
  });

  it("文件地址对中文文件名编码，默认发给手机", () => {
    const url = new URL(relayFileUrl("报告 v2.pdf"), "https://x.test");
    expect(url.pathname).toBe("/api/v1/relay/file");
    expect(url.searchParams.get("filename")).toBe("报告 v2.pdf");
    expect(url.searchParams.get("target")).toBe("android");
    expect(url.searchParams.get("source")).toBe("web");
  });

  it("发送文字、上传原始文件字节、取走与忽略都带登录凭证", async () => {
    window.localStorage.setItem("memoisle_access_token", "token-1");
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/relay/text")) return jsonResponse({ id: "t1" }, 201);
      if (url.includes("/relay/file?")) return jsonResponse({ id: "f1" }, 201);
      if (url.includes("/relay/inbox?")) return jsonResponse([]);
      if (url.endsWith("/download")) return new Response("hello", { status: 200 });
      if (init?.method === "DELETE") return new Response(null, { status: 204 });
      return jsonResponse({ detail: "未模拟的接口" }, 500);
    });
    vi.stubGlobal("fetch", fetchMock);

    await sendRelayText("你好");
    const file = new File(["abc"], "a.txt", { type: "text/plain" });
    await sendRelayFile(file);
    await pollRelayInbox(25, ["x"]);
    const blob = await downloadRelayItem("f/1");
    await discardRelayItem("t1");

    expect(await blob.text()).toBe("hello");
    const [textCall, fileCall, pollCall, downloadCall, deleteCall] = fetchMock.mock.calls;
    expect(JSON.parse(String(textCall[1]?.body))).toEqual({ text: "你好", target: "android", source: "web" });
    expect(fileCall[1]?.body).toBe(file);
    expect((fileCall[1]?.headers as Record<string, string>)["Content-Type"]).toBe("text/plain");
    expect(String(pollCall[0])).toContain("/relay/inbox?device=web&wait=25&known=x");
    expect(String(downloadCall[0])).toBe("/api/v1/relay/items/f%2F1/download");
    expect(String(deleteCall[0])).toBe("/api/v1/relay/items/t1");
    for (const call of fetchMock.mock.calls) {
      expect((call[1]?.headers as Record<string, string>).Authorization).toBe("Bearer token-1");
    }
  });

  it("超限时抛出服务端的中文提示", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ detail: "文件不能超过 20 MB" }, 413)));
    await expect(sendRelayFile(new File(["x"], "a.bin"))).rejects.toMatchObject({
      message: "文件不能超过 20 MB",
      status: 413,
    });
  });
});

describe("传输本地校验与文案", () => {
  it("文本按 UTF-8 字节限制 100 KB", () => {
    expect(relayTextError("  ")).toBe("请输入要发送的内容。");
    expect(relayTextError("字".repeat(34_133))).toBeNull();
    expect(relayTextError("字".repeat(34_134))).toContain("100 KB");
  });

  it("文件不能为空或超过 20 MB", () => {
    expect(relayFileError({ name: "a", size: 0 })).toContain("空文件");
    expect(relayFileError({ name: "a", size: 20 * 1024 * 1024 })).toBeNull();
    expect(relayFileError({ name: "大.zip", size: 20 * 1024 * 1024 + 1 })).toContain("20 MB");
  });

  it("格式化大小与剩余时间", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(1536)).toBe("1.5 KB");
    expect(formatBytes(5 * 1024 * 1024)).toBe("5.0 MB");
    expect(formatRemaining(599.2)).toBe("10:00");
    expect(formatRemaining(61)).toBe("1:01");
    expect(formatRemaining(0)).toBe("已过期");
  });
});

describe("剪贴板图片", () => {
  it("有图时挑 image/*，没图返回 null，png 优先", () => {
    expect(pickClipboardImageType(["text/plain", "text/html"])).toBeNull();
    expect(pickClipboardImageType([])).toBeNull();
    expect(pickClipboardImageType(["image/jpeg"])).toBe("image/jpeg");
    expect(pickClipboardImageType(["text/plain", "image/webp"])).toBe("image/webp");
    expect(pickClipboardImageType(["image/jpeg", "image/png"])).toBe("image/png");
    expect(pickClipboardImageType(["image/png", "image/jpeg"])).toBe("image/png");
    expect(pickClipboardImageType(["image/png; charset=binary", "image/jpeg"])).toBe("image/png; charset=binary");
  });

  it("按 mime 生成 clipboard-时间戳.扩展名，未知类型用 png", () => {
    const at = new Date(2026, 10, 20, 15, 30, 0);
    expect(clipboardImageFilename("image/png", at)).toBe("clipboard-20261120-153000.png");
    expect(clipboardImageFilename("image/jpeg", at)).toBe("clipboard-20261120-153000.jpg");
    expect(clipboardImageFilename("image/webp", new Date(2026, 0, 2, 9, 5, 7))).toBe("clipboard-20260102-090507.webp");
    expect(clipboardImageFilename("image/unknown", at)).toBe("clipboard-20261120-153000.png");
    expect(clipboardImageFilename("IMAGE/GIF; charset=binary", at)).toBe("clipboard-20261120-153000.gif");
  });

  it("文件且 mime 以 image/ 开头才算图片", () => {
    expect(isRelayImage({ kind: "file", mime_type: "image/jpeg" })).toBe(true);
    expect(isRelayImage({ kind: "file", mime_type: "image/png; charset=binary" })).toBe(true);
    expect(isRelayImage({ kind: "file", mime_type: "application/pdf" })).toBe(false);
    expect(isRelayImage({ kind: "file", mime_type: null })).toBe(false);
    expect(isRelayImage({ kind: "text", mime_type: "image/png" })).toBe(false);
  });
});
