import { useEffect, useRef, useState, type FormEvent } from "react";

import {
  VAULT_ROTATE_OPTIONS,
  generatePassword,
  parseRecoveryCodes,
  vaultKindLabels,
  type RecoveryCode,
  type VaultItemData,
  type VaultLoginData,
  type VaultSecretData,
  type VaultServerData,
} from "./vault";
import { daysSince, daysUntilDate, isWeakPassword, reminderLabels, type VaultReminder } from "./vaultReminders";

// 敏感字段默认遮挡，点「显示」才露出明文。
function SecretInput({ label, value, onChange, onCopy, onGenerate, multiline = false }: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  onCopy: () => void;
  onGenerate?: () => void;
  multiline?: boolean;
}) {
  const [visible, setVisible] = useState(false);
  return (
    <div className="vault-field">
      <div className="vault-field-label">
        <span>{label}</span>
        <span className="vault-field-tools">
          <button type="button" onClick={() => setVisible((current) => !current)}>
            {visible ? "隐藏" : "显示"}
          </button>
          {onGenerate && <button type="button" onClick={onGenerate}>生成</button>}
          <button type="button" onClick={onCopy} disabled={!value}>复制</button>
        </span>
      </div>
      {multiline && visible && (
        <textarea
          aria-label={label}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          rows={6}
          spellCheck={false}
          autoComplete="off"
          className="vault-mono"
        />
      )}
      {multiline && !visible && (
        <button
          type="button"
          className="vault-masked-block"
          aria-label={`${label}已隐藏，点按显示并编辑`}
          onClick={() => setVisible(true)}
        >
          {value ? `•••••• 已隐藏（${value.length} 个字符），点按显示` : "点按输入"}
        </button>
      )}
      {!multiline && (
        <input
          aria-label={label}
          type={visible ? "text" : "password"}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          spellCheck={false}
          // 避免浏览器把这里当成 MemoIsle 自己的登录表单去保存或自动填充。
          autoComplete="new-password"
          className="vault-mono"
        />
      )}
    </div>
  );
}

function rotateLabel(days: number): string {
  if (days === 0) return "不提醒";
  if (days === 365) return "每年";
  return `每 ${days} 天`;
}

function describeAge(iso: string): string {
  const days = daysSince(iso);
  const date = new Date(iso).toLocaleDateString("zh-CN");
  return `${date}（${days === 0 ? "今天" : `${days} 天前`}）`;
}

// 账号密码和密钥共用的提醒设置。
function ReminderFields({ draft, changedLabel, secretChanged, onChange }: {
  draft: VaultLoginData | VaultSecretData | VaultServerData;
  changedLabel: string;
  secretChanged: boolean;
  onChange: (field: "rotateDays" | "expiresOn" | "skipChecks", value: number | string | boolean) => void;
}) {
  const expiresIn = draft.expiresOn ? daysUntilDate(draft.expiresOn) : null;
  return (
    <fieldset className="vault-reminder-fields">
      <legend>提醒</legend>
      <p className="vault-hint">
        {draft.kind === "login"
          ? "密码"
          : draft.kind === "server"
            ? "登录凭据"
            : "密钥"}上次更换：
        {secretChanged ? "保存后记为今天" : changedLabel}
      </p>
      <div className="vault-reminder-grid">
        <label className="vault-field">
          <span className="vault-field-label"><span>定期更换</span></span>
          <select
            value={draft.rotateDays}
            onChange={(event) => onChange("rotateDays", Number(event.target.value))}
          >
            {VAULT_ROTATE_OPTIONS.map((days) => (
              <option key={days} value={days}>{rotateLabel(days)}</option>
            ))}
          </select>
        </label>
        <label className="vault-field">
          <span className="vault-field-label">
            <span>到期日</span>
            {draft.expiresOn && (
              <button type="button" onClick={() => onChange("expiresOn", "")}>清除</button>
            )}
          </span>
          <input
            type="date"
            value={draft.expiresOn}
            onChange={(event) => onChange("expiresOn", event.target.value)}
          />
        </label>
      </div>
      {expiresIn !== null && (
        <small className={expiresIn <= 0 ? "vault-hint warn" : "vault-hint"}>
          {expiresIn < 0 ? `已过期 ${-expiresIn} 天` : expiresIn === 0 ? "今天到期" : `还有 ${expiresIn} 天到期，到期前 14 天开始提醒`}
        </small>
      )}
      {draft.kind === "login" && (
        <label className="vault-acknowledge">
          <input
            type="checkbox"
            checked={draft.skipChecks}
            onChange={(event) => onChange("skipChecks", event.target.checked)}
          />
          不检查这条的密码强度和是否与其他条目重复
        </label>
      )}
    </fieldset>
  );
}

