// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ApiError, createLedgerEntry, deleteLedgerEntry, getLedgerSummary,
  listLedgerCategories, listLedgerEntries, quickCreateLedgerEntry, updateLedgerEntry,
} from "../api";
import { isoDateOf, monthOf } from "../ledger";
import LedgerPanel from "../LedgerPanel";
import type { LedgerEntry } from "../types";

vi.mock("../api", async (importOriginal) => ({
  ...await importOriginal<typeof import("../api")>(),
  createLedgerEntry: vi.fn(), deleteLedgerEntry: vi.fn(), getLedgerSummary: vi.fn(),
  listLedgerCategories: vi.fn(), listLedgerEntries: vi.fn(), quickCreateLedgerEntry: vi.fn(),
  updateLedgerEntry: vi.fn(),
}));

const entry: LedgerEntry = {
  id: "11111111-1111-4111-8111-111111111111", version: 3, kind: "expense",
  amount_cents: 2550, currency: "CNY", occurred_on: "2026-11-03", category: "餐饮",
  account: "现金", note: "午饭", created_at: "2026-11-03T00:00:00Z", updated_at: "2026-11-03T00:00:00Z",
};
let container: HTMLDivElement;
let root: Root;

async function click(text: string): Promise<void> {
  const button = [...container.querySelectorAll("button")].find((element) => element.textContent?.trim() === text);
  expect(button, text).toBeTruthy();
  await act(async () => { button!.click(); });
}

function quickInput(): HTMLInputElement {
  return container.querySelector<HTMLInputElement>('input[aria-label="一句话记账"]')!;
}

