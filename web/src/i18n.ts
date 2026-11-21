import { en } from "./locales/en";

/**
 * 界面语言：跟随系统或手动选择中文 / English，偏好只存在本机。
 *
 * 文案以中文原文作为 key（`t("保存")`），英文译文在 `locales/en.ts`；
 * 新增中文文案却没写英文时 `tsc` 直接报错，避免漏翻。
 * 同一句中文在不同场景需要不同英文时，key 末尾加 ` @@场景`（如 `"收藏 @@nav"`），
 * 中文界面会去掉这个后缀。
 * 非组件模块可直接调用 `t()`；组件里用 `useI18n()` 订阅切换，切换后无需刷新。
 */

export type Language = "zh" | "en";
export type LanguagePreference = "system" | Language;
export type MessageKey = keyof typeof en;
export type MessageParams = Record<string, string | number | null | undefined>;

export const LANGUAGE_STORAGE_KEY = "memoisle_language";

export const languageOptions: ReadonlyArray<{ value: LanguagePreference; label: string }> = [
  // 「中文」「English」用各自语言的自称，任何界面语言下都不翻译。
  { value: "system", get label() { return t("跟随系统"); } },
  { value: "zh", label: "中文" },
  { value: "en", label: "English" },
];

const catalogs: Record<Language, Partial<Record<MessageKey, string>>> = {
  zh: {},
  en,
};

/** 系统语言以 zh 开头（zh-CN、zh-TW、zh-Hans…）时用中文，其余一律英文。 */
export function resolveSystemLanguage(languages: readonly string[] | undefined | null): Language {
  const first = languages?.find((item) => typeof item === "string" && item.trim() !== "");
  return first?.trim().toLowerCase().startsWith("zh") ? "zh" : "en";
}

function systemLanguages(): readonly string[] {
  if (typeof navigator === "undefined") return [];
  if (Array.isArray(navigator.languages) && navigator.languages.length > 0) {
    return navigator.languages;
  }
  return navigator.language ? [navigator.language] : [];
}

function parsePreference(value: unknown): LanguagePreference {
  return value === "zh" || value === "en" ? value : "system";
}

export function readLanguagePreference(): LanguagePreference {
  try {
    return parsePreference(globalThis.localStorage?.getItem(LANGUAGE_STORAGE_KEY));
  } catch {
    // 隐私模式或存储受限时跟随系统。
    return "system";
  }
}

function writeLanguagePreference(pref: LanguagePreference): void {
  try {
    if (pref === "system") {
      globalThis.localStorage?.removeItem(LANGUAGE_STORAGE_KEY);
    } else {
      globalThis.localStorage?.setItem(LANGUAGE_STORAGE_KEY, pref);
    }
  } catch {
    // 写入失败只影响下次启动；本次会话仍按选择显示。
  }
}

interface LanguageState {
  preference: LanguagePreference;
  language: Language;
}

let state: LanguageState = computeState(readLanguagePreference());
const listeners = new Set<() => void>();

function computeState(preference: LanguagePreference): LanguageState {
  return {
    preference,
    language: preference === "system" ? resolveSystemLanguage(systemLanguages()) : preference,
  };
}

function applyDocumentLanguage(language: Language): void {
  if (typeof document === "undefined") return;
  document.documentElement.lang = language === "zh" ? "zh-CN" : "en";
}

function updateState(next: LanguageState): void {
  const changed = next.language !== state.language || next.preference !== state.preference;
  state = next;
  applyDocumentLanguage(state.language);
  if (changed) {
    for (const listener of [...listeners]) listener();
  }
}

if (typeof window !== "undefined") {
  // 跟随系统时，系统 / 浏览器语言变化后立即切换。
  window.addEventListener("languagechange", () => {
    if (state.preference === "system") updateState(computeState("system"));
  });
}
applyDocumentLanguage(state.language);

export function getLanguagePreference(): LanguagePreference {
  return state.preference;
}

export function getLanguage(): Language {
  return state.language;
}

export function setLanguagePreference(pref: LanguagePreference): LanguagePreference {
  const preference = parsePreference(pref);
  writeLanguagePreference(preference);
  updateState(computeState(preference));
  return preference;
}

/** 重新读取存储与系统语言，供测试或外部修改存储后使用。 */
export function reloadLanguagePreference(): void {
  updateState(computeState(readLanguagePreference()));
}

export function subscribeLanguage(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Intl 格式化用的 locale。 */
export function currentLocale(): string {
  return state.language === "zh" ? "zh-CN" : "en-US";
}

export function interpolate(template: string, params?: MessageParams): string {
  if (!params) return template;
  return template.replace(/\{(\w+)\}/g, (match, name: string) => {
    if (!Object.prototype.hasOwnProperty.call(params, name)) return match;
    const value = params[name];
    return value === null || value === undefined ? "" : String(value);
  });
}

const CONTEXT_SUFFIX = / @@\w+$/;

export function translate(language: Language, key: MessageKey, params?: MessageParams): string {
  const template = catalogs[language][key] ?? key.replace(CONTEXT_SUFFIX, "");
  return interpolate(template, params);
}

/** 按当前语言取文案；key 是中文原文，`{name}` 为插值参数。 */
export function t(key: MessageKey, params?: MessageParams): string {
  return translate(state.language, key, params);
}

/** 只标记文案 key、不立即翻译；用于模块级常量，渲染时再 `t()`。 */
export function msg<K extends MessageKey>(key: K): K {
  return key;
}

/** 当前语言下的列表连接符（中文「、」，英文 ", "）。 */
export function listSeparator(): string {
  return state.language === "zh" ? "、" : ", ";
}

const dateTimeFormatCache = new Map<string, Intl.DateTimeFormat>();

/** 按当前语言取（并缓存）日期格式化器；切换语言后自动换成对应 locale。 */
export function dateTimeFormat(options: Intl.DateTimeFormatOptions): Intl.DateTimeFormat {
  const locale = currentLocale();
  const cacheKey = `${locale}|${JSON.stringify(options)}`;
  let formatter = dateTimeFormatCache.get(cacheKey);
  if (!formatter) {
    formatter = new Intl.DateTimeFormat(locale, options);
    dateTimeFormatCache.set(cacheKey, formatter);
  }
  return formatter;
}
