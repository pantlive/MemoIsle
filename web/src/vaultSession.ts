// 解锁后的库密钥只放在内存里：刷新页面、退出登录或闲置超时都会锁定。
// 放在模块里而不是组件状态里，离开密码库页面再回来不必重新输入主密码。

export const VAULT_AUTO_LOCK_MS = 5 * 60_000;

let sessionKey: CryptoKey | null = null;
let lockTimer: number | null = null;
const listeners = new Set<() => void>();

function notify(): void {
  for (const listener of listeners) listener();
}

function scheduleLock(): void {
  if (lockTimer !== null) window.clearTimeout(lockTimer);
  lockTimer = window.setTimeout(lockVaultSession, VAULT_AUTO_LOCK_MS);
}

export function getVaultSessionKey(): CryptoKey | null {
  return sessionKey;
}

export function startVaultSession(key: CryptoKey): void {
  sessionKey = key;
  scheduleLock();
  notify();
}

export function lockVaultSession(): void {
  if (lockTimer !== null) window.clearTimeout(lockTimer);
  lockTimer = null;
  if (sessionKey === null) return;
  sessionKey = null;
  notify();
}

// 用户在密码库里有操作时顺延自动锁定。
export function touchVaultSession(): void {
  if (sessionKey !== null) scheduleLock();
}

export function subscribeVaultSession(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
