import { describe, expect, it } from "vitest";
import { extractCaptureUrl, suggestCaptureType } from "../captureTypeSuggestion";
import { parseClipboardWord } from "../clipboardWord";
import { normalizeWebUrl, sourceHost } from "../webUrl";

describe("parseClipboardWord", () => {
  it("splits lemma, phonetic and Chinese meaning", () => {
    expect(parseClipboardWord("serendipity /ˌserənˈdɪpəti/ 意外发现")).toEqual({
      lemma: "serendipity",
      phonetic: "/ˌserənˈdɪpəti/",
      meaning: "意外发现",
      example: null,
    });
  });

  it("rejects urls, paths and sentences", () => {
    expect(parseClipboardWord("https://example.com")).toBeNull();
    expect(parseClipboardWord("src/App.tsx")).toBeNull();
    expect(parseClipboardWord("This is a sentence.")).toBeNull();
    expect(parseClipboardWord("   ")).toBeNull();
  });
});

describe("capture type suggestion", () => {
  it("extracts the first url without trailing punctuation", () => {
    expect(extractCaptureUrl("看看 https://a.test/x）。")).toBe("https://a.test/x");
    expect(extractCaptureUrl("纯文字")).toBeNull();
  });

  it("suggests resource for text containing a url", () => {
    expect(suggestCaptureType({ title: "", body: "https://a.test", url: "" })?.type).toBe(
      "resource",
    );
    expect(suggestCaptureType({ title: "", body: "", url: "" })).toBeNull();
  });
});

describe("web urls", () => {
  it("normalizes and reads hosts", () => {
    expect(normalizeWebUrl("example.com/a")).toMatch(/^https?:\/\/example\.com\/a$/);
    expect(sourceHost("https://www.example.com/path")).toMatch(/example\.com$/);
    expect(sourceHost(null)).toBe("网页资料");
  });
});
