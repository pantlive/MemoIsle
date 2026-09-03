import {
  type FormEvent,
  useCallback,
  useEffect,
  useState,
  type ReactNode,
} from "react";

import App from "./App";
import {
  ApiError,
  authAuthorizationUrl,
  clearAccessToken,
  devLogin,
  getAccessToken,
  getAuthProviders,
  getAuthUser,
  loginWithEmail,
  logout,
  registerWithEmail,
  setAccessToken,
} from "./api";
import type { AuthProvidersResponse, AuthUser } from "./types";

type AuthStatus = "loading" | "anonymous" | "authenticated";
type EmailAuthMode = "login" | "register";

function describeAuthError(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message;
  }
  return "登录服务暂时不可用，请稍后重试。";
}

function readAuthCallback(): { token: string | null; error: string | null } {
  const currentUrl = new URL(window.location.href);
  const fragmentParameters = new URLSearchParams(currentUrl.hash.slice(1));
  const token = fragmentParameters.get("access_token");
  const error = fragmentParameters.get("auth_error");
  if (!token && !error) {
    return { token: null, error: null };
  }

  currentUrl.hash = "";
  window.history.replaceState({}, "", currentUrl);
  return { token, error };
}

export default function AuthGate(): ReactNode {
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [providers, setProviders] = useState<AuthProvidersResponse | null>(null);
  const [user, setUser] = useState<AuthUser | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [emailAuthMode, setEmailAuthMode] = useState<EmailAuthMode>("login");
  const [thirdPartyOpen, setThirdPartyOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [displayName, setDisplayName] = useState("");

  const loadProviders = useCallback(async (): Promise<void> => {
    setProviders(await getAuthProviders());
  }, []);

  useEffect(() => {
    let active = true;
    const initializeAuth = async (): Promise<void> => {
      const callback = readAuthCallback();
      const token = callback.token ?? getAccessToken();
      if (callback.error) {
        setError("第三方登录未完成，请重新发起登录。");
      }
      if (!token) {
        const providerList = await getAuthProviders();
        if (!active) {
          return;
        }
        setProviders(providerList);
        setStatus("anonymous");
        return;
      }
      setAccessToken(token);
      try {
        const currentUser = await getAuthUser();
        if (!active) {
          return;
        }
        setUser(currentUser);
        setStatus("authenticated");
      } catch (authError) {
        clearAccessToken();
        if (!active) {
          return;
        }
        setError(describeAuthError(authError));
        setProviders(await getAuthProviders());
        setStatus("anonymous");
      }
    };

    void initializeAuth().catch((initialError: unknown) => {
      if (active) {
        setError(describeAuthError(initialError));
        setStatus("anonymous");
      }
    });
    return () => {
      active = false;
    };
  }, []);

  const handleDevLogin = useCallback(async (): Promise<void> => {
    if (busy) {
      return;
    }
    setBusy(true);
    setError("");
    try {
      const session = await devLogin();
      setAccessToken(session.access_token);
      setUser(session.user);
      setStatus("authenticated");
    } catch (loginError) {
      setError(describeAuthError(loginError));
    } finally {
      setBusy(false);
    }
  }, [busy]);

  const handleEmailAuth = useCallback(
    async (event: FormEvent<HTMLFormElement>): Promise<void> => {
      event.preventDefault();
      if (busy || !email.trim() || password.length < (emailAuthMode === "register" ? 8 : 1)) {
        return;
      }
      if (emailAuthMode === "register" && password !== confirmPassword) {
        setError("两次输入的密码不一致");
        return;
      }
      setBusy(true);
      setError("");
      try {
        const session =
          emailAuthMode === "login"
            ? await loginWithEmail(email.trim(), password)
            : await registerWithEmail(
                email.trim(),
                password,
                confirmPassword,
                displayName.trim() || undefined,
              );
        setAccessToken(session.access_token);
        setUser(session.user);
        setStatus("authenticated");
        setPassword("");
        setConfirmPassword("");
      } catch (authError) {
        setError(describeAuthError(authError));
      } finally {
        setBusy(false);
      }
    },
    [busy, confirmPassword, displayName, email, emailAuthMode, password],
  );

  const handleLogout = useCallback(async (): Promise<void> => {
    try {
      await logout();
    } catch {
      clearAccessToken();
    }
    setUser(null);
    setStatus("anonymous");
    await loadProviders().catch(() => undefined);
  }, [loadProviders]);

  if (status === "loading") {
    return (
      <main className="auth-screen">
        <section className="auth-card">
          <span className="brand-mark" aria-hidden="true">M</span>
          <h1>MemoIsle</h1>
          <p>正在检查登录状态…</p>
        </section>
      </main>
    );
  }

  if (status === "authenticated" && user) {
    return <App authUser={user} onLogout={handleLogout} />;
  }

  return (
    <main className="auth-screen">
      <section className="auth-card">
        <span className="brand-mark" aria-hidden="true">M</span>
        <h1>登录 MemoIsle</h1>
        <p>使用同一账号在 Web 与 Android 之间同步你的资料库。</p>
        {error && <p className="auth-error">{error}</p>}
        <button
          className="auth-toggle"
          type="button"
          onClick={() => setThirdPartyOpen((open) => !open)}
          aria-expanded={thirdPartyOpen}
        >
          {thirdPartyOpen ? "收起第三方登录" : "第三方登录"}
        </button>
        {thirdPartyOpen && (
          <div className="auth-actions">
            {providers?.providers.map((provider) =>
              provider.enabled ? (
                <a
                  href={authAuthorizationUrl(
                    provider.provider,
                    window.location.origin + window.location.pathname,
                  )}
                  key={provider.provider}
                >
                  {provider.label}
                </a>
              ) : (
                <button
                  type="button"
                  disabled
                  key={provider.provider}
                  title="该登录方式尚未配置"
                >
                  {provider.label}
                </button>
              ),
            )}
            {providers?.dev_login_available && (
              <button onClick={() => void handleDevLogin()} disabled={busy}>
                {busy ? "正在登录…" : "本地开发登录"}
              </button>
            )}
          </div>
        )}
        <div className="auth-divider"><span>或使用邮箱登录</span></div>
        {providers?.email_login_enabled !== false && (
          <form className="auth-email-form" onSubmit={handleEmailAuth}>
            <div className="auth-mode-tabs" role="tablist" aria-label="邮箱账号操作">
              <button
                type="button"
                className={emailAuthMode === "login" ? "active" : ""}
                onClick={() => setEmailAuthMode("login")}
              >登录</button>
              <button
                type="button"
                className={emailAuthMode === "register" ? "active" : ""}
                onClick={() => setEmailAuthMode("register")}
              >注册</button>
            </div>
            {emailAuthMode === "register" && (
              <label>
                昵称（可选）
                <input
                  value={displayName}
                  onChange={(event) => setDisplayName(event.target.value)}
                  maxLength={120}
                  autoComplete="nickname"
                />
              </label>
            )}
            <label>
              邮箱
              <input
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                required
                autoComplete="email"
              />
            </label>
            <label>
              密码
              <input
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
                minLength={emailAuthMode === "register" ? 8 : 1}
                maxLength={128}
                autoComplete={
                  emailAuthMode === "login" ? "current-password" : "new-password"
                }
              />
            </label>
            {emailAuthMode === "register" && (
              <label>
                确认密码
                <input
                  type="password"
                  value={confirmPassword}
                  onChange={(event) => setConfirmPassword(event.target.value)}
                  required
                  minLength={8}
                  maxLength={128}
                  autoComplete="new-password"
                />
              </label>
            )}
            <button type="submit" disabled={busy}>
              {busy
                ? "正在处理…"
                : emailAuthMode === "login"
                  ? "邮箱登录"
                  : "创建账号"}
            </button>
          </form>
        )}
      </section>
    </main>
  );
}
