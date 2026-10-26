import { type ReactNode, useEffect, useRef, useState } from "react";

import {
  confirmResourceClassificationReviews,
  getResourceCategories,
  getResourceClassificationReviews,
  retryResourceClassificationReviews,
} from "./api";
import Icon from "./Icon";
import ResourceClassificationInsight from "./ResourceClassificationInsight";
import type { ResourceCategoryOption, ResourceClassificationReviewAction, ResourceClassificationReviewList } from "./types";

const reasons: Record<string, string> = {
  low_confidence: "置信度不足",
  unknown_category: "模板中无此类别",
  invalid_response: "分类数据无效",
  no_match: "口径都不匹配",
  folder_conflict: "与书签文件夹判断相反",
  legacy: "未保存候选",
};
const skipReasons: Record<string, string> = {
  missing: "网页已移除",
  conflict: "网页已修改，请刷新后确认",
  not_pending: "已确认、已处理或需要先完成巡检",
  no_candidate: "没有可采纳的候选，请指定分类或保留原分类",
  category_unavailable: "候选分类已删除或停用",
};

export default function ResourceClassificationReviewDialog({
  onClose,
  onChanged,
}: { onClose: () => void; onChanged: () => void }): ReactNode {
  const [query, setQuery] = useState("");
  const [reason, setReason] = useState("");
  const [candidate, setCandidate] = useState("");
  const [maxConfidence, setMaxConfidence] = useState("");
  const [offset, setOffset] = useState(0);
  const [refresh, setRefresh] = useState(0);
  const [list, setList] = useState<ResourceClassificationReviewList | null>(null);
  const [categories, setCategories] = useState<ResourceCategoryOption[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [choices, setChoices] = useState<Record<string, string>>({});
  const [target, setTarget] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [skipped, setSkipped] = useState<string[]>([]);
  const onChangedRef = useRef(onChanged);
  onChangedRef.current = onChanged;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    // 每次筛选或刷新重新选择，提交只覆盖当前页面明确勾选的版本。
    setSelected(new Set());
    setChoices({});
    void Promise.all([
      getResourceClassificationReviews({ query, reason, candidate_code: candidate, max_confidence: maxConfidence, offset }),
      getResourceCategories(),
    ]).then(([updated, options]) => {
      if (cancelled) return;
      setList(updated);
      setCategories(options);
    }).catch((loadError: unknown) => {
      if (!cancelled) {
        setList(null);
        setError(loadError instanceof Error ? loadError.message : "读取待确认网页失败");
      }
    }).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [query, reason, candidate, maxConfidence, offset, refresh]);

  const rows = list?.items ?? [];
  const selectedRows = rows.filter((item) => selected.has(item.id));
  const availableChoices = selectedRows.filter((item) => item.candidates.some((choice) =>
    choice.available && choice.code === (choices[item.id] ?? item.candidates[0]?.code),
  ));
  const disabled = busy || loading;
  const setFilter = (change: () => void): void => { change(); setOffset(0); };
  const toggle = (id: string): void => setSelected((current) => {
    const updated = new Set(current);
    if (updated.has(id)) updated.delete(id); else updated.add(id);
    return updated;
  });

  useEffect(() => {
    const handleKey = (event: KeyboardEvent): void => {
      if (event.key === "Escape" && !busy) onClose();
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [busy, onClose]);

  const confirm = async (action: ResourceClassificationReviewAction): Promise<void> => {
    if (disabled || selectedRows.length === 0) return;
    setBusy(true);
    setError("");
    setNotice("");
    setSkipped([]);
    try {
      const result = await confirmResourceClassificationReviews({
        action,
        items: selectedRows.map((item) => ({
          memo_id: item.id,
          expected_version: item.version,
          ...(action === "adopt" && (choices[item.id] ?? item.candidates[0]?.code)
            ? { candidate_code: choices[item.id] ?? item.candidates[0].code } : {}),
        })),
        ...(action === "assign" ? { category_code: target } : {}),
      });
      setNotice(`已确认 ${result.updated_count} 条，跳过 ${result.skipped_count} 条。`);
      setSkipped(result.results.filter((item) => item.status === "skipped").map((item) =>
        `${selectedRows.find((row) => row.id === item.memo_id)?.title || "网页"}：${skipReasons[item.reason || ""] || "请刷新后重试"}`,
      ));
      onChangedRef.current();
      setOffset(0);
      setRefresh((value) => value + 1);
    } catch (confirmError) {
      setError(confirmError instanceof Error ? confirmError.message : "确认分类失败");
    } finally {
      setBusy(false);
    }
  };

  return <div className="dialog-backdrop" role="presentation">
    <section className="classification-review-dialog dialog-shell" role="dialog" aria-modal="true" aria-labelledby="classification-review-title">
      <div className="dialog-header">
        <div>
          <span className="type-label"><Icon name="review" size={16} /> 智能分类</span>
          <h2 id="classification-review-title">分类确认中心</h2>
          <p>复核模型未确定的网页。也可以把全部待确认网页重新交给大模型按分类模板归类；人工确认后不再自动分类。确认失效的网页不进入分类确认。</p>
        </div>
        <button type="button" className="icon-button" aria-label="关闭分类确认中心" onClick={onClose} disabled={busy}>
          <Icon name="close" size={16} />
        </button>
      </div>
      <div className="dialog-body">
      <div className="classification-review-filters">
        <label>搜索待确认网页<input type="search" maxLength={200} value={query} disabled={busy}
          onChange={(event) => setFilter(() => setQuery(event.target.value))} placeholder="标题、网址或网页描述" /></label>
        <label>未确定原因<select value={reason} disabled={busy} onChange={(event) => setFilter(() => setReason(event.target.value))}>
          <option value="">全部原因</option>
          {Object.entries(reasons).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select></label>
        <label>首选候选类别<select value={candidate} disabled={busy} onChange={(event) => setFilter(() => setCandidate(event.target.value))}>
          <option value="">全部候选</option><option value="_none">未保存候选</option>
          {categories.map((item) => <option key={item.code} value={item.code}>{item.path || item.name}{item.is_active ? "" : "（已停用）"}</option>)}
        </select></label>
        <label>最高置信度<select value={maxConfidence} disabled={busy} onChange={(event) => setFilter(() => setMaxConfidence(event.target.value))}>
          <option value="">不限（含未提供）</option><option value="0.7">70% 及以下</option>
          <option value="0.5">50% 及以下</option><option value="0.3">30% 及以下</option>
        </select></label>
      </div>
      <div className="classification-review-toolbar">
        <label className="classification-review-check"><input type="checkbox" disabled={disabled || rows.length === 0}
          checked={rows.length > 0 && selectedRows.length === rows.length}
          onChange={(event) => setSelected(event.target.checked ? new Set(rows.map((item) => item.id)) : new Set())} />全选当前页</label>
        <span>已选 {selectedRows.length} 条</span>
        <button type="button" className="ghost" disabled={disabled || selectedRows.length === 0} onClick={() => void confirm("keep")}>保留原分类</button>
        <label>指定分类<select value={target} disabled={disabled} onChange={(event) => setTarget(event.target.value)}>
          <option value="">选择分类</option>
          {categories.filter((item) => item.is_active).map((item) => <option key={item.code} value={item.code}>{item.path || item.name}</option>)}
        </select></label>
        <button type="button" className="ghost" disabled={disabled || selectedRows.length === 0 || !target || !categories.some((item) => item.code === target && item.is_active)}
          onClick={() => void confirm("assign")}>应用指定分类</button>
      </div>
      {notice && <p role="status">{notice}</p>}
      {skipped.length > 0 && <details className="classification-review-skipped" open><summary>跳过原因</summary>
        <ul>{skipped.map((message, index) => <li key={index}>{message}</li>)}</ul>
      </details>}
      {loading ? <p role="status">正在读取待确认网页…</p> : <>
        <p className="classification-review-total">共 {list?.total_count ?? 0} 条符合筛选条件{rows.length > 0 && ` · 当前 ${offset + 1}–${offset + rows.length} 条`}</p>
        {rows.length === 0 && !error && <p>当前没有待确认的网页。</p>}
        <div className="classification-review-items">
          {rows.map((item) => <article className="classification-review-item" key={item.id}>
            <input type="checkbox" aria-label={`选择 ${item.title}`} disabled={busy} checked={selected.has(item.id)} onChange={() => toggle(item.id)} />
            <div>
              <a href={item.source_url} target="_blank" rel="noreferrer">{item.title}</a>
              <p>当前分类：{item.current_category_label || "未分类"}</p>
              <p>{reasons[item.assessment?.reason_code || "legacy"] || "模型未确定"}
                {item.assessment?.reason_code === "low_confidence" && item.assessment.confidence !== null && ` · 置信度 ${(item.assessment.confidence * 100).toFixed(0)}%`}</p>
              {item.candidates.length > 0 ? <label>采纳候选<select aria-label={`${item.title}的候选类别`} disabled={busy}
                value={choices[item.id] ?? item.candidates[0].code} onChange={(event) => setChoices((current) => ({ ...current, [item.id]: event.target.value }))}>
                {item.candidates.map((choice) => <option key={choice.code} value={choice.code} disabled={!choice.available}>
                  {choice.label}{choice.probability !== null ? ` · 概率 ${(choice.probability * 100).toFixed(1)}%` : ""}{choice.available ? "" : "（不可用）"}
                </option>)}
              </select></label> : <p>未保存候选，可指定分类或保留原分类。</p>}
              {item.assessment && <details><summary>查看分类依据</summary><ResourceClassificationInsight assessment={item.assessment} /></details>}
            </div>
          </article>)}
        </div>
      </>}
      <div className="classification-review-pagination">
        <button type="button" className="ghost" disabled={disabled || offset === 0} onClick={() => setOffset(Math.max(0, offset - 50))}>上一页</button>
        <button type="button" className="ghost" disabled={disabled || !list || offset + list.limit >= list.total_count} onClick={() => setOffset(offset + 50)}>下一页</button>
        <button type="button" className="ghost" disabled={disabled} onClick={() => setRefresh((value) => value + 1)}>刷新列表</button>
      </div>
      </div>
      <div className="dialog-actions">
        <button
          type="button"
          className="ghost"
          disabled={disabled || (list?.total_count ?? 0) === 0}
          onClick={() => {
            if (disabled || (list?.total_count ?? 0) === 0) return;
            setBusy(true);
            setError("");
            setNotice("");
            void retryResourceClassificationReviews().then(() => {
              onChangedRef.current();
              onClose();
            }).catch((retryError: unknown) => {
              setError(retryError instanceof Error ? retryError.message : "重新分类待确认网页失败");
            }).finally(() => setBusy(false));
          }}
        >重新分类全部待确认 {list?.total_count ?? 0}</button>
        <button type="button" className="primary" disabled={disabled || availableChoices.length === 0} onClick={() => void confirm("adopt")}>采纳所选候选</button>
      </div>
      {error && <div className="dialog-error" role="alert">{error}</div>}
    </section>
  </div>;
}
