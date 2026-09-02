import { useEffect, useRef, useState } from "react";

import WordPronunciation from "./WordPronunciation";
import type { Memo, MemoType, ReviewFeedback, ReviewQueueResponse } from "./types";

export type ReviewQueueFilter = "all" | MemoType;

interface ReviewPanelProps {
  queue: ReviewQueueResponse | null;
  filter: ReviewQueueFilter;
  loading: boolean;
  busy: boolean;
  onFilterChange: (filter: ReviewQueueFilter) => void;
  onSkip: (memo: Memo) => void;
  onReviewWord: (memo: Memo, feedback: ReviewFeedback) => void;
  onOpenResource: (memo: Memo) => void;
  onStarResource: (memo: Memo) => void;
  onOrganizeIdea: (memo: Memo, title: string, body: string) => void;
  onArchiveIdea: (memo: Memo) => void;
}

const queueFilters: { value: ReviewQueueFilter; label: string }[] = [
  { value: "all", label: "混合队列" },
  { value: "word", label: "单词复习" },
  { value: "resource", label: "待阅读" },
  { value: "idea", label: "待整理" },
];

const reviewTimeFormatter = new Intl.DateTimeFormat("zh-CN", {
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

function formatReviewTime(value: string | null, empty: string): string {
  if (!value) {
    return empty;
  }
  return reviewTimeFormatter.format(new Date(value));
}

function sourceHost(sourceUrl: string | null): string {
  if (!sourceUrl) {
    return "网页资料";
  }
  try {
    return new URL(sourceUrl).hostname.replace(/^www\./, "");
  } catch {
    return sourceUrl;
  }
}

export default function ReviewPanel({
  queue,
  filter,
  loading,
  busy,
  onFilterChange,
  onSkip,
  onReviewWord,
  onOpenResource,
  onStarResource,
  onOrganizeIdea,
  onArchiveIdea,
}: ReviewPanelProps) {
  const current = queue?.items[0] ?? null;
  const [showAnswer, setShowAnswer] = useState(false);
  const [ideaTitle, setIdeaTitle] = useState("");
  const [ideaBody, setIdeaBody] = useState("");
  const remainingCount = queue?.items.length ?? 0;
  const totalCount =
    filter === "word"
      ? (queue?.word_count ?? 0)
      : filter === "resource"
        ? (queue?.resource_count ?? 0)
        : filter === "idea"
          ? (queue?.idea_count ?? 0)
          : (queue?.word_count ?? 0) +
            (queue?.resource_count ?? 0) +
            (queue?.idea_count ?? 0);
  const sessionTotalRef = useRef<number | null>(null);
  useEffect(() => {
    sessionTotalRef.current = null;
  }, [filter]);
  if (queue && sessionTotalRef.current === null) {
    sessionTotalRef.current = totalCount;
  }
  const sessionTotal = sessionTotalRef.current ?? totalCount;
  const progressLabel =
    current && sessionTotal > 0
      ? `${Math.min(sessionTotal - totalCount + 1, sessionTotal)}/${sessionTotal}`
      : null;

  useEffect(() => {
    setShowAnswer(false);
    setIdeaTitle(current?.type === "idea" ? current.title : "");
    setIdeaBody(current?.type === "idea" ? current.body : "");
  }, [current?.id]);

  if (loading && !queue) {
    return <div className="review-empty">正在准备今日回顾…</div>;
  }
  if (!queue || totalCount === 0 || !current) {
    return (
      <section className="review-complete">
        <span className="review-complete-icon" aria-hidden="true">◷</span>
        <h2>今天的回顾已经完成</h2>
        <p>到期单词、待读资料和待整理灵感都会出现在这里。可以返回资料库继续收藏。</p>
      </section>
    );
  }

  return (
    <section className="review-session" aria-labelledby="review-card-title">
      <div className="review-queue-filters" aria-label="回顾队列">
        {queueFilters.map((item) => (
          <button
            key={item.value}
            type="button"
            className={filter === item.value ? "active" : ""}
            onClick={() => onFilterChange(item.value)}
          >
            {item.label}
          </button>
        ))}
      </div>
      <div className="review-stats" aria-label="今日回顾数量">
        <span><strong>{queue.word_count}</strong> 个单词</span>
        <span><strong>{queue.resource_count}</strong> 篇待读</span>
        <span><strong>{queue.idea_count}</strong> 条待整理</span>
      </div>
      <article className="review-card">
        <div className="review-card-meta">
          <span>
            {current.type === "word"
              ? "单词复习"
              : current.type === "resource"
                ? "待阅读"
                : "待整理灵感"}
          </span>
          <span>{progressLabel ?? `还剩 ${remainingCount} 条`}</span>
        </div>
        {current.type === "word" && (
          <>
            <h2 id="review-card-title">{current.title}</h2>
            <WordPronunciation lemma={current.title} />
            {current.word_phonetic && <p className="review-phonetic">{current.word_phonetic}</p>}
            {current.word_example && (
              <p className="review-example">“{current.word_example}”</p>
            )}
            <p className="review-schedule">
              上次 {formatReviewTime(current.last_review_at, "尚未复习")}
              {" · "}
              下次 {formatReviewTime(current.next_review_at, "待安排")}
            </p>
            {showAnswer ? (
              <div className="review-answer">
                <p>{current.word_meaning || current.body}</p>
                <div className="review-actions">
                  <button type="button" disabled={busy} onClick={() => onReviewWord(current, "forgot")}>忘记</button>
                  <button type="button" disabled={busy} onClick={() => onReviewWord(current, "fuzzy")}>模糊</button>
                  <button type="button" className="primary" disabled={busy} onClick={() => onReviewWord(current, "remembered")}>记得</button>
                </div>
              </div>
            ) : (
              <div className="review-hidden">
                <p>先回想释义和例句，再显示答案。</p>
                <button type="button" onClick={() => setShowAnswer(true)}>显示答案</button>
              </div>
            )}
          </>
        )}
        {current.type === "resource" && (
          <>
            <h2 id="review-card-title">{current.title}</h2>
            <p className="review-example">
              {sourceHost(current.source_url)}
              {current.resource_category_label ? ` · ${current.resource_category_label}` : ""}
            </p>
            {current.resource_description && <p>{current.resource_description}</p>}
            <div className="review-actions">
              <button type="button" className="primary" disabled={busy} onClick={() => onOpenResource(current)}>打开原网页</button>
              <button type="button" disabled={busy} onClick={() => onStarResource(current)}>
                {current.starred ? "取消星标" : "星标"}
              </button>
            </div>
          </>
        )}
        {current.type === "idea" && (
          <>
            <h2 id="review-card-title">补充这条灵感</h2>
            <label>
              标题
              <input
                value={ideaTitle}
                onChange={(event) => setIdeaTitle(event.target.value)}
                maxLength={200}
              />
            </label>
            <label>
              内容
              <textarea
                value={ideaBody}
                onChange={(event) => setIdeaBody(event.target.value)}
                rows={6}
                maxLength={50_000}
              />
            </label>
            <div className="review-actions">
              <button
                type="button"
                className="primary"
                disabled={busy || !ideaBody.trim()}
                onClick={() => onOrganizeIdea(current, ideaTitle.trim(), ideaBody.trim())}
              >
                整理完成
              </button>
              <button type="button" disabled={busy} onClick={() => onArchiveIdea(current)}>归档</button>
            </div>
          </>
        )}
        <button type="button" className="review-skip" disabled={busy} onClick={() => onSkip(current)}>
          跳过
        </button>
      </article>
    </section>
  );
}
