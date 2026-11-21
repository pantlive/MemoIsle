import { type CSSProperties, memo as memoComponent, useState } from "react";
import { categoryDepth } from "./categoryTree";
import Icon from "./Icon";
import { formatImageBytes, imageDimensionLabel } from "./imageFiles";
import MemoImageThumb from "./MemoImageThumb";
import {
  MAX_MEMO_CATEGORIES,
  memoCategoryCodes,
  memoCategoryLabels,
} from "./memoCategories";
import { trashDaysRemaining } from "./memoListHelpers";
import ResourceClassificationInsight from "./ResourceClassificationInsight";
import ResourceMonogram from "./ResourceIcon";
import { resourceSummary } from "./resourceSummary";
import type { Memo, ResourceCategoryOption } from "./types";
import { siteHue, sourceHost } from "./webUrl";
import { type ActiveView, timeFormatter, viewCopy } from "./workspaceViews";
import { useI18n } from "./I18nProvider";

/**
 * 列表行与图片卡片。
 *
 * 用 memo 包裹：App 每次重渲染（例如在收藏框里打字）时，只有数据或选中状态
 * 变了的行才重绘。回调统一经过稳定的 actions 对象传入，避免每次渲染都换引用。
 */
export interface MemoRowActions {
  select(memo: Memo): void;
  openPreview(memo: Memo): void;
  opened(memo: Memo): void;
  toggleBatch(memo: Memo): void;
  organizeInbox(memo: Memo): void;
  archiveInbox(memo: Memo): void;
  restore(memo: Memo): void;
  permanentDelete(memo: Memo): void;
  toggleCategory(memo: Memo, code: string): void;
  toggleStar(memo: Memo): void;
  moveToTrash(memo: Memo): void;
}

interface ImageCardProps {
  memo: Memo;
  selected: boolean;
  batchSelected: boolean;
  batchBusy: boolean;
  actions: MemoRowActions;
}

function ImageCardView({ memo, selected, batchSelected, batchBusy, actions }: ImageCardProps) {
  const { t } = useI18n();
  return (
    <article
      className={`image-card${selected ? " selected" : ""}${batchSelected ? " batch-selected" : ""}`}
      tabIndex={0}
      onClick={() => actions.select(memo)}
      onKeyDown={(event) => {
        if (event.target !== event.currentTarget) {
          return;
        }
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          actions.select(memo);
        }
      }}
    >
      <div className="image-card-media">
        {memo.image_mime_type ? (
          <MemoImageThumb
            memoId={memo.id}
            version={memo.version}
            alt={memo.title}
            className="image-card-thumb"
          />
        ) : (
          <span className="image-card-empty">{t("尚未上传图片")}</span>
        )}
      </div>
      <div className="image-card-body">
        <label className="memo-batch-check" onClick={(event) => event.stopPropagation()}>
          <input type="checkbox" aria-label={t("选择 {title}", { title: memo.title })} disabled={batchBusy} checked={batchSelected} onChange={() => actions.toggleBatch(memo)} />
          <span>{t("选择")}</span>
        </label>
        <strong>{memo.starred && <Icon name="star" size={16} className="is-filled" />}{memo.title}</strong>
        {memo.resource_category_label && <small>{t("分类：{resource_category_label}", { resource_category_label: memo.resource_category_label })}</small>}
        <small>
          {timeFormatter().format(new Date(memo.created_at))} ·{" "}
          {imageDimensionLabel(memo)}
        </small>
        <small>
          {formatImageBytes(memo.image_size_bytes) || t("等待上传文件")}
        </small>
        {memo.image_ocr_status === "ready" &&
          (memo.image_auto_tags ?? []).length > 0 && (
            <small
              className="image-card-tags"
              title={memo.image_auto_tags.join(" ")}
            >
              {memo.image_auto_tags
                .slice(0, 2)
                .map((tag) => `#${tag}`)
                .join(" ")}
            </small>
          )}
      </div>
    </article>
  );
}

export const ImageCard = memoComponent(ImageCardView);

interface MemoListRowProps {
  memo: Memo;
  view: ActiveView;
  selected: boolean;
  batchSelected: boolean;
  batchBusy: boolean;
  /** 该资料正在保存分类/星标。 */
  updating: boolean;
  /** 回收站正在批量恢复或清空。 */
  trashBusy: boolean;
  categories: ResourceCategoryOption[];
  actions: MemoRowActions;
}

