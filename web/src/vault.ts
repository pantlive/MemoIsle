// 密码库的浏览器端加密。主密码和库密钥都不离开浏览器，服务器只收到密文。
//
// 主密码 --PBKDF2-SHA256--> 包裹密钥 --AES-GCM 包裹--> 随机库密钥 --AES-GCM--> 每个条目
// 更改主密码只需重新包裹库密钥，条目不必重新加密。

import type { VaultItemRecord, VaultKeyMaterial, VaultStatus } from "./api";

export const VAULT_KDF = "pbkdf2-sha256";
export const VAULT_ITERATIONS = 600_000;
export const MIN_MASTER_PASSWORD_LENGTH = 10;
const KEY_WRAP_AAD = "memoisle-vault-key:v1";
const ITEM_AAD_PREFIX = "memoisle-vault-item:v1:";
const MAX_RECOVERY_CODES = 100;

export type VaultKind = "login" | "secret" | "recovery" | "server" | "subscription";

export const subscriptionProviderLabels = {
  claude: "Claude",
  chatgpt: "ChatGPT",
  grok: "Grok",
  other: "其他",
} as const;

export type SubscriptionProvider = keyof typeof subscriptionProviderLabels;

export const subscriptionProviderUrls: Record<SubscriptionProvider, string> = {
  claude: "https://claude.ai",
  chatgpt: "https://chatgpt.com",
  grok: "https://grok.com",
  other: "",
};

// 订阅信息全部放在加密 JSON 中，账号和金额也不进入明文 API 字段。
export interface VaultSubscriptionData extends VaultReminderSettings {
  kind: "subscription";
  title: string;
  provider: SubscriptionProvider;
  plan: string;
  account: string;
  password: string;
  url: string;
  startedOn: string;
  billingCycle: "monthly" | "yearly" | "none";
  price: string;
  balance: string;
  currency: string;
  notes: string;
}

export interface RecoveryCode {
  code: string;
  used: boolean;
}

// 提醒设置和条目一起加密，服务器看不到哪些密码过期、多久没换。
export interface VaultReminderSettings {
  // 密码或密钥上次变化的时间（ISO）；旧条目没有记录时按创建时间算。
  changedAt: string;
  // 每隔多少天提醒更换，0 表示不提醒。
  rotateDays: number;
  // 到期日 YYYY-MM-DD，留空表示不会过期。
  expiresOn: string;
}

export const VAULT_ROTATE_OPTIONS = [0, 30, 90, 180, 365] as const;

export interface VaultLoginData extends VaultReminderSettings {
  kind: "login";
  title: string;
  username: string;
  password: string;
  url: string;
  notes: string;
  // 不检查强度和重复，用于故意保留的简单密码（如门禁 PIN）。
  skipChecks: boolean;
}

export interface VaultSecretData extends VaultReminderSettings {
  kind: "secret";
  title: string;
  secret: string;
  notes: string;
}

export interface VaultRecoveryData {
  kind: "recovery";
  title: string;
  account: string;
  codes: RecoveryCode[];
  notes: string;
}

// SSH 登录方式决定「密码」和「私钥」哪个字段生效。
export type ServerAuthMethod = "password" | "key";

export interface VaultServerData extends VaultReminderSettings {
  kind: "server";
  title: string;
  /** 主机名或 IP，例如 203.0.113.10 或 vps.example.com。 */
  host: string;
  /** SSH 端口，通常 22。 */
  port: string;
  username: string;
  authMethod: ServerAuthMethod;
  /** authMethod === "password" 时使用。 */
  password: string;
  /** authMethod === "key" 时使用的私钥内容（PEM / OpenSSH）。 */
  privateKey: string;
  /** 私钥的口令，可为空。 */
  keyPassphrase: string;
  notes: string;
}

export type VaultItemData =
  | VaultLoginData
  | VaultSecretData
  | VaultRecoveryData
  | VaultServerData
  | VaultSubscriptionData;

export interface VaultEntry {
  id: string;
  version: number;
  createdAt: string;
  updatedAt: string;
  data: VaultItemData;
}

const encoder = new TextEncoder();
const decoder = new TextDecoder();

function toBase64(bytes: ArrayBuffer | Uint8Array): string {
  const view = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  let binary = "";
  for (const byte of view) binary += String.fromCharCode(byte);
  return btoa(binary);
}

function fromBase64(text: string): Uint8Array<ArrayBuffer> {
  const binary = atob(text);
  const bytes = new Uint8Array(new ArrayBuffer(binary.length));
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes;
}

