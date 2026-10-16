import { type ReactNode, useEffect, useRef, useState } from "react";

import {
  getResourceClassificationState,
  resumeResourceClassification,
  retryClassifiedResources,
  retryResourceClassificationReviews,
  startResourceClassification,
} from "./api";
import type { ResourceClassificationState } from "./types";
import BookmarkFolderMappingDialog from "./BookmarkFolderMappingDialog";
import ResourceClassificationReviewDialog from "./ResourceClassificationReviewDialog";

interface ResourceClassificationPanelProps {
  onChanged: () => void;
  // 面板折叠时，外层入口用待确认数提示用户。
  onReviewCount?: (count: number) => void;
}

export default function ResourceClassificationPanel({
  onChanged,
  onReviewCount,
}: ResourceClassificationPanelProps): ReactNode {
  const [state, setState] = useState<ResourceClassificationState | null>(null);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");
  const [loadError, setLoadError] = useState("");
  const [reviewOpen, setReviewOpen] = useState(false);
  const [folderOpen, setFolderOpen] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const onChangedRef = useRef(onChanged);
  const previousProgress = useRef("");
  onChangedRef.current = onChanged;

  const reviewCount = state?.review_count ?? 0;
  useEffect(() => {
    onReviewCount?.(reviewCount);
  }, [onReviewCount, reviewCount]);

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    const load = async (): Promise<void> => {
      try {
        const updated = await getResourceClassificationState();
        if (cancelled) return;
        setState(updated);
        setLoadError("");
        const job = updated.job;
        const progress = job ? `${job.id}:${job.succeeded_count}:${job.status}` : "";
        if (previousProgress.current && progress !== previousProgress.current) {
          onChangedRef.current();
        }
        previousProgress.current = progress;
      } catch (progressError) {
        if (!cancelled) setLoadError(progressError instanceof Error ? progressError.message : "读取分类进度失败");
      } finally {
        // 分类任务在后端运行，切换视图或关闭页面后仍会继续。
        if (!cancelled) timer = window.setTimeout(() => void load(), 3000);
      }
    };
    void load();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [refresh]);

  const job = state?.job;
  const running = job?.status === "pending" || job?.status === "processing";
  const canResume = job?.status === "failed" && job.processed_count < job.total_count;
  const waitingForRetry = job?.status === "pending" && Boolean(job.next_retry_at);
  const retrySeconds = job?.next_retry_at
    ? Math.max(0, Math.ceil((new Date(job.next_retry_at).getTime() - Date.now()) / 1000))
    : 0;

  const handleStart = async (): Promise<void> => {
    if (starting || running) return;
    setStarting(true);
    setError("");
    try {
      setState(await (canResume ? resumeResourceClassification() : startResourceClassification()));
    } catch (startError) {
      setError(startError instanceof Error ? startError.message : canResume ? "继续分类任务失败" : "启动网页分类失败");
    } finally {
      setStarting(false);
    }
  };

  const handleRetryReview = async (): Promise<void> => {
    if (starting || running || !state?.review_count) return;
    setStarting(true);
    setError("");
    try {
      setState(await retryResourceClassificationReviews());
    } catch (retryError) {
      setError(retryError instanceof Error ? retryError.message : "重新分类待确认网页失败");
    } finally {
      setStarting(false);
    }
  };

  const handleRetryClassified = async (): Promise<void> => {
    if (starting || running || !state?.classified_retry_count) return;
    setStarting(true);
    setError("");
    try {
      setState(await retryClassifiedResources());
    } catch (retryError) {
      setError(retryError instanceof Error ? retryError.message : "重新分类已完成网页失败");
    } finally {
      setStarting(false);
    }
  };

  return (
    <section className="resource-classification-panel" aria-label="已有网页大模型分类">
      <div className="resource-classification-heading">
        <div>
          <strong>大模型分类已有网页</strong>
          <p>结合网页标题、描述和可用的公开正文摘要，先由大模型列出可能标签，再按你的分类模板归类。新导入网页自动处理；确认失效的网页不参与分类，其余巡检状态仍会分类。已人工确认和自定义规则自动跳过。已完成的模型分类可用「重新分类已完成」再跑一轮。书签导入的网页会先由 Jev 判断原文件夹的归类是否正确，正确就沿用对应的分类。</p>
        </div>
      </div>
      <div className="resource-classification-actions">
        <button type="button" onClick={() => setReviewOpen(true)} disabled={!state}>
          分类确认 {state?.review_count ?? 0}
        </button>
        <button
          type="button"
          onClick={() => void handleRetryReview()}
          disabled={starting || running || !state || (state.review_count ?? 0) === 0}
        >
          重新分类待确认 {state?.review_count ?? 0}
        </button>
        <button
          type="button"
          onClick={() => void handleRetryClassified()}
          disabled={starting || running || !state || (state.classified_retry_count ?? 0) === 0}
        >
          重新分类已完成 {state?.classified_retry_count ?? 0}
        </button>
        <button
          type="button"
          onClick={() => setFolderOpen(true)}
          disabled={starting || running || !state || (state.folder_retry_count ?? 0) === 0}
          title="先确认文件夹对应的分类，再逐条判断已导入的书签"
        >
          按书签文件夹重新判断 {state?.folder_retry_count ?? 0}
        </button>
        <button
          type="button"
          onClick={() => void handleStart()}
          disabled={starting || running || !state || (state.pending_count === 0 && !canResume)}
        >
          {starting ? canResume ? "正在继续…" : "正在启动…" : waitingForRetry ? "等待自动重试…" : running ? "正在分类…" : canResume ? "继续任务" : state?.pending_count === 0 ? "当前可分类网页已处理" : job ? "处理剩余网页" : "开始批量分类"}
        </button>
      </div>
      {state && <p className="resource-classification-counts">
        待处理 {state.pending_count} · 已完成模型分类 {state.classified_count} · 保留人工确认与规则分类 {state.protected_count}
        {` · 暂缓分类（确认失效）${state.deferred_count}`}
      </p>}
      {job && <div role="status" className="resource-classification-progress">
        {running && <progress value={job.processed_count} max={Math.max(1, job.total_count)} aria-label="网页分类进度" />}
        <span>
          {waitingForRetry ? "等待自动重试" : job.status === "pending" ? "等待后台处理" : job.status === "processing" ? job.automatic ? "后台自动分类中" : "后台分类中" : job.status === "failed" ? "任务已暂停" : "本轮已完成"}
          {` · ${job.processed_count}/${job.total_count} · 成功 ${job.succeeded_count} · 未确定 ${job.failed_count} · 跳过 ${job.skipped_count}`}
        </span>
        {job.retry_count > 0 && <span>
          {`当前网页自动重试 ${job.retry_count}/${job.retry_limit}`}
          {waitingForRetry && (retrySeconds > 0 ? ` · 约 ${retrySeconds} 秒后继续` : " · 即将继续")}
        </span>}
        {canResume && <span>{`已保留处理进度，继续任务只处理本轮剩余 ${job.total_count - job.processed_count} 条。`}</span>}
        {job.failed_count > 0 && <span>未确定的网页保留原分类，可在分类确认中心批量确认；继续任务不会重复请求已处理条目。</span>}
        {job.error && <span role="alert">{job.error}</span>}
      </div>}
      {(error || loadError) && <p role="alert">{error || loadError}</p>}
      {folderOpen && <BookmarkFolderMappingDialog
        onClose={() => setFolderOpen(false)}
        onStarted={() => setRefresh((value) => value + 1)}
      />}
      {reviewOpen && <ResourceClassificationReviewDialog onClose={() => setReviewOpen(false)} onChanged={() => {
        onChangedRef.current();
        setRefresh((value) => value + 1);
      }} />}
    </section>
  );
}
