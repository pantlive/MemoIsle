import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";

import {
  ApiError,
  createVault,
  createVaultItem,
  deleteVaultItem,
  getVaultStatus,
  listVaultItems,
  resetVault,
  updateVaultItem,
  updateVaultKey,
  type VaultItemRecord,
  type VaultStatus,
} from "./api";
import {
  MIN_MASTER_PASSWORD_LENGTH,
  WrongMasterPasswordError,
  buildVaultBackup,
  createVaultKey,
  decryptVaultItem,
  emptyVaultItem,
  encryptVaultItem,
  openVaultBackup,
  parseVaultBackup,
  rewrapVaultKey,
  stampSecretChange,
  subscriptionProviderLabels,
  unlockVault,
  vaultItemFingerprint,
  vaultKindLabels,
  type VaultBackupFile,
  type VaultEntry,
  type VaultItemData,
  type VaultKind,
} from "./vault";
import VaultItemDialog from "./VaultItemDialog";
import { saveVaultReminderCount } from "./vaultReminderBadge";
import {
  collectVaultReminders,
  lastChangedAt,
  reminderLabels,
  type VaultReminder,
} from "./vaultReminders";
import {
  VAULT_AUTO_LOCK_MS,
  getVaultSessionKey,
  lockVaultSession,
  startVaultSession,
  subscribeVaultSession,
  touchVaultSession,
} from "./vaultSession";
import Icon from "./Icon";

const CLIPBOARD_CLEAR_MS = 30_000;
const RESET_PHRASE = "清空密码库";
// 用汉字做类型图标，任何字体都能正常显示。
const kindIcons: Record<VaultKind, string> = {
  login: "账",
  secret: "钥",
  recovery: "码",
  server: "云",
  subscription: "AI",
};

type Phase = "loading" | "error" | "insecure" | "setup" | "locked" | "unlocked";

// WebCrypto 只在 HTTPS 或 localhost 下可用；局域网 http 地址打开时无法加密。
const cryptoAvailable = (): boolean => (
  window.isSecureContext && typeof crypto !== "undefined" && crypto.subtle !== undefined
);
type KindFilter = VaultKind | "all" | "reminders";
// 提醒卡片里最多直接列出几条，其余点「只看需处理的」查看。
const REMINDER_PREVIEW_LIMIT = 4;

interface ImportState {
  backup: VaultBackupFile;
  fileName: string;
}

interface EditorState {
  entry: VaultEntry | null;
  data: VaultItemData;
}

function describe(error: unknown): string {
  if (error instanceof WrongMasterPasswordError) return error.message;
  if (error instanceof Error && error.message) return error.message;
  return "操作失败，请稍后重试。";
}

function entrySubtitle(data: VaultItemData): string {
  if (data.kind === "subscription") {
    const currency = data.currency === "USD" ? "$" : data.currency === "CNY" ? "¥" : data.currency;
    return [
      `${subscriptionProviderLabels[data.provider]}${data.plan ? ` ${data.plan}` : ""}`,
      data.balance ? `余额 ${currency}${data.balance}` : "",
      data.expiresOn ? `${data.expiresOn} 到期` : "",
    ].filter(Boolean).join(" · ");
  }
  if (data.kind === "login") return data.username || data.url || "未填写用户名";
  if (data.kind === "secret") return data.secret ? `${data.secret.length} 个字符` : "未填写密钥";
  if (data.kind === "server") {
    // 服务器优先显示「用户@主机:端口」，扫一眼就知道是哪台机器。
    if (!data.host) return "未填写主机";
    const target = `${data.username ? `${data.username}@` : ""}${data.host}`;
    const port = data.port && data.port !== "22" ? `:${data.port}` : "";
    return `${target}${port} · ${data.authMethod === "key" ? "私钥" : "密码"}`;
  }
  const remaining = data.codes.filter((item) => !item.used).length;
  return `${data.account ? `${data.account} · ` : ""}剩余 ${remaining} / ${data.codes.length} 个可用`;
}

function entryHasSecret(data: VaultItemData): boolean {
  if (data.kind === "login") return Boolean(data.password);
  if (data.kind === "secret") return Boolean(data.secret);
  if (data.kind === "server") {
    return data.authMethod === "key"
      ? Boolean(data.privateKey)
      : Boolean(data.password);
  }
  return false;
}

