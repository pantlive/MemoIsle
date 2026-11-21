import { useState, type FormEvent } from "react";

import {
  createResourceCategory,
  createResourceCategoryRule,
  deleteResourceCategory,
  deleteResourceCategoryRule,
  updateResourceCategory,
  updateResourceCategoryRule,
} from "./api";
import Icon from "./Icon";
import {
  buildCategoryTree,
  categoryDepth,
  categoryHasScope,
  MAX_CATEGORY_DEPTH,
  type CategoryTreeNode,
} from "./categoryTree";
import type {
  ResourceCategoryOption,
  ResourceCategoryRule,
  ResourceCategoryRuleMatchType,
} from "./types";
import { t } from "./i18n";
import { useI18n } from "./I18nProvider";

const ruleMatchLabels: Record<ResourceCategoryRuleMatchType, string> = {
  get domain() { return t("网站域名"); },
  get url() { return t("网址包含"); },
  get text() { return t("标题或描述包含"); },
};

const rulePatternPlaceholders: Record<ResourceCategoryRuleMatchType, string> = {
  get domain() { return t("例如：github.com"); },
  get url() { return t("例如：/research/"); },
  get text() { return t("例如：深度学习"); },
};

const DEFAULT_RULE_PRIORITY = 100;

type CategoryValues = {
  name: string;
  description: string;
  parentCode: string;
  definition: string;
  includeExamples: string;
  excludeExamples: string;
};

type CategoryFormMode =
  | { kind: "create"; parentCode: string; fixedParent: boolean }
  | { kind: "edit"; category: ResourceCategoryOption };

type RuleValues = {
  matchType: ResourceCategoryRuleMatchType;
  pattern: string;
  categoryCode: string;
  priority: string;
  name: string;
};

type RuleFormMode =
  | { kind: "create"; categoryCode: string }
  | { kind: "edit"; rule: ResourceCategoryRule };

type Notice = { tone: "info" | "error"; text: string; ruleCategory?: string };

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : t("操作失败，请稍后重试。");
}

// 后端在未命名时用「匹配方式 · 内容」作名称，这种名称不再重复展示。
function customRuleName(rule: ResourceCategoryRule): string | null {
  return rule.name && rule.name !== `${rule.match_type} · ${rule.pattern}` ? rule.name : null;
}

