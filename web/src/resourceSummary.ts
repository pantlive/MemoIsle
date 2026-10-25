import type { Memo } from "./types";

// 网页简介：优先用大模型写的用途简介，其次是网页自带描述，最后是备注；备注只是网址时不算。
export function resourceSummary(memo: Memo): string {
  const summary = memo.resource_ai_summary?.trim();
  if (summary) return summary;
  const description = memo.resource_description?.trim();
  if (description) return description;
  const body = memo.body.trim();
  return body && body !== memo.source_url ? body : "";
}
