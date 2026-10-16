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
