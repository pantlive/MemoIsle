import type { MemoType } from "./types";

export interface CaptureTypeSuggestion {
  type: MemoType;
  reason: string;
  key: string;
}

interface CaptureTypeInput {
  title: string;
  body: string;
  url: string;
}

const CJK = /[\u3400-\u9fff]/u;
const HTTP_URL = /https?:\/\/[^\s]+/iu;
const BARE_URL = /(?:^|\s)(?:www\.)?[a-z0-9-]+(?:\.[a-z0-9-]+)+(?:\/[^\s]*)?/iu;
const ENGLISH_LEMMA =
  /^[A-Za-z][A-Za-z0-9'’.\-]*(?:[\s-][A-Za-z][A-Za-z0-9'’.\-]*){0,5}$/u;

/** 从输入文本中提取第一个 HTTP(S) 网址，供类型切换时保留用户内容。 */
export function extractCaptureUrl(value: string): string | null {
  const match = value.match(HTTP_URL) ?? value.match(BARE_URL);
  if (!match) {
    return null;
  }
  return match[0].replace(/[),.;!?，。！？）】》]+$/u, "");
}

function looksLikeEnglishLemma(value: string): boolean {
  const cleaned = value.trim().replace(/\s+/gu, " ");
  return (
    cleaned.length > 0 &&
    cleaned.length <= 80 &&
    !CJK.test(cleaned) &&
    !/[.!?。！？]$/u.test(cleaned) &&
    ENGLISH_LEMMA.test(cleaned)
  );
}

/** 根据网址、词形和正文给出非强制的捕获类型建议。 */
export function suggestCaptureType(
  input: CaptureTypeInput,
): CaptureTypeSuggestion | null {
  const title = input.title.trim();
  const body = input.body.trim();
  const url = input.url.trim();
  const sourceText = [url, title, body].filter(Boolean).join(" ");
  if (!sourceText) {
    return null;
  }

  const foundUrl = extractCaptureUrl(sourceText);
  if (foundUrl) {
    return {
      type: "resource",
      reason: "检测到网址，更适合保存为网页资料",
      key: `resource:${foundUrl.toLowerCase()}`,
    };
  }

  const lemmaCandidate = title || body.split("\n", 1)[0] || "";
  if (looksLikeEnglishLemma(lemmaCandidate)) {
    return {
      type: "word",
      reason: "内容像英语单词或短语，可以直接查词并加入复习",
      key: `word:${lemmaCandidate.toLowerCase()}:${body.slice(0, 80)}`,
    };
  }

  if (body || title) {
    return {
      type: "idea",
      reason: "这段内容更适合先放入灵感收件箱",
      key: `idea:${title}:${body.slice(0, 120)}`,
    };
  }
  return null;
}
