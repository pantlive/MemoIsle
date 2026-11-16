import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";

import {
  ApiError, createLedgerEntry, deleteLedgerEntry, getLedgerSummary,
  listLedgerCategories, listLedgerEntries, quickCreateLedgerEntry, updateLedgerEntry,
} from "./api";
import Icon from "./Icon";
import {
  categoryOptions, centsToAmountInput, formatEntryDate, formatMoney, formatMonthLabel,
  formatSignedAmount, isoDateOf, LEDGER_CURRENCIES, ledgerKindLabels, monthOf,
  parseAmountToCents, shiftMonth,
} from "./ledger";
import type { LedgerCategoryUsage, LedgerEntry, LedgerEntryInput, LedgerKind, LedgerSummary } from "./types";

const PAGE_SIZE = 500;
const QUICK_TEXT_MAX_LENGTH = 200;
const describe = (error: unknown): string => error instanceof Error ? error.message : "操作失败，请重试。";

/** 一句话记账成功后的识别结果，例如「餐饮 -¥10.00 · 11月16日 · 微信」；不是今年的带上年份。 */
function describeQuickEntry(entry: LedgerEntry): string {
  const year = entry.occurred_on.slice(0, 4);
  const day = formatEntryDate(entry.occurred_on);
  const date = year === String(new Date().getFullYear()) ? day : `${year}年${day}`;
  return [`${entry.category} ${formatSignedAmount(entry.kind, entry.amount_cents, entry.currency)}`, date, entry.account]
    .filter(Boolean).join(" · ");
}

interface MutationOptions<T> {
  /** 自定义成功提示；返回的 month 与当前月份不同时切过去，由切月触发重新读取。 */
  onSuccess?: (result: T) => { notice: string; month?: string };
  /** 自定义失败提示的位置，例如一句话记账显示在输入框下方。 */
  onError?: (message: string) => void;
}

function LedgerEditor({ entry, month, categories, busy, error, onClose, onSave }: {
  entry: LedgerEntry | null;
  month: string;
  categories: LedgerCategoryUsage[];
  busy: boolean;
  error: string;
  onClose: () => void;
  onSave: (input: LedgerEntryInput) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [kind, setKind] = useState<LedgerKind>(entry?.kind ?? "expense");
  const [amount, setAmount] = useState(entry ? centsToAmountInput(entry.amount_cents) : "");
  const [currency, setCurrency] = useState(entry?.currency ?? "CNY");
  const [date, setDate] = useState(entry?.occurred_on ?? (month === monthOf() ? isoDateOf() : `${month}-01`));
  const [category, setCategory] = useState(entry?.category ?? "餐饮");
  const [account, setAccount] = useState(entry?.account ?? "");
  const [note, setNote] = useState(entry?.note ?? "");
  const [validation, setValidation] = useState("");

  useEffect(() => {
    // 原生模态框负责焦点约束与关闭后恢复焦点。
    const element = dialog.current!;
    element.showModal();
    return () => element.close();
  }, []);

  function submit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    const cents = parseAmountToCents(amount);
    if (cents === null) {
      setValidation("请输入大于 0、最多两位小数且不超过 10 亿元的金额。");
      return;
    }
    if (!category.trim() || !/^[A-Z]{3}$/.test(currency.trim().toUpperCase())) {
      setValidation("请填写分类和三位字母币种。");
      return;
    }
    setValidation("");
    onSave({ kind, amount_cents: cents, currency: currency.trim().toUpperCase(), occurred_on: date,
      category: category.trim(), account: account.trim() || null, note: note.trim() || null });
  }

  return <dialog ref={dialog} className="ledger-dialog" aria-labelledby="ledger-editor-title"
    onCancel={(event) => { event.preventDefault(); if (!busy) onClose(); }}>
    <form onSubmit={submit}>
      <h2 id="ledger-editor-title">{entry ? "编辑流水" : "记一笔"}</h2>
      <fieldset disabled={busy} className="ledger-fields">
        <label>方向<select aria-label="方向" value={kind} onChange={(event) => {
          const value = event.target.value as LedgerKind;
          setKind(value); setCategory(value === "income" ? "工资" : "餐饮");
        }}><option value="expense">支出</option><option value="income">收入</option></select></label>
        <label>金额<input autoFocus inputMode="decimal" value={amount} onChange={(event) => setAmount(event.target.value)} required placeholder="0.00" /></label>
        <label>币种<input list="ledger-currencies" value={currency} onChange={(event) => setCurrency(event.target.value.toUpperCase())} maxLength={3} pattern="[A-Za-z]{3}" required /></label>
        <datalist id="ledger-currencies">{LEDGER_CURRENCIES.map((value) => <option key={value} value={value} />)}</datalist>
        <label>日期<input type="date" value={date} min="1900-01-01" max="2100-12-31" onChange={(event) => setDate(event.target.value)} required /></label>
        <label>分类<input list="ledger-category-options" value={category} onChange={(event) => setCategory(event.target.value)} maxLength={30} required /></label>
        <datalist id="ledger-category-options">{categoryOptions(kind, categories).map((value) => <option key={value} value={value} />)}</datalist>
        <label>账户（选填）<input value={account} onChange={(event) => setAccount(event.target.value)} maxLength={30} placeholder="如现金、银行卡" /></label>
        <label className="ledger-wide">备注（选填）<textarea value={note} onChange={(event) => setNote(event.target.value)} maxLength={500} rows={3} /></label>
      </fieldset>
      {(validation || error) && <p role="alert" className="ledger-error">{validation || error}</p>}
      <div className="ledger-actions"><button type="button" onClick={onClose} disabled={busy}>取消</button><button className="primary" disabled={busy}>{busy ? "保存中…" : "保存"}</button></div>
    </form>
  </dialog>;
}

