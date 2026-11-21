/**
 * 记账的纯函数：金额与「分」互转、月份加减与显示、预置分类。
 *
 * Android 端 `data/LedgerEntry.kt` 按同一套规则实现，两端测试用例保持一致。
 */

import type { LedgerKind } from "./types";
import { currentLocale, getLanguage, t } from "./i18n";

/** 单笔上限 10 亿元，与后端一致。 */
export const LEDGER_MAX_AMOUNT_CENTS = 100_000_000_000;
export const LEDGER_DEFAULT_CURRENCY = "CNY";
export const LEDGER_CATEGORY_MAX_LENGTH = 30;
export const LEDGER_ACCOUNT_MAX_LENGTH = 30;
export const LEDGER_NOTE_MAX_LENGTH = 500;

export const LEDGER_CURRENCIES = ["CNY", "USD", "EUR", "HKD", "JPY", "GBP"] as const;

export const ledgerKindLabels: Record<LedgerKind, string> = {
  get expense() { return t("支出"); },
  get income() { return t("收入"); },
};

/** 预置分类；用过的自定义分类由服务端 /ledger/categories 补充。 */
/** 预置分类按当前界面语言给出；分类是自由文本，选中后按显示的文字保存。 */
export const LEDGER_PRESET_CATEGORIES: Record<LedgerKind, readonly string[]> = {
  get expense() {
    return [t("餐饮"), t("交通"), t("购物"), t("订阅"), t("住房"), t("娱乐"), t("医疗"), t("其他")];
  },
  get income() {
    return [t("工资"), t("其他")];
  },
};

export function ledgerAccountSuggestions(): string[] {
  return [t("现金"), t("银行卡"), t("信用卡"), t("支付宝"), t("微信")];
}

export const currencyLabels: Record<string, string> = {
  get CNY() { return t("人民币"); },
  get USD() { return t("美元"); },
  get EUR() { return t("欧元"); },
  get HKD() { return t("港币"); },
  get JPY() { return t("日元"); },
  get GBP() { return t("英镑"); },
};

const currencySymbols: Record<string, string> = {
  CNY: "¥",
  USD: "$",
  EUR: "€",
  GBP: "£",
  HKD: "HK$",
  JPY: "JP¥",
};

const AMOUNT_PATTERN = /^(\d{1,9}|1000000000)(?:\.(\d{0,2}))?$/;
const MONTH_PATTERN = /^(\d{4})-(0[1-9]|1[0-2])$/;

/** 全角数字和全角句点换成半角，去掉空白、千分位逗号和货币符号。 */
function normalizeAmountText(input: string): string {
  return input
    .replace(/[０-９]/g, (char) => String.fromCharCode(char.charCodeAt(0) - 0xff10 + 48))
    .replace(/．/g, ".")
    .replace(/[\s,，¥￥$]/g, "");
}

/**
 * 把输入的金额换成分；最多两位小数，必须大于 0 且不超过上限，否则返回 null。
 * 只做整数运算，避免 0.1 + 0.2 这类浮点误差。
 */
export function parseAmountToCents(input: string): number | null {
  const text = normalizeAmountText(input);
  const match = AMOUNT_PATTERN.exec(text.startsWith(".") ? `0${text}` : text);
  if (!match) return null;
  const whole = Number(match[1]);
  const fraction = Number((match[2] ?? "").padEnd(2, "0"));
  const cents = whole * 100 + fraction;
  if (cents <= 0 || cents > LEDGER_MAX_AMOUNT_CENTS) return null;
  return cents;
}

/** 分 -> 带千分位、两位小数的金额，例如 123456 -> "1,234.56"，负数前加 "-"。 */
export function formatCents(cents: number): string {
  const sign = cents < 0 ? "-" : "";
  const absolute = Math.abs(Math.trunc(cents));
  const whole = Math.floor(absolute / 100).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const fraction = (absolute % 100).toString().padStart(2, "0");
  return `${sign}${whole}.${fraction}`;
}

/** 编辑时回填的金额：整数不带小数，例如 2500 -> "25"，2550 -> "25.50"。 */
export function centsToAmountInput(cents: number): string {
  const absolute = Math.abs(Math.trunc(cents));
  const whole = Math.floor(absolute / 100);
  const fraction = absolute % 100;
  return fraction === 0 ? String(whole) : `${whole}.${fraction.toString().padStart(2, "0")}`;
}

export function currencySymbol(currency: string): string {
  return currencySymbols[currency] ?? `${currency} `;
}

/** 带币种符号的金额，例如 ("CNY", -150) -> "-¥1.50"。 */
export function formatMoney(cents: number, currency: string): string {
  const formatted = formatCents(cents);
  return formatted.startsWith("-")
    ? `-${currencySymbol(currency)}${formatted.slice(1)}`
    : `${currencySymbol(currency)}${formatted}`;
}

/** 流水里的金额带方向符号：支出 "-¥25.50"，收入 "+¥25.50"。 */
export function formatSignedAmount(kind: LedgerKind, cents: number, currency: string): string {
  return `${kind === "income" ? "+" : "-"}${formatMoney(Math.abs(cents), currency)}`;
}

function pad2(value: number): string {
  return value.toString().padStart(2, "0");
}

export function isValidMonth(month: string): boolean {
  return MONTH_PATTERN.test(month);
}

/** 本地时区的当前月份 YYYY-MM。 */
export function monthOf(date: Date = new Date()): string {
  return `${date.getFullYear()}-${pad2(date.getMonth() + 1)}`;
}

/** 本地时区的日期 YYYY-MM-DD。 */
export function isoDateOf(date: Date = new Date()): string {
  return `${monthOf(date)}-${pad2(date.getDate())}`;
}

/** 月份加减，跨年自动进退位；输入不合法时原样返回。 */
export function shiftMonth(month: string, delta: number): string {
  const match = MONTH_PATTERN.exec(month);
  if (!match) return month;
  const index = Number(match[1]) * 12 + Number(match[2]) - 1 + delta;
  const year = Math.floor(index / 12);
  return `${year.toString().padStart(4, "0")}-${pad2(index - year * 12 + 1)}`;
}

/** "2026-11" -> "2026年11月"。 */
export function formatMonthLabel(month: string): string {
  const match = MONTH_PATTERN.exec(month);
  if (!match) return month;
  if (getLanguage() === "zh") return `${match[1]}年${Number(match[2])}月`;
  return new Intl.DateTimeFormat(currentLocale(), { year: "numeric", month: "short", timeZone: "UTC" })
    .format(new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, 1)));
}

/** "2026-11-03" -> "11月3日"。 */
export function formatEntryDate(isoDate: string): string {
  const [, month, day] = isoDate.split("-");
  if (!month || !day) return isoDate;
  if (getLanguage() === "zh") return `${Number(month)}月${Number(day)}日`;
  return new Intl.DateTimeFormat(currentLocale(), { month: "short", day: "numeric", timeZone: "UTC" })
    .format(new Date(Date.UTC(2000, Number(month) - 1, Number(day))));
}

/** 新建时的分类候选：预置在前，用过的自定义分类按使用次数追加。 */
export function categoryOptions(kind: LedgerKind, used: readonly { kind: LedgerKind; category: string }[]): string[] {
  const options = [...LEDGER_PRESET_CATEGORIES[kind]];
  for (const item of used) {
    if (item.kind === kind && !options.includes(item.category)) options.push(item.category);
  }
  return options;
}