async function submitQuick(text: string): Promise<void> {
  const input = quickInput();
  await act(async () => {
    // 走原生 setter，React 才能感知到受控输入框的变化。
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, text);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => {
    container.querySelector("form.ledger-quick")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  vi.spyOn(HTMLDialogElement.prototype, "showModal").mockImplementation(function (this: HTMLDialogElement) { this.open = true; });
  vi.spyOn(HTMLDialogElement.prototype, "close").mockImplementation(function (this: HTMLDialogElement) { this.open = false; });
  vi.mocked(listLedgerEntries).mockResolvedValue([entry]);
  vi.mocked(listLedgerCategories).mockResolvedValue([{ kind: "expense", category: "餐饮", entry_count: 1 }]);
  vi.mocked(getLedgerSummary).mockResolvedValue({ month: "2026-11", totals: [{ currency: "CNY", income_cents: 0, expense_cents: 2550, balance_cents: -2550, entry_count: 1 }], categories: [] });
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals();
});

describe("记账界面", () => {
  it("renders server totals and deletes only after confirmation with the current version", async () => {
    await act(async () => root.render(<LedgerPanel />));
    expect(container.textContent).toContain("-¥25.50");
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    await click("删除");
    expect(deleteLedgerEntry).not.toHaveBeenCalled();
    confirm.mockReturnValue(true);
    vi.mocked(deleteLedgerEntry).mockResolvedValue(undefined);
    await click("删除");
    expect(deleteLedgerEntry).toHaveBeenCalledWith(entry.id, 3);
    expect(listLedgerEntries).toHaveBeenCalledTimes(2);
  });

  it("submits editor values as integer cents with the read version", async () => {
    vi.mocked(updateLedgerEntry).mockResolvedValue(entry);
    await act(async () => root.render(<LedgerPanel />));
    await click("编辑");
    const form = container.querySelector("dialog form")!;
    await act(async () => { form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })); });
    expect(updateLedgerEntry).toHaveBeenCalledWith(entry.id, {
      kind: "expense", amount_cents: 2550, currency: "CNY", occurred_on: "2026-11-03",
      category: "餐饮", account: "现金", note: "午饭",
    }, 3);
    expect(createLedgerEntry).not.toHaveBeenCalled();
    expect(container.querySelector("dialog")).toBeNull();
  });

  it("closes stale editors, reports conflicts and reloads server data", async () => {
    vi.mocked(updateLedgerEntry).mockRejectedValue(new ApiError("冲突", 409));
    await act(async () => root.render(<LedgerPanel />));
    await click("编辑");
    await act(async () => { container.querySelector("dialog form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })); });
    expect(container.textContent).toContain("已在其他设备修改");
    expect(container.querySelector("dialog")).toBeNull();
    expect(getLedgerSummary).toHaveBeenCalledTimes(2);
  });

  it("reports offline failures without showing data for the previous month", async () => {
    await act(async () => root.render(<LedgerPanel />));
    vi.mocked(listLedgerEntries).mockRejectedValue(new Error("网络不可用"));
    await act(async () => { container.querySelector<HTMLButtonElement>('[aria-label="上个月"]')!.click(); });
    expect(container.textContent).toContain("网络不可用");
    expect(container.textContent).not.toContain("午饭");
    expect(container.querySelectorAll(".ledger-totals article")).toHaveLength(0);
  });

  it("saves a sentence, shows what was recognized and opens it for editing", async () => {
    const today = isoDateOf();
    const saved: LedgerEntry = { ...entry, id: "22222222-2222-4222-8222-222222222222", version: 1,
      amount_cents: 1000, occurred_on: today, account: null, note: "今天早饭花了10元" };
    vi.mocked(quickCreateLedgerEntry).mockResolvedValue(saved);
    await act(async () => root.render(<LedgerPanel />));
    await submitQuick("  今天早饭花了10元 ");
    expect(quickCreateLedgerEntry).toHaveBeenCalledWith("今天早饭花了10元", today);
    expect(container.querySelector('[role="status"]')?.textContent).toContain("已记下：餐饮 -¥10.00 · ");
    expect(quickInput().value).toBe("");
    expect(listLedgerEntries).toHaveBeenCalledTimes(2);
    expect(listLedgerEntries).toHaveBeenLastCalledWith(expect.objectContaining({ month: monthOf() }));
    expect(createLedgerEntry).not.toHaveBeenCalled();

    await act(async () => { container.querySelector<HTMLButtonElement>('[aria-label="编辑刚记下的这一笔"]')!.click(); });
    const dialog = container.querySelector("dialog")!;
    expect(dialog.textContent).toContain("编辑流水");
    expect(dialog.querySelector<HTMLInputElement>('input[inputmode="decimal"]')!.value).toBe("10");
    vi.mocked(updateLedgerEntry).mockResolvedValue({ ...saved, version: 2 });
    await act(async () => { dialog.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })); });
    expect(updateLedgerEntry).toHaveBeenCalledWith(saved.id, expect.objectContaining({ amount_cents: 1000, occurred_on: today }), 1);
    expect(container.querySelector('[aria-label="编辑刚记下的这一笔"]')).toBeNull();
  });

  it("keeps the sentence and shows the reason below the input when it cannot be recognized", async () => {
    vi.mocked(quickCreateLedgerEntry).mockRejectedValue(new ApiError("没有识别到金额，请写明多少钱", 422));
    await act(async () => root.render(<LedgerPanel />));
    await submitQuick("早饭");
    expect(container.querySelector("#ledger-quick-error")?.textContent).toBe("没有识别到金额，请写明多少钱");
    expect(quickInput().value).toBe("早饭");
    expect(quickInput().getAttribute("aria-invalid")).toBe("true");
    expect(container.textContent).not.toContain("已记下");
    expect(container.querySelector("dialog")).toBeNull();
    expect(listLedgerEntries).toHaveBeenCalledTimes(1);
  });

  it("switches to the month of an entry recorded in another month", async () => {
    vi.mocked(quickCreateLedgerEntry).mockResolvedValue({ ...entry, occurred_on: "1999-03-05" });
    await act(async () => root.render(<LedgerPanel />));
    await submitQuick("1999年3月5号午饭25.5元");
    expect(container.textContent).toContain("已记下：餐饮 -¥25.50 · 1999年3月5日 · 现金");
    expect(container.querySelector<HTMLInputElement>('input[type="month"]')!.value).toBe("1999-03");
    // 只按新月份重新读取一次，不再多读一遍原来的月份。
    expect(listLedgerEntries).toHaveBeenCalledTimes(2);
    expect(listLedgerEntries).toHaveBeenLastCalledWith(expect.objectContaining({ month: "1999-03" }));
    expect(getLedgerSummary).toHaveBeenLastCalledWith("1999-03");
  });
});
