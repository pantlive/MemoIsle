import { type FormEvent, type ReactNode, useState } from "react";

import { ApiError, createResourceCategory, generateResourceCategories } from "./api";
import type { ResourceCategorySuggestion, ResourceCategoryOption } from "./types";

interface CategoryGeneratorProps {
  categories: ResourceCategoryOption[];
  onAdded: () => Promise<void>;
}

export default function CategoryGenerator({
  categories,
  onAdded,
}: CategoryGeneratorProps): ReactNode {
  const [instructions, setInstructions] = useState("");
  const [suggestions, setSuggestions] = useState<ResourceCategorySuggestion[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  const handleGenerate = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    if (busy || !instructions.trim()) return;
    setBusy(true);
    setMessage("");
    setSuggestions([]);
    try {
      const result = await generateResourceCategories(instructions.trim());
      setSuggestions(result.categories);
      setMessage(
        result.categories.length
          ? "可修改建议后加入分类模板。"
          : "本次没有生成新的分类建议，可以调整整理要求后重试。",
      );
    } catch (error) {
      setMessage(error instanceof ApiError ? error.message : "分类建议生成失败，请稍后重试。");
    } finally {
      setBusy(false);
    }
  };

  const handleAdd = async (index: number): Promise<void> => {
    if (busy) return;
    const suggestion = suggestions[index];
    if (!suggestion?.name.trim()) return;
    setBusy(true);
    try {
      const created = await createResourceCategory({
        name: suggestion.name.trim(),
        description: suggestion.description?.trim() || undefined,
        parent_code: suggestion.parent_code || undefined,
      });
      // 加入模板后移除对应建议，防止再次提交生成重复类别。
      setSuggestions((current) => current.filter((_item, position) => position !== index));
      setMessage(`已添加「${created.name}」。`);
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
      <form className="category-create-form" onSubmit={(event) => void handleGenerate(event)}>
        <textarea
          value={instructions}
          onChange={(event) => setInstructions(event.target.value)}
          placeholder="例如：我主要收藏 AI 工具、PyTorch 教程和视觉论文，请细化现有分类。"
          aria-label="分类整理要求"
          maxLength={2000}
          rows={3}
          disabled={busy}
        />
        <button type="submit" disabled={busy || !instructions.trim()}>
          {busy ? "正在处理……" : "生成分类建议"}
        </button>
      </form>
      {message && <p className="category-generator-message" role="status">{message}</p>}
      <div className="custom-category-list">
        {suggestions.map((suggestion, index) => (
          <div key={index} className="custom-category-row custom-category-edit category-create-form">
            <input
              value={suggestion.name}
              onChange={(event) => updateSuggestion(index, { name: event.target.value })}
              aria-label={`建议 ${index + 1} 的分类名称`}
              maxLength={50}
              disabled={busy}
            />
            <input
              value={suggestion.description || ""}
              onChange={(event) => updateSuggestion(index, { description: event.target.value })}
              aria-label={`建议 ${index + 1} 的分类说明`}
              maxLength={300}
              disabled={busy}
            />
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
            <button type="button" disabled={busy || !suggestion.name.trim()} onClick={() => void handleAdd(index)}>
              加入模板
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
