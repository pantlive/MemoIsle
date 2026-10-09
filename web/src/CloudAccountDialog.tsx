import { useCallback, useEffect, useState } from "react";

import {
  createCloudAccount,
  deleteCloudAccount,
  listCloudAccounts,
  verifyCloudAccount,
} from "./api";
import type { CloudAccount, CloudProvider } from "./types";

interface CloudAccountDialogProps {
  onClose: () => void;
  onChanged: () => void;
}

const providerLabels: Record<CloudProvider, string> = {
  aliyun: "阿里云盘",
  baidu: "百度网盘",
};

const credentialPlaceholder: Record<CloudProvider, string> = {
  aliyun:
    '{"refresh_token": "...", "client_id": "...", "client_secret": "..."}',
  baidu: '{"bduss": "...", "stoken": "...", "access_token": "..."}',
};

const credentialHint: Record<CloudProvider, string> = {
  aliyun:
    "阿里云盘使用官方 OpenAPI：请在阿里云盘开放平台注册应用，粘贴 refresh_token 与配套的 client_id / client_secret，或一个尚未过期的 access_token。",
  baidu:
    "百度网盘走浏览器登录态：粘贴 BDUSS（可带 STOKEN）。上传还需要开放平台应用的 access_token，只给 cookie 时上传会被拒绝，目录与分享转存不受影响。",
};

const dateFormatter = new Intl.DateTimeFormat("zh-CN", {
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

function formatTime(value: string | null): string {
  return value ? dateFormatter.format(new Date(value)) : "尚未校验";
}

export default function CloudAccountDialog({
  onClose,
  onChanged,
}: CloudAccountDialogProps) {
  const [accounts, setAccounts] = useState<CloudAccount[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [provider, setProvider] = useState<CloudProvider>("aliyun");
  const [credential, setCredential] = useState("");
  const [defaultFolder, setDefaultFolder] = useState("/MemoIsle/电子书");

  const loadAccounts = useCallback(async () => {
    setLoading(true);
    try {
      setAccounts(await listCloudAccounts());
      setMessage("");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "读取云盘绑定失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadAccounts();
  }, [loadAccounts]);

  const handleBind = async () => {
    if (busy) {
      return;
    }
    if (!credential.trim()) {
      setMessage("请先粘贴云盘登录态");
      return;
    }
    setBusy(true);
    try {
      await createCloudAccount({
        provider,
        credential: credential.trim(),
        default_folder: defaultFolder.trim() || null,
      });
      setCredential("");
      setMessage("绑定成功，凭据已加密保存");
      await loadAccounts();
      onChanged();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "绑定失败");
    } finally {
      setBusy(false);
    }
  };

  const handleVerify = async (accountId: string) => {
    if (busy) {
      return;
    }
    setBusy(true);
    try {
      const updated = await verifyCloudAccount(accountId);
      setMessage(
        updated.status === "active"
          ? "凭据可用"
          : updated.last_error || "凭据已失效，请重新绑定",
      );
      await loadAccounts();
      onChanged();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "校验失败");
    } finally {
      setBusy(false);
    }
  };

  const handleDelete = async (accountId: string) => {
    if (busy) {
      return;
    }
    setBusy(true);
    try {
      await deleteCloudAccount(accountId);
      setMessage("已解绑");
      await loadAccounts();
      onChanged();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "解绑失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="dialog-backdrop" role="presentation">
      <section
        className="cloud-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="cloud-dialog-title"
      >
        <div className="dialog-header">
          <div>
            <span className="type-label">电子书转存</span>
            <h2 id="cloud-dialog-title">云盘绑定</h2>
          </div>
          <button
            type="button"
            className="icon-button"
            aria-label="关闭云盘绑定"
            onClick={onClose}
          >×</button>
        </div>

        <p className="cloud-dialog-note">
          电子书收藏需要先把文件存进你自己的云盘。请在浏览器登录阿里云盘后，
          从开发者工具复制登录态（refresh_token，或包含 refresh_token 的
          cookie）粘贴到下面。凭据会加密保存，页面只显示末尾四位。
        </p>

        <section className="cloud-bind-form">
          <label>
            <span>云盘</span>
            <select
              value={provider}
              onChange={(event) =>
                setProvider(event.target.value as CloudProvider)
              }
            >
              <option value="aliyun">阿里云盘</option>
              <option value="baidu">百度网盘</option>
            </select>
          </label>
          <label>
            <span>默认转存目录</span>
            <input
              value={defaultFolder}
              onChange={(event) => setDefaultFolder(event.target.value)}
              placeholder="/MemoIsle/电子书"
              maxLength={500}
            />
          </label>
          <label className="cloud-credential-field">
            <span>登录态</span>
            <textarea
              value={credential}
              onChange={(event) => setCredential(event.target.value)}
              placeholder={credentialPlaceholder[provider]}
              rows={4}
              maxLength={8000}
            />
          </label>
          <button
            type="button"
            className="primary-button"
            disabled={busy}
            onClick={() => void handleBind()}
          >绑定云盘</button>
          <p className="cloud-dialog-hint">{credentialHint[provider]}</p>
        </section>

        <section className="cloud-account-list" aria-label="已绑定云盘">
          {loading && <div className="cloud-empty">正在读取绑定…</div>}
          {!loading && !accounts.length && (
            <div className="cloud-empty">还没有绑定任何云盘。</div>
          )}
          {!loading && accounts.map((account) => (
            <article className="cloud-account" key={account.id}>
              <div className="cloud-account-heading">
                <div>
                  <span className={`cloud-status ${account.status}`}>
                    {account.status === "active" ? "可用" : "已失效"}
                  </span>
                  <h3>{providerLabels[account.provider]} · {account.display_name}</h3>
                </div>
                <span className="cloud-account-hint">{account.credential_hint}</span>
              </div>
              <div className="cloud-account-meta">
                <span>默认目录：{account.default_folder}</span>
                <span>最近校验：{formatTime(account.last_checked_at)}</span>
                {account.last_error && <span>问题：{account.last_error}</span>}
              </div>
              <div className="cloud-account-actions">
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void handleVerify(account.id)}
                >重新校验</button>
                <button
                  type="button"
                  className="danger-button"
                  disabled={busy}
                  onClick={() => void handleDelete(account.id)}
                >解绑</button>
              </div>
            </article>
          ))}
        </section>

        {message && <p className="cloud-dialog-message" role="status">{message}</p>}
      </section>
    </div>
  );
}
