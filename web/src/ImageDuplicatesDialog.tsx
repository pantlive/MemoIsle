import { useEffect, useState } from "react";
import { applyMemoBatch, getImageDuplicateGroup, getImageDuplicates } from "./api";
import Icon from "./Icon";
import type { ImageDuplicateList } from "./types";

type DuplicateItem = ImageDuplicateList["groups"][number]["items"][number];
export default function ImageDuplicatesDialog({ onClose, onChanged }: { onClose: () => void; onChanged: () => void }) {
  const [list, setList] = useState<ImageDuplicateList | null>(null);
  const [offset, setOffset] = useState(0);
  const [group, setGroup] = useState<{ hash: string; offset: number; total: number; rows: DuplicateItem[] } | null>(null);
  const [selected, setSelected] = useState<Map<string, DuplicateItem>>(new Map());
  const [refresh, setRefresh] = useState(0);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  useEffect(() => {
    let cancelled = false;
    setLoading(true); setError(""); setSelected(new Map());
    void getImageDuplicates(offset).then((updated) => {
      if (cancelled) return;
      const lastOffset = updated.total_count > 0 ? Math.floor((updated.total_count - 1) / updated.limit) * updated.limit : 0;
      if (offset > lastOffset) { setOffset(lastOffset); return; }
      setList(updated);
    })
      .catch((loadError: unknown) => { if (!cancelled) setError(loadError instanceof Error ? loadError.message : "读取重复图片失败"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [offset, refresh]);
  useEffect(() => {
    const handleKey = (event: KeyboardEvent): void => {
      if (event.key === "Escape" && !busy) onClose();
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [busy, onClose]);
  const openGroup = async (hash: string, nextOffset = 0): Promise<void> => {
    setLoading(true); setSelected(new Map()); setError("");
    try { const result = await getImageDuplicateGroup(hash, nextOffset); setGroup({ hash, offset: nextOffset, total: result.total_count, rows: result.items }); }
    catch (groupError) { setError(groupError instanceof Error ? groupError.message : "读取重复组失败"); }
    finally { setLoading(false); }
  };
  const toggle = (item: DuplicateItem): void => setSelected((current) => {
    const updated = new Map(current); if (updated.has(item.id)) updated.delete(item.id); else if (updated.size < 100) updated.set(item.id, item); return updated;
  });
  const trashSelected = async (): Promise<void> => {
    if (busy || selected.size === 0) return;
    setBusy(true); setError("");
    try {
      const result = await applyMemoBatch("trash", [...selected.values()].map((item) => ({ memo_id: item.id, expected_version: item.version })));
      setNotice(`已移入回收站 ${result.updated_count} 条，跳过 ${result.skipped_count} 条。${result.skipped_count ? "跳过的条目已修改或移除，请刷新后重新选择。" : ""}`);
      setSelected(new Map()); setGroup(null); setOffset(0); setRefresh((value) => value + 1); onChanged();
    } catch (actionError) { setError(actionError instanceof Error ? actionError.message : "移入回收站失败"); }
    finally { setBusy(false); }
  };
  const renderItems = (rows: DuplicateItem[]) => rows.map((item) => <label className="duplicate-image-item" key={item.id}>
    <input type="checkbox" aria-label={`选择重复图片 ${item.title}`} disabled={busy || loading || (!selected.has(item.id) && selected.size >= 100)}
      checked={selected.has(item.id)} onChange={() => toggle(item)} />{item.title}
  </label>);
  return <div className="dialog-backdrop" role="presentation"><section className="classification-review-dialog image-duplicates-dialog dialog-shell" role="dialog" aria-modal="true" aria-labelledby="image-duplicates-title">
    <div className="dialog-header"><div>
      <span className="type-label"><Icon name="image" size={16} /> 图片整理</span>
      <h2 id="image-duplicates-title">重复图片</h2>
      <p>仅显示完整文件相同的图片。选择需要整理的记录后移入回收站，可还原；每次最多选择 100 条。</p>
    </div>
      <button type="button" className="icon-button" aria-label="关闭重复图片" onClick={onClose} disabled={busy}>
        <Icon name="close" size={16} />
      </button></div>
    <div className="dialog-body">
    {notice && <p role="status">{notice}</p>}
    {loading ? <p role="status">正在读取重复图片…</p> : group ? <>
      <button type="button" className="ghost" disabled={busy} onClick={() => { setGroup(null); setSelected(new Map()); }}>返回重复组</button>
      <p>本组共 {group.total} 条 · 当前 {group.offset + 1}–{group.offset + group.rows.length} 条</p>
      {renderItems(group.rows)}
      <div className="classification-review-pagination"><button type="button" className="ghost" disabled={busy || group.offset === 0} onClick={() => void openGroup(group.hash, Math.max(0, group.offset - 50))}>组内上一页</button>
        <button type="button" className="ghost" disabled={busy || group.offset + 50 >= group.total} onClick={() => void openGroup(group.hash, group.offset + 50)}>组内下一页</button></div>
    </> : <>
      <p>共 {list?.total_count ?? 0} 组完全重复图片</p>
      {list?.groups.map((item) => <section className="duplicate-image-group" key={item.image_hash}>
        <strong>重复 {item.count} 条</strong><p>按收藏时间排列，最早收藏显示在前。当前显示 {item.items.length} 条。</p>
        {renderItems(item.items)}
        {item.count > 50 && <button type="button" disabled={busy} onClick={() => void openGroup(item.image_hash)}>查看本组全部图片</button>}
      </section>)}
      <div className="classification-review-pagination"><button type="button" className="ghost" disabled={busy || loading || offset === 0} onClick={() => { setLoading(true); setOffset(Math.max(0, offset - 10)); }}>上一页重复组</button>
        <button type="button" className="ghost" disabled={busy || loading || !list || offset + list.limit >= list.total_count} onClick={() => { setLoading(true); setOffset(offset + 10); }}>下一页重复组</button></div>
    </>}
    </div>
    <div className="dialog-actions">
      <span>已选 {selected.size} 条</span>
      <button type="button" className="ghost" disabled={busy} onClick={() => setSelected(new Map())}>取消选择</button>
      <button type="button" className="danger-button" disabled={busy || loading || selected.size === 0} onClick={() => void trashSelected()}>选中重复图片移入回收站</button>
    </div>
    {error && <div className="dialog-error" role="alert">{error}</div>}
  </section></div>;
}
