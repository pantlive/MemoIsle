import { useCallback, useEffect, useState } from "react";
import Icon from "./Icon";
import { pendingHealthIssueCount } from "./linkHealth";

import {
  applyLinkHealthAction,
  getLinkHealthCenter,
  updateLinkHealthSettings,
  updateLinkHealthSitePause,
} from "./api";
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

function hostnameFromUrl(value: string | null): string | null {
  if (!value) {
    return null;
  }
  try {
    return new URL(value).hostname.toLowerCase();
  } catch {
    return null;
  }
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
    ignore: "暂停此条",
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
  const [settingsBusy, setSettingsBusy] = useState(false);
  const [healthEnabled, setHealthEnabled] = useState(true);
  const [intervalHours, setIntervalHours] = useState(720);
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

  useEffect(() => {
    if (!center) {
      return;
    }
    setHealthEnabled(center.settings.enabled);
    setIntervalHours(center.settings.interval_hours);
  }, [center]);

  const handleSettingsSave = async () => {
    setSettingsBusy(true);
    setError("");
    try {
      const updated = await updateLinkHealthSettings({
        enabled: healthEnabled,
        interval_hours: intervalHours,
      });
      setCenter(updated);
      onChanged();
    } catch (settingsError) {
      setError(
        settingsError instanceof Error ? settingsError.message : "保存巡检设置失败。",
      );
    } finally {
      setSettingsBusy(false);
    }
  };

  const handleSitePause = async (hostname: string, paused: boolean) => {
    setSettingsBusy(true);
    setError("");
    try {
      const updated = await updateLinkHealthSitePause(hostname, paused);
      setCenter(updated);
      onChanged();
    } catch (pauseError) {
      setError(pauseError instanceof Error ? pauseError.message : "更新网站巡检设置失败。");
    } finally {
      setSettingsBusy(false);
    }
  };

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
        className="health-dialog dialog-shell"
        role="dialog"
        aria-modal="true"
        aria-labelledby="health-dialog-title"
      >
        <div className="dialog-header">
          <div>
            <span className="type-label">自动巡检</span>
            <h2 id="health-dialog-title">网页巡检中心</h2>
            {center && <p>
              当前显示 {center.items.length} 条，共 {filter ? center.counts[filter] : pendingHealthIssueCount(center.counts)} 条待处理
            </p>}
          </div>
          <button className="icon-button" aria-label="关闭巡检中心" onClick={onClose}>
            <Icon name="close" size={16} />
          </button>
        </div>

        <div className="dialog-body">
        <div className="health-summary">
          <div className="danger"><strong>{counts?.failed ?? 0}</strong><span>确认失效</span></div>
          <div><strong>{counts?.redirected ?? 0}</strong><span>网址跳转</span></div>
          <div><strong>{counts?.changed ?? 0}</strong><span>信息变化</span></div>
          <div><strong>{counts?.temporary_failure ?? 0}</strong><span>暂时失败</span></div>
        </div>

        <section className="health-settings" aria-label="巡检设置">
          <div className="health-settings-heading">
            <div>
              <strong>巡检设置</strong>
              <span>控制当前账号的自动巡检范围和频率</span>
            </div>
            <button
              type="button"
              className="primary"
              onClick={() => void handleSettingsSave()}
              disabled={settingsBusy}
            >
              {settingsBusy ? "保存中…" : "保存设置"}
            </button>
          </div>
          <div className="health-settings-fields">
            <label className="health-toggle">
              <input
                type="checkbox"
                checked={healthEnabled}
                onChange={(event) => setHealthEnabled(event.target.checked)}
              />
              <span>启用账号巡检</span>
            </label>
            <label>
              检查频率
              <select
                value={intervalHours}
                onChange={(event) => setIntervalHours(Number(event.target.value))}
                disabled={settingsBusy}
              >
                <option value={24}>每天</option>
                <option value={72}>每 3 天</option>
                <option value={168}>每周</option>
                <option value={720}>每 30 天</option>
                <option value={2160}>每 90 天</option>
                <option value={8760}>每年</option>
              </select>
            </label>
          </div>
          {!!center?.settings.paused_sites.length && (
            <div className="health-paused-sites">
              <span>已暂停网站</span>
              <div>
                {center.settings.paused_sites.map((hostname) => (
                  <button
                    type="button"
                    key={hostname}
                    onClick={() => void handleSitePause(hostname, false)}
                    disabled={settingsBusy}
                  >
                    {hostname} · 恢复
                  </button>
                ))}
              </div>
            </div>
          )}
        </section>

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
          {!loading && center && center.items.map((memo) => {
            const actions = actionsFor(memo);
            const [primary, ...rest] = actions;
            const hostname = hostnameFromUrl(memo.source_url);
            const sitePaused = Boolean(
              hostname && center.settings.paused_sites.includes(hostname),
            );
            return (
            <article className="health-result" key={memo.id}>
              <div className="health-result-heading">
                <div>
                  <span className={`health-status ${memo.link_health_status}`}>
                    {memo.link_health_status === "healthy" && memo.resource_ai_review_required
                      ? "已恢复，待人工确认"
                      : statusLabels[memo.link_health_status]}
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
                {primary && (
                  <button
                    type="button"
                    className={primary === "delete" ? "danger-button" : "primary"}
                    disabled={actingId === memo.id}
                    onClick={() => void handleAction(memo, primary)}
                  >
                    {actingId === memo.id ? "处理中…" : actionLabel(primary)}
                  </button>
                )}
                {(rest.length > 0 || hostname) && (
                  <details className="health-more">
                    <summary aria-label="更多操作">
                      <Icon name="more" size={16} />
                    </summary>
                    <div
                      className="health-more-menu"
                      // 选中任一操作后收起菜单，避免处理中时菜单还挂在列表上。
                      onClick={(event) => event.currentTarget.closest("details")?.removeAttribute("open")}
                    >
                      {rest.map((action) => (
                        <button
                          type="button"
                          className={action === "delete" ? "danger-button" : ""}
                          disabled={actingId === memo.id}
                          key={action}
                          onClick={() => void handleAction(memo, action)}
                        >
                          {actingId === memo.id ? "处理中…" : actionLabel(action)}
                        </button>
                      ))}
                      {hostname && (
                        <button
                          type="button"
                          disabled={settingsBusy || actingId === memo.id}
                          onClick={() => {
                            void handleSitePause(hostname, !sitePaused);
                          }}
                        >
                          {sitePaused ? "恢复此站点" : "暂停此站点"}
                        </button>
                      )}
                    </div>
                  </details>
                )}
              </div>
            </article>
            );
          })}
        </div>
        </div>

        {error && <div className="dialog-error" role="alert">{error}</div>}
      </section>
    </div>
  );
}
