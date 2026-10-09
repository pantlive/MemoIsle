import type { LinkHealthCenter } from "./types";

export function pendingHealthIssueCount(counts: LinkHealthCenter["counts"]): number {
  // 统计全部待确认数量，避免把接口一次展示的 200 条误当成总数。
  return counts.failed + counts.redirected + counts.changed
    + counts.auth_required + counts.temporary_failure + (counts.review_pending ?? 0);
}
