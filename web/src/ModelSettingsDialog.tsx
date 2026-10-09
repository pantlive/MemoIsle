import { useEffect, useState } from "react";

import {
  listModelSettings,
  resetModelSetting,
  saveModelSetting,
  testModelConnection,
} from "./api";
import type { ModelProvider, ModelSetting } from "./types";

interface ModelSettingsDialogProps {
  onClose: () => void;
}

interface ModelSettingForm {
  saved: ModelSetting;
  model: string;
  apiKey: string;
  baseUrl: string;
  enabled: boolean;
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
    message: saved.error ?? "",
  };
}

export default function ModelSettingsDialog({ onClose }: ModelSettingsDialogProps) {
  const [forms, setForms] = useState<ModelSettingForm[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [busy, setBusy] = useState<ModelProvider | null>(null);

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
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && busy === null) onClose();
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [busy, onClose]);

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
    setBusy(provider);
    updateForm(provider, { message: "" });
    const payload = {
      model: form.model.trim(),
      enabled: form.enabled,
      // 留空使用服务器默认地址，已保存的自定义地址会显示在输入框。
      base_url: form.baseUrl.trim() || null,
      // 空白表示保留已有密钥，前端不读取或持久化保存的明文。
      ...(form.apiKey.trim() ? { api_key: form.apiKey.trim() } : {}),
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
            <h2 id="model-settings-title">模型服务</h2>
          </div>
          <button
            type="button"
            className="icon-button"
            aria-label="关闭设置"
            onClick={onClose}
            disabled={busy !== null}
          >×</button>
        </div>
        <p className="model-settings-note">
          密钥按账号加密保存，填写后立即生效。已配置的密钥留空即可保留。
        </p>
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
        <p className="model-settings-note">
          连接测试会发送一条固定短文本，可能产生少量 API 费用。
        </p>
      </section>
    </div>
  );
}