function MemoListRowView({
  memo,
  view,
  selected,
  batchSelected,
  batchBusy,
  updating,
  trashBusy,
  categories,
  actions,
}: MemoListRowProps) {
  const { t } = useI18n();
  const [pickerOpen, setPickerOpen] = useState(false);
  return (
    <article
      className={
        `memo-row${memo.type === "resource" ? " resource-row" : ""}` +
        (selected ? " selected" : "") +
        (batchSelected ? " batch-selected" : "")
      }
      data-memo-id={memo.id}
      onClick={() => {
        if (view !== "trash" && memo.type === "resource") {
          actions.openPreview(memo);
        } else if (view !== "trash") {
          actions.select(memo);
        }
      }}
      onKeyDown={(event) => {
        if (view === "trash" || event.target !== event.currentTarget) {
          return;
        }
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          if (memo.type === "resource") {
            actions.openPreview(memo);
          } else {
            actions.select(memo);
          }
        }
      }}
      tabIndex={
        view === "trash" ? undefined : 0
      }
      >
      <input className="memo-batch-check" type="checkbox" aria-label={t("选择 {title}", { title: memo.title })}
        disabled={batchBusy} checked={batchSelected} onClick={(event) => event.stopPropagation()}
        onChange={() => actions.toggleBatch(memo)} />
      <span
        className={`memo-type-icon ${memo.type}`}
        style={memo.type === "resource"
          ? { "--avatar-hue": siteHue(sourceHost(memo.source_url) || memo.title) } as CSSProperties
          : undefined}
      >
        {memo.audio_mime_type ? (
          <Icon name="audio" size={18} />
        ) : memo.type === "image" && memo.image_mime_type ? (
          <MemoImageThumb
            memoId={memo.id}
            version={memo.version}
            alt={memo.title}
            className="memo-image-thumb"
          />
        ) : memo.type === "resource" ? (
          <ResourceMonogram
            sourceUrl={memo.source_url}
            siteName={memo.resource_site_name}
          />
        ) : (
          <Icon name={viewCopy[memo.type].icon} size={18} />
        )}
      </span>
      <span className="memo-copy">
        {memo.type === "resource" && memo.source_url ? (
          <a
            className="memo-title-link"
            href={memo.source_url}
            target="_blank"
            rel="noreferrer"
            onClick={(event) => {
              event.stopPropagation();
              actions.opened(memo);
            }}
            onAuxClick={(event) => {
              if (event.button === 1) actions.opened(memo);
            }}
          >
            {memo.title}
          </a>
        ) : (
          <strong>{memo.starred && <Icon name="star" size={16} className="is-filled" />}{memo.title}</strong>
        )}
        <span>
          {memo.type === "resource"
            ? resourceSummary(memo) || sourceHost(memo.source_url)
            : memo.type === "word"
              ? memo.word_phonetic || memo.word_meaning || t("等待补充释义")
              : memo.type === "image"
                ? memo.body || t("图片收藏")
                : memo.body}
        </span>
        {memo.type === "resource" && <ResourceClassificationInsight memo={memo} compact />}
        <small className="memo-meta-line">
          {memo.type === "resource"
            ? (
              <>
                {/* 标题已是原网页链接；无标题时标题就是站点名，不再重复。 */}
                {memo.title !== sourceHost(memo.source_url) && (
                  <span className="memo-source-host">{sourceHost(memo.source_url)}</span>
                )}
                {memo.resource_open_count > 0 && (
                  <span className="memo-open-count">{t("打开 {resource_open_count} 次", { resource_open_count: memo.resource_open_count })}</span>
                )}
                {memo.tags.length > 0 && (
                  <span className="memo-tags" aria-label={t("我的标签")}>
                    {memo.tags.map((tag) => (
                      <span key={tag} className="memo-tag">#{tag}</span>
                    ))}
                  </span>
                )}
                {memo.ebook_path && (
                  <span
                    className="memo-ebook-badge"
                    title={memo.ebook_path}
                  >
                    {t("云盘")}
                    {memo.ebook_format
                      ? ` · ${memo.ebook_format.toUpperCase()}`
                      : ""}
                    {memo.ebook_size_bytes
                      ? ` · ${formatImageBytes(memo.ebook_size_bytes)}`
                      : ""}
                  </span>
                )}
              </>
            )
            : memo.type === "word"
              ? t("熟悉度 {familiarity}/5 · 已复习 {review_count} 次 · 下次 {value}", { familiarity: memo.familiarity, review_count: memo.review_count, value: memo.next_review_at
                  ? timeFormatter().format(new Date(memo.next_review_at))
                  : t("待安排") })
              : memo.type === "image"
                ? memo.image_mime_type
                  ? t("图片 · {value} · {value2}", { value: imageDimensionLabel(memo), value2: formatImageBytes(memo.image_size_bytes) || t("处理中") })
                  : t("尚未上传图片")
                : memo.audio_mime_type ? t("语音灵感") : t("灵感")}
          {memo.type !== "resource" && t(" · 版本 {version}", { version: memo.version })}
          {view === "trash" &&
            t(" · 还剩 {value} 天", { value: trashDaysRemaining(memo) })}
          {view === "inbox" && t(" · 待整理")}
        </small>
      </span>
      <span className="memo-row-side">
        <time dateTime={memo.updated_at}>
          {timeFormatter().format(new Date(memo.updated_at))}
        </time>
        {view === "inbox" && (
          <span
            className="trash-inline-actions"
            onClick={(event) => event.stopPropagation()}
          >
            <button
              type="button"
              onClick={() => actions.organizeInbox(memo)}
            >
              {t("整理完成")}
            </button>
            <button
              type="button"
              onClick={() => actions.archiveInbox(memo)}
            >
              {t("归档")}
            </button>
          </span>
        )}
        {view === "trash" && (
          <span
            className="trash-inline-actions"
            onClick={(event) => event.stopPropagation()}
          >
            <button
              type="button"
              onClick={() => actions.restore(memo)}
              disabled={trashBusy}
            >
              {t("恢复")}
            </button>
            <button
              type="button"
              className="danger"
              onClick={() => actions.permanentDelete(memo)}
              disabled={trashBusy}
            >
              {t("永久删除")}
            </button>
          </span>
        )}
        {view !== "trash" && memo.type === "resource" && (
          <span
            className="resource-inline-actions"
            onClick={(event) => event.stopPropagation()}
          >
            <details
              className="resource-category-picker"
              onToggle={(event) => setPickerOpen(event.currentTarget.open)}
            >
              <summary
                title={memoCategoryLabels(memo, categories).join(t("、"))}
              >
                {memoCategoryLabels(memo, categories).join(t("、"))
                  || t("分类中")}
              </summary>
              {/* 收起时不渲染菜单：每行一整套分类复选框会让长列表的 DOM 膨胀。 */}
              {pickerOpen && (
                <div className="resource-category-picker-menu">
                  {categories
                    .filter((category) => category.is_active)
                    .map((category) => {
                      const selectedCodes = memoCategoryCodes(memo);
                      const selected = selectedCodes.includes(category.code);
                      return (
                        <label
                          key={category.code}
                          style={{
                            paddingLeft: `${8 + (categoryDepth(category) - 1) * 12}px`,
                          }}
                        >
                          <input
                            type="checkbox"
                            checked={selected}
                            disabled={
                              updating
                              || (
                                !selected
                                && selectedCodes.length >= MAX_MEMO_CATEGORIES
                              )
                            }
                            onChange={() =>
                              actions.toggleCategory(memo, category.code)
                            }
                          />
                          {category.path || category.name}
                        </label>
                      );
                    })}
                  <small>{t("最多 8 个分类")}</small>
                </div>
              )}
            </details>
            <button
              type="button"
              className={memo.starred ? "starred" : ""}
              aria-label={memo.starred ? t("取消星标") : t("添加星标")}
              aria-pressed={memo.starred}
              title={memo.starred ? t("取消星标") : t("添加星标")}
              disabled={updating}
              onClick={() =>
                actions.toggleStar(memo)
              }
            >
              <Icon name="star" size={16} className={memo.starred ? "is-filled" : undefined} />
            </button>
            <button
              type="button"
              className="resource-trash-button"
              aria-label={t("将“{title}”移入回收站", { title: memo.title })}
              title={t("移入回收站")}
              disabled={updating}
              onClick={() => actions.moveToTrash(memo)}
            >
              <Icon name="trash" size={16} />
            </button>
          </span>
        )}
      </span>
    </article>
  );
}

export const MemoListRow = memoComponent(MemoListRowView);
