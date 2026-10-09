import { useEffect, useRef, useState } from "react";

import WordPronunciation from "./WordPronunciation";
import type {
  Memo,
  MemoType,
  ReviewFeedback,
  ReviewQueueResponse,
  ReviewSettings,
} from "./types";

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
  reviewSettings: ReviewSettings | null;
  reviewSettingsBusy: boolean;
  onSaveReviewSettings: (
    dailyLimit: number,
    intervalsDays: number[],
  ) => Promise<void>;
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

const reviewIntervalLabels = [
  "忘记后",
  "模糊后 / 熟悉度 1",
  "熟悉度 2",
  "熟悉度 3",
  "熟悉度 4",
  "熟悉度 5",
];

interface ReviewPlanSettingsProps {
  settings: ReviewSettings | null;
  busy: boolean;
  onSave: (dailyLimit: number, intervalsDays: number[]) => Promise<void>;
}

function ReviewPlanSettings({ settings, busy, onSave }: ReviewPlanSettingsProps) {
  const [open, setOpen] = useState(false);
  const [dailyLimit, setDailyLimit] = useState("10");
  const [intervalsDays, setIntervalsDays] = useState<string[]>(
    [1, 3, 7, 14, 30, 60].map(String),
  );
  const [error, setError] = useState("");

  useEffect(() => {
    if (!settings) {
      return;
    }
    setDailyLimit(String(settings.daily_limit));
    setIntervalsDays(settings.intervals_days.map(String));
  }, [settings]);

  const handleSave = () => {
    const parsedDailyLimit = Number(dailyLimit);
    const parsedIntervals = intervalsDays.map(Number);
    if (
      !Number.isInteger(parsedDailyLimit) ||
      parsedDailyLimit < 1 ||
      parsedDailyLimit > 100
    ) {
      setError("每日上限需要是 1–100 的整数。");
      return;
    }
    if (
      parsedIntervals.length !== 6 ||
      parsedIntervals.some(
        (interval) => !Number.isInteger(interval) || interval < 1 || interval > 365,
      )
    ) {
      setError("每个间隔需要是 1–365 天的整数。");
      return;
    }
    setError("");
    void onSave(parsedDailyLimit, parsedIntervals);
  };

  return (
    <section className="review-plan-settings" aria-label="自定义复习计划">
      <div className="review-plan-heading">
        <div>
          <strong>复习计划</strong>
          <span>
            {settings
              ? `每天最多 ${settings.daily_limit} 条 · ${settings.intervals_days.join(" / ")} 天`
              : "正在读取设置…"}
          </span>
        </div>
        <button type="button" onClick={() => setOpen((value) => !value)}>
          {open ? "收起" : "调整计划"}
        </button>
      </div>
      {open && (
        <div className="review-plan-fields">
          <label>
            每日队列上限
            <input
              type="number"
              min="1"
              max="100"
              value={dailyLimit}
              onChange={(event) => setDailyLimit(event.target.value)}
              disabled={busy}
            />
          </label>
          <div className="review-interval-grid">
            {intervalsDays.map((value, index) => (
              <label key={reviewIntervalLabels[index]}>
                {reviewIntervalLabels[index]}
                <input
                  type="number"
                  min="1"
                  max="365"
                  value={value}
                  onChange={(event) => {
                    const next = [...intervalsDays];
                    next[index] = event.target.value;
                    setIntervalsDays(next);
                  }}
                  disabled={busy}
                />
              </label>
            ))}
          </div>
          <p className="review-plan-help">
            “记得”会按复习后的熟悉度选择对应间隔；“忘记”和“模糊”分别使用前两档。
          </p>
          {error && <p className="review-plan-error">{error}</p>}
          <button
            type="button"
            className="primary"
            onClick={handleSave}
            disabled={busy || !settings}
          >
            {busy ? "保存中…" : "保存计划"}
          </button>
        </div>
      )}
    </section>
  );
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
  reviewSettings,
  reviewSettingsBusy,
  onSaveReviewSettings,
}: ReviewPanelProps) {
  const current = queue?.items[0] ?? null;
  const [showAnswer, setShowAnswer] = useState(false);
  const [ideaTitle, setIdeaTitle] = useState("");
  const [ideaBody, setIdeaBody] = useState("");
  const remainingCount = queue?.items.length ?? 0;
  const scheduledCount = queue?.scheduled_count ?? remainingCount;
  const dailyLimit = queue?.daily_limit ?? 10;
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
    sessionTotalRef.current = scheduledCount;
  }
  const sessionTotal = sessionTotalRef.current ?? totalCount;
  const progressLabel =
    current && sessionTotal > 0
      ? `${Math.min(sessionTotal - remainingCount + 1, sessionTotal)}/${sessionTotal}`
      : null;

  useEffect(() => {
    setShowAnswer(false);
    setIdeaTitle(current?.type === "idea" ? current.title : "");
    setIdeaBody(current?.type === "idea" ? current.body : "");
  }, [current?.id]);

  if (loading && !queue) {
    return (
      <div className="review-empty">
        <ReviewPlanSettings
          settings={reviewSettings}
          busy={reviewSettingsBusy}
          onSave={onSaveReviewSettings}
        />
        正在准备今日回顾…
      </div>
    );
  }
  if (!queue || totalCount === 0 || !current) {
    return (
      <section className="review-session">
        <ReviewPlanSettings
          settings={reviewSettings}
          busy={reviewSettingsBusy}
          onSave={onSaveReviewSettings}
        />
        <div className="review-complete">
          <span className="review-complete-icon" aria-hidden="true">◷</span>
          <h2>今天的回顾已经完成</h2>
          <p>到期单词、待读资料和待整理灵感都会出现在这里。可以返回资料库继续收藏。</p>
        </div>
      </section>
    );
  }

  return (
    <section className="review-session" aria-labelledby="review-card-title">
      <ReviewPlanSettings
        settings={reviewSettings}
        busy={reviewSettingsBusy}
        onSave={onSaveReviewSettings}
      />
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
        <span><strong>{scheduledCount}</strong> / {dailyLimit} 条今日计划</span>
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
            <WordPronunciation
              lemma={current.title}
              phonetic={current.word_phonetic}
              usAudioUrl={current.word_us_audio_url}
              ukAudioUrl={current.word_uk_audio_url}
            />
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
              {current.resource_categories && current.resource_categories.length > 0
                ? ` · ${current.resource_categories.length} 个分类`
                : current.resource_category_label
                  ? ` · ${current.resource_category_label}`
                  : ""}
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
