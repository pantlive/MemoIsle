import { type ReactNode, useCallback, useSyncExternalStore } from "react";

import {
  getLanguage,
  getLanguagePreference,
  type Language,
  type LanguagePreference,
  type MessageKey,
  type MessageParams,
  setLanguagePreference,
  subscribeLanguage,
  translate,
} from "./i18n";

export interface I18nValue {
  language: Language;
  preference: LanguagePreference;
  locale: string;
  t: (key: MessageKey, params?: MessageParams) => string;
  setPreference: (pref: LanguagePreference) => LanguagePreference;
}

/**
 * 订阅当前语言：切换后使用它的组件立即重新渲染。
 * 不依赖 Provider，单独渲染组件的测试也能直接用。
 */
export function useI18n(): I18nValue {
  const language = useSyncExternalStore(subscribeLanguage, getLanguage, getLanguage);
  const preference = useSyncExternalStore(subscribeLanguage, getLanguagePreference, getLanguagePreference);
  const t = useCallback(
    (key: MessageKey, params?: MessageParams) => translate(language, key, params),
    [language],
  );
  return {
    language,
    preference,
    locale: language === "zh" ? "zh-CN" : "en-US",
    t,
    setPreference: setLanguagePreference,
  };
}

/**
 * 包住整个应用的语言边界。各组件通过 `useI18n()` 各自订阅切换，
 * 这里只保证根部也订阅一次（`<html lang>` 由 i18n.ts 同步）。
 */
export function I18nProvider({ children }: { children: ReactNode }) {
  useI18n();
  return <>{children}</>;
}
