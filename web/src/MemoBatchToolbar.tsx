import { useState } from "react";

import { applyMemoBatch } from "./api";
import type { Memo, MemoBatchAction } from "./types";

export default function MemoBatchToolbar({ rows, selected, trash, onSelection, onChanged, onBusy }: {
  rows: Memo[];
  selected: Map<string, Memo>;
  trash: boolean;
  onSelection: (selection: Map<string, Memo>) => void;
  onChanged: () => void;
  onBusy: (busy: boolean) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [details, setDetails] = useState<string[]>([]);
  const [error, setError] = useState("");
  const items = rows.filter((row) => selected.has(row.id)).map((row) => selected.get(row.id)!);
  const act = async (action: MemoBatchAction): Promise<void> => {
    if (busy || items.length === 0) return;
    if (action === "permanent" && !window.confirm(`永久删除选中的 ${items.length} 条内容及附件？此操作无法还原。`)) return;
    setBusy(true); onBusy(true); setError(""); setNotice(""); setDetails([]);
    try {
      const result = await applyMemoBatch(action, items.map((memo) => ({ memo_id: memo.id, expected_version: memo.version })));
      setNotice(`已处理 ${result.updated_count} 条，跳过 ${result.skipped_count} 条。`);
      const reasons = { missing: "已移除或已过保留期限", conflict: "已修改，请重新选择", not_applicable: "条目状态已变化" };
      setDetails(result.results.filter((item) => item.status === "skipped").map((item) =>
        `${selected.get(item.memo_id)?.title || "条目"}：${reasons[item.reason || "missing"]}`,
      ));
      onSelection(new Map()); onChanged();
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : "处理选中条目失败");
    } finally { setBusy(false); onBusy(false); }
  };
  return <section className="memo-batch-toolbar" aria-label="选中条目操作">
    <div className="memo-batch-actions">
      <label><input type="checkbox" disabled={busy || rows.length === 0} checked={rows.length > 0 && items.length === rows.length}
        onChange={(event) => onSelection(event.target.checked ? new Map(rows.map((row) => [row.id, row])) : new Map())} />全选当前页</label>
      <span>已选 {items.length} 条</span>
      {trash ? <>
        <button type="button" disabled={busy || items.length === 0} onClick={() => void act("restore")}>还原选中</button>
        <button type="button" disabled={busy || items.length === 0} onClick={() => void act("permanent")}>永久删除选中</button>
      </> : <button type="button" disabled={busy || items.length === 0} onClick={() => void act("trash")}>选中移入回收站</button>}
      <button type="button" disabled={busy || items.length === 0} onClick={() => onSelection(new Map())}>取消选择</button>
    </div>
    {notice && <p role="status">{notice}</p>}
    {details.length > 0 && <details open><summary>跳过原因</summary><ul>{details.map((text, index) => <li key={index}>{text}</li>)}</ul></details>}
    {error && <p role="alert">{error}</p>}
  </section>;
}
