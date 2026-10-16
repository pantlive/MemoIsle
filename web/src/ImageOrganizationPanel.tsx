import { useEffect, useRef, useState } from "react";
import { getImageOrganization, resumeImageOrganization, startImageOrganization } from "./api";
import ImageDuplicatesDialog from "./ImageDuplicatesDialog";
import type { ImageOrganizationAction, ImageOrganizationState, Memo } from "./types";

export default function ImageOrganizationPanel({ selected, onChanged }: { selected: Memo[]; onChanged: () => void }) {
  const [state, setState] = useState<ImageOrganizationState | null>(null);
  const [busy, setBusy] = useState(false);
  const [duplicatesOpen, setDuplicatesOpen] = useState(false);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const onChangedRef = useRef(onChanged);
  const progress = useRef("");
  onChangedRef.current = onChanged;
  useEffect(() => {
    let cancelled = false;
    let timer: number;
    const load = async (): Promise<void> => {
      try {
        const updated = await getImageOrganization();
        if (cancelled) return;
        setState(updated);
        const marker = updated.job ? `${updated.job.id}:${updated.job.processed_count}:${updated.job.status}` : "";
        if (progress.current && progress.current !== marker) onChangedRef.current();
        progress.current = marker;
      } catch (loadError) {
        if (!cancelled) setError(loadError instanceof Error ? loadError.message : "读取图片整理进度失败");
      } finally { if (!cancelled) timer = window.setTimeout(() => void load(), 3000); }
    };
    void load();
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [refresh]);
  const running = state?.job?.status === "pending" || state?.job?.status === "processing";
  const start = async (action: ImageOrganizationAction, scope: "all" | "selected"): Promise<void> => {
    if (busy || running) return;
    setBusy(true); setError("");
    try { setState(await startImageOrganization(action, scope === "selected" ? selected : undefined)); }
    catch (startError) { setError(startError instanceof Error ? startError.message : "启动图片整理失败"); }
    finally { setBusy(false); }
  };
  const resume = async (): Promise<void> => {
    setBusy(true); setError("");
    try { setState(await resumeImageOrganization()); }
    catch (resumeError) { setError(resumeError instanceof Error ? resumeError.message : "继续图片任务失败"); }
    finally { setBusy(false); }
  };
  const job = state?.job;
  return <section className="image-organization-panel" aria-label="图片批量整理">
    <strong>图片批量整理</strong>
    <p>OCR 在本机识别中英文。分类时只使用识别文字和图片标题，按现有分类模板归类；已处理和手动分类跳过。没有可识别文字的图片可手动选择分类。</p>
    {state && <p>待识别 {state.pending_ocr_count} · 待模板分类 {state.pending_classification_count} · 完全重复 {state.duplicate_group_count} 组</p>}
    <div className="memo-batch-actions">
      <button type="button" disabled={busy || running || !state || state.pending_ocr_count === 0} onClick={() => void start("ocr", "all")}>识别全部未处理图片</button>
      <button type="button" disabled={busy || running || selected.length === 0} onClick={() => void start("ocr", "selected")}>识别选中图片</button>
      <button type="button" disabled={busy || running || selected.length === 0} onClick={() => void start("ocr_classify", "selected")}>选中图片按模板归类</button>
      <button type="button" disabled={busy || running || !state || state.pending_classification_count === 0} onClick={() => void start("ocr_classify", "all")}>归类全部未处理图片</button>
      <button type="button" onClick={() => setDuplicatesOpen(true)}>查看重复图片 {state?.duplicate_group_count ?? 0}</button>
      {job?.status === "failed" && <button type="button" disabled={busy} onClick={() => void resume()}>继续图片任务</button>}
    </div>
    {job && <div role="status" className="resource-classification-progress">
      {running && <progress value={job.processed_count} max={Math.max(1, job.total_count)} aria-label="图片整理进度" />}
      <span>{running ? "后台整理中" : job.status === "failed" ? "任务已暂停" : "本轮已完成"} · {job.processed_count}/{job.total_count} · 成功 {job.succeeded_count} · 未确定或失败 {job.failed_count} · 跳过 {job.skipped_count}</span>
      {job.error && <span role="alert">{job.error}</span>}
    </div>}
    {error && <p role="alert">{error}</p>}
    {duplicatesOpen && <ImageDuplicatesDialog onClose={() => setDuplicatesOpen(false)} onChanged={() => { onChangedRef.current(); setRefresh((value) => value + 1); }} />}
  </section>;
}
