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

export type VaultKind = "login" | "secret" | "recovery";

export interface RecoveryCode {
  code: string;
  used: boolean;
}

export interface VaultLoginData {
  kind: "login";
  title: string;
  username: string;
  password: string;
  url: string;
  notes: string;
}

export interface VaultSecretData {
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

export type VaultItemData = VaultLoginData | VaultSecretData | VaultRecoveryData;

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
  const plaintext = utf8(JSON.stringify({ v: 1, ...data }));
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

// 解密后按类型补齐字段，旧版本或缺字段的数据也能正常显示。
function normalizeItemData(raw: Record<string, unknown>): VaultItemData {
  const title = text(raw.title) || "未命名";
  const notes = text(raw.notes);
  if (raw.kind === "secret") {
    return { kind: "secret", title, secret: text(raw.secret), notes };
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
  if (kind === "secret") return { kind, title: "", secret: "", notes: "" };
  if (kind === "recovery") return { kind, title: "", account: "", codes: [], notes: "" };
  return { kind, title: "", username: "", password: "", url: "", notes: "" };
}

export const vaultKindLabels: Record<VaultKind, string> = {
  login: "账号密码",
  secret: "密钥",
  recovery: "恢复码",
};