function matchesQuery(data: VaultItemData, query: string): boolean {
  if (!query) return true;
  // 只按名称、用户名、网址、账号和备注搜索，不匹配密码和密钥本身。
  const haystack = [
    data.title,
    data.notes,
    data.kind === "login" ? `${data.username} ${data.url}` : "",
    data.kind === "recovery" ? data.account : "",
    data.kind === "subscription"
      ? `${subscriptionProviderLabels[data.provider]} ${data.plan} ${data.account}`
      : "",
    // 服务器可以按主机名、IP、用户名、端口搜到。
    data.kind === "server"
      ? `${data.host} ${data.username} ${data.port}`
      : "",
  ].join(" ").toLowerCase();
  return haystack.includes(query.toLowerCase());
}

function MasterPasswordFields({ password, confirm, onPassword, onConfirm, autoFocus }: {
  password: string;
  confirm: string;
  onPassword: (value: string) => void;
  onConfirm: (value: string) => void;
  autoFocus?: boolean;
}) {
  const tooShort = password.length > 0 && password.length < MIN_MASTER_PASSWORD_LENGTH;
  const mismatch = confirm.length > 0 && confirm !== password;
  return (
    <>
      <label className="vault-field">
        <span className="vault-field-label"><span>新主密码</span></span>
        <input
          type="password"
          value={password}
          onChange={(event) => onPassword(event.target.value)}
          autoComplete="new-password"
          autoFocus={autoFocus}
          minLength={MIN_MASTER_PASSWORD_LENGTH}
          required
        />
        <small className={tooShort ? "vault-hint warn" : "vault-hint"}>
          至少 {MIN_MASTER_PASSWORD_LENGTH} 个字符；用几个不相关的词组成的长句更好记也更安全。
        </small>
      </label>
      <label className="vault-field">
        <span className="vault-field-label"><span>再输入一次</span></span>
        <input
          type="password"
          value={confirm}
          onChange={(event) => onConfirm(event.target.value)}
          autoComplete="new-password"
          required
        />
        {mismatch && <small className="vault-hint warn">两次输入不一致。</small>}
      </label>
    </>
  );
}

async function decryptVaultItemsOrThrow(key: CryptoKey, records: VaultItemRecord[]): Promise<void> {
  try {
    await Promise.all(records.map((record) => decryptVaultItem(key, record)));
  } catch {
    throw new Error("当前解锁状态和服务器上的密码库对不上（主密码可能刚在别处改过），请锁定后重新解锁再导出。");
  }
}

function masterPasswordReady(password: string, confirm: string): boolean {
  return password.length >= MIN_MASTER_PASSWORD_LENGTH && password === confirm;
}