function randomBytes(length: number): Uint8Array<ArrayBuffer> {
  return crypto.getRandomValues(new Uint8Array(new ArrayBuffer(length)));
}

// 统一 Unicode 形式，同一主密码在不同设备、输入法下派生出同一把密钥。
function passwordBytes(password: string): Uint8Array<ArrayBuffer> {
  const encoded = encoder.encode(password.normalize("NFC"));
  const bytes = new Uint8Array(new ArrayBuffer(encoded.length));
  bytes.set(encoded);
  return bytes;
}

function utf8(text: string): Uint8Array<ArrayBuffer> {
  const encoded = encoder.encode(text);
  const bytes = new Uint8Array(new ArrayBuffer(encoded.length));
  bytes.set(encoded);
  return bytes;
}

async function deriveWrappingKey(
  password: string,
  salt: Uint8Array<ArrayBuffer>,
  iterations: number,
): Promise<CryptoKey> {
  const material = await crypto.subtle.importKey(
    "raw",
    passwordBytes(password),
    "PBKDF2",
    false,
    ["deriveKey"],
  );
  return crypto.subtle.deriveKey(
    { name: "PBKDF2", hash: "SHA-256", salt, iterations },
    material,
    { name: "AES-GCM", length: 256 },
    false,
    ["wrapKey", "unwrapKey"],
  );
}

async function wrapVaultKey(
  vaultKey: CryptoKey,
  password: string,
): Promise<VaultKeyMaterial> {
  const salt = randomBytes(16);
  const iv = randomBytes(12);
  const wrappingKey = await deriveWrappingKey(password, salt, VAULT_ITERATIONS);
  const wrapped = await crypto.subtle.wrapKey("raw", vaultKey, wrappingKey, {
    name: "AES-GCM",
    iv,
    additionalData: utf8(KEY_WRAP_AAD),
  });
  return {
    kdf: VAULT_KDF,
    kdf_iterations: VAULT_ITERATIONS,
    kdf_salt: toBase64(salt),
    wrapped_key: toBase64(wrapped),
    wrap_iv: toBase64(iv),
  };
}

export class WrongMasterPasswordError extends Error {
  constructor() {
    super("主密码不正确。");
  }
}

// extractable 只在更改主密码时为 true；平时的会话密钥不可导出，页面脚本也拿不到原始字节。
async function unwrapVaultKey(
  password: string,
  status: VaultStatus,
  extractable: boolean,
): Promise<CryptoKey> {
  if (!status.kdf_salt || !status.wrapped_key || !status.wrap_iv || !status.kdf_iterations) {
    throw new Error("密码库参数不完整。");
  }
  if (status.kdf !== VAULT_KDF) {
    throw new Error("不支持的密码库格式，请更新 MemoIsle。");
  }
  const wrappingKey = await deriveWrappingKey(
    password,
    fromBase64(status.kdf_salt),
    status.kdf_iterations,
  );
  try {
    return await crypto.subtle.unwrapKey(
      "raw",
      fromBase64(status.wrapped_key),
      wrappingKey,
      { name: "AES-GCM", iv: fromBase64(status.wrap_iv), additionalData: utf8(KEY_WRAP_AAD) },
      { name: "AES-GCM", length: 256 },
      extractable,
      ["encrypt", "decrypt"],
    );
  } catch {
    // AES-GCM 认证失败只可能是主密码错误或数据被篡改。
    throw new WrongMasterPasswordError();
  }
}

export async function createVaultKey(
  password: string,
): Promise<{ material: VaultKeyMaterial; key: CryptoKey }> {
  const vaultKey = await crypto.subtle.generateKey(
    { name: "AES-GCM", length: 256 },
    true,
    ["encrypt", "decrypt"],
  );
  const material = await wrapVaultKey(vaultKey, password);
  // 用刚生成的参数解开一次，既验证可用，也换成不可导出的会话密钥。
  const key = await unwrapVaultKey(
    password,
    { configured: true, version: 1, item_count: 0, ...material },
    false,
  );
  return { material, key };
}

export async function unlockVault(password: string, status: VaultStatus): Promise<CryptoKey> {
  return unwrapVaultKey(password, status, false);
}

export async function rewrapVaultKey(
  currentPassword: string,
  newPassword: string,
  status: VaultStatus,
): Promise<{ material: VaultKeyMaterial; key: CryptoKey }> {
  const exportable = await unwrapVaultKey(currentPassword, status, true);
  const material = await wrapVaultKey(exportable, newPassword);
  const key = await unwrapVaultKey(
    newPassword,
    { ...status, ...material },
    false,
  );
  return { material, key };
}

