import {
  type FormEvent,
  useCallback,
  useEffect,
  useState,
  type ReactNode,
} from "react";

import App from "./App";
import BrandLogo from "./BrandLogo";
import Icon from "./Icon";
import {
  ApiError,
  androidDownloadUrl,
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
  requestVerificationCode,
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
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [verificationCode, setVerificationCode] = useState("");
  const [codeSending, setCodeSending] = useState(false);
  const [codeCooldown, setCodeCooldown] = useState(0);
  const [displayName, setDisplayName] = useState("");
  const [resetToken, setResetToken] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmNewPassword, setConfirmNewPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [showNewPassword, setShowNewPassword] = useState(false);

  const loadProviders = useCallback(async (): Promise<void> => {
    setProviders(await getAuthProviders());
  }, []);

  useEffect(() => {
    if (codeCooldown <= 0) {
      return;
    }
    const timer = window.setTimeout(() => {
      setCodeCooldown((current) => Math.max(0, current - 1));
    }, 1000);
    return () => window.clearTimeout(timer);
  }, [codeCooldown]);

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
      if (
        emailAuthMode === "register" &&
        !/^\d{6}$/.test(verificationCode.trim())
      ) {
        setError("请输入 6 位邮箱验证码");
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
          await registerWithEmail(
            email.trim(),
            password,
            confirmPassword,
            verificationCode.trim(),
            displayName.trim() || undefined,
          );
          setNotice("注册成功，请使用邮箱登录。");
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
        setVerificationCode("");
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
      verificationCode,
    ],
  );

  const handleSendVerificationCode = useCallback(async (): Promise<void> => {
    if (
      busy ||
      codeSending ||
      codeCooldown > 0 ||
      !email.trim()
    ) {
      return;
    }
    setCodeSending(true);
    setError("");
    setNotice("");
    try {
      await requestVerificationCode(email.trim());
      setCodeCooldown(60);
      setNotice("验证码已发送，请查收邮箱（10 分钟内有效）。");
    } catch (codeError) {
      setError(describeAuthError(codeError));
    } finally {
      setCodeSending(false);
    }
  }, [busy, codeCooldown, codeSending, email]);

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
        <section className="auth-card auth-loading">
          <div className="auth-brand" aria-label="MemoIsle">
            <BrandLogo className="auth-brand-mark" />
            <span className="auth-brand-name">MemoIsle</span>
          </div>
          <div className="auth-heading">
            <h1>MemoIsle</h1>
            <p>正在检查登录状态…</p>
          </div>
        </section>
      </main>
    );
  }

  if (status === "authenticated" && user) {
    return (
      <App
        authUser={user}
        onLogout={handleLogout}
        onPasswordChanged={() => {
          setNotice("密码已修改，请使用新密码重新登录。");
          setEmailAuthMode("login");
          setPassword("");
          void handleLogout();
        }}
      />
    );
  }

  const enabledProviders =
    providers?.providers.filter((provider) => provider.enabled) ?? [];
  const hasThirdPartyLogin = enabledProviders.length > 0;
  const isEmailMode = emailAuthMode === "login" || emailAuthMode === "register";
  const authHeading = {
    login: "欢迎回到 MemoIsle",
    register: "加入 MemoIsle",
    forgot: "找回你的资料库",
    reset: "设置新密码",
  }[emailAuthMode];
  const authSubheading = {
    login: "继续整理那些值得再次遇见的内容",
    register: "从今天开始，收好每一个值得再次遇见的瞬间",
    forgot: "输入注册邮箱，我们会发送密码重置链接",
    reset: "设置一个新的密码，继续回到你的私人小岛",
  }[emailAuthMode];
  const normalizedEmail = email.trim();
  const emailInvalid = normalizedEmail.length > 0 &&
    !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(normalizedEmail);
  const verificationCodeInvalid = emailAuthMode === "register" &&
    verificationCode.length > 0 &&
    !/^\d{6}$/.test(verificationCode);
  const passwordInvalid = emailAuthMode === "register" &&
    password.length > 0 &&
    password.length < 8;
  const newPasswordInvalid = emailAuthMode === "reset" &&
    newPassword.length > 0 &&
    newPassword.length < 8;
  const currentConfirmPassword = emailAuthMode === "register"
    ? confirmPassword
    : confirmNewPassword;
  const currentPassword = emailAuthMode === "register" ? password : newPassword;
  const confirmPasswordInvalid =
    (emailAuthMode === "register" || emailAuthMode === "reset") &&
    currentConfirmPassword.length > 0 &&
    currentConfirmPassword !== currentPassword;

  return (
    <main className="auth-screen">
      <section className={`auth-card auth-card-${emailAuthMode}`}>
        <div className="auth-brand" aria-label="MemoIsle">
          <BrandLogo className="auth-brand-mark" />
          <span className="auth-brand-name">MemoIsle</span>
        </div>
        <div className="auth-heading">
          <h1>{authHeading}</h1>
          <p>{authSubheading}</p>
        </div>
        {error && (
          <p className="auth-feedback auth-feedback-error" role="alert">
            <Icon name="health" size={16} />
            {error}
          </p>
        )}
        {notice && (
          <p className="auth-feedback auth-feedback-notice" role="status">
            <Icon name="check" size={16} />
            {notice}
          </p>
        )}
        {providers?.email_login_enabled !== false && (
          <form className="auth-email-form" onSubmit={handleEmailAuth}>
            {(emailAuthMode === "register" ||
              emailAuthMode === "forgot") && (
              <label
                className={`auth-field${
                  emailAuthMode === "forgot" && emailInvalid
                    ? " auth-field-invalid"
                    : ""
                }`}
              >
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
                  aria-invalid={emailAuthMode === "forgot" && emailInvalid}
                  autoComplete={emailAuthMode === "forgot" ? "email" : "nickname"}
                  placeholder={
                    emailAuthMode === "forgot" ? "输入注册邮箱" : "输入昵称（可选）"
                  }
                  required={emailAuthMode === "forgot"}
                />
              </label>
            )}
            {emailAuthMode !== "forgot" && emailAuthMode !== "reset" && (
              <label className={`auth-field${emailInvalid ? " auth-field-invalid" : ""}`}>
                电子邮箱
                <input
                  type="email"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  required
                  aria-invalid={emailInvalid}
                  autoComplete="email"
                  placeholder="输入邮箱地址"
                />
              </label>
            )}
            {emailInvalid && (
              <p className="auth-field-error">请输入有效的邮箱地址</p>
            )}
            {emailAuthMode === "register" && (
              <div className="auth-code-row">
                <label className={`auth-field${verificationCodeInvalid ? " auth-field-invalid" : ""}`}>
                  邮箱验证码
                  <input
                    type="text"
                    value={verificationCode}
                    onChange={(event) =>
                      setVerificationCode(event.target.value.replace(/\D/g, "").slice(0, 6))
                    }
                    inputMode="numeric"
                    pattern="[0-9]{6}"
                    maxLength={6}
                    required
                    aria-invalid={verificationCodeInvalid}
                    autoComplete="one-time-code"
                    placeholder="输入 6 位验证码"
                  />
                </label>
                <button
                  type="button"
                  onClick={() => void handleSendVerificationCode()}
                  disabled={
                    busy ||
                    codeSending ||
                    codeCooldown > 0 ||
                    !email.trim() ||
                    emailInvalid
                  }
                >
                  {codeSending
                    ? "发送中…"
                    : codeCooldown > 0
                      ? `${codeCooldown}s 后重发`
                      : "发送验证码"}
                </button>
              </div>
            )}
            {verificationCodeInvalid && (
              <p className="auth-field-error">请输入 6 位数字验证码</p>
            )}
            {emailAuthMode !== "forgot" && emailAuthMode !== "reset" && (
              <label className={`auth-field${passwordInvalid ? " auth-field-invalid" : ""}`}>
                密码
                <span className="auth-password-control">
                  <input
                    type={showPassword ? "text" : "password"}
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    required
                    aria-invalid={passwordInvalid}
                    minLength={emailAuthMode === "register" ? 8 : 1}
                    maxLength={128}
                    autoComplete={
                      emailAuthMode === "login" ? "current-password" : "new-password"
                    }
                    placeholder={
                      emailAuthMode === "register" ? "设置 8 位以上密码" : "输入密码"
                    }
                  />
                  <button
                    className="auth-password-toggle"
                    type="button"
                    onClick={() => setShowPassword((visible) => !visible)}
                    aria-label={showPassword ? "隐藏密码" : "显示密码"}
                  >
                    {showPassword ? "隐藏" : "显示"}
                  </button>
                </span>
              </label>
            )}
            {emailAuthMode === "register" && (
              <p className="auth-password-hint">
                至少 8 位，建议包含字母和数字
              </p>
            )}
            {passwordInvalid && (
              <p className="auth-field-error">密码至少需要 8 位</p>
            )}
            {emailAuthMode === "reset" && (
              <label className={`auth-field${newPasswordInvalid ? " auth-field-invalid" : ""}`}>
                新密码
                <span className="auth-password-control">
                  <input
                    type={showNewPassword ? "text" : "password"}
                    value={newPassword}
                    onChange={(event) => setNewPassword(event.target.value)}
                    required
                    aria-invalid={newPasswordInvalid}
                    minLength={8}
                    maxLength={128}
                    autoComplete="new-password"
                    placeholder="设置新密码"
                  />
                  <button
                    className="auth-password-toggle"
                    type="button"
                    onClick={() => setShowNewPassword((visible) => !visible)}
                    aria-label={showNewPassword ? "隐藏新密码" : "显示新密码"}
                  >
                    {showNewPassword ? "隐藏" : "显示"}
                  </button>
                </span>
              </label>
            )}
            {newPasswordInvalid && (
              <p className="auth-field-error">密码至少需要 8 位</p>
            )}
            {(emailAuthMode === "register" || emailAuthMode === "reset") && (
              <label className={`auth-field${confirmPasswordInvalid ? " auth-field-invalid" : ""}`}>
                确认密码
                <span className="auth-password-control">
                  <input
                    type={showConfirmPassword ? "text" : "password"}
                    value={
                      emailAuthMode === "register" ? confirmPassword : confirmNewPassword
                    }
                    onChange={(event) =>
                      emailAuthMode === "register"
                        ? setConfirmPassword(event.target.value)
                        : setConfirmNewPassword(event.target.value)
                    }
                    required
                    aria-invalid={confirmPasswordInvalid}
                    minLength={8}
                    maxLength={128}
                    autoComplete="new-password"
                    placeholder="再次输入密码"
                  />
                  <button
                    className="auth-password-toggle"
                    type="button"
                    onClick={() => setShowConfirmPassword((visible) => !visible)}
                    aria-label={showConfirmPassword ? "隐藏确认密码" : "显示确认密码"}
                  >
                    {showConfirmPassword ? "隐藏" : "显示"}
                  </button>
                </span>
              </label>
            )}
            {confirmPasswordInvalid && (
              <p className="auth-field-error">两次输入的密码需保持一致</p>
            )}
            <button type="submit" disabled={busy || codeSending}>
              {busy
                ? "正在处理…"
                : emailAuthMode === "login"
                  ? "登录"
                  : emailAuthMode === "register"
                    ? "创建账号"
                    : emailAuthMode === "forgot"
                      ? "发送重置链接"
                      : "重置密码"}
            </button>
          </form>
        )}
        {emailAuthMode === "login" &&
          providers?.email_login_enabled !== false && (
            <div className="auth-login-links">
              <button
                className="auth-text-button"
                type="button"
                onClick={() => void handleResendVerification()}
                disabled={busy || !email.trim()}
              >
                重新发送验证邮件
              </button>
              <button
                className="auth-text-button auth-forgot-link"
                type="button"
                onClick={() => setEmailAuthMode("forgot")}
                disabled={busy}
              >
                忘记密码？
              </button>
            </div>
          )}
        {emailAuthMode === "login" && providers?.dev_login_available && (
          <button
            className="auth-dev-login"
            type="button"
            onClick={() => void handleDevLogin()}
            disabled={busy}
          >
            {busy ? "正在进入…" : "本地开发登录"}
          </button>
        )}
        {isEmailMode && hasThirdPartyLogin && (
          <>
            <div className="auth-divider">
              <span>或使用其他方式</span>
            </div>
            <div className="auth-provider-grid">
              {enabledProviders.map((provider) => (
                <a
                  href={authAuthorizationUrl(
                    provider.provider,
                    window.location.origin + window.location.pathname,
                  )}
                  key={provider.provider}
                >
                  {provider.label}
                </a>
              ))}
            </div>
          </>
        )}
        {isEmailMode && (
          <div className="auth-mode-switch">
            {emailAuthMode === "login" ? (
              <>
                还没有账号？
                <button
                  type="button"
                  onClick={() => setEmailAuthMode("register")}
                  disabled={busy}
                >
                  立即注册
                </button>
              </>
            ) : (
              <>
                已有账号？
                <button
                  type="button"
                  onClick={() => setEmailAuthMode("login")}
                  disabled={busy}
                >
                  返回登录
                </button>
              </>
            )}
          </div>
        )}
        {(emailAuthMode === "forgot" || emailAuthMode === "reset") && (
          <button
            className="auth-text-button auth-back-link"
            type="button"
            onClick={() => setEmailAuthMode("login")}
            disabled={busy}
          >
            返回邮箱登录
          </button>
        )}
        {emailAuthMode === "register" && (
          <p className="auth-privacy-note">
            注册即表示你同意我们只为同步服务保存必要信息
          </p>
        )}
        <a
          className="auth-android-download"
          href={androidDownloadUrl()}
          download="MemoIsle-android.apk"
        ><Icon name="download" size={16} /> 下载安卓端（APK）</a>
        {isEmailMode && (
          <div className="auth-trust-note">
            <span className="auth-trust-icon" aria-hidden="true"><Icon name="swap" size={14} /></span>
            <span>你的资料只属于你 · Web 与 Android 自动同步</span>
          </div>
        )}
      </section>
    </main>
  );
}