export default function VaultPanel() {
  const [phase, setPhase] = useState<Phase>("loading");
  const [status, setStatus] = useState<VaultStatus | null>(null);
  const [entries, setEntries] = useState<VaultEntry[]>([]);
  const [brokenCount, setBrokenCount] = useState(0);
  const [query, setQuery] = useState("");
  const [kindFilter, setKindFilter] = useState<KindFilter>("all");
  const [editor, setEditor] = useState<EditorState | null>(null);
  const [dialogError, setDialogError] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [formError, setFormError] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [acknowledged, setAcknowledged] = useState(false);
  const [resetOpen, setResetOpen] = useState(false);
  const [resetPhrase, setResetPhrase] = useState("");
  const [changeOpen, setChangeOpen] = useState(false);
  const [currentPassword, setCurrentPassword] = useState("");
  const clipboardTimer = useRef<number | null>(null);
  const backupInputRef = useRef<HTMLInputElement>(null);
  const [importState, setImportState] = useState<ImportState | null>(null);
  const [importPassword, setImportPassword] = useState("");
  const [importProgress, setImportProgress] = useState("");
  const [importError, setImportError] = useState("");

  useEffect(() => {
    if (!importState && !changeOpen) return;
    // 提交按钮禁用时可能失去焦点，错误返回后仍应能通过 Esc 关闭表单。
    const handleKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || busy) return;
      if (importState) setImportState(null);
      if (changeOpen) setChangeOpen(false);
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [busy, changeOpen, importState]);

  const clearSecrets = () => {
    setPassword("");
    setConfirm("");
    setCurrentPassword("");
  };

  const loadEntries = useCallback(async (key: CryptoKey) => {
    const records = await listVaultItems();
    const results = await Promise.allSettled(records.map((record) => decryptVaultItem(key, record)));
    const decrypted = results
      .filter((result): result is PromiseFulfilledResult<VaultEntry> => result.status === "fulfilled")
      .map((result) => result.value);
    setEntries(decrypted);
    setBrokenCount(results.length - decrypted.length);
  }, []);

  const refreshStatus = useCallback(async () => {
    if (!cryptoAvailable()) {
      setPhase("insecure");
      return;
    }
    setPhase("loading");
    try {
      const next = await getVaultStatus();
      setStatus(next);
      const key = getVaultSessionKey();
      if (!next.configured) {
        lockVaultSession();
        setPhase("setup");
      } else if (key) {
        await loadEntries(key);
        setPhase("unlocked");
      } else {
        setPhase("locked");
      }
    } catch (error) {
      setFormError(describe(error));
      setPhase("error");
    }
  }, [loadEntries]);

  useEffect(() => {
    void refreshStatus();
  }, [refreshStatus]);

  // 自动锁定或在别处锁定后，立刻清掉内存里的明文条目。
  useEffect(() => subscribeVaultSession(() => {
    if (getVaultSessionKey()) return;
    setEntries([]);
    setEditor(null);
    setChangeOpen(false);
    setPhase((current) => (current === "unlocked" ? "locked" : current));
    setNotice("密码库已锁定。");
  }), []);

  useEffect(() => {
    if (phase !== "unlocked") return;
    const touch = () => touchVaultSession();
    window.addEventListener("pointerdown", touch);
    window.addEventListener("keydown", touch);
    return () => {
      window.removeEventListener("pointerdown", touch);
      window.removeEventListener("keydown", touch);
    };
  }, [phase]);

  useEffect(() => () => {
    if (clipboardTimer.current !== null) window.clearTimeout(clipboardTimer.current);
  }, []);

  const copyValue = useCallback(async (value: string, label: string) => {
    if (!value) return;
    try {
      await navigator.clipboard.writeText(value);
    } catch {
      setNotice("浏览器不允许写入剪贴板，请手动复制。");
      return;
    }
    setNotice(`已复制${label}，${CLIPBOARD_CLEAR_MS / 1000} 秒后清空剪贴板。`);
    if (clipboardTimer.current !== null) window.clearTimeout(clipboardTimer.current);
    clipboardTimer.current = window.setTimeout(() => {
      clipboardTimer.current = null;
      void (async () => {
        // 能读剪贴板时只在内容没变时清空，避免覆盖用户之后复制的其他内容。
        try {
          const current = await navigator.clipboard.readText();
          if (current !== value) return;
        } catch {
          // 读不到就直接清空，宁可多清一次也不把密码留在剪贴板里。
        }
        await navigator.clipboard.writeText("").catch(() => undefined);
      })();
    }, CLIPBOARD_CLEAR_MS);
  }, []);

  const handleSetup = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!masterPasswordReady(password, confirm) || !acknowledged) return;
    setBusy(true);
    setFormError("");
    try {
      const { material, key } = await createVaultKey(password);
      const created = await createVault(material);
      clearSecrets();
      setStatus(created);
      startVaultSession(key);
      setEntries([]);
      setPhase("unlocked");
      setNotice("密码库已创建。主密码不会上传，请务必记住它。");
    } catch (error) {
      setFormError(describe(error));
    } finally {
      setBusy(false);
    }
  };

  const handleUnlock = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!status || !password) return;
    setBusy(true);
    setFormError("");
    try {
      // 每次解锁都取最新参数，主密码可能刚在其他设备上改过。
      const latest = await getVaultStatus();
      setStatus(latest);
      if (!latest.configured) {
        setPhase("setup");
        return;
      }
      const key = await unlockVault(password, latest);
      clearSecrets();
      startVaultSession(key);
      await loadEntries(key);
      setPhase("unlocked");
      setNotice(`已解锁，${VAULT_AUTO_LOCK_MS / 60_000} 分钟无操作会自动锁定。`);
    } catch (error) {
      setFormError(describe(error));
    } finally {
      setBusy(false);
    }
  };

  const handleReset = async () => {
    if (resetPhrase !== RESET_PHRASE) return;
    setBusy(true);
    try {
      await resetVault();
      lockVaultSession();
      saveVaultReminderCount(0);
      setResetOpen(false);
      setResetPhrase("");
      setNotice("密码库已清空，可以重新设置主密码。");
      await refreshStatus();
    } catch (error) {
      setFormError(describe(error));
    } finally {
      setBusy(false);
    }
  };

  const handleChangePassword = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!status || !masterPasswordReady(password, confirm) || !currentPassword) return;
    setBusy(true);
    setFormError("");
    try {
      const latest = await getVaultStatus();
      const { material, key } = await rewrapVaultKey(currentPassword, password, latest);
      const updated = await updateVaultKey(material, latest.version ?? 1);
      clearSecrets();
      setStatus(updated);
      startVaultSession(key);
      setChangeOpen(false);
      setNotice("主密码已更改，其他设备下次解锁时使用新主密码。");
    } catch (error) {
      setFormError(
        error instanceof ApiError && error.status === 409
          ? "主密码刚在其他地方改过，请刷新后重试。"
          : describe(error),
      );
    } finally {
      setBusy(false);
    }
  };

  const openNew = (kind: VaultKind) => {
    setDialogError("");
    setEditor({ entry: null, data: emptyVaultItem(kind) });
  };

  const handleSave = async (data: VaultItemData) => {
    const key = getVaultSessionKey();
    if (!key || !editor) return;
    setBusy(true);
    setDialogError("");
    const id = editor.entry?.id ?? crypto.randomUUID();
    try {
      const encrypted = await encryptVaultItem(key, id, stampSecretChange(editor.entry?.data ?? null, data));
      const record = editor.entry
        ? await updateVaultItem(id, encrypted, editor.entry.version)
        : await createVaultItem(id, encrypted);
      const saved = await decryptVaultItem(key, record);
      setEntries((current) => [saved, ...current.filter((entry) => entry.id !== saved.id)]);
      setEditor(null);
      setNotice(`已加密保存「${saved.data.title}」。`);
    } catch (error) {
      if (error instanceof ApiError && error.status === 409 && error.current) {
        // 别处改过：载入最新内容，让用户在新版本上重新修改。
        const latest = await decryptVaultItem(key, error.current as unknown as VaultItemRecord);
        setEntries((current) => current.map((entry) => (entry.id === latest.id ? latest : entry)));
        setEditor({ entry: latest, data: latest.data });
        setDialogError("这一条刚在别处修改过，已载入最新内容，请重新修改后保存。");
      } else {
        setDialogError(describe(error));
      }
    } finally {
      setBusy(false);
    }
  };

  const handleDelete = async () => {
    const entry = editor?.entry;
    if (!entry || !window.confirm(`永久删除「${entry.data.title}」？删除后无法恢复。`)) return;
    setBusy(true);
    try {
      await deleteVaultItem(entry.id, entry.version);
      setEntries((current) => current.filter((item) => item.id !== entry.id));
      setEditor(null);
      setNotice(`已删除「${entry.data.title}」。`);
    } catch (error) {
      setDialogError(
        error instanceof ApiError && error.status === 409
          ? "这一条刚在别处修改过，请关闭后刷新再删除。"
          : describe(error),
      );
    } finally {
      setBusy(false);
    }
  };

  const handleExportBackup = async () => {
    const key = getVaultSessionKey();
    if (!key) return;
    setBusy(true);
    try {
      const [latest, records] = await Promise.all([getVaultStatus(), listVaultItems()]);
      // 先用当前会话密钥试解每一条：主密码若在别处改过，包裹参数就和会话密钥对不上。
      await decryptVaultItemsOrThrow(key, records);
      const backup = buildVaultBackup(latest, records);
      const blob = new Blob([JSON.stringify(backup, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `memoisle-vault-backup-${backup.exported_at.slice(0, 10)}.json`;
      document.body.append(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 0);
      setNotice(`已导出加密备份（${records.length} 条）。恢复时需要输入现在的主密码，请妥善保管。`);
    } catch (error) {
      setNotice(describe(error));
    } finally {
      setBusy(false);
    }
  };

  const handleBackupFile = async (file: File) => {
    try {
      const backup = parseVaultBackup(await file.text());
      setImportPassword("");
      setImportError("");
      setImportProgress("");
      setImportState({ backup, fileName: file.name });
    } catch (error) {
      setNotice(`无法读取「${file.name}」：${describe(error)}`);
    }
  };

  const handleImportBackup = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const key = getVaultSessionKey();
    if (!key || !importState || !importPassword) return;
    setBusy(true);
    setImportError("");
    try {
      setImportProgress("正在解密备份…");
      const { items, failed } = await openVaultBackup(importPassword, importState.backup);
      setImportPassword("");
      const existing = new Set(entries.map((entry) => vaultItemFingerprint(entry.data)));
      const fresh = items.filter((item) => {
        const fingerprint = vaultItemFingerprint(item);
        if (existing.has(fingerprint)) return false;
        existing.add(fingerprint);
        return true;
      });
      const saved: VaultEntry[] = [];
      for (const [index, item] of fresh.entries()) {
        setImportProgress(`正在加密写入 ${index + 1} / ${fresh.length}…`);
        // 用新 ID 和当前库密钥重新加密，备份来自旧密码库或其他账号也不会冲突。
        const id = crypto.randomUUID();
        const record = await createVaultItem(id, await encryptVaultItem(key, id, item));
        saved.push(await decryptVaultItem(key, record));
      }
      setEntries((current) => [...saved, ...current]);
      setImportState(null);
      const skipped = items.length - fresh.length;
      setNotice([
        `已导入 ${saved.length} 条`,
        skipped > 0 ? `跳过 ${skipped} 条重复` : "",
        failed > 0 ? `${failed} 条无法解密` : "",
      ].filter(Boolean).join("，") + "。");
    } catch (error) {
      setImportError(
        error instanceof WrongMasterPasswordError
          ? "主密码不正确。请输入导出这份备份时使用的主密码。"
          : describe(error),
      );
      // 中途失败时已写入的条目保留，重新读取一遍列表。
      await loadEntries(key).catch(() => undefined);
    } finally {
      setImportProgress("");
      setBusy(false);
    }
  };

  const closeEditor = useCallback(() => setEditor(null), []);

  const reminders = useMemo(() => collectVaultReminders(entries), [entries]);
  const remindersByEntry = useMemo(() => {
    const result = new Map<string, VaultReminder[]>();
    for (const reminder of reminders) {
      result.set(reminder.entryId, [...(result.get(reminder.entryId) ?? []), reminder]);
    }
    return result;
  }, [reminders]);

  // 锁定后导航用这个数字提示还有几条需要处理。
  useEffect(() => {
    if (phase === "unlocked") saveVaultReminderCount(remindersByEntry.size);
  }, [phase, remindersByEntry]);

  const counts = useMemo(() => {
    const result: Record<KindFilter, number> = {
      all: entries.length,
      login: 0,
      secret: 0,
      recovery: 0,
      server: 0,
      subscription: 0,
      reminders: remindersByEntry.size,
    };
    for (const entry of entries) result[entry.data.kind] += 1;
    return result;
  }, [entries, remindersByEntry]);

  const openEntry = (entry: VaultEntry) => {
    setDialogError("");
    setEditor({ entry, data: entry.data });
  };

  const visibleEntries = useMemo(() => entries
    .filter((entry) => (
      kindFilter === "all"
      || (kindFilter === "reminders" ? remindersByEntry.has(entry.id) : entry.data.kind === kindFilter)
    ))
    .filter((entry) => matchesQuery(entry.data, query.trim()))
    .sort((left, right) => left.data.title.localeCompare(right.data.title, "zh-CN")), [entries, kindFilter, query, remindersByEntry]);

  return (
    <section className="vault-panel" aria-labelledby="vault-title">
      <div className="page-heading">
        <div>
          <h1 id="vault-title">密码库</h1>
          <p className="page-subtitle">端到端加密 · 服务器只保存密文</p>
        </div>
        {phase === "unlocked" && (
          <span className="vault-heading-actions">
            <button type="button" disabled={busy} onClick={() => void handleExportBackup()}>
              导出备份
            </button>
            <button type="button" disabled={busy} onClick={() => backupInputRef.current?.click()}>
              导入备份
            </button>
            <input
              ref={backupInputRef}
              type="file"
              accept=".json,application/json"
              hidden
              aria-label="选择密码库备份文件"
              onChange={(event) => {
                const file = event.target.files?.[0];
                event.target.value = "";
                if (file) void handleBackupFile(file);
              }}
            />
            <button type="button" onClick={() => { clearSecrets(); setFormError(""); setChangeOpen(true); }}>
              更改主密码
            </button>
            <button type="button" onClick={() => lockVaultSession()}>锁定</button>
          </span>
        )}
      </div>

      {notice && (
        <div className="status-message" role="status">
          <span>{notice}</span>
          <button type="button" onClick={() => setNotice("")} aria-label="关闭提示"><Icon name="close" size={16} /></button>
        </div>
      )}

      {phase === "loading" && <div className="state-panel">正在读取密码库……</div>}

      {phase === "insecure" && (
        <div className="state-panel error-state">
          <p>
            当前地址不是 HTTPS，浏览器不提供加密功能，密码库无法使用。
            请通过 https:// 或本机的 localhost 打开 MemoIsle。
          </p>
        </div>
      )}

      {phase === "error" && (
        <div className="state-panel error-state">
          <p>{formError || "暂时无法读取密码库。"}</p>
          <button type="button" onClick={() => void refreshStatus()}>重试</button>
        </div>
      )}

      {phase === "setup" && (
        <form className="vault-card vault-gate" onSubmit={(event) => void handleSetup(event)}>
          <h2>设置主密码</h2>
          <p>
            主密码只在这台浏览器里用来加密，不会上传。MemoIsle 服务器只保存加密后的内容，
            即使数据库泄露也读不出来。
          </p>
          <MasterPasswordFields
            password={password}
            confirm={confirm}
            onPassword={setPassword}
            onConfirm={setConfirm}
            autoFocus
          />
          <label className="vault-acknowledge">
            <input
              type="checkbox"
              checked={acknowledged}
              onChange={(event) => setAcknowledged(event.target.checked)}
            />
            我知道忘记主密码后，任何人都无法找回密码库里的内容。
          </label>
          {formError && <p className="vault-error" role="alert">{formError}</p>}
          <button
            type="submit"
            className="primary"
            disabled={busy || !acknowledged || !masterPasswordReady(password, confirm)}
          >
            {busy ? "正在生成密钥…" : "创建密码库"}
          </button>
        </form>
      )}

      {phase === "locked" && (
        <div className="vault-card vault-gate">
          <form onSubmit={(event) => void handleUnlock(event)}>
            <h2>密码库已锁定</h2>
            <p>
              输入主密码解锁{status?.item_count ? `，共 ${status.item_count} 条` : ""}。
              解锁在本机浏览器里完成，主密码不会发送到服务器。
            </p>
            <label className="vault-field">
              <span className="vault-field-label"><span>主密码</span></span>
              <input
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                autoComplete="current-password"
                autoFocus
                required
              />
            </label>
            {formError && <p className="vault-error" role="alert">{formError}</p>}
            <button type="submit" className="primary" disabled={busy || !password}>
              {busy ? "解锁中…" : "解锁"}
            </button>
          </form>
          <details
            className="vault-reset"
            open={resetOpen}
            onToggle={(event) => setResetOpen((event.target as HTMLDetailsElement).open)}
          >
            <summary>忘记主密码？</summary>
            <p>
              主密码无法找回，也无法重置后保留内容。唯一的办法是清空整个密码库，
              {status?.item_count ? `其中的 ${status.item_count} 条会` : "所有内容会"}永久删除，然后重新设置主密码。
            </p>
            <label className="vault-field">
              <span className="vault-field-label"><span>输入「{RESET_PHRASE}」确认</span></span>
              <input value={resetPhrase} onChange={(event) => setResetPhrase(event.target.value)} />
            </label>
            <button
              type="button"
              className="danger-button"
              disabled={busy || resetPhrase !== RESET_PHRASE}
              onClick={() => void handleReset()}
            >
              永久清空密码库
            </button>
          </details>
        </div>
      )}

      {phase === "unlocked" && (
        <>
          <div className="vault-toolbar">
            <div className="resource-search vault-search">
              <Icon name="search" size={18} />
              <input
                aria-label="搜索密码库"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="按名称、账号、服务商、套餐、网址或备注搜索"
                autoComplete="off"
              />
            </div>
            <div className="vault-new-actions" aria-label="新建">
              {(["login", "secret", "server", "recovery", "subscription"] as VaultKind[]).map((kind) => (
                <button key={kind} type="button" onClick={() => openNew(kind)}>
                  ＋ {vaultKindLabels[kind]}
                </button>
              ))}
            </div>
          </div>
          <div className="category-filter vault-kind-filter" role="group" aria-label="按类型筛选">
            {(["all", "login", "secret", "server", "recovery", "subscription", "reminders"] as KindFilter[])
              // 「需处理」没有提醒时不显示，正在看这一栏时保留，避免按钮突然消失。
              .filter((kind) => kind !== "reminders" || counts.reminders > 0 || kindFilter === "reminders")
              .map((kind) => (
                <button
                  key={kind}
                  type="button"
                  className={`${kindFilter === kind ? "active" : ""}${kind === "reminders" ? " vault-filter-reminders" : ""}`}
                  aria-pressed={kindFilter === kind}
                  onClick={() => setKindFilter(kind)}
                >
                  {kind === "all" ? "全部" : kind === "reminders" ? "需处理" : vaultKindLabels[kind]} {counts[kind]}
                </button>
              ))}
          </div>
          {reminders.length > 0 && kindFilter !== "reminders" && !query.trim() && (
            <section className="vault-reminders" aria-labelledby="vault-reminders-title">
              <div className="vault-reminders-header">
                <h2 id="vault-reminders-title">密码提醒</h2>
                <small>{remindersByEntry.size} 条需要处理</small>
              </div>
              <ul>
                {reminders.slice(0, REMINDER_PREVIEW_LIMIT).map((reminder) => {
                  const entry = entries.find((item) => item.id === reminder.entryId);
                  return (
                    <li key={`${reminder.entryId}:${reminder.type}`}>
                      <button
                        type="button"
                        className={`vault-reminder ${reminder.level}`}
                        onClick={() => entry && openEntry(entry)}
                      >
                        <span className="vault-reminder-badge">{reminderLabels[reminder.type]}</span>
                        <span className="vault-reminder-text">
                          <strong>{reminder.title}</strong>
                          <small>{reminder.message}</small>
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
              {reminders.length > REMINDER_PREVIEW_LIMIT && (
                <button type="button" className="vault-reminders-more" onClick={() => setKindFilter("reminders")}>
                  查看全部 {reminders.length} 项提醒
                </button>
              )}
            </section>
          )}
          {brokenCount > 0 && (
            <p className="vault-error" role="alert">
              有 {brokenCount} 条无法解密，可能已损坏或被篡改，已跳过显示。
            </p>
          )}
          {entries.length === 0 && (
            <div className="state-panel empty-state">
              <h3>密码库还是空的</h3>
              <p>可以保存网站账号密码、AI 订阅、API Key 或 SSH 私钥，以及两步验证的恢复码。已有加密备份可以点右上角「导入备份」恢复。</p>
            </div>
          )}
          {entries.length > 0 && visibleEntries.length === 0 && (
            <div className="state-panel">
              {kindFilter === "reminders" && !query.trim() ? "提醒都处理完了。" : "没有匹配的条目。"}
            </div>
          )}
          <ul className="vault-list">
            {visibleEntries.map((entry) => {
              const { data } = entry;
              const nextCode = data.kind === "recovery" ? data.codes.find((item) => !item.used) : undefined;
              const entryReminders = remindersByEntry.get(entry.id) ?? [];
              return (
                <li key={entry.id} className="vault-row">
                  <button type="button" className="vault-row-main" onClick={() => openEntry(entry)}>
                    <span className={`vault-kind-icon ${data.kind}`} aria-hidden="true">{kindIcons[data.kind]}</span>
                    <span className="vault-row-text">
                      <span className="vault-row-title">
                        <strong>{data.title}</strong>
                        {entryReminders.map((reminder) => (
                          <span
                            key={reminder.type}
                            className={`vault-reminder-badge ${reminder.level}`}
                            title={reminder.message}
                          >
                            {reminderLabels[reminder.type]}
                          </span>
                        ))}
                      </span>
                      <small>
                        {kindFilter === "reminders" && entryReminders[0]
                          ? entryReminders.map((reminder) => reminder.message).join(" ")
                          : `${vaultKindLabels[data.kind]} · ${entrySubtitle(data)}`}
                      </small>
                    </span>
                  </button>
                  <span className="vault-row-actions">
                    {data.kind === "subscription" && (
                      <>
                        <button type="button" disabled={!data.account} onClick={() => void copyValue(data.account, "账号")}>复制账号</button>
                      </>
                    )}
                    {data.kind === "login" && (
                      <>
                        <button type="button" disabled={!data.username} onClick={() => void copyValue(data.username, "用户名")}>复制用户名</button>
                        <button type="button" disabled={!data.password} onClick={() => void copyValue(data.password, "密码")}>复制密码</button>
                      </>
                    )}
                    {data.kind === "secret" && (
                      <button type="button" disabled={!data.secret} onClick={() => void copyValue(data.secret, "密钥")}>复制密钥</button>
                    )}
                    {data.kind === "server" && (
                      <>
                        <button type="button" disabled={!data.host} onClick={() => void copyValue(data.host, "主机")}>复制主机</button>
                        <button
                          type="button"
                          disabled={data.authMethod === "key" ? !data.privateKey : !data.password}
                          onClick={() => void copyValue(
                            data.authMethod === "key" ? data.privateKey : data.password,
                            data.authMethod === "key" ? "私钥" : "密码",
                          )}
                        >
                          {data.authMethod === "key" ? "复制私钥" : "复制密码"}
                        </button>
                        <button
                          type="button"
                          disabled={!data.host}
                          title="复制可直接粘贴到终端的 ssh 命令"
                          onClick={() => void copyValue(
                            `ssh${data.port && data.port !== "22" ? ` -p ${data.port}` : ""} ${
                              data.username ? `${data.username}@` : ""}${data.host}`,
                            "ssh 命令",
                          )}
                        >
                          复制 ssh
                        </button>
                      </>
                    )}
                    {data.kind === "recovery" && (
                      <button
                        type="button"
                        disabled={!nextCode}
                        title="复制第一个还没用过的恢复码；用完后记得在详情里标记已用"
                        onClick={() => nextCode && void copyValue(nextCode.code, "恢复码")}
                      >
                        {nextCode ? "复制未用的恢复码" : "恢复码已用完"}
                      </button>
                    )}
                  </span>
                </li>
              );
            })}
          </ul>
        </>
      )}

      {editor && (
        <VaultItemDialog
          initial={editor.data}
          isNew={editor.entry === null}
          changedAt={editor.entry && entryHasSecret(editor.entry.data) ? lastChangedAt(editor.entry) : null}
          reminders={editor.entry ? remindersByEntry.get(editor.entry.id) ?? [] : []}
          busy={busy}
          error={dialogError}
          onSave={(data) => void handleSave(data)}
          onDelete={() => void handleDelete()}
          onClose={closeEditor}
          onCopy={(value, label) => void copyValue(value, label)}
        />
      )}

      {importState && (
        <div className="dialog-backdrop vault-import-backdrop" role="presentation">
          <form
            className="vault-item-dialog dialog-shell"
            role="dialog"
            aria-modal="true"
            aria-labelledby="vault-import-title"
            onSubmit={(event) => void handleImportBackup(event)}
          >
            <div className="dialog-header">
              <h2 id="vault-import-title">导入加密备份</h2>
              <button type="button" className="icon-button" aria-label="关闭" disabled={busy} onClick={() => setImportState(null)}><Icon name="close" size={16} /></button>
            </div>
            <div className="dialog-body vault-form">
              <p className="vault-import-summary">
                「{importState.fileName}」：{importState.backup.items.length} 条，
                导出于 {new Date(importState.backup.exported_at).toLocaleString("zh-CN")}。
                导入的条目会用当前密码库的密钥重新加密，和已有内容完全相同的条目会跳过。
              </p>
              <label className="vault-field">
                <span className="vault-field-label"><span>导出这份备份时的主密码</span></span>
                <input
                  type="password"
                  value={importPassword}
                  onChange={(event) => setImportPassword(event.target.value)}
                  autoComplete="off"
                  autoFocus
                  required
                />
              </label>
              {importProgress && <p className="vault-hint" role="status">{importProgress}</p>}
            </div>
            <div className="dialog-actions">
              <button type="button" onClick={() => setImportState(null)} disabled={busy}>取消</button>
              <button type="submit" className="primary" disabled={busy || !importPassword}>
                {busy ? "导入中…" : "导入"}
              </button>
            </div>
            {importError && <p className="dialog-error" role="alert">{importError}</p>}
          </form>
        </div>
      )}

      {changeOpen && (
        <div className="dialog-backdrop vault-password-backdrop" role="presentation">
          <form
            className="vault-item-dialog dialog-shell"
            role="dialog"
            aria-modal="true"
            aria-labelledby="vault-change-title"
            onSubmit={(event) => void handleChangePassword(event)}
          >
            <div className="dialog-header">
              <h2 id="vault-change-title">更改主密码</h2>
              <button type="button" className="icon-button" aria-label="关闭" disabled={busy} onClick={() => setChangeOpen(false)}><Icon name="close" size={16} /></button>
            </div>
            <div className="dialog-body vault-form">
              <label className="vault-field">
                <span className="vault-field-label"><span>当前主密码</span></span>
                <input
                  type="password"
                  value={currentPassword}
                  onChange={(event) => setCurrentPassword(event.target.value)}
                  autoComplete="current-password"
                  autoFocus
                  required
                />
              </label>
              <MasterPasswordFields
                password={password}
                confirm={confirm}
                onPassword={setPassword}
                onConfirm={setConfirm}
              />
            </div>
            <div className="dialog-actions">
              <button type="button" onClick={() => setChangeOpen(false)} disabled={busy}>取消</button>
              <button
                type="submit"
                className="primary"
                disabled={busy || !currentPassword || !masterPasswordReady(password, confirm)}
              >
                {busy ? "重新加密中…" : "更改主密码"}
              </button>
            </div>
            {formError && <p className="dialog-error" role="alert">{formError}</p>}
          </form>
        </div>
      )}
    </section>
  );
}
