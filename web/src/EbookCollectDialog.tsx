import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Icon from "./Icon";

import {
  createEbookJob,
  listCloudAccounts,
  listEbookJobs,
  retryEbookJob,
} from "./api";
import type { CloudAccount, EbookJob, EbookJobStatus } from "./types";

interface EbookCollectDialogProps {
  onClose: () => void;
  onChanged: () => void;
}

const statusLabels: Record<EbookJobStatus, string> = {
  pending: "排队中",
  running: "处理中",
  success: "已完成",
  failed: "失败",
};

const modeLabels: Record<EbookJob["mode"], string> = {
  transfer: "云盘转存",
  upload: "下载后上传",
};

const ACTIVE_STATUSES: EbookJobStatus[] = ["pending", "running"];
const POLL_INTERVAL_MS = 2000;

function parseTags(value: string): string[] {
  const parts = value
    .split(/[,，、\s]+/)
    .map((item) => item.trim())
    .filter(Boolean);
  return [...new Set(parts)].slice(0, 20);
}

export default function EbookCollectDialog({
  onClose,
  onChanged,
}: EbookCollectDialogProps) {
  const [accounts, setAccounts] = useState<CloudAccount[]>([]);
  const [jobs, setJobs] = useState<EbookJob[]>([]);
  const [url, setUrl] = useState("");
  const [sharePassword, setSharePassword] = useState("");
  const [targetFolder, setTargetFolder] = useState("");
  const [tagsInput, setTagsInput] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const notifiedRef = useRef(false);

  const activeAccount = useMemo(
    () => accounts.find((account) => account.status === "active") ?? null,
    [accounts],
  );
  const hasActiveJob = jobs.some((job) =>
    ACTIVE_STATUSES.includes(job.status),
  );

  const refreshJobs = useCallback(async () => {
    try {
      const next = await listEbookJobs();
      setJobs(next);
      if (next.some((job) => job.status === "success") && !notifiedRef.current) {
        notifiedRef.current = true;
        onChanged();
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "读取任务失败");
    }
  }, [onChanged]);

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const [accountsResult, jobsResult] = await Promise.all([
          listCloudAccounts(),
          listEbookJobs(),
        ]);
        if (!active) {
          return;
        }
        setAccounts(accountsResult);
        setJobs(jobsResult);
        const first = accountsResult.find(
          (account) => account.status === "active",
        );
        if (first) {
          setTargetFolder(first.default_folder);
        }
      } catch (error) {
        if (active) {
          setMessage(error instanceof Error ? error.message : "初始化失败");
        }
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!hasActiveJob) {
      return;
    }
    const timer = window.setInterval(() => void refreshJobs(), POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [hasActiveJob, refreshJobs]);

  const handleSubmit = async () => {
    if (busy) {
      return;
    }
    if (!url.trim()) {
      setMessage("请粘贴电子书链接");
      return;
    }
    setBusy(true);
    try {
      const job = await createEbookJob({
        url: url.trim(),
        share_password: sharePassword.trim() || null,
        target_folder: targetFolder.trim() || null,
        tags: parseTags(tagsInput),
        note: note.trim() || null,
      });
      setJobs((current) => [job, ...current]);
      setUrl("");
      setSharePassword("");
      setNote("");
      setMessage(`已提交：${modeLabels[job.mode]}，正在处理`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "提交失败");
    } finally {
      setBusy(false);
    }
  };

  const handleRetry = async (jobId: string) => {
    if (busy) {
      return;
    }
    setBusy(true);
    try {
      const job = await retryEbookJob(jobId);
      setJobs((current) =>
        current.map((item) => (item.id === job.id ? job : item)),
      );
      setMessage("已重新排队");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "重试失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="dialog-backdrop ebook-collect-backdrop" role="presentation">
      <section
        className="cloud-dialog ebook-collect-dialog dialog-shell"
        role="dialog"
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            event.stopPropagation();
            onClose();
          }
        }}
        aria-modal="true"
        aria-labelledby="ebook-dialog-title"
      >
        <div className="dialog-header">
          <div>
            <span className="type-label"><Icon name="book" size={16} /> 电子书</span>
            <h2 id="ebook-dialog-title">收藏电子书</h2>
          </div>
          <button
            autoFocus
            type="button"
            className="icon-button"
            aria-label="关闭收藏电子书"
            onClick={onClose}
          ><Icon name="close" size={16} /></button>
        </div>

        <div className="dialog-body">
          {!activeAccount && (
            <p className="cloud-dialog-note">
              还没有可用的云盘绑定。请先关闭本窗口，在「云盘绑定」里绑定阿里云盘，
              电子书才有地方存放。
            </p>
          )}

          <section className="cloud-bind-form">
            <label className="cloud-credential-field">
              <span>电子书链接</span>
              <input
                value={url}
                onChange={(event) => setUrl(event.target.value)}
                placeholder="云盘分享链接，或出版社/图书馆的下载直链"
                maxLength={2048}
              />
            </label>
            <label>
              <span>分享提取码（可选）</span>
              <input
                value={sharePassword}
                onChange={(event) => setSharePassword(event.target.value)}
                placeholder="链接里带 ?pwd= 时可留空"
                maxLength={100}
              />
            </label>
            <label>
              <span>转存目录</span>
              <input
                value={targetFolder}
                onChange={(event) => setTargetFolder(event.target.value)}
                placeholder={
                  activeAccount ? activeAccount.default_folder : "/MemoIsle/电子书"
                }
                maxLength={500}
              />
            </label>
            <label>
              <span>标签（逗号分隔）</span>
              <input
                value={tagsInput}
                onChange={(event) => setTagsInput(event.target.value)}
                placeholder="编程, 待读"
              />
            </label>
            <label className="cloud-credential-field">
              <span>备注（可选）</span>
              <textarea
                value={note}
                onChange={(event) => setNote(event.target.value)}
                placeholder="从哪看到的、为什么想读"
                rows={2}
                maxLength={2000}
              />
            </label>

            <p className="cloud-dialog-hint">
              云盘分享链接会被转存到你的云盘；普通直链由服务端下载后上传。
              MemoIsle 只保存云盘链接与元数据快照，不保存电子书本体。
            </p>
          </section>

          <section className="cloud-account-list" aria-label="电子书任务">
            {!jobs.length && <div className="cloud-empty">还没有电子书任务。</div>}
            {jobs.map((job) => (
              <article className="ebook-job" key={job.id}>
                <div className="cloud-account-heading">
                  <div>
                    <span className={`cloud-status ${job.status}`}>
                      {statusLabels[job.status]}
                    </span>
                    <h3>{modeLabels[job.mode]} · {job.stage || "等待开始"}</h3>
                  </div>
                  <span className="cloud-account-hint">{job.progress}%</span>
                </div>
                <div className="ebook-progress" aria-hidden="true">
                  <span style={{ width: `${job.progress}%` }} />
                </div>
                <div className="cloud-account-meta">
                  <span className="ebook-source">{job.source_url}</span>
                  <span>目标目录：{job.target_folder}</span>
                  {job.error && <span>失败原因：{job.error}</span>}
                </div>
                {job.status === "failed" && (
                  <div className="cloud-account-actions">
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => void handleRetry(job.id)}
                    >重试</button>
                  </div>
                )}
              </article>
            ))}
          </section>
        </div>
        <div className="dialog-actions">
          <button type="button" onClick={onClose}>关闭</button>
          <button
            type="button"
            className="primary"
            disabled={busy || !activeAccount}
            onClick={() => void handleSubmit()}
          >提交并转存</button>
        </div>
        {message && <p className="dialog-error cloud-dialog-message" role="status">{message}</p>}
      </section>
    </div>
  );
}
