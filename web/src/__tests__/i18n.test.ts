// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  getLanguage,
  getLanguagePreference,
  interpolate,
  LANGUAGE_STORAGE_KEY,
  readLanguagePreference,
  reloadLanguagePreference,
  resolveSystemLanguage,
  setLanguagePreference,
  subscribeLanguage,
  t,
  translate,
} from "../i18n";
import { en } from "../locales/en";

function mockNavigatorLanguages(languages: string[]): void {
  vi.spyOn(navigator, "languages", "get").mockReturnValue(languages);
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  localStorage.clear();
  // 其他测试按中文断言，恢复 setup 中固定的中文偏好。
  setLanguagePreference("zh");
});

describe("系统语言解析", () => {
  it("以 zh 开头的语言都解析为中文", () => {
    expect(resolveSystemLanguage(["zh-CN"])).toBe("zh");
    expect(resolveSystemLanguage(["zh-TW", "en-US"])).toBe("zh");
    expect(resolveSystemLanguage(["ZH-hans"])).toBe("zh");
    expect(resolveSystemLanguage(["zh"])).toBe("zh");
  });

  it("其余语言或缺失时一律英文，且只看首选语言", () => {
    expect(resolveSystemLanguage(["en-US", "zh-CN"])).toBe("en");
    expect(resolveSystemLanguage(["ja-JP"])).toBe("en");
    expect(resolveSystemLanguage([])).toBe("en");
    expect(resolveSystemLanguage(undefined)).toBe("en");
    expect(resolveSystemLanguage(["", "zh-CN"])).toBe("zh");
  });

  it("跟随系统时按 navigator.languages 选择，并响应 languagechange", () => {
    mockNavigatorLanguages(["en-US"]);
    setLanguagePreference("system");
    expect(getLanguagePreference()).toBe("system");
    expect(getLanguage()).toBe("en");
    expect(document.documentElement.lang).toBe("en");

    const listener = vi.fn();
    const unsubscribe = subscribeLanguage(listener);
    mockNavigatorLanguages(["zh-CN"]);
    window.dispatchEvent(new Event("languagechange"));
    expect(getLanguage()).toBe("zh");
    expect(document.documentElement.lang).toBe("zh-CN");
    expect(listener).toHaveBeenCalledTimes(1);
    unsubscribe();
  });

  it("手动选择后不再随系统语言变化", () => {
    mockNavigatorLanguages(["zh-CN"]);
    setLanguagePreference("en");
    window.dispatchEvent(new Event("languagechange"));
    expect(getLanguage()).toBe("en");
  });
});

describe("偏好存取", () => {
  it("手动选择写入本机存储，跟随系统时移除", () => {
    setLanguagePreference("en");
    expect(localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBe("en");
    expect(readLanguagePreference()).toBe("en");
    setLanguagePreference("system");
    expect(localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBeNull();
    expect(readLanguagePreference()).toBe("system");
  });

  it("存储里的非法值回退到跟随系统", () => {
    localStorage.setItem(LANGUAGE_STORAGE_KEY, "fr");
    expect(readLanguagePreference()).toBe("system");
  });

  it("读取存储抛异常时回退到跟随系统", () => {
    vi.stubGlobal("localStorage", {
      getItem: () => { throw new Error("denied"); },
      setItem: () => { throw new Error("denied"); },
      removeItem: () => { throw new Error("denied"); },
    });
    expect(readLanguagePreference()).toBe("system");
    mockNavigatorLanguages(["en-GB"]);
    reloadLanguagePreference();
    expect(getLanguagePreference()).toBe("system");
    expect(getLanguage()).toBe("en");
  });

  it("写入存储抛异常时本次会话仍按选择显示", () => {
    vi.stubGlobal("localStorage", {
      getItem: () => null,
      setItem: () => { throw new Error("quota"); },
      removeItem: () => { throw new Error("quota"); },
    });
    expect(setLanguagePreference("en")).toBe("en");
    expect(getLanguage()).toBe("en");
  });
});

describe("文案与插值", () => {
  it("中文界面直接显示 key，并去掉场景后缀", () => {
    expect(translate("zh", "资料库还是空的")).toBe("资料库还是空的");
    expect(translate("zh", "内容 @@item")).toBe("内容");
    expect(translate("en", "内容 @@item")).toBe("Item");
  });

  it("按当前语言插值，缺失参数保留占位符，空值替换为空串", () => {
    setLanguagePreference("en");
    expect(t("已恢复「{title}」。", { title: "Note" })).toBe("Restored \"Note\".");
    setLanguagePreference("zh");
    expect(t("已恢复「{title}」。", { title: "笔记" })).toBe("已恢复「笔记」。");
    expect(interpolate("{a}-{b}-{c}", { a: 1, b: null })).toBe("1--{c}");
  });

  it("英文译文非空，且与中文 key 的占位符完全一致", () => {
    const placeholders = (text: string) => [...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();
    for (const [key, value] of Object.entries(en)) {
      expect(value.trim() === "" && key.trim() !== "", `空译文：${key}`).toBe(false);
      expect(placeholders(value), `占位符不一致：${key}`).toEqual(placeholders(key));
    }
  });

  it("英文译文里不残留中文", () => {
    const cjk = /[一-鿿]/;
    const leftovers = Object.entries(en).filter(([, value]) => cjk.test(value)).map(([key]) => key);
    expect(leftovers).toEqual([]);
  });
});
