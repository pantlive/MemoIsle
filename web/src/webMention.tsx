import type { ReactNode } from "react";
import type { BrowserOpenTab } from "./types";
import { sourceHost } from "./webUrl";

/** 收藏输入框里的「@网页」：从浏览器打开的标签页中挑选。 */

export function readWebMentionQuery(value: string): string | null {
  const match = value.match(/(^|\s)@([^\s]*)$/);
  return match ? match[2] : null;
}

export function tabMatchesMentionQuery(tab: BrowserOpenTab, query: string): boolean {
  const needle = query.trim().toLowerCase();
  if (!needle) {
    return true;
  }
  return (
    tab.page_title.toLowerCase().includes(needle) ||
    tab.page_url.toLowerCase().includes(needle) ||
    sourceHost(tab.page_url).toLowerCase().includes(needle)
  );
}

export function highlightMentionMatch(text: string, query: string): ReactNode {
  const needle = query.trim();
  if (!needle) {
    return text;
  }
  const index = text.toLowerCase().indexOf(needle.toLowerCase());
  if (index < 0) {
    return text;
  }
  return (
    <>
      {text.slice(0, index)}
      <mark className="capture-command-mark">
        {text.slice(index, index + needle.length)}
      </mark>
      {text.slice(index + needle.length)}
    </>
  );
}

// 判断地址是否为 MemoIsle 本站页面，一键收藏时需跳过自身标签页。
export function isMemoIslePageUrl(rawUrl: string): boolean {
  try {
    return new URL(rawUrl).origin === window.location.origin;
  } catch {
    return false;
  }
}
