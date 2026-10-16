import { useSyncExternalStore } from "react";

// 解锁时记下有几条需要处理，锁定后导航仍能提示。只存一个数字，不含任何条目信息。
const STORAGE_KEY = "memoisle_vault_reminder_count";
const CHANGE_EVENT = "memoisle-vault-reminders";

export function readVaultReminderCount(): number {
  try {
    const value = Number(window.localStorage.getItem(STORAGE_KEY));
    return Number.isFinite(value) && value > 0 ? Math.floor(value) : 0;
  } catch {
    return 0;
  }
}

export function saveVaultReminderCount(count: number): void {
  try {
    if (count > 0) window.localStorage.setItem(STORAGE_KEY, String(count));
    else window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // 无法写入本地存储时只是不显示提示。
  }
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

function subscribe(listener: () => void): () => void {
  window.addEventListener(CHANGE_EVENT, listener);
  window.addEventListener("storage", listener);
  return () => {
    window.removeEventListener(CHANGE_EVENT, listener);
    window.removeEventListener("storage", listener);
  };
}

export function useVaultReminderCount(): number {
  return useSyncExternalStore(subscribe, readVaultReminderCount, () => 0);
}
