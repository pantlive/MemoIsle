import { useEffect, useRef, useState } from "react";
import { getImageOrganization, resumeImageOrganization, startImageOrganization } from "./api";
import ImageDuplicatesDialog from "./ImageDuplicatesDialog";
import type { ImageOrganizationAction, ImageOrganizationState, Memo } from "./types";
import { useI18n } from "./I18nProvider";

export default function ImageOrganizationPanel({ selected, onChanged }: { selected: Memo[]; onChanged: () => void }) {
  const { t } = useI18n();
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
        if (!cancelled) setError(loadError instanceof Error ? loadError.message : t("读取图片整理进度失败"));
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
    catch (startError) { setError(startError instanceof Error ? startError.message : t("启动图片整理失败")); }
    finally { setBusy(false); }
  };
  const resume = async (): Promise<void> => {
    setBusy(true); setError("");
    try { setState(await resumeImageOrganization()); }
    catch (resumeError) { setError(resumeError instanceof Error ? resumeError.message : t("继续图片任务失败")); }
    finally { setBusy(false); }
  };
  const job = state?.job;
  return <section className="image-organization-panel" aria-label={t("图片批量整理")}>
    <strong>{t("图片批量整理")}</strong>
    <p>{t("OCR 在本机识别中英文。分类时只使用识别文字和图片标题，按现有分类模板归类；已处理和手动分类跳过。没有可识别文字的图片可手动选择分类。")}</p>
    {state && <p>{t("待识别 {pending_ocr_count} · 待模板分类 {pending_classification_count} · 完全重复 {duplicate_group_count} 组", { pending_ocr_count: state.pending_ocr_count, pending_classification_count: state.pending_classification_count, duplicate_group_count: state.duplicate_group_count })}</p>}
    <div className="memo-batch-actions">
      <button type="button" disabled={busy || running || !state || state.pending_ocr_count === 0} onClick={() => void start("ocr", "all")}>{t("识别全部未处理图片")}</button>
      <button type="button" disabled={busy || running || selected.length === 0} onClick={() => void start("ocr", "selected")}>{t("识别选中图片")}</button>
      <button type="button" disabled={busy || running || selected.length === 0} onClick={() => void start("ocr_classify", "selected")}>{t("选中图片按模板归类")}</button>
      <button type="button" disabled={busy || running || !state || state.pending_classification_count === 0} onClick={() => void start("ocr_classify", "all")}>{t("归类全部未处理图片")}</button>
      <button type="button" onClick={() => setDuplicatesOpen(true)}>{t("查看重复图片 {count}", { count: state?.duplicate_group_count ?? 0 })}</button>
      {job?.status === "failed" && <button type="button" disabled={busy} onClick={() => void resume()}>{t("继续图片任务")}</button>}
    </div>
    {job && <div role="status" className="resource-classification-progress">
      {running && <progress value={job.processed_count} max={Math.max(1, job.total_count)} aria-label={t("图片整理进度")} />}
      <span>{running ? t("后台整理中") : job.status === "failed" ? t("任务已暂停") : t("本轮已完成")}{t(" · {processed_count}/{total_count} · 成功 {succeeded_count} · 未确定或失败 {failed_count} · 跳过 {skipped_count}", { processed_count: job.processed_count, total_count: job.total_count, succeeded_count: job.succeeded_count, failed_count: job.failed_count, skipped_count: job.skipped_count })}</span>
      {job.error && <span role="alert">{job.error}</span>}
    </div>}
    {error && <p role="alert">{error}</p>}
    {duplicatesOpen && <ImageDuplicatesDialog onClose={() => setDuplicatesOpen(false)} onChanged={() => { onChangedRef.current(); setRefresh((value) => value + 1); }} />}
  </section>;
}
