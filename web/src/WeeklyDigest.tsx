import { useCallback, useEffect, useRef, useState } from "react";

import { getRandomMemo, getWeeklySummary } from "./api";
import Icon from "./Icon";
import type { Memo, WeeklySummary } from "./types";
import { t } from "./i18n";
import { useI18n } from "./I18nProvider";

interface WeeklyDigestProps {
  /** 打开摘要里的条目或随机漫游抽到的条目。 */
  onOpen: (memo: Memo) => void;
}

// 最近抽到过的条目，下一次随机漫游时尽量避开。
const RECENT_WANDER_LIMIT = 20;

const typeLabels: { key: keyof WeeklySummary["created_by_type"]; label: string }[] = [
  { key: "resource", get label() { return t("网页资料"); } },
  { key: "word", get label() { return t("单词"); } },
  { key: "idea", get label() { return t("灵感"); } },
  { key: "image", get label() { return t("图片"); } },
];

/** 回顾页顶部：最近七天的概览，以及「随便看看」随机漫游。 */
export default function WeeklyDigest({ onOpen }: WeeklyDigestProps) {
  const { t } = useI18n();
  const [summary, setSummary] = useState<WeeklySummary | null>(null);
  const [error, setError] = useState("");
  const [wandering, setWandering] = useState(false);
  const [wanderMessage, setWanderMessage] = useState("");
  const recentRef = useRef<string[]>([]);

  useEffect(() => {
    let active = true;
    getWeeklySummary()
      .then((next) => {
        if (active) setSummary(next);
      })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : t("摘要加载失败"));
      });
    return () => {
      active = false;
    };
  }, []);

  const wander = useCallback(async () => {
    setWandering(true);
    setWanderMessage("");
    try {
      const memo = await getRandomMemo({ exclude: recentRef.current });
      if (!memo) {
        setWanderMessage(t("资料库还是空的，先收藏几条内容吧。"));
        return;
      }
      recentRef.current = [memo.id, ...recentRef.current.filter((id) => id !== memo.id)]
        .slice(0, RECENT_WANDER_LIMIT);
      onOpen(memo);
    } catch (reason) {
      setWanderMessage(reason instanceof Error ? reason.message : t("随机漫游失败"));
    } finally {
      setWandering(false);
    }
  }, [onOpen]);

  return (
    <section className="weekly-digest" aria-label={t("本周摘要")}>
      <div className="weekly-digest-heading">
        <div>
          <strong>{t("本周摘要")}</strong>
          <span>{t("最近 7 天")}</span>
        </div>
        <button type="button" onClick={() => void wander()} disabled={wandering}>
          <Icon name="review" size={16} />
          {wandering ? t("正在挑选…") : t("随便看看")}
        </button>
      </div>
      {wanderMessage && <p className="weekly-digest-note" role="status">{wanderMessage}</p>}
      {error && <p className="weekly-digest-note">{error}</p>}
      {!summary && !error && <p className="weekly-digest-note">{t("正在统计…")}</p>}
      {summary && (
        <>
          <dl className="weekly-digest-stats">
            <div>
              <dt>{t("新增收藏")}</dt>
              <dd>{summary.created_total}</dd>
            </div>
            <div>
              <dt>{t("复习单词")}</dt>
              <dd>{summary.reviewed_words}</dd>
            </div>
            <div>
              <dt>{t("打开资料")}</dt>
              <dd>{summary.opened_resources}</dd>
            </div>
            <div>
              <dt>{t("待整理")}</dt>
              <dd>{summary.inbox_remaining}</dd>
            </div>
          </dl>
          {summary.created_total > 0 && (
            <p className="weekly-digest-breakdown">
              {typeLabels
                .filter(({ key }) => (summary.created_by_type[key] ?? 0) > 0)
                .map(({ key, label }) => `${label} ${summary.created_by_type[key]}`)
                .join(" · ")}
            </p>
          )}
          {summary.top_tags.length > 0 && (
            <p className="weekly-digest-tags" aria-label={t("本周常用标签")}>
              {summary.top_tags.map(({ tag, count }) => (
                <span key={tag} className="memo-tag">#{tag} × {count}</span>
              ))}
            </p>
          )}
          {summary.highlights.length > 0 && (
            <ul className="weekly-digest-highlights" aria-label={t("本周新收藏")}>
              {summary.highlights.map((memo) => (
                <li key={memo.id}>
                  <button type="button" onClick={() => onOpen(memo)}>{memo.title}</button>
                </li>
              ))}
            </ul>
          )}
          {summary.created_total === 0 && (
            <p className="weekly-digest-note">{t("这周还没有新收藏，试试「随便看看」重新遇见旧内容。")}</p>
          )}
        </>
      )}
    </section>
  );
}
