import { useCallback, useEffect, useRef, useState } from "react";

import { getRandomMemo, getWeeklySummary } from "./api";
import Icon from "./Icon";
import type { Memo, WeeklySummary } from "./types";

interface WeeklyDigestProps {
  /** 打开摘要里的条目或随机漫游抽到的条目。 */
  onOpen: (memo: Memo) => void;
}

// 最近抽到过的条目，下一次随机漫游时尽量避开。
const RECENT_WANDER_LIMIT = 20;

const typeLabels: { key: keyof WeeklySummary["created_by_type"]; label: string }[] = [
  { key: "resource", label: "网页资料" },
  { key: "word", label: "单词" },
  { key: "idea", label: "灵感" },
  { key: "image", label: "图片" },
];

/** 回顾页顶部：最近七天的概览，以及「随便看看」随机漫游。 */
export default function WeeklyDigest({ onOpen }: WeeklyDigestProps) {
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
        if (active) setError(reason instanceof Error ? reason.message : "摘要加载失败");
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
        setWanderMessage("资料库还是空的，先收藏几条内容吧。");
        return;
      }
      recentRef.current = [memo.id, ...recentRef.current.filter((id) => id !== memo.id)]
        .slice(0, RECENT_WANDER_LIMIT);
      onOpen(memo);
    } catch (reason) {
      setWanderMessage(reason instanceof Error ? reason.message : "随机漫游失败");
    } finally {
      setWandering(false);
    }
  }, [onOpen]);

  return (
    <section className="weekly-digest" aria-label="本周摘要">
      <div className="weekly-digest-heading">
        <div>
          <strong>本周摘要</strong>
          <span>最近 7 天</span>
        </div>
        <button type="button" onClick={() => void wander()} disabled={wandering}>
          <Icon name="review" size={16} />
          {wandering ? "正在挑选…" : "随便看看"}
        </button>
      </div>
      {wanderMessage && <p className="weekly-digest-note" role="status">{wanderMessage}</p>}
      {error && <p className="weekly-digest-note">{error}</p>}
      {!summary && !error && <p className="weekly-digest-note">正在统计…</p>}
      {summary && (
        <>
          <dl className="weekly-digest-stats">
            <div>
              <dt>新增收藏</dt>
              <dd>{summary.created_total}</dd>
            </div>
            <div>
              <dt>复习单词</dt>
              <dd>{summary.reviewed_words}</dd>
            </div>
            <div>
              <dt>打开资料</dt>
              <dd>{summary.opened_resources}</dd>
            </div>
            <div>
              <dt>待整理</dt>
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
            <p className="weekly-digest-tags" aria-label="本周常用标签">
              {summary.top_tags.map(({ tag, count }) => (
                <span key={tag} className="memo-tag">#{tag} × {count}</span>
              ))}
            </p>
          )}
          {summary.highlights.length > 0 && (
            <ul className="weekly-digest-highlights" aria-label="本周新收藏">
              {summary.highlights.map((memo) => (
                <li key={memo.id}>
                  <button type="button" onClick={() => onOpen(memo)}>{memo.title}</button>
                </li>
              ))}
            </ul>
          )}
          {summary.created_total === 0 && (
            <p className="weekly-digest-note">这周还没有新收藏，试试「随便看看」重新遇见旧内容。</p>
          )}
        </>
      )}
    </section>
  );
}
