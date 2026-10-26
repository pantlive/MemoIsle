export type ThemePreference = "system" | "light" | "dark";

const storageKey = "memoisle_theme";
const systemDark = window.matchMedia("(prefers-color-scheme: dark)");
let systemThemeListener: (() => void) | null = null;

export const themeOptions = [
  { value: "system", label: "跟随系统", icon: "monitor" },
  { value: "light", label: "浅色", icon: "sun" },
  { value: "dark", label: "深色", icon: "moon" },
] as const;

export function readThemePreference(): ThemePreference {
  try {
    const stored = localStorage.getItem(storageKey);
    return stored === "light" || stored === "dark" ? stored : "system";
  } catch {
    // 隐私模式或存储受限时继续跟随系统。
    return "system";
  }
}

export function saveThemePreference(pref: ThemePreference): ThemePreference {
  try {
    localStorage.setItem(storageKey, pref);
    return pref;
  } catch {
    // 写入失败时，界面状态与回退的实际主题保持一致。
    return "system";
  }
}

export function applyTheme(pref: ThemePreference): void {
  const root = document.documentElement;
  if (pref === "system") {
    root.removeAttribute("data-theme");
  } else {
    root.dataset.theme = pref;
  }

  const updateBrowserTheme = (): void => {
    const dark = pref === "dark" || (pref === "system" && systemDark.matches);
    document.querySelector<HTMLMetaElement>('meta[name="theme-color"]')
      ?.setAttribute("content", dark ? "#15191c" : "#f5f6f7");
    document.querySelector<HTMLMetaElement>('meta[name="color-scheme"]')
      ?.setAttribute("content", dark ? "dark" : "light");
  };

  // 显式选择主题后移除监听；只有跟随系统时同步浏览器顶栏。
  if (systemThemeListener) {
    systemDark.removeEventListener("change", systemThemeListener);
    systemThemeListener = null;
  }
  updateBrowserTheme();
  if (pref === "system") {
    systemThemeListener = updateBrowserTheme;
    systemDark.addEventListener("change", systemThemeListener);
  }
}
