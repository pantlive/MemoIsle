import { useEffect, useState } from "react";
import Icon from "./Icon";
import { themeOptions, type ThemePreference } from "./theme";

import {
  androidDownloadUrl,
  changePassword,
  createInvitation,
  getBrowserHistorySettings,
  getInvitations,
  listModelSettings,
  resetModelSetting,
  saveModelSetting,
  testModelConnection,
  updateBrowserHistorySettings,
} from "./api";
import type { InvitationStatus, ModelProvider, ModelSetting } from "./types";
import { languageOptions, type LanguagePreference, t } from "./i18n";
import { useI18n } from "./I18nProvider";

interface ModelSettingsDialogProps {
  themePreference: ThemePreference;
  onThemeChange: (pref: ThemePreference) => void;
  languagePreference: LanguagePreference;
  onLanguageChange: (pref: LanguagePreference) => void;
  onClose: () => void;
  accountEmail: string | null;
  onPasswordChanged: () => void;
}

interface ModelSettingForm {
  saved: ModelSetting;
  model: string;
  apiKey: string;
  baseUrl: string;
  enabled: boolean;
  /** 以文本保存，便于校验；空表示恢复默认阈值。 */
  minConfidence: string;
  message: string;
}

const providerDetails: Record<ModelProvider, {
  name: string;
  purpose: string;
  addressHint: string;
}> = {
  deepseek: {
    name: "DeepSeek",
    get purpose() { return t("根据你的整理要求生成分类模板，预览后可编辑并加入模板。"); },
    get addressHint() { return t("中转服务需兼容 Chat Completions 和 JSON 输出。可填写基础地址或完整 /chat/completions 地址。"); },
  },
  jev: {
    name: "Jev · TypeSafe AI",
    get purpose() { return t("为新收藏的网页选择已有分类；图片继续使用现有 OCR 与视觉标签流程。"); },
    get addressHint() { return t("中转服务需兼容 TypeSafe 接口。可填写基础地址或完整 /systemone 地址。"); },
  },
};

function inviteRegistrationLink(code: string): string {
  const url = new URL(window.location.origin + window.location.pathname);
  url.searchParams.set("invite_code", code);
  return url.toString();
}

function createForm(saved: ModelSetting): ModelSettingForm {
  return {
    saved,
    model: saved.model,
    apiKey: "",
    baseUrl: saved.custom_base_url ?? "",
    enabled: saved.enabled,
    minConfidence: String(saved.min_confidence ?? saved.default_min_confidence),
    message: saved.error ?? "",
  };
}

