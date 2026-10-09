import type { ReactNode } from "react";

import type { Memo, ResourceClassificationAssessment } from "./types";

const reasonLabels: Record<string, string> = {
  accepted: "模型判断达到自动分类要求。",
  low_confidence: "模型判断未达到自动分类要求，保留原分类。",
  unknown_category: "模型返回的类别不在当前模板中，保留原分类。",
  invalid_response: "模型返回的分类数据无效，保留原分类。",
  no_ocr_text: "没有识别到图片文字，保留原分类，可手动选择模板。",
};

export default function ResourceClassificationInsight({
  memo,
  assessment: suppliedAssessment,
  compact = false,
}: {
  memo?: Memo;
  assessment?: ResourceClassificationAssessment | null;
  compact?: boolean;
}): ReactNode {
  const confirmation = memo?.resource_ai_confirmation;
  const assessment = suppliedAssessment ?? memo?.resource_ai_assessment;
  const contentLabel = memo?.type === "image" || assessment?.input_source === "image_ocr" ? "图片" : "网页";
  if (confirmation) {
    const action = { adopt: "采纳候选", keep: "保留原分类", assign: "指定分类" }[confirmation.action];
    if (compact) return <small className="classification-insight-brief">已人工确认 · {action}</small>;
    return <section className="classification-insight" aria-label={`${contentLabel}分类确认`}>
      <strong>已人工确认 · {action}</strong>
      <p>{confirmation.category_label || "未分类"}</p>
      <p className="classification-insight-meta">{new Date(confirmation.confirmed_at).toLocaleString("zh-CN")}</p>
      {assessment && <details>
        <summary>当时的模型依据</summary>
        <ResourceClassificationInsight assessment={assessment} />
      </details>}
    </section>;
  }
  if (!assessment || memo?.resource_category_source === "manual") return null;
  const validResult = assessment.reason_code === "accepted" || assessment.reason_code === "low_confidence";
  const confidence = !validResult
    ? "分类结果无效"
    : assessment.confidence === null
    ? "未提供有效置信度"
    : `置信度 ${(assessment.confidence * 100).toFixed(0)}%`;

  if (compact) {
    return <small className={`classification-insight-brief ${assessment.status}`}>
      {assessment.status === "classified" ? "模型已归类" : "模型未确定"}
      {` · ${confidence}`}
      {assessment.status === "uncertain" && assessment.candidates.length > 0 &&
        ` · 候选：${assessment.candidates.map((item) => item.label).join("、")}`}
    </small>;
  }

  return <section className="classification-insight" aria-label={`${contentLabel}分类依据`}>
    <strong>分类依据</strong>
    <p>{reasonLabels[assessment.reason_code] || "本次判断未确定，保留原分类。"}</p>
    <p>{confidence}{` · 自动分类要求 ${(assessment.threshold * 100).toFixed(0)}%`}</p>
    {assessment.candidates.length > 0 && <ul aria-label="模型候选类别">
      {assessment.candidates.map((candidate) => <li key={candidate.code}>
        {candidate.label}
        {candidate.probability !== null && ` · 候选概率 ${(candidate.probability * 100).toFixed(1)}%`}
      </li>)}
    </ul>}
    <p className="classification-insight-meta">
      {assessment.model}{` · ${new Date(assessment.attempted_at).toLocaleString("zh-CN")}`}
      {assessment.input_source === "image_ocr" ? " · 使用了本地图片识别文字" : assessment.input_source === "public_excerpt" ? " · 使用了公开正文摘要" : " · 使用标题、网页描述与站点信息"}
    </p>
    {assessment.input_source !== "metadata" && assessment.input_excerpt &&
      <details>
        <summary>{assessment.input_source === "image_ocr" ? "使用的图片识别文字" : "使用的公开正文摘要"}</summary>
        <p className="classification-insight-excerpt">{assessment.input_excerpt}</p>
      </details>}
  </section>;
}
