import type { IconName } from "./Icon";
import type { OfflineDraftMemoType } from "./offlineDrafts";
import type { MemoType } from "./types";

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
  action?: "health" | "settings" | "vault" | "history";
  /** 分组的第一项带上组名，侧栏在它上方显示小标题。 */
  group?: string;
}

export const navigation: NavigationItem[] = [
  { label: "首页", icon: "home", view: "all" },
  { label: "收件箱", icon: "inbox", view: "inbox" },
  { label: "回顾", icon: "review", view: "review" },
  { label: "网页资料", icon: "link", view: "resource", group: "收藏" },
  { label: "英语单词", icon: "word", view: "word" },
  { label: "灵感", icon: "idea", view: "idea" },
  { label: "图片收藏", icon: "image", view: "image" },
  { label: "网页巡检", icon: "health", action: "health", group: "工具" },
  { label: "浏览历史", icon: "history", action: "history" },
  { label: "密码库", icon: "vault", action: "vault" },
  { label: "回收站", icon: "trash", view: "trash" },
  { label: "设置", icon: "settings", action: "settings" },
];

export const headingDateFormatter = new Intl.DateTimeFormat("zh-CN", {
  month: "long",
  day: "numeric",
  weekday: "long",
});

/** 首页标题按当前时段问候。 */
export function greetingForHour(hour: number): string {
  if (hour < 5) return "夜深了";
  if (hour < 11) return "早上好";
  if (hour < 13) return "中午好";
  if (hour < 18) return "下午好";
  return "晚上好";
}

export const timeFormatter = new Intl.DateTimeFormat("zh-CN", {
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

export const viewCopy = {
  all: {
    title: "最近内容",
    eyebrow: "一个入口，找回所有收藏",
    icon: "collection",
    itemLabel: "内容",
    emptyTitle: "资料库还是空的",
    emptyBody: "从灵感、英语单词或网页资料开始收藏第一条内容。",
  },
  idea: {
    title: "灵感",
    eyebrow: "捕捉此刻的想法",
    icon: "idea",
    itemLabel: "灵感",
    emptyTitle: "第一条灵感正在等你",
    emptyBody: "从上方快速记录开始，内容会同步到你的 Android 设备。",
  },
  resource: {
    title: "网页资料",
    eyebrow: "保存值得再次打开的内容",
    icon: "link",
    itemLabel: "资料",
    emptyTitle: "还没有收藏网页资料",
    emptyBody: "粘贴文章、课程、工具或视频链接，稍后继续阅读。",
  },
  word: {
    title: "英语单词",
    eyebrow: "收藏语境，按计划再次遇见",
    icon: "word",
    itemLabel: "单词",
    emptyTitle: "从第一个英语单词开始",
    emptyBody: "保存词形、释义和例句，稍后使用三档反馈进行复习。",
  },
  image: {
    title: "图片收藏",
    eyebrow: "收藏画面，随时再看一眼",
    icon: "image",
    itemLabel: "图片",
    emptyTitle: "还没有收藏图片",
    emptyBody: "选择、拖入或直接粘贴图片，就能开始图片收藏。",
  },
  review: {
    title: "今日回顾",
    eyebrow: "用几分钟再次遇见值得留下的内容",
    icon: "review",
    itemLabel: "回顾",
    emptyTitle: "今天没有需要回顾的内容",
    emptyBody: "到期单词、未读资料和待整理灵感会显示在这里。",
  },
  inbox: {
    title: "收件箱",
    eyebrow: "先记下的内容，在这里补完再放进资料库",
    icon: "inbox",
    itemLabel: "待整理条目",
    emptyTitle: "收件箱是空的",
    emptyBody: "快速记下的灵感会先到这里。补上标题或整理完成后，就会离开收件箱。",
  },
  trash: {
    title: "回收站",
    eyebrow: "删除的内容默认保留 30 天",
    icon: "trash",
    itemLabel: "回收站条目",
    emptyTitle: "回收站是空的",
    emptyBody: "移入回收站的内容会在这里保留 30 天，之后永久删除。",
  },
} as const;
