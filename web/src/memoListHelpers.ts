import { ApiError } from "./api";
import type { Memo, MemoSort } from "./types";

export const TRASH_RETENTION_DAYS = 30;

/** 「最常打开」只对网页资料有意义；「最相关」只在搜索时有意义（服务端无搜索词时按最近更新）。 */
export function effectiveSort(sort: MemoSort, resourceView: boolean): MemoSort {
  return sort === "opened_desc" && !resourceView ? "updated_desc" : sort;
}

export function trashDaysRemaining(memo: Memo): number {
  const start = Date.parse(memo.deleted_at ?? memo.updated_at);
  if (Number.isNaN(start)) {
    return 0;
  }
  const remainingMs =
    TRASH_RETENTION_DAYS * 24 * 60 * 60 * 1000 - (Date.now() - start);
  return Math.max(0, Math.ceil(remainingMs / (24 * 60 * 60 * 1000)));
}

export function describeError(error: unknown): string {
  if (error instanceof ApiError && error.status === 409) {
    return "内容已在其他设备更新，请处理编辑冲突后再保存。";
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "操作失败，请稍后重试。";
}