// 附加认证数据绑定条目 ID，服务器无法把一条密文挪到另一条上冒充。
function itemAad(id: string): Uint8Array<ArrayBuffer> {
  return utf8(`${ITEM_AAD_PREFIX}${id}`);
}

export async function encryptVaultItem(
  key: CryptoKey,
  id: string,
  data: VaultItemData,
): Promise<{ ciphertext: string; iv: string }> {
  const iv = randomBytes(12);
  // 写入和读取都校验订阅字段，避免将非法日期或金额存入密文。
  const normalized = data.kind === "subscription" ? normalizeItemData({ ...data }) : data;
  const plaintext = utf8(JSON.stringify({ v: 1, ...normalized }));
  const ciphertext = await crypto.subtle.encrypt(
    { name: "AES-GCM", iv, additionalData: itemAad(id) },
    key,
    plaintext,
  );
  return { ciphertext: toBase64(ciphertext), iv: toBase64(iv) };
}

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function subscriptionDate(value: unknown): string {
  const date = text(value);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) return "";
  const parsed = new Date(`${date}T00:00:00Z`);
  // 日期必须真实存在，不能让 2 月 30 日自动滚动成 3 月。
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === date ? date : "";
}

function subscriptionAmount(value: unknown): string {
  const amount = text(value);
  return /^\d{1,9}(\.\d{1,2})?$/.test(amount) ? amount : "";
}

function reminderSettings(raw: Record<string, unknown>): VaultReminderSettings {
  const changedAt = text(raw.changedAt);
  const expiresOn = text(raw.expiresOn);
  return {
    changedAt: Number.isNaN(Date.parse(changedAt)) ? "" : changedAt,
    rotateDays: (VAULT_ROTATE_OPTIONS as readonly unknown[]).includes(raw.rotateDays)
      ? raw.rotateDays as number
      : 0,
    expiresOn: /^\d{4}-\d{2}-\d{2}$/.test(expiresOn) ? expiresOn : "",
  };
}

// 解密后按类型补齐字段，旧版本或缺字段的数据也能正常显示。
function normalizeItemData(raw: Record<string, unknown>): VaultItemData {
  const title = text(raw.title) || "未命名";
  const notes = text(raw.notes);
  if (raw.kind === "subscription") {
    const provider = raw.provider;
    return {
      kind: "subscription",
      title,
      provider: provider === "claude" || provider === "chatgpt" || provider === "grok"
        ? provider : "other",
      plan: text(raw.plan),
      account: text(raw.account),
      password: text(raw.password),
      url: text(raw.url),
      startedOn: subscriptionDate(raw.startedOn),
      billingCycle: raw.billingCycle === "yearly" || raw.billingCycle === "none"
        ? raw.billingCycle : "monthly",
      price: subscriptionAmount(raw.price),
      balance: subscriptionAmount(raw.balance),
      currency: /^[A-Z]{3}$/.test(text(raw.currency)) ? text(raw.currency) : "USD",
      notes,
      ...reminderSettings(raw),
      expiresOn: subscriptionDate(raw.expiresOn),
    };
  }
  if (raw.kind === "secret") {
    return { kind: "secret", title, secret: text(raw.secret), notes, ...reminderSettings(raw) };
  }
  if (raw.kind === "server") {
    const port = text(raw.port);
    return {
      kind: "server",
      title,
      host: text(raw.host),
      // 端口只接受 1-65535，越界或 0 回落到 22。
      port:
        /^[0-9]{1,5}$/.test(port)
        && Number(port) >= 1
        && Number(port) <= 65535
          ? port
          : "22",
      username: text(raw.username),
      authMethod: raw.authMethod === "key" ? "key" : "password",
      password: text(raw.password),
      privateKey: text(raw.privateKey),
      keyPassphrase: text(raw.keyPassphrase),
      notes,
      ...reminderSettings(raw),
    };
  }
  if (raw.kind === "recovery") {
    const codes = Array.isArray(raw.codes)
      ? raw.codes
        .filter((item): item is Record<string, unknown> => typeof item === "object" && item !== null)
        .map((item) => ({ code: text(item.code), used: item.used === true }))
        .filter((item) => item.code)
      : [];
    return { kind: "recovery", title, account: text(raw.account), codes, notes };
  }
  return {
    kind: "login",
    title,
    username: text(raw.username),
    password: text(raw.password),
    url: text(raw.url),
    notes,
    skipChecks: raw.skipChecks === true,
    ...reminderSettings(raw),
  };
}

