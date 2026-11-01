// @vitest-environment happy-dom
import { describe, expect, it } from "vitest";
import { ApiError } from "../api";
import { buildCategoryTree, categoryHasScope } from "../categoryTree";
import {
  formatImageBytes,
  imageFileExtension,
  imageInfoLabel,
  imageMimeFromFile,
} from "../imageFiles";
import {
  defaultResourceCategories,
  memoCategoryCodes,
  memoCategoryLabels,
  memoMatchesCategoryFilter,
} from "../memoCategories";
import { describeError, effectiveSort, trashDaysRemaining } from "../memoListHelpers";
import { pendingHealthIssueCount } from "../linkHealth";
import type { Memo, ResourceCategoryOption } from "../types";

function memo(fields: Partial<Memo>): Memo {
  return {
    id: "m",
    type: "resource",
    title: "t",
    body: "",
    updated_at: "2026-10-01T00:00:00Z",
    resource_categories: [],
    resource_category: null,
    resource_category_label: null,
    ...fields,
  } as Memo;
}

function category(code: string, parent: string | null, name = code): ResourceCategoryOption {
  return {
    id: null,
    code,
    name,
    description: null,
    is_system: false,
    is_active: true,
    version: 1,
    parent_code: parent,
    depth: parent ? 2 : 1,
    path: parent ? `${parent}/${name}` : name,
  } as ResourceCategoryOption;
}

describe("memo categories", () => {
  const categories = [category("tech", null), category("ai", "tech"), category("food", null)];

  it("falls back to the legacy single category", () => {
    expect(memoCategoryCodes(memo({ resource_category: "food" }))).toEqual(["food"]);
    expect(memoCategoryCodes(memo({ resource_categories: ["ai", "food"] }))).toEqual([
      "ai",
      "food",
    ]);
  });

  it("matches a parent filter through its children", () => {
    const ai = memo({ resource_categories: ["ai"] });
    expect(memoMatchesCategoryFilter(ai, "tech", categories)).toBe(true);
    expect(memoMatchesCategoryFilter(ai, "food", categories)).toBe(false);
    expect(memoMatchesCategoryFilter(ai, "", categories)).toBe(true);
  });

  it("labels categories by path and falls back to the stored label", () => {
    expect(memoCategoryLabels(memo({ resource_categories: ["ai"] }), categories)).toEqual([
      "tech/ai",
    ]);
    expect(
      memoCategoryLabels(
        memo({ resource_categories: ["gone"], resource_category_label: "旧分类" }),
        categories,
      ),
    ).toEqual(["旧分类"]);
  });

  it("ships the seven system categories", () => {
    expect(defaultResourceCategories.map((item) => item.code)).toContain("other");
    expect(defaultResourceCategories).toHaveLength(7);
  });

  it("builds a tree and detects scope", () => {
    const tree = buildCategoryTree(categories);
    expect(tree.map((node) => node.code)).toEqual(["tech", "food"]);
    expect(tree[0].children.map((node) => node.code)).toEqual(["ai"]);
    expect(categoryHasScope({ ...categories[0], definition: "  " })).toBe(false);
    expect(categoryHasScope({ ...categories[0], include_examples: "GPT" })).toBe(true);
  });
});

describe("list helpers", () => {
  it("only allows opened_desc on the resource view", () => {
    expect(effectiveSort("opened_desc", false)).toBe("updated_desc");
    expect(effectiveSort("opened_desc", true)).toBe("opened_desc");
    expect(effectiveSort("relevance", false)).toBe("relevance");
  });

  it("counts remaining trash days", () => {
    const now = Date.now();
    const deleted = new Date(now - 10 * 24 * 60 * 60 * 1000).toISOString();
    expect(trashDaysRemaining(memo({ deleted_at: deleted }))).toBe(20);
    expect(trashDaysRemaining(memo({ deleted_at: "not a date" }))).toBe(0);
  });

  it("explains version conflicts in plain words", () => {
    expect(describeError(new ApiError("conflict", 409))).toContain("其他设备");
    expect(describeError(new Error("boom"))).toBe("boom");
    expect(describeError("weird")).toBe("操作失败，请稍后重试。");
  });

  it("sums every pending link health issue", () => {
    expect(
      pendingHealthIssueCount({
        failed: 1,
        redirected: 2,
        changed: 3,
        auth_required: 4,
        temporary_failure: 5,
        review_pending: 6,
      } as Parameters<typeof pendingHealthIssueCount>[0]),
    ).toBe(21);
  });
});

describe("image files", () => {
  it("formats sizes", () => {
    expect(formatImageBytes(null)).toBe("");
    expect(formatImageBytes(512)).toBe("512 B");
    expect(formatImageBytes(2048)).toBe("2 KB");
    expect(formatImageBytes(3 * 1024 * 1024)).toBe("3.0 MB");
  });

  it("infers mime types from extensions when the browser gives none", () => {
    expect(imageMimeFromFile(new File([], "a.JPEG"))).toBe("image/jpeg");
    expect(imageMimeFromFile(new File([], "a.txt"))).toBe("");
    expect(imageMimeFromFile(new File([], "x", { type: "image/avif" }))).toBe("image/avif");
    expect(imageFileExtension("image/webp")).toBe("webp");
    expect(imageFileExtension(null)).toBe("image");
  });

  it("summarises image info", () => {
    expect(imageInfoLabel(memo({ image_mime_type: null }))).toBe("尚未上传图片文件");
    expect(
      imageInfoLabel(
        memo({
          image_mime_type: "image/png",
          image_width: 10,
          image_height: 20,
          image_size_bytes: 2048,
        }),
      ),
    ).toBe("10 × 20 · 2 KB · PNG");
  });
});
