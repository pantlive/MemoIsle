import {
  type FormEvent,
  type ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import BookmarkImportDialog from "./BookmarkImportDialog";
import BrandLogo from "./BrandLogo";
import CategoryGenerator from "./CategoryGenerator";
import ResourceClassificationPanel from "./ResourceClassificationPanel";
import ResourceClassificationInsight from "./ResourceClassificationInsight";
import DataMenu from "./DataMenu";
import MemoBatchToolbar from "./MemoBatchToolbar";
import { normalizeWebUrl, sourceHost } from "./webUrl";
import ResourcePreviewDialog, { type ResourceEditChanges } from "./ResourcePreviewDialog";
import CategoryTemplatePanel from "./CategoryTemplatePanel";
import { categoryDepth } from "./categoryTree";
import ImageOrganizationPanel from "./ImageOrganizationPanel";
import CloudAccountDialog from "./CloudAccountDialog";
import ModelSettingsDialog from "./ModelSettingsDialog";
import EbookCollectDialog from "./EbookCollectDialog";
import { parseClipboardWord } from "./clipboardWord";
import LinkHealthDialog from "./LinkHealthDialog";
import { pendingHealthIssueCount } from "./linkHealth";
import ReviewPanel, { type ReviewQueueFilter } from "./ReviewPanel";
import QuickAccess from "./QuickAccess";
import ShortcutHelpDialog from "./ShortcutHelpDialog";
import VaultPanel from "./VaultPanel";
import { lockVaultSession } from "./vaultSession";
import { saveVaultReminderCount, useVaultReminderCount } from "./vaultReminderBadge";
import SpeechPronunciation from "./SpeechPronunciation";
import WordDictionaryPreview from "./WordDictionaryPreview";
import WordPronunciation from "./WordPronunciation";
import {
  extractCaptureUrl,
  suggestCaptureType,
  type CaptureTypeSuggestion,
} from "./captureTypeSuggestion";
import {
  createBrowserSpeechRecognition,
  type BrowserSpeechRecognitionController,
} from "./browserSpeechRecognition";
import {
  clearCaptureDraft,
  clearEditorDraft,
  loadCaptureDrafts,
  loadEditorDraft,
  saveCaptureDraft,
  saveEditorDraft,
  type CaptureDrafts,
  type OfflineDraftMemoType,
} from "./offlineDrafts";
import {
  ApiError,
  browserExtensionArchiveFilename,
  browserExtensionDownloadUrl,
  createImageMemo,
  createMemo,
  downloadUserData,
  emptyTrash,
  exchangeBrowserCapture,
  getResourceCategories,
  getResourceCategoryRules,
  getMemoCounts,
  getMemo,
  listQuickAccess,
  recordResourceOpen,
  setQuickAccessHidden,
  getLinkHealthCenter,
  getReviewSettings,
  getReviewQueue,
  loadMemoAudioUrl,
  loadMemoImageUrl,
  listOpenBrowserTabs,
  listMemos,
  lookupWord,
  mergeWord,
  importLibraryData,
  importWords,
  permanentlyDeleteMemo,
  recognizeMemoImageOcr,
  restoreAllTrash,
  restoreMemo,
  reviewWord,
  skipReview,
  trashMemo,
  updateReviewSettings,
  updateMemo,
  uploadMemoAudio,
  uploadMemoImage,
} from "./api";
import type { DataExportFormat } from "./api";
import {
  compressImageIfNeeded,
  describeImageCompression,
} from "./imageCompression";
import type {
  AuthUser,
  BrowserCaptureContext,
  BrowserOpenTab,
  ImageOcrSource,
  ImageOcrStatus,
  Memo,
  MemoCounts,
  MemoSort,
  MemoType,
  ResourceCategory,
  ResourceCategoryOption,
  ResourceCategoryRule,
  ReviewFeedback,
  ReviewQueueResponse,
  ReviewSettings,
  WordLookupResponse,
} from "./types";

type LoadState = "loading" | "ready" | "error";
type SaveState = "idle" | "saving" | "saved" | "error";
type VoiceState =
  | "idle"
  | "requesting"
  | "recording"
  | "paused"
  | "ready"
  | "saving";
type ActiveType = Extract<MemoType, "idea" | "resource" | "word" | "image">;
type ActiveView = ActiveType | "all" | "review" | "inbox" | "trash";
type ResourceViewMode = "list" | "cards";

function isCaptureType(view: ActiveView): view is OfflineDraftMemoType {
  return view === "idea" || view === "resource" || view === "word";
}

const RESOURCE_PAGE_SIZE = 10;
// 图片 OCR 为后台任务，上传后按固定间隔轮询识别结果。
const IMAGE_OCR_POLL_INTERVAL_MS = 2_000;
const IMAGE_OCR_POLL_MAX_ATTEMPTS = 10;
const IMAGE_OCR_STATUS_LABELS: Record<ImageOcrStatus, string> = {
  none: "未识别",
  pending: "排队中",
  processing: "识别中",
  ready: "已识别",
  failed: "识别失败",
  disabled: "服务端未启用",
};

interface AppProps {
  authUser: AuthUser;
  onLogout: () => void;
}

interface NavigationItem {
  label: string;
  icon: string;
  view?: ActiveView;
  action?: "health" | "settings" | "vault";
}

interface PendingResource {
  clientId: string;
  url: string;
  title: string;
  body: string;
}

interface ImageUploadTask {
  id: string;
  name: string;
  status: "pending" | "uploading" | "done" | "error";
  error?: string;
  /** 自动压缩提示（原大小 → 新大小、尺寸/格式变化）。 */
  note?: string;
}

const navigation: NavigationItem[] = [
  { label: "首页", icon: "⌂", view: "all" },
  { label: "收件箱", icon: "▣", view: "inbox" },
  { label: "英语单词", icon: "Aa", view: "word" },
  { label: "网页资料", icon: "↗", view: "resource" },
  { label: "图片收藏", icon: "▧", view: "image" },
  { label: "网页巡检", icon: "!", action: "health" },
  { label: "灵感", icon: "✦", view: "idea" },
  { label: "回顾", icon: "◷", view: "review" },
  { label: "回收站", icon: "♻", view: "trash" },
  { label: "密码库", icon: "◈", action: "vault" },
  { label: "设置", icon: "⚙", action: "settings" },
];

const timeFormatter = new Intl.DateTimeFormat("zh-CN", {
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

const MAX_MEMO_CATEGORIES = 8;

const defaultResourceCategories: ResourceCategoryOption[] = [
  ["learning", "学习资料"],
  ["article", "文章阅读"],
  ["media", "视频与音频"],
  ["tool", "工具与服务"],
  ["book_paper", "书籍与论文"],
  ["product", "商品与好物"],
  ["other", "其他"],
].map(([code, name]) => ({
  id: null,
  code,
  name,
  description: null,
  is_system: true,
  is_active: true,
  version: 1,
  parent_code: null,
  depth: 1,
  path: name,
}));

function memoCategoryCodes(memo: Memo): string[] {
  if (memo.resource_categories && memo.resource_categories.length > 0) {
    return memo.resource_categories;
  }
  return memo.resource_category ? [memo.resource_category] : [];
}

function descendantCategoryCodes(
  code: string,
  categories: ResourceCategoryOption[],
): string[] {
  const children = categories.filter((category) => category.parent_code === code);
  return [
    code,
    ...children.flatMap((child) => descendantCategoryCodes(child.code, categories)),
  ];
}

function memoMatchesCategoryFilter(
  memo: Memo,
  filter: string,
  categories: ResourceCategoryOption[],
): boolean {
  if (!filter) {
    return true;
  }
  const allowed = new Set(descendantCategoryCodes(filter, categories));
  return memoCategoryCodes(memo).some((code) => allowed.has(code));
}

function memoCategoryLabels(
  memo: Memo,
  categories: ResourceCategoryOption[],
): string[] {
  return memoCategoryCodes(memo).map((code) => {
    const option = categories.find((category) => category.code === code);
    return option?.path || option?.name || memo.resource_category_label || code;
  });
}

const viewCopy = {
  all: {
    title: "最近内容",
    eyebrow: "一个入口，找回所有收藏",
    icon: "□",
    itemLabel: "内容",
    emptyTitle: "资料库还是空的",
    emptyBody: "从灵感、英语单词或网页资料开始收藏第一条内容。",
  },
  idea: {
    title: "灵感",
    eyebrow: "捕捉此刻的想法",
    icon: "✦",
    itemLabel: "灵感",
    emptyTitle: "第一条灵感正在等你",
    emptyBody: "从上方快速记录开始，内容会同步到你的 Android 设备。",
  },
  resource: {
    title: "网页资料",
    eyebrow: "保存值得再次打开的内容",
    icon: "↗",
    itemLabel: "资料",
    emptyTitle: "还没有收藏网页资料",
    emptyBody: "粘贴文章、课程、工具或视频链接，稍后继续阅读。",
  },
  word: {
    title: "英语单词",
    eyebrow: "收藏语境，按计划再次遇见",
    icon: "Aa",
    itemLabel: "单词",
    emptyTitle: "从第一个英语单词开始",
    emptyBody: "保存词形、释义和例句，稍后使用三档反馈进行复习。",
  },
  image: {
    title: "图片收藏",
    eyebrow: "收藏画面，随时再看一眼",
    icon: "▧",
    itemLabel: "图片",
    emptyTitle: "还没有收藏图片",
    emptyBody: "选择、拖入或直接粘贴图片，就能开始图片收藏。",
  },
  review: {
    title: "今日回顾",
    eyebrow: "用几分钟再次遇见值得留下的内容",
    icon: "◷",
    itemLabel: "回顾",
    emptyTitle: "今天没有需要回顾的内容",
    emptyBody: "到期单词、未读资料和待整理灵感会显示在这里。",
  },
  inbox: {
    title: "收件箱",
    eyebrow: "先记下的内容，在这里补完再放进资料库",
    icon: "▣",
    itemLabel: "待整理条目",
    emptyTitle: "收件箱是空的",
    emptyBody: "快速记下的灵感会先到这里。补上标题或整理完成后，就会离开收件箱。",
  },
  trash: {
    title: "回收站",
    eyebrow: "删除的内容默认保留 30 天",
    icon: "♻",
    itemLabel: "回收站条目",
    emptyTitle: "回收站是空的",
    emptyBody: "移入回收站的内容会在这里保留 30 天，之后永久删除。",
  },
} as const;

const TRASH_RETENTION_DAYS = 30;

function trashDaysRemaining(memo: Memo): number {
  const start = Date.parse(memo.deleted_at ?? memo.updated_at);
  if (Number.isNaN(start)) {
    return 0;
  }
  const remainingMs =
    TRASH_RETENTION_DAYS * 24 * 60 * 60 * 1000 - (Date.now() - start);
  return Math.max(0, Math.ceil(remainingMs / (24 * 60 * 60 * 1000)));
}

function describeError(error: unknown): string {
  if (error instanceof ApiError && error.status === 409) {
    return "内容已在其他设备更新，请处理编辑冲突后再保存。";
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "操作失败，请稍后重试。";
}

function readWebMentionQuery(value: string): string | null {
  const match = value.match(/(^|\s)@([^\s]*)$/);
  return match ? match[2] : null;
}

function tabMatchesMentionQuery(tab: BrowserOpenTab, query: string): boolean {
  const needle = query.trim().toLowerCase();
  if (!needle) {
    return true;
  }
  return (
    tab.page_title.toLowerCase().includes(needle) ||
    tab.page_url.toLowerCase().includes(needle) ||
    sourceHost(tab.page_url).toLowerCase().includes(needle)
  );
}

function highlightMentionMatch(text: string, query: string): ReactNode {
  const needle = query.trim();
  if (!needle) {
    return text;
  }
  const index = text.toLowerCase().indexOf(needle.toLowerCase());
  if (index < 0) {
    return text;
  }
  return (
    <>
      {text.slice(0, index)}
      <mark className="capture-command-mark">
        {text.slice(index, index + needle.length)}
      </mark>
      {text.slice(index + needle.length)}
    </>
  );
}

// 判断地址是否为 MemoIsle 本站页面，一键收藏时需跳过自身标签页。
function isMemoIslePageUrl(rawUrl: string): boolean {
  try {
    return new URL(rawUrl).origin === window.location.origin;
  } catch {
    return false;
  }
}

function formatImageBytes(bytes: number | null): string {
  if (!bytes || bytes <= 0) {
    return "";
  }
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${Math.round(bytes / 1024)} KB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function imageDimensionLabel(memo: Memo): string {
  if (memo.image_width && memo.image_height) {
    return `${memo.image_width} × ${memo.image_height}`;
  }
  return "尺寸未知";
}

function imageInfoLabel(memo: Memo): string {
  if (!memo.image_mime_type) {
    return "尚未上传图片文件";
  }
  const parts = [
    imageDimensionLabel(memo),
    formatImageBytes(memo.image_size_bytes),
    memo.image_mime_type.replace("image/", "").toUpperCase(),
  ].filter((part) => part.length > 0);
  return parts.join(" · ");
}

function imageOcrSourceLabel(source: ImageOcrSource | null): string {
  if (source === "local") {
    return "本地识别";
  }
  if (source === "llm") {
    return "视觉模型";
  }
  return "";
}

function imageFileTitle(file: File | Blob): string {
  const rawName = file instanceof File ? file.name : "";
  const base = rawName.replace(/\.[^.]+$/, "").trim();
  return base || "粘贴的图片";
}

function imageMimeFromFile(file: File): string {
  if (file.type.startsWith("image/")) {
    return file.type;
  }
  const extension = file.name.toLowerCase().split(".").pop() ?? "";
  switch (extension) {
    case "png":
      return "image/png";
    case "jpg":
    case "jpeg":
      return "image/jpeg";
    case "webp":
      return "image/webp";
    case "gif":
      return "image/gif";
    default:
      return "";
  }
}

function imageFileExtension(mimeType: string | null): string {
  switch (mimeType) {
    case "image/png":
      return "png";
    case "image/jpeg":
      return "jpg";
    case "image/webp":
      return "webp";
    case "image/gif":
      return "gif";
    default:
      return "image";
  }
}

function isImageFile(file: File): boolean {
  return file.type.startsWith("image/") || imageMimeFromFile(file) !== "";
}

// 图片接口需要 Bearer 头，缩略图通过组件内的对象 URL 读取，卸载时释放。
function MemoImageThumb({
  memoId,
  version,
  alt,
  className,
}: {
  memoId: string;
  version: number;
  alt: string;
  className?: string;
}) {
  const [url, setUrl] = useState("");
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    let objectUrl: string | null = null;
    setUrl("");
    setFailed(false);
    void loadMemoImageUrl(memoId, "thumbnail")
      .then((next) => {
        if (!active) {
          URL.revokeObjectURL(next);
          return;
        }
        objectUrl = next;
        setUrl(next);
      })
      .catch(() => {
        if (active) {
          setFailed(true);
        }
      });
    return () => {
      active = false;
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
      }
    };
  }, [memoId, version]);

  if (failed) {
    return <span className="image-thumb-fallback" aria-hidden="true">▧</span>;
  }
  if (!url) {
    return <span className="image-thumb-loading" aria-hidden="true" />;
  }
  return <img className={className ?? "image-thumb"} src={url} alt={alt} />;
}

function resourceRowElements(): HTMLElement[] {
  return Array.from(document.querySelectorAll<HTMLElement>(".memo-list .memo-row[data-memo-id]"));
}

export default function App({ authUser, onLogout }: AppProps) {
  const [activeType, setActiveType] = useState<ActiveView>("all");
  const [memos, setMemos] = useState<Memo[]>([]);
  const [currentResultCount, setCurrentResultCount] = useState(0);
  const [trashTotalCount, setTrashTotalCount] = useState(0);
  const [trashBulkAction, setTrashBulkAction] = useState<"restore" | "empty" | null>(null);
  const trashBulkBusyRef = useRef(false);
  const [memoCounts, setMemoCounts] = useState<MemoCounts | null>(null);
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [message, setMessage] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  // 网页收藏有自己的搜索框，输入时留在当前视图，不再跳回「全部」。
  const [resourceQuery, setResourceQuery] = useState("");
  const [debouncedResourceQuery, setDebouncedResourceQuery] = useState("");
  const [resourceCategoryFilter, setResourceCategoryFilter] = useState<
    ResourceCategory | ""
  >("");
  const [resourceStarredOnly, setResourceStarredOnly] = useState(false);
  const [imageCategoryFilter, setImageCategoryFilter] = useState("");
  const [resourcePage, setResourcePage] = useState(1);
  const [pageSize, setPageSize] = useState(RESOURCE_PAGE_SIZE);
  const [batchSelection, setBatchSelection] = useState<Map<string, Memo>>(new Map());
  const [batchBusy, setBatchBusy] = useState(false);
  const [memoSort, setMemoSort] = useState<MemoSort>("updated_desc");
  const [quickAccessItems, setQuickAccessItems] = useState<Memo[]>([]);
  const [quickAccessLoaded, setQuickAccessLoaded] = useState(false);
  // 撤销按钮只跟随对应的那条提示，提示被替换后自动失效。
  const [quickAccessUndo, setQuickAccessUndo] = useState<{ memo: Memo; message: string } | null>(null);
  const [resourceViewMode, setResourceViewMode] =
    useState<ResourceViewMode>("list");
  const [resourceCategories, setResourceCategories] = useState(
    defaultResourceCategories,
  );
  const [categoryRules, setCategoryRules] = useState<ResourceCategoryRule[]>([]);
  const [categorySettingsOpen, setCategorySettingsOpen] = useState(false);
  const [categorySettingsLoading, setCategorySettingsLoading] = useState(false);
  const categorySettingsRef = useRef<HTMLElement>(null);
  const [bookmarkImportOpen, setBookmarkImportOpen] = useState(false);
  const [cloudAccountOpen, setCloudAccountOpen] = useState(false);
  const [modelSettingsOpen, setModelSettingsOpen] = useState(false);
  const [ebookCollectOpen, setEbookCollectOpen] = useState(false);
  const [healthCenterOpen, setHealthCenterOpen] = useState(false);
  const [healthIssueCount, setHealthIssueCount] = useState(0);
  const [reviewQueue, setReviewQueue] = useState<ReviewQueueResponse | null>(null);
  const [reviewFilter, setReviewFilter] = useState<ReviewQueueFilter>("all");
  const [reviewBusy, setReviewBusy] = useState(false);
  const [reviewSettings, setReviewSettings] = useState<ReviewSettings | null>(null);
  const [reviewSettingsBusy, setReviewSettingsBusy] = useState(false);
  const [undoMemo, setUndoMemo] = useState<Memo | null>(null);
  const [wordLookup, setWordLookup] = useState<WordLookupResponse | null>(null);
  const [wordLookupSelection, setWordLookupSelection] = useState<number[]>([]);
  const [wordLookupBusy, setWordLookupBusy] = useState(false);
  const [duplicateWord, setDuplicateWord] = useState<Memo | null>(null);
  const [duplicateResource, setDuplicateResource] = useState<Memo | null>(null);
  const [pendingResource, setPendingResource] = useState<PendingResource | null>(null);
  const [dismissedSuggestionKey, setDismissedSuggestionKey] = useState("");
  const [newBody, setNewBody] = useState("");
  const [newUrl, setNewUrl] = useState("");
  const [newTitle, setNewTitle] = useState("");
  const [newPhonetic, setNewPhonetic] = useState("");
  const [newExample, setNewExample] = useState("");
  const [pendingWord, setPendingWord] = useState<{
    title: string;
    meaning: string;
    phonetic: string;
    example: string;
  } | null>(null);
  const [webAttachment, setWebAttachment] = useState<
    BrowserCaptureContext | BrowserOpenTab | null
  >(null);
  const [openBrowserTabs, setOpenBrowserTabs] = useState<BrowserOpenTab[]>([]);
  const [openBrowserTabsLoading, setOpenBrowserTabsLoading] = useState(false);
  const [openBrowserTabsError, setOpenBrowserTabsError] = useState<string | null>(
    null,
  );
  const [webAttachmentHelp, setWebAttachmentHelp] = useState(false);
  const [webCommandOpen, setWebCommandOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [isExporting, setIsExporting] = useState(false);
  const [isImporting, setIsImporting] = useState(false);
  const [updatingResourceId, setUpdatingResourceId] = useState<string | null>(null);
  const [typeChangingId, setTypeChangingId] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [resourcePreviewMemo, setResourcePreviewMemo] = useState<Memo | null>(null);
  const [resourcePreviewEditing, setResourcePreviewEditing] = useState(false);
  const [shortcutHelpOpen, setShortcutHelpOpen] = useState(false);
  // 密码库是独立页面，不属于任何内容类型；切换到任何内容视图都会离开它。
  const [vaultOpen, setVaultOpen] = useState(false);
  const vaultReminderCount = useVaultReminderCount();
  const vaultOpenRef = useRef(vaultOpen);
  vaultOpenRef.current = vaultOpen;
  // 登录失效或切换账号时整个工作台卸载，库密钥不能留给下一个账号。
  useEffect(() => () => lockVaultSession(), []);
  // 列表在数据刷新或弹窗关闭后要恢复焦点的行；"first" 表示新页面的第一行。
  const pendingRowFocusRef = useRef<string[] | "first" | null>(null);
  const previewReturnIdRef = useRef<string[] | null>(null);
  const resourceListKeyRef = useRef<(event: KeyboardEvent) => boolean>(() => false);
  const [classificationToolsOpen, setClassificationToolsOpen] = useState(false);
  const [classificationReviewCount, setClassificationReviewCount] = useState(0);
  const [editorTitle, setEditorTitle] = useState("");
  const [editorBody, setEditorBody] = useState("");
  const [editorPhonetic, setEditorPhonetic] = useState("");
  const [editorExample, setEditorExample] = useState("");
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [conflictMemo, setConflictMemo] = useState<Memo | null>(null);
  const [showWordAnswer, setShowWordAnswer] = useState(false);
  const [reviewing, setReviewing] = useState(false);
  const [voicePanelOpen, setVoicePanelOpen] = useState(false);
  const [voiceState, setVoiceState] = useState<VoiceState>("idle");
  const [voiceSeconds, setVoiceSeconds] = useState(0);
  const [voiceVolume, setVoiceVolume] = useState(0);
  const [voiceText, setVoiceText] = useState("");
  const [voiceTranscriptionMessage, setVoiceTranscriptionMessage] = useState("");
  const [voiceBlob, setVoiceBlob] = useState<Blob | null>(null);
  const [voiceDraftMemo, setVoiceDraftMemo] = useState<Memo | null>(null);
  const [voiceDiscardConfirmOpen, setVoiceDiscardConfirmOpen] = useState(false);
  const [audioUrl, setAudioUrl] = useState("");
  const [imageUploadTasks, setImageUploadTasks] = useState<ImageUploadTask[]>([]);
  const [imageDragActive, setImageDragActive] = useState(false);
  const [imagePreviewUrl, setImagePreviewUrl] = useState("");
  const [imageFullUrl, setImageFullUrl] = useState("");
  const [imagePreviewFailed, setImagePreviewFailed] = useState(false);
  const [imagePreviewBusy, setImagePreviewBusy] = useState(false);
  const [replaceImageBusy, setReplaceImageBusy] = useState(false);
  const [ocrBusy, setOcrBusy] = useState(false);
  const [ocrError, setOcrError] = useState("");
  const reviewDueCount = reviewQueue
    ? reviewQueue.word_count + reviewQueue.resource_count + reviewQueue.idea_count
    : 0;
  const reviewScheduledCount = reviewQueue?.scheduled_count ?? reviewDueCount;
  const storedCaptureDrafts = useMemo(
    () => loadCaptureDrafts(authUser.id),
    [authUser.id],
  );
  const captureRef = useRef<HTMLTextAreaElement>(null);
  const quickSaveBusyRef = useRef(false);
  const quickSaveRecentPageRef = useRef<() => void>(() => undefined);
  const urlRef = useRef<HTMLInputElement>(null);
  const wordRef = useRef<HTMLInputElement>(null);
  const wordImportInputRef = useRef<HTMLInputElement>(null);
  const libraryImportInputRef = useRef<HTMLInputElement>(null);
  const imageInputRef = useRef<HTMLInputElement>(null);
  const imageReplaceInputRef = useRef<HTMLInputElement>(null);
  const imageUploadChainRef = useRef<Promise<void>>(Promise.resolve());
  const wordLookupRequestRef = useRef(0);
  const autoFilledWordRef = useRef({
    lemma: "",
    phonetic: "",
    meaning: "",
    example: "",
  });
  const wordDraftRef = useRef({
    phonetic: "",
    meaning: "",
    example: "",
  });
  wordDraftRef.current = {
    phonetic: newPhonetic,
    meaning: newBody,
    example: newExample,
  };
  const captureFieldsRef = useRef({
    title: "",
    body: "",
    url: "",
    phonetic: "",
    example: "",
  });
  captureFieldsRef.current = {
    title: newTitle,
    body: newBody,
    url: newUrl,
    phonetic: newPhonetic,
    example: newExample,
  };
  const captureDraftsRef = useRef<CaptureDrafts>(storedCaptureDrafts);
  const activeTypeRef = useRef(activeType);
  activeTypeRef.current = activeType;
  const searchRef = useRef<HTMLInputElement>(null);
  const resourceSearchRef = useRef<HTMLInputElement>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const voiceChunksRef = useRef<Blob[]>([]);
  const voiceStartedAtRef = useRef(0);
  const voiceTimerRef = useRef<number | null>(null);
  const voicePausedAtRef = useRef<number | null>(null);
  const voicePausedTotalMsRef = useRef(0);
  const voiceDiscardingRef = useRef(false);
  const voiceCaptureGenerationRef = useRef(0);
  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const volumeAnimationRef = useRef<number | null>(null);
  const speechRecognitionRef = useRef<BrowserSpeechRecognitionController | null>(null);
  const voiceTranscriptionActiveRef = useRef(false);
  const voiceTranscriptionStartedRef = useRef(false);
  const voiceAutomaticTextRef = useRef("");
  const recognitionBaseTextRef = useRef("");
  const loadRequestRef = useRef(0);
  const captureTokenHandledRef = useRef<string | null>(null);

  const stopVoiceVolumeMonitor = () => {
    if (volumeAnimationRef.current !== null) {
      window.cancelAnimationFrame(volumeAnimationRef.current);
      volumeAnimationRef.current = null;
    }
    analyserRef.current = null;
    const audioContext = audioContextRef.current;
    audioContextRef.current = null;
    if (audioContext) {
      void audioContext.close().catch(() => undefined);
    }
    setVoiceVolume(0);
  };

  const startVoiceVolumeMonitor = (stream: MediaStream) => {
    const audioContextConstructor =
      window.AudioContext ??
      (window as Window & { webkitAudioContext?: typeof AudioContext })
        .webkitAudioContext;
    if (!audioContextConstructor) {
      return;
    }
    try {
      const audioContext = new audioContextConstructor();
      const analyser = audioContext.createAnalyser();
      analyser.fftSize = 256;
      const source = audioContext.createMediaStreamSource(stream);
      source.connect(analyser);
      const samples = new Uint8Array(analyser.fftSize);
      audioContextRef.current = audioContext;
      analyserRef.current = analyser;
      const updateVolume = () => {
        analyser.getByteTimeDomainData(samples);
        let sumSquares = 0;
        for (const sample of samples) {
          const normalized = (sample - 128) / 128;
          sumSquares += normalized * normalized;
        }
        const rms = Math.sqrt(sumSquares / samples.length);
        // 放大低音量输入，保留 0-100 的简单、易懂反馈。
        setVoiceVolume(Math.min(100, Math.round(rms * 180)));
        volumeAnimationRef.current = window.requestAnimationFrame(updateVolume);
      };
      if (audioContext.state === "suspended") {
        void audioContext.resume();
      }
      volumeAnimationRef.current = window.requestAnimationFrame(updateVolume);
    } catch {
      // 音量监测失败不应阻塞录音本身。
      stopVoiceVolumeMonitor();
    }
  };

  const activeVoiceElapsedMs = () => {
    const endAt = voicePausedAtRef.current ?? Date.now();
    return Math.max(
      0,
      endAt - voiceStartedAtRef.current - voicePausedTotalMsRef.current,
    );
  };

  const updateVoiceElapsed = () => {
    setVoiceSeconds(Math.floor(activeVoiceElapsedMs() / 1_000));
  };

  const copy = viewCopy[activeType];
  // 网页收藏使用视图内搜索框，其他视图沿用顶部搜索框。
  const viewQuery = activeType === "resource" ? resourceQuery : searchQuery;
  const resourcePageCount = Math.max(
    1,
    Math.ceil(currentResultCount / pageSize),
  );

  const selectedMemo = useMemo(
    () => memos.find((memo) => memo.id === selectedId) ?? null,
    [memos, selectedId],
  );
  const selectedCopy = selectedMemo ? viewCopy[selectedMemo.type] : copy;
  const captureTypeSuggestion = useMemo<CaptureTypeSuggestion | null>(
    () => suggestCaptureType({ title: newTitle, body: newBody, url: newUrl }),
    [newBody, newTitle, newUrl],
  );

  useEffect(() => {
    if (!selectedMemo || selectedMemo.type === "resource") {
      return;
    }
    const serverBody = selectedMemo.type === "word"
      ? selectedMemo.word_meaning ?? selectedMemo.body
      : selectedMemo.body;
    const unchanged =
      editorTitle === selectedMemo.title &&
      editorBody === serverBody &&
      editorPhonetic === (selectedMemo.word_phonetic ?? "") &&
      editorExample === (selectedMemo.word_example ?? "");
    const timer = window.setTimeout(() => {
      if (unchanged) {
        clearEditorDraft(authUser.id, selectedMemo.id);
        return;
      }
      saveEditorDraft(authUser.id, selectedMemo.id, {
        title: editorTitle,
        body: editorBody,
        phonetic: editorPhonetic,
        example: editorExample,
        baseVersion: selectedMemo.version,
        updatedAt: new Date().toISOString(),
      });
    }, 150);
    return () => window.clearTimeout(timer);
  }, [
    authUser.id,
    editorBody,
    editorExample,
    editorPhonetic,
    editorTitle,
    selectedMemo,
  ]);

  useEffect(() => {
    let active = true;
    let objectUrl: string | null = null;
    if (!selectedMemo?.audio_mime_type) {
      setAudioUrl("");
      return;
    }

    // 录音接口需要 Bearer 头，因此先读取 Blob 再生成对象 URL。
    void loadMemoAudioUrl(selectedMemo.id)
      .then((url) => {
        if (!active) {
          URL.revokeObjectURL(url);
          return;
        }
        objectUrl = url;
        setAudioUrl(url);
      })
      .catch(() => {
        if (active) {
          setAudioUrl("");
        }
      });
    return () => {
      active = false;
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
      }
    };
  }, [
    selectedMemo?.audio_mime_type,
    selectedMemo?.id,
    selectedMemo?.version,
  ]);

  useEffect(() => {
    let active = true;
    let objectUrl: string | null = null;
    setImageFullUrl("");
    setImagePreviewFailed(false);
    if (!selectedMemo || selectedMemo.type !== "image" || !selectedMemo.image_mime_type) {
      setImagePreviewUrl("");
      return;
    }
    setImagePreviewUrl("");
    setImagePreviewBusy(true);
    // 详情先展示缩略图，原图在用户点击“查看原图”时再按需读取。
    void loadMemoImageUrl(selectedMemo.id, "thumbnail")
      .then((url) => {
        if (!active) {
          URL.revokeObjectURL(url);
          return;
        }
        objectUrl = url;
        setImagePreviewUrl(url);
      })
      .catch(() => {
        if (active) {
          setImagePreviewUrl("");
        }
      })
      .finally(() => {
        if (active) {
          setImagePreviewBusy(false);
        }
      });
    return () => {
      active = false;
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
      }
    };
  }, [
    selectedMemo?.id,
    selectedMemo?.image_mime_type,
    selectedMemo?.version,
    selectedMemo?.type,
  ]);

  useEffect(() => {
    // 原图对象 URL 替换或卸载时释放，避免内存泄漏。
    return () => {
      if (imageFullUrl) {
        URL.revokeObjectURL(imageFullUrl);
      }
    };
  }, [imageFullUrl]);

  useEffect(() => {
    setOcrError("");
  }, [selectedId]);

  useEffect(() => {
    // 上传/替换后 OCR 在后台执行，轮询选中条目直到拿到结果。
    const ocrStatus = selectedMemo?.image_ocr_status;
    if (
      !selectedMemo ||
      selectedMemo.type !== "image" ||
      (ocrStatus !== "pending" && ocrStatus !== "processing")
    ) {
      return;
    }
    const memoId = selectedMemo.id;
    let active = true;
    let attempts = 0;
    let timer: number | null = null;
    const poll = async () => {
      attempts += 1;
      try {
        const latest = await getMemo(memoId);
        if (!active) {
          return;
        }
        setMemos((current) =>
          current.map((memo) => (memo.id === latest.id ? latest : memo)),
        );
        if (
          (latest.image_ocr_status === "pending" ||
            latest.image_ocr_status === "processing") &&
          attempts < IMAGE_OCR_POLL_MAX_ATTEMPTS
        ) {
          timer = window.setTimeout(
            () => void poll(),
            IMAGE_OCR_POLL_INTERVAL_MS,
          );
        }
      } catch {
        // 轮询失败时保留现有状态，避免打断浏览。
      }
    };
    timer = window.setTimeout(() => void poll(), IMAGE_OCR_POLL_INTERVAL_MS);
    return () => {
      active = false;
      if (timer !== null) {
        window.clearTimeout(timer);
      }
    };
  }, [selectedMemo?.id, selectedMemo?.image_ocr_status]);

  const refreshHealthSummary = useCallback(async () => {
    try {
      const center = await getLinkHealthCenter();
      setHealthIssueCount(pendingHealthIssueCount(center.counts));
    } catch {
      // 巡检摘要失败不应阻断资料库主体读取。
    }
  }, []);

  const refreshMemoCounts = useCallback(async () => {
    try {
      setMemoCounts(await getMemoCounts());
    } catch {
      // 数量摘要失败不应阻断最近内容列表。
    }
  }, []);

  const loadQuickAccess = useCallback(async () => {
    try {
      setQuickAccessItems(await listQuickAccess(8));
      setQuickAccessLoaded(true);
    } catch {
      // 快速访问只是入口，读取失败时保留上次结果。
    }
  }, []);

  // 打开原网页后计数；本地列表立即更新，快速访问重新排序。
  const handleResourceOpened = useCallback((memo: Memo) => {
    if (memo.type !== "resource") return;
    void recordResourceOpen(memo.id)
      .then((stats) => {
        const patch = (item: Memo) => (item.id === memo.id ? { ...item, ...stats } : item);
        setMemos((current) => current.map(patch));
        setResourcePreviewMemo((current) => (current ? patch(current) : current));
        void loadQuickAccess();
      })
      .catch(() => {
        // 计数失败不影响打开网页本身；条目可能已删除，刷新入口。
        void loadQuickAccess();
      });
  }, [loadQuickAccess]);

  const changeQuickAccessHidden = useCallback(async (memo: Memo, hidden: boolean) => {
    const patch = (item: Memo) => (
      item.id === memo.id ? { ...item, resource_quick_access_hidden: hidden } : item
    );
    if (hidden) {
      // 先从界面移走，失败再放回。
      setQuickAccessItems((current) => current.filter((item) => item.id !== memo.id));
    }
    try {
      await setQuickAccessHidden(memo.id, hidden);
      setMemos((current) => current.map(patch));
      setResourcePreviewMemo((current) => (current ? patch(current) : current));
      setUndoMemo(null);
      if (hidden) {
        const text = `已从快速访问移除「${memo.title}」，仍会继续记录打开次数。`;
        setMessage(text);
        setQuickAccessUndo({ memo, message: text });
      } else {
        setMessage(`「${memo.title}」已重新显示在快速访问。`);
        setQuickAccessUndo(null);
      }
    } catch (error) {
      setMessage(describeError(error));
    } finally {
      void loadQuickAccess();
    }
  }, [loadQuickAccess]);

  const loadReviewQueue = useCallback(async (filter: ReviewQueueFilter = reviewFilter) => {
    try {
      setReviewQueue(
        await getReviewQueue({
          type: filter === "all" ? undefined : filter,
        }),
      );
    } catch (error) {
      setMessage(describeError(error));
    }
  }, [reviewFilter]);

  const handleSaveReviewSettings = async (
    dailyLimit: number,
    intervalsDays: number[],
  ): Promise<void> => {
    setReviewSettingsBusy(true);
    try {
      const updated = await updateReviewSettings({
        daily_limit: dailyLimit,
        intervals_days: intervalsDays,
      });
      setReviewSettings(updated);
      await loadReviewQueue(reviewFilter);
      setMessage("复习计划已更新，今日队列已按新上限刷新。");
    } catch (error) {
      setMessage(describeError(error));
    } finally {
      setReviewSettingsBusy(false);
    }
  };

  const refreshCategorySettings = useCallback(async () => {
    setCategorySettingsLoading(true);
    try {
      const [categories, rules] = await Promise.all([
        getResourceCategories(),
        getResourceCategoryRules(),
      ]);
      setResourceCategories(categories);
      setCategoryRules(rules);
    } catch (error) {
      setMessage(describeError(error));
    } finally {
      setCategorySettingsLoading(false);
    }
  }, []);

  const refreshOpenBrowserTabs = useCallback(async (showLoading = true) => {
    if (showLoading) {
      setOpenBrowserTabsLoading(true);
    }
    try {
      const tabs = await listOpenBrowserTabs();
      setOpenBrowserTabs(tabs);
      setOpenBrowserTabsError(null);
    } catch (error) {
      setOpenBrowserTabsError(describeError(error));
      if (showLoading) {
        setOpenBrowserTabs([]);
      }
    } finally {
      if (showLoading) {
        setOpenBrowserTabsLoading(false);
      }
    }
  }, []);

  const fillWordFromClipboard = useCallback(async (options?: {
    overwrite?: boolean;
    silent?: boolean;
  }) => {
    const overwrite = options?.overwrite ?? false;
    const silent = options?.silent ?? true;
    if (!overwrite && newTitle.trim()) {
      return false;
    }
    if (!navigator.clipboard?.readText) {
      if (!silent) {
        setMessage("当前浏览器不能读取剪贴板，请直接粘贴单词。");
      }
      return false;
    }
    try {
      const draft = parseClipboardWord(await navigator.clipboard.readText());
      if (!draft) {
        if (!silent) {
          setMessage("剪贴板里没有可收藏的英语单词。");
        }
        return false;
      }
      setNewTitle((current) =>
        overwrite || !current.trim() ? draft.lemma : current,
      );
      if (draft.phonetic) {
        setNewPhonetic((current) =>
          overwrite || !current.trim() ? draft.phonetic ?? current : current,
        );
      }
      if (draft.meaning) {
        setNewBody((current) =>
          overwrite || !current.trim() ? draft.meaning ?? current : current,
        );
      }
      if (draft.example) {
        setNewExample((current) =>
          overwrite || !current.trim() ? draft.example ?? current : current,
        );
      }
      setMessage(`已从剪贴板填入「${draft.lemma}」，确认后保存。`);
      return true;
    } catch {
      if (!silent) {
        setMessage("无法读取剪贴板，请允许访问或直接粘贴单词。");
      }
      return false;
    }
  }, [newTitle]);

  const clearWordLookup = () => {
    wordLookupRequestRef.current += 1;
    setWordLookup(null);
    setWordLookupSelection([]);
    setWordLookupBusy(false);
  };

  const persistCaptureDraft = (type: ActiveView) => {
    if (!isCaptureType(type)) {
      return;
    }
    const fields = captureFieldsRef.current;
    const draft = { ...fields };
    captureDraftsRef.current[type] = draft;
    saveCaptureDraft(authUser.id, type, draft);
  };

  const loadCaptureDraft = (type: ActiveView) => {
    if (type === "idea") {
      setNewBody(captureDraftsRef.current.idea.body);
      setNewTitle("");
      setNewUrl("");
      setNewPhonetic("");
      setNewExample("");
      return;
    }
    if (type === "word") {
      const draft = captureDraftsRef.current.word;
      setNewTitle(draft.title);
      setNewPhonetic(draft.phonetic);
      setNewBody(draft.body);
      setNewExample(draft.example);
      setNewUrl("");
      return;
    }
    if (type === "resource") {
      const draft = captureDraftsRef.current.resource;
      setNewUrl(draft.url);
      setNewTitle(draft.title);
      setNewBody(draft.body);
      setNewPhonetic("");
      setNewExample("");
      return;
    }
    setNewTitle("");
    setNewBody("");
    setNewUrl("");
    setNewPhonetic("");
    setNewExample("");
  };

  useEffect(() => {
    if (!isCaptureType(activeType)) {
      return;
    }
    const timer = window.setTimeout(() => {
      const draft = { ...captureFieldsRef.current };
      const hasContent = Object.values(draft).some((value) => value.trim());
      captureDraftsRef.current[activeType] = draft;
      if (hasContent) {
        saveCaptureDraft(authUser.id, activeType, draft);
      } else {
        clearCaptureDraft(authUser.id, activeType);
      }
    }, 150);
    return () => window.clearTimeout(timer);
  }, [
    activeType,
    authUser.id,
    newBody,
    newExample,
    newPhonetic,
    newTitle,
    newUrl,
  ]);

  const changeActiveType = (type: ActiveView, preserveCapture = false) => {
    setVaultOpen(false);
    if (type === activeType) {
      return;
    }
    persistCaptureDraft(activeType);
    if (!preserveCapture) {
      loadCaptureDraft(type);
    }
    if (type !== "word") {
      clearWordLookup();
    }
    setActiveType(type);
  };

  const formatLookupMeaning = (senses: WordLookupResponse["senses"]): string =>
    senses
      .slice(0, 4)
      .map((sense) =>
        sense.part_of_speech
          ? `${sense.part_of_speech}: ${sense.definition}`
          : sense.definition,
      )
      .join("\n");

  const applyDictionaryPreview = (
    preview: WordLookupResponse,
    selectedIndices?: number[],
  ): string[] => {
    const current = wordDraftRef.current;
    const selectedSenses =
      selectedIndices && selectedIndices.length > 0
        ? preview.senses.filter((sense) => selectedIndices.includes(sense.index))
        : preview.senses.slice(0, 4);
    const meaning = formatLookupMeaning(selectedSenses);
    const example =
      selectedSenses.find((sense) => sense.example?.trim())?.example?.trim() ??
      "";
    const phonetic = preview.phonetic?.trim() ?? "";
    if (activeTypeRef.current !== "word") {
      return [];
    }
    const filled: string[] = [];
    if (
      phonetic &&
      (!current.phonetic.trim() ||
        current.phonetic.trim() === autoFilledWordRef.current.phonetic)
    ) {
      filled.push("音标");
      autoFilledWordRef.current.phonetic = phonetic;
      setNewPhonetic(phonetic);
    }
    if (
      meaning &&
      (!current.meaning.trim() ||
        current.meaning.trim() === autoFilledWordRef.current.meaning)
    ) {
      filled.push("中文释义");
      autoFilledWordRef.current.meaning = meaning;
      setNewBody(meaning);
    }
    if (
      example &&
      (!current.example.trim() ||
        current.example.trim() === autoFilledWordRef.current.example)
    ) {
      filled.push("例句");
      autoFilledWordRef.current.example = example;
      setNewExample(example);
    }
    autoFilledWordRef.current.lemma = preview.lemma || preview.word;
    return filled;
  };

  const lookupWordAndMaybeApply = async (
    word: string,
    autoApply: boolean,
  ): Promise<void> => {
    if (!word || creating) {
      return;
    }
    if (autoApply && !parseClipboardWord(word)) {
      return;
    }
    const requestId = ++wordLookupRequestRef.current;
    setWordLookupBusy(true);
    if (!autoApply) {
      setWordLookup(null);
      setWordLookupSelection([]);
    }
    try {
      const preview = await lookupWord(word);
      if (
        requestId !== wordLookupRequestRef.current ||
        activeTypeRef.current !== "word"
      ) {
        return;
      }
      const filled = applyDictionaryPreview(
        preview,
        autoApply
          ? undefined
          : preview.senses.length > 0
            ? [preview.senses[0].index]
            : [],
      );
      if (autoApply) {
        if (filled.length > 0) {
          setMessage(`已自动填入${filled.join("、")}。`);
        }
        return;
      }
      setWordLookup(preview);
      setWordLookupSelection(
        preview.senses.length > 0 ? [preview.senses[0].index] : [],
      );
      setMessage(
        preview.senses.length > 0
          ? filled.length > 0
            ? `已自动填入${filled.join("、")}，也可继续选择其他释义。`
            : "已查到中文释义，请选择后使用。"
          : "词典没有返回中文释义，请手动填写。",
      );
    } catch (error) {
      if (!autoApply && requestId === wordLookupRequestRef.current) {
        setMessage(`查词失败：${describeError(error)}`);
      }
    } finally {
      if (requestId === wordLookupRequestRef.current) {
        setWordLookupBusy(false);
      }
    }
  };

  const handleLookupWord = async (): Promise<void> => {
    await lookupWordAndMaybeApply(newTitle.trim(), false);
  };

  const applyWordLookup = () => {
    if (!wordLookup || wordLookupSelection.length === 0) {
      return;
    }
    const filled = applyDictionaryPreview(wordLookup, wordLookupSelection);
    clearWordLookup();
    setMessage(
      filled.length > 0
        ? `已应用所选释义（${filled.join("、")}）；手工填写的内容已保留。`
        : "已保留手工填写的内容。",
    );
  };

  const applyCaptureTypeSuggestion = (suggestion: CaptureTypeSuggestion) => {
    const fields = captureFieldsRef.current;
    persistCaptureDraft(activeType);
    if (suggestion.type === "resource") {
      const extractedUrl = extractCaptureUrl(fields.url || fields.body);
      if (extractedUrl) {
        setNewUrl(extractedUrl);
      }
      setNewTitle(fields.title);
      setNewBody(fields.body);
      setNewPhonetic("");
      setNewExample("");
    } else if (suggestion.type === "word") {
      const wordDraft = parseClipboardWord(fields.title || fields.body);
      setNewTitle(wordDraft?.lemma ?? (fields.title || fields.body.trim()));
      setNewBody(wordDraft?.meaning ?? (fields.title ? fields.body : ""));
      setNewPhonetic(wordDraft?.phonetic ?? fields.phonetic);
      setNewExample(wordDraft?.example ?? fields.example);
      setNewUrl("");
    } else {
      setNewBody(fields.body || fields.title);
      setNewTitle(fields.title);
      setNewUrl("");
      setNewPhonetic("");
      setNewExample("");
    }
    changeActiveType(suggestion.type, true);
    setDismissedSuggestionKey(suggestion.key);
    setMessage(`已切换为${viewCopy[suggestion.type].itemLabel}，请确认后保存。`);
  };

  const enterWordCapture = () => {
    switchType("word");
    void fillWordFromClipboard({
      overwrite: false,
      silent: true,
    });
    window.setTimeout(() => wordRef.current?.focus(), 0);
  };

  const focusCapture = useCallback(() => {
    setVaultOpen(false);
    if (
      activeType === "all" ||
      activeType === "inbox" ||
      activeType === "review" ||
      activeType === "trash"
    ) {
      changeActiveType("idea");
      setSearchQuery("");
      setDebouncedQuery("");
      window.setTimeout(() => captureRef.current?.focus(), 0);
      return;
    }
    if (activeType === "resource") {
      urlRef.current?.focus();
    } else if (activeType === "word") {
      void fillWordFromClipboard({ silent: true });
      wordRef.current?.focus();
    } else if (activeType === "image") {
      imageInputRef.current?.click();
    } else {
      captureRef.current?.focus();
    }
  }, [activeType, fillWordFromClipboard]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebouncedQuery(searchQuery.trim());
    }, 250);
    return () => window.clearTimeout(timer);
  }, [searchQuery]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebouncedResourceQuery(resourceQuery.trim());
    }, 250);
    return () => window.clearTimeout(timer);
  }, [resourceQuery]);

  // 搜索条件变化后回到第一页，避免停留在越界页码上看到空结果。
  useEffect(() => {
    setResourcePage(1);
  }, [debouncedResourceQuery]);

  useEffect(() => {
    if (activeType !== "word") {
      return;
    }
    const word = newTitle.trim();
    if (!parseClipboardWord(word)) {
      return;
    }
    const timer = window.setTimeout(() => {
      void lookupWordAndMaybeApply(word, true);
    }, 450);
    return () => {
      window.clearTimeout(timer);
      wordLookupRequestRef.current += 1;
      setWordLookupBusy(false);
    };
  }, [activeType, newTitle]);

  useEffect(() => {
    void refreshHealthSummary();
    const timer = window.setInterval(() => void refreshHealthSummary(), 60_000);
    return () => window.clearInterval(timer);
  }, [refreshHealthSummary]);

  useEffect(() => {
    void refreshMemoCounts();
  }, [refreshMemoCounts]);

  useEffect(() => {
    if (activeType === "resource") {
      void refreshCategorySettings();
    }
  }, [activeType, refreshCategorySettings]);

  useEffect(() => {
    if (!categorySettingsOpen) {
      return;
    }
    categorySettingsRef.current?.scrollIntoView({
      block: "nearest",
      behavior: "smooth",
    });
  }, [categorySettingsOpen]);

  useEffect(() => {
    if (!webCommandOpen) {
      return;
    }
    void refreshOpenBrowserTabs();
    const timer = window.setInterval(
      () => void refreshOpenBrowserTabs(false),
      5_000,
    );
    return () => window.clearInterval(timer);
  }, [webCommandOpen, refreshOpenBrowserTabs]);

  useEffect(() => {
    const currentUrl = new URL(window.location.href);
    const token = currentUrl.searchParams.get("memoisle_capture");
    const captureError = currentUrl.searchParams.get("memoisle_capture_error");
    const attemptedApiBaseUrl = currentUrl.searchParams.get("memoisle_capture_api");
    if (!token && !captureError) {
      return;
    }
    currentUrl.searchParams.delete("memoisle_capture");
    currentUrl.searchParams.delete("memoisle_capture_error");
    currentUrl.searchParams.delete("memoisle_capture_api");
    window.history.replaceState({}, "", currentUrl);
    changeActiveType("resource");
    setSelectedId(null);
    if (captureError) {
      const authenticationError = captureError === "not_authenticated";
      setWebAttachmentHelp(!authenticationError);
      setMessage(
        captureError === "unsupported_page"
          ? "当前页面不支持收藏，请在普通公网 HTTP(S) 网页使用扩展。"
          : captureError === "not_authenticated"
            ? "请先在 MemoIsle 中登录，扩展即可一键收藏当前网页。"
            : captureError === "capture_failed"
              ? "网页收藏失败，请稍后重试，也可以粘贴网址或输入 @ 选择网页后保存。"
            : `扩展暂时无法连接 MemoIsle${
                attemptedApiBaseUrl ? `（已尝试 ${attemptedApiBaseUrl}）` : ""
              }，请确认后端已启动，并刷新本页让扩展同步当前地址。`,
      );
      return;
    }
    if (!token || captureTokenHandledRef.current === token) {
      return;
    }
    captureTokenHandledRef.current = token;
    void exchangeBrowserCapture(token)
      .then((capture) => {
        setWebAttachment(capture);
        setWebAttachmentHelp(false);
        setNewUrl(capture.page_url);
        setNewTitle(capture.page_title);
        setMessage("已附加当前网页；输入 @ 可从当前浏览器的其他打开网页中选择。");
        void refreshOpenBrowserTabs();
      })
      .catch((captureExchangeError) => {
        setWebAttachmentHelp(true);
        setMessage(describeError(captureExchangeError));
      });
  }, [refreshOpenBrowserTabs]);

  const loadCurrentMemos = useCallback(async (showLoading = true) => {
    const requestId = ++loadRequestRef.current;
    if (activeType === "review") {
      if (showLoading) {
        setLoadState("loading");
      }
      try {
        const queue = await getReviewQueue({
          type: reviewFilter === "all" ? undefined : reviewFilter,
        });
        if (requestId !== loadRequestRef.current) {
          return;
        }
        setReviewQueue(queue);
        setLoadState("ready");
      } catch (error) {
        if (requestId !== loadRequestRef.current) {
          return;
        }
        if (showLoading) {
          setMessage(describeError(error));
          setLoadState("error");
        }
      }
      return;
    }
    if (showLoading) {
      setLoadState("loading");
    }
    try {
      const resourceView = activeType === "resource";
      const trashView = activeType === "trash";
      const inboxView = activeType === "inbox";
      const [response, allTrash] = await Promise.all([
        listMemos({
          type:
            activeType === "all" || trashView || inboxView ? undefined : activeType,
          query: resourceView ? debouncedResourceQuery : debouncedQuery,
          category: resourceView ? resourceCategoryFilter || undefined
            : activeType === "image" ? imageCategoryFilter || undefined : undefined,
          starred: resourceView && resourceStarredOnly ? true : undefined,
          status: trashView ? "trashed" : inboxView ? "inbox" : undefined,
          // 「最常打开」只对网页资料有意义，其他视图沿用默认排序。
          sort: memoSort === "opened_desc" && !resourceView ? "updated_desc" : memoSort,
          limit: pageSize,
          offset: (resourcePage - 1) * pageSize,
        }),
        // 一键回收站操作使用全量计数，选中条目操作另按当前页快照处理。
        trashView && debouncedQuery.trim()
          ? listMemos({ status: "trashed", limit: 1 })
          : Promise.resolve(null),
      ]);
      if (requestId !== loadRequestRef.current) {
        return;
      }
      setMemos(response.items);
      setCurrentResultCount(response.total_count);
      if (trashView) setTrashTotalCount(allTrash?.total_count ?? response.total_count);
      setLoadState("ready");
    } catch (error) {
      if (requestId !== loadRequestRef.current) {
        return;
      }
      // 静默轮询失败时保留现有内容，避免网络波动导致页面闪烁。
      if (showLoading) {
        setMessage(describeError(error));
        setLoadState("error");
      }
    }
  }, [
    activeType,
    debouncedQuery,
    debouncedResourceQuery,
    memoSort,
    resourceCategoryFilter,
    imageCategoryFilter,
    resourcePage,
    pageSize,
    resourceStarredOnly,
    reviewFilter,
  ]);

  const loadCurrentMemosRef = useRef(loadCurrentMemos);
  loadCurrentMemosRef.current = loadCurrentMemos;

  useEffect(() => {
    // 更改页面或筛选清除选择，轮询刷新保留用户所见版本以检测并发冲突。
    setBatchSelection(new Map());
  }, [loadCurrentMemos]);

  useEffect(() => { setResourcePage(1); }, [activeType, debouncedQuery]);

  const toggleBatchMemo = (memo: Memo): void => setBatchSelection((current) => {
    const updated = new Map(current);
    if (updated.has(memo.id)) updated.delete(memo.id); else updated.set(memo.id, memo);
    return updated;
  });

  useEffect(() => {
    setSelectedId(null);
    setMessage("");
    void loadCurrentMemos();
  }, [loadCurrentMemos]);

  useEffect(() => {
    let refreshTimer: number | null = null;
    const refreshOnReturn = (): void => {
      if (document.visibilityState !== "visible" || refreshTimer !== null) {
        return;
      }
      // 回到 Web 时刷新扩展新收藏的内容；合并同次切换触发的可见性与焦点事件。
      refreshTimer = window.setTimeout(() => {
        refreshTimer = null;
        void loadCurrentMemos(false);
        void refreshMemoCounts();
      }, 150);
    };
    window.addEventListener("focus", refreshOnReturn);
    document.addEventListener("visibilitychange", refreshOnReturn);
    return () => {
      window.removeEventListener("focus", refreshOnReturn);
      document.removeEventListener("visibilitychange", refreshOnReturn);
      if (refreshTimer !== null) {
        window.clearTimeout(refreshTimer);
      }
    };
  }, [loadCurrentMemos, refreshMemoCounts]);

  useEffect(() => {
    if (activeType === "all") {
      void loadReviewQueue();
    }
  }, [activeType, loadReviewQueue]);

  useEffect(() => {
    // 数量变化说明有条目新增、删除或恢复，快速访问跟着刷新。
    if (activeType === "all" || activeType === "resource") {
      void loadQuickAccess();
    }
  }, [activeType, memoCounts, loadQuickAccess]);

  useEffect(() => {
    let active = true;
    void getReviewSettings()
      .then((settings) => {
        if (active) {
          setReviewSettings(settings);
        }
      })
      .catch(() => {
        // 设置读取失败不应阻断内容浏览，队列接口仍会使用服务端默认值。
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (activeType === "review" || loadState !== "ready") {
      return;
    }
    setResourcePage((page) => Math.min(page, resourcePageCount));
  }, [activeType, loadState, resourcePageCount]);

  useEffect(() => {
    const hasPendingResource = memos.some(
      (memo) =>
        memo.type === "resource" &&
        ["pending", "processing"].includes(memo.resource_metadata_status),
    );
    if (!hasPendingResource) {
      return;
    }
    const timer = window.setTimeout(
      () => void loadCurrentMemos(false),
      5_000,
    );
    return () => window.clearTimeout(timer);
  }, [loadCurrentMemos, memos]);

  useEffect(() => {
    const handleShortcut = (event: KeyboardEvent) => {
      const quickBookmarkHotkey =
        (event.ctrlKey || event.metaKey) &&
        event.shiftKey &&
        event.altKey &&
        event.key.toLowerCase() === "b";
      if (quickBookmarkHotkey) {
        // 一键收藏最近浏览的网页，输入框内同样生效。
        event.preventDefault();
        quickSaveRecentPageRef.current?.();
        return;
      }
      const target = event.target as HTMLElement | null;
      const isEditing =
        target?.tagName === "INPUT" ||
        target?.tagName === "TEXTAREA" ||
        target?.tagName === "SELECT" ||
        Boolean(target?.isContentEditable);
      if (isEditing || event.ctrlKey || event.metaKey || event.altKey) {
        return;
      }
      // 弹窗打开时由弹窗自己处理按键。
      if (document.querySelector('[role="dialog"][aria-modal="true"]')) {
        return;
      }
      if (event.key === "?") {
        event.preventDefault();
        setShortcutHelpOpen(true);
        return;
      }
      // 密码库页面不响应内容列表的单键快捷键，避免误触。
      if (vaultOpenRef.current) {
        return;
      }
      if (activeTypeRef.current === "resource" && resourceListKeyRef.current(event)) {
        return;
      }
      if (event.key.toLowerCase() === "n") {
        event.preventDefault();
        focusCapture();
      }
      if (event.key === "/") {
        event.preventDefault();
        // 网页收藏视图优先聚焦自己的搜索框，避免被顶栏搜索带去「全部」。
        if (activeTypeRef.current === "resource") {
          resourceSearchRef.current?.focus();
          return;
        }
        searchRef.current?.focus();
      }
    };
    window.addEventListener("keydown", handleShortcut);
    return () => window.removeEventListener("keydown", handleShortcut);
  }, [focusCapture]);

  useEffect(() => {
    return () => {
      if (voiceTimerRef.current !== null) {
        window.clearInterval(voiceTimerRef.current);
      }
      stopVoiceVolumeMonitor();
      const recorder = recorderRef.current;
      if (recorder && recorder.state !== "inactive") {
        recorder.stop();
      }
      recorder?.stream.getTracks().forEach((track) => track.stop());
    };
  }, []);

  const switchType = (type: ActiveView, preserveCapture = false) => {
    changeActiveType(type, preserveCapture);
    setResourcePage(1);
    setSearchQuery("");
    setDebouncedQuery("");
    setSelectedId(null);
    setSaveState("idle");
    if (type !== "image") setImageCategoryFilter("");
    if (type !== "resource") {
      setResourceCategoryFilter("");
      setResourceStarredOnly(false);
    }
  };

  const handleSearchChange = (value: string) => {
    setSearchQuery(value);
    if (value.trim()) setVaultOpen(false);
    if (
      value.trim() &&
      activeType !== "all" &&
      activeType !== "trash" &&
      activeType !== "inbox"
    ) {
      changeActiveType("all");
      setResourceCategoryFilter("");
      setResourceStarredOnly(false);
      setSelectedId(null);
    }
  };

  const handleExport = async (format: DataExportFormat): Promise<void> => {
    if (isExporting || isImporting) {
      return;
    }
    setIsExporting(true);
    try {
      const blob = await downloadUserData(format);
      const objectUrl = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = objectUrl;
      anchor.download = `memoisle-export-${new Date().toISOString().slice(0, 10)}.${format === "markdown" ? "md" : format}`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 0);
      const formatLabel = format === "json" ? "JSON" : format === "csv" ? "CSV" : "Markdown";
      setMessage(`个人数据已导出为 ${formatLabel}，录音文件未打包。`);
    } catch (error) {
      setMessage(describeError(error));
    } finally {
      setIsExporting(false);
    }
  };

  const handleLibraryImport = async (file: File): Promise<void> => {
    if (isImporting || isExporting) {
      return;
    }
    if (file.name.toLowerCase().endsWith(".md")) {
      setMessage("Markdown 仅供阅读，完整恢复请使用 JSON 或 CSV 备份。");
      return;
    }
    setIsImporting(true);
    try {
      const result = await importLibraryData(file);
      await Promise.all([loadCurrentMemos(false), refreshMemoCounts()]);
      const errorPreview = result.errors
        .slice(0, 2)
        .map((error) => `第 ${error.row} 行：${error.message}`)
        .join("；");
      const suffix = errorPreview ? `；${errorPreview}` : "";
      setMessage(
        `备份导入完成：新增 ${result.imported_count}，重复 ${result.duplicate_count}，失败 ${result.failed_count}${suffix}`,
      );
    } catch (error) {
      setMessage(describeError(error));
    } finally {
      setIsImporting(false);
    }
  };

  const handleWordImport = async (file: File): Promise<void> => {
    if (isImporting || isExporting) {
      return;
    }
    setIsImporting(true);
    try {
      const result = await importWords(file);
      await Promise.all([loadCurrentMemos(false), refreshMemoCounts()]);
      const errorPreview = result.errors
        .slice(0, 2)
        .map((error) => `第 ${error.row} 行：${error.message}`)
        .join("；");
      const suffix = errorPreview ? `；${errorPreview}` : "";
      setMessage(
        `单词导入完成：新增 ${result.imported_count}，重复 ${result.duplicate_count}，跳过 ${result.skipped_count}，失败 ${result.failed_count}${suffix}`,
      );
    } catch (error) {
      setMessage(describeError(error));
    } finally {
      setIsImporting(false);
    }
  };

  const handleCaptureBodyChange = (value: string) => {
    setNewBody(value);
    setWebCommandOpen(
      activeType === "resource" && readWebMentionQuery(value) !== null,
    );
  };

  const webMentionQuery = readWebMentionQuery(newBody) ?? "";
  const matchedOpenBrowserTabs = useMemo(() => {
    return openBrowserTabs.filter((tab) =>
      tabMatchesMentionQuery(tab, webMentionQuery),
    );
  }, [openBrowserTabs, webMentionQuery]);

  const clearWebCommandMarker = () => {
    setNewBody((current) => current.replace(/(^|\s)@[^\s]*$/, "$1"));
    setWebCommandOpen(false);
  };

  const chooseOpenBrowserTab = (tab: BrowserOpenTab) => {
    clearWebCommandMarker();
    setWebAttachment(tab);
    setWebAttachmentHelp(false);
    setNewUrl(tab.page_url);
    setNewTitle(tab.page_title);
    setMessage("已附加当前浏览器中的网页，可以补充备注后保存。");
  };

  const showBrowserPageHelp = () => {
    clearWebCommandMarker();
    if (!webAttachment) {
      setWebAttachmentHelp(true);
    }
  };

  const removeWebAttachment = () => {
    if (webAttachment) {
      if (newUrl === webAttachment.page_url) {
        setNewUrl("");
      }
      if (newTitle === webAttachment.page_title) {
        setNewTitle("");
      }
    }
    setWebAttachment(null);
    setWebAttachmentHelp(false);
  };

  const selectMemo = (memo: Memo) => {
    if (memo.type === "resource") {
      return;
    }
    const savedDraft = loadEditorDraft(authUser.id, memo.id);
    const serverBody = memo.type === "word" ? memo.word_meaning ?? memo.body : memo.body;
    setSelectedId(memo.id);
    setEditorTitle(savedDraft?.title ?? memo.title);
    setEditorBody(savedDraft?.body ?? serverBody);
    setEditorPhonetic(savedDraft?.phonetic ?? memo.word_phonetic ?? "");
    setEditorExample(savedDraft?.example ?? memo.word_example ?? "");
    setConflictMemo(null);
    setShowWordAnswer(false);
    setSaveState("idle");
    setMessage(
      savedDraft
        ? savedDraft.baseVersion !== memo.version
          ? "已恢复基于旧版本的本地草稿，保存时会检查编辑冲突。"
          : "已恢复未提交的本地草稿。"
        : "",
    );
  };

  const handleCreate = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (
      creating ||
      activeType === "all" ||
      activeType === "review" ||
      activeType === "inbox" ||
      activeType === "trash"
    ) {
      return;
    }
    const body = newBody.trim();
    const sourceUrl = activeType === "resource" ? normalizeWebUrl(newUrl) : null;
    if (activeType === "idea" && !body) {
      return;
    }
    if (activeType === "word" && !newTitle.trim()) {
      setMessage("请输入要收藏的英语单词或短语。");
      wordRef.current?.focus();
      return;
    }
    if (activeType === "resource" && !sourceUrl) {
      setMessage("请输入有效的网址，例如 https://example.com/article。");
      urlRef.current?.focus();
      return;
    }

    setCreating(true);
    setMessage("");
    setDuplicateWord(null);
    setDuplicateResource(null);
    setPendingResource(null);
    const pendingResourceDraft: PendingResource | null =
      activeType === "resource" && sourceUrl
        ? {
            clientId: "",
            url: sourceUrl,
            title: newTitle.trim(),
            body: body || sourceUrl || newTitle.trim(),
          }
        : null;
    try {
      const clientId = crypto.randomUUID();
      if (pendingResourceDraft) {
        pendingResourceDraft.clientId = clientId;
      }
      const created = await createMemo({
        type: activeType,
        title: newTitle.trim() || undefined,
        body: body || sourceUrl || newTitle.trim(),
        source_url: sourceUrl ?? undefined,
        source_title:
          activeType === "resource" ? newTitle.trim() || undefined : undefined,
        word_phonetic:
          activeType === "word" ? newPhonetic.trim() || undefined : undefined,
        word_meaning: activeType === "word" ? body || undefined : undefined,
        word_example:
          activeType === "word" ? newExample.trim() || undefined : undefined,
        tags: [],
      }, clientId);
      const deduplicatedResource =
        activeType === "resource" && created.client_id !== clientId;
      setMemos((current) => [
        created,
        ...current.filter((memo) => memo.id !== created.id),
      ]);
      void refreshMemoCounts();
      void loadReviewQueue();
      setNewBody("");
      setNewUrl("");
      setNewTitle("");
      setNewPhonetic("");
      setNewExample("");
      clearWordLookup();
      setWebAttachment(null);
      setWebAttachmentHelp(false);
      setWebCommandOpen(false);
      setUndoMemo(deduplicatedResource ? null : created);
      setDuplicateResource(null);
      setPendingResource(null);
      selectMemo(created);
      setMessage(
        deduplicatedResource
          ? "该网址已经收藏，已定位到资料库中的原有条目。"
          : `${copy.itemLabel}已保存，并可在 Android 端同步。`,
      );
    } catch (error) {
      if (
        activeType === "word" &&
        error instanceof ApiError &&
        error.code === "duplicate_lemma" &&
        error.current
      ) {
        setDuplicateWord(error.current);
        setPendingWord({
          title: newTitle.trim(),
          meaning: body,
          phonetic: newPhonetic.trim(),
          example: newExample.trim(),
        });
        setMessage("已收藏相同词形，可以查看、合并例句或仍然保存。");
      } else if (
        activeType === "resource" &&
        error instanceof ApiError &&
        error.code === "duplicate_resource" &&
        error.current &&
        pendingResourceDraft
      ) {
        setDuplicateResource(error.current);
        setPendingResource(pendingResourceDraft);
        setMessage("已收藏相同网址，可以查看已有资料或仍然保存。");
      } else {
        setMessage(describeError(error));
      }
    } finally {
      setCreating(false);
    }
  };

  const quickSaveRecentPage = async () => {
    if (creating || quickSaveBusyRef.current) {
      return;
    }
    quickSaveBusyRef.current = true;
    // 跳到资料视图，清掉分页/搜索/分类过滤，确保新收藏的条目立即可见。
    const switchToResourceView = () => {
      switchType("resource");
      setResourceCategoryFilter("");
      setResourceStarredOnly(false);
    };
    // 切换视图会触发列表重载并清空提示，延迟一帧再写入消息以避免被清掉。
    const showMessageSoon = (text: string) => {
      window.setTimeout(() => setMessage(text), 150);
    };
    let pendingResourceDraft: PendingResource | null = null;
    try {
      const tabs = await listOpenBrowserTabs();
      // 列表按最近查看排序（last_seen_at 降序），跳过 MemoIsle 本站自身标签页。
      const target = tabs.find((tab) => !isMemoIslePageUrl(tab.page_url));
      if (!target) {
        switchToResourceView();
        setWebAttachmentHelp(true);
        showMessageSoon(
          tabs.length === 0
            ? "暂未读取到可收藏的网页，请打开普通公网网页后重试；若已打开，请检查扩展是否允许访问本站并刷新页面。"
            : "最近浏览的网页是 MemoIsle 本站页面，请先切到想收藏的网页再按快捷键。",
        );
        return;
      }
      const sourceUrl = normalizeWebUrl(target.page_url);
      if (!sourceUrl) {
        switchToResourceView();
        showMessageSoon("最近浏览的网页地址无效，请在资料视图粘贴网址后保存。");
        return;
      }
      showMessageSoon(`正在收藏「${target.page_title || sourceHost(sourceUrl)}」…`);
      const clientId = crypto.randomUUID();
      pendingResourceDraft = {
        clientId,
        url: sourceUrl,
        title: target.page_title.trim(),
        body: sourceUrl,
      };
      const created = await createMemo(
        {
          type: "resource",
          body: sourceUrl,
          source_url: sourceUrl,
          source_title: target.page_title.trim() || undefined,
          tags: [],
        },
        clientId,
      );
      const deduplicatedResource = created.client_id !== clientId;
      switchToResourceView();
      if (!deduplicatedResource) {
        setMemos((current) => [
          created,
          ...current.filter((memo) => memo.id !== created.id),
        ]);
        setUndoMemo(created);
      }
      setDuplicateResource(null);
      setPendingResource(null);
      void refreshMemoCounts();
      void loadReviewQueue();
      showMessageSoon(
        deduplicatedResource
          ? "该网页已在资料库中，已定位到原有条目。"
          : `已收藏「${target.page_title || sourceHost(sourceUrl)}」，可在此查看。`,
      );
    } catch (error) {
      if (
        error instanceof ApiError &&
        error.code === "duplicate_resource" &&
        error.current &&
        pendingResourceDraft
      ) {
        setDuplicateResource(error.current);
        setPendingResource(pendingResourceDraft);
        switchToResourceView();
        showMessageSoon("该网页已经收藏，可以查看已有资料或仍然保存。");
        return;
      }
      showMessageSoon(describeError(error));
    } finally {
      quickSaveBusyRef.current = false;
    }
  };
  quickSaveRecentPageRef.current = quickSaveRecentPage;

  const handleUndoSave = async () => {
    const target = undoMemo;
    if (!target || creating) {
      return;
    }
    const version =
      selectedMemo?.id === target.id ? selectedMemo.version : target.version;
    try {
      await updateMemo(target.id, {
        expected_version: version,
        status: "trashed",
      });
      setMemos((current) => current.filter((memo) => memo.id !== target.id));
      if (selectedId === target.id) {
        setSelectedId(null);
      }
      setUndoMemo(null);
      void refreshMemoCounts();
      void loadReviewQueue();
      setMessage("已撤销刚才的保存，可在回收站恢复。");
    } catch (error) {
      setMessage(describeError(error));
    }
  };

  const handleMoveToTrash = async (memo: Memo) => {
    if (creating) {
      return;
    }
    if (
      !window.confirm(
        `「${memo.title}」将移入回收站，${TRASH_RETENTION_DAYS} 天后永久删除。继续吗？`,
      )
    ) {
      return;
    }
    try {
      await trashMemo(memo.id, memo.version);
      setMemos((current) => current.filter((item) => item.id !== memo.id));
      if (selectedId === memo.id) {
        setSelectedId(null);
      }
      if (resourcePreviewMemo?.id === memo.id) {
        setResourcePreviewMemo(null);
      }
      if (undoMemo?.id === memo.id) {
        setUndoMemo(null);
      }
      void refreshMemoCounts();
      void loadReviewQueue();
      setMessage("已移入回收站，可在 30 天内恢复。");
    } catch (error) {
      setMessage(describeError(error));
    }
  };

  const handleRestoreFromTrash = async (memo: Memo) => {
    if (trashBulkBusyRef.current) return;
    try {
      const restored = await restoreMemo(memo.id, memo.version);
      setMemos((current) => current.filter((item) => item.id !== memo.id));
      if (activeTypeRef.current === "trash") {
        setTrashTotalCount((count) => Math.max(0, count - 1));
        setCurrentResultCount((count) => Math.max(0, count - 1));
      }
      void refreshMemoCounts();
      setMessage(`已恢复「${restored.title}」。`);
    } catch (error) {
      setMessage(describeError(error));
    }
  };

  const handlePermanentDelete = async (memo: Memo) => {
    if (trashBulkBusyRef.current) return;
    if (
      !window.confirm(
        `将永久删除「${memo.title}」，此操作不可恢复。确定继续吗？`,
      )
    ) {
      return;
    }
    try {
      await permanentlyDeleteMemo(memo.id, memo.version);
      setMemos((current) => current.filter((item) => item.id !== memo.id));
      if (activeTypeRef.current === "trash") {
        setTrashTotalCount((count) => Math.max(0, count - 1));
        setCurrentResultCount((count) => Math.max(0, count - 1));
      }
      if (selectedId === memo.id) {
        setSelectedId(null);
      }
      if (resourcePreviewMemo?.id === memo.id) {
        setResourcePreviewMemo(null);
      }
      setMessage("已永久删除。");
    } catch (error) {
      setMessage(describeError(error));
    }
  };

  const handleTrashBulkAction = async (action: "restore" | "empty"): Promise<void> => {
    if (trashBulkBusyRef.current) return;
    if (action === "empty" && !window.confirm(
      "确定永久删除回收站的全部内容及图片、录音附件？此操作无法恢复。",
    )) return;
    trashBulkBusyRef.current = true;
    setTrashBulkAction(action);
    try {
      const count = action === "restore"
        ? (await restoreAllTrash()).restored_count
        : (await emptyTrash()).deleted_count;
      if (activeTypeRef.current === "trash") {
        setSelectedId(null);
        setResourcePreviewMemo(null);
      }
      // 用当前视图的最新查询刷新，避免操作期间切换页面或搜索造成旧结果回写。
      await Promise.all([
        loadCurrentMemosRef.current(false),
        refreshMemoCounts(),
        loadReviewQueue(),
        refreshHealthSummary(),
      ]);
      setMessage(action === "restore"
        ? `已还原 ${count} 条内容，恢复到删除前的状态。`
        : `回收站已清空，永久删除 ${count} 条内容。`);
    } catch (error) {
      setMessage(describeError(error));
    } finally {
      trashBulkBusyRef.current = false;
      setTrashBulkAction(null);
    }
  };

  const handleViewDuplicateWord = () => {
    if (!duplicateWord) {
      return;
    }
    selectMemo(duplicateWord);
    setDuplicateWord(null);
    setPendingWord(null);
    setMessage("已打开已有单词，可继续补充语境。");
  };

  const handleMergeDuplicateWord = async () => {
    if (!duplicateWord || !pendingWord || creating) {
      return;
    }
    setCreating(true);
    try {
      const merged = await mergeWord(duplicateWord.id, {
        expectedVersion: duplicateWord.version,
        wordPhonetic: pendingWord.phonetic || undefined,
        wordMeaning: pendingWord.meaning || undefined,
        wordExample: pendingWord.example || undefined,
      });
      setMemos((current) => [
        merged,
        ...current.filter((memo) => memo.id !== merged.id),
      ]);
      setNewBody("");
      setNewTitle("");
      setNewPhonetic("");
      setNewExample("");
      clearWordLookup();
      setDuplicateWord(null);
      setPendingWord(null);
      setUndoMemo(null);
      selectMemo(merged);
      setMessage("已把新语境合并进已有单词。");
      void loadReviewQueue();
    } catch (error) {
      setMessage(describeError(error));
    } finally {
      setCreating(false);
    }
  };

  const handleForceDuplicateWord = async () => {
    if (!pendingWord || creating) {
      return;
    }
    setCreating(true);
    try {
      const created = await createMemo({
        type: "word",
        title: pendingWord.title,
        body: pendingWord.meaning || pendingWord.title,
        word_phonetic: pendingWord.phonetic || undefined,
        word_meaning: pendingWord.meaning || undefined,
        word_example: pendingWord.example || undefined,
        allow_duplicate: true,
        tags: [],
      });
      setMemos((current) => [created, ...current]);
      setNewBody("");
      setNewTitle("");
      setNewPhonetic("");
      setNewExample("");
      clearWordLookup();
      setDuplicateWord(null);
      setPendingWord(null);
      setUndoMemo(created);
      selectMemo(created);
      void refreshMemoCounts();
      void loadReviewQueue();
      setMessage("已另外保存这条单词。");
    } catch (error) {
      setMessage(describeError(error));
    } finally {
      setCreating(false);
    }
  };

  const handleViewDuplicateResource = () => {
    if (!duplicateResource) {
      return;
    }
    setMemos((current) => [
      duplicateResource,
      ...current.filter((memo) => memo.id !== duplicateResource.id),
    ]);
    setResourcePreviewMemo(duplicateResource);
    setMessage("已打开已有网页资料；原输入仍然保留，可以返回后选择仍然保存。");
  };

  const handleForceDuplicateResource = async () => {
    if (!pendingResource || creating) {
      return;
    }
    setCreating(true);
    try {
      const created = await createMemo(
        {
          type: "resource",
          title: pendingResource.title || undefined,
          body: pendingResource.body,
          source_url: pendingResource.url,
          source_title: pendingResource.title || undefined,
          allow_duplicate: true,
          tags: [],
        },
        pendingResource.clientId,
      );
      setMemos((current) => [
        created,
        ...current.filter((memo) => memo.id !== created.id),
      ]);
      setUndoMemo(created);
      setNewBody("");
      setNewUrl("");
      setNewTitle("");
      setDuplicateResource(null);
      setPendingResource(null);
      setWebAttachment(null);
      setWebAttachmentHelp(false);
      void refreshMemoCounts();
      void loadReviewQueue();
      setMessage("已另外保存这条网页资料，可撤销刚才的保存。");
    } catch (error) {
      setMessage(describeError(error));
    } finally {
      setCreating(false);
    }
  };

  const handleCopyResourceLink = async (memo: Memo) => {
    if (!memo.source_url || !navigator.clipboard?.writeText) {
      setMessage("当前浏览器不能写入剪贴板，请手动复制网址。");
      return;
    }
    try {
      await navigator.clipboard.writeText(memo.source_url);
      setMessage("网页链接已复制。");
    } catch {
      setMessage("复制失败，请手动复制网址。");
    }
  };

  const handleArchiveResource = async (memo: Memo) => {
    if (typeChangingId || creating) {
      return;
    }
    setUpdatingResourceId(memo.id);
    try {
      const updated = await updateMemo(memo.id, {
        expected_version: memo.version,
        status: "archived",
      });
      setMemos((current) => current.filter((item) => item.id !== updated.id));
      setResourcePreviewMemo(null);
      void refreshMemoCounts();
      void loadReviewQueue();
      setMessage("网页资料已归档。");
    } catch (error) {
      setMessage(describeError(error));
    } finally {
      setUpdatingResourceId(null);
    }
  };

  const handleChangeMemoType = async (memo: Memo, nextType: MemoType) => {
    if (memo.type === nextType || typeChangingId || creating) {
      return;
    }
    if (memo.type === "image" || nextType === "image") {
      setMessage("图片收藏不支持类型转换，请保留为图片内容。");
      return;
    }
    const warnings: Record<MemoType, string> = {
      idea: "转换后会清理单词或网页专属字段，标题、正文和来源链接会保留。继续吗？",
      word: "转换后正文会作为单词释义，并清理网页专属字段。继续吗？",
      resource: "转换后需要网址，网页元数据会重新抓取；标题、正文和来源链接会保留。继续吗？",
      image: "图片收藏需要图片文件，不能从其他类型转换。",
    };
    if (!window.confirm(warnings[nextType])) {
      return;
    }
    setTypeChangingId(memo.id);
    try {
      const updated = await updateMemo(memo.id, {
        expected_version: memo.version,
        type: nextType,
      });
      setMemos((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
      if (updated.type === "resource") {
        setSelectedId(null);
        setResourcePreviewMemo(updated);
      } else {
        setResourcePreviewMemo(null);
        selectMemo(updated);
      }
      void refreshMemoCounts();
      void loadReviewQueue();
      void loadCurrentMemos(false);
      setMessage(`已将内容转换为${viewCopy[nextType].itemLabel}。`);
    } catch (error) {
      setMessage(describeError(error));
    } finally {
      setTypeChangingId(null);
    }
  };

  const handleUpdate = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (
      !selectedMemo ||
      selectedMemo.type === "resource" ||
      !editorTitle.trim()
    ) {
      return;
    }
    if (selectedMemo.type === "idea" && !editorBody.trim()) {
      return;
    }
    setSaveState("saving");
    setMessage("");
    try {
      const updated = await updateMemo(selectedMemo.id, {
        expected_version: selectedMemo.version,
        title: editorTitle.trim(),
        body:
          selectedMemo.type === "image"
            ? editorBody.trim()
            : editorBody.trim() || selectedMemo.body,
        word_phonetic:
          selectedMemo.type === "word" ? editorPhonetic.trim() || undefined : undefined,
        word_meaning:
          selectedMemo.type === "word" ? editorBody.trim() || undefined : undefined,
        word_example:
          selectedMemo.type === "word" ? editorExample.trim() || undefined : undefined,
      });
      setMemos((current) =>
        current.map((memo) => (memo.id === updated.id ? updated : memo)),
      );
      clearEditorDraft(authUser.id, updated.id);
      setSaveState("saved");
      if (undoMemo?.id === updated.id) {
        setUndoMemo(updated);
      }
    } catch (error) {
      setSaveState("error");
      setMessage(describeError(error));
      if (error instanceof ApiError && error.status === 409 && error.current) {
        const serverMemo = error.current;
        // 只更新服务端基线，编辑器中的本地字段继续保留给用户选择。
        setMemos((current) => {
          const hasCurrent = current.some((memo) => memo.id === serverMemo.id);
          return hasCurrent
            ? current.map((memo) => (memo.id === serverMemo.id ? serverMemo : memo))
            : [serverMemo, ...current];
        });
        setConflictMemo(serverMemo);
      } else if (error instanceof ApiError && error.status === 409) {
        setMessage("内容已在其他设备更新，但服务端没有返回当前版本，请刷新后再处理。");
      }
    }
  };

  const keepLocalConflict = () => {
    setConflictMemo(null);
    setSaveState("idle");
    setMessage("已保留本地修改，请确认内容后再次保存。");
  };

  const useServerConflict = () => {
    if (!conflictMemo) {
      return;
    }
    const serverMemo = conflictMemo;
    setEditorTitle(serverMemo.title);
    setEditorBody(
      serverMemo.type === "word"
        ? serverMemo.word_meaning ?? serverMemo.body
        : serverMemo.body,
    );
    setEditorPhonetic(serverMemo.word_phonetic ?? "");
    setEditorExample(serverMemo.word_example ?? "");
    clearEditorDraft(authUser.id, serverMemo.id);
    setMemos((current) =>
      current.map((memo) => (memo.id === serverMemo.id ? serverMemo : memo)),
    );
    setShowWordAnswer(false);
    setConflictMemo(null);
    setSaveState("idle");
    setMessage("已采用服务端版本。");
  };

  const updateResourceOrganization = async (
    memo: Memo,
    changes: {
      resource_category?: ResourceCategory;
      resource_categories?: ResourceCategory[];
      starred?: boolean;
    },
  ) => {
    if ((memo.type !== "resource" && memo.type !== "image") || updatingResourceId === memo.id) {
      return;
    }
    setUpdatingResourceId(memo.id);
    setMessage("");
    try {
      const updated = await updateMemo(memo.id, {
        expected_version: memo.version,
        ...changes,
      });
      const remainsVisible =
        activeType === "image" ? (!imageCategoryFilter || memoMatchesCategoryFilter(updated, imageCategoryFilter, resourceCategories)) :
        activeType !== "resource" ||
        ((!resourceCategoryFilter ||
          memoMatchesCategoryFilter(
            updated,
            resourceCategoryFilter,
            resourceCategories,
          )) &&
          (!resourceStarredOnly || updated.starred));
      setMemos((current) =>
        remainsVisible
          ? current.map((item) => (item.id === updated.id ? updated : item))
          : current.filter((item) => item.id !== updated.id),
      );
      if (!remainsVisible) void loadCurrentMemos(false);
    } catch (error) {
      setMessage(describeError(error));
      if (error instanceof ApiError && error.status === 409) {
        await loadCurrentMemos(false);
      }
    } finally {
      setUpdatingResourceId(null);
    }
  };

  const closeResourcePreview = useCallback(() => setResourcePreviewMemo(null), []);
  const closeShortcutHelp = useCallback(() => setShortcutHelpOpen(false), []);
  const openPreviewSource = useCallback(() => {
    if (resourcePreviewMemo) handleResourceOpened(resourcePreviewMemo);
  }, [resourcePreviewMemo, handleResourceOpened]);

  const openResourcePreview = (memo: Memo, editing = false) => {
    // 记下当前行和相邻行，关闭弹窗后焦点回到原处；原行被删除时落到相邻行。
    const index = memos.findIndex((item) => item.id === memo.id);
    previewReturnIdRef.current = [memo.id, memos[index + 1]?.id, memos[index - 1]?.id]
      .filter((id): id is string => Boolean(id));
    setResourcePreviewEditing(editing);
    setResourcePreviewMemo(memo);
  };

  const focusPendingRow = useCallback(() => {
    const pending = pendingRowFocusRef.current;
    if (!pending) return;
    pendingRowFocusRef.current = null;
    const rows = resourceRowElements();
    const row = pending === "first"
      ? rows[0]
      : pending
        .map((id) => rows.find((item) => item.dataset.memoId === id))
        .find(Boolean);
    row?.focus();
  }, []);

  useEffect(() => {
    if (resourcePreviewMemo) return;
    setResourcePreviewEditing(false);
    if (!previewReturnIdRef.current) return;
    pendingRowFocusRef.current = previewReturnIdRef.current;
    previewReturnIdRef.current = null;
    window.requestAnimationFrame(focusPendingRow);
  }, [resourcePreviewMemo, focusPendingRow]);

  useEffect(() => {
    // 翻页或删除后等新列表渲染完成再落焦点。
    if (loadState === "ready") focusPendingRow();
  }, [memos, loadState, focusPendingRow]);

  // 网页资料列表的单键快捷键；返回 true 表示已处理。
  resourceListKeyRef.current = (event: KeyboardEvent): boolean => {
    if (loadState !== "ready") return false;
    const rows = resourceRowElements();
    const active = document.activeElement as HTMLElement | null;
    const currentRow = active?.closest<HTMLElement>(".memo-list .memo-row[data-memo-id]") ?? null;
    const onRow = currentRow !== null && active === currentRow;
    const index = currentRow ? rows.indexOf(currentRow) : -1;
    const key = event.key.length === 1 ? event.key.toLowerCase() : event.key;
    const changePage = (delta: number) => {
      const page = resourcePage + delta;
      if (batchBusy || page < 1 || page > resourcePageCount) return;
      pendingRowFocusRef.current = "first";
      setResourcePage(page);
    };

    if (key === "j" || (key === "ArrowDown" && currentRow)) {
      event.preventDefault();
      rows[index < 0 ? 0 : Math.min(index + 1, rows.length - 1)]?.focus();
      return true;
    }
    if (key === "k" || (key === "ArrowUp" && currentRow)) {
      event.preventDefault();
      rows[Math.max(index - 1, 0)]?.focus();
      return true;
    }
    if (key === "]" || (key === "ArrowRight" && onRow)) {
      event.preventDefault();
      changePage(1);
      return true;
    }
    if (key === "[" || (key === "ArrowLeft" && onRow)) {
      event.preventDefault();
      changePage(-1);
      return true;
    }
    if (!onRow) return false;
    const memo = memos.find((item) => item.id === currentRow.dataset.memoId);
    if (!memo || memo.type !== "resource") return false;
    switch (key) {
      case "e":
        openResourcePreview(memo, true);
        break;
      case "o":
        if (memo.source_url) {
          window.open(memo.source_url, "_blank", "noopener,noreferrer");
          handleResourceOpened(memo);
        }
        break;
      case "c":
        void handleCopyResourceLink(memo);
        break;
      case "s":
        void updateResourceOrganization(memo, { starred: !memo.starred });
        break;
      case "x":
        if (!batchBusy) toggleBatchMemo(memo);
        break;
      case "Delete": {
        const fallback = [memo.id, rows[index + 1]?.dataset.memoId, rows[index - 1]?.dataset.memoId]
          .filter((id): id is string => Boolean(id));
        void handleMoveToTrash(memo).then(() => {
          pendingRowFocusRef.current = fallback;
          window.requestAnimationFrame(focusPendingRow);
        });
        break;
      }
      default:
        return false;
    }
    event.preventDefault();
    return true;
  };

  const saveResourceEdits = async (
    memo: Memo,
    changes: ResourceEditChanges,
  ): Promise<string | null> => {
    setUpdatingResourceId(memo.id);
    try {
      const updated = await updateMemo(memo.id, {
        expected_version: memo.version,
        ...changes,
      });
      setMemos((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
      setResourcePreviewMemo(updated);
      setMessage("网页资料已保存。");
      return null;
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        // 别处已改过这条资料：换成最新版本，让用户在新内容上重新编辑。
        try {
          const latest = await getMemo(memo.id);
          setResourcePreviewMemo(latest);
          setMemos((current) =>
            current.map((item) => (item.id === latest.id ? latest : item)),
          );
        } catch {
          void loadCurrentMemos(false);
        }
        return "这条资料刚在别处被修改过，已载入最新内容，请重新编辑。";
      }
      return describeError(error);
    } finally {
      setUpdatingResourceId(null);
    }
  };

  const handleResourceTagSearch = (tag: string) => {
    setResourcePreviewMemo(null);
    if (activeType !== "resource") {
      switchType("resource");
    }
    setResourceQuery(tag);
    setResourcePage(1);
  };

  const toggleMemoCategory = (memo: Memo, code: string) => {
    const current = memoCategoryCodes(memo);
    if (!current.includes(code) && current.length >= MAX_MEMO_CATEGORIES) {
      setMessage("最多 8 个分类");
      return;
    }
    const next = current.includes(code)
      ? current.filter((item) => item !== code)
      : [...current, code];
    void updateResourceOrganization(memo, { resource_categories: next });
  };

  const handleReview = async (feedback: ReviewFeedback) => {
    if (!selectedMemo || selectedMemo.type !== "word" || reviewing) {
      return;
    }
    setReviewing(true);
    setMessage("");
    try {
      const reviewed = await reviewWord(
        selectedMemo.id,
        selectedMemo.version,
        feedback,
      );
      setMemos((current) =>
        current.map((memo) => (memo.id === reviewed.id ? reviewed : memo)),
      );
      setMessage("复习结果已记录，下次回顾时间已经更新。");
      setShowWordAnswer(false);
      void loadReviewQueue();
    } catch (error) {
      setMessage(describeError(error));
      if (error instanceof ApiError && error.status === 409) {
        await loadCurrentMemos();
      }
    } finally {
      setReviewing(false);
    }
  };

  const handleReviewSkip = async (memo: Memo) => {
    if (reviewBusy) {
      return;
    }
    setReviewBusy(true);
    try {
      await skipReview(memo.id, memo.version);
      await loadReviewQueue();
      setMessage("已跳过，明天之前不会再出现。");
    } catch (error) {
      setMessage(describeError(error));
      if (error instanceof ApiError && error.status === 409) {
        await loadReviewQueue();
      }
    } finally {
      setReviewBusy(false);
    }
  };

  const handleReviewWord = async (memo: Memo, feedback: ReviewFeedback) => {
    if (reviewBusy) {
      return;
    }
    setReviewBusy(true);
    try {
      await reviewWord(memo.id, memo.version, feedback);
      await loadReviewQueue();
      setMessage("复习结果已记录，下次回顾时间已经更新。");
    } catch (error) {
      setMessage(describeError(error));
      if (error instanceof ApiError && error.status === 409) {
        await loadReviewQueue();
      }
    } finally {
      setReviewBusy(false);
    }
  };

  const handleReviewOpenResource = async (memo: Memo) => {
    if (!memo.source_url || reviewBusy) {
      return;
    }
    setReviewBusy(true);
    try {
      window.open(memo.source_url, "_blank", "noopener,noreferrer");
      handleResourceOpened(memo);
      await updateMemo(memo.id, {
        expected_version: memo.version,
        resource_reading_status: "reading",
      });
      await loadReviewQueue();
    } catch (error) {
      setMessage(describeError(error));
    } finally {
      setReviewBusy(false);
    }
  };

  const handleReviewStarResource = async (memo: Memo) => {
    if (reviewBusy) {
      return;
    }
    setReviewBusy(true);
    try {
      const updated = await updateMemo(memo.id, {
        expected_version: memo.version,
        starred: !memo.starred,
      });
      setReviewQueue((current) =>
        current
          ? {
              ...current,
              items: current.items.map((item) =>
                item.id === updated.id ? updated : item,
              ),
            }
          : current,
      );
    } catch (error) {
      setMessage(describeError(error));
    } finally {
      setReviewBusy(false);
    }
  };

  const handleReviewOrganizeIdea = async (
    memo: Memo,
    title: string,
    body: string,
  ) => {
    if (reviewBusy || !body) {
      return;
    }
    setReviewBusy(true);
    try {
      await updateMemo(memo.id, {
        expected_version: memo.version,
        title: title || undefined,
        body,
        status: "active",
      });
      await loadReviewQueue();
      setMessage("灵感已整理，并移出今日回顾。");
    } catch (error) {
      setMessage(describeError(error));
    } finally {
      setReviewBusy(false);
    }
  };

  const handleReviewArchiveIdea = async (memo: Memo) => {
    if (reviewBusy) {
      return;
    }
    setReviewBusy(true);
    try {
      await updateMemo(memo.id, {
        expected_version: memo.version,
        status: "archived",
      });
      await loadReviewQueue();
      setMessage("灵感已归档。");
    } catch (error) {
      setMessage(describeError(error));
    } finally {
      setReviewBusy(false);
    }
  };

  const handleOrganizeInboxItem = async (memo: Memo) => {
    const nextTitle = (
      memo.id === selectedId ? editorTitle : memo.title
    ).trim();
    const nextBody = (memo.id === selectedId ? editorBody : memo.body).trim();
    if (memo.type === "idea" && !nextBody) {
      setMessage("请先补充内容，再标记为整理完成。");
      return;
    }
    try {
      const updated = await updateMemo(memo.id, {
        expected_version: memo.version,
        title: nextTitle || undefined,
        body: nextBody || memo.body,
        status: "active",
      });
      setMemos((current) => current.filter((item) => item.id !== updated.id));
      setCurrentResultCount((count) => Math.max(0, count - 1));
      if (selectedId === memo.id) {
        setSelectedId(null);
      }
      void refreshMemoCounts();
      void loadReviewQueue();
      setMessage("已整理完成，并移出收件箱。");
    } catch (error) {
      setMessage(describeError(error));
    }
  };

  const handleArchiveInboxItem = async (memo: Memo) => {
    try {
      const updated = await updateMemo(memo.id, {
        expected_version: memo.version,
        status: "archived",
      });
      setMemos((current) => current.filter((item) => item.id !== updated.id));
      setCurrentResultCount((count) => Math.max(0, count - 1));
      if (selectedId === memo.id) {
        setSelectedId(null);
      }
      void refreshMemoCounts();
      void loadReviewQueue();
      setMessage("已归档，并移出收件箱。");
    } catch (error) {
      setMessage(describeError(error));
    }
  };

  const resetVoiceCapture = () => {
    voiceCaptureGenerationRef.current += 1;
    stopVoiceVolumeMonitor();
    if (voiceTimerRef.current !== null) {
      window.clearInterval(voiceTimerRef.current);
      voiceTimerRef.current = null;
    }
    recorderRef.current = null;
    voiceTranscriptionActiveRef.current = false;
    voiceTranscriptionStartedRef.current = false;
    voicePausedAtRef.current = null;
    voicePausedTotalMsRef.current = 0;
    voiceDiscardingRef.current = false;
    recognitionBaseTextRef.current = "";
    try {
      speechRecognitionRef.current?.abort();
    } catch {
      // 识别器已经结束时 abort 可能抛异常，清理流程仍应继续。
    }
    speechRecognitionRef.current = null;
    setVoiceState("idle");
    setVoiceSeconds(0);
    setVoiceText("");
    setVoiceTranscriptionMessage("");
    setVoiceBlob(null);
    setVoiceDraftMemo(null);
    setVoiceDiscardConfirmOpen(false);
    voiceChunksRef.current = [];
    voiceAutomaticTextRef.current = "";
  };

  const startBrowserTranscription = (resetAutomaticText = true) => {
    const recognition = createBrowserSpeechRecognition();
    if (!recognition) {
      setVoiceTranscriptionMessage("当前浏览器不支持自动转写，录音完成后可手动填写文字。");
      return;
    }
    voiceTranscriptionActiveRef.current = true;
    voiceTranscriptionStartedRef.current = true;
    recognitionBaseTextRef.current = resetAutomaticText
      ? ""
      : voiceAutomaticTextRef.current.trim();
    if (resetAutomaticText) {
      voiceAutomaticTextRef.current = "";
    }
    recognition.onresult = (event) => {
      let finalText = "";
      let interimText = "";
      for (let index = 0; index < event.results.length; index += 1) {
        const result = event.results[index];
        if (result.length === 0) {
          continue;
        }
        if (result.isFinal) {
          finalText += `${result[0].transcript} `;
        } else {
          interimText += `${result[0].transcript} `;
        }
      }
      const sessionText = `${finalText}${interimText}`.trim();
      const transcript = [recognitionBaseTextRef.current, sessionText]
        .filter(Boolean)
        .join(" ");
      const previousAutomaticText = voiceAutomaticTextRef.current;
      voiceAutomaticTextRef.current = transcript;
      setVoiceText((current) => {
        const cleanedCurrent = current.trim();
        if (!cleanedCurrent || cleanedCurrent === previousAutomaticText) {
          return transcript;
        }
        return current;
      });
      if (transcript) {
        setVoiceTranscriptionMessage("正在实时转写，录音结束后仍可编辑结果。");
      }
    };
    recognition.onerror = (event) => {
      const fatalErrors = new Set(["audio-capture", "not-allowed", "service-not-allowed"]);
      if (fatalErrors.has(event.error)) {
        voiceTranscriptionActiveRef.current = false;
        voiceTranscriptionStartedRef.current = false;
        setVoiceTranscriptionMessage("浏览器语音识别不可用，原始录音仍会保留，可手动填写文字。");
      } else if (event.error !== "no-speech") {
        setVoiceTranscriptionMessage("浏览器转写暂时失败，录音仍会继续。");
      }
    };
    recognition.onend = () => {
      if (
        !voiceTranscriptionActiveRef.current ||
        recorderRef.current?.state !== "recording"
      ) {
        return;
      }
      // Chrome 可能在静音或短暂网络波动后结束识别，录音期间自动重启。
      window.setTimeout(() => {
        if (
          !voiceTranscriptionActiveRef.current ||
          recorderRef.current?.state !== "recording"
        ) {
          return;
        }
        try {
          recognition.start();
        } catch {
          // 已经启动时忽略重复 start，等待下一次结果或录音结束。
        }
      }, 100);
    };
    speechRecognitionRef.current = recognition;
    setVoiceTranscriptionMessage("正在启动浏览器语音识别…");
    try {
      recognition.start();
    } catch {
      voiceTranscriptionActiveRef.current = false;
      voiceTranscriptionStartedRef.current = false;
      speechRecognitionRef.current = null;
      setVoiceTranscriptionMessage("浏览器语音识别启动失败，录音仍会继续。");
    }
  };

  const startVoiceCapture = async () => {
    if (!navigator.mediaDevices?.getUserMedia || !("MediaRecorder" in window)) {
      setMessage("当前浏览器不支持录音，请使用文字输入或 Android 客户端。");
      return;
    }
    const captureGeneration = voiceCaptureGenerationRef.current + 1;
    voiceCaptureGenerationRef.current = captureGeneration;
    voiceDiscardingRef.current = false;
    voicePausedAtRef.current = null;
    voicePausedTotalMsRef.current = 0;
    setVoiceVolume(0);
    setVoiceState("requesting");
    setMessage("");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (captureGeneration !== voiceCaptureGenerationRef.current) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      const mimeType = [
        "audio/webm;codecs=opus",
        "audio/webm",
        "audio/mp4",
      ].find((candidate) => MediaRecorder.isTypeSupported(candidate));
      const recorder = new MediaRecorder(
        stream,
        mimeType ? { mimeType } : undefined,
      );
      voiceChunksRef.current = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          voiceChunksRef.current.push(event.data);
        }
      };
      recorder.onstop = () => {
        const durationMs = activeVoiceElapsedMs();
        const blob = new Blob(voiceChunksRef.current, {
          type: recorder.mimeType || "audio/webm",
        });
        recorder.stream.getTracks().forEach((track) => track.stop());
        stopVoiceVolumeMonitor();
        if (voiceTimerRef.current !== null) {
          window.clearInterval(voiceTimerRef.current);
          voiceTimerRef.current = null;
        }
        voiceTranscriptionActiveRef.current = false;
        try {
          speechRecognitionRef.current?.stop();
        } catch {
          // 识别器已结束时无需再次停止。
        }
        speechRecognitionRef.current = null;
        recorderRef.current = null;
        voicePausedAtRef.current = null;
        voicePausedTotalMsRef.current = 0;
        if (voiceDiscardingRef.current) {
          voiceDiscardingRef.current = false;
          voiceChunksRef.current = [];
          resetVoiceCapture();
          setVoicePanelOpen(false);
          setVoiceDiscardConfirmOpen(false);
          return;
        }
        setVoiceSeconds(Math.max(1, Math.round(durationMs / 1_000)));
        setVoiceBlob(blob);
        setVoiceState("ready");
        const recognizedText = voiceAutomaticTextRef.current.trim();
        if (recognizedText) {
          setVoiceText((current) => current.trim() || recognizedText);
          setVoiceTranscriptionMessage("转写完成，可直接编辑结果。");
        } else if (voiceTranscriptionStartedRef.current) {
          setVoiceTranscriptionMessage("未识别到可用文字，可手动填写。");
        }
      };
      recorder.onerror = () => {
        recorder.stream.getTracks().forEach((track) => track.stop());
        stopVoiceVolumeMonitor();
        voiceTranscriptionActiveRef.current = false;
        try {
          speechRecognitionRef.current?.abort();
        } catch {
          // 识别器已经结束时无需再次停止。
        }
        speechRecognitionRef.current = null;
        recorderRef.current = null;
        voiceChunksRef.current = [];
        voicePausedAtRef.current = null;
        voicePausedTotalMsRef.current = 0;
        setVoiceState("idle");
        setMessage("录音失败，请检查麦克风权限后重试。");
      };
      recorderRef.current = recorder;
      voiceStartedAtRef.current = Date.now();
      startVoiceVolumeMonitor(stream);
      startBrowserTranscription();
      recorder.start(500);
      setVoiceSeconds(0);
      setVoiceState("recording");
      voiceTimerRef.current = window.setInterval(() => {
        updateVoiceElapsed();
      }, 500);
    } catch (error) {
      if (captureGeneration !== voiceCaptureGenerationRef.current) {
        return;
      }
      stopVoiceVolumeMonitor();
      recorderRef.current?.stream.getTracks().forEach((track) => track.stop());
      recorderRef.current = null;
      setVoiceState("idle");
      setMessage(
        error instanceof Error
          ? `无法使用麦克风：${error.message}`
          : "无法使用麦克风。",
      );
    }
  };

  const stopVoiceCapture = () => {
    const recorder = recorderRef.current;
    if (recorder && (recorder.state === "recording" || recorder.state === "paused")) {
      voiceTranscriptionActiveRef.current = false;
      try {
        speechRecognitionRef.current?.stop();
      } catch {
        // 识别器已结束时无需再次停止。
      }
      recorder.stop();
    }
  };

  const pauseVoiceCapture = () => {
    const recorder = recorderRef.current;
    if (!recorder || recorder.state !== "recording") {
      return;
    }
    try {
      recorder.pause();
      voicePausedAtRef.current = Date.now();
      setVoiceVolume(0);
      voiceTranscriptionActiveRef.current = false;
      try {
        speechRecognitionRef.current?.stop();
      } catch {
        // 识别器已结束时无需再次停止。
      }
      setVoiceState("paused");
      updateVoiceElapsed();
    } catch {
      setMessage("当前浏览器暂不支持暂停录音，请直接结束录音。");
    }
  };

  const resumeVoiceCapture = () => {
    const recorder = recorderRef.current;
    if (!recorder || recorder.state !== "paused") {
      return;
    }
    try {
      recorder.resume();
      if (voicePausedAtRef.current !== null) {
        voicePausedTotalMsRef.current += Date.now() - voicePausedAtRef.current;
      }
      voicePausedAtRef.current = null;
      setVoiceState("recording");
      startBrowserTranscription(false);
      updateVoiceElapsed();
    } catch {
      setMessage("录音继续失败，请结束当前录音后重试。");
    }
  };

  const requestVoiceClose = () => {
    if (voiceState === "saving") {
      return;
    }
    if (voiceState === "idle" && !voiceText.trim() && !voiceBlob) {
      setVoicePanelOpen(false);
      resetVoiceCapture();
      return;
    }
    setVoiceDiscardConfirmOpen(true);
  };

  const discardVoiceCapture = () => {
    voiceDiscardingRef.current = true;
    setVoiceDiscardConfirmOpen(false);
    setVoicePanelOpen(false);
    const recorder = recorderRef.current;
    if (recorder && recorder.state !== "inactive") {
      try {
        recorder.stop();
        return;
      } catch {
        // 停止失败时仍然继续释放麦克风和临时状态。
      }
    }
    voiceDiscardingRef.current = false;
    resetVoiceCapture();
  };

  const saveVoiceCapture = async () => {
    if (!voiceBlob || voiceState === "saving") {
      return;
    }
    setVoiceState("saving");
    setMessage("");
    try {
      const draft = voiceDraftMemo ?? await createMemo({
        type: "idea",
        body: voiceText.trim() || "语音记录",
        tags: ["语音"],
      });
      setVoiceDraftMemo(draft);
      const uploaded = await uploadMemoAudio(
        draft.id,
        draft.version,
        voiceBlob,
        voiceSeconds * 1_000,
      );
      if (activeType === "idea") {
        setMemos((current) => [uploaded, ...current]);
      } else {
        switchType("idea");
      }
      void refreshMemoCounts();
      setVoicePanelOpen(false);
      resetVoiceCapture();
      setMessage("语音灵感已保存，并可在详情中播放。");
    } catch (error) {
      setVoiceState("ready");
      setMessage(describeError(error));
    }
  };

  const uploadImageFiles = async (files: File[]) => {
    const tasks: ImageUploadTask[] = files.map((file) => ({
      id: crypto.randomUUID(),
      name: imageFileTitle(file),
      status: "pending",
    }));
    setImageUploadTasks((current) => [...tasks, ...current]);
    let doneCount = 0;
    let errorCount = 0;
    let compressedCount = 0;
    const updateTask = (
      taskId: string,
      changes: Partial<ImageUploadTask>,
    ): void => {
      setImageUploadTasks((current) =>
        current.map((task) => (task.id === taskId ? { ...task, ...changes } : task)),
      );
    };
    for (let index = 0; index < files.length; index += 1) {
      const file = files[index];
      const task = tasks[index];
      const declaredMime = imageMimeFromFile(file);
      if (!declaredMime) {
        errorCount += 1;
        updateTask(task.id, {
          status: "error",
          error: "仅支持 PNG、JPEG、WebP 或 GIF 图片",
        });
        continue;
      }
      updateTask(task.id, { status: "uploading" });
      // 超过服务端限制（20 MB / 12000 像素 / 5000 万像素）时先压缩再上传。
      let prepared;
      try {
        prepared = await compressImageIfNeeded(file, declaredMime);
      } catch (error) {
        errorCount += 1;
        updateTask(task.id, { status: "error", error: describeError(error) });
        continue;
      }
      const uploadMime = prepared.compressed ? prepared.newType : declaredMime;
      const uploadFile =
        prepared.blob.type === uploadMime
          ? prepared.blob
          : new File([prepared.blob], file.name || "image", { type: uploadMime });
      if (prepared.compressed) {
        compressedCount += 1;
        updateTask(task.id, { note: describeImageCompression(prepared) });
      }
      try {
        const created = await createImageMemo(imageFileTitle(file));
        const uploaded = await uploadMemoImage(
          created.id,
          uploadFile,
          created.version,
        );
        doneCount += 1;
        updateTask(task.id, { status: "done" });
        if (activeTypeRef.current === "image") {
          setMemos((current) => [
            uploaded,
            ...current.filter((memo) => memo.id !== uploaded.id),
          ]);
        }
      } catch (error) {
        errorCount += 1;
        updateTask(task.id, { status: "error", error: describeError(error) });
      }
    }
    void refreshMemoCounts();
    void loadCurrentMemos(false);
    const compressedNote =
      compressedCount > 0 ? `，其中 ${compressedCount} 张已自动压缩` : "";
    setMessage(
      errorCount === 0
        ? `已收藏 ${doneCount} 张图片${compressedNote}。`
        : `已收藏 ${doneCount} 张图片${compressedNote}，${errorCount} 张失败。`,
    );
  };

  // 多次选择/粘贴的图片按顺序上传，避免并发创建造成列表抖动。
  const queueImageFiles = (files: File[]) => {
    const images = files.filter(isImageFile);
    if (images.length === 0) {
      if (files.length > 0) {
        setMessage("请选择图片文件（PNG、JPEG、WebP 或 GIF）。");
      }
      return;
    }
    if (images.length < files.length) {
      setMessage("已忽略不是图片的文件。");
    }
    imageUploadChainRef.current = imageUploadChainRef.current
      .then(() => uploadImageFiles(images))
      .catch(() => undefined);
  };

  const handleViewOriginal = async (memo: Memo) => {
    if (!memo.image_mime_type) {
      return;
    }
    // 先同步打开标签页，异步读取原图后再写入地址，避免被拦截。
    const newTab = window.open("", "_blank");
    setImagePreviewBusy(true);
    try {
      let url = imageFullUrl;
      if (!url) {
        url = await loadMemoImageUrl(memo.id, "original");
        setImageFullUrl(url);
      }
      if (newTab) {
        newTab.opener = null;
        newTab.location.replace(url);
      } else {
        setMessage("浏览器拦截了新标签页，请允许弹出窗口后重试。");
      }
    } catch (error) {
      newTab?.close();
      setMessage(describeError(error));
    } finally {
      setImagePreviewBusy(false);
    }
  };

  const handleDownloadImage = async (memo: Memo) => {
    if (!memo.image_mime_type) {
      return;
    }
    setImagePreviewBusy(true);
    try {
      let url = imageFullUrl;
      if (!url) {
        url = await loadMemoImageUrl(memo.id, "original");
        setImageFullUrl(url);
      }
      const anchor = document.createElement("a");
      anchor.href = url;
      const safeTitle = (memo.title || "图片收藏")
        .replace(/[\\/:*?"<>|]/g, "_")
        .slice(0, 80);
      anchor.download = `${safeTitle}.${imageFileExtension(memo.image_mime_type)}`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      setMessage("原图已开始下载。");
    } catch (error) {
      setMessage(describeError(error));
    } finally {
      setImagePreviewBusy(false);
    }
  };

  const handleReplaceImage = async (file: File) => {
    if (!selectedMemo || selectedMemo.type !== "image" || replaceImageBusy) {
      return;
    }
    const declaredMime = imageMimeFromFile(file);
    if (!declaredMime) {
      setMessage("请选择图片文件（PNG、JPEG、WebP 或 GIF）。");
      return;
    }
    setReplaceImageBusy(true);
    setMessage("");
    try {
      const prepared = await compressImageIfNeeded(file, declaredMime);
      const uploadMime = prepared.compressed ? prepared.newType : declaredMime;
      const uploadFile =
        prepared.blob.type === uploadMime
          ? prepared.blob
          : new File([prepared.blob], file.name || "image", { type: uploadMime });
      const updated = await uploadMemoImage(
        selectedMemo.id,
        uploadFile,
        selectedMemo.version,
      );
      setMemos((current) =>
        current.map((memo) => (memo.id === updated.id ? updated : memo)),
      );
      setMessage(
        prepared.compressed
          ? `图片已替换，原图和缩略图都已更新。${describeImageCompression(prepared)}`
          : "图片已替换，原图和缩略图都已更新。",
      );
    } catch (error) {
      if (error instanceof ApiError && error.status === 409 && error.current) {
        const serverMemo = error.current;
        setMemos((current) =>
          current.map((memo) => (memo.id === serverMemo.id ? serverMemo : memo)),
        );
        setMessage("图片已在其他设备更新，已刷新为服务端版本，请重新选择替换文件。");
      } else {
        setMessage(describeError(error));
      }
    } finally {
      setReplaceImageBusy(false);
    }
  };

  const handleRecognizeImageOcr = async () => {
    if (!selectedMemo || selectedMemo.type !== "image" || ocrBusy) {
      return;
    }
    setOcrBusy(true);
    setOcrError("");
    try {
      const updated = await recognizeMemoImageOcr(selectedMemo.id);
      setMemos((current) =>
        current.map((memo) => (memo.id === updated.id ? updated : memo)),
      );
    } catch (error) {
      if (error instanceof ApiError && error.status === 503) {
        setOcrError("服务端未启用图片文字识别，请联系管理员开启后再试。");
      } else {
        setOcrError(describeError(error));
      }
    } finally {
      setOcrBusy(false);
    }
  };

  const handleImageOcrTagClick = (tag: string) => {
    // 自动标签走全局搜索，服务端已覆盖 OCR 文本与自动标签。
    handleSearchChange(tag);
  };

  useEffect(() => {
    if (activeType !== "image") {
      return;
    }
    const handlePaste = (event: ClipboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (
        target &&
        (target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.isContentEditable)
      ) {
        return;
      }
      const files = Array.from(event.clipboardData?.items ?? [])
        .filter((item) => item.type.startsWith("image/"))
        .map((item) => item.getAsFile())
        .filter((file): file is File => file !== null);
      if (files.length === 0) {
        return;
      }
      event.preventDefault();
      queueImageFiles(files);
    };
    window.addEventListener("paste", handlePaste);
    return () => window.removeEventListener("paste", handlePaste);
  }, [activeType]);

  return (
    <div className="app-shell">
      <aside className="side-navigation" aria-label="主导航">
        <div className="brand-block">
          <BrandLogo className="brand-mark" />
          <div><strong>MemoIsle</strong><span>Personal sanctuary</span></div>
        </div>
        <button className="new-button" onClick={focusCapture}>
          <span aria-hidden="true">＋</span> 新建
        </button>
        <nav>
          {navigation.map((item) => {
            const enabled = item.view !== undefined || item.action !== undefined;
            // 首页现在是与「全部内容」合并后的唯一入口，需要正常显示选中态。
            const active = item.action === "vault"
              ? vaultOpen
              : !vaultOpen && item.view === activeType;
            return (
              <button
                className={active ? "nav-item active" : "nav-item"}
                disabled={!enabled}
                key={item.label}
                onClick={() => {
                  if (item.view === "word") {
                    enterWordCapture();
                  } else if (item.view) {
                    switchType(item.view);
                  } else if (item.action === "health") {
                    setHealthCenterOpen(true);
                  } else if (item.action === "settings") {
                    setModelSettingsOpen(true);
                  } else if (item.action === "vault") {
                    setSelectedId(null);
                    setVaultOpen(true);
                  }
                }}
                title={enabled ? undefined : "将在后续里程碑开放"}
              >
                <span className="nav-icon" aria-hidden="true">{item.icon}</span>
                {item.label}
                {item.view === "inbox" && memoCounts !== null && (
                  <span className="nav-count">{memoCounts.inbox_count}</span>
                )}
                {item.view === "resource" && memoCounts !== null && (
                  <span className="nav-count">{memoCounts.resource_count}</span>
                )}
                {item.view === "image" && memoCounts !== null && (
                  <span className="nav-count">{memoCounts.image_count}</span>
                )}
                {item.view === "review" && reviewQueue !== null && (
                  <span className="nav-count">
                    {reviewQueue.word_count +
                      reviewQueue.resource_count +
                      reviewQueue.idea_count}
                  </span>
                )}
                {item.action === "health" && healthIssueCount > 0 && (
                  <span className="nav-count">{healthIssueCount}</span>
                )}
                {item.action === "vault" && vaultReminderCount > 0 && (
                  <span className="nav-count" title={`上次解锁时有 ${vaultReminderCount} 条密码提醒`}>
                    {vaultReminderCount}
                  </span>
                )}
              </button>
            );
          })}
        </nav>
        <div className="account-block">
          <span className="avatar">{authUser.display_name.slice(0, 1)}</span>
          <span>{authUser.email ?? authUser.display_name}</span>
          <button
            className="account-logout"
            onClick={() => {
              // 退出登录前先锁定，内存里不留解锁后的库密钥。
              lockVaultSession();
              saveVaultReminderCount(0);
              void onLogout();
            }}
            type="button"
          >退出</button>
        </div>
      </aside>

      <div className="workspace">
        <header className="top-bar">
          <div className="search-box">
            <span aria-hidden="true">⌕</span>
            <input
              ref={searchRef}
              aria-label="搜索全部内容"
              value={searchQuery}
              onChange={(event) => handleSearchChange(event.target.value)}
              // 网页资料页的 / 聚焦本页搜索框，顶栏不再标注快捷键。
              placeholder={activeType === "resource" ? "搜索全部内容" : "搜索全部内容（/）"}
              maxLength={200}
            />
            {searchQuery && (
              <button
                type="button"
                aria-label="清除搜索"
                onClick={() => setSearchQuery("")}
              >×</button>
            )}
          </div>
          <span className="sync-status"><span className="sync-dot" /> 已同步</span>
          <button
            type="button"
            className="model-settings-open"
            onClick={() => setModelSettingsOpen(true)}
            aria-label="打开设置"
          ><span aria-hidden="true">⚙</span><span className="top-bar-label">设置</span></button>
          <a
            className="top-bar-button extension-download-button"
            href={browserExtensionDownloadUrl()}
            download={browserExtensionArchiveFilename()}
            title="下载后解压，并在 Chrome 或 Edge 中加载已解压的扩展"
          >↓ 下载扩展</a>
          <div className="data-export-controls">
            <input
              ref={wordImportInputRef}
              className="sr-only"
              type="file"
              accept=".json,.csv,application/json,text/csv"
              aria-label="导入单词文件"
              onChange={(event) => {
                const file = event.target.files?.[0];
                event.target.value = "";
                if (file) {
                  void handleWordImport(file);
                }
              }}
            />
            <input
              ref={libraryImportInputRef}
              className="sr-only"
              type="file"
              accept=".json,.csv,application/json,text/csv"
              aria-label="导入备份文件"
              onChange={(event) => {
                const file = event.target.files?.[0];
                event.target.value = "";
                if (file) {
                  void handleLibraryImport(file);
                }
              }}
            />
            <DataMenu
              busyLabel={isImporting ? "导入中…" : isExporting ? "导出中…" : ""}
              onImportLibrary={() => libraryImportInputRef.current?.click()}
              onImportWords={() => wordImportInputRef.current?.click()}
              onExport={(format) => void handleExport(format)}
            />
          </div>
          <button
            className={`trash-shortcut${activeType === "inbox" ? " active" : ""}`}
            type="button"
            onClick={() => switchType("inbox")}
            aria-label="收件箱"
          >
            <span aria-hidden="true">▣</span><span className="top-bar-label">收件箱</span>
          </button>
          <button
            className={`trash-shortcut${activeType === "trash" ? " active" : ""}`}
            type="button"
            onClick={() => switchType("trash")}
            aria-label="回收站"
          >
            <span aria-hidden="true">♻</span><span className="top-bar-label">回收站</span>
          </button>
          <button
            className={`trash-shortcut${vaultOpen ? " active" : ""}`}
            type="button"
            onClick={() => {
              setSelectedId(null);
              setVaultOpen(true);
            }}
            aria-label={vaultReminderCount > 0 ? `密码库，${vaultReminderCount} 条提醒` : "密码库"}
          >
            <span aria-hidden="true">◈</span><span className="top-bar-label">密码库</span>
            {vaultReminderCount > 0 && <span className="vault-shortcut-badge" aria-hidden="true">{vaultReminderCount}</span>}
          </button>
          <button className="compact-new" onClick={focusCapture}>＋ 新建</button>
        </header>

        <main className="main-content">
          {vaultOpen ? <VaultPanel /> : <>
          <div className="page-heading">
            <div><p className="eyebrow">{copy.eyebrow}</p><h1>{copy.title}</h1></div>
            <span>
              {activeType === "review" && reviewQueue
                ? `今日计划 ${reviewScheduledCount} 条 · 待处理 ${reviewDueCount} 条`
                : activeType === "inbox"
                  ? `${currentResultCount} 条待整理`
                : activeType === "trash"
                  ? `${currentResultCount} 条待恢复`
                : activeType === "resource" && memoCounts !== null
                  ? `${memoCounts.resource_count} 条资料`
                : activeType === "image" && memoCounts !== null
                  ? `${memoCounts.image_count} 张图片`
                  : `${currentResultCount} 条内容`}
            </span>
          </div>

          {activeType === "trash" && (
            <section className="trash-bulk-toolbar" aria-label="回收站批量操作">
              <div>
                <strong>回收站操作</strong>
                <p>共 {trashTotalCount} 条，一键操作覆盖回收站全部内容。</p>
              </div>
              <div className="trash-bulk-actions">
                <button
                  type="button"
                  className="primary"
                  disabled={loadState === "loading" || trashBulkAction !== null || trashTotalCount === 0}
                  onClick={() => void handleTrashBulkAction("restore")}
                >{trashBulkAction === "restore" ? "正在还原…" : "一键还原"}</button>
                <button
                  type="button"
                  className="danger"
                  disabled={loadState === "loading" || trashBulkAction !== null || trashTotalCount === 0}
                  onClick={() => void handleTrashBulkAction("empty")}
                >{trashBulkAction === "empty" ? "正在清空…" : "一键清空"}</button>
              </div>
            </section>
          )}

          {activeType === "all" && !searchQuery.trim() && (
            <QuickAccess
              items={quickAccessItems}
              loaded={quickAccessLoaded}
              onOpen={handleResourceOpened}
              onRemove={(memo) => void changeQuickAccessHidden(memo, true)}
            />
          )}

          {activeType === "all" && !searchQuery.trim() && reviewQueue && (
            <section className="today-review-card">
              <div>
                <p className="eyebrow">今日回顾</p>
                <h2>今天计划 {reviewScheduledCount} 条</h2>
                <div className="today-review-stats">
                  <span>{reviewQueue.word_count} 个单词</span>
                  <span>{reviewQueue.resource_count} 篇待读</span>
                  <button
                    type="button"
                    className="today-review-inbox-link"
                    onClick={() => switchType("inbox")}
                  >
                    {reviewQueue.idea_count} 条待整理
                  </button>
                </div>
              </div>
              <button
                type="button"
                className="today-review-start"
                onClick={() => switchType("review")}
                disabled={reviewScheduledCount === 0}
              >
                {reviewScheduledCount === 0 ? "今天已完成" : "开始回顾"}
              </button>
            </section>
          )}

          {activeType === "review" && (
            <ReviewPanel
              queue={reviewQueue}
              filter={reviewFilter}
              loading={loadState === "loading"}
              busy={reviewBusy}
              onFilterChange={(nextFilter) => {
                setReviewFilter(nextFilter);
                void loadReviewQueue(nextFilter);
              }}
              onSkip={(memo) => void handleReviewSkip(memo)}
              onReviewWord={(memo, feedback) => void handleReviewWord(memo, feedback)}
              onOpenResource={(memo) => void handleReviewOpenResource(memo)}
              onStarResource={(memo) => void handleReviewStarResource(memo)}
              onOrganizeIdea={(memo, title, body) =>
                void handleReviewOrganizeIdea(memo, title, body)
              }
              onArchiveIdea={(memo) => void handleReviewArchiveIdea(memo)}
              reviewSettings={reviewSettings}
              reviewSettingsBusy={reviewSettingsBusy}
              onSaveReviewSettings={handleSaveReviewSettings}
            />
          )}

          {activeType === "image" && (
            <section className="image-capture-card" aria-label="收藏图片">
              <input
                ref={imageInputRef}
                className="sr-only"
                type="file"
                accept="image/*"
                multiple
                aria-label="选择图片文件"
                onChange={(event) => {
                  const files = Array.from(event.target.files ?? []);
                  event.target.value = "";
                  if (files.length > 0) {
                    queueImageFiles(files);
                  }
                }}
              />
              <div
                className={`image-dropzone${imageDragActive ? " dragging" : ""}`}
                role="button"
                tabIndex={0}
                onClick={() => imageInputRef.current?.click()}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    imageInputRef.current?.click();
                  }
                }}
                onDragOver={(event) => {
                  event.preventDefault();
                  setImageDragActive(true);
                }}
                onDragEnter={(event) => {
                  event.preventDefault();
                  setImageDragActive(true);
                }}
                onDragLeave={(event) => {
                  if (event.currentTarget.contains(event.relatedTarget as Node)) {
                    return;
                  }
                  setImageDragActive(false);
                }}
                onDrop={(event) => {
                  event.preventDefault();
                  setImageDragActive(false);
                  queueImageFiles(Array.from(event.dataTransfer.files));
                }}
              >
                <span className="image-dropzone-icon" aria-hidden="true">▧</span>
                <strong>点击选择、拖入或按 Ctrl/⌘+V 粘贴图片</strong>
                <span>
                  支持 PNG、JPEG、WebP、GIF，单张不超过 20 MB，可一次选择多张。
                </span>
              </div>
              {imageUploadTasks.length > 0 && (
                <ul className="image-upload-list">
                  {imageUploadTasks.map((task) => (
                    <li className={`image-upload-item ${task.status}`} key={task.id}>
                      <span className="image-upload-name">{task.name}</span>
                      <span className="image-upload-state">
                        {task.status === "pending" && "等待上传"}
                        {task.status === "uploading" && "正在上传…"}
                        {task.status === "done" && "已收藏"}
                        {task.status === "error" && (task.error ?? "上传失败")}
                      </span>
                      {task.note && (
                        <span className="image-upload-note">{task.note}</span>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </section>
          )}

          {activeType !== "all" && activeType !== "review" && activeType !== "inbox" && activeType !== "trash" && activeType !== "image" && (
          <form className="capture-card" onSubmit={handleCreate}>
            <label
              htmlFor={
                activeType === "idea"
                  ? "quick-capture"
                  : activeType === "resource" ? "resource-url" : "word-lemma"
              }
            >
              {activeType === "idea"
                ? "快速记录"
                : activeType === "resource" ? "保存网页资料" : "收藏英语单词"}
            </label>
            {captureTypeSuggestion &&
              captureTypeSuggestion.type !== activeType &&
              captureTypeSuggestion.key !== dismissedSuggestionKey && (
                <div className="capture-type-suggestion" role="status">
                  <span>{captureTypeSuggestion.reason}</span>
                  <button
                    type="button"
                    onClick={() => applyCaptureTypeSuggestion(captureTypeSuggestion)}
                  >
                    切换为{viewCopy[captureTypeSuggestion.type].itemLabel}
                  </button>
                  <button
                    type="button"
                    className="capture-type-suggestion-dismiss"
                    aria-label="暂不切换内容类型"
                    onClick={() => setDismissedSuggestionKey(captureTypeSuggestion.key)}
                  >
                    暂不
                  </button>
                </div>
              )}
            {activeType === "resource" && (
              <div className="resource-fields">
                <input
                  id="resource-url"
                  ref={urlRef}
                  value={newUrl}
                  onChange={(event) => setNewUrl(event.target.value)}
                  placeholder="粘贴网址，例如 https://example.com/article"
                  inputMode="url"
                  autoCapitalize="none"
                  maxLength={2_048}
                />
                <input
                  value={newTitle}
                  onChange={(event) => setNewTitle(event.target.value)}
                  placeholder="标题（可选）"
                  maxLength={200}
                />
              </div>
            )}
            {activeType === "resource" && webAttachment && (
              <div className="web-attachment-card">
                {webAttachment.favicon_url ? (
                  <img
                    src={webAttachment.favicon_url}
                    alt=""
                    onError={(event) => {
                      event.currentTarget.style.display = "none";
                    }}
                  />
                ) : (
                  <span className="web-attachment-icon">↗</span>
                )}
                <span>
                  <em>@网页</em>
                  <strong>{webAttachment.page_title}</strong>
                  <small>{sourceHost(webAttachment.page_url)} · {webAttachment.page_url}</small>
                </span>
                <button type="button" aria-label="移除网页附件" onClick={removeWebAttachment}>×</button>
              </div>
            )}
            {activeType === "resource" && webAttachmentHelp && !webAttachment && (
              <div className="web-attachment-help">
                <div className="web-attachment-help-copy">
                  <strong>@网页暂未读取到可收藏的网页</strong>
                  <span>这不代表扩展未安装。请先打开普通公网 HTTP(S) 网页，再输入 @ 重试；浏览器设置页、新标签页和本地页面不会出现在列表中。</span>
                  <small>已安装扩展：请确认扩展已启用、允许访问本站，并刷新 MemoIsle 页面。更新扩展文件后需在扩展管理中点击重新加载。</small>
                </div>
                <div className="web-attachment-help-actions">
                  <a
                    href={browserExtensionDownloadUrl()}
                    download={browserExtensionArchiveFilename()}
                  >下载扩展</a>
                  <button
                    type="button"
                    onClick={() => {
                      setWebAttachmentHelp(false);
                      urlRef.current?.focus();
                    }}
                  >粘贴网址</button>
                </div>
              </div>
            )}
            {activeType === "word" && (
              <div className="word-fields">
                <input
                  id="word-lemma"
                  ref={wordRef}
                  value={newTitle}
                  onChange={(event) => {
                    setNewTitle(event.target.value);
                    clearWordLookup();
                  }}
                  onPaste={(event) => {
                    const text = event.clipboardData.getData("text");
                    const draft = parseClipboardWord(text);
                    if (!draft || (!draft.phonetic && !draft.meaning)) {
                      return;
                    }
                    event.preventDefault();
                    setNewTitle(draft.lemma);
                    clearWordLookup();
                    if (draft.phonetic) {
                      setNewPhonetic(draft.phonetic);
                    }
                    if (draft.meaning) {
                      setNewBody(draft.meaning);
                    }
                    setMessage(`已从剪贴板填入「${draft.lemma}」，确认后保存。`);
                  }}
                  placeholder="单词或短语，输入后自动填入中文释义"
                  autoCapitalize="none"
                  maxLength={200}
                />
                <div className="word-phonetic-play-row">
                  <input
                    value={newPhonetic}
                    onChange={(event) => setNewPhonetic(event.target.value)}
                    placeholder="音标（输入后点右侧播放）"
                    maxLength={120}
                  />
                  <WordPronunciation
                    lemma={newTitle}
                    usAudioUrl={wordLookup?.us_audio_url}
                    ukAudioUrl={wordLookup?.uk_audio_url}
                  />
                </div>
              </div>
            )}
            {activeType === "word" && (
              <>
                <div className="word-lookup-toolbar">
                  <span className="word-lookup-hint">
                    {wordLookupBusy
                      ? "正在填入中文释义、音标和例句…"
                      : "输入单词后自动填入中文释义、音标和例句"}
                  </span>
                  <button
                    type="button"
                    className="word-lookup-button"
                    disabled={!newTitle.trim() || wordLookupBusy || creating}
                    onClick={() => void handleLookupWord()}
                  >
                    {wordLookupBusy ? "正在查词…" : "重新查词"}
                  </button>
                  {wordLookup && (
                    <button
                      type="button"
                      className="word-lookup-clear"
                      onClick={clearWordLookup}
                    >
                      清除预览
                    </button>
                  )}
                </div>
                {wordLookup && (
                  <WordDictionaryPreview
                    preview={wordLookup}
                    selectedIndices={wordLookupSelection}
                    busy={wordLookupBusy || creating}
                    onToggle={(index) => {
                      setWordLookupSelection((current) =>
                        current.includes(index)
                          ? current.filter((item) => item !== index)
                          : [...current, index],
                      );
                    }}
                    onApply={applyWordLookup}
                    onClose={clearWordLookup}
                  />
                )}
              </>
            )}
            <div className="capture-textarea-area">
              <textarea
                id="quick-capture"
                ref={captureRef}
                value={newBody}
                onChange={(event) => handleCaptureBodyChange(event.target.value)}
                placeholder={
                  activeType === "idea"
                    ? "写下此刻的想法，稍后再整理……"
                    : activeType === "resource"
                      ? "添加备注，输入 @ 后可继续打字筛选当前浏览器打开的网页"
                      : "中文释义（输入单词后自动填入，也可手改）"
                }
                rows={activeType === "idea" ? 3 : 2}
                maxLength={50_000}
              />
              {activeType === "resource" && webCommandOpen && (
                <div className="capture-command-menu" role="menu">
                  <div className="capture-command-heading">
                    <strong>
                      {webMentionQuery
                        ? `@网页 · 匹配“${webMentionQuery}”`
                        : "@网页 · 当前浏览器"}
                    </strong>
                    <small>
                      {webMentionQuery
                        ? "按标题、网址或站点名筛选，点选后即可附加"
                        : "选择当前浏览器打开的网页，不限标签页 · 按 Ctrl/⌘+Shift+Alt+B 直接收藏最近浏览的网页"}
                    </small>
                  </div>
                  {openBrowserTabsLoading && (
                    <div className="capture-command-empty">正在读取当前浏览器网页……</div>
                  )}
                  {!openBrowserTabsLoading &&
                    matchedOpenBrowserTabs.map((tab) => (
                    <div className="capture-open-tab" key={tab.id}>
                      <button
                        type="button"
                        role="menuitem"
                        className="capture-open-tab-select"
                        onClick={() => chooseOpenBrowserTab(tab)}
                      >
                        {tab.favicon_url ? (
                          <img src={tab.favicon_url} alt="" />
                        ) : (
                          <span className="capture-command-icon">↗</span>
                        )}
                        <span>
                          <strong>
                            {highlightMentionMatch(tab.page_title, webMentionQuery)}
                          </strong>
                          <small>
                            {highlightMentionMatch(
                              sourceHost(tab.page_url),
                              webMentionQuery,
                            )}{" "}
                            · 最近同步 {timeFormatter.format(new Date(tab.last_seen_at))}
                          </small>
                        </span>
                      </button>
                    </div>
                  ))}
                  {!openBrowserTabsLoading &&
                    openBrowserTabs.length > 0 &&
                    matchedOpenBrowserTabs.length === 0 && (
                    <div className="capture-command-empty">
                      <span>没有标题或网址包含“{webMentionQuery}”的打开网页</span>
                    </div>
                  )}
                  {!openBrowserTabsLoading &&
                    openBrowserTabs.length === 0 &&
                    openBrowserTabsError && (
                    <div className="capture-command-empty">
                      <span>无法读取当前浏览器网页：{openBrowserTabsError}</span>
                      <button type="button" onClick={showBrowserPageHelp}>查看连接方式</button>
                    </div>
                  )}
                  {!openBrowserTabsLoading &&
                    openBrowserTabs.length === 0 &&
                    !openBrowserTabsError && (
                    <div className="capture-command-empty">
                      <span>未发现当前浏览器打开的网页</span>
                      <button type="button" onClick={showBrowserPageHelp}>查看连接方式</button>
                    </div>
                  )}
                </div>
              )}
            </div>
            {activeType === "word" && (
              <textarea
                className="word-example"
                value={newExample}
                onChange={(event) => setNewExample(event.target.value)}
                placeholder="例句（输入单词后自动填入，也可手改）"
                rows={2}
                maxLength={5_000}
              />
            )}
            {activeType === "word" && (
              <button
                type="button"
                className="clipboard-fill"
                onClick={() => void fillWordFromClipboard({ overwrite: true, silent: false })}
              >
                从剪贴板填入
              </button>
            )}
            <div className="capture-footer">
              <div className="capture-types" aria-label="内容类型">
                <button
                  type="button"
                  className={activeType === "idea" ? "type-pill active" : "type-pill"}
                  onClick={() => switchType("idea")}
                >✦ 灵感</button>
                <button
                  type="button"
                  className={activeType === "word" ? "type-pill active" : "type-pill"}
                  onClick={enterWordCapture}
                >Aa 单词</button>
                <button
                  type="button"
                  className={activeType === "resource" ? "type-pill active" : "type-pill"}
                  onClick={() => switchType("resource")}
                >↗ 资料</button>
                <button
                  type="button"
                  className="type-pill voice-pill"
                  onClick={() => setVoicePanelOpen(true)}
                >● 语音</button>
              </div>
              <button
                type="submit"
                disabled={
                  creating ||
                  (activeType === "idea"
                    ? !newBody.trim()
                    : activeType === "resource" ? !newUrl.trim() : !newTitle.trim())
                }
              >
                {creating ? "保存中…" : `保存${copy.itemLabel}`}
              </button>
            </div>
          </form>
          )}

          {activeType === "resource" && (
            <div className="resource-library-tools">
              <div>
                <strong>整理工具</strong>
                <span>导入书签、巡检失效链接、管理分类</span>
              </div>
              <span className="resource-tool-actions">
                <button type="button" onClick={() => setHealthCenterOpen(true)}>
                  ! 网页巡检{healthIssueCount > 0 ? ` ${healthIssueCount}` : ""}
                </button>
                <button type="button" onClick={() => setBookmarkImportOpen(true)}>
                  ⇧ 导入浏览器书签
                </button>
                <button type="button" onClick={() => setCloudAccountOpen(true)}>
                  ☁ 云盘绑定
                </button>
                <button type="button" onClick={() => setEbookCollectOpen(true)}>
                  ▤ 收藏电子书
                </button>
                <button
                  type="button"
                  aria-expanded={categorySettingsOpen}
                  aria-controls="category-settings-panel"
                  onClick={() => setCategorySettingsOpen((open) => !open)}
                >
                  ⚙ 分类模板
                </button>
                <button
                  type="button"
                  aria-expanded={classificationToolsOpen}
                  aria-controls="classification-tools"
                  onClick={() => setClassificationToolsOpen((open) => !open)}
                >
                  ✦ 智能分类{classificationReviewCount > 0 ? ` · 待确认 ${classificationReviewCount}` : ""}
                </button>
              </span>
            </div>
          )}

          {activeType === "resource" && categorySettingsOpen && (
            <section
              id="category-settings-panel"
              ref={categorySettingsRef}
              className="category-settings-panel"
              aria-label="自定义分类模板和规则"
            >
              <CategoryTemplatePanel
                categories={resourceCategories}
                rules={categoryRules}
                loading={categorySettingsLoading}
                onRefresh={refreshCategorySettings}
              />
            </section>
          )}

          {/* 折叠时保持挂载，后台分类进度与待确认数仍会刷新。 */}
          {activeType === "resource" && (
            <div id="classification-tools" hidden={!classificationToolsOpen}>
              <ResourceClassificationPanel
                onChanged={() => {
                  void loadCurrentMemos(false);
                  void refreshMemoCounts();
                }}
                onReviewCount={setClassificationReviewCount}
              />
              <CategoryGenerator
                categories={resourceCategories}
                onAdded={refreshCategorySettings}
              />
            </div>
          )}

          {activeType === "image" && <ImageOrganizationPanel
            selected={memos.filter((memo) => batchSelection.has(memo.id)).map((memo) => batchSelection.get(memo.id)!)}
            onChanged={() => { void loadCurrentMemos(false); void refreshMemoCounts(); }} />}

          {message && (
            <div className="status-message" role="status">
              <span>{message}</span>
              {undoMemo && !duplicateWord && !duplicateResource && (
                <button type="button" onClick={() => void handleUndoSave()}>撤销</button>
              )}
              {quickAccessUndo?.message === message && (
                <button
                  type="button"
                  onClick={() => void changeQuickAccessHidden(quickAccessUndo.memo, false)}
                >撤销</button>
              )}
              {duplicateWord && (
                <span className="status-actions">
                  <button type="button" onClick={handleViewDuplicateWord}>查看</button>
                  <button type="button" onClick={() => void handleMergeDuplicateWord()}>合并例句</button>
                  <button type="button" onClick={() => void handleForceDuplicateWord()}>仍然保存</button>
                </span>
              )}
              {duplicateResource && (
                <span className="status-actions">
                  <button type="button" onClick={handleViewDuplicateResource}>查看已有</button>
                  <button type="button" onClick={() => void handleForceDuplicateResource()}>仍然保存</button>
                </span>
              )}
            </div>
          )}

          {activeType === "resource" && !resourceQuery.trim() && resourcePage === 1 && (
            <QuickAccess
              compact
              items={quickAccessItems.slice(0, 4)}
              loaded={quickAccessLoaded}
              onOpen={handleResourceOpened}
              onRemove={(memo) => void changeQuickAccessHidden(memo, true)}
            />
          )}

          {activeType !== "review" && (
          <section className="recent-section" aria-labelledby="recent-title">
            <div className="section-heading">
              <h2 id="recent-title">
                {viewQuery.trim()
                  ? `“${viewQuery.trim()}”的搜索结果`
                  : activeType === "resource" ? "收藏列表" : copy.title}
              </h2>
              <div className="section-actions">
                {activeType === "image" && <select aria-label="筛选图片分类" value={imageCategoryFilter}
                  disabled={batchBusy} onChange={(event) => { setImageCategoryFilter(event.target.value); setResourcePage(1); }}>
                  <option value="">全部分类</option>
                  {resourceCategories.filter((item) => item.is_active).map((item) =>
                    <option key={item.code} value={item.code}>{item.path || item.name}</option>)}
                </select>}
                <label>
                  <span className="sr-only">排序方式</span>
                  <select
                    value={memoSort === "opened_desc" && activeType !== "resource" ? "updated_desc" : memoSort}
                    onChange={(event) => {
                      setMemoSort(event.target.value as MemoSort);
                      setResourcePage(1);
                    }}
                  >
                    <option value="updated_desc">最近更新</option>
                    <option value="updated_asc">最早更新</option>
                    <option value="created_desc">最近收藏</option>
                    <option value="created_asc">最早收藏</option>
                    <option value="title_asc">标题 A–Z</option>
                    <option value="title_desc">标题 Z–A</option>
                    {activeType === "resource" && <option value="opened_desc">最常打开</option>}
                  </select>
                </label>
                {activeType === "resource" && (
                  <span className="view-switch" aria-label="资料显示方式">
                    <button
                      className={resourceViewMode === "list" ? "active" : ""}
                      onClick={() => setResourceViewMode("list")}
                      aria-label="列表视图"
                      title="列表视图"
                    >☷</button>
                    <button
                      className={resourceViewMode === "cards" ? "active" : ""}
                      onClick={() => setResourceViewMode("cards")}
                      aria-label="卡片视图"
                      title="卡片视图"
                    >▦</button>
                  </span>
                )}
                {activeType === "resource" && (
                  <button
                    type="button"
                    className="shortcut-help-button"
                    onClick={() => setShortcutHelpOpen(true)}
                    title="查看键盘快捷键（?）"
                  >⌨ 快捷键</button>
                )}
                <button onClick={() => void loadCurrentMemos()}>刷新</button>
              </div>
            </div>
            {activeType === "resource" && (
              <div className="resource-filter-panel" aria-label="资料组合筛选">
                <div className="resource-search">
                  <span aria-hidden="true">⌕</span>
                  <input
                    ref={resourceSearchRef}
                    aria-label="搜索网页收藏"
                    value={resourceQuery}
                    onChange={(event) => setResourceQuery(event.target.value)}
                    placeholder="搜索网页收藏：标题、网址、描述、标签（/）"
                    maxLength={200}
                  />
                  {resourceQuery && (
                    <button
                      type="button"
                      aria-label="清除网页收藏搜索"
                      onClick={() => setResourceQuery("")}
                    >×</button>
                  )}
                </div>
                <div className="category-filter">
                  <span>分类</span>
                  <button
                    className={!resourceCategoryFilter ? "active" : ""}
                    onClick={() => {
                      setResourceCategoryFilter("");
                      setResourcePage(1);
                    }}
                  >全部</button>
                  {resourceCategories
                    .filter((category) => category.is_active)
                    .map((category) => (
                      <button
                        className={
                          resourceCategoryFilter === category.code ? "active" : ""
                        }
                        key={category.code}
                        title={category.path || category.name}
                        style={{
                          marginLeft: `${Math.max(0, categoryDepth(category) - 1) * 8}px`,
                        }}
                        onClick={() => {
                          setResourceCategoryFilter(category.code);
                          setResourcePage(1);
                        }}
                      >{category.path || category.name}</button>
                    ))}
                  <label className="star-filter-toggle">
                    <input
                      type="checkbox"
                      checked={resourceStarredOnly}
                      onChange={(event) => {
                        setResourceStarredOnly(event.target.checked);
                        setResourcePage(1);
                      }}
                    />
                    只看星标
                  </label>
                </div>
                <div className="resource-filter-result-count" role="status">
                  {debouncedResourceQuery
                    ? <>“{debouncedResourceQuery}”找到 <strong>{currentResultCount}</strong> 条资料</>
                    : <>筛选结果 <strong>{currentResultCount}</strong> 条资料</>}
                </div>
              </div>
            )}
            {loadState === "loading" && (
              <div className="state-panel">
                {viewQuery.trim() ? "正在搜索资料库……" : `正在从共享资料库读取${copy.itemLabel}……`}
              </div>
            )}
            {loadState === "error" && (
              <div className="state-panel error-state">
                <p>暂时无法连接资料库。</p>
                <button onClick={() => void loadCurrentMemos()}>重试</button>
              </div>
            )}
            {loadState === "ready" && memos.length === 0 && (
              <div className="state-panel empty-state">
                <span className="empty-icon">{copy.icon}</span>
                <h3>{viewQuery.trim() ? "没有找到匹配内容" : copy.emptyTitle}</h3>
                <p>
                  {viewQuery.trim()
                    ? "换个关键词，或清除搜索后浏览全部收藏。"
                    : copy.emptyBody}
                </p>
              </div>
            )}
            {loadState === "ready" && <MemoBatchToolbar key={activeType} rows={memos} selected={batchSelection}
              trash={activeType === "trash"} onSelection={setBatchSelection} onBusy={setBatchBusy} onChanged={() => {
                void loadCurrentMemos(false); void refreshMemoCounts();
              }} />}
            {loadState === "ready" && memos.length > 0 && activeType === "image" && (
              <div className="image-grid">
                {memos.map((memo) => (
                  <article
                    className={`image-card${memo.id === selectedId ? " selected" : ""}`}
                    key={memo.id}
                    tabIndex={0}
                    onClick={() => selectMemo(memo)}
                    onKeyDown={(event) => {
                      if (event.target !== event.currentTarget) {
                        return;
                      }
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        selectMemo(memo);
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
                        <span className="image-card-empty">尚未上传图片</span>
                      )}
                    </div>
                    <div className="image-card-body">
                      <label className="memo-batch-check" onClick={(event) => event.stopPropagation()}>
                        <input type="checkbox" aria-label={`选择 ${memo.title}`} disabled={batchBusy} checked={batchSelection.has(memo.id)} onChange={() => toggleBatchMemo(memo)} />选择
                      </label>
                      <strong>{memo.starred ? "★ " : ""}{memo.title}</strong>
                      {memo.resource_category_label && <small>分类：{memo.resource_category_label}</small>}
                      <small>
                        {timeFormatter.format(new Date(memo.created_at))} ·{" "}
                        {imageDimensionLabel(memo)}
                      </small>
                      <small>
                        {formatImageBytes(memo.image_size_bytes) || "等待上传文件"}
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
                ))}
              </div>
            )}
            {loadState === "ready" && memos.length > 0 && activeType !== "image" && (
              <div
                className={
                  activeType === "resource" && resourceViewMode === "cards"
                    ? "memo-list card-view"
                    : "memo-list"
                }
              >
                {memos.map((memo) => (
                  <article
                    className={
                      `memo-row${memo.type === "resource" ? " resource-row" : ""}` +
                      (memo.id === selectedId ? " selected" : "")
                    }
                    key={memo.id}
                    data-memo-id={memo.id}
                    onClick={() => {
                      if (activeType !== "trash" && memo.type === "resource") {
                        openResourcePreview(memo);
                      } else if (activeType !== "trash") {
                        selectMemo(memo);
                      }
                    }}
                    onKeyDown={(event) => {
                      if (activeType === "trash" || event.target !== event.currentTarget) {
                        return;
                      }
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        if (memo.type === "resource") {
                          openResourcePreview(memo);
                        } else {
                          selectMemo(memo);
                        }
                      }
                    }}
                    tabIndex={
                      activeType === "trash" ? undefined : 0
                    }
                    >
                    <input className="memo-batch-check" type="checkbox" aria-label={`选择 ${memo.title}`}
                      disabled={batchBusy} checked={batchSelection.has(memo.id)} onClick={(event) => event.stopPropagation()}
                      onChange={() => toggleBatchMemo(memo)} />
                    <span className={`memo-type-icon ${memo.type}`}>
                      {memo.audio_mime_type ? (
                        "●"
                      ) : memo.type === "image" && memo.image_mime_type ? (
                        <MemoImageThumb
                          memoId={memo.id}
                          version={memo.version}
                          alt={memo.title}
                          className="memo-image-thumb"
                        />
                      ) : (
                        viewCopy[memo.type].icon
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
                            handleResourceOpened(memo);
                          }}
                          onAuxClick={(event) => {
                            if (event.button === 1) handleResourceOpened(memo);
                          }}
                        >
                          {memo.title}
                        </a>
                      ) : (
                        <strong>{memo.starred ? "★ " : ""}{memo.title}</strong>
                      )}
                      <span>
                        {memo.type === "resource"
                          ? memo.resource_description ||
                            (memo.body === memo.source_url
                              ? sourceHost(memo.source_url)
                              : memo.body)
                          : memo.type === "word"
                            ? memo.word_phonetic || memo.word_meaning || "等待补充释义"
                            : memo.type === "image"
                              ? memo.body || "图片收藏"
                              : memo.body}
                      </span>
                      {memo.type === "resource" && memo.tags.length > 0 && (
                        <div className="resource-user-tags" aria-label="我的标签">
                          {memo.tags.map((tag) => (
                            <span key={tag} className="resource-user-tag">#{tag}</span>
                          ))}
                        </div>
                      )}
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
                                <span className="memo-open-count">打开 {memo.resource_open_count} 次</span>
                              )}
                              {memo.ebook_path && (
                                <span
                                  className="memo-ebook-badge"
                                  title={memo.ebook_path}
                                >
                                  云盘
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
                            ? `熟悉度 ${memo.familiarity}/5 · 已复习 ${memo.review_count} 次 · 下次 ${
                              memo.next_review_at
                                ? timeFormatter.format(new Date(memo.next_review_at))
                                : "待安排"
                            }`
                            : memo.type === "image"
                              ? memo.image_mime_type
                                ? `图片 · ${imageDimensionLabel(memo)} · ${
                                    formatImageBytes(memo.image_size_bytes) || "处理中"
                                  }`
                                : "尚未上传图片"
                              : memo.audio_mime_type ? "语音灵感" : "灵感"}
                        {memo.type !== "resource" && ` · 版本 ${memo.version}`}
                        {activeType === "trash" &&
                          ` · 还剩 ${trashDaysRemaining(memo)} 天`}
                        {activeType === "inbox" && " · 待整理"}
                      </small>
                    </span>
                    <span className="memo-row-side">
                      <time dateTime={memo.updated_at}>
                        {timeFormatter.format(new Date(memo.updated_at))}
                      </time>
                      {activeType === "inbox" && (
                        <span
                          className="trash-inline-actions"
                          onClick={(event) => event.stopPropagation()}
                        >
                          <button
                            type="button"
                            onClick={() => void handleOrganizeInboxItem(memo)}
                          >
                            整理完成
                          </button>
                          <button
                            type="button"
                            onClick={() => void handleArchiveInboxItem(memo)}
                          >
                            归档
                          </button>
                        </span>
                      )}
                      {activeType === "trash" && (
                        <span
                          className="trash-inline-actions"
                          onClick={(event) => event.stopPropagation()}
                        >
                          <button
                            type="button"
                            onClick={() => void handleRestoreFromTrash(memo)}
                            disabled={trashBulkAction !== null}
                          >
                            恢复
                          </button>
                          <button
                            type="button"
                            className="danger"
                            onClick={() => void handlePermanentDelete(memo)}
                            disabled={trashBulkAction !== null}
                          >
                            永久删除
                          </button>
                        </span>
                      )}
                      {activeType !== "trash" && memo.type === "resource" && (
                        <span
                          className="resource-inline-actions"
                          onClick={(event) => event.stopPropagation()}
                        >
                          <details className="resource-category-picker">
                            <summary
                              title={memoCategoryLabels(memo, resourceCategories).join("、")}
                            >
                              {memoCategoryLabels(memo, resourceCategories).join("、")
                                || "分类中"}
                            </summary>
                            <div className="resource-category-picker-menu">
                              {resourceCategories
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
                                          updatingResourceId === memo.id
                                          || (
                                            !selected
                                            && selectedCodes.length >= MAX_MEMO_CATEGORIES
                                          )
                                        }
                                        onChange={() =>
                                          toggleMemoCategory(memo, category.code)
                                        }
                                      />
                                      {category.path || category.name}
                                    </label>
                                  );
                                })}
                              <small>最多 8 个分类</small>
                            </div>
                          </details>
                          <button
                            type="button"
                            className={memo.starred ? "starred" : ""}
                            aria-label={memo.starred ? "取消星标" : "添加星标"}
                            aria-pressed={memo.starred}
                            title={memo.starred ? "取消星标" : "添加星标"}
                            disabled={updatingResourceId === memo.id}
                            onClick={() =>
                              void updateResourceOrganization(memo, {
                                starred: !memo.starred,
                              })
                            }
                          >
                            {memo.starred ? "★" : "☆"}
                          </button>
                          <button
                            type="button"
                            className="resource-trash-button"
                            aria-label={`将“${memo.title}”移入回收站`}
                            disabled={updatingResourceId === memo.id}
                            onClick={() => void handleMoveToTrash(memo)}
                          >
                            回收站
                          </button>
                        </span>
                      )}
                    </span>
                  </article>
                ))}
              </div>
            )}
            {loadState === "ready" && (
              <nav className="resource-pagination" aria-label={activeType === "resource" ? "网页资料分页" : activeType === "trash" ? "回收站分页" : "内容列表分页"}>
                <label>每页条数<select aria-label="每页条数" value={pageSize} disabled={batchBusy} onChange={(event) => {
                  setPageSize(Number(event.target.value)); setResourcePage(1);
                }}>{[10, 25, 50, 100].map((size) => <option key={size} value={size}>{size} 条</option>)}</select></label>
                <button
                  type="button"
                  disabled={resourcePage === 1 || batchBusy}
                  onClick={() => setResourcePage((page) => Math.max(1, page - 1))}
                >
                  上一页
                </button>
                <span>
                  第 {resourcePage} / {resourcePageCount} 页 · 共 {currentResultCount} 条
                </span>
                <button
                  type="button"
                  disabled={
                    resourcePage >= resourcePageCount ||
                    batchBusy
                  }
                  onClick={() => setResourcePage((page) => page + 1)}
                >
                  下一页
                </button>
              </nav>
            )}
          </section>
          )}
          </>}
        </main>
      </div>

      {selectedMemo && selectedMemo.type === "image" && (
        <aside className="editor-panel image-detail-panel" aria-label="图片详情">
          <div className="editor-header">
            <div>
              <span className="type-label">▧ 图片</span>
              <h2>图片详情</h2>
            </div>
            <button
              className="icon-button"
              aria-label="关闭图片详情"
              onClick={() => setSelectedId(null)}
            >×</button>
          </div>
          <div className="image-detail-preview">
            {selectedMemo.image_mime_type ? (
              (imagePreviewUrl || imageFullUrl) && !imagePreviewFailed ? (
                <img
                  src={imageFullUrl || imagePreviewUrl}
                  alt={selectedMemo.title}
                  onError={() => {
                    if (imageFullUrl) {
                      setImageFullUrl("");
                      return;
                    }
                    setImagePreviewFailed(true);
                  }}
                />
              ) : (
                <div className="image-preview-loading">
                  {imagePreviewBusy
                    ? "正在读取图片……"
                    : imagePreviewFailed
                      ? "图片读取失败，可尝试查看原图或替换图片。"
                      : "暂时无法显示图片"}
                </div>
              )
            ) : (
              <div className="image-preview-empty">
                <span>这张图片还没有上传文件。</span>
                <button
                  type="button"
                  onClick={() => imageReplaceInputRef.current?.click()}
                  disabled={replaceImageBusy}
                >
                  {replaceImageBusy ? "上传中…" : "上传图片"}
                </button>
              </div>
            )}
          </div>
          <ResourceClassificationInsight memo={selectedMemo} />
          <div className="image-detail-toolbar">
            <label>图片分类<select aria-label="图片分类" value={selectedMemo.resource_category || ""}
              disabled={updatingResourceId === selectedMemo.id || replaceImageBusy}
              onChange={(event) => void updateResourceOrganization(selectedMemo, { resource_categories: event.target.value ? [event.target.value] : [] })}>
              <option value="">未分类</option>{resourceCategories.filter((item) => item.is_active).map((item) => <option key={item.code} value={item.code}>{item.path || item.name}</option>)}
              {selectedMemo.resource_category && !resourceCategories.some((item) => item.code === selectedMemo.resource_category && item.is_active) &&
                <option value={selectedMemo.resource_category} disabled>{selectedMemo.resource_category_label || selectedMemo.resource_category}（已停用）</option>}
            </select></label>
            <span className="image-detail-meta">{imageInfoLabel(selectedMemo)}</span>
            {selectedMemo.image_mime_type && (
              <span className="image-detail-actions">
                <button
                  type="button"
                  onClick={() => void handleViewOriginal(selectedMemo)}
                  disabled={imagePreviewBusy}
                >
                  查看原图
                </button>
                <button
                  type="button"
                  onClick={() => void handleDownloadImage(selectedMemo)}
                  disabled={imagePreviewBusy}
                >
                  下载
                </button>
              </span>
            )}
          </div>
          <div className="image-ocr-section">
            <div className="image-ocr-header">
              <span className="image-ocr-title">图片文字识别</span>
              <span
                className={`image-ocr-status ${selectedMemo.image_ocr_status}`}
              >
                {IMAGE_OCR_STATUS_LABELS[selectedMemo.image_ocr_status] ?? "未识别"}
              </span>
            </div>
            {selectedMemo.image_ocr_status === "ready" && (
              <p className="image-ocr-meta">
                {[
                  imageOcrSourceLabel(selectedMemo.image_ocr_source),
                  selectedMemo.image_ocr_updated_at
                    ? `更新于 ${timeFormatter.format(new Date(selectedMemo.image_ocr_updated_at))}`
                    : "",
                ]
                  .filter((part) => part.length > 0)
                  .join(" · ") || "识别完成"}
              </p>
            )}
            {(selectedMemo.image_ocr_status === "failed" ||
              selectedMemo.image_ocr_status === "disabled") &&
              selectedMemo.image_ocr_error && (
                <p className="image-ocr-error" role="alert">
                  {selectedMemo.image_ocr_error}
                </p>
              )}
            {selectedMemo.image_ocr_status === "ready" &&
              (selectedMemo.image_ocr_text?.trim() ? (
                <pre className="image-ocr-text">
                  {selectedMemo.image_ocr_text}
                </pre>
              ) : (
                <p className="image-ocr-empty">没有识别到文字</p>
              ))}
            {(selectedMemo.image_auto_tags ?? []).length > 0 && (
              <div className="image-ocr-tags">
                {(selectedMemo.image_auto_tags ?? []).map((tag) => (
                  <button
                    type="button"
                    key={tag}
                    className="image-ocr-tag"
                    title={`搜索标签「${tag}」`}
                    onClick={() => handleImageOcrTagClick(tag)}
                  >
                    #{tag}
                  </button>
                ))}
              </div>
            )}
            <div className="image-ocr-actions">
              <button
                type="button"
                onClick={() => void handleRecognizeImageOcr()}
                disabled={
                  ocrBusy ||
                  !selectedMemo.image_mime_type ||
                  selectedMemo.image_ocr_status === "pending" ||
                  selectedMemo.image_ocr_status === "processing"
                }
              >
                {ocrBusy
                  ? "识别中…"
                  : selectedMemo.image_ocr_status === "none"
                    ? "识别文字"
                    : "重新识别"}
              </button>
              {ocrError && (
                <span className="image-ocr-error" role="alert">
                  {ocrError}
                </span>
              )}
            </div>
          </div>
          <form onSubmit={handleUpdate}>
            <label>标题
              <input
                value={editorTitle}
                onChange={(event) => setEditorTitle(event.target.value)}
                maxLength={200}
                placeholder="给这张图片起个名字"
              />
            </label>
            <label>备注
              <textarea
                value={editorBody}
                onChange={(event) => setEditorBody(event.target.value)}
                rows={6}
                maxLength={50_000}
                placeholder="记下这张图片的来历或想法（可留空）"
              />
            </label>
            <div className="editor-meta">
              <span>服务端版本 {selectedMemo.version}</span>
              <span>更新于 {timeFormatter.format(new Date(selectedMemo.updated_at))}</span>
            </div>
            <div className="editor-actions">
              <span className={`save-state ${saveState}`}>
                {saveState === "saving" && "正在保存…"}
                {saveState === "saved" && "已保存"}
                {saveState === "error" && "保存失败"}
              </span>
              <button
                type="button"
                className="danger"
                disabled={saveState === "saving"}
                onClick={() => void handleMoveToTrash(selectedMemo)}
              >
                移入回收站
              </button>
              <button
                type="button"
                disabled={replaceImageBusy || saveState === "saving"}
                onClick={() => imageReplaceInputRef.current?.click()}
              >
                {replaceImageBusy ? "替换中…" : "替换图片"}
              </button>
              <button type="submit" disabled={saveState === "saving" || !editorTitle.trim()}>
                保存修改
              </button>
            </div>
            <input
              ref={imageReplaceInputRef}
              className="sr-only"
              type="file"
              accept="image/*"
              aria-label="替换图片文件"
              onChange={(event) => {
                const file = event.target.files?.[0];
                event.target.value = "";
                if (file) {
                  void handleReplaceImage(file);
                }
              }}
            />
          </form>
        </aside>
      )}

      {selectedMemo && selectedMemo.type !== "resource" && selectedMemo.type !== "image" && (
        <aside className="editor-panel" aria-label={`编辑${selectedCopy.itemLabel}`}>
          <div className="editor-header">
            <div>
              <span className="type-label">
                {selectedCopy.icon} {selectedCopy.itemLabel}
              </span>
              <h2>
                {selectedMemo.type === "word" ? "学习单词" : "继续整理"}
              </h2>
            </div>
            <button className="icon-button" aria-label="关闭编辑" onClick={() => setSelectedId(null)}>×</button>
          </div>
          {selectedMemo.audio_mime_type && (
            <div className="audio-player-card">
              <div>
                <strong>原始录音</strong>
                <span>
                  {selectedMemo.audio_duration_ms
                    ? `${Math.round(selectedMemo.audio_duration_ms / 1_000)} 秒`
                    : "语音记录"}
                </span>
              </div>
              <audio controls preload="metadata" src={audioUrl || undefined} />
            </div>
          )}
          {selectedMemo.transcript && (
            <details className="meeting-transcript-card">
              <summary>会议转写（我 / 对方）</summary>
              <pre>{selectedMemo.transcript}</pre>
            </details>
          )}
          <form onSubmit={handleUpdate}>
            <label>
              内容类型
              <select
                value={selectedMemo.type}
                disabled={typeChangingId === selectedMemo.id || saveState === "saving"}
                onChange={(event) =>
                  void handleChangeMemoType(
                    selectedMemo,
                    event.target.value as MemoType,
                  )
                }
              >
                <option value="idea">灵感</option>
                <option value="word">英语单词</option>
                <option value="resource" disabled={!selectedMemo.source_url}>
                  网页资料{selectedMemo.source_url ? "" : "（需要网址）"}
                </option>
              </select>
            </label>
            <label>{selectedMemo.type === "word" ? "单词或短语" : "标题"}
              <input value={editorTitle} onChange={(event) => setEditorTitle(event.target.value)} maxLength={200} />
            </label>
            {selectedMemo.type === "word" && (
              <>
                <p className="review-schedule">
                  上次复习 {selectedMemo.last_review_at
                    ? timeFormatter.format(new Date(selectedMemo.last_review_at))
                    : "尚未复习"}
                  {" · "}
                  下次 {selectedMemo.next_review_at
                    ? timeFormatter.format(new Date(selectedMemo.next_review_at))
                    : "待安排"}
                </p>
                <label>音标（点右侧播放）
                  <div className="word-phonetic-play-row">
                    <input
                      value={editorPhonetic}
                      onChange={(event) => setEditorPhonetic(event.target.value)}
                      maxLength={120}
                      placeholder="音标（可选）"
                    />
                    <WordPronunciation
                      lemma={editorTitle || selectedMemo.title}
                      usAudioUrl={selectedMemo.word_us_audio_url}
                      ukAudioUrl={selectedMemo.word_uk_audio_url}
                    />
                  </div>
                </label>
              </>
            )}
            {selectedMemo.type === "word" && !showWordAnswer ? (
              <div className="word-answer-hidden">
                <span>Aa</span>
                <p>先回想释义和例句，再显示答案。</p>
                <button type="button" onClick={() => setShowWordAnswer(true)}>
                  显示释义与例句
                </button>
              </div>
            ) : (
              <>
            <label>
              {selectedMemo.type === "word" ? "释义" : "内容"}
              <textarea
                value={editorBody}
                onChange={(event) => setEditorBody(event.target.value)}
                rows={12}
                maxLength={50_000}
              />
            </label>
                {selectedMemo.type === "idea" && (
                  <SpeechPronunciation text={editorBody} label="播放内容" />
                )}
                {selectedMemo.type === "word" && (
                  <label>例句或上下文
                    <textarea
                      value={editorExample}
                      onChange={(event) => setEditorExample(event.target.value)}
                      rows={4}
                      maxLength={5_000}
                    />
                  </label>
                )}
                {selectedMemo.type === "word" && (
                  <SpeechPronunciation text={editorExample} label="播放例句" />
                )}
                {selectedMemo.type === "word" && (
                  <div className="review-panel">
                    <div>
                      <strong>这次记得怎么样？</strong>
                      <span>熟悉度 {selectedMemo.familiarity}/5</span>
                    </div>
                    <div className="review-actions">
                      <button type="button" disabled={reviewing} onClick={() => void handleReview("forgot")}>忘记</button>
                      <button type="button" disabled={reviewing} onClick={() => void handleReview("fuzzy")}>模糊</button>
                      <button type="button" disabled={reviewing} onClick={() => void handleReview("remembered")}>记得</button>
                    </div>
                  </div>
                )}
              </>
            )}
            <div className="editor-meta">
              <span>服务端版本 {selectedMemo.version}</span>
              <span>更新于 {timeFormatter.format(new Date(selectedMemo.updated_at))}</span>
            </div>
            <div className="editor-actions">
              <span className={`save-state ${saveState}`}>
                {saveState === "saving" && "正在保存…"}
                {saveState === "saved" && "已保存"}
                {saveState === "error" && "保存失败"}
              </span>
              <button
                type="button"
                className="danger"
                disabled={saveState === "saving"}
                onClick={() => void handleMoveToTrash(selectedMemo)}
              >
                移入回收站
              </button>
              {selectedMemo.status === "inbox" && (
                <>
                  <button
                    type="button"
                    disabled={saveState === "saving"}
                    onClick={() => void handleArchiveInboxItem(selectedMemo)}
                  >
                    归档
                  </button>
                  <button
                    type="button"
                    disabled={
                      saveState === "saving" ||
                      (selectedMemo.type === "idea" && !editorBody.trim())
                    }
                    onClick={() => void handleOrganizeInboxItem(selectedMemo)}
                  >
                    整理完成
                  </button>
                </>
              )}
              <button
                type="submit"
                disabled={
                  saveState === "saving" || !editorTitle.trim() ||
                  (selectedMemo.type === "idea"
                    ? !editorBody.trim()
                    : false)
                }
              >保存修改</button>
            </div>
          </form>
        </aside>
      )}

      {resourcePreviewMemo && (
        <ResourcePreviewDialog
          memo={resourcePreviewMemo}
          categoryLabels={memoCategoryLabels(resourcePreviewMemo, resourceCategories)}
          busy={updatingResourceId === resourcePreviewMemo.id}
          typeChanging={typeChangingId === resourcePreviewMemo.id}
          onClose={closeResourcePreview}
          onSave={(changes) => saveResourceEdits(resourcePreviewMemo, changes)}
          onCopyLink={() => void handleCopyResourceLink(resourcePreviewMemo)}
          onArchive={() => void handleArchiveResource(resourcePreviewMemo)}
          onTrash={() => void handleMoveToTrash(resourcePreviewMemo)}
          onChangeType={(type) => void handleChangeMemoType(resourcePreviewMemo, type)}
          onTagSearch={handleResourceTagSearch}
          onOpenSource={openPreviewSource}
          onQuickAccessHiddenChange={(hidden) =>
            void changeQuickAccessHidden(resourcePreviewMemo, hidden)}
          initialEditing={resourcePreviewEditing}
        />
      )}

      {shortcutHelpOpen && <ShortcutHelpDialog onClose={closeShortcutHelp} />}

      {conflictMemo && (
        <div className="conflict-backdrop">
          <section
            className="conflict-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="conflict-title"
          >
            <div className="conflict-dialog-header">
              <div>
                <span className="type-label">! 编辑冲突</span>
                <h2 id="conflict-title">发现其他设备的修改</h2>
              </div>
              <button
                className="icon-button"
                aria-label="稍后处理编辑冲突"
                onClick={() => setConflictMemo(null)}
              >×</button>
            </div>
            <p>
              “{conflictMemo.title}”已经在其他设备更新。当前编辑框中的修改仍然保留，
              请选择要继续使用的版本。
            </p>
            <div className="conflict-actions">
              <button type="button" onClick={useServerConflict}>
                采用服务端版本
              </button>
              <button type="button" className="primary" onClick={keepLocalConflict}>
                保留我的修改
              </button>
            </div>
            <button
              type="button"
              className="conflict-later"
              onClick={() => setConflictMemo(null)}
            >
              稍后处理
            </button>
          </section>
        </div>
      )}

      {voicePanelOpen && (
        <div className="voice-backdrop" role="presentation">
          <section className="voice-dialog" role="dialog" aria-modal="true" aria-labelledby="voice-title">
            <div className="voice-dialog-header">
              <div>
                <span className="type-label">● 语音灵感</span>
                <h2 id="voice-title">记录此刻的想法</h2>
              </div>
              <button
                type="button"
                className="icon-button"
                aria-label="关闭语音记录"
                disabled={voiceState === "saving"}
                onClick={requestVoiceClose}
              >×</button>
            </div>

            <div
              className={`voice-orb ${
                voiceState === "recording"
                  ? "recording"
                  : voiceState === "paused" ? "paused" : ""
              }`}
            >
              <span>●</span>
              <strong>{voiceSeconds} 秒</strong>
              <small>
                {voiceState === "recording"
                  ? "正在录音"
                  : voiceState === "paused"
                    ? "已暂停"
                  : voiceState === "ready" ? "录音已就绪" : "等待开始"}
              </small>
            </div>

            <div className="voice-meter" aria-label={`输入音量 ${voiceVolume}%`}>
              <span>输入音量</span>
              <div className="voice-meter-track" aria-hidden="true">
                <span style={{ width: `${voiceVolume}%` }} />
              </div>
              <strong>{voiceVolume}%</strong>
            </div>

            <label className="voice-note-label">
              转写/配套文字（可选）
              <textarea
                value={voiceText}
                onChange={(event) => setVoiceText(event.target.value)}
                placeholder="录音时会尝试自动转写，也可以手动补充……"
                rows={4}
                maxLength={50_000}
                disabled={voiceState === "saving"}
              />
            </label>
            {voiceTranscriptionMessage && (
              <p className="voice-transcription-status" aria-live="polite">
                {voiceTranscriptionMessage}
              </p>
            )}

            <div className="voice-actions">
              {voiceState === "idle" && (
                <button className="primary" onClick={() => void startVoiceCapture()}>
                  开始录音
                </button>
              )}
              {voiceState === "requesting" && <button disabled>正在请求麦克风权限…</button>}
              {(voiceState === "recording" || voiceState === "paused") && (
                <>
                  <button
                    type="button"
                    onClick={voiceState === "recording" ? pauseVoiceCapture : resumeVoiceCapture}
                  >
                    {voiceState === "recording" ? "暂停" : "继续"}
                  </button>
                  <button type="button" className="stop" onClick={stopVoiceCapture}>
                    结束录音
                  </button>
                </>
              )}
              {voiceState === "ready" && (
                <>
                  <button type="button" onClick={resetVoiceCapture}>重新录制</button>
                  <button type="button" className="primary" onClick={() => void saveVoiceCapture()}>
                    保存语音灵感
                  </button>
                </>
              )}
              {voiceState === "saving" && <button disabled>正在保存录音…</button>}
              {voiceState !== "saving" && (
                <button type="button" onClick={requestVoiceClose}>取消</button>
              )}
            </div>
            <p className="voice-privacy">
              Android 使用设备端 SenseVoice；Web 端使用浏览器语音识别（可能由浏览器服务处理）。
              原始录音始终只保存到你的私人资料库。
            </p>
          </section>
        </div>
      )}

      {voiceDiscardConfirmOpen && (
        <div className="voice-discard-backdrop" role="presentation">
          <section
            className="voice-discard-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="voice-discard-title"
          >
            <h2 id="voice-discard-title">放弃这段记录？</h2>
            <p>录音和当前文字不会保存，确定要放弃吗？</p>
            <div className="voice-discard-actions">
              <button type="button" onClick={() => setVoiceDiscardConfirmOpen(false)}>
                继续编辑
              </button>
              <button type="button" className="danger" onClick={discardVoiceCapture}>
                放弃记录
              </button>
            </div>
          </section>
        </div>
      )}

      {bookmarkImportOpen && (
        <BookmarkImportDialog
          onClose={() => setBookmarkImportOpen(false)}
          onImported={() => {
            void loadCurrentMemos();
            void refreshMemoCounts();
          }}
        />
      )}

      {healthCenterOpen && (
        <LinkHealthDialog
          onClose={() => setHealthCenterOpen(false)}
          onChanged={() => {
            void refreshHealthSummary();
            void loadCurrentMemos();
            void refreshMemoCounts();
          }}
        />
      )}

      {cloudAccountOpen && (
        <CloudAccountDialog
          onClose={() => setCloudAccountOpen(false)}
          onChanged={() => setMessage("云盘绑定已更新")}
        />
      )}

      {modelSettingsOpen && (
        <ModelSettingsDialog onClose={() => setModelSettingsOpen(false)} />
      )}

      {ebookCollectOpen && (
        <EbookCollectDialog
          onClose={() => setEbookCollectOpen(false)}
          onChanged={() => {
            void loadCurrentMemos();
            void refreshMemoCounts();
          }}
        />
      )}

      <nav className="mobile-navigation" aria-label="移动端主导航">
        <button className={activeType === "all" ? "active" : ""} onClick={() => switchType("all")}>⌂<span>首页</span></button>
        <button className={activeType === "resource" ? "active" : ""} onClick={() => switchType("resource")}>↗<span>资料</span></button>
        <button className={activeType === "image" ? "active" : ""} onClick={() => switchType("image")}>▧<span>图片</span></button>
        <button className="mobile-create" onClick={focusCapture}>＋<span>新建</span></button>
        <button className={activeType === "idea" ? "active" : ""} onClick={() => switchType("idea")}>✦<span>灵感</span></button>
        <button className={activeType === "word" ? "active" : ""} onClick={enterWordCapture}>Aa<span>单词</span></button>
      </nav>
    </div>
  );
}
