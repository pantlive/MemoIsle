// 网页资料共用的网址工具：补全协议并校验，或取出展示用的站点名。

export function normalizeWebUrl(value: string): string | null {
  const cleaned = value.trim();
  if (!cleaned) {
    return null;
  }
  const candidate = /^https?:\/\//i.test(cleaned) ? cleaned : `https://${cleaned}`;
  try {
    const parsed = new URL(candidate);
    if (!parsed.hostname || !["http:", "https:"].includes(parsed.protocol)) {
      return null;
    }
    return parsed.toString();
  } catch {
    return null;
  }
}

export function sourceHost(sourceUrl: string | null): string {
  if (!sourceUrl) {
    return "网页资料";
  }
  try {
    return new URL(sourceUrl).hostname.replace(/^www\./, "");
  } catch {
    return sourceUrl;
  }
}

/** 常见的二级后缀，取站点首字时要再往前退一段。 */
const COMPOUND_SUFFIXES = new Set([
  "com.cn",
  "net.cn",
  "org.cn",
  "gov.cn",
  "edu.cn",
  "co.uk",
  "org.uk",
  "ac.uk",
  "co.jp",
  "ne.jp",
  "or.jp",
  "com.tw",
  "com.hk",
  "com.au",
  "co.kr",
]);

/** 取第一个字形；emoji 等代理对不会被截成半个字符。 */
function firstGlyph(value: string): string {
  const [glyph] = Array.from(value.trim());
  return glyph ?? "";
}

/** CJK、假名、谚文等全角文字：同字号下比拉丁大写字母重，需要单独降一档。 */
export function isIdeographic(value: string): boolean {
  return /[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]/.test(value);
}

/**
 * 网页资料图标里的「站点首字」。
 *
 * 优先用抓取到的站点名（`resource_site_name`），没有就退回域名里可读的那一段：
 * `github.com` → G，`news.ycombinator.com` → Y，`sspai.com.cn` → S。
 * 拿不到可用字符时返回空串，由调用方决定兜底图标。
 */
export function sourceMonogram(
  sourceUrl: string | null | undefined,
  siteName?: string | null,
): string {
  const fromSiteName = firstGlyph(siteName ?? "");
  if (fromSiteName) {
    return isIdeographic(fromSiteName)
      ? fromSiteName
      : fromSiteName.toLocaleUpperCase();
  }

  // 没有网址时 sourceHost 会返回「网页资料」，那不是站点，别把「网」当首字。
  if (!sourceUrl?.trim()) {
    return "";
  }
  const host = sourceHost(sourceUrl);
  const labels = host.split(".").filter(Boolean);
  if (labels.length === 0) {
    return "";
  }
  if (labels[0].toLowerCase() === "www") {
    labels.shift();
  }
  if (labels.length === 0) {
    return "";
  }

  const suffix = labels.slice(-2).join(".").toLowerCase();
  const index = COMPOUND_SUFFIXES.has(suffix)
    ? labels.length - 3
    : labels.length - 2;
  const label = labels[Math.max(0, index)] ?? labels[0];

  // IPv4 / 纯数字域名取首字符意义不大，交给调用方兜底。
  const glyph = firstGlyph(label);
  return glyph && !/[\d.:-]/.test(glyph) ? glyph.toLocaleUpperCase() : "";
}
