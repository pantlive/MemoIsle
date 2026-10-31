// 密码提醒：解锁后在浏览器里根据明文条目计算，不上传任何结果。

import type { VaultEntry, VaultItemData } from "./vault";

const DAY_MS = 86_400_000;
// 到期前多少天开始提醒。
const EXPIRY_WARN_DAYS = 14;
const ROTATE_WARN_DAYS = 7;
const LOW_RECOVERY_CODES = 2;

export type VaultReminderLevel = "danger" | "warn";

export type VaultReminderType =
  | "expired"
  | "expiring"
  | "rotate"
  | "rotate-soon"
  | "reused"
  | "weak"
  | "codes-empty"
  | "codes-low";

export interface VaultReminder {
  entryId: string;
  title: string;
  type: VaultReminderType;
  level: VaultReminderLevel;
  message: string;
}

export const reminderLabels: Record<VaultReminderType, string> = {
  expired: "已过期",
  expiring: "即将到期",
  rotate: "该更换了",
  "rotate-soon": "快该换了",
  reused: "重复密码",
  weak: "弱密码",
  "codes-empty": "恢复码用完",
  "codes-low": "恢复码不足",
};

function localMidnight(date: Date): number {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
}

// expiresOn 是本地日期，按本地日历算相差天数。
export function daysUntilDate(isoDate: string, now = new Date()): number {
  const [year, month, day] = isoDate.split("-").map(Number);
  return Math.round((new Date(year, month - 1, day).getTime() - localMidnight(now)) / DAY_MS);
}

export function lastChangedAt(entry: Pick<VaultEntry, "createdAt" | "data">): string {
  const { data } = entry;
  return (data.kind === "login" || data.kind === "secret" || data.kind === "server")
    && data.changedAt
    ? data.changedAt
    : entry.createdAt;
}

export function daysSince(iso: string, now = new Date()): number {
  return Math.max(0, Math.round((localMidnight(now) - localMidnight(new Date(iso))) / DAY_MS));
}

function characterClasses(password: string): number {
  return [/[a-z]/, /[A-Z]/, /\d/, /[^a-zA-Z\d]/].filter((pattern) => pattern.test(password)).length;
}

// 粗略判断：太短、字符种类太少，或整串都是同一个字符。
export function isWeakPassword(password: string): boolean {
  if (!password) return false;
  const length = [...password].length;
  if (length < 8) return true;
  if (new Set(password).size <= 2) return true;
  const classes = characterClasses(password);
  if (length < 12 && classes < 3) return true;
  return classes === 1 && length < 16;
}

function hasSecretValue(data: VaultItemData): boolean {
  if (data.kind === "login") return Boolean(data.password);
  if (data.kind === "secret") return Boolean(data.secret);
  if (data.kind === "server") {
    // 私钥和密码任一存在就算有凭据，用于到期与定期更换提醒。
    return Boolean(data.privateKey || data.password);
  }
  return false;
}

function quoteTitles(titles: string[]): string {
  const shown = titles.slice(0, 2).map((title) => `「${title}」`).join("");
  return titles.length > 2 ? `${shown}等 ${titles.length} 条` : shown;
}

export function collectVaultReminders(entries: VaultEntry[], now = new Date()): VaultReminder[] {
  const reminders: VaultReminder[] = [];
  const add = (entry: VaultEntry, type: VaultReminderType, level: VaultReminderLevel, message: string) => {
    reminders.push({ entryId: entry.id, title: entry.data.title, type, level, message });
  };

  const byPassword = new Map<string, VaultEntry[]>();
  for (const entry of entries) {
    const { data } = entry;
    if (data.kind === "login" && !data.skipChecks && data.password) {
      byPassword.set(data.password, [...(byPassword.get(data.password) ?? []), entry]);
    }
  }

  for (const entry of entries) {
    const { data } = entry;

    if (data.kind === "recovery") {
      if (data.codes.length === 0) continue;
      const remaining = data.codes.filter((item) => !item.used).length;
      if (remaining === 0) {
        add(entry, "codes-empty", "danger", "恢复码已全部用完，请到网站重新生成一组。");
      } else if (remaining <= LOW_RECOVERY_CODES) {
        add(entry, "codes-low", "warn", `只剩 ${remaining} 个可用恢复码，建议重新生成一组。`);
      }
      continue;
    }

    const hasSecret = hasSecretValue(data);
    // 订阅按到期日提醒续费。
    if (data.expiresOn && (data.kind === "subscription" || hasSecret)) {
      const days = daysUntilDate(data.expiresOn, now);
      if (days < 0) {
        add(entry, "expired", "danger", data.kind === "subscription"
          ? `已于 ${data.expiresOn} 到期（${-days} 天前），请续费或更新到期日。`
          : `已于 ${data.expiresOn} 过期（${-days} 天前），请更换。`);
      } else if (days === 0) {
        add(entry, "expired", "danger", data.kind === "subscription"
          ? "今天到期，请确认续费。"
          : "今天到期，请尽快更换。");
      } else if (days <= EXPIRY_WARN_DAYS) {
        add(entry, "expiring", "warn", data.kind === "subscription"
          ? `${days} 天后到期续费（${data.expiresOn}）。`
          : `${days} 天后到期（${data.expiresOn}）。`);
      }
    }
    // 定期更换仍然只检查已经填写的密码或密钥。
    if (data.kind !== "subscription" && hasSecret && data.rotateDays > 0) {
      const age = daysSince(lastChangedAt(entry), now);
      const left = data.rotateDays - age;
      if (left <= 0) {
        add(entry, "rotate", "danger", `已 ${age} 天没有更换，设定为每 ${data.rotateDays} 天换一次。`);
      } else if (left <= ROTATE_WARN_DAYS) {
        add(entry, "rotate-soon", "warn", `${left} 天后到了更换周期（每 ${data.rotateDays} 天）。`);
      }
    }

    if (data.kind === "login" && !data.skipChecks && data.password) {
      const others = (byPassword.get(data.password) ?? []).filter((item) => item.id !== entry.id);
      if (others.length > 0) {
        add(entry, "reused", "danger", `和${quoteTitles(others.map((item) => item.data.title))}用的是同一个密码。`);
      }
      if (isWeakPassword(data.password)) {
        add(entry, "weak", "warn", "密码偏弱，建议用「生成」换成 20 位随机密码。");
      }
    }
  }

  return reminders.sort((left, right) => (
    (left.level === right.level ? 0 : left.level === "danger" ? -1 : 1)
    || left.title.localeCompare(right.title, "zh-CN")
  ));
}