export class VaultDecryptError extends Error {
  constructor() {
    super("有条目无法解密，可能已损坏或被篡改。");
  }
}

export async function decryptVaultItem(
  key: CryptoKey,
  record: VaultItemRecord,
): Promise<VaultEntry> {
  let plaintext: ArrayBuffer;
  try {
    plaintext = await crypto.subtle.decrypt(
      { name: "AES-GCM", iv: fromBase64(record.iv), additionalData: itemAad(record.id) },
      key,
      fromBase64(record.ciphertext),
    );
  } catch {
    throw new VaultDecryptError();
  }
  const raw = JSON.parse(decoder.decode(plaintext)) as Record<string, unknown>;
  return {
    id: record.id,
    version: record.version,
    createdAt: record.created_at,
    updatedAt: record.updated_at,
    data: normalizeItemData(raw),
  };
}

const LOWER = "abcdefghijkmnopqrstuvwxyz";
const UPPER = "ABCDEFGHJKLMNPQRSTUVWXYZ";
const DIGITS = "23456789";
const SYMBOLS = "!@#$%^&*-_=+?";

// 拒绝采样保证每个字符等概率；去掉了 l/1/O/0 这类易混字符。
function randomChar(alphabet: string): string {
  const limit = 256 - (256 % alphabet.length);
  for (;;) {
    const [byte] = crypto.getRandomValues(new Uint8Array(1));
    if (byte < limit) return alphabet[byte % alphabet.length];
  }
}

export function generatePassword(length = 20, useSymbols = true): string {
  const groups = useSymbols ? [LOWER, UPPER, DIGITS, SYMBOLS] : [LOWER, UPPER, DIGITS];
  const alphabet = groups.join("");
  for (;;) {
    const candidate = Array.from({ length }, () => randomChar(alphabet)).join("");
    if (groups.every((group) => [...candidate].some((char) => group.includes(char)))) {
      return candidate;
    }
  }
}

// 网站给的恢复码通常按空格、换行或逗号分隔，粘贴整段即可。
export function parseRecoveryCodes(input: string, existing: RecoveryCode[] = []): RecoveryCode[] {
  const seen = new Set(existing.map((item) => item.code));
  const added: RecoveryCode[] = [];
  for (const piece of input.split(/[\s,，;；]+/)) {
    const code = piece.trim();
    if (!code || seen.has(code)) continue;
    seen.add(code);
    added.push({ code, used: false });
  }
  return [...existing, ...added].slice(0, MAX_RECOVERY_CODES);
}

export function emptyVaultItem(kind: VaultKind): VaultItemData {
  const reminders: VaultReminderSettings = { changedAt: "", rotateDays: 0, expiresOn: "" };
  if (kind === "subscription") {
    return {
      kind,
      title: "",
      provider: "claude",
      plan: "",
      account: "",
      password: "",
      url: subscriptionProviderUrls.claude,
      startedOn: "",
      billingCycle: "monthly",
      price: "",
      balance: "",
      currency: "USD",
      notes: "",
      ...reminders,
    };
  }
  if (kind === "secret") return { kind, title: "", secret: "", notes: "", ...reminders };
  if (kind === "recovery") return { kind, title: "", account: "", codes: [], notes: "" };
  if (kind === "server") {
    return {
      kind,
      title: "",
      host: "",
      port: "22",
      username: "root",
      authMethod: "password",
      password: "",
      privateKey: "",
      keyPassphrase: "",
      notes: "",
      ...reminders,
    };
  }
  return {
    kind,
    title: "",
    username: "",
    password: "",
    url: "",
    notes: "",
    skipChecks: false,
    ...reminders,
  };
}

// 保存时密码或密钥有变化，就把「上次更换」记为现在。
export function stampSecretChange(
  previous: VaultItemData | null,
  next: VaultItemData,
  now = new Date().toISOString(),
): VaultItemData {
  if (next.kind === "login" || next.kind === "subscription") {
    const before = previous?.kind === next.kind ? previous.password : "";
    if (next.password && next.password !== before) return { ...next, changedAt: now };
  }
  if (next.kind === "secret") {
    const before = previous?.kind === "secret" ? previous.secret : "";
    if (next.secret && next.secret !== before) return { ...next, changedAt: now };
  }
  if (next.kind === "server") {
    // 密码或私钥任一变化都算「换过凭据」。
    const before = previous?.kind === "server" ? previous : null;
    const credential = next.authMethod === "key" ? next.privateKey : next.password;
    const previousCredential = before
      ? before.authMethod === "key" ? before.privateKey : before.password
      : "";
    if (credential && credential !== previousCredential) {
      return { ...next, changedAt: now };
    }
  }
  return next;
}

