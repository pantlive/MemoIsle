export interface ClipboardWordDraft {
  lemma: string;
  phonetic: string | null;
  meaning: string | null;
  example: string | null;
}

const HTTP_URL = /^(https?:\/\/|www\.)/i;
const BARE_URL = /^[a-z0-9.-]+\.[a-z]{2,}([/:?#].*)?$/i;
const PHONETIC = /([\/\[])([^\/\[\]]{1,80})\1/;
const MIXED_LEMMA_MEANING =
  /^([A-Za-z][A-Za-z0-9'’.\-]*(?:[\s-][A-Za-z][A-Za-z0-9'’.\-]*){0,7})\s+([^\s].*)$/u;
const CJK = /[\u3400-\u9fff]/;

export function parseClipboardWord(raw: string): ClipboardWordDraft | null {
  const text = raw.replace(/\u00a0/g, " ").replace(/\r\n/g, "\n").trim();
  if (!text) {
    return null;
  }
  const firstToken = text.split(/\s+/, 1)[0] ?? "";
  if (isClipboardUrl(text) || isClipboardUrl(firstToken)) {
    return null;
  }

  const lines = text.split("\n").map((line) => line.trim()).filter(Boolean);
  if (lines.length === 0) {
    return null;
  }

  let firstLine = lines[0];
  let phonetic: string | null = null;
  const phoneticMatch = firstLine.match(PHONETIC);
  if (phoneticMatch && phoneticMatch.index !== undefined) {
    phonetic = `/${phoneticMatch[2]}/`.slice(0, 120);
    firstLine = `${firstLine.slice(0, phoneticMatch.index)} ${firstLine.slice(
      phoneticMatch.index + phoneticMatch[0].length,
    )}`
      .replace(/\s+/g, " ")
      .trim();
  }

  let lemma = firstLine;
  let meaning = lines.slice(1).join("\n").trim() || null;
  const mixed = firstLine.match(MIXED_LEMMA_MEANING);
  if (mixed && CJK.test(mixed[2]) && !CJK.test(mixed[1])) {
    lemma = mixed[1].trim();
    meaning = [mixed[2].trim(), meaning].filter(Boolean).join("\n") || null;
  }

  lemma = lemma.replace(/\s+/g, " ").trim();
  if (!isPlausibleLemma(lemma)) {
    return null;
  }
  if (lemma.length > 200) {
    lemma = lemma.slice(0, 200).trim();
  }
  if (meaning && meaning.length > 5_000) {
    meaning = meaning.slice(0, 5_000);
  }
  return {
    lemma,
    phonetic,
    meaning,
    example: null,
  };
}

function isClipboardUrl(value: string): boolean {
  const cleaned = value.trim();
  return HTTP_URL.test(cleaned) || BARE_URL.test(cleaned);
}

function isPlausibleLemma(lemma: string): boolean {
  if (!lemma || lemma.length > 80) {
    return false;
  }
  if (/[.!?。！？]$/.test(lemma) || isClipboardUrl(lemma)) {
    return false;
  }
  if (!/[A-Za-z]/.test(lemma)) {
    return false;
  }
  return lemma.split(/\s+/).filter(Boolean).length <= 8;
}
