import type { Memo, ResourceCategoryOption } from "./types";

/** 资料分类：多分类兼容旧单分类字段，筛选时包含子分类。 */

export const MAX_MEMO_CATEGORIES = 8;

export const defaultResourceCategories: ResourceCategoryOption[] = [
  ["learning", "学习资料"],
  ["article", "文章阅读"],
  ["media", "视频与音频"],
  ["tool", "工具与服务"],
  ["book_paper", "书籍与论文"],
  ["product", "商品与好物"],
  ["other", "其他"],
].map(([code, name]) => ({
  id: null,
  code,
  name,
  description: null,
  is_system: true,
  is_active: true,
  version: 1,
  parent_code: null,
  depth: 1,
  path: name,
}));

export function memoCategoryCodes(memo: Memo): string[] {
  if (memo.resource_categories && memo.resource_categories.length > 0) {
    return memo.resource_categories;
  }
  return memo.resource_category ? [memo.resource_category] : [];
}

export function descendantCategoryCodes(
  code: string,
  categories: ResourceCategoryOption[],
): string[] {
  const children = categories.filter((category) => category.parent_code === code);
  return [
    code,
    ...children.flatMap((child) => descendantCategoryCodes(child.code, categories)),
  ];
}

export function memoMatchesCategoryFilter(
  memo: Memo,
  filter: string,
  categories: ResourceCategoryOption[],
): boolean {
  if (!filter) {
    return true;
  }
  const allowed = new Set(descendantCategoryCodes(filter, categories));
  return memoCategoryCodes(memo).some((code) => allowed.has(code));
}

export function memoCategoryLabels(
  memo: Memo,
  categories: ResourceCategoryOption[],
): string[] {
  return memoCategoryCodes(memo).map((code) => {
    const option = categories.find((category) => category.code === code);
    return option?.path || option?.name || memo.resource_category_label || code;
  });
}
