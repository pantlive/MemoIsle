import {
  type FormEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import BookmarkImportDialog from "./BookmarkImportDialog";
import { parseClipboardWord } from "./clipboardWord";
import LinkHealthDialog from "./LinkHealthDialog";
import ReviewPanel, { type ReviewQueueFilter } from "./ReviewPanel";
import WordPronunciation from "./WordPronunciation";
import {
  ApiError,
  browserExtensionDownloadUrl,
  createResourceCategory,
  createResourceCategoryRule,
  createMemo,
  deleteResourceCategoryRule,
  exchangeBrowserCapture,
  getResourceCategories,
  getResourceCategoryRules,
  getMemoCounts,
  getLinkHealthCenter,
  getReviewQueue,
  listOpenBrowserTabs,
  listMemos,
  memoAudioUrl,
  mergeWord,
  reviewWord,
  skipReview,
  updateResourceCategory,
  updateMemo,
  uploadMemoAudio,
} from "./api";
import type {
  BrowserCaptureContext,
  BrowserOpenTab,
  Memo,
  MemoCounts,
  MemoSort,
  MemoType,
  ResourceCategory,
  ResourceCategoryOption,
  ResourceCategoryRule,
  ResourceCategoryRuleMatchType,
  ReviewFeedback,
  ReviewQueueResponse,
} from "./types";

type LoadState = "loading" | "ready" | "error";
type SaveState = "idle" | "saving" | "saved" | "error";
type VoiceState = "idle" | "requesting" | "recording" | "ready" | "saving";
type ActiveType = Extract<MemoType, "idea" | "resource" | "word">;
type ActiveView = ActiveType | "all" | "review";
type ResourceViewMode = "list" | "cards";

const RESOURCE_PAGE_SIZE = 10;

interface NavigationItem {
  label: string;
  icon: string;
  view?: ActiveView;
  action?: "health";
}

const navigation: NavigationItem[] = [
  { label: "首页", icon: "⌂", view: "all" },
  { label: "收件箱", icon: "▣" },
  { label: "全部内容", icon: "□", view: "all" },
  { label: "英语单词", icon: "Aa", view: "word" },
  { label: "网页资料", icon: "↗", view: "resource" },
  { label: "网页巡检", icon: "!", action: "health" },
  { label: "灵感", icon: "✦", view: "idea" },
  { label: "回顾", icon: "◷", view: "review" },
];

const timeFormatter = new Intl.DateTimeFormat("zh-CN", {
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

const defaultResourceCategories: ResourceCategoryOption[] = [
  {
    id: null,
    code: "learning",
    name: "学习资料",
    description: null,
    is_system: true,
    is_active: true,
    version: 1,
  },
  {
    id: null,
    code: "article",
    name: "文章阅读",
    description: null,
    is_system: true,
    is_active: true,
    version: 1,
  },
  {
    id: null,
    code: "media",
    name: "视频与音频",
    description: null,
    is_system: true,
    is_active: true,
    version: 1,
  },
  {
    id: null,
    code: "tool",
    name: "工具与服务",
    description: null,
    is_system: true,
    is_active: true,
    version: 1,
  },
  {
    id: null,
    code: "book_paper",
    name: "书籍与论文",
    description: null,
    is_system: true,
    is_active: true,
    version: 1,
  },
  {
    id: null,
    code: "product",
    name: "商品与好物",
    description: null,
    is_system: true,
    is_active: true,
    version: 1,
  },
  {
    id: null,
    code: "other",
    name: "其他",
    description: null,
    is_system: true,
    is_active: true,
    version: 1,
  },
];

const resourceRuleMatchLabels: Record<ResourceCategoryRuleMatchType, string> = {
  domain: "网站域名",
  url: "网址包含",
  text: "标题或描述包含",
};

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
  review: {
    title: "今日回顾",
    eyebrow: "用几分钟再次遇见值得留下的内容",
    icon: "◷",
    itemLabel: "回顾",
    emptyTitle: "今天没有需要回顾的内容",
    emptyBody: "到期单词、未读资料和待整理灵感会显示在这里。",
  },
} as const;

function describeError(error: unknown): string {
  if (error instanceof ApiError && error.status === 409) {
    return "内容已在其他设备更新，已重新载入服务端版本。";
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "操作失败，请稍后重试。";
}

function normalizeWebUrl(value: string): string | null {
  const cleaned = value.trim();
  if (!cleaned) {
    return null;
  }
  const candidate = /^https?:\/\//i.test(cleaned) ? cleaned : `https://${cleaned}`;
  try {
    const parsed = new URL(candidate);
    if (!parsed.hostname || !["http:", "https:"].includes(parsed.protocol)) {
      return null;
    }
    return parsed.toString();
  } catch {
    return null;
  }
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

export default function App() {
  const [activeType, setActiveType] = useState<ActiveView>("all");
  const [memos, setMemos] = useState<Memo[]>([]);
  const [currentResultCount, setCurrentResultCount] = useState(0);
  const [memoCounts, setMemoCounts] = useState<MemoCounts | null>(null);
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [message, setMessage] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [resourceCategoryFilter, setResourceCategoryFilter] = useState<
    ResourceCategory | ""
  >("");
  const [resourceStarredOnly, setResourceStarredOnly] = useState(false);
  const [resourcePage, setResourcePage] = useState(1);
  const [memoSort, setMemoSort] = useState<MemoSort>("updated_desc");
  const [resourceViewMode, setResourceViewMode] =
    useState<ResourceViewMode>("list");
  const [resourceCategories, setResourceCategories] = useState(
    defaultResourceCategories,
  );
  const [categoryRules, setCategoryRules] = useState<ResourceCategoryRule[]>([]);
  const [categorySettingsOpen, setCategorySettingsOpen] = useState(false);
  const [categorySettingsLoading, setCategorySettingsLoading] = useState(false);
  const [categorySubmitting, setCategorySubmitting] = useState(false);
  const [newCategoryName, setNewCategoryName] = useState("");
  const [newCategoryDescription, setNewCategoryDescription] = useState("");
  const [newRuleName, setNewRuleName] = useState("");
  const [newRuleCategory, setNewRuleCategory] = useState("");
  const [newRuleMatchType, setNewRuleMatchType] =
    useState<ResourceCategoryRuleMatchType>("domain");
  const [newRulePattern, setNewRulePattern] = useState("");
  const [newRulePriority, setNewRulePriority] = useState("100");
  const [bookmarkImportOpen, setBookmarkImportOpen] = useState(false);
  const [healthCenterOpen, setHealthCenterOpen] = useState(false);
  const [healthIssueCount, setHealthIssueCount] = useState(0);
  const [reviewQueue, setReviewQueue] = useState<ReviewQueueResponse | null>(null);
  const [reviewFilter, setReviewFilter] = useState<ReviewQueueFilter>("all");
  const [reviewBusy, setReviewBusy] = useState(false);
  const [undoMemo, setUndoMemo] = useState<Memo | null>(null);
  const [wordSourceUrl, setWordSourceUrl] = useState("");
  const [duplicateWord, setDuplicateWord] = useState<Memo | null>(null);
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
    sourceUrl: string | null;
  } | null>(null);
  const [webAttachment, setWebAttachment] = useState<
    BrowserCaptureContext | BrowserOpenTab | null
  >(null);
  const [openBrowserTabs, setOpenBrowserTabs] = useState<BrowserOpenTab[]>([]);
  const [openBrowserTabsLoading, setOpenBrowserTabsLoading] = useState(false);
  const [webAttachmentHelp, setWebAttachmentHelp] = useState(false);
  const [webCommandOpen, setWebCommandOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [updatingResourceId, setUpdatingResourceId] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [editorTitle, setEditorTitle] = useState("");
  const [editorBody, setEditorBody] = useState("");
  const [editorPhonetic, setEditorPhonetic] = useState("");
  const [editorExample, setEditorExample] = useState("");
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [showWordAnswer, setShowWordAnswer] = useState(false);
  const [reviewing, setReviewing] = useState(false);
  const [voicePanelOpen, setVoicePanelOpen] = useState(false);
  const [voiceState, setVoiceState] = useState<VoiceState>("idle");
  const [voiceSeconds, setVoiceSeconds] = useState(0);
  const [voiceText, setVoiceText] = useState("");
  const [voiceBlob, setVoiceBlob] = useState<Blob | null>(null);
  const [voiceDraftMemo, setVoiceDraftMemo] = useState<Memo | null>(null);
  const captureRef = useRef<HTMLTextAreaElement>(null);
  const urlRef = useRef<HTMLInputElement>(null);
  const wordRef = useRef<HTMLInputElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const voiceChunksRef = useRef<Blob[]>([]);
  const voiceStartedAtRef = useRef(0);
  const voiceTimerRef = useRef<number | null>(null);
  const loadRequestRef = useRef(0);
  const captureTokenHandledRef = useRef<string | null>(null);
  const copy = viewCopy[activeType];
  const resourcePageCount = Math.max(
    1,
    Math.ceil(currentResultCount / RESOURCE_PAGE_SIZE),
  );

  const selectedMemo = useMemo(
    () => memos.find((memo) => memo.id === selectedId) ?? null,
    [memos, selectedId],
  );
  const selectedCopy = selectedMemo ? viewCopy[selectedMemo.type] : copy;

  const refreshHealthSummary = useCallback(async () => {
    try {
      const center = await getLinkHealthCenter();
      setHealthIssueCount(center.items.length);
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

  const loadReviewQueue = useCallback(async (filter: ReviewQueueFilter = reviewFilter) => {
    try {
      setReviewQueue(
        await getReviewQueue({
          limit: 10,
          type: filter === "all" ? undefined : filter,
        }),
      );
    } catch (error) {
      setMessage(describeError(error));
    }
  }, [reviewFilter]);

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

  const handleCreateCategory = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const name = newCategoryName.trim();
    if (!name || categorySubmitting) {
      return;
    }
    setCategorySubmitting(true);
    try {
      const category = await createResourceCategory({
        name,
        description: newCategoryDescription.trim() || undefined,
      });
      setResourceCategories((current) => [...current, category]);
      setNewCategoryName("");
      setNewCategoryDescription("");
      setNewRuleCategory(category.code);
      setMessage(`已创建“${category.name}”，现在可以为它添加规则。`);
    } catch (error) {
      setMessage(describeError(error));
    } finally {
      setCategorySubmitting(false);
    }
  };

  const handleToggleCategory = async (category: ResourceCategoryOption) => {
    if (!category.id || categorySubmitting) {
      return;
    }
    setCategorySubmitting(true);
    try {
      const updated = await updateResourceCategory(category.id, {
        expected_version: category.version,
        is_active: !category.is_active,
      });
      setResourceCategories((current) =>
        current.map((item) => (item.code === updated.code ? updated : item)),
      );
      setMessage(
        updated.is_active
          ? `已启用“${updated.name}”。`
          : `已停用“${updated.name}”，已有资料会重新判断。`,
      );
    } catch (error) {
      setMessage(describeError(error));
    } finally {
      setCategorySubmitting(false);
    }
  };

  const handleCreateCategoryRule = async (
    event: FormEvent<HTMLFormElement>,
  ) => {
    event.preventDefault();
    const pattern = newRulePattern.trim();
    const priority = Number.parseInt(newRulePriority, 10);
    if (
      !newRuleCategory ||
      !pattern ||
      !Number.isInteger(priority) ||
      priority < 0 ||
      categorySubmitting
    ) {
      setMessage("请选择分类并填写有效的规则内容和优先级。");
      return;
    }
    setCategorySubmitting(true);
    try {
      const rule = await createResourceCategoryRule({
        name: newRuleName.trim() || undefined,
        category_code: newRuleCategory,
        match_type: newRuleMatchType,
        pattern,
        priority,
      });
      setCategoryRules((current) => [...current, rule]);
      setNewRuleName("");
      setNewRulePattern("");
      setMessage("分类规则已保存，已有网页资料正在按新规则整理。");
    } catch (error) {
      setMessage(describeError(error));
    } finally {
      setCategorySubmitting(false);
    }
  };

  const handleDeleteCategoryRule = async (rule: ResourceCategoryRule) => {
    if (categorySubmitting) {
      return;
    }
    setCategorySubmitting(true);
    try {
      await deleteResourceCategoryRule(rule.id);
      setCategoryRules((current) =>
        current.filter((item) => item.id !== rule.id),
      );
      setMessage("分类规则已删除，相关资料会重新判断。");
    } catch (error) {
      setMessage(describeError(error));
    } finally {
      setCategorySubmitting(false);
    }
  };

  const refreshOpenBrowserTabs = useCallback(async (showLoading = true) => {
    if (showLoading) {
      setOpenBrowserTabsLoading(true);
    }
    try {
      const tabs = await listOpenBrowserTabs();
      setOpenBrowserTabs(tabs);
    } catch {
      // 当前浏览器标签页读取失败时仍保留粘贴网址和一次性捕获入口。
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

  const enterWordCapture = useCallback(() => {
    const alreadyOnWord = activeType === "word";
    if (!alreadyOnWord) {
      setNewTitle("");
      setNewPhonetic("");
      setNewExample("");
      setNewBody("");
      setWordSourceUrl("");
    }
    switchType("word");
    void fillWordFromClipboard({
      overwrite: !alreadyOnWord,
      silent: true,
    });
    window.setTimeout(() => wordRef.current?.focus(), 0);
  }, [activeType, fillWordFromClipboard]);

  const focusCapture = useCallback(() => {
    if (activeType === "all") {
      setActiveType("idea");
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
    if (!token && !captureError) {
      return;
    }
    currentUrl.searchParams.delete("memoisle_capture");
    currentUrl.searchParams.delete("memoisle_capture_error");
    window.history.replaceState({}, "", currentUrl);
    setActiveType("resource");
    setSelectedId(null);
    if (captureError) {
      setWebAttachmentHelp(true);
      setMessage(
        captureError === "unsupported_page"
          ? "当前页面不支持收藏，请在普通公网 HTTP(S) 网页使用扩展。"
          : "扩展暂时无法连接 MemoIsle，可保留备注并改为粘贴网址。",
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
          limit: 10,
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
      const response = await listMemos({
        type: activeType === "all" ? undefined : activeType,
        query: debouncedQuery,
        category: resourceView ? resourceCategoryFilter || undefined : undefined,
        starred: resourceView && resourceStarredOnly ? true : undefined,
        sort: memoSort,
        limit: resourceView ? RESOURCE_PAGE_SIZE : undefined,
        offset: resourceView ? (resourcePage - 1) * RESOURCE_PAGE_SIZE : undefined,
      });
      if (requestId !== loadRequestRef.current) {
        return;
      }
      setMemos(response.items);
      setCurrentResultCount(response.total_count);
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
    memoSort,
    resourceCategoryFilter,
    resourcePage,
    resourceStarredOnly,
    reviewFilter,
  ]);

  useEffect(() => {
    setSelectedId(null);
    setMessage("");
    void loadCurrentMemos();
  }, [loadCurrentMemos]);

  useEffect(() => {
    if (activeType === "all") {
      void loadReviewQueue();
    }
  }, [activeType, loadReviewQueue]);

  useEffect(() => {
    if (activeType !== "resource") {
      return;
    }
    setResourcePage((page) => Math.min(page, resourcePageCount));
  }, [activeType, resourcePageCount]);

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
      const target = event.target as HTMLElement | null;
      const isEditing =
        target?.tagName === "INPUT" || target?.tagName === "TEXTAREA";
      if (isEditing) {
        return;
      }
      if (event.key.toLowerCase() === "n") {
        event.preventDefault();
        focusCapture();
      }
      if (event.key === "/") {
        event.preventDefault();
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
      const recorder = recorderRef.current;
      if (recorder?.state === "recording") {
        recorder.stop();
      }
      recorder?.stream.getTracks().forEach((track) => track.stop());
    };
  }, []);

  const switchType = (type: ActiveView) => {
    setActiveType(type);
    setResourcePage(1);
    setSearchQuery("");
    setDebouncedQuery("");
    setSelectedId(null);
    setSaveState("idle");
    if (type !== "resource") {
      setResourceCategoryFilter("");
      setResourceStarredOnly(false);
    }
  };

  const handleSearchChange = (value: string) => {
    setSearchQuery(value);
    if (value.trim() && activeType !== "all") {
      setActiveType("all");
      setResourceCategoryFilter("");
      setResourceStarredOnly(false);
      setSelectedId(null);
    }
  };

  const handleCaptureBodyChange = (value: string) => {
    setNewBody(value);
    setWebCommandOpen(activeType === "resource" && /(^|\s)@$/.test(value));
  };

  const clearWebCommandMarker = () => {
    setNewBody((current) => current.replace(/(^|\s)@$/, "$1"));
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
    setSelectedId(memo.id);
    setEditorTitle(memo.title);
    setEditorBody(memo.body);
    setEditorPhonetic(memo.word_phonetic ?? "");
    setEditorExample(memo.word_example ?? "");
    if (memo.type === "word") {
      setEditorBody(memo.word_meaning ?? memo.body);
    }
    setShowWordAnswer(false);
    setSaveState("idle");
    setMessage("");
  };

  const handleCreate = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (creating || activeType === "all" || activeType === "review") {
      return;
    }
    const body = newBody.trim();
    const sourceUrl = activeType === "resource" ? normalizeWebUrl(newUrl) : null;
    const wordSource = activeType === "word" && wordSourceUrl.trim()
      ? normalizeWebUrl(wordSourceUrl)
      : null;
    if (activeType === "idea" && !body) {
      return;
    }
    if (activeType === "word" && !newTitle.trim()) {
      setMessage("请输入要收藏的英语单词或短语。");
      wordRef.current?.focus();
      return;
    }
    if (activeType === "word" && wordSourceUrl.trim() && !wordSource) {
      setMessage("出处链接需要是有效的网址，也可以留空。");
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
    try {
      const clientId = crypto.randomUUID();
      const created = await createMemo({
        type: activeType,
        title: newTitle.trim() || undefined,
        body: body || sourceUrl || newTitle.trim(),
        source_url: sourceUrl ?? wordSource ?? undefined,
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
      setWordSourceUrl("");
      setWebAttachment(null);
      setWebAttachmentHelp(false);
      setWebCommandOpen(false);
      setUndoMemo(deduplicatedResource ? null : created);
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
          sourceUrl: wordSource,
        });
        setMessage("已收藏相同词形，可以查看、合并例句或仍然保存。");
      } else {
        setMessage(describeError(error));
      }
    } finally {
      setCreating(false);
    }
  };

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
      setMessage("已撤销刚才的保存。");
    } catch (error) {
      setMessage(describeError(error));
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
        sourceUrl: pendingWord.sourceUrl || undefined,
      });
      setMemos((current) => [
        merged,
        ...current.filter((memo) => memo.id !== merged.id),
      ]);
      setNewBody("");
      setNewTitle("");
      setNewPhonetic("");
      setNewExample("");
      setWordSourceUrl("");
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
        source_url: pendingWord.sourceUrl || undefined,
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
      setWordSourceUrl("");
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
        body: editorBody.trim() || selectedMemo.body,
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
      setSaveState("saved");
      if (undoMemo?.id === updated.id) {
        setUndoMemo(updated);
      }
    } catch (error) {
      setSaveState("error");
      setMessage(describeError(error));
      if (error instanceof ApiError && error.status === 409) {
        await loadCurrentMemos();
        setSelectedId(null);
      }
    }
  };

  const updateResourceOrganization = async (
    memo: Memo,
    changes: {
      resource_category?: ResourceCategory;
      starred?: boolean;
    },
  ) => {
    if (memo.type !== "resource" || updatingResourceId === memo.id) {
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
        activeType !== "resource" ||
        ((!resourceCategoryFilter ||
          updated.resource_category === resourceCategoryFilter) &&
          (!resourceStarredOnly || updated.starred));
      setMemos((current) =>
        remainsVisible
          ? current.map((item) => (item.id === updated.id ? updated : item))
          : current.filter((item) => item.id !== updated.id),
      );
    } catch (error) {
      setMessage(describeError(error));
      if (error instanceof ApiError && error.status === 409) {
        await loadCurrentMemos(false);
      }
    } finally {
      setUpdatingResourceId(null);
    }
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

  const resetVoiceCapture = () => {
    setVoiceState("idle");
    setVoiceSeconds(0);
    setVoiceText("");
    setVoiceBlob(null);
    setVoiceDraftMemo(null);
    voiceChunksRef.current = [];
  };

  const startVoiceCapture = async () => {
    if (!navigator.mediaDevices?.getUserMedia || !("MediaRecorder" in window)) {
      setMessage("当前浏览器不支持录音，请使用文字输入或 Android 客户端。");
      return;
    }
    setVoiceState("requesting");
    setMessage("");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
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
        const durationMs = Date.now() - voiceStartedAtRef.current;
        const blob = new Blob(voiceChunksRef.current, {
          type: recorder.mimeType || "audio/webm",
        });
        recorder.stream.getTracks().forEach((track) => track.stop());
        if (voiceTimerRef.current !== null) {
          window.clearInterval(voiceTimerRef.current);
          voiceTimerRef.current = null;
        }
        setVoiceSeconds(Math.max(1, Math.round(durationMs / 1_000)));
        setVoiceBlob(blob);
        setVoiceState("ready");
      };
      recorder.onerror = () => {
        recorder.stream.getTracks().forEach((track) => track.stop());
        setVoiceState("idle");
        setMessage("录音失败，请检查麦克风权限后重试。");
      };
      recorderRef.current = recorder;
      voiceStartedAtRef.current = Date.now();
      recorder.start(500);
      setVoiceSeconds(0);
      setVoiceState("recording");
      voiceTimerRef.current = window.setInterval(() => {
        setVoiceSeconds(Math.floor((Date.now() - voiceStartedAtRef.current) / 1_000));
      }, 500);
    } catch (error) {
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
    if (recorder?.state === "recording") {
      recorder.stop();
    }
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

  return (
    <div className="app-shell">
      <aside className="side-navigation" aria-label="主导航">
        <div className="brand-block">
          <span className="brand-mark">M</span>
          <div><strong>MemoIsle</strong><span>Personal sanctuary</span></div>
        </div>
        <button className="new-button" onClick={focusCapture}>
          <span aria-hidden="true">＋</span> 新建
        </button>
        <nav>
          {navigation.map((item) => {
            const enabled = item.view !== undefined || item.action !== undefined;
            const active = item.view === activeType && item.label !== "首页";
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
                  }
                }}
                title={enabled ? undefined : "将在后续里程碑开放"}
              >
                <span className="nav-icon" aria-hidden="true">{item.icon}</span>
                {item.label}
                {item.view === "resource" && memoCounts !== null && (
                  <span className="nav-count">{memoCounts.resource_count}</span>
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
              </button>
            );
          })}
        </nav>
        <div className="account-block">
          <span className="avatar">林</span><span>本地开发账号</span>
          <span className="sync-dot" aria-label="同步正常" />
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
              placeholder="搜索全部内容（/）"
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
          <a
            className="extension-download-button"
            href={browserExtensionDownloadUrl()}
            download="memoisle-browser-extension.zip"
            title="下载后解压，并在 Chrome 或 Edge 中加载已解压的扩展"
          >↓ 下载扩展</a>
          <button className="compact-new" onClick={focusCapture}>＋ 新建</button>
        </header>

        <main className="main-content">
          <div className="page-heading">
            <div><p className="eyebrow">{copy.eyebrow}</p><h1>{copy.title}</h1></div>
            <span>
              {activeType === "review" && reviewQueue
                ? `今天 ${reviewQueue.word_count + reviewQueue.resource_count + reviewQueue.idea_count} 条值得回顾`
                : activeType === "resource" && memoCounts !== null
                  ? `${memoCounts.resource_count} 条资料`
                  : `${memos.length} 条内容`}
            </span>
          </div>

          {activeType === "all" && !searchQuery.trim() && reviewQueue && (
            <section className="today-review-card">
              <div>
                <p className="eyebrow">今日回顾</p>
                <h2>今天有 {reviewQueue.word_count + reviewQueue.resource_count + reviewQueue.idea_count} 条值得回顾</h2>
                <div className="today-review-stats">
                  <span>{reviewQueue.word_count} 个单词</span>
                  <span>{reviewQueue.resource_count} 篇待读</span>
                  <span>{reviewQueue.idea_count} 条待整理</span>
                </div>
              </div>
              <button
                type="button"
                className="today-review-start"
                onClick={() => switchType("review")}
                disabled={
                  reviewQueue.word_count +
                    reviewQueue.resource_count +
                    reviewQueue.idea_count ===
                  0
                }
              >
                {reviewQueue.word_count +
                  reviewQueue.resource_count +
                  reviewQueue.idea_count ===
                0
                  ? "今天已完成"
                  : "开始回顾"}
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
            />
          )}

          {activeType !== "all" && activeType !== "review" && (
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
                  <strong>@网页暂未连接当前浏览器</strong>
                  <span>请启用 MemoIsle 扩展并刷新浏览器页面，然后输入 @ 选择当前打开的网页。</span>
                  <small>下载 ZIP 并解压 → Chrome 扩展管理 → 加载已解压扩展 → 选择 memoisle-extension 文件夹。</small>
                </div>
                <div className="web-attachment-help-actions">
                  <a
                    href={browserExtensionDownloadUrl()}
                    download="memoisle-browser-extension.zip"
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
                  onChange={(event) => setNewTitle(event.target.value)}
                  onPaste={(event) => {
                    const text = event.clipboardData.getData("text");
                    const draft = parseClipboardWord(text);
                    if (!draft || (!draft.phonetic && !draft.meaning)) {
                      return;
                    }
                    event.preventDefault();
                    setNewTitle(draft.lemma);
                    if (draft.phonetic) {
                      setNewPhonetic(draft.phonetic);
                    }
                    if (draft.meaning) {
                      setNewBody(draft.meaning);
                    }
                    setMessage(`已从剪贴板填入「${draft.lemma}」，确认后保存。`);
                  }}
                  placeholder="单词或短语，点击单词时可从剪贴板填入"
                  autoCapitalize="none"
                  maxLength={200}
                />
                <input
                  value={newPhonetic}
                  onChange={(event) => setNewPhonetic(event.target.value)}
                  placeholder="音标（可选）"
                  maxLength={120}
                />
              </div>
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
                      ? "添加备注，输入 @ 可选择当前浏览器打开的网页（可选）"
                      : "填写中文释义或个人理解（可选）"
                }
                rows={activeType === "idea" ? 3 : 2}
                maxLength={50_000}
              />
              {activeType === "resource" && webCommandOpen && (
                <div className="capture-command-menu" role="menu">
                  <div className="capture-command-heading">
                    <strong>@网页 · 当前浏览器</strong>
                    <small>选择当前浏览器正在打开的网页，不限当前标签页</small>
                  </div>
                  {openBrowserTabsLoading && (
                    <div className="capture-command-empty">正在读取当前浏览器网页……</div>
                  )}
                  {!openBrowserTabsLoading && openBrowserTabs.map((tab) => (
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
                          <strong>{tab.page_title}</strong>
                          <small>
                            {sourceHost(tab.page_url)} · 最近同步 {timeFormatter.format(new Date(tab.last_seen_at))}
                          </small>
                        </span>
                      </button>
                    </div>
                  ))}
                  {!openBrowserTabsLoading && openBrowserTabs.length === 0 && (
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
                placeholder="例句或遇到它的上下文（可选）"
                rows={2}
                maxLength={5_000}
              />
            )}
            {activeType === "word" && (
              <input
                className="word-source"
                value={wordSourceUrl}
                onChange={(event) => setWordSourceUrl(event.target.value)}
                placeholder="出处链接（可选）"
                inputMode="url"
                autoCapitalize="none"
                maxLength={2_048}
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
                <strong>批量整理已有收藏</strong>
                <span>从当前浏览器直接读取书签，自动去重、分类并支持整批撤销。</span>
              </div>
              <span className="resource-tool-actions">
                <button type="button" onClick={() => setHealthCenterOpen(true)}>
                  ! 网页巡检{healthIssueCount > 0 ? ` ${healthIssueCount}` : ""}
                </button>
                <button type="button" onClick={() => setBookmarkImportOpen(true)}>
                  ⇧ 导入浏览器书签
                </button>
                <button
                  type="button"
                  onClick={() => setCategorySettingsOpen((open) => !open)}
                >
                  ⚙ 分类模板
                </button>
              </span>
            </div>
          )}

          {activeType === "resource" && categorySettingsOpen && (
            <section
              className="category-settings-panel"
              aria-label="自定义分类模板和规则"
            >
              <div className="category-settings-heading">
                <div>
                  <strong>我的分类模板</strong>
                  <span>先按你的规则分类，无法判断时再交给大模型。</span>
                </div>
                {categorySettingsLoading && <small>正在读取……</small>}
              </div>
              <div className="category-settings-grid">
                <div className="category-template-column">
                  <h3>自定义分类</h3>
                  <form
                    className="category-create-form"
                    onSubmit={handleCreateCategory}
                  >
                    <input
                      value={newCategoryName}
                      onChange={(event) => setNewCategoryName(event.target.value)}
                      placeholder="例如：待研究项目"
                      maxLength={50}
                    />
                    <input
                      value={newCategoryDescription}
                      onChange={(event) =>
                        setNewCategoryDescription(event.target.value)
                      }
                      placeholder="给大模型的分类说明（可选）"
                      maxLength={300}
                    />
                    <button type="submit" disabled={categorySubmitting}>
                      添加分类
                    </button>
                  </form>
                  <div className="custom-category-list">
                    {resourceCategories
                      .filter((category) => !category.is_system)
                      .map((category) => (
                        <div className="custom-category-row" key={category.code}>
                          <span>
                            <strong>{category.name}</strong>
                            {category.description && <small>{category.description}</small>}
                          </span>
                          <button
                            type="button"
                            disabled={categorySubmitting}
                            onClick={() => void handleToggleCategory(category)}
                          >
                            {category.is_active ? "停用" : "启用"}
                          </button>
                        </div>
                      ))}
                    {resourceCategories.every((category) => category.is_system) && (
                      <p className="category-settings-empty">
                        还没有自定义分类，先创建一个属于你的分类模板。
                      </p>
                    )}
                  </div>
                </div>
                <div className="category-rule-column">
                  <h3>自动分类规则</h3>
                  <form
                    className="category-rule-form"
                    onSubmit={handleCreateCategoryRule}
                  >
                    <input
                      value={newRuleName}
                      onChange={(event) => setNewRuleName(event.target.value)}
                      placeholder="规则名称（可选）"
                      maxLength={100}
                    />
                    <div className="category-rule-fields">
                      <select
                        value={newRuleCategory}
                        onChange={(event) => setNewRuleCategory(event.target.value)}
                      >
                        <option value="">选择分类</option>
                        {resourceCategories
                          .filter((category) => category.is_active)
                          .map((category) => (
                            <option key={category.code} value={category.code}>
                              {category.name}
                            </option>
                          ))}
                      </select>
                      <select
                        value={newRuleMatchType}
                        onChange={(event) =>
                          setNewRuleMatchType(
                            event.target.value as ResourceCategoryRuleMatchType,
                          )
                        }
                      >
                        {Object.entries(resourceRuleMatchLabels).map(
                          ([value, label]) => (
                            <option key={value} value={value}>
                              {label}
                            </option>
                          ),
                        )}
                      </select>
                    </div>
                    <div className="category-rule-fields">
                      <input
                        value={newRulePattern}
                        onChange={(event) => setNewRulePattern(event.target.value)}
                        placeholder={
                          newRuleMatchType === "domain"
                            ? "例如：github.com"
                            : newRuleMatchType === "url"
                              ? "例如：/research/"
                              : "例如：深度学习"
                        }
                        maxLength={500}
                      />
                      <input
                        type="number"
                        min="0"
                        max="10000"
                        value={newRulePriority}
                        onChange={(event) => setNewRulePriority(event.target.value)}
                        aria-label="规则优先级"
                        title="数字越小优先级越高"
                      />
                    </div>
                    <button type="submit" disabled={categorySubmitting}>
                      保存规则
                    </button>
                  </form>
                  <div className="category-rule-list">
                    {categoryRules.map((rule) => (
                      <div className="category-rule-row" key={rule.id}>
                        <span>
                          <strong>{rule.category_label}</strong>
                          <small>
                            {resourceRuleMatchLabels[rule.match_type]}：{rule.pattern}
                            {rule.priority !== 100 ? ` · 优先级 ${rule.priority}` : ""}
                          </small>
                        </span>
                        <button
                          type="button"
                          disabled={categorySubmitting}
                          onClick={() => void handleDeleteCategoryRule(rule)}
                        >
                          删除
                        </button>
                      </div>
                    ))}
                    {categoryRules.length === 0 && (
                      <p className="category-settings-empty">
                        还没有规则，域名规则最适合先整理常用网站。
                      </p>
                    )}
                  </div>
                </div>
              </div>
            </section>
          )}

          {message && (
            <div className="status-message" role="status">
              <span>{message}</span>
              {undoMemo && !duplicateWord && (
                <button type="button" onClick={() => void handleUndoSave()}>撤销</button>
              )}
              {duplicateWord && (
                <span className="status-actions">
                  <button type="button" onClick={handleViewDuplicateWord}>查看</button>
                  <button type="button" onClick={() => void handleMergeDuplicateWord()}>合并例句</button>
                  <button type="button" onClick={() => void handleForceDuplicateWord()}>仍然保存</button>
                </span>
              )}
            </div>
          )}

          {activeType !== "review" && (
          <section className="recent-section" aria-labelledby="recent-title">
            <div className="section-heading">
              <h2 id="recent-title">
                {searchQuery.trim()
                  ? `“${searchQuery.trim()}”的搜索结果`
                  : copy.title}
              </h2>
              <div className="section-actions">
                <label>
                  <span className="sr-only">排序方式</span>
                  <select
                    value={memoSort}
                    onChange={(event) => {
                      setMemoSort(event.target.value as MemoSort);
                      if (activeType === "resource") {
                        setResourcePage(1);
                      }
                    }}
                  >
                    <option value="updated_desc">最近更新</option>
                    <option value="updated_asc">最早更新</option>
                    <option value="created_desc">最近收藏</option>
                    <option value="created_asc">最早收藏</option>
                    <option value="title_asc">标题 A–Z</option>
                    <option value="title_desc">标题 Z–A</option>
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
                <button onClick={() => void loadCurrentMemos()}>刷新</button>
              </div>
            </div>
            {activeType === "resource" && (
              <div className="resource-filter-panel" aria-label="资料组合筛选">
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
                        onClick={() => {
                          setResourceCategoryFilter(category.code);
                          setResourcePage(1);
                        }}
                      >{category.name}</button>
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
                  筛选结果 <strong>{currentResultCount}</strong> 条资料
                </div>
              </div>
            )}
            {loadState === "loading" && (
              <div className="state-panel">
                {searchQuery.trim() ? "正在搜索资料库……" : `正在从共享资料库读取${copy.itemLabel}……`}
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
                <h3>{searchQuery.trim() ? "没有找到匹配内容" : copy.emptyTitle}</h3>
                <p>
                  {searchQuery.trim()
                    ? "换个关键词，或清除搜索后浏览全部收藏。"
                    : copy.emptyBody}
                </p>
              </div>
            )}
            {loadState === "ready" && memos.length > 0 && (
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
                    onClick={() => {
                      if (memo.type !== "resource") {
                        selectMemo(memo);
                      }
                    }}
                    onKeyDown={(event) => {
                      if (
                        memo.type === "resource" ||
                        event.target !== event.currentTarget
                      ) {
                        return;
                      }
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        selectMemo(memo);
                      }
                    }}
                    tabIndex={memo.type === "resource" ? undefined : 0}
                  >
                    <span className={`memo-type-icon ${memo.type}`}>
                      {memo.audio_mime_type ? "●" : viewCopy[memo.type].icon}
                    </span>
                    <span className="memo-copy">
                      {memo.type === "resource" && memo.source_url ? (
                        <a
                          className="memo-title-link"
                          href={memo.source_url}
                          target="_blank"
                          rel="noreferrer"
                          onClick={(event) => event.stopPropagation()}
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
                            : memo.body}
                      </span>
                      <small className="memo-meta-line">
                        {memo.type === "resource"
                          ? (
                            <>
                              {memo.source_url ? (
                                <a
                                  className="memo-url-link"
                                  href={memo.source_url}
                                  target="_blank"
                                  rel="noreferrer"
                                  onClick={(event) => event.stopPropagation()}
                                >
                                  {sourceHost(memo.source_url)} ↗
                                </a>
                              ) : sourceHost(memo.source_url)}
                            </>
                          )
                          : memo.type === "word"
                            ? `熟悉度 ${memo.familiarity}/5 · 已复习 ${memo.review_count} 次 · 下次 ${
                              memo.next_review_at
                                ? timeFormatter.format(new Date(memo.next_review_at))
                                : "待安排"
                            }`
                            : memo.audio_mime_type ? "语音灵感" : "灵感"}
                        {memo.type !== "resource" && ` · 版本 ${memo.version}`}
                      </small>
                    </span>
                    <span className="memo-row-side">
                      <time dateTime={memo.updated_at}>
                        {timeFormatter.format(new Date(memo.updated_at))}
                      </time>
                      {memo.type === "resource" && (
                        <span
                          className="resource-inline-actions"
                          onClick={(event) => event.stopPropagation()}
                        >
                          <select
                            aria-label={`修改“${memo.title}”的分类`}
                            value={memo.resource_category ?? ""}
                            disabled={updatingResourceId === memo.id}
                            onChange={(event) =>
                              void updateResourceOrganization(memo, {
                                resource_category:
                                  event.target.value as ResourceCategory,
                              })
                            }
                          >
                            <option value="" disabled>分类中</option>
                            {resourceCategories.map((category) => (
                              <option key={category.code} value={category.code}>
                                {category.name}
                              </option>
                            ))}
                          </select>
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
                        </span>
                      )}
                    </span>
                  </article>
                ))}
              </div>
            )}
            {activeType === "resource" && currentResultCount > RESOURCE_PAGE_SIZE && (
              <nav className="resource-pagination" aria-label="网页资料分页">
                <button
                  type="button"
                  disabled={resourcePage === 1 || loadState === "loading"}
                  onClick={() => setResourcePage((page) => Math.max(1, page - 1))}
                >
                  上一页
                </button>
                <span>
                  第 {resourcePage} / {resourcePageCount} 页
                </span>
                <button
                  type="button"
                  disabled={
                    resourcePage >= resourcePageCount ||
                    loadState === "loading"
                  }
                  onClick={() => setResourcePage((page) => page + 1)}
                >
                  下一页
                </button>
              </nav>
            )}
          </section>
          )}
        </main>
      </div>

      {selectedMemo && selectedMemo.type !== "resource" && (
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
              <audio controls preload="metadata" src={memoAudioUrl(selectedMemo.id)} />
            </div>
          )}
          <form onSubmit={handleUpdate}>
            <label>{selectedMemo.type === "word" ? "单词或短语" : "标题"}
              <input value={editorTitle} onChange={(event) => setEditorTitle(event.target.value)} maxLength={200} />
            </label>
            {selectedMemo.type === "word" && (
              <>
                <WordPronunciation lemma={editorTitle || selectedMemo.title} />
                <p className="review-schedule">
                  上次复习 {selectedMemo.last_review_at
                    ? timeFormatter.format(new Date(selectedMemo.last_review_at))
                    : "尚未复习"}
                  {" · "}
                  下次 {selectedMemo.next_review_at
                    ? timeFormatter.format(new Date(selectedMemo.next_review_at))
                    : "待安排"}
                </p>
                {selectedMemo.source_url && (
                  <p className="review-example">
                    出处{" "}
                    <a href={selectedMemo.source_url} target="_blank" rel="noreferrer">
                      {sourceHost(selectedMemo.source_url)}
                    </a>
                  </p>
                )}
                <label>音标
                  <input
                    value={editorPhonetic}
                    onChange={(event) => setEditorPhonetic(event.target.value)}
                    maxLength={120}
                    placeholder="音标（可选）"
                  />
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

      {voicePanelOpen && (
        <div className="voice-backdrop" role="presentation">
          <section className="voice-dialog" role="dialog" aria-modal="true" aria-labelledby="voice-title">
            <div className="voice-dialog-header">
              <div>
                <span className="type-label">● 语音灵感</span>
                <h2 id="voice-title">记录此刻的想法</h2>
              </div>
              <button
                className="icon-button"
                aria-label="关闭语音记录"
                disabled={voiceState === "recording" || voiceState === "saving"}
                onClick={() => {
                  setVoicePanelOpen(false);
                  resetVoiceCapture();
                }}
              >×</button>
            </div>

            <div className={`voice-orb ${voiceState === "recording" ? "recording" : ""}`}>
              <span>●</span>
              <strong>{voiceSeconds} 秒</strong>
              <small>
                {voiceState === "recording"
                  ? "正在录音"
                  : voiceState === "ready" ? "录音已就绪" : "等待开始"}
              </small>
            </div>

            <label className="voice-note-label">
              配套文字（可选）
              <textarea
                value={voiceText}
                onChange={(event) => setVoiceText(event.target.value)}
                placeholder="可以同时写下关键词或已整理的文字……"
                rows={4}
                maxLength={50_000}
                disabled={voiceState === "saving"}
              />
            </label>

            <div className="voice-actions">
              {voiceState === "idle" && (
                <button className="primary" onClick={() => void startVoiceCapture()}>
                  开始录音
                </button>
              )}
              {voiceState === "requesting" && <button disabled>正在请求麦克风权限…</button>}
              {voiceState === "recording" && (
                <button className="stop" onClick={stopVoiceCapture}>结束录音</button>
              )}
              {voiceState === "ready" && (
                <>
                  <button onClick={resetVoiceCapture}>重新录制</button>
                  <button className="primary" onClick={() => void saveVoiceCapture()}>
                    保存语音灵感
                  </button>
                </>
              )}
              {voiceState === "saving" && <button disabled>正在保存录音…</button>}
            </div>
            <p className="voice-privacy">录音只会保存到你的私人资料库，不会写入应用日志。</p>
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

      <nav className="mobile-navigation" aria-label="移动端主导航">
        <button className={activeType === "all" ? "active" : ""} onClick={() => switchType("all")}>□<span>全部</span></button>
        <button className={activeType === "resource" ? "active" : ""} onClick={() => switchType("resource")}>↗<span>资料</span></button>
        <button className="mobile-create" onClick={focusCapture}>＋<span>新建</span></button>
        <button className={activeType === "idea" ? "active" : ""} onClick={() => switchType("idea")}>✦<span>灵感</span></button>
        <button className={activeType === "word" ? "active" : ""} onClick={enterWordCapture}>Aa<span>单词</span></button>
      </nav>
    </div>
  );
}
