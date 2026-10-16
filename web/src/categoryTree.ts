import type { ResourceCategoryOption } from "./types";

export const MAX_CATEGORY_DEPTH = 3;

export type CategoryTreeNode = ResourceCategoryOption & {
  children: CategoryTreeNode[];
};

export function categoryDepth(category: ResourceCategoryOption): number {
  return category.depth ?? 1;
}

export function buildCategoryTree(
  categories: ResourceCategoryOption[],
): CategoryTreeNode[] {
  const nodes = new Map<string, CategoryTreeNode>();
  for (const category of categories) {
    nodes.set(category.code, { ...category, children: [] });
  }
  const roots: CategoryTreeNode[] = [];
  for (const category of categories) {
    const node = nodes.get(category.code);
    if (!node) {
      continue;
    }
    const parent = category.parent_code
      ? nodes.get(category.parent_code)
      : undefined;
    if (parent) {
      parent.children.push(node);
    } else {
      roots.push(node);
    }
  }
  return roots;
}

// 口径和例子是模型判定的主要依据，只要填了任意一项就认为口径已填。
export function categoryHasScope(category: ResourceCategoryOption): boolean {
  return Boolean(
    (category.definition ?? "").trim() ||
      (category.include_examples ?? "").trim() ||
      (category.exclude_examples ?? "").trim(),
  );
}
