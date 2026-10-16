import { type FormEvent, type ReactNode, useEffect, useMemo, useState } from "react";

import { ApiError, createResourceCategory, generateResourceCategories } from "./api";
import type {
  ResourceCategoryGenerateMode,
  ResourceCategoryOption,
  ResourceCategorySuggestion,
} from "./types";

interface CategoryGeneratorProps {
  categories: ResourceCategoryOption[];
  onAdded: () => Promise<void>;
}

const STORAGE_KEY = "memoisle_cluster_category_suggestions";

function readStoredSuggestions(): ResourceCategorySuggestion[] {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((item): item is ResourceCategorySuggestion => (
      Boolean(item) && typeof item === "object" && typeof (item as ResourceCategorySuggestion).name === "string"
    ));
  } catch {
    return [];
  }
}

export default function CategoryGenerator({
  categories,
  onAdded,
}: CategoryGeneratorProps): ReactNode {
  const [instructions, setInstructions] = useState("");
  const [suggestions, setSuggestions] = useState<ResourceCategorySuggestion[]>(readStoredSuggestions);
  const [resultMode, setResultMode] = useState<ResourceCategoryGenerateMode | null>(
    readStoredSuggestions().length > 0 ? "subcategories" : null,
  );
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState(
    readStoredSuggestions().length > 0 ? "上次聚类的标签还在，可继续加入模板或重新确认顶级分类。" : "",
  );
  const topLevel = useMemo(
    () => categories.filter((item) => item.is_active && !item.parent_code),
    [categories],
  );

  useEffect(() => {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(suggestions));
    } catch {
      // 存储满或被禁用时仍展示当前会话里的标签。
    }
  }, [suggestions]);

  const handleGenerate = async (mode: ResourceCategoryGenerateMode): Promise<void> => {
    if (busy) return;
    setBusy(true);
    setMessage("");
    try {
      const result = await generateResourceCategories(instructions.trim(), mode);
      setSuggestions(result.categories);
      setResultMode(mode);
      if (mode === "top_level") {
        setMessage(
          result.categories.length
            ? `已补出 ${result.categories.length} 个顶级分类建议。加入模板后，再确认够用并细分。`
            : "这次没有补出新的顶级分类，可以补充整理要求后重试。",
        );
      } else {
        setMessage(
          result.categories.length
            ? `已按现有顶级分类细分出 ${result.categories.length} 个细类。加入模板后再重新分类。`
            : "这次没有生成细类，可以补充整理要求后重试。",
        );
      }
    } catch (error) {
      setMessage(error instanceof ApiError ? error.message : "分类建议生成失败，请稍后重试。");
    } finally {
      setBusy(false);
    }
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>): void => {
    event.preventDefault();
  };

  const handleAdd = async (index: number): Promise<void> => {
    if (busy) return;
    const suggestion = suggestions[index];
    if (!suggestion?.name.trim() || suggestion.existing_code) return;
    setBusy(true);
    try {
      const created = await createResourceCategory({
        name: suggestion.name.trim(),
        description: suggestion.description?.trim() || undefined,
        parent_code: suggestion.parent_code || undefined,
      });
      setSuggestions((current) => current.filter((_item, position) => position !== index));
      setMessage(`已添加「${created.name}」。加入模板后重新分类，网页上会用这个标签。`);
      await onAdded();
    } catch (error) {
      setMessage(error instanceof ApiError ? error.message : "添加分类失败，请稍后重试。");
    } finally {
      setBusy(false);
    }
  };

  const updateSuggestion = (index: number, changes: Partial<ResourceCategorySuggestion>): void => {
    setSuggestions((current) => current.map((item, position) => position === index ? { ...item, ...changes } : item));
  };

  return (
    <div className="category-generator">
      <h3>智能生成分类</h3>
      <p className="category-generator-message">
        先确认当前顶级分类是否够用。够用后再按这些大类细分；不够就先补顶级分类，加入模板后再细分。
      </p>
      <form className="category-create-form" onSubmit={handleSubmit}>
        <h4 className="cluster-confirm-heading">当前顶级分类</h4>
        {topLevel.length > 0 ? (
          <ul className="cluster-top-level-list" aria-label="当前顶级分类">
            {topLevel.map((category) => (
              <li key={category.code}>
                <strong className="cluster-tag-chip">#{category.path || category.name}</strong>
              </li>
            ))}
          </ul>
        ) : (
          <p className="category-generator-message">还没有启用的顶级分类。</p>
        )}
        <textarea
          value={instructions}
          onChange={(event) => setInstructions(event.target.value)}
          placeholder="可选。例如：细分类偏 AI 编程工具和论文。"
          aria-label="分类整理要求"
          maxLength={2000}
          rows={3}
          disabled={busy}
        />
        <div className="cluster-confirm-actions">
          <button
            type="button"
            className="cluster-confirm-primary"
            disabled={busy || topLevel.length === 0}
            onClick={() => void handleGenerate("subcategories")}
          >
            {busy ? "正在处理……" : "够用，开始细分"}
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => void handleGenerate("top_level")}
          >
            {busy ? "正在处理……" : "不够，先补顶级分类"}
          </button>
        </div>
      </form>
      {message && <p className="category-generator-message" role="status">{message}</p>}
      {suggestions.length > 0 && (
        <ul
          className="cluster-tag-list"
          aria-label={resultMode === "top_level" ? "顶级分类建议" : "细类建议"}
        >
          {suggestions.map((suggestion, index) => (
            <li key={`${suggestion.existing_code || suggestion.name}-${index}`} className="cluster-tag-card">
              <strong className="cluster-tag-chip">#{suggestion.name || "未命名"}</strong>
              {suggestion.existing_code ? null : (
                <input
                  className="cluster-tag-name"
                  value={suggestion.name}
                  onChange={(event) => updateSuggestion(index, { name: event.target.value })}
                  aria-label={`建议 ${index + 1} 的分类名称`}
                  maxLength={50}
                  disabled={busy}
                />
              )}
              {suggestion.description && <p>{suggestion.description}</p>}
              {(suggestion.examples ?? []).length > 0 && (
                <p className="cluster-tag-examples">例如：{(suggestion.examples ?? []).join("、")}</p>
              )}
              {suggestion.existing_code ? (
                <small>已有模板</small>
              ) : (
                <div className="cluster-tag-actions">
                  {resultMode === "top_level" ? null : (
                    <select
                      value={suggestion.parent_code || ""}
                      onChange={(event) => updateSuggestion(index, { parent_code: event.target.value || null })}
                      aria-label={`建议 ${index + 1} 的父分类`}
                      disabled={busy}
                    >
                      <option value="">顶级分类</option>
                      {categories.filter((item) => item.is_active && (item.depth || 1) < 3).map((item) => (
                        <option key={item.code} value={item.code}>{item.path || item.name}</option>
                      ))}
                    </select>
                  )}
                  <button type="button" disabled={busy || !suggestion.name.trim()} onClick={() => void handleAdd(index)}>
                    加入模板
                  </button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