export default function LedgerPanel() {
  const [month, setMonth] = useState(monthOf);
  const [kind, setKind] = useState<LedgerKind | "">("");
  const [category, setCategory] = useState("");
  const [entries, setEntries] = useState<LedgerEntry[]>([]);
  const [summary, setSummary] = useState<LedgerSummary | null>(null);
  const [categories, setCategories] = useState<LedgerCategoryUsage[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [editor, setEditor] = useState<{ entry: LedgerEntry | null } | null>(null);
  const [dialogError, setDialogError] = useState("");
  const [busy, setBusy] = useState(false);
  const [quickText, setQuickText] = useState("");
  const [quickError, setQuickError] = useState("");
  const [quickSaved, setQuickSaved] = useState<LedgerEntry | null>(null);
  const requestId = useRef(0);
  const mutationBusy = useRef(false);

  const reload = useCallback(async () => {
    const id = ++requestId.current;
    setLoading(true);
    setError("");
    // 切换月份或筛选时立即移除旧数据，避免把上月金额当成当月。
    setEntries([]); setSummary(null); setHasMore(false);
    try {
      const [rows, totals, used] = await Promise.all([
        listLedgerEntries({ month, kind: kind || undefined, category: category || undefined, limit: PAGE_SIZE }),
        getLedgerSummary(month), listLedgerCategories(),
      ]);
      if (id !== requestId.current) return;
      setEntries(rows); setSummary(totals); setCategories(used); setHasMore(rows.length === PAGE_SIZE);
    } catch (failure) {
      if (id === requestId.current) setError(`无法读取记账数据：${describe(failure)}`);
    } finally {
      if (id === requestId.current) setLoading(false);
    }
  }, [month, kind, category]);

  useEffect(() => { void reload(); return () => { requestId.current++; }; }, [reload]);

  async function loadMore(): Promise<void> {
    const id = ++requestId.current;
    setLoading(true); setError("");
    try {
      const rows = await listLedgerEntries({ month, kind: kind || undefined, category: category || undefined, limit: PAGE_SIZE, offset: entries.length });
      if (id !== requestId.current) return;
      setEntries((current) => [...current, ...rows.filter((row) => !current.some((item) => item.id === row.id))]);
      setHasMore(rows.length === PAGE_SIZE);
    } catch (failure) {
      if (id === requestId.current) setError(describe(failure));
    } finally { if (id === requestId.current) setLoading(false); }
  }

  async function mutate<T>(action: () => Promise<T>, options: MutationOptions<T> = {}): Promise<void> {
    if (mutationBusy.current) return;
    mutationBusy.current = true;
    setBusy(true); setDialogError(""); setNotice(""); setQuickSaved(null);
    try {
      const result = await action();
      const success = options.onSuccess?.(result);
      setEditor(null); setNotice(success?.notice ?? "已保存。");
      if (success?.month && success.month !== month) setMonth(success.month);
      else await reload();
    } catch (failure) {
      if (failure instanceof ApiError && failure.status === 409) {
        setEditor(null);
        setNotice("已在其他设备修改，已重新读取数据，请重新打开后操作。");
        await reload();
      } else if (options.onError) options.onError(describe(failure));
      else if (editor) setDialogError(describe(failure));
      else setError(describe(failure));
    } finally { mutationBusy.current = false; setBusy(false); }
  }

  function submitQuick(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    const text = quickText.trim();
    if (!text) { setQuickError("请输入一句话，如：今天早饭花了10元"); return; }
    setQuickError("");
    // 识别失败时保留输入，方便改一改再记。
    void mutate(() => quickCreateLedgerEntry(text, isoDateOf()), {
      onSuccess: ({ parsed_by: parsedBy, ...entry }) => {
        setQuickText(""); setQuickSaved(entry);
        const source = parsedBy === "llm" ? "（本地模型识别）" : "";
        return { notice: `已记下：${describeQuickEntry(entry)}${source}`, month: entry.occurred_on.slice(0, 7) };
      },
      onError: setQuickError,
    });
  }

  const usedCategories = [...new Set(categories.filter((item) => !kind || item.kind === kind).map((item) => item.category))];
  return <section className="ledger-panel" aria-label="记账">
    <div className="page-heading"><div><h1>记账</h1><p className="page-subtitle">每一笔收支，都心中有数</p></div>
      <div className="ledger-actions"><button disabled={loading || busy} onClick={() => void reload()}>刷新</button><button className="primary" disabled={busy || loading} onClick={() => { setDialogError(""); setEditor({ entry: null }); }}><Icon name="plus" size={16} /> 记一笔</button></div></div>
    <form className="ledger-quick" onSubmit={submitQuick}>
      <input aria-label="一句话记账" value={quickText} maxLength={QUICK_TEXT_MAX_LENGTH} readOnly={busy}
        placeholder="如：今天早饭花了10元" enterKeyHint="done" aria-invalid={quickError ? true : undefined}
        aria-describedby={quickError ? "ledger-quick-error" : undefined}
        onChange={(event) => { setQuickText(event.target.value); setQuickError(""); }} />
      <button className="primary" disabled={busy || !quickText.trim()}>记下</button>
      {quickError && <p id="ledger-quick-error" role="alert" className="ledger-error">{quickError}</p>}
    </form>
    <div className="ledger-month">
      <button aria-label="上个月" disabled={busy || month === "1900-01"} onClick={() => setMonth(shiftMonth(month, -1))}>‹</button>
      <label><span className="sr-only">月份</span><input type="month" value={month} min="1900-01" max="2100-12" disabled={busy} onChange={(event) => { if (/^(19\d{2}|20\d{2}|2100)-(0[1-9]|1[0-2])$/.test(event.target.value)) setMonth(event.target.value); }} /></label>
      <button aria-label="下个月" disabled={busy || month === "2100-12"} onClick={() => setMonth(shiftMonth(month, 1))}>›</button>
      <button disabled={busy} onClick={() => setMonth(monthOf())}>本月</button>
    </div>
    {notice && <p role="status" className="ledger-notice">{notice}{quickSaved && <button type="button" disabled={busy || loading}
      aria-label="编辑刚记下的这一笔" onClick={() => {
        // 列表里有更新的版本时用它，避免拿旧版本号保存。
        setDialogError(""); setEditor({ entry: entries.find((item) => item.id === quickSaved.id) ?? quickSaved });
      }}>编辑</button>}</p>}
    {error && <p role="alert" className="ledger-error">{error} <button disabled={loading || busy} onClick={() => void reload()}>重试</button></p>}
    {loading && <p role="status">正在读取…</p>}
    <div className="ledger-totals">{summary?.totals.map((total) => <article className="ledger-card" key={total.currency}>
      <h2>{total.currency} <small>{total.entry_count} 笔</small></h2><dl>
        <div><dt>收入</dt><dd className="ledger-income">{formatMoney(total.income_cents, total.currency)}</dd></div>
        <div><dt>支出</dt><dd>{formatMoney(total.expense_cents, total.currency)}</dd></div>
        <div><dt>结余</dt><dd>{formatMoney(total.balance_cents, total.currency)}</dd></div>
      </dl></article>)}</div>
    {!!summary?.categories.length && <details className="ledger-card"><summary>分类小计 · {formatMonthLabel(month)}</summary><ul className="ledger-category-totals">{summary.categories.map((total) => <li key={`${total.currency}-${total.kind}-${total.category}`}>
      <span>{total.category} · {ledgerKindLabels[total.kind]} · {total.currency}</span><strong>{formatMoney(total.amount_cents, total.currency)}</strong>
    </li>)}</ul></details>}
    <div className="ledger-filters">
      <label>方向<select aria-label="流水方向" value={kind} disabled={busy} onChange={(event) => { setKind(event.target.value as LedgerKind | ""); setCategory(""); }}><option value="">全部收支</option><option value="expense">支出</option><option value="income">收入</option></select></label>
      <label>分类<select aria-label="流水分类" value={category} disabled={busy} onChange={(event) => setCategory(event.target.value)}><option value="">全部分类</option>{usedCategories.map((value) => <option key={value}>{value}</option>)}</select></label>
      <small>汇总包含当月全部收支</small>
    </div>
    {!loading && !error && !entries.length && <div className="ledger-empty"><Icon name="ledger" size={32} /><p>这个月还没有符合条件的流水</p><span>记下第一笔，开始了解自己的收支。</span></div>}
    <ul className="ledger-entries">{entries.map((entry) => <li className="ledger-row" key={entry.id}>
      <div className="ledger-row-info"><strong>{entry.category}</strong><small><time dateTime={entry.occurred_on}>{formatEntryDate(entry.occurred_on)}</time>{entry.account ? ` · ${entry.account}` : ""}</small>{entry.note && <p>{entry.note}</p>}</div>
      <strong className={entry.kind === "income" ? "ledger-income" : ""}>{formatSignedAmount(entry.kind, entry.amount_cents, entry.currency)}</strong>
      <div className="ledger-actions"><button disabled={busy || loading} aria-label={`编辑${entry.category} ${entry.occurred_on}`} onClick={() => { setDialogError(""); setEditor({ entry }); }}>编辑</button><button className="danger-text" disabled={busy || loading} aria-label={`删除${entry.category} ${entry.occurred_on}`} onClick={() => {
        if (window.confirm(`确定永久删除 ${entry.occurred_on} 的「${entry.category}」${formatMoney(entry.amount_cents, entry.currency)}？`)) void mutate(() => deleteLedgerEntry(entry.id, entry.version));
      }}>删除</button></div>
    </li>)}</ul>
    {hasMore && <button disabled={loading || busy} onClick={() => void loadMore()}>加载更多流水</button>}
    {editor && <LedgerEditor entry={editor.entry} month={month} categories={categories} busy={busy} error={dialogError} onClose={() => setEditor(null)} onSave={(input) => void mutate(() => editor.entry ? updateLedgerEntry(editor.entry.id, input, editor.entry.version) : createLedgerEntry(input))} />}
  </section>;
}
