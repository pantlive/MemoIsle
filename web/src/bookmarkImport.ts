import type { BookmarkInput } from "./types";

const MAX_BOOKMARK_FILE_BYTES = 10 * 1024 * 1024;
const MAX_BOOKMARKS = 5_000;

function directChild(element: Element, tagName: string): Element | null {
  return (
    Array.from(element.children).find((child) => child.tagName === tagName) ?? null
  );
}

function bookmarkTitle(anchor: Element, url: string): string {
  const title = (anchor.textContent ?? "").trim();
  if (title) {
    return title.slice(0, 300);
  }
  try {
    return new URL(url).hostname.replace(/^www\./, "").slice(0, 300);
  } catch {
    return "未命名书签";
  }
}

function collectBookmarks(
  container: Element,
  folders: string[],
  items: BookmarkInput[],
): void {
  let pendingFolder: string | null = null;
  for (const child of Array.from(container.children)) {
    if (items.length >= MAX_BOOKMARKS) {
      return;
    }
    if (child.tagName === "DT") {
      const heading = directChild(child, "H3");
      const anchor = directChild(child, "A");
      const nestedList = directChild(child, "DL");
      const folderName = (heading?.textContent ?? "").trim();
      if (anchor) {
        const url = (anchor.getAttribute("href") ?? "").trim();
        items.push({
          client_item_id: `bookmark-${items.length + 1}`,
          title: bookmarkTitle(anchor, url),
          url,
          folder_path: folders.length ? folders.join("/") : undefined,
        });
      }
      if (nestedList) {
        collectBookmarks(
          nestedList,
          folderName ? [...folders, folderName] : folders,
          items,
        );
      } else if (folderName) {
        // Netscape 书签格式常把文件夹对应的 DL 放在 H3 所在 DT 之后。
        pendingFolder = folderName;
      }
      continue;
    }
    if (child.tagName === "DL") {
      collectBookmarks(
        child,
        pendingFolder ? [...folders, pendingFolder] : folders,
        items,
      );
      pendingFolder = null;
      continue;
    }
    collectBookmarks(child, folders, items);
  }
}

export async function parseChromeBookmarksFile(
  file: File,
): Promise<BookmarkInput[]> {
  if (file.size > MAX_BOOKMARK_FILE_BYTES) {
    throw new Error("书签文件不能超过 10 MB。");
  }
  const html = await file.text();
  const document = new DOMParser().parseFromString(html, "text/html");
  const root = document.querySelector("dl");
  if (!root) {
    throw new Error("未识别到 Chrome/Netscape 书签结构，请重新导出 HTML 文件。");
  }
  const items: BookmarkInput[] = [];
  collectBookmarks(root, [], items);
  if (!items.length) {
    throw new Error("书签文件中没有可读取的网页链接。");
  }
  if (items.length >= MAX_BOOKMARKS && document.querySelectorAll("a[href]").length > MAX_BOOKMARKS) {
    throw new Error("单次最多导入 5000 条书签，请拆分文件后重试。");
  }
  return items;
}
