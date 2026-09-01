import { useCallback, useEffect, useState } from "react";

import { applyLinkHealthAction, getLinkHealthCenter } from "./api";
import type {
  LinkHealthAction,
  LinkHealthCenter,
  LinkHealthStatus,
  Memo,
} from "./types";

interface LinkHealthDialogProps {
  onClose: () => void;
  onChanged: () => void;
}

const filters: Array<{ value: LinkHealthStatus | ""; label: string }> = [
  { value: "", label: "待处理" },
  { value: "failed", label: "确认失效" },
  { value: "redirected", label: "网址跳转" },
  { value: "changed", label: "信息变化" },
  { value: "temporary_failure", label: "暂时失败" },
  { value: "auth_required", label: "需要登录" },
  { value: "ignored", label: "已忽略" },
];

const statusLabels: Record<LinkHealthStatus, string> = {
  unchecked: "等待检查",
  healthy: "正常",
  redirected: "网址已跳转",
  changed: "网页信息有变化",
  auth_required: "需要登录",
  temporary_failure: "暂时无法访问",
  failed: "确认失效",
  ignored: "已忽略",
};

const dateFormatter = new Intl.DateTimeFormat("zh-CN", {
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

function formatTime(value: string | null): string {
  return value ? dateFormatter.format(new Date(value)) : "暂无";
}

function actionsFor(memo: Memo): LinkHealthAction[] {
  if (memo.link_health_status === "ignored") {
    return ["resume"];
  }
  if (memo.link_health_status === "redirected") {
    return ["adopt_redirect", "retry", "ignore", "delete"];
  }
  if (memo.link_health_status === "changed") {
    return ["update_metadata", "retry", "ignore"];
  }
  return ["retry", "update_url", "ignore", "delete"];
}

function actionLabel(action: LinkHealthAction): string {
  const labels: Record<LinkHealthAction, string> = {
    retry: "重新检查",
    ignore: "忽略提醒",
    resume: "恢复巡检",
    adopt_redirect: "采用新网址",
    update_url: "更新网址",
    update_metadata: "更新资料信息",
    delete: "删除资料",
  };
  return labels[action];
}

export default function LinkHealthDialog({
  onClose,
  onChanged,
}: LinkHealthDialogProps) {
  const [filter, setFilter] = useState<LinkHealthStatus | "">("");
  const [center, setCenter] = useState<LinkHealthCenter | null>(null);
  const [loading, setLoading] = useState(true);
  const [actingId, setActingId] = useState<string | null>(null);
  const [error, setError] = useState("");

  const loadCenter = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setCenter(await getLinkHealthCenter(filter || undefined));
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "读取巡检结果失败。");
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => {
    void loadCenter();
  }, [loadCenter]);

  const handleAction = async (memo: Memo, action: LinkHealthAction) => {
    let newUrl: string | undefined;
    if (action === "update_url") {
      newUrl = window.prompt("输入替换后的完整 HTTP(S) 网址", memo.link_effective_url || memo.source_url || "")?.trim();
      if (!newUrl) {
        return;
      }
    }
    if (
      action === "delete" &&
      !window.confirm("这条网页资料会移入回收站，确定继续吗？")
    ) {
      return;
    }
    setActingId(memo.id);
    setError("");
    try {
      await applyLinkHealthAction(memo.id, memo.version, action, newUrl);
      await loadCenter();
      onChanged();
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : "处理失败。");
    } finally {
      setActingId(null);
    }
  };

  const counts = center?.counts;
  return (
    <div className="dialog-backdrop" role="presentation">
      <section
        className="health-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="health-dialog-title"
      >
        <div className="dialog-header">
          <div>
            <span className="type-label">自动巡检</span>
            <h2 id="health-dialog-title">网页巡检中心</h2>
          </div>
          <button className="icon-button" aria-label="关闭巡检中心" onClick={onClose}>×</button>
        </div>

        <div className="health-summary">
          <div className="danger"><strong>{counts?.failed ?? 0}</strong><span>确认失效</span></div>
          <div><strong>{counts?.redirected ?? 0}</strong><span>网址跳转</span></div>
          <div><strong>{counts?.changed ?? 0}</strong><span>信息变化</span></div>
          <div><strong>{counts?.temporary_failure ?? 0}</strong><span>暂时失败</span></div>
        </div>

        <div className="health-filters" aria-label="巡检结果筛选">
          {filters.map((item) => (
            <button
              type="button"
              className={filter === item.value ? "active" : ""}
              key={item.value || "actionable"}
              onClick={() => setFilter(item.value)}
            >{item.label}</button>
          ))}
        </div>

        <div className="health-result-list">
          {loading && <div className="health-empty">正在读取巡检结果…</div>}
          {!loading && !center?.items.length && (
            <div className="health-empty">这个分组目前没有需要处理的网页。</div>
          )}
          {!loading && center?.items.map((memo) => (
            <article className="health-result" key={memo.id}>
              <div className="health-result-heading">
                <div>
                  <span className={`health-status ${memo.link_health_status}`}>
                    {statusLabels[memo.link_health_status]}
                  </span>
                  <h3>{memo.title}</h3>
                </div>
                <span>连续失败 {memo.link_consecutive_failures} 次</span>
              </div>
              <a href={memo.source_url || "#"} target="_blank" rel="noreferrer">
                {memo.source_url}
              </a>
              {memo.link_effective_url && memo.link_effective_url !== memo.source_url && (
                <p>候选新网址：{memo.link_effective_url}</p>
              )}
              <div className="health-result-meta">
                <span>最近成功：{formatTime(memo.link_last_success_at)}</span>
                <span>最近检查：{formatTime(memo.link_last_checked_at)}</span>
                <span>{memo.link_health_error || (memo.link_health_http_status ? `HTTP ${memo.link_health_http_status}` : "等待判定")}</span>
              </div>
              <div className="health-actions">
                {actionsFor(memo).map((action) => (
                  <button
                    type="button"
                    className={action === "delete" ? "danger-button" : ""}
                    disabled={actingId === memo.id}
                    key={action}
                    onClick={() => void handleAction(memo, action)}
                  >{actingId === memo.id ? "处理中…" : actionLabel(action)}</button>
                ))}
              </div>
            </article>
          ))}
        </div>

        {error && <div className="dialog-error" role="alert">{error}</div>}
      </section>
    </div>
  );
}
