import type { ReactNode } from "react";

import type { Memo, ResourceClassificationAssessment } from "./types";
import { currentLocale, t } from "./i18n";
import { useI18n } from "./I18nProvider";

function listedClassificationTags(
  assessment: ResourceClassificationAssessment,
  memo?: Memo,
): { heading: string; tags: string[] } {
  const proposed = (assessment.proposed_categories ?? []).map((item) => item.label);
  if (proposed.length > 0) {
    return { heading: t("大模型列出的标签"), tags: proposed };
  }
  const autoTags = memo?.resource_auto_tags ?? [];
  if (autoTags.length > 0) {
    return { heading: t("自动标签"), tags: autoTags };
  }
  return { heading: t("大模型列出的标签"), tags: [] };
}

type FolderEvidence = NonNullable<ResourceClassificationAssessment["bookmark_folder"]>;

function folderEvidenceText(evidence: FolderEvidence): string {
  const confidence = evidence.confidence === null ? "" : t("（置信度 {value}%）", { value: (evidence.confidence * 100).toFixed(0) });
  const subject = t("{value}「{folder}」", { value: evidence.kind === "tag" ? t("书签标签") : t("书签文件夹"), folder: evidence.folder });
  const mapped = evidence.mapping_source === "manual" ? t("按你的指定对应") : t("对应");
  if (evidence.verdict === "kept") {
    return t("{subject}{mapped}「{category_label}」，Jev 判定网页属于这个分类{confidence}，已沿用。", { subject, mapped, category_label: evidence.category_label, confidence });
  }
  if (evidence.verdict === "rejected") {
    return t("{subject}{mapped}「{category_label}」，但 Jev 判定网页不属于它{confidence}，已按完整流程重新分类。", { subject, mapped, category_label: evidence.category_label, confidence });
  }
  return evidence.mapping_source === "manual"
    ? t("{subject}已设为不沿用，已按完整流程分类。", { subject })
    : t("{subject}没有对应的已有分类，已按完整流程分类。", { subject });
}

const reasonLabels: Record<string, string> = {
  get accepted() { return t("模型判断达到自动分类要求。"); },
  get low_confidence() { return t("模型判断未达到自动分类要求，保留原分类。"); },
  get unknown_category() { return t("模型返回的类别不在当前模板中，保留原分类。"); },
  get invalid_response() { return t("模型返回的分类数据无效，保留原分类。"); },
  get no_ocr_text() { return t("没有识别到图片文字，保留原分类，可手动选择模板。"); },
  get no_match() { return t("所有自定义分类的口径都不匹配，已改用系统兜底分类。"); },
  get folder_conflict() { return t("Jev 判定网页不属于书签原归类对应的分类，完整分类却又选回了它；保留原分类，请人工确认。"); },
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
  const { t } = useI18n();
  const confirmation = memo?.resource_ai_confirmation;
  const assessment = suppliedAssessment ?? memo?.resource_ai_assessment;
  const contentLabel = memo?.type === "image" || assessment?.input_source === "image_ocr" ? t("图片") : t("网页");
  if (confirmation) {
    const action = { adopt: t("采纳候选"), keep: t("保留原分类"), assign: t("指定分类") }[confirmation.action];
    // 列表里只提示需要处理的分类，人工确认过的不再占行。
    if (compact) return null;
    return <section className="classification-insight" aria-label={t("{contentLabel}分类确认", { contentLabel })}>
      <strong>{t("已人工确认 · {action}", { action })}</strong>
      <p>{confirmation.category_label || t("未分类")}</p>
      <p className="classification-insight-meta">{new Date(confirmation.confirmed_at).toLocaleString(currentLocale())}</p>
      {assessment && <details>
        <summary>{t("当时的模型依据")}</summary>
        <ResourceClassificationInsight assessment={assessment} />
      </details>}
    </section>;
  }
  if (!assessment || memo?.resource_category_source === "manual") return null;
  const fallbackUsed = assessment.fallback_used === true;
  const validResult = assessment.reason_code === "accepted" || assessment.reason_code === "low_confidence";
  const confidence =
    assessment.reason_code === "no_match"
      ? t("没有命中你的自定义分类口径")
      : !validResult
      ? t("分类结果无效")
      : assessment.confidence === null
      ? t("未提供有效置信度")
      : t("置信度 {value}%", { value: (assessment.confidence * 100).toFixed(0) });

  const listed = listedClassificationTags(assessment, memo);
  const rankedCandidates = assessment.candidates.filter((item) => item.probability !== null);
  const showCandidates = rankedCandidates.length > 0 || (
    listed.tags.length === 0 && assessment.candidates.length > 0
  );

  if (compact) {
    if (assessment.status === "classified" && validResult) return null;
    return <small className={`classification-insight-brief ${assessment.status}`}>
      {assessment.status === "classified" ? t("模型已归类") : t("模型未确定")}
      {` · ${confidence}`}
      {fallbackUsed && t(" · 系统兜底分类")}
      {assessment.status === "uncertain" && listed.tags.length === 0 && assessment.candidates.length > 0 &&
        t(" · 候选：{value}", { value: assessment.candidates.map((item) => item.label).join(t("、")) })}
    </small>;
  }

  return <section className="classification-insight" aria-label={t("{contentLabel}分类依据", { contentLabel })}>
    <strong>{t("分类依据")}</strong>
    <p>{reasonLabels[assessment.reason_code] || t("本次判断未确定，保留原分类。")}</p>
    {fallbackUsed && <p className="classification-insight-fallback">{t("系统兜底分类 · 这条没有命中你自己的细类")}</p>}
    {assessment.bookmark_folder && <>
      <strong>{assessment.bookmark_folder.verdict === "kept" ? t("沿用书签原归类") : t("书签原归类复核")}</strong>
      <p className="classification-insight-folder">{folderEvidenceText(assessment.bookmark_folder)}</p>
    </>}
    <p>{confidence}{t(" · 自动分类要求 {value}%", { value: (assessment.threshold * 100).toFixed(0) })}</p>
    {listed.tags.length > 0 && <>
      <strong>{listed.heading}</strong>
      <ul className="classification-insight-tags" aria-label={listed.heading}>
        {listed.tags.map((tag) => <li key={tag}>{tag}</li>)}
      </ul>
    </>}
    {assessment.reason && <>
      <strong>{t("模型判定依据")}</strong>
      <p className="classification-insight-reason">{assessment.reason}</p>
    </>}
    {showCandidates && <ul aria-label={t("模型候选类别")}>
      {(rankedCandidates.length > 0 ? rankedCandidates : assessment.candidates).map((candidate) => <li key={candidate.code}>
        {candidate.label}
        {candidate.probability !== null && t(" · 候选概率 {value}%", { value: (candidate.probability * 100).toFixed(1) })}
      </li>)}
    </ul>}
    <p className="classification-insight-meta">
      {assessment.model}{` · ${new Date(assessment.attempted_at).toLocaleString(currentLocale())}`}
      {assessment.input_source === "image_ocr" ? t(" · 使用了本地图片识别文字") : assessment.input_source === "public_excerpt" ? t(" · 使用了公开正文摘要") : t(" · 使用标题、网页描述与站点信息")}
    </p>
    {assessment.input_source !== "metadata" && assessment.input_excerpt &&
      <details>
        <summary>{assessment.input_source === "image_ocr" ? t("使用的图片识别文字") : t("使用的公开正文摘要")}</summary>
        <p className="classification-insight-excerpt">{assessment.input_excerpt}</p>
      </details>}
  </section>;
}
