import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import AuthGate from "./AuthGate";
import { applyTheme, readThemePreference } from "./theme";
import "./styles.css";

// 登录页和主界面都沿用首屏脚本应用的偏好，并同步系统主题变化。
applyTheme(readThemePreference());

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <AuthGate />
  </StrictMode>,
);