function CategoryForm({
  mode,
  categories,
  busy,
  onSubmit,
  onCancel,
}: {
  mode: CategoryFormMode;
  categories: ResourceCategoryOption[];
  busy: boolean;
  onSubmit: (values: CategoryValues) => Promise<boolean>;
  onCancel: () => void;
}) {
  const { t } = useI18n();
  const initial = mode.kind === "edit" ? mode.category : null;
  const [values, setValues] = useState<CategoryValues>({
    name: initial?.name ?? "",
    description: initial?.description ?? "",
    parentCode: mode.kind === "create" ? mode.parentCode : initial?.parent_code ?? "",
    definition: initial?.definition ?? "",
    includeExamples: initial?.include_examples ?? "",
    excludeExamples: initial?.exclude_examples ?? "",
  });
  const set = (field: keyof CategoryValues) => (value: string) =>
    setValues((current) => ({ ...current, [field]: value }));
  const parent = categories.find((category) => category.code === values.parentCode);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!values.name.trim()) return;
    await onSubmit(values);
  };

  return (
    <form className="template-form" onSubmit={(event) => void handleSubmit(event)}>
      <div className="template-form-row">
        <label>
          {t("名称")}
          <input
            autoFocus
            value={values.name}
            onChange={(event) => set("name")(event.target.value)}
            placeholder={t("例如：待研究项目")}
            maxLength={50}
            required
          />
        </label>
        {mode.kind === "create" && !mode.fixedParent ? (
          <label>
            {t("放在")}
            <select value={values.parentCode} onChange={(event) => set("parentCode")(event.target.value)}>
              <option value="">{t("顶级分类")}</option>
              {categories
                .filter((category) => categoryDepth(category) < MAX_CATEGORY_DEPTH)
                .map((category) => (
                  <option key={category.code} value={category.code}>
                    {category.path || category.name}
                  </option>
                ))}
            </select>
          </label>
        ) : (
          <label>
            {t("放在")}
            <input value={parent ? parent.path || parent.name : t("顶级分类")} disabled />
          </label>
        )}
      </div>
      <label>
        {t("说明")}
        <input
          value={values.description}
          onChange={(event) => set("description")(event.target.value)}
          placeholder={t("一句话说明这个分类放什么（可选）")}
          maxLength={300}
        />
      </label>
      <details className="template-scope" open={Boolean(initial && categoryHasScope(initial))}>
        <summary>{t("判定口径与例子（可选，写得越具体，模型分得越准）")}</summary>
        <label>
          {t("判定口径")}
          <textarea
            value={values.definition}
            onChange={(event) => set("definition")(event.target.value)}
            placeholder={t("什么算这一类。例：卖订阅额度的编程 agent 套餐，如 Claude Code、Codex")}
            maxLength={600}
            rows={3}
          />
        </label>
        <label>
          {t("属于这一类的例子")}
          <textarea
            value={values.includeExamples}
            onChange={(event) => set("includeExamples")(event.target.value)}
            placeholder={t("一行一条")}
            maxLength={800}
            rows={2}
          />
        </label>
        <label>
          {t("不属于这一类的反例")}
          <textarea
            value={values.excludeExamples}
            onChange={(event) => set("excludeExamples")(event.target.value)}
            placeholder={t("一行一条。例：模型 API 平台不算，归大模型服务")}
            maxLength={800}
            rows={2}
          />
        </label>
        {mode.kind === "edit" && <small>{t("清空后保存会删除已有口径。")}</small>}
      </details>
      <div className="template-form-actions">
        <button type="button" onClick={onCancel} disabled={busy}>{t("取消")}</button>
        <button type="submit" className="primary" disabled={busy || !values.name.trim()}>
          {busy ? t("保存中…") : mode.kind === "edit" ? t("保存修改") : t("添加分类")}
        </button>
      </div>
    </form>
  );
}

