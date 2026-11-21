// 密码提醒：解锁后在浏览器里根据明文条目计算，不上传任何结果。

import { resolveServerPrivateKey, type VaultEntry, type VaultItemData } from "./vault";
import { t } from "./i18n";

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
  | "codes-low"
  | "missing-key";

export interface VaultReminder {
  entryId: string;
  title: string;
  type: VaultReminderType;
  level: VaultReminderLevel;
  message: string;
}

export const reminderLabels: Record<VaultReminderType, string> = {
  get expired() { return t("已过期"); },
  get expiring() { return t("即将到期"); },
  get rotate() { return t("该更换了"); },
  get "rotate-soon"() { return t("快该换了"); },
  get reused() { return t("重复密码"); },
  get weak() { return t("弱密码"); },
  get "codes-empty"() { return t("恢复码用完"); },
  get "codes-low"() { return t("恢复码不足"); },
  get "missing-key"() { return t("密钥缺失"); },
};

function localMidnight(date: Date): number {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
}

// expiresOn 是本地日期，按本地日历算相差天数。
export function daysUntilDate(isoDate: string, now = new Date()): number {
  const [year, month, day] = isoDate.split("-").map(Number);
  return Math.round((new Date(year, month - 1, day).getTime() - localMidnight(now)) / DAY_MS);
}

export function lastChangedAt(
  entry: Pick<VaultEntry, "createdAt" | "data">,
  entries: VaultEntry[] = [],
): string {
  const { data } = entry;
  // 服务器跟随原密钥的轮换时间，旧密钥没有记录时按其创建时间算。
  if (data.kind === "server" && data.authMethod === "key" && data.privateKeyRef) {
    const target = entries.find((item) => item.id === data.privateKeyRef && item.data.kind === "secret");
    if (target) return lastChangedAt(target);
  }
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

function hasSecretValue(data: VaultItemData, entries: VaultEntry[]): boolean {
  if (data.kind === "login") return Boolean(data.password);
  if (data.kind === "secret") return Boolean(data.secret);
  if (data.kind === "server") {
    return Boolean(data.authMethod === "key" ? resolveServerPrivateKey(data, entries).value : data.password);
  }
  return false;
}

function quoteTitles(titles: string[]): string {
  const shown = titles.slice(0, 2).map((title) => t("「{title}」", { title })).join("");
  return titles.length > 2 ? t("{shown}等 {length} 条", { shown, length: titles.length }) : shown;
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
        add(entry, "codes-empty", "danger", t("恢复码已全部用完，请到网站重新生成一组。"));
      } else if (remaining <= LOW_RECOVERY_CODES) {
        add(entry, "codes-low", "warn", t("只剩 {remaining} 个可用恢复码，建议重新生成一组。", { remaining }));
      }
      continue;
    }

    if (data.kind === "server" && data.authMethod === "key"
      && resolveServerPrivateKey(data, entries).missing) {
      add(entry, "missing-key", "danger", t("引用的密钥已被删除，请重新选择或直接填写私钥。"));
    }
    const hasSecret = hasSecretValue(data, entries);
    // 订阅按到期日提醒续费。
    if (data.expiresOn && (data.kind === "subscription" || hasSecret)) {
      const days = daysUntilDate(data.expiresOn, now);
      if (days < 0) {
        add(entry, "expired", "danger", data.kind === "subscription"
          ? t("已于 {expiresOn} 到期（{value} 天前），请续费或更新到期日。", { expiresOn: data.expiresOn, value: -days })
          : t("已于 {expiresOn} 过期（{value} 天前），请更换。", { expiresOn: data.expiresOn, value: -days }));
      } else if (days === 0) {
        add(entry, "expired", "danger", data.kind === "subscription"
          ? t("今天到期，请确认续费。")
          : t("今天到期，请尽快更换。"));
      } else if (days <= EXPIRY_WARN_DAYS) {
        add(entry, "expiring", "warn", data.kind === "subscription"
          ? t("{days} 天后到期续费（{expiresOn}）。", { days, expiresOn: data.expiresOn })
          : t("{days} 天后到期（{expiresOn}）。", { days, expiresOn: data.expiresOn }));
      }
    }
    // 定期更换仍然只检查已经填写的密码或密钥。
    if (data.kind !== "subscription" && hasSecret && data.rotateDays > 0) {
      const age = daysSince(lastChangedAt(entry, entries), now);
      const left = data.rotateDays - age;
      if (left <= 0) {
        add(entry, "rotate", "danger", t("已 {age} 天没有更换，设定为每 {rotateDays} 天换一次。", { age, rotateDays: data.rotateDays }));
      } else if (left <= ROTATE_WARN_DAYS) {
        add(entry, "rotate-soon", "warn", t("{left} 天后到了更换周期（每 {rotateDays} 天）。", { left, rotateDays: data.rotateDays }));
      }
    }

    if (data.kind === "login" && !data.skipChecks && data.password) {
      const others = (byPassword.get(data.password) ?? []).filter((item) => item.id !== entry.id);
      if (others.length > 0) {
        add(entry, "reused", "danger", t("和{value}用的是同一个密码。", { value: quoteTitles(others.map((item) => item.data.title)) }));
      }
      if (isWeakPassword(data.password)) {
        add(entry, "weak", "warn", t("密码偏弱，建议用「生成」换成 20 位随机密码。"));
      }
    }
  }

  return reminders.sort((left, right) => (
    (left.level === right.level ? 0 : left.level === "danger" ? -1 : 1)
    || left.title.localeCompare(right.title, "zh-CN")
  ));
}