export const vaultKindLabels: Record<VaultKind, string> = {
  login: "账号密码",
  secret: "密钥",
  recovery: "恢复码",
  server: "云服务器",
  subscription: "AI 订阅",
};

// 加密备份：直接保存服务器上的密文和导出时的包裹参数，文件里没有任何明文。
// 恢复时用导出那一刻的主密码解开，再用当前库密钥重新加密写入。
export const VAULT_BACKUP_FORMAT = "memoisle-vault-backup";
const MAX_BACKUP_BYTES = 20 * 1024 * 1024;

export interface VaultBackupFile {
  format: typeof VAULT_BACKUP_FORMAT;
  version: 1;
  exported_at: string;
  kdf: string;
  kdf_iterations: number;
  kdf_salt: string;
  wrapped_key: string;
  wrap_iv: string;
  items: { id: string; iv: string; ciphertext: string }[];
}

export function buildVaultBackup(status: VaultStatus, records: VaultItemRecord[]): VaultBackupFile {
  if (!status.kdf || !status.kdf_iterations || !status.kdf_salt || !status.wrapped_key || !status.wrap_iv) {
    throw new Error("密码库参数不完整，无法导出。");
  }
  return {
    format: VAULT_BACKUP_FORMAT,
    version: 1,
    exported_at: new Date().toISOString(),
    kdf: status.kdf,
    kdf_iterations: status.kdf_iterations,
    kdf_salt: status.kdf_salt,
    wrapped_key: status.wrapped_key,
    wrap_iv: status.wrap_iv,
    items: records.map(({ id, iv, ciphertext }) => ({ id, iv, ciphertext })),
  };
}

function isBase64(value: unknown): value is string {
  if (typeof value !== "string" || !value) return false;
  try {
    atob(value);
    return true;
  } catch {
    return false;
  }
}

export function parseVaultBackup(text: string): VaultBackupFile {
  if (text.length > MAX_BACKUP_BYTES) throw new Error("备份文件过大。");
  let raw: Record<string, unknown>;
  try {
    raw = JSON.parse(text) as Record<string, unknown>;
  } catch {
    throw new Error("不是有效的 JSON 文件。");
  }
  if (raw?.format !== VAULT_BACKUP_FORMAT) {
    throw new Error("这不是 MemoIsle 密码库备份文件。");
  }
  if (raw.version !== 1) throw new Error("备份文件版本不受支持，请更新 MemoIsle。");
  const items = Array.isArray(raw.items) ? raw.items : null;
  const keyFieldsValid = raw.kdf === VAULT_KDF
    && typeof raw.kdf_iterations === "number"
    && raw.kdf_iterations >= VAULT_ITERATIONS
    && isBase64(raw.kdf_salt)
    && isBase64(raw.wrapped_key)
    && isBase64(raw.wrap_iv);
  const itemsValid = items?.every((item) => (
    typeof item === "object" && item !== null
    && typeof (item as Record<string, unknown>).id === "string"
    && isBase64((item as Record<string, unknown>).iv)
    && isBase64((item as Record<string, unknown>).ciphertext)
  ));
  if (!keyFieldsValid || !items || !itemsValid) throw new Error("备份文件已损坏或格式不完整。");
  return raw as unknown as VaultBackupFile;
}

export async function openVaultBackup(
  password: string,
  backup: VaultBackupFile,
): Promise<{ items: VaultItemData[]; failed: number }> {
  const key = await unlockVault(password, {
    configured: true,
    version: null,
    item_count: backup.items.length,
    kdf: backup.kdf,
    kdf_iterations: backup.kdf_iterations,
    kdf_salt: backup.kdf_salt,
    wrapped_key: backup.wrapped_key,
    wrap_iv: backup.wrap_iv,
  });
  const results = await Promise.allSettled(backup.items.map((item) => decryptVaultItem(key, {
    ...item,
    version: 1,
    created_at: backup.exported_at,
    updated_at: backup.exported_at,
  })));
  const items = results
    .filter((result): result is PromiseFulfilledResult<VaultEntry> => result.status === "fulfilled")
    .map((result) => result.value.data);
  return { items, failed: results.length - items.length };
}

// 用于导入去重：同类型、同内容的条目视为重复。
export function vaultItemFingerprint(data: VaultItemData): string {
  return JSON.stringify(data);
}