function RuleForm({
  mode,
  categories,
  busy,
  onSubmit,
  onCancel,
}: {
  mode: RuleFormMode;
  categories: ResourceCategoryOption[];
  busy: boolean;
  onSubmit: (values: RuleValues) => Promise<boolean>;
  onCancel: () => void;
}) {
  const { t } = useI18n();
  const rule = mode.kind === "edit" ? mode.rule : null;
  const [values, setValues] = useState<RuleValues>({
    matchType: rule?.match_type ?? "domain",
    pattern: rule?.pattern ?? "",
    categoryCode: rule?.category_code ?? (mode.kind === "create" ? mode.categoryCode : ""),
    priority: String(rule?.priority ?? DEFAULT_RULE_PRIORITY),
    name: rule ? customRuleName(rule) ?? "" : "",
  });
  const set = <K extends keyof RuleValues>(field: K) => (value: RuleValues[K]) =>
    setValues((current) => ({ ...current, [field]: value }));
  const priority = Number.parseInt(values.priority, 10);
  const valid = Boolean(values.pattern.trim() && values.categoryCode)
    && Number.isInteger(priority) && priority >= 0 && priority <= 10_000;

  return (
    <form
      className="template-form"
      onSubmit={(event) => {
        event.preventDefault();
        if (valid) void onSubmit(values);
      }}
    >
      <div className="template-form-row">
        <label>
          {t("匹配方式")}
          <select
            value={values.matchType}
            onChange={(event) => set("matchType")(event.target.value as ResourceCategoryRuleMatchType)}
          >
            {Object.entries(ruleMatchLabels).map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
        </label>
        <label>
          {t("匹配内容")}
          <input
            autoFocus
            value={values.pattern}
            onChange={(event) => set("pattern")(event.target.value)}
            placeholder={rulePatternPlaceholders[values.matchType]}
            maxLength={500}
            required
          />
        </label>
      </div>
      <div className="template-form-row">
        <label>
          {t("归入分类")}
          <select value={values.categoryCode} onChange={(event) => set("categoryCode")(event.target.value)} required>
            <option value="">{t("选择分类")}</option>
            {categories
              .filter((category) => category.is_active)
              .map((category) => (
                <option key={category.code} value={category.code}>
                  {category.path || category.name}
                </option>
              ))}
          </select>
        </label>
        <label>
          {t("优先级")}
          <input
            type="number"
            min="0"
            max="10000"
            value={values.priority}
            onChange={(event) => set("priority")(event.target.value)}
          />
          <small>{t("数字越小越先匹配，默认 {DEFAULT_RULE_PRIORITY}。", { DEFAULT_RULE_PRIORITY })}</small>
        </label>
      </div>
      <label>
        {t("规则名称")}
        <input
          value={values.name}
          onChange={(event) => set("name")(event.target.value)}
          placeholder={t("可选，方便自己辨认")}
          maxLength={100}
        />
      </label>
      <div className="template-form-actions">
        <button type="button" onClick={onCancel} disabled={busy}>{t("取消")}</button>
        <button type="submit" className="primary" disabled={busy || !valid}>
          {busy ? t("保存中…") : mode.kind === "edit" ? t("保存修改") : t("添加规则")}
        </button>
      </div>
    </form>
  );
}

export default function CategoryTemplatePanel({
  categories,
  rules,
  loading,
  onRefresh,
}: {
  categories: ResourceCategoryOption[];
  rules: ResourceCategoryRule[];
  loading: boolean;
  onRefresh: () => Promise<void>;
}) {
  const { t } = useI18n();
  const [tab, setTab] = useState<"categories" | "rules">("categories");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [categoryForm, setCategoryForm] = useState<CategoryFormMode | null>(null);
  // 子分类表单挂在父分类下面，记录它挂在哪一行。
  const [categoryFormAnchor, setCategoryFormAnchor] = useState<string | null>(null);
  const [ruleForm, setRuleForm] = useState<RuleFormMode | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);

  const tree = buildCategoryTree(categories);
  const sortedRules = [...rules].sort((a, b) => a.priority - b.priority);
  const parentCodes = categories.filter((category) =>
    categories.some((child) => child.parent_code === category.code),
  ).map((category) => category.code);
  const allExpanded = parentCodes.length > 0 && parentCodes.every((code) => expanded.has(code));

  const run = async (action: () => Promise<Notice | null>): Promise<boolean> => {
    if (busy) return false;
    setBusy(true);
    setNotice(null);
    try {
      const result = await action();
      await onRefresh();
      setNotice(result);
      return true;
    } catch (error) {
      setNotice({ tone: "error", text: errorText(error) });
      return false;
    } finally {
      setBusy(false);
    }
  };

  const expandTo = (code: string | null | undefined) => {
    setExpanded((current) => {
      const next = new Set(current);
      let cursor = code;
      while (cursor) {
        next.add(cursor);
        cursor = categories.find((category) => category.code === cursor)?.parent_code;
      }
      return next;
    });
  };

  const toggle = (code: string) => {
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  };

  const openCategoryForm = (mode: CategoryFormMode, anchor: string | null) => {
    setRuleForm(null);
    setCategoryForm(mode);
    setCategoryFormAnchor(anchor);
    if (anchor) expandTo(anchor);
  };

  const closeCategoryForm = () => {
    setCategoryForm(null);
    setCategoryFormAnchor(null);
  };

  const submitCategory = async (values: CategoryValues): Promise<boolean> => {
    const mode = categoryForm;
    if (!mode) return false;
    const scope = {
      definition: values.definition.trim() || null,
      include_examples: values.includeExamples.trim() || null,
      exclude_examples: values.excludeExamples.trim() || null,
    };
    const ok = await run(async () => {
      if (mode.kind === "edit") {
        const updated = await updateResourceCategory(mode.category.id!, {
          expected_version: mode.category.version,
          name: values.name.trim(),
          description: values.description.trim() || null,
          ...scope,
        });
        return { tone: "info", text: t("已更新“{name}”。", { name: updated.name }) };
      }
      const created = await createResourceCategory({
        name: values.name.trim(),
        description: values.description.trim() || undefined,
        parent_code: values.parentCode || undefined,
        ...scope,
      });
      expandTo(created.parent_code);
      return { tone: "info", text: t("已创建“{value}”。", { value: created.path || created.name }), ruleCategory: created.code };
    });
    if (ok) closeCategoryForm();
    return ok;
  };

  const toggleCategory = (category: ResourceCategoryOption) =>
    void run(async () => {
      const updated = await updateResourceCategory(category.id!, {
        expected_version: category.version,
        is_active: !category.is_active,
      });
      return {
        tone: "info",
        text: updated.is_active ? t("已启用“{name}”。", { name: updated.name }) : t("已停用“{name}”，已有资料会重新判断。", { name: updated.name }),
      };
    });

  const deleteCategory = (category: ResourceCategoryOption) => {
    const confirmed = window.confirm(
      t("删除分类“{value}”？子分类和相关规则会一并删除，已用这些分类的网页会重新判断。", { value: category.path || category.name }),
    );
    if (!confirmed) return;
    if (categoryForm?.kind === "edit" && categoryForm.category.code === category.code) closeCategoryForm();
    void run(async () => {
      await deleteResourceCategory(category.id!);
      return { tone: "info", text: t("已删除“{name}”。", { name: category.name }) };
    });
  };

  const submitRule = async (values: RuleValues): Promise<boolean> => {
    const mode = ruleForm;
    if (!mode) return false;
    const payload = {
      name: values.name.trim() || undefined,
      category_code: values.categoryCode,
      match_type: values.matchType,
      pattern: values.pattern.trim(),
      priority: Number.parseInt(values.priority, 10),
    };
    const ok = await run(async () => {
      if (mode.kind === "edit") {
        await updateResourceCategoryRule(mode.rule.id, {
          expected_version: mode.rule.version,
          ...payload,
          // 清空名称时回到后端的默认命名。
          name: payload.name ?? `${payload.match_type} · ${payload.pattern}`,
        });
        return { tone: "info", text: t("规则已更新，相关资料会按新规则重新整理。") };
      }
      await createResourceCategoryRule(payload);
      return { tone: "info", text: t("规则已保存，已有网页资料正在按新规则整理。") };
    });
    if (ok) setRuleForm(null);
    return ok;
  };

  const toggleRule = (rule: ResourceCategoryRule) =>
    void run(async () => {
      const updated = await updateResourceCategoryRule(rule.id, {
        expected_version: rule.version,
        enabled: !rule.enabled,
      });
      return { tone: "info", text: updated.enabled ? t("规则已启用。") : t("规则已停用，相关资料会重新判断。") };
    });

  const deleteRule = (rule: ResourceCategoryRule) => {
    if (!window.confirm(t("删除规则「{value}：{pattern}」？", { value: ruleMatchLabels[rule.match_type], pattern: rule.pattern }))) return;
    if (ruleForm?.kind === "edit" && ruleForm.rule.id === rule.id) setRuleForm(null);
    void run(async () => {
      await deleteResourceCategoryRule(rule.id);
      return { tone: "info", text: t("规则已删除，相关资料会重新判断。") };
    });
  };

  const startRuleFor = (categoryCode: string) => {
    closeCategoryForm();
    setTab("rules");
    setRuleForm({ kind: "create", categoryCode });
    setNotice(null);
  };

  const renderCategoryForm = () =>
    categoryForm && (
      <CategoryForm
        key={categoryForm.kind === "edit" ? categoryForm.category.code : `new-${categoryFormAnchor ?? "root"}`}
        mode={categoryForm}
        categories={categories}
        busy={busy}
        onSubmit={submitCategory}
        onCancel={closeCategoryForm}
      />
    );

  const renderNodes = (nodes: CategoryTreeNode[]) => (
    <ul className="template-tree">
      {nodes.map((node) => {
        const hasChildren = node.children.length > 0;
        const editing = categoryForm?.kind === "edit" && categoryForm.category.code === node.code;
        const addingChild = categoryForm?.kind === "create" && categoryFormAnchor === node.code;
        const open = expanded.has(node.code) || addingChild;
        const copy = (
          <>
            <span className="template-node-title">
              <strong>{node.name}</strong>
              {node.is_system && <span className="template-badge">{t("系统")}</span>}
              {!node.is_active && <span className="template-badge muted">{t("已停用")}</span>}
              {!node.is_system && !categoryHasScope(node) && (
                <span className="category-scope-badge pending">{t("待补口径")}</span>
              )}
            </span>
            {(node.description || hasChildren) && (
              <small>
                {[node.description, hasChildren ? t("{length} 个子分类", { length: node.children.length }) : ""]
                  .filter(Boolean)
                  .join(" · ")}
              </small>
            )}
          </>
        );
        return (
          <li key={node.code}>
            {editing ? (
              <div className="template-node-editing">{renderCategoryForm()}</div>
            ) : (
              <div className={node.is_active ? "template-node" : "template-node inactive"}>
                {hasChildren ? (
                  <button
                    type="button"
                    className="template-node-copy"
                    aria-expanded={open}
                    onClick={() => toggle(node.code)}
                  >
                    <span className="template-node-arrow" aria-hidden="true"><Icon name={open ? "chevronDown" : "chevronRight"} size={14} /></span>
                    <span className="template-node-text">{copy}</span>
                  </button>
                ) : (
                  <div className="template-node-copy">
                    <span className="template-node-arrow" aria-hidden="true" />
                    <span className="template-node-text">{copy}</span>
                  </div>
                )}
                <span className="template-node-actions">
                  {categoryDepth(node) < MAX_CATEGORY_DEPTH && (
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => openCategoryForm({ kind: "create", parentCode: node.code, fixedParent: true }, node.code)}
                    >
                      {t("＋子分类")}
                    </button>
                  )}
                  {node.is_active && (
                    <button type="button" disabled={busy} onClick={() => startRuleFor(node.code)}>{t("＋规则")}</button>
                  )}
                  {!node.is_system && (
                    <>
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => openCategoryForm({ kind: "edit", category: node }, node.parent_code ?? null)}
                      >
                        {t("编辑")}
                      </button>
                      <button type="button" disabled={busy} onClick={() => toggleCategory(node)}>
                        {node.is_active ? t("停用") : t("启用")}
                      </button>
                      <button type="button" className="danger" disabled={busy} onClick={() => deleteCategory(node)}>
                        {t("删除")}
                      </button>
                    </>
                  )}
                </span>
              </div>
            )}
            {open && (hasChildren || addingChild) && (
              <div className="template-children">
                {addingChild && <div className="template-node-editing">{renderCategoryForm()}</div>}
                {hasChildren && renderNodes(node.children)}
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );

  return (
    <>
      <div className="template-header">
        <div>
          <strong>{t("分类模板")}</strong>
          <span>{t("网页资料按这些分类整理。大类下可以再分小类，最多三层；规则命中的网页直接归类，不经过模型。")}</span>
        </div>
        {loading && <small>{t("正在读取……")}</small>}
      </div>
      <div className="template-tabs" role="tablist" aria-label={t("分类模板")}>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "categories"}
          onClick={() => setTab("categories")}
        >
          {t("分类 ")}<span>{categories.length}</span>
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "rules"}
          onClick={() => setTab("rules")}
        >
          {t("自动规则 ")}<span>{rules.length}</span>
        </button>
      </div>

      {notice && (
        <p className={`template-notice ${notice.tone}`} role={notice.tone === "error" ? "alert" : "status"}>
          {notice.text}
          {notice.ruleCategory && (
            <button type="button" onClick={() => startRuleFor(notice.ruleCategory!)}>{t("为它添加规则")}</button>
          )}
        </p>
      )}

      {tab === "categories" ? (
        <div className="template-section" role="tabpanel">
          <div className="template-toolbar">
            <button
              type="button"
              className="primary"
              disabled={busy}
              onClick={() => openCategoryForm({ kind: "create", parentCode: "", fixedParent: false }, null)}
            >
              {t("＋ 新建分类")}
            </button>
            {parentCodes.length > 0 && (
              <button
                type="button"
                onClick={() => setExpanded(allExpanded ? new Set() : new Set(parentCodes))}
              >
                {allExpanded ? t("全部收起") : t("全部展开")}
              </button>
            )}
          </div>
          {categoryForm?.kind === "create" && categoryFormAnchor === null && (
            <div className="template-node-editing">{renderCategoryForm()}</div>
          )}
          {renderNodes(tree)}
        </div>
      ) : (
        <div className="template-section" role="tabpanel">
          <div className="template-toolbar">
            <button
              type="button"
              className="primary"
              disabled={busy}
              onClick={() => setRuleForm({ kind: "create", categoryCode: "" })}
            >
              {t("＋ 新建规则")}
            </button>
            <small>{t("按优先级从小到大匹配，先命中的规则生效。")}</small>
          </div>
          {ruleForm?.kind === "create" && (
            <div className="template-node-editing">
              <RuleForm
                key={`new-${ruleForm.categoryCode}`}
                mode={ruleForm}
                categories={categories}
                busy={busy}
                onSubmit={submitRule}
                onCancel={() => setRuleForm(null)}
              />
            </div>
          )}
          {sortedRules.length === 0 && !ruleForm && (
            <p className="template-empty">{t("还没有规则。常用网站最适合先加域名规则，例如把 github.com 归到「工具与服务」。")}</p>
          )}
          <ul className="template-rule-list">
            {sortedRules.map((rule) => {
              const name = customRuleName(rule);
              return (
                <li key={rule.id}>
                  {ruleForm?.kind === "edit" && ruleForm.rule.id === rule.id ? (
                    <div className="template-node-editing">
                      <RuleForm
                        key={rule.id}
                        mode={ruleForm}
                        categories={categories}
                        busy={busy}
                        onSubmit={submitRule}
                        onCancel={() => setRuleForm(null)}
                      />
                    </div>
                  ) : (
                    <div className={rule.enabled ? "template-node" : "template-node inactive"}>
                      <div className="template-node-copy">
                        <span className="template-node-text">
                          <span className="template-node-title">
                            <strong>
                              {t("{value}「{pattern}」→ {category_label}", { value: ruleMatchLabels[rule.match_type], pattern: rule.pattern, category_label: rule.category_label })}
                            </strong>
                            {!rule.enabled && <span className="template-badge muted">{t("已停用")}</span>}
                          </span>
                          <small>
                            {[name, t("优先级 {priority}", { priority: rule.priority })].filter(Boolean).join(" · ")}
                          </small>
                        </span>
                      </div>
                      <span className="template-node-actions">
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => {
                            closeCategoryForm();
                            setRuleForm({ kind: "edit", rule });
                          }}
                        >
                          {t("编辑")}
                        </button>
                        <button type="button" disabled={busy} onClick={() => toggleRule(rule)}>
                          {rule.enabled ? t("停用") : t("启用")}
                        </button>
                        <button type="button" className="danger" disabled={busy} onClick={() => deleteRule(rule)}>
                          {t("删除")}
                        </button>
                      </span>
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </>
  );
}