function RecoveryCodeEditor({ codes, onChange, onCopy }: {
  codes: RecoveryCode[];
  onChange: (codes: RecoveryCode[]) => void;
  onCopy: (code: string) => void;
}) {
  const [pasted, setPasted] = useState("");
  const remaining = codes.filter((item) => !item.used).length;
  return (
    <div className="vault-field">
      <div className="vault-field-label">
        <span>恢复码</span>
        {codes.length > 0 && <small>剩余 {remaining} / {codes.length} 个可用</small>}
      </div>
      {codes.length > 0 && (
        <ul className="vault-code-list">
          {codes.map((item, index) => (
            <li key={item.code} className={item.used ? "used" : ""}>
              <label>
                <input
                  type="checkbox"
                  checked={item.used}
                  onChange={() => onChange(codes.map((code, current) => (
                    current === index ? { ...code, used: !code.used } : code
                  )))}
                />
                已用
              </label>
              <code className="vault-mono">{item.code}</code>
              <button type="button" onClick={() => onCopy(item.code)} disabled={item.used}>复制</button>
              <button
                type="button"
                className="danger-text"
                aria-label={`删除恢复码 ${item.code}`}
                onClick={() => onChange(codes.filter((_, current) => current !== index))}
              >×</button>
            </li>
          ))}
        </ul>
      )}
      <textarea
        aria-label="添加恢复码"
        value={pasted}
        onChange={(event) => setPasted(event.target.value)}
        rows={codes.length > 0 ? 2 : 5}
        placeholder="把网站给的恢复码整段粘贴进来，按空格、换行或逗号自动拆分"
        spellCheck={false}
        autoComplete="off"
        className="vault-mono"
      />
      <button
        type="button"
        className="vault-add-codes"
        disabled={!pasted.trim()}
        onClick={() => {
          onChange(parseRecoveryCodes(pasted, codes));
          setPasted("");
        }}
      >
        添加恢复码
      </button>
    </div>
  );
}

