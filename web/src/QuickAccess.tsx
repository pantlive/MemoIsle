import type { CSSProperties } from "react";

import type { Memo } from "./types";
import { sourceHost } from "./webUrl";

// 由站点名算出固定色相，同一站点每次显示同一种颜色。
function avatarHue(text: string): number {
  let hash = 0;
  for (const char of text) hash = (hash * 31 + char.charCodeAt(0)) % 360;
  return hash;
}

function avatarLetter(memo: Memo): string {
  const name = memo.resource_site_name || sourceHost(memo.source_url) || memo.title;
  return (name.replace(/^www\./, "").trim()[0] ?? "?").toUpperCase();
}

// 快速访问：按打开次数列出常用网页，点击即在新标签页打开并计数。
// 不加载站点 favicon，避免每次进入页面都向第三方暴露访问记录。
export default function QuickAccess({ items, loaded, onOpen, onRemove, compact = false }: {
  items: Memo[];
  // 首次读取完成前不显示，避免空状态一闪而过。
  loaded: boolean;
  onOpen: (memo: Memo) => void;
  onRemove: (memo: Memo) => void;
  compact?: boolean;
}) {
  if (!loaded) return null;
  return (
    <section className={`quick-access${compact ? " compact" : ""}`} aria-labelledby="quick-access-title">
      <div className="quick-access-header">
        <h2 id="quick-access-title">快速访问</h2>
        <small>按打开次数排列</small>
      </div>
      {items.length === 0 && (
        <p className="quick-access-empty">
          还没有打开记录。在 MemoIsle 里点开网页标题或「打开原网页」后，常用的网页会按打开次数出现在这里。
        </p>
      )}
      {items.length > 0 && <ul className="quick-access-grid">
        {items.map((memo) => {
          const host = sourceHost(memo.source_url);
          return (
            <li key={memo.id}>
              <a
                className="quick-access-tile"
                data-memo-id={memo.id}
                href={memo.source_url ?? undefined}
                target="_blank"
                rel="noreferrer"
                title={`${memo.title}\n${memo.source_url ?? ""}`}
                onClick={() => onOpen(memo)}
                onAuxClick={(event) => {
                  // 中键在新标签页打开同样计数。
                  if (event.button === 1) onOpen(memo);
                }}
              >
                <span
                  className="quick-access-avatar"
                  aria-hidden="true"
                  style={{ "--avatar-hue": avatarHue(host || memo.title) } as CSSProperties}
                >
                  {avatarLetter(memo)}
                </span>
                <span className="quick-access-text">
                  <strong>{memo.title}</strong>
                  <small>{memo.resource_open_count} 次 · {host}</small>
                </span>
              </a>
              <button
                type="button"
                className="quick-access-remove"
                aria-label={`从快速访问移除「${memo.title}」`}
                title="从快速访问移除"
                onClick={() => {
                  // 移除后焦点落到相邻磁贴，键盘操作不会丢失位置。
                  const index = items.findIndex((item) => item.id === memo.id);
                  const neighbor = items[index + 1] ?? items[index - 1];
                  onRemove(memo);
                  if (neighbor) {
                    window.requestAnimationFrame(() => {
                      document
                        .querySelector<HTMLElement>(`.quick-access-tile[data-memo-id="${neighbor.id}"]`)
                        ?.focus();
                    });
                  }
                }}
              >×</button>
            </li>
          );
        })}
      </ul>}
    </section>
  );
}