export default function ModelSettingsDialog({
  themePreference,
  onThemeChange,
  languagePreference,
  onLanguageChange,
  onClose,
  accountEmail,
  onPasswordChanged,
}: ModelSettingsDialogProps) {
  const { t } = useI18n();
  const [forms, setForms] = useState<ModelSettingForm[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [busy, setBusy] = useState<ModelProvider | null>(null);
  // 浏览历史默认只搜索最近 30 天，打开后可按更长窗口或全部时间检索。
  const [historyExtended, setHistoryExtended] = useState(false);
  const [historyBusy, setHistoryBusy] = useState(false);
  const [historyMessage, setHistoryMessage] = useState("");
  // 登录密码只保存在当前表单内存里，提交成功后清空并退出登录。
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [passwordBusy, setPasswordBusy] = useState(false);
  const [passwordError, setPasswordError] = useState("");
  const [inviteStatus, setInviteStatus] = useState<InvitationStatus | null>(null);
  const [issuedInviteCode, setIssuedInviteCode] = useState("");
  const [inviteBusy, setInviteBusy] = useState(false);
  const [inviteError, setInviteError] = useState("");
  const [inviteNotice, setInviteNotice] = useState("");

  async function handlePasswordChange(): Promise<void> {
    if (passwordBusy) return;
    setPasswordError("");
    if (newPassword !== confirmPassword) {
      setPasswordError(t("两次输入的新密码不一致"));
      return;
    }
    if (newPassword === currentPassword) {
      setPasswordError(t("新密码不能与当前密码相同"));
      return;
    }
    setPasswordBusy(true);
    try {
      await changePassword(currentPassword, newPassword, confirmPassword);
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      onPasswordChanged();
    } catch (error) {
      setPasswordError(error instanceof Error ? error.message : t("修改密码失败"));
    } finally {
      setPasswordBusy(false);
    }
  }

  useEffect(() => {
    let cancelled = false;
    void getInvitations()
      .then((status) => {
        if (!cancelled) setInviteStatus(status);
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setInviteError(error instanceof Error ? error.message : t("读取邀请状态失败"));
        }
      });
    return () => { cancelled = true; };
  }, []);

  async function handleCreateInvitation(): Promise<void> {
    if (inviteBusy || inviteStatus?.remaining !== 1) return;
    setInviteBusy(true);
    setInviteError("");
    setInviteNotice("");
    try {
      const created = await createInvitation();
      setIssuedInviteCode(created.code);
      setInviteStatus({
        remaining: 0,
        created_at: created.created_at,
        used_at: null,
        used_by_label: null,
      });
      setInviteNotice(t("只显示这一次"));
    } catch (error) {
      setInviteError(error instanceof Error ? error.message : t("生成邀请码失败"));
    } finally {
      setInviteBusy(false);
    }
  }

  async function copyInviteText(value: string, success: string): Promise<void> {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(value);
      } else {
        const area = document.createElement("textarea");
        area.value = value;
        document.body.appendChild(area);
        area.select();
        document.execCommand("copy");
        area.remove();
      }
      setInviteNotice(success);
      setInviteError("");
    } catch {
      setInviteError(t("复制失败，请手动选择邀请码"));
    }
  }

  useEffect(() => {
    let cancelled = false;
    void listModelSettings()
      .then((settings) => {
        if (!cancelled) setForms(settings.map(createForm));
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setLoadError(error instanceof Error ? error.message : t("读取模型设置失败"));
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    let cancelled = false;
    void getBrowserHistorySettings()
      .then((settings) => {
        if (!cancelled) setHistoryExtended(settings.extended_search_enabled);
      })
      .catch(() => {
        // 读取失败时保持关闭状态，不影响模型服务的设置。
      });
    return () => { cancelled = true; };
  }, []);

  async function toggleHistoryExtended(enabled: boolean): Promise<void> {
    if (historyBusy) return;
    setHistoryBusy(true);
    setHistoryMessage("");
    try {
      const saved = await updateBrowserHistorySettings({
        extended_search_enabled: enabled,
      });
      setHistoryExtended(saved.extended_search_enabled);
      setHistoryMessage(
        saved.extended_search_enabled
          ? t("已开启。浏览历史面板可以按 90 天、一年或全部时间搜索。")
          : t("已关闭。浏览历史面板只搜索最近 30 天。"),
      );
    } catch (error) {
      setHistoryMessage(
        error instanceof Error ? error.message : t("保存浏览历史设置失败"),
      );
    } finally {
      setHistoryBusy(false);
    }
  }

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && busy === null && !passwordBusy && !inviteBusy) {
        onClose();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [busy, inviteBusy, onClose, passwordBusy]);

  function updateForm(provider: ModelProvider, patch: Partial<ModelSettingForm>): void {
    setForms((current) => current.map((form) =>
      form.saved.provider === provider ? { ...form, ...patch } : form,
    ));
  }

  async function handleAction(
    form: ModelSettingForm,
    action: "save" | "test" | "reset",
  ): Promise<void> {
    if (busy !== null) return;
    const provider = form.saved.provider;
    if (action !== "reset" && !form.model.trim()) {
      updateForm(provider, { message: t("请填写模型名称") });
      return;
    }
    const thresholdText = form.minConfidence.trim();
    const threshold = thresholdText === "" ? null : Number(thresholdText);
    if (threshold !== null && (!Number.isFinite(threshold) || threshold < 0 || threshold > 1)) {
      updateForm(provider, { message: t("置信度阈值需要是 0 到 1 之间的小数") });
      return;
    }
    setBusy(provider);
    updateForm(provider, { message: "" });
    const payload = {
      model: form.model.trim(),
      enabled: form.enabled,
      // 留空使用服务器默认地址，已保存的自定义地址会显示在输入框。
      base_url: form.baseUrl.trim() || null,
      // 空白表示保留已有密钥，前端不读取或持久化保存的明文。
      ...(form.apiKey.trim() ? { api_key: form.apiKey.trim() } : {}),
      // 空值恢复服务器默认阈值。
      min_confidence: threshold,
    };
    try {
      if (action === "test") {
        const result = await testModelConnection(provider, payload);
        updateForm(provider, { message: t("{message}。测试不会保存修改。", { message: result.message }) });
      } else {
        const saved = action === "save"
          ? await saveModelSetting(provider, payload)
          : await resetModelSetting(provider);
        updateForm(provider, {
          ...createForm(saved),
          message: saved.error ?? (action === "reset"
            ? t("已移除账号配置，恢复服务器默认设置。")
            : t("已保存，后续请求立即使用新设置。")),
        });
      }
    } catch (error) {
      updateForm(provider, { message: error instanceof Error ? error.message : t("操作失败") });
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="dialog-backdrop model-settings-backdrop" role="presentation">
      <section
        className="cloud-dialog model-settings-dialog dialog-shell"
        role="dialog"
        aria-modal="true"
        aria-labelledby="model-settings-title"
      >
        <div className="dialog-header">
          <div>
            <span className="type-label"><Icon name="settings" size={16} />{t(" 账户与偏好")}</span>
            <h2 id="model-settings-title">{t("设置")}</h2>
          </div>
          <button
            autoFocus
            type="button"
            className="icon-button"
            aria-label={t("关闭设置")}
            onClick={onClose}
            disabled={busy !== null || passwordBusy || inviteBusy}
          ><Icon name="close" size={16} /></button>
        </div>
        <div className="dialog-body">
          <section className="settings-section" aria-labelledby="settings-appearance-title">
            <div className="settings-section-heading">
              <div>
                <h3 id="settings-appearance-title">{t("外观")}</h3>
                <p>{t("选择页面主题，偏好会保存在当前浏览器。")}</p>
              </div>
            </div>
            <div className="view-switch theme-options" role="group" aria-label={t("主题偏好")}>
              {themeOptions.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  className={themePreference === option.value ? "active" : ""}
                  aria-pressed={themePreference === option.value}
                  onClick={() => onThemeChange(option.value)}
                >{option.label}</button>
              ))}
            </div>
          </section>
          <section className="settings-section" aria-labelledby="settings-language-title">
            <div className="settings-section-heading">
              <div>
                <h3 id="settings-language-title">{t("语言")}</h3>
                <p>{t("跟随系统时，系统语言为中文则显示中文，否则显示英文。偏好会保存在当前浏览器。")}</p>
              </div>
            </div>
            <div className="view-switch theme-options" role="group" aria-label={t("界面语言")}>
              {languageOptions.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  className={languagePreference === option.value ? "active" : ""}
                  aria-pressed={languagePreference === option.value}
                  onClick={() => onLanguageChange(option.value)}
                  lang={option.value === "en" ? "en" : option.value === "zh" ? "zh-CN" : undefined}
                >{option.label}</button>
              ))}
            </div>
          </section>
          <section className="settings-section" aria-labelledby="settings-password-title">
            <div className="settings-section-heading">
              <div>
                <h3 id="settings-password-title">{t("修改登录密码")}</h3>
                {accountEmail && <p>{accountEmail}</p>}
                <p>{t("修改后所有设备需要重新登录。密码库使用独立的主密码。")}</p>
              </div>
            </div>
            <form
              className="cloud-bind-form"
              onSubmit={(event) => {
                event.preventDefault();
                void handlePasswordChange();
              }}
            >
              <label>
                <span>{t("当前密码")}</span>
                <input
                  type="password"
                  autoComplete="current-password"
                  name="current_password"
                  value={currentPassword}
                  maxLength={128}
                  required
                  disabled={passwordBusy}
                  onChange={(event) => setCurrentPassword(event.target.value)}
                />
              </label>
              <label>
                <span>{t("新密码")}</span>
                <input
                  type="password"
                  autoComplete="new-password"
                  value={newPassword}
                  name="new_password"
                  minLength={8}
                  maxLength={128}
                  placeholder={t("设置 8 位以上的新密码")}
                  required
                  disabled={passwordBusy}
                  onChange={(event) => setNewPassword(event.target.value)}
                />
              </label>
              <label>
                <span>{t("确认新密码")}</span>
                <input
                  type="password"
                  autoComplete="new-password"
                  value={confirmPassword}
                  name="confirm_password"
                  minLength={8}
                  maxLength={128}
                  required
                  disabled={passwordBusy}
                  onChange={(event) => setConfirmPassword(event.target.value)}
                />
              </label>
              {passwordError && <p className="auth-field-error" role="alert">{passwordError}</p>}
              <div className="model-settings-actions">
                <button type="submit" className="primary" disabled={passwordBusy}>
                  {passwordBusy ? t("正在修改…") : t("修改密码并重新登录")}
                </button>
              </div>
            </form>
          </section>
          <section className="settings-section" aria-labelledby="settings-invite-title">
            <div className="settings-section-heading">
              <div>
                <h3 id="settings-invite-title">{t("邀请好友")}</h3>
                <p>{t("每个账号只能生成 1 个邀请码。用过和还没用的都占用这一次。")}</p>
              </div>
            </div>
            {inviteStatus == null && !inviteError && <p className="invite-friend-note">{t("正在读取邀请次数…")}</p>}
            {inviteStatus != null && (
              <p className="invite-friend-note">{t("剩余邀请次数：{remaining}", { remaining: inviteStatus.remaining })}</p>
            )}
            {inviteStatus != null && inviteStatus.remaining === 0 && !issuedInviteCode && (
              <p className="invite-friend-note">
                {inviteStatus.used_at
                  ? t("邀请码已使用{value}。", { value: inviteStatus.used_by_label ? t("，注册人：{used_by_label}", { used_by_label: inviteStatus.used_by_label }) : "" })
                  : t("邀请码已生成，还没有人使用。明文不会再次显示。")}
              </p>
            )}
            {issuedInviteCode && (
              <div className="invite-friend-code cloud-bind-form">
                <label>
                  <span>{t("邀请码")}</span>
                  <input readOnly value={issuedInviteCode} spellCheck={false} />
                </label>
                <p className="invite-friend-link">{inviteRegistrationLink(issuedInviteCode)}</p>
                <p className="invite-friend-note">{t("只显示这一次。把注册链接发给朋友，打开后会自动填入邀请码。")}</p>
                <div className="model-settings-actions">
                  <button
                    type="button"
                    onClick={() => void copyInviteText(issuedInviteCode, t("邀请码已复制"))}
                  >{t("复制邀请码")}</button>
                  <button
                    type="button"
                    onClick={() => void copyInviteText(
                      inviteRegistrationLink(issuedInviteCode),
                      t("注册链接已复制"),
                    )}
                  >{t("复制注册链接")}</button>
                </div>
              </div>
            )}
            {inviteError && <p className="auth-field-error" role="alert">{inviteError}</p>}
            {inviteNotice && <p className="invite-friend-note" role="status">{inviteNotice}</p>}
            <div className="model-settings-actions">
              <button
                type="button"
                className="primary"
                disabled={inviteBusy || inviteStatus?.remaining !== 1}
                onClick={() => void handleCreateInvitation()}
              >
                {inviteBusy ? t("正在生成…") : t("生成邀请码")}
              </button>
            </div>
          </section>
          <section className="settings-section" aria-labelledby="settings-android-title">
            <div className="settings-section-heading">
              <div>
                <h3 id="settings-android-title">{t("安卓客户端")}</h3>
                <p>{t("在手机上安装 MemoIsle，使用同一账号同步收藏、录音和密码库。")}</p>
              </div>
            </div>
            <a
              className="secondary-button android-download-link"
              href={androidDownloadUrl()}
              download="MemoIsle-android.apk"
            ><Icon name="download" size={16} />{t(" 下载安卓端（APK）")}</a>
          </section>
          <section className="settings-section" aria-labelledby="settings-history-title">
            <div className="settings-section-heading">
              <div>
                <h3 id="settings-history-title">{t("浏览历史")}</h3>
                <p>
                  {t("历史记录会一直保存在你的资料库里，但默认只在「浏览历史」里搜索最近 30 天。 打开下面的开关后，可以按 90 天、一年或全部时间检索更早的记录。")}
                </p>
              </div>
            </div>
            <label className="model-settings-enable">
              <input
                type="checkbox"
                checked={historyExtended}
                disabled={historyBusy}
                onChange={(event) => void toggleHistoryExtended(event.target.checked)}
              />
              <span>{t("允许搜索更久的历史记录")}</span>
            </label>
            {historyBusy && <p role="status">{t("正在保存…")}</p>}
            {historyMessage && (
              <p className="model-settings-message" role="status">{historyMessage}</p>
            )}
          </section>
          <section className="settings-section" aria-labelledby="settings-models-title">
            <div className="settings-section-heading">
              <div>
                <h3 id="settings-models-title">{t("模型服务")}</h3>
                <p>{t("密钥按账号加密保存，填写后立即生效。已配置的密钥留空即可保留。")}</p>
              </div>
            </div>
            {loading && <p role="status">{t("正在读取设置…")}</p>}
            {loadError && <p role="alert">{loadError}</p>}
            <div className="model-settings-list">
              {forms.map((form) => {
                const provider = form.saved.provider;
                const details = providerDetails[provider];
                const status = form.saved.error
                  ? t("需要重新填写密钥")
                  : !form.saved.enabled
                    ? t("已停用")
                    : form.saved.has_api_key ? t("密钥已配置") : t("尚未配置密钥");
                return (
                  <form
                    key={provider}
                    className="cloud-bind-form model-settings-card"
                    onSubmit={(event) => {
                      event.preventDefault();
                      void handleAction(form, "save");
                    }}
                  >
                    <div className="model-settings-card-header">
                      <h3>{details.name}</h3>
                      <span>{status}</span>
                    </div>
                    <p className="cloud-dialog-hint">{details.purpose}</p>
                    <label>
                      <span>{t("请求地址（可选）")}</span>
                      <input
                        type="url"
                        value={form.baseUrl}
                        placeholder={form.saved.default_base_url}
                        maxLength={2048}
                        autoComplete="off"
                        spellCheck={false}
                        disabled={busy !== null}
                        onChange={(event) => updateForm(provider, {
                          baseUrl: event.target.value, message: "",
                        })}
                      />
                    </label>
                    <p className="cloud-dialog-hint">
                      {t("留空使用默认地址。更换服务时，请填写对应的 API Key。 {addressHint}", { addressHint: details.addressHint })}
                    </p>
                    <label>
                      <span>{t("模型名称")}</span>
                      <input
                        value={form.model}
                        maxLength={200}
                        autoComplete="off"
                        required
                        disabled={busy !== null}
                        onChange={(event) => updateForm(provider, {
                          model: event.target.value, message: "",
                        })}
                      />
                    </label>
                    <label>
                      <span>API Key</span>
                      <input
                        type="password"
                        value={form.apiKey}
                        autoComplete="new-password"
                        spellCheck={false}
                        maxLength={4000}
                        disabled={busy !== null}
                        placeholder={form.saved.has_api_key
                          ? t("已配置 {key_hint}，留空保留", { key_hint: form.saved.key_hint })
                          : t("粘贴该服务的 API Key")}
                        onChange={(event) => updateForm(provider, {
                          apiKey: event.target.value, message: "",
                        })}
                      />
                    </label>
                    {form.saved.credential_source === "environment" && (
                      <p className="cloud-dialog-hint">
                        {t("当前使用服务器密钥；填写后优先使用你保存的密钥。")}
                      </p>
                    )}
                    <label>
                      <span>{t("自动分类置信度阈值")}</span>
                      <input
                        inputMode="decimal"
                        value={form.minConfidence}
                        placeholder={String(form.saved.default_min_confidence)}
                        disabled={busy !== null}
                        onChange={(event) => updateForm(provider, {
                          minConfidence: event.target.value, message: "",
                        })}
                      />
                    </label>
                    <p className="cloud-dialog-hint">
                      {t("低于这个置信度的判定会进「分类确认中心」，不会直接改分类。 填 0 到 1 之间的小数，留空恢复默认 {value}。调低会多自动分类、少人工确认。", { value: String(form.saved.default_min_confidence) })}
                    </p>
                    <label className="model-settings-enable">
                      <input
                        type="checkbox"
                        checked={form.enabled}
                        disabled={busy !== null}
                        onChange={(event) => updateForm(provider, {
                          enabled: event.target.checked, message: "",
                        })}
                      />
                      <span>{t("启用此服务")}</span>
                    </label>
                    <div className="model-settings-actions">
                      <button type="submit" className="primary" disabled={busy !== null}>
                        {t("保存设置")}
                      </button>
                      <button
                        type="button"
                        className="secondary-button"
                        disabled={busy !== null}
                        onClick={() => void handleAction(form, "test")}
                      >{t("测试连接")}</button>
                      {form.saved.has_custom_settings && (
                        <button
                          type="button"
                          className="danger-button"
                          disabled={busy !== null}
                          onClick={() => void handleAction(form, "reset")}
                        >{t("移除账号配置")}</button>
                      )}
                    </div>
                    {busy === provider && <p role="status">{t("正在处理…")}</p>}
                    {form.message && <p className="model-settings-message" role="status">{form.message}</p>}
                  </form>
                );
              })}
            </div>
          </section>
          <p className="model-settings-note">
            {t("连接测试会发送一条固定短文本，可能产生少量 API 费用。")}
          </p>
        </div>
      </section>
    </div>
  );
}
