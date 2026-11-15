import { describe, expect, it } from "vitest";

import {
  LEDGER_PRESET_CATEGORIES,
  categoryOptions,
  centsToAmountInput,
  formatCents,
  formatEntryDate,
  formatMoney,
  formatMonthLabel,
  formatSignedAmount,
  isValidMonth,
  isoDateOf,
  monthOf,
  parseAmountToCents,
  shiftMonth,
} from "../ledger";

// 与 Android 端 LedgerTest.kt 使用同一组用例，两端换算结果必须一致。
describe("parseAmountToCents", () => {
  it.each([
    ["25", 2_500],
    ["25.5", 2_550],
    ["25.50", 2_550],
    ["0.01", 1],
    [".5", 50],
    ["12.", 1_200],
    ["1,234.56", 123_456],
    [" ¥1 234.5 ", 123_450],
    ["１２．３", 1_230],
    ["1000000000", 100_000_000_000],
  ])("parses %s", (input, cents) => {
    expect(parseAmountToCents(input)).toBe(cents);
  });

  it.each(["", "0", "0.00", ".", "-5", "1.234", "abc", "1e3", "9999999999", "1000000000.01", "12.3.4"])(
    "rejects %s",
    (input) => {
      expect(parseAmountToCents(input)).toBeNull();
    },
  );

  it("does not drift like floating point math", () => {
    expect(parseAmountToCents("0.1")! + parseAmountToCents("0.2")!).toBe(30);
    expect(parseAmountToCents("19.99")).toBe(1_999);
  });
});

describe("formatting cents", () => {
  it.each([
    [0, "0.00"],
    [1, "0.01"],
    [2_550, "25.50"],
    [123_456, "1,234.56"],
    [100_000_000_000, "1,000,000,000.00"],
    [-1_500, "-15.00"],
  ])("formats %d", (cents, text) => {
    expect(formatCents(cents)).toBe(text);
  });

  it.each([
    [2_500, "25"],
    [2_550, "25.50"],
    [1, "0.01"],
    [5, "0.05"],
    [123_456, "1234.56"],
  ])("fills the editor with %d", (cents, text) => {
    expect(centsToAmountInput(cents)).toBe(text);
    // 回填的文本再解析回来不变。
    expect(parseAmountToCents(text)).toBe(cents);
  });

  it("adds currency symbols and direction", () => {
    expect(formatMoney(-150, "CNY")).toBe("-¥1.50");
    expect(formatMoney(2_000, "USD")).toBe("$20.00");
    expect(formatMoney(100, "CHF")).toBe("CHF 1.00");
    expect(formatSignedAmount("expense", 2_550, "CNY")).toBe("-¥25.50");
    expect(formatSignedAmount("income", 2_550, "CNY")).toBe("+¥25.50");
  });
});

describe("months", () => {
  it.each([
    ["2026-01", -1, "2025-12"],
    ["2026-12", 1, "2027-01"],
    ["2026-11", 0, "2026-11"],
    ["2026-03", -14, "2025-01"],
    ["2026-03", 25, "2028-04"],
    ["2026-13", 1, "2026-13"],
  ])("shifts %s by %d", (month, delta, expected) => {
    expect(shiftMonth(month, delta)).toBe(expected);
  });

  it("validates and formats months", () => {
    expect(isValidMonth("2026-03")).toBe(true);
    expect(isValidMonth("2026-3")).toBe(false);
    expect(isValidMonth("2026-00")).toBe(false);
    expect(formatMonthLabel("2026-03")).toBe("2026年3月");
    expect(formatEntryDate("2026-11-03")).toBe("11月3日");
  });

  it("uses the local calendar date", () => {
    expect(monthOf(new Date(2026, 0, 31, 23, 59))).toBe("2026-01");
    expect(isoDateOf(new Date(2026, 1, 3, 0, 1))).toBe("2026-02-03");
  });
});

describe("categoryOptions", () => {
  it("lists presets first and appends used custom categories of the same kind", () => {
    const options = categoryOptions("expense", [
      { kind: "expense", category: "咖啡" },
      { kind: "income", category: "理财" },
      { kind: "expense", category: "餐饮" },
    ]);
    expect(options).toEqual([...LEDGER_PRESET_CATEGORIES.expense, "咖啡"]);
    expect(categoryOptions("income", [{ kind: "income", category: "理财" }])).toEqual(["工资", "其他", "理财"]);
  });
});
