import { useEffect, useState } from "react";

import {
  androidDownloadUrl,
  changePassword,
  getBrowserHistorySettings,
  listModelSettings,
  resetModelSetting,
  saveModelSetting,
  testModelConnection,
  updateBrowserHistorySettings,
} from "./api";
import type { ModelProvider, ModelSetting } from "./types";

interface ModelSettingsDialogProps {
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
    purpose: "根据你的整理要求生成分类模板，预览后可编辑并加入模板。",
    addressHint: "中转服务需兼容 Chat Completions 和 JSON 输出。可填写基础地址或完整 /chat/completions 地址。",
  },
  jev: {
    name: "Jev · TypeSafe AI",
    purpose: "为新收藏的网页选择已有分类；图片继续使用现有 OCR 与视觉标签流程。",
    addressHint: "中转服务需兼容 TypeSafe 接口。可填写基础地址或完整 /systemone 地址。",
  },
};

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
  onClose,
  accountEmail,
  onPasswordChanged,
}: ModelSettingsDialogProps) {
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

  async function handlePasswordChange(): Promise<void> {
    if (passwordBusy) return;
    setPasswordError("");
    if (newPassword !== confirmPassword) {
      setPasswordError("两次输入的新密码不一致");
      return;
    }
    if (newPassword === currentPassword) {
      setPasswordError("新密码不能与当前密码相同");
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
      setPasswordError(error instanceof Error ? error.message : "修改密码失败");
    } finally {
      setPasswordBusy(false);
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
          setLoadError(error instanceof Error ? error.message : "读取模型设置失败");
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
          ? "已开启。浏览历史面板可以按 90 天、一年或全部时间搜索。"
          : "已关闭。浏览历史面板只搜索最近 30 天。",
      );
    } catch (error) {
      setHistoryMessage(
        error instanceof Error ? error.message : "保存浏览历史设置失败",
      );
    } finally {
      setHistoryBusy(false);
    }
  }

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && busy === null && !passwordBusy) onClose();
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [busy, onClose, passwordBusy]);

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
      updateForm(provider, { message: "请填写模型名称" });
      return;
    }
    const thresholdText = form.minConfidence.trim();
    const threshold = thresholdText === "" ? null : Number(thresholdText);
    if (threshold !== null && (!Number.isFinite(threshold) || threshold < 0 || threshold > 1)) {
      updateForm(provider, { message: "置信度阈值需要是 0 到 1 之间的小数" });
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
        updateForm(provider, { message: `${result.message}。测试不会保存修改。` });
      } else {
        const saved = action === "save"
          ? await saveModelSetting(provider, payload)
          : await resetModelSetting(provider);
        updateForm(provider, {
          ...createForm(saved),
          message: saved.error ?? (action === "reset"
            ? "已移除账号配置，恢复服务器默认设置。"
            : "已保存，后续请求立即使用新设置。"),
        });
      }
    } catch (error) {
      updateForm(provider, { message: error instanceof Error ? error.message : "操作失败" });
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="dialog-backdrop" role="presentation">
      <section
        className="cloud-dialog model-settings-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="model-settings-title"
      >
        <div className="dialog-header">
          <div>
            <span className="type-label">设置</span>
            <h2 id="model-settings-title">设置</h2>
          </div>
          <button
            type="button"
            className="icon-button"
            aria-label="关闭设置"
            onClick={onClose}
            disabled={busy !== null || passwordBusy}
          >×</button>
        </div>
        <section className="settings-section" aria-labelledby="settings-password-title">
          <div className="settings-section-heading">
            <div>
              <h3 id="settings-password-title">修改登录密码</h3>
              {accountEmail && <p>{accountEmail}</p>}
              <p>修改后所有设备需要重新登录。密码库使用独立的主密码。</p>
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
              <span>当前密码</span>
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
              <span>新密码</span>
              <input
                type="password"
                autoComplete="new-password"
                value={newPassword}
                name="new_password"
                minLength={8}
                maxLength={128}
                placeholder="设置 8 位以上的新密码"
                required
                disabled={passwordBusy}
                onChange={(event) => setNewPassword(event.target.value)}
              />
            </label>
            <label>
              <span>确认新密码</span>
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
              <button type="submit" className="primary-button" disabled={passwordBusy}>
                {passwordBusy ? "正在修改…" : "修改密码并重新登录"}
              </button>
            </div>
          </form>
        </section>
        <section className="settings-section" aria-labelledby="settings-android-title">
          <div className="settings-section-heading">
            <div>
              <h3 id="settings-android-title">安卓客户端</h3>
              <p>在手机上安装 MemoIsle，使用同一账号同步收藏、录音和密码库。</p>
            </div>
          </div>
          <a
            className="secondary-button android-download-link"
            href={androidDownloadUrl()}
            download="MemoIsle-android.apk"
          >↓ 下载安卓端（APK）</a>
        </section>
        <section className="settings-section" aria-labelledby="settings-history-title">
          <div className="settings-section-heading">
            <div>
              <h3 id="settings-history-title">浏览历史</h3>
              <p>
                历史记录会一直保存在你的资料库里，但默认只在「浏览历史」里搜索最近 30 天。
                打开下面的开关后，可以按 90 天、一年或全部时间检索更早的记录。
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
            <span>允许搜索更久的历史记录</span>
          </label>
          {historyBusy && <p role="status">正在保存…</p>}
          {historyMessage && (
            <p className="model-settings-message" role="status">{historyMessage}</p>
          )}
        </section>
        <section className="settings-section" aria-labelledby="settings-models-title">
          <div className="settings-section-heading">
            <div>
              <h3 id="settings-models-title">模型服务</h3>
              <p>密钥按账号加密保存，填写后立即生效。已配置的密钥留空即可保留。</p>
            </div>
          </div>
          {loading && <p role="status">正在读取设置…</p>}
          {loadError && <p role="alert">{loadError}</p>}
          <div className="model-settings-list">
            {forms.map((form) => {
              const provider = form.saved.provider;
              const details = providerDetails[provider];
              const status = form.saved.error
                ? "需要重新填写密钥"
                : !form.saved.enabled
                  ? "已停用"
                  : form.saved.has_api_key ? "密钥已配置" : "尚未配置密钥";
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
                    <span>请求地址（可选）</span>
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
                    留空使用默认地址。更换服务时，请填写对应的 API Key。
                    {details.addressHint}
                  </p>
                  <label>
                    <span>模型名称</span>
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
                        ? `已配置 ${form.saved.key_hint}，留空保留`
                        : "粘贴该服务的 API Key"}
                      onChange={(event) => updateForm(provider, {
                        apiKey: event.target.value, message: "",
                      })}
                    />
                  </label>
                  {form.saved.credential_source === "environment" && (
                    <p className="cloud-dialog-hint">
                      当前使用服务器密钥；填写后优先使用你保存的密钥。
                    </p>
                  )}
                  <label>
                    <span>自动分类置信度阈值</span>
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
                    低于这个置信度的判定会进「分类确认中心」，不会直接改分类。
                    填 0 到 1 之间的小数，留空恢复默认
                    {String(form.saved.default_min_confidence)}。调低会多自动分类、少人工确认。
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
                    <span>启用此服务</span>
                  </label>
                  <div className="model-settings-actions">
                    <button type="submit" className="primary-button" disabled={busy !== null}>
                      保存设置
                    </button>
                    <button
                      type="button"
                      className="secondary-button"
                      disabled={busy !== null}
                      onClick={() => void handleAction(form, "test")}
                    >测试连接</button>
                    {form.saved.has_custom_settings && (
                      <button
                        type="button"
                        className="secondary-button"
                        disabled={busy !== null}
                        onClick={() => void handleAction(form, "reset")}
                      >移除账号配置</button>
                    )}
                  </div>
                  {busy === provider && <p role="status">正在处理…</p>}
                  {form.message && <p className="model-settings-message" role="status">{form.message}</p>}
                </form>
              );
            })}
          </div>
        </section>
        <p className="model-settings-note">
          连接测试会发送一条固定短文本，可能产生少量 API 费用。
        </p>
      </section>
    </div>
  );
}
