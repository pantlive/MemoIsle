import type { IconName } from "./Icon";
import type { OfflineDraftMemoType } from "./offlineDrafts";
import type { MemoType } from "./types";
import { dateTimeFormat, t } from "./i18n";

/** 工作台视图：类型定义、侧栏导航、各视图文案与时间格式。 */

export type ActiveType = Extract<MemoType, "idea" | "resource" | "word" | "image">;
export type ActiveView = ActiveType | "all" | "review" | "inbox" | "trash";
export type ResourceViewMode = "list" | "cards";

export function isCaptureType(view: ActiveView): view is OfflineDraftMemoType {
  return view === "idea" || view === "resource" || view === "word";
}

export interface NavigationItem {
  label: string;
  /** 导航统一使用内联 SVG 图标。 */
  icon: IconName;
  view?: ActiveView;
  action?: "health" | "settings" | "vault" | "ledger" | "relay" | "forget" | "history";
  /** 分组的第一项带上组名，侧栏在它上方显示小标题。 */
  group?: string;
}

export const navigation: NavigationItem[] = [
  { get label() { return t("首页"); }, icon: "home", view: "all" },
  { get label() { return t("收件箱"); }, icon: "inbox", view: "inbox" },
  { get label() { return t("回顾"); }, icon: "review", view: "review" },
  { get label() { return t("网页资料"); }, icon: "link", view: "resource", get group() { return t("收藏 @@nav"); } },
  { get label() { return t("英语单词"); }, icon: "word", view: "word" },
  { get label() { return t("灵感"); }, icon: "idea", view: "idea" },
  { get label() { return t("图片收藏"); }, icon: "image", view: "image" },
  { get label() { return t("网页巡检"); }, icon: "health", action: "health", get group() { return t("工具"); } },
  { get label() { return t("浏览历史"); }, icon: "history", action: "history" },
  { get label() { return t("密码库"); }, icon: "vault", action: "vault" },
  { get label() { return t("记账"); }, icon: "ledger", action: "ledger" },
  { get label() { return t("易忘事项"); }, icon: "forget", action: "forget" },
  { get label() { return t("传输"); }, icon: "swap", action: "relay" },
  { get label() { return t("回收站"); }, icon: "trash", view: "trash" },
  { get label() { return t("设置"); }, icon: "settings", action: "settings" },
];

export const headingDateFormatter = (): Intl.DateTimeFormat => dateTimeFormat({
  month: "long",
  day: "numeric",
  weekday: "long",
});

/** 首页标题按当前时段问候。 */
export function greetingForHour(hour: number): string {
  if (hour < 5) return t("夜深了");
  if (hour < 11) return t("早上好");
  if (hour < 13) return t("中午好");
  if (hour < 18) return t("下午好");
  return t("晚上好");
}

export const timeFormatter = (): Intl.DateTimeFormat => dateTimeFormat({
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

export const viewCopy = {
  all: {
    get title() { return t("最近内容"); },
    get eyebrow() { return t("一个入口，找回所有收藏"); },
    icon: "collection",
    get itemLabel() { return t("内容 @@item"); },
    get emptyTitle() { return t("资料库还是空的"); },
    get emptyBody() { return t("从灵感、英语单词或网页资料开始收藏第一条内容。"); },
  },
  idea: {
    get title() { return t("灵感"); },
    get eyebrow() { return t("捕捉此刻的想法"); },
    icon: "idea",
    get itemLabel() { return t("灵感 @@item"); },
    get emptyTitle() { return t("第一条灵感正在等你"); },
    get emptyBody() { return t("从上方快速记录开始，内容会同步到你的 Android 设备。"); },
  },
  resource: {
    get title() { return t("网页资料"); },
    get eyebrow() { return t("保存值得再次打开的内容"); },
    icon: "link",
    get itemLabel() { return t("资料"); },
    get emptyTitle() { return t("还没有收藏网页资料"); },
    get emptyBody() { return t("粘贴文章、课程、工具或视频链接，稍后继续阅读。"); },
  },
  word: {
    get title() { return t("英语单词"); },
    get eyebrow() { return t("收藏语境，按计划再次遇见"); },
    icon: "word",
    get itemLabel() { return t("单词"); },
    get emptyTitle() { return t("从第一个英语单词开始"); },
    get emptyBody() { return t("保存词形、释义和例句，稍后使用三档反馈进行复习。"); },
  },
  image: {
    get title() { return t("图片收藏"); },
    get eyebrow() { return t("收藏画面，随时再看一眼"); },
    icon: "image",
    get itemLabel() { return t("图片"); },
    get emptyTitle() { return t("还没有收藏图片"); },
    get emptyBody() { return t("选择、拖入或直接粘贴图片，就能开始图片收藏。"); },
  },
  review: {
    get title() { return t("今日回顾"); },
    get eyebrow() { return t("用几分钟再次遇见值得留下的内容"); },
    icon: "review",
    get itemLabel() { return t("回顾"); },
    get emptyTitle() { return t("今天没有需要回顾的内容"); },
    get emptyBody() { return t("到期单词、未读资料和待整理灵感会显示在这里。"); },
  },
  inbox: {
    get title() { return t("收件箱"); },
    get eyebrow() { return t("先记下的内容，在这里补完再放进资料库"); },
    icon: "inbox",
    get itemLabel() { return t("待整理条目"); },
    get emptyTitle() { return t("收件箱是空的"); },
    get emptyBody() { return t("快速记下的灵感会先到这里。补上标题或整理完成后，就会离开收件箱。"); },
  },
  trash: {
    get title() { return t("回收站"); },
    get eyebrow() { return t("删除的内容默认保留 30 天"); },
    icon: "trash",
    get itemLabel() { return t("回收站条目"); },
    get emptyTitle() { return t("回收站是空的"); },
    get emptyBody() { return t("移入回收站的内容会在这里保留 30 天，之后永久删除。"); },
  },
} as const;
