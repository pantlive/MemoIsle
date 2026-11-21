import { useState } from "react";

import { applyMemoBatch } from "./api";
import type { Memo, MemoBatchAction } from "./types";
import { useI18n } from "./I18nProvider";

export default function MemoBatchToolbar({ rows, selected, trash, onSelection, onChanged, onBusy }: {
  rows: Memo[];
  selected: Map<string, Memo>;
  trash: boolean;
  onSelection: (selection: Map<string, Memo>) => void;
  onChanged: () => void;
  onBusy: (busy: boolean) => void;
}) {
  const { t } = useI18n();
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [details, setDetails] = useState<string[]>([]);
  const [error, setError] = useState("");
  const items = rows.filter((row) => selected.has(row.id)).map((row) => selected.get(row.id)!);
  const act = async (action: MemoBatchAction): Promise<void> => {
    if (busy || items.length === 0) return;
    if (action === "permanent" && !window.confirm(t("永久删除选中的 {length} 条内容及附件？此操作无法还原。", { length: items.length }))) return;
    setBusy(true); onBusy(true); setError(""); setNotice(""); setDetails([]);
    try {
      const result = await applyMemoBatch(action, items.map((memo) => ({ memo_id: memo.id, expected_version: memo.version })));
      setNotice(t("已处理 {updated_count} 条，跳过 {skipped_count} 条。", { updated_count: result.updated_count, skipped_count: result.skipped_count }));
      const reasons = { missing: t("已移除或已过保留期限"), conflict: t("已修改，请重新选择"), not_applicable: t("条目状态已变化") };
      setDetails(result.results.filter((item) => item.status === "skipped").map((item) =>
        t("{value}：{value2}", { value: selected.get(item.memo_id)?.title || t("条目"), value2: reasons[item.reason || "missing"] }),
      ));
      onSelection(new Map()); onChanged();
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : t("处理选中条目失败"));
    } finally { setBusy(false); onBusy(false); }
  };
  // 没选中条目也没有结果提示时只留「全选」，不占一整张卡片。
  const idle = items.length === 0 && !notice && !error;
  return <section className={idle ? "memo-batch-toolbar idle" : "memo-batch-toolbar"} aria-label={t("选中条目操作")}>
    <div className="memo-batch-actions">
      <label><input type="checkbox" disabled={busy || rows.length === 0} checked={rows.length > 0 && items.length === rows.length}
        onChange={(event) => onSelection(event.target.checked ? new Map(rows.map((row) => [row.id, row])) : new Map())} />{t("全选当前页")}</label>
      {!idle && <span>{t("已选 {length} 条", { length: items.length })}</span>}
      {!idle && (trash ? <>
        <button type="button" disabled={busy || items.length === 0} onClick={() => void act("restore")}>{t("还原选中")}</button>
        <button type="button" disabled={busy || items.length === 0} onClick={() => void act("permanent")}>{t("永久删除选中")}</button>
      </> : <button type="button" disabled={busy || items.length === 0} onClick={() => void act("trash")}>{t("选中移入回收站")}</button>)}
      {!idle && <button type="button" disabled={busy || items.length === 0} onClick={() => onSelection(new Map())}>{t("取消选择")}</button>}
    </div>
    {notice && <p role="status">{notice}</p>}
    {details.length > 0 && <details open><summary>{t("跳过原因")}</summary><ul>{details.map((text, index) => <li key={index}>{text}</li>)}</ul></details>}
    {error && <p role="alert">{error}</p>}
  </section>;
}
