import { useEffect, useRef, useState, type FormEvent } from "react";

import ResourceClassificationInsight from "./ResourceClassificationInsight";
import type { Memo, MemoType } from "./types";
import { normalizeWebUrl, sourceHost } from "./webUrl";

const MAX_TAGS = 20;
const openedFormatter = new Intl.DateTimeFormat("zh-CN", {
  month: "numeric",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

export type ResourceEditChanges = {
  title: string;
  body: string;
  source_url: string;
  tags: string[];
};

// 标签输入支持逗号、顿号或空格分隔，允许带 # 前缀。
function parseTagInput(value: string): string[] {
  const tags = value
    .split(/[,，、\s]+/)
    .map((tag) => tag.replace(/^#+/, "").trim())
    .filter(Boolean);
  return [...new Set(tags)].slice(0, MAX_TAGS);
}

function resourceNote(memo: Memo): string {
  return memo.body === memo.source_url ? "" : memo.body;
}

function hasClassificationDetail(memo: Memo): boolean {
  return Boolean(
    memo.resource_ai_confirmation
    || (memo.resource_ai_assessment && memo.resource_category_source !== "manual"),
  );
}

export default function ResourcePreviewDialog({
  memo,
  categoryLabels,
  busy,
  typeChanging,
  onClose,
  onSave,
  onCopyLink,
  onArchive,
  onTrash,
  onChangeType,
  onTagSearch,
  onOpenSource,
  onQuickAccessHiddenChange,
  initialEditing = false,
}: {
  memo: Memo;
  categoryLabels: string[];
  busy: boolean;
  typeChanging: boolean;
  onClose: () => void;
  // 返回错误文案；保存成功返回 null。
  onSave: (changes: ResourceEditChanges) => Promise<string | null>;
  onCopyLink: () => void;
  onArchive: () => void;
  onTrash: () => void;
  onChangeType: (type: MemoType) => void;
  onTagSearch: (tag: string) => void;
  // 每次打开原网页都要回报，用于快速访问计数。
  onOpenSource: () => void;
  onQuickAccessHiddenChange: (hidden: boolean) => void;
  // 从列表按 E 打开时直接进入编辑。
  initialEditing?: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState("");
  const [url, setUrl] = useState("");
  const [note, setNote] = useState("");
  const [tagText, setTagText] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const titleRef = useRef<HTMLInputElement>(null);
  const dialogRef = useRef<HTMLElement>(null);
  const savedNote = resourceNote(memo);

  const startEditing = () => {
    setTitle(memo.title);
    setUrl(memo.source_url ?? "");
    setNote(resourceNote(memo));
    setTagText(memo.tags.join("，"));
    setError("");
    setEditing(true);
  };
  const startEditingRef = useRef(startEditing);
  startEditingRef.current = startEditing;

  useEffect(() => {
    if (initialEditing) {
      startEditingRef.current();
    } else {
      setEditing(false);
      setError("");
    }
  }, [memo.id, initialEditing]);

  useEffect(() => {
    // 不在编辑时把焦点放在弹窗上，避免键盘事件继续落在背后的列表行上。
    if (editing) titleRef.current?.focus();
    else dialogRef.current?.focus();
  }, [editing]);

  useEffect(() => {
    const handleKey = (event: KeyboardEvent) => {
      if (saving) return;
      if (event.key === "Escape") {
        if (editing) {
          setEditing(false);
          setError("");
        } else {
          onClose();
        }
        return;
      }
      const target = event.target as HTMLElement | null;
      const typing = target?.tagName === "INPUT" || target?.tagName === "TEXTAREA"
        || target?.tagName === "SELECT" || target?.isContentEditable;
      if (editing || typing || event.ctrlKey || event.metaKey || event.altKey) return;
      const key = event.key.toLowerCase();
      if (key === "e" && !busy) {
        event.preventDefault();
        startEditingRef.current();
      } else if (key === "o" && memo.source_url) {
        event.preventDefault();
        window.open(memo.source_url, "_blank", "noopener,noreferrer");
        onOpenSource();
      }
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [editing, saving, busy, memo.source_url, onClose, onOpenSource]);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const sourceUrl = normalizeWebUrl(url);
    if (!sourceUrl) {
      setError("请输入有效的网址，例如 https://example.com/article。");
      return;
    }
    const cleanedNote = note.trim();
    setSaving(true);
    setError("");
    const failure = await onSave({
      title: title.trim() || sourceHost(sourceUrl),
      // 没有备注时正文沿用网址，与新建网页资料的约定一致。
      body: cleanedNote || sourceUrl,
      source_url: sourceUrl,
      tags: parseTagInput(tagText),
    });
    setSaving(false);
    if (failure) {
      setError(failure);
    } else {
      setEditing(false);
    }
  };

  return (
    <div className="dialog-backdrop">
      <section
        ref={dialogRef}
        tabIndex={-1}
        className="resource-preview-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="resource-preview-title"
      >
        <div className="dialog-header">
          <div>
            <span className="type-label">↗ 网页资料</span>
            <h2 id="resource-preview-title">{editing ? "编辑网页资料" : memo.title}</h2>
          </div>
          <button
            type="button"
            className="icon-button"
            aria-label="关闭网页资料预览"
            onClick={onClose}
            disabled={saving}
          >
            ×
          </button>
        </div>

        {editing ? (
          <form className="resource-edit-form" onSubmit={(event) => void handleSubmit(event)}>
            <label>
              标题
              <input
                ref={titleRef}
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                placeholder="留空时使用站点名"
                maxLength={200}
              />
            </label>
            <label>
              网址
              <input
                value={url}
                onChange={(event) => setUrl(event.target.value)}
                inputMode="url"
                autoCapitalize="none"
                maxLength={2_048}
                required
              />
              {normalizeWebUrl(url) !== memo.source_url && normalizeWebUrl(url) && (
                <small>修改网址后会重新读取网页信息并重新分类。</small>
              )}
            </label>
            <label>
              备注
              <textarea
                value={note}
                onChange={(event) => setNote(event.target.value)}
                rows={4}
                maxLength={50_000}
              />
            </label>
            <label>
              标签
              <input
                value={tagText}
                onChange={(event) => setTagText(event.target.value)}
                placeholder="用逗号或空格分隔，例如：React，前端"
              />
              <small>最多 {MAX_TAGS} 个。</small>
            </label>
            {error && <p className="resource-edit-error" role="alert">{error}</p>}
            <div className="dialog-actions resource-preview-actions">
              <button
                type="button"
                onClick={() => {
                  setEditing(false);
                  setError("");
                }}
                disabled={saving}
              >
                取消
              </button>
              <button type="submit" className="primary" disabled={saving}>
                {saving ? "保存中…" : "保存"}
              </button>
            </div>
          </form>
        ) : (
          <>
            <div className="resource-preview-content">
              {memo.resource_description && <p>{memo.resource_description}</p>}
              {savedNote && (
                <div className="resource-preview-note">
                  <span>个人备注</span>
                  <p>{savedNote}</p>
                </div>
              )}
              {memo.tags.length > 0 && (
                <div className="resource-user-tags" aria-label="我的标签">
                  {memo.tags.map((tag) => (
                    <button
                      type="button"
                      key={tag}
                      className="resource-user-tag"
                      title={`在网页资料中搜索「${tag}」`}
                      onClick={() => onTagSearch(tag)}
                    >
                      #{tag}
                    </button>
                  ))}
                </div>
              )}
              <p className="resource-preview-categories">
                分类：{categoryLabels.length > 0 ? categoryLabels.join(" · ") : "分类中"}
              </p>
              <a
                className="resource-preview-url"
                href={memo.source_url ?? undefined}
                target="_blank"
                rel="noreferrer"
                onClick={() => memo.source_url && onOpenSource()}
                onAuxClick={(event) => event.button === 1 && memo.source_url && onOpenSource()}
              >
                {memo.source_url || "暂无来源网址"}
              </a>
              <span className="resource-preview-meta">
                {memo.resource_site_name || sourceHost(memo.source_url)}
                {memo.resource_open_count > 0 && ` · 已打开 ${memo.resource_open_count} 次`}
                {memo.resource_last_opened_at && ` · 最近 ${openedFormatter.format(new Date(memo.resource_last_opened_at))}`}
                {memo.link_health_status !== "unchecked" && ` · 巡检：${memo.link_health_status}`}
              </span>
              {(memo.resource_open_count > 0 || memo.resource_quick_access_hidden) && (
                <p className="resource-preview-quick-access">
                  {memo.resource_quick_access_hidden
                    ? "已从快速访问移除。"
                    : "会按打开次数出现在快速访问。"}
                  <button
                    type="button"
                    onClick={() => onQuickAccessHiddenChange(!memo.resource_quick_access_hidden)}
                  >
                    {memo.resource_quick_access_hidden ? "重新显示" : "从快速访问移除"}
                  </button>
                </p>
              )}
              {hasClassificationDetail(memo) && (
                <details className="resource-preview-insight">
                  <summary>分类依据</summary>
                  <ResourceClassificationInsight memo={memo} />
                </details>
              )}
              <label className="resource-preview-type">
                转换为
                <select
                  value={memo.type}
                  disabled={typeChanging}
                  onChange={(event) => onChangeType(event.target.value as MemoType)}
                >
                  <option value="resource">网页资料</option>
                  <option value="idea">灵感</option>
                  <option value="word">英语单词</option>
                </select>
              </label>
            </div>
            <div className="dialog-actions resource-preview-actions">
              <button type="button" onClick={startEditing} disabled={busy}>编辑</button>
              <button type="button" onClick={onCopyLink} disabled={!memo.source_url}>复制链接</button>
              <button type="button" onClick={onArchive} disabled={busy}>
                {busy ? "处理中…" : "归档"}
              </button>
              <button type="button" className="danger-button" onClick={onTrash}>回收站</button>
              <button
                type="button"
                className="primary"
                onClick={() => {
                  if (memo.source_url) {
                    window.open(memo.source_url, "_blank", "noopener,noreferrer");
                    onOpenSource();
                  }
                }}
                disabled={!memo.source_url}
              >
                打开原网页
              </button>
            </div>
          </>
        )}
      </section>
    </div>
  );
}