export default function VaultItemDialog({
  initial, isNew, changedAt, reminders, busy, error, onSave, onDelete, onClose, onCopy,
}: {
  initial: VaultItemData;
  isNew: boolean;
  // 已保存条目的上次更换时间；新建时为 null。
  changedAt: string | null;
  reminders: VaultReminder[];
  busy: boolean;
  error: string;
  onSave: (data: VaultItemData) => void;
  onDelete: () => void;
  onClose: () => void;
  onCopy: (value: string, label: string) => void;
}) {
  const [draft, setDraft] = useState<VaultItemData>(initial);
  const titleRef = useRef<HTMLInputElement>(null);
  const dirty = JSON.stringify(draft) !== JSON.stringify(initial);
  const dirtyRef = useRef(dirty);
  dirtyRef.current = dirty;

  // 保存冲突时外部会换成最新内容。
  useEffect(() => setDraft(initial), [initial]);

  useEffect(() => {
    titleRef.current?.focus();
  }, []);

  useEffect(() => {
    const handleKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || busy) return;
      if (dirtyRef.current && !window.confirm("有未保存的修改，确定放弃吗？")) return;
      onClose();
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [busy, onClose]);

  // 各类型字段不同，按字段名写入当前类型的草稿。
  const update = (field: string, value: string | number | boolean | RecoveryCode[]) => {
    setDraft((current) => ({ ...current, [field]: value }) as VaultItemData);
  };

  const secretChanged = (draft.kind === "login" && initial.kind === "login" && draft.password !== initial.password && Boolean(draft.password))
    || (draft.kind === "secret" && initial.kind === "secret" && draft.secret !== initial.secret && Boolean(draft.secret))
    || (draft.kind === "server" && initial.kind === "server" && (
      draft.authMethod === "key"
        ? draft.privateKey !== initial.privateKey && Boolean(draft.privateKey)
        : draft.password !== initial.password && Boolean(draft.password)
    ));
  const changedLabel = changedAt ? describeAge(changedAt) : "还没有填写";

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!draft.title.trim()) return;
    if (draft.kind === "server" && !draft.host.trim()) return;
    onSave({ ...draft, title: draft.title.trim() });
  };

  return (
    <div className="dialog-backdrop">
      <section
        className="vault-item-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="vault-item-title"
      >
        <div className="dialog-header">
          <div>
            <span className="type-label">{vaultKindLabels[draft.kind]}</span>
            <h2 id="vault-item-title">{isNew ? `新建${vaultKindLabels[draft.kind]}` : draft.title || "未命名"}</h2>
          </div>
          <button
            type="button"
            className="icon-button"
            aria-label="关闭"
            disabled={busy}
            onClick={() => {
              if (!dirty || window.confirm("有未保存的修改，确定放弃吗？")) onClose();
            }}
          >×</button>
        </div>
        <form className="vault-form" onSubmit={handleSubmit} autoComplete="off">
          {reminders.length > 0 && (
            <ul className="vault-dialog-reminders" aria-label="这一条的提醒">
              {reminders.map((reminder) => (
                <li key={reminder.type} className={reminder.level}>
                  <strong>{reminderLabels[reminder.type]}</strong>
                  <span>{reminder.message}</span>
                </li>
              ))}
            </ul>
          )}
          <label className="vault-field">
            <span className="vault-field-label"><span>名称</span></span>
            <input
              ref={titleRef}
              value={draft.title}
              onChange={(event) => update("title", event.target.value)}
              placeholder={
                draft.kind === "login"
                  ? "例如：GitHub"
                  : draft.kind === "secret"
                    ? "例如：OpenAI API Key"
                    : draft.kind === "server"
                      ? "例如：阿里云 ECS · 博客服务器"
                      : "例如：GitHub 两步验证"
              }
              maxLength={200}
              required
            />
          </label>

          {draft.kind === "login" && (
            <>
              <label className="vault-field">
                <span className="vault-field-label">
                  <span>用户名或邮箱</span>
                  <button type="button" onClick={() => onCopy(draft.username, "用户名")} disabled={!draft.username}>复制</button>
                </span>
                <input
                  value={draft.username}
                  onChange={(event) => update("username", event.target.value)}
                  autoComplete="off"
                  spellCheck={false}
                />
              </label>
              <SecretInput
                label="密码"
                value={draft.password}
                onChange={(value) => update("password", value)}
                onCopy={() => onCopy(draft.password, "密码")}
                onGenerate={() => update("password", generatePassword())}
              />
              {!draft.skipChecks && isWeakPassword(draft.password) && (
                <small className="vault-hint warn vault-weak-hint">
                  密码偏弱：至少 12 位并混合大小写、数字和符号更安全，也可以点「生成」。
                </small>
              )}
              <label className="vault-field">
                <span className="vault-field-label"><span>网址</span></span>
                <input
                  value={draft.url}
                  onChange={(event) => update("url", event.target.value)}
                  inputMode="url"
                  autoComplete="off"
                  placeholder="https://"
                />
              </label>
            </>
          )}

          {draft.kind === "secret" && (
            <SecretInput
              label="密钥内容"
              value={draft.secret}
              onChange={(value) => update("secret", value)}
              onCopy={() => onCopy(draft.secret, "密钥")}
              multiline
            />
          )}

          {draft.kind === "server" && (
            <>
              <div className="vault-server-address">
                <label className="vault-field">
                  <span className="vault-field-label"><span>主机</span></span>
                  <input
                    value={draft.host}
                    onChange={(event) => update("host", event.target.value)}
                    autoComplete="off"
                    spellCheck={false}
                    placeholder="203.0.113.10 或 vps.example.com"
                    required
                  />
                </label>
                <label className="vault-field vault-port-field">
                  <span className="vault-field-label"><span>端口</span></span>
                  <input
                    value={draft.port}
                    onChange={(event) => update("port", event.target.value.replace(/[^0-9]/g, "").slice(0, 5))}
                    inputMode="numeric"
                    autoComplete="off"
                    placeholder="22"
                  />
                </label>
              </div>
              <label className="vault-field">
                <span className="vault-field-label">
                  <span>登录用户</span>
                  <button type="button" onClick={() => onCopy(draft.username, "用户名")} disabled={!draft.username}>复制</button>
                </span>
                <input
                  value={draft.username}
                  onChange={(event) => update("username", event.target.value)}
                  autoComplete="off"
                  spellCheck={false}
                  placeholder="root"
                />
              </label>
              <fieldset className="vault-auth-method">
                <legend>登录方式</legend>
                {([
                  ["password", "密码"],
                  ["key", "SSH 私钥"],
                ] as const).map(([value, label]) => (
                  <label key={value}>
                    <input
                      type="radio"
                      name="server-auth-method"
                      checked={draft.authMethod === value}
                      onChange={() => update("authMethod", value)}
                    />
                    {label}
                  </label>
                ))}
              </fieldset>
              {draft.authMethod === "password" ? (
                <SecretInput
                  label="登录密码"
                  value={draft.password}
                  onChange={(value) => update("password", value)}
                  onCopy={() => onCopy(draft.password, "密码")}
                  onGenerate={() => update("password", generatePassword())}
                />
              ) : (
                <>
                  <SecretInput
                    label="SSH 私钥"
                    value={draft.privateKey}
                    onChange={(value) => update("privateKey", value)}
                    onCopy={() => onCopy(draft.privateKey, "私钥")}
                    multiline
                  />
                  <SecretInput
                    label="私钥口令（可选）"
                    value={draft.keyPassphrase}
                    onChange={(value) => update("keyPassphrase", value)}
                    onCopy={() => onCopy(draft.keyPassphrase, "私钥口令")}
                  />
                </>
              )}
            </>
          )}

          {(draft.kind === "login" || draft.kind === "secret" || draft.kind === "server") && (
            <ReminderFields
              draft={draft}
              changedLabel={changedLabel}
              secretChanged={secretChanged}
              onChange={update}
            />
          )}

          {draft.kind === "recovery" && (
            <>
              <label className="vault-field">
                <span className="vault-field-label"><span>对应账号</span></span>
                <input
                  value={draft.account}
                  onChange={(event) => update("account", event.target.value)}
                  autoComplete="off"
                  placeholder="例如：me@example.com"
                />
              </label>
              <RecoveryCodeEditor
                codes={draft.codes}
                onChange={(codes) => update("codes", codes)}
                onCopy={(code) => onCopy(code, "恢复码")}
              />
            </>
          )}

          <label className="vault-field">
            <span className="vault-field-label"><span>备注</span></span>
            <textarea
              value={draft.notes}
              onChange={(event) => update("notes", event.target.value)}
              rows={3}
              maxLength={10_000}
            />
          </label>

          {error && <p className="vault-error" role="alert">{error}</p>}
          <div className="dialog-actions vault-dialog-actions">
            {!isNew && (
              <button type="button" className="danger-button" onClick={onDelete} disabled={busy}>
                删除
              </button>
            )}
            <span className="vault-dialog-spacer" />
            <button type="submit" className="primary" disabled={busy || !draft.title.trim() || (!dirty && !isNew)}>
              {busy ? "加密保存中…" : "保存"}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
