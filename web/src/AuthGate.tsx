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
  requestEmailVerification,
  requestPasswordReset,
  registerWithEmail,
  resetPassword,
  setAccessToken,
  verifyEmailToken,
} from "./api";
import type { AuthProvidersResponse, AuthUser } from "./types";

type AuthStatus = "loading" | "anonymous" | "authenticated";
type EmailAuthMode = "login" | "register" | "forgot" | "reset";

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

function readEmailAction(): {
  verificationToken: string | null;
  resetToken: string | null;
} {
  const currentUrl = new URL(window.location.href);
  const verificationToken = currentUrl.searchParams.get("verification_token");
  const resetToken = currentUrl.searchParams.get("reset_token");
  if (!verificationToken && !resetToken) {
    return { verificationToken: null, resetToken: null };
  }

  currentUrl.searchParams.delete("verification_token");
  currentUrl.searchParams.delete("reset_token");
  window.history.replaceState({}, "", currentUrl);
  return { verificationToken, resetToken };
}

export default function AuthGate(): ReactNode {
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [providers, setProviders] = useState<AuthProvidersResponse | null>(null);
  const [user, setUser] = useState<AuthUser | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [emailAuthMode, setEmailAuthMode] = useState<EmailAuthMode>("login");
  const [thirdPartyOpen, setThirdPartyOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [resetToken, setResetToken] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmNewPassword, setConfirmNewPassword] = useState("");

  const loadProviders = useCallback(async (): Promise<void> => {
    setProviders(await getAuthProviders());
  }, []);

  useEffect(() => {
    let active = true;
    const initializeAuth = async (): Promise<void> => {
      const callback = readAuthCallback();
      const emailAction = readEmailAction();
      const token = callback.token ?? getAccessToken();
      if (callback.error) {
        setError("第三方登录未完成，请重新发起登录。");
      }
      if (emailAction.resetToken) {
        setResetToken(emailAction.resetToken);
        setEmailAuthMode("reset");
      }
      if (emailAction.verificationToken) {
        try {
          await verifyEmailToken(emailAction.verificationToken);
          setNotice("邮箱验证成功，请使用邮箱登录。");
          setEmailAuthMode("login");
        } catch (verifyError) {
          setError(describeAuthError(verifyError));
        }
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
      if (
        busy ||
        (emailAuthMode !== "reset" && !email.trim()) ||
        (emailAuthMode === "login" && password.length < 1) ||
        ((emailAuthMode === "register" || emailAuthMode === "reset") &&
          (emailAuthMode === "register" ? password : newPassword).length < 8)
      ) {
        return;
      }
      if (
        (emailAuthMode === "register" && password !== confirmPassword) ||
        (emailAuthMode === "reset" && newPassword !== confirmNewPassword)
      ) {
        setError("两次输入的密码不一致");
        return;
      }
      setBusy(true);
      setError("");
      setNotice("");
      try {
        if (emailAuthMode === "login") {
          const session = await loginWithEmail(email.trim(), password);
          setAccessToken(session.access_token);
          setUser(session.user);
          setStatus("authenticated");
        } else if (emailAuthMode === "register") {
          const registered = await registerWithEmail(
            email.trim(),
            password,
            confirmPassword,
            displayName.trim() || undefined,
          );
          setNotice(
            registered.verification_email_sent
              ? "注册成功，请查收邮箱并完成验证。"
              : "注册成功，但验证邮件发送失败，请稍后重试。",
          );
          setEmailAuthMode("login");
        } else if (emailAuthMode === "forgot") {
          await requestPasswordReset(email.trim());
          setNotice("如果邮箱已注册，重置链接已发送。");
          setEmailAuthMode("login");
        } else {
          await resetPassword(resetToken, newPassword, confirmNewPassword);
          setNotice("密码已重置，请使用新密码登录。");
          setResetToken("");
          setEmailAuthMode("login");
        }
        setPassword("");
        setConfirmPassword("");
        setNewPassword("");
        setConfirmNewPassword("");
      } catch (authError) {
        setError(describeAuthError(authError));
      } finally {
        setBusy(false);
      }
    },
    [
      busy,
      confirmNewPassword,
      confirmPassword,
      displayName,
      email,
      emailAuthMode,
      newPassword,
      password,
      resetToken,
    ],
  );

  const handleResendVerification = useCallback(async (): Promise<void> => {
    if (busy || !email.trim()) {
      return;
    }
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await requestEmailVerification(email.trim());
      setNotice("如果邮箱尚未验证，验证链接已发送。");
    } catch (verificationError) {
      setError(describeAuthError(verificationError));
    } finally {
      setBusy(false);
    }
  }, [busy, email]);

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
        {notice && <p className="auth-notice">{notice}</p>}
        {providers?.dev_login_available && (
          <button
            className="auth-dev-login"
            type="button"
            onClick={() => void handleDevLogin()}
            disabled={busy}
          >
            {busy ? "正在登录…" : "本地开发登录"}
          </button>
        )}
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
          </div>
        )}
        <div className="auth-divider">
          <span>
            {emailAuthMode === "reset" ? "设置新密码" : "或使用邮箱登录"}
          </span>
        </div>
        {providers?.email_login_enabled !== false && (
          <form className="auth-email-form" onSubmit={handleEmailAuth}>
            {(emailAuthMode === "login" || emailAuthMode === "register") && (
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
            )}
            {(emailAuthMode === "register" ||
              emailAuthMode === "forgot") && (
              <label>
                {emailAuthMode === "forgot" ? "注册邮箱" : "昵称（可选）"}
                <input
                  type={emailAuthMode === "forgot" ? "email" : "text"}
                  value={emailAuthMode === "forgot" ? email : displayName}
                  onChange={(event) =>
                    emailAuthMode === "forgot"
                      ? setEmail(event.target.value)
                      : setDisplayName(event.target.value)
                  }
                  maxLength={emailAuthMode === "forgot" ? 320 : 120}
                  autoComplete={emailAuthMode === "forgot" ? "email" : "nickname"}
                />
              </label>
            )}
            {emailAuthMode !== "forgot" && emailAuthMode !== "reset" && (
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
            )}
            {emailAuthMode !== "forgot" && emailAuthMode !== "reset" && (
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
            )}
            {emailAuthMode === "reset" && (
              <label>
                新密码
                <input
                  type="password"
                  value={newPassword}
                  onChange={(event) => setNewPassword(event.target.value)}
                  required
                  minLength={8}
                  maxLength={128}
                  autoComplete="new-password"
                />
              </label>
            )}
            {(emailAuthMode === "register" || emailAuthMode === "reset") && (
              <label>
                确认密码
                <input
                  type="password"
                  value={
                    emailAuthMode === "register" ? confirmPassword : confirmNewPassword
                  }
                  onChange={(event) =>
                    emailAuthMode === "register"
                      ? setConfirmPassword(event.target.value)
                      : setConfirmNewPassword(event.target.value)
                  }
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
                  : emailAuthMode === "register"
                    ? "创建账号"
                    : emailAuthMode === "forgot"
                      ? "发送重置链接"
                      : "重置密码"}
            </button>
            {emailAuthMode === "login" && (
              <button
                className="auth-text-button"
                type="button"
                onClick={() => void handleResendVerification()}
                disabled={busy || !email.trim()}
              >
                重新发送验证邮件
              </button>
            )}
            {(emailAuthMode === "forgot" || emailAuthMode === "reset") && (
              <button
                className="auth-text-button"
                type="button"
                onClick={() => setEmailAuthMode("login")}
                disabled={busy}
              >
                返回邮箱登录
              </button>
            )}
          </form>
        )}
        {emailAuthMode === "login" &&
          providers?.email_login_enabled !== false && (
            <button
              className="auth-text-button"
              type="button"
              onClick={() => setEmailAuthMode("forgot")}
              disabled={busy}
            >
              忘记密码？
            </button>
          )}
      </section>
    </main>
  );
}
