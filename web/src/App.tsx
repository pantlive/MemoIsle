import {
  type FormEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import BookmarkImportDialog from "./BookmarkImportDialog";
import LinkHealthDialog from "./LinkHealthDialog";
import {
  ApiError,
  browserExtensionDownloadUrl,
  createMemo,
  enrichResource,
  exchangeBrowserCapture,
  getLinkHealthCenter,
  listOpenBrowserTabs,
  listMemos,
  memoAudioUrl,
  reviewWord,
  updateMemo,
  uploadMemoAudio,
} from "./api";
import type {
  BrowserCaptureContext,
  BrowserOpenTab,
  LinkHealthStatus,
  Memo,
  MemoSort,
  MemoStatus,
  MemoType,
  ResourceCategory,
  ResourceKind,
  ResourceReadingStatus,
  ReviewFeedback,
} from "./types";

type LoadState = "loading" | "ready" | "error";
type SaveState = "idle" | "saving" | "saved" | "error";
type VoiceState = "idle" | "requesting" | "recording" | "ready" | "saving";
type ActiveType = Extract<MemoType, "idea" | "resource" | "word">;
type ActiveView = ActiveType | "all";
type ResourceViewMode = "list" | "cards";

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
  { label: "回顾", icon: "◷" },
];

const timeFormatter = new Intl.DateTimeFormat("zh-CN", {
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

const resourceCategories: Array<{
  value: ResourceCategory;
  label: string;
}> = [
  { value: "learning", label: "学习资料" },
  { value: "article", label: "文章阅读" },
  { value: "media", label: "视频与音频" },
  { value: "tool", label: "工具与服务" },
  { value: "book_paper", label: "书籍与论文" },
  { value: "product", label: "商品与好物" },
  { value: "other", label: "其他" },
];

const resourceKinds: Array<{ value: ResourceKind; label: string }> = [
  { value: "article", label: "文章" },
  { value: "video", label: "视频" },
  { value: "course", label: "课程" },
  { value: "tool", label: "工具" },
  { value: "book", label: "书籍" },
  { value: "other", label: "其他" },
];

const resourceReadingStatuses: Array<{
  value: ResourceReadingStatus;
  label: string;
}> = [
  { value: "unread", label: "未读" },
  { value: "reading", label: "阅读中" },
  { value: "completed", label: "已完成" },
  { value: "archived", label: "已归档" },
];

function categoryLabel(category: ResourceCategory | null): string {
  return resourceCategories.find((item) => item.value === category)?.label ?? "分类中";
}

function resourceKindLabel(kind: ResourceKind | null): string {
  return resourceKinds.find((item) => item.value === kind)?.label ?? "其他";
}

function readingStatusLabel(status: ResourceReadingStatus | null): string {
  return resourceReadingStatuses.find((item) => item.value === status)?.label ?? "未读";
}

function metadataStatusLabel(memo: Memo): string {
  if (memo.resource_metadata_status === "processing") {
    return "正在读取网页信息";
  }
  if (memo.resource_metadata_status === "pending") {
    return "等待读取网页信息";
  }
  if (memo.resource_metadata_status === "failed") {
    return "网页信息读取失败";
  }
  return "网页信息已更新";
}

const viewCopy = {
  all: {
    title: "全部内容",
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
  const [activeType, setActiveType] = useState<ActiveView>("idea");
  const [memos, setMemos] = useState<Memo[]>([]);
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [message, setMessage] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [resourceCategoryFilter, setResourceCategoryFilter] = useState<
    ResourceCategory | ""
  >("");
  const [resourceTagFilter, setResourceTagFilter] = useState("");
  const [resourceCollectionFilter, setResourceCollectionFilter] = useState("");
  const [resourceKindFilter, setResourceKindFilter] = useState<ResourceKind | "">("");
  const [resourceReadingFilter, setResourceReadingFilter] = useState<
    ResourceReadingStatus | ""
  >("");
  const [resourceStarredOnly, setResourceStarredOnly] = useState(false);
  const [resourceHealthFilter, setResourceHealthFilter] = useState<
    LinkHealthStatus | ""
  >("");
  const [resourceStatusFilter, setResourceStatusFilter] = useState<
    MemoStatus | ""
  >("");
  const [resourceCreatedFrom, setResourceCreatedFrom] = useState("");
  const [resourceCreatedTo, setResourceCreatedTo] = useState("");
  const [memoSort, setMemoSort] = useState<MemoSort>("updated_desc");
  const [resourceViewMode, setResourceViewMode] =
    useState<ResourceViewMode>("list");
  const [bookmarkImportOpen, setBookmarkImportOpen] = useState(false);
  const [healthCenterOpen, setHealthCenterOpen] = useState(false);
  const [healthIssueCount, setHealthIssueCount] = useState(0);
  const [newBody, setNewBody] = useState("");
  const [newUrl, setNewUrl] = useState("");
  const [newTitle, setNewTitle] = useState("");
  const [newPhonetic, setNewPhonetic] = useState("");
  const [newExample, setNewExample] = useState("");
  const [webAttachment, setWebAttachment] = useState<
    BrowserCaptureContext | BrowserOpenTab | null
  >(null);
  const [openBrowserTabs, setOpenBrowserTabs] = useState<BrowserOpenTab[]>([]);
  const [openBrowserTabsLoading, setOpenBrowserTabsLoading] = useState(false);
  const [webAttachmentHelp, setWebAttachmentHelp] = useState(false);
  const [webCommandOpen, setWebCommandOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [editorTitle, setEditorTitle] = useState("");
  const [editorBody, setEditorBody] = useState("");
  const [editorUrl, setEditorUrl] = useState("");
  const [editorPhonetic, setEditorPhonetic] = useState("");
  const [editorExample, setEditorExample] = useState("");
  const [editorCategory, setEditorCategory] = useState<ResourceCategory | "">("");
  const [editorResourceKind, setEditorResourceKind] =
    useState<ResourceKind>("other");
  const [editorReadingStatus, setEditorReadingStatus] =
    useState<ResourceReadingStatus>("unread");
  const [editorTags, setEditorTags] = useState("");
  const [editorCollections, setEditorCollections] = useState("");
  const [editorStarred, setEditorStarred] = useState(false);
  const [editorStatus, setEditorStatus] = useState<MemoStatus>("active");
  const [enrichingResource, setEnrichingResource] = useState(false);
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

  const refreshOpenBrowserTabs = useCallback(async () => {
    setOpenBrowserTabsLoading(true);
    try {
      const tabs = await listOpenBrowserTabs();
      setOpenBrowserTabs(tabs);
    } catch {
      // 当前浏览器标签页读取失败时仍保留粘贴网址和一次性捕获入口。
      setOpenBrowserTabs([]);
    } finally {
      setOpenBrowserTabsLoading(false);
    }
  }, []);

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
      wordRef.current?.focus();
    } else {
      captureRef.current?.focus();
    }
  }, [activeType]);

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
    if (!webCommandOpen) {
      return;
    }
    void refreshOpenBrowserTabs();
    const timer = window.setInterval(
      () => void refreshOpenBrowserTabs(),
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

  const loadCurrentMemos = useCallback(async () => {
    const requestId = ++loadRequestRef.current;
    setLoadState("loading");
    try {
      const resourceView = activeType === "resource";
      const items = await listMemos({
        type: activeType === "all" ? undefined : activeType,
        query: debouncedQuery,
        category: resourceView ? resourceCategoryFilter || undefined : undefined,
        resourceKind: resourceView ? resourceKindFilter || undefined : undefined,
        readingStatus: resourceView
          ? resourceReadingFilter || undefined
          : undefined,
        health: resourceView ? resourceHealthFilter || undefined : undefined,
        tag: resourceView ? resourceTagFilter || undefined : undefined,
        collection: resourceView
          ? resourceCollectionFilter || undefined
          : undefined,
        starred: resourceView && resourceStarredOnly ? true : undefined,
        status: resourceView ? resourceStatusFilter || undefined : undefined,
        createdFrom: resourceView ? resourceCreatedFrom || undefined : undefined,
        createdTo: resourceView ? resourceCreatedTo || undefined : undefined,
        sort: memoSort,
      });
      if (requestId !== loadRequestRef.current) {
        return;
      }
      setMemos(items);
      setLoadState("ready");
    } catch (error) {
      if (requestId !== loadRequestRef.current) {
        return;
      }
      setMessage(describeError(error));
      setLoadState("error");
    }
  }, [
    activeType,
    debouncedQuery,
    memoSort,
    resourceCategoryFilter,
    resourceCollectionFilter,
    resourceCreatedFrom,
    resourceCreatedTo,
    resourceHealthFilter,
    resourceKindFilter,
    resourceReadingFilter,
    resourceStarredOnly,
    resourceStatusFilter,
    resourceTagFilter,
  ]);

  useEffect(() => {
    setSelectedId(null);
    setMessage("");
    void loadCurrentMemos();
  }, [loadCurrentMemos]);

  useEffect(() => {
    const hasPendingResource = memos.some(
      (memo) =>
        memo.type === "resource" &&
        ["pending", "processing"].includes(memo.resource_metadata_status),
    );
    if (!hasPendingResource) {
      return;
    }
    const timer = window.setTimeout(() => void loadCurrentMemos(), 1_500);
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
    setSearchQuery("");
    setDebouncedQuery("");
    setSelectedId(null);
    setSaveState("idle");
    if (type !== "resource") {
      setResourceCategoryFilter("");
      setResourceTagFilter("");
      setResourceCollectionFilter("");
      setResourceKindFilter("");
      setResourceReadingFilter("");
      setResourceStarredOnly(false);
      setResourceHealthFilter("");
      setResourceStatusFilter("");
      setResourceCreatedFrom("");
      setResourceCreatedTo("");
    }
  };

  const handleSearchChange = (value: string) => {
    setSearchQuery(value);
    if (value.trim() && activeType !== "all") {
      setActiveType("all");
      setResourceCategoryFilter("");
      setResourceTagFilter("");
      setResourceCollectionFilter("");
      setResourceKindFilter("");
      setResourceReadingFilter("");
      setResourceStarredOnly(false);
      setResourceHealthFilter("");
      setResourceStatusFilter("");
      setResourceCreatedFrom("");
      setResourceCreatedTo("");
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
    setSelectedId(memo.id);
    setEditorTitle(memo.title);
    setEditorBody(memo.body === memo.source_url ? "" : memo.body);
    setEditorUrl(memo.source_url ?? "");
    setEditorPhonetic(memo.word_phonetic ?? "");
    setEditorExample(memo.word_example ?? "");
    setEditorCategory(memo.resource_category ?? "");
    setEditorResourceKind(memo.resource_kind ?? "other");
    setEditorReadingStatus(memo.resource_reading_status ?? "unread");
    setEditorTags(memo.tags.join("，"));
    setEditorCollections(memo.collections.join("，"));
    setEditorStarred(memo.starred);
    setEditorStatus(memo.status);
    if (memo.type === "word") {
      setEditorBody(memo.word_meaning ?? memo.body);
    }
    setShowWordAnswer(false);
    setSaveState("idle");
    setMessage("");
  };

  const handleCreate = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (creating || activeType === "all") {
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
    try {
      const clientId = crypto.randomUUID();
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
      setNewBody("");
      setNewUrl("");
      setNewTitle("");
      setNewPhonetic("");
      setNewExample("");
      setWebAttachment(null);
      setWebAttachmentHelp(false);
      setWebCommandOpen(false);
      selectMemo(created);
      setMessage(
        deduplicatedResource
          ? "该网址已经收藏，已打开资料库中的原有条目。"
          : `${copy.itemLabel}已保存，并可在 Android 端同步。`,
      );
    } catch (error) {
      setMessage(describeError(error));
    } finally {
      setCreating(false);
    }
  };

  const handleUpdate = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selectedMemo || !editorTitle.trim()) {
      return;
    }
    const sourceUrl =
      selectedMemo.type === "resource" ? normalizeWebUrl(editorUrl) : null;
    if (selectedMemo.type === "resource" && !sourceUrl) {
      setMessage("网页资料必须保留有效的原始链接。");
      return;
    }
    if (selectedMemo.type === "idea" && !editorBody.trim()) {
      return;
    }
    if (
      editorStatus === "trashed" &&
      selectedMemo.status !== "trashed" &&
      !window.confirm("这条内容会移入回收站，确定继续吗？")
    ) {
      return;
    }

    setSaveState("saving");
    setMessage("");
    try {
      const updated = await updateMemo(selectedMemo.id, {
        expected_version: selectedMemo.version,
        title: editorTitle.trim(),
        body: editorBody.trim() || sourceUrl || selectedMemo.body,
        source_url: sourceUrl ?? undefined,
        source_title:
          selectedMemo.type === "resource" ? editorTitle.trim() : undefined,
        word_phonetic:
          selectedMemo.type === "word" ? editorPhonetic.trim() || undefined : undefined,
        word_meaning:
          selectedMemo.type === "word" ? editorBody.trim() || undefined : undefined,
        word_example:
          selectedMemo.type === "word" ? editorExample.trim() || undefined : undefined,
        resource_category:
          selectedMemo.type === "resource" && editorCategory
            ? editorCategory
            : undefined,
        resource_kind:
          selectedMemo.type === "resource" ? editorResourceKind : undefined,
        resource_reading_status:
          selectedMemo.type === "resource" ? editorReadingStatus : undefined,
        tags: editorTags
          .split(/[,，]/)
          .map((tag) => tag.trim())
          .filter(Boolean),
        collections: editorCollections
          .split(/[,，]/)
          .map((collection) => collection.trim())
          .filter(Boolean),
        starred: editorStarred,
        status: editorStatus,
      });
      setMemos((current) =>
        current.map((memo) => (memo.id === updated.id ? updated : memo)),
      );
      setSaveState("saved");
    } catch (error) {
      setSaveState("error");
      setMessage(describeError(error));
      if (error instanceof ApiError && error.status === 409) {
        await loadCurrentMemos();
        setSelectedId(null);
      }
    }
  };

  const handleEnrichResource = async () => {
    if (!selectedMemo || selectedMemo.type !== "resource" || enrichingResource) {
      return;
    }
    setEnrichingResource(true);
    setMessage("");
    try {
      const enriched = await enrichResource(selectedMemo.id);
      setMemos((current) =>
        current.map((memo) => (memo.id === enriched.id ? enriched : memo)),
      );
      selectMemo(enriched);
      setMessage("网页信息与自动分类已更新。");
    } catch (error) {
      setMessage(describeError(error));
    } finally {
      setEnrichingResource(false);
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
    } catch (error) {
      setMessage(describeError(error));
      if (error instanceof ApiError && error.status === 409) {
        await loadCurrentMemos();
      }
    } finally {
      setReviewing(false);
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
                  if (item.view) {
                    switchType(item.view);
                  } else if (item.action === "health") {
                    setHealthCenterOpen(true);
                  }
                }}
                title={enabled ? undefined : "将在后续里程碑开放"}
              >
                <span className="nav-icon" aria-hidden="true">{item.icon}</span>
                {item.label}
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
            <span>{memos.length} 条内容</span>
          </div>

          {activeType !== "all" && (
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
                  placeholder="单词或短语，例如 serendipity"
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
                  onClick={() => switchType("word")}
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
                <span>导入 Chrome HTML 后自动去重、分类并支持整批撤销。</span>
              </div>
              <span className="resource-tool-actions">
                <button type="button" onClick={() => setHealthCenterOpen(true)}>
                  ! 网页巡检{healthIssueCount > 0 ? ` ${healthIssueCount}` : ""}
                </button>
                <button type="button" onClick={() => setBookmarkImportOpen(true)}>
                  ⇧ 导入 Chrome 书签
                </button>
              </span>
            </div>
          )}

          {activeType === "resource" && (
            <section className="resource-filter-panel" aria-label="资料组合筛选">
              <div className="category-filter">
                <span>自动分类</span>
                <button
                  className={!resourceCategoryFilter ? "active" : ""}
                  onClick={() => setResourceCategoryFilter("")}
                >全部</button>
                {resourceCategories.map((category) => (
                  <button
                    className={
                      resourceCategoryFilter === category.value ? "active" : ""
                    }
                    key={category.value}
                    onClick={() => setResourceCategoryFilter(category.value)}
                  >{category.label}</button>
                ))}
              </div>
              <div className="resource-filter-grid">
                <label>
                  标签
                  <input
                    value={resourceTagFilter}
                    onChange={(event) => setResourceTagFilter(event.target.value)}
                    placeholder="用户或自动标签"
                    maxLength={100}
                  />
                </label>
                <label>
                  收藏夹
                  <input
                    value={resourceCollectionFilter}
                    onChange={(event) =>
                      setResourceCollectionFilter(event.target.value)
                    }
                    placeholder="收藏夹名称"
                    maxLength={100}
                  />
                </label>
                <label>
                  资源类型
                  <select
                    value={resourceKindFilter}
                    onChange={(event) =>
                      setResourceKindFilter(event.target.value as ResourceKind | "")
                    }
                  >
                    <option value="">全部类型</option>
                    {resourceKinds.map((kind) => (
                      <option key={kind.value} value={kind.value}>{kind.label}</option>
                    ))}
                  </select>
                </label>
                <label>
                  阅读状态
                  <select
                    value={resourceReadingFilter}
                    onChange={(event) =>
                      setResourceReadingFilter(
                        event.target.value as ResourceReadingStatus | "",
                      )
                    }
                  >
                    <option value="">全部进度</option>
                    {resourceReadingStatuses.map((readingStatus) => (
                      <option key={readingStatus.value} value={readingStatus.value}>
                        {readingStatus.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  巡检状态
                  <select
                    value={resourceHealthFilter}
                    onChange={(event) =>
                      setResourceHealthFilter(
                        event.target.value as LinkHealthStatus | "",
                      )
                    }
                  >
                    <option value="">全部状态</option>
                    <option value="healthy">正常</option>
                    <option value="unchecked">等待检查</option>
                    <option value="redirected">网址跳转</option>
                    <option value="changed">信息变化</option>
                    <option value="auth_required">需要登录</option>
                    <option value="temporary_failure">暂时失败</option>
                    <option value="failed">确认失效</option>
                    <option value="ignored">已忽略</option>
                  </select>
                </label>
                <label>
                  资料状态
                  <select
                    value={resourceStatusFilter}
                    onChange={(event) =>
                      setResourceStatusFilter(event.target.value as MemoStatus | "")
                    }
                  >
                    <option value="">未删除资料</option>
                    <option value="inbox">收件箱</option>
                    <option value="active">使用中</option>
                    <option value="archived">已归档</option>
                    <option value="trashed">回收站</option>
                  </select>
                </label>
                <label>
                  收藏起始日期
                  <input
                    type="date"
                    value={resourceCreatedFrom}
                    max={resourceCreatedTo || undefined}
                    onChange={(event) => setResourceCreatedFrom(event.target.value)}
                  />
                </label>
                <label>
                  收藏结束日期
                  <input
                    type="date"
                    value={resourceCreatedTo}
                    min={resourceCreatedFrom || undefined}
                    onChange={(event) => setResourceCreatedTo(event.target.value)}
                  />
                </label>
                <label className="checkbox-filter">
                  <input
                    type="checkbox"
                    checked={resourceStarredOnly}
                    onChange={(event) => setResourceStarredOnly(event.target.checked)}
                  />
                  只看星标资料
                </label>
                <button
                  type="button"
                  className="clear-filter-button"
                  onClick={() => {
                    setResourceCategoryFilter("");
                    setResourceTagFilter("");
                    setResourceCollectionFilter("");
                    setResourceKindFilter("");
                    setResourceReadingFilter("");
                    setResourceStarredOnly(false);
                    setResourceHealthFilter("");
                    setResourceStatusFilter("");
                    setResourceCreatedFrom("");
                    setResourceCreatedTo("");
                    setMemoSort("updated_desc");
                  }}
                >清除筛选</button>
              </div>
            </section>
          )}

          {message && <div className="status-message" role="status">{message}</div>}

          <section className="recent-section" aria-labelledby="recent-title">
            <div className="section-heading">
              <h2 id="recent-title">
                {searchQuery.trim()
                  ? `“${searchQuery.trim()}”的搜索结果`
                  : activeType === "all" ? "全部内容" : "最近内容"}
              </h2>
              <div className="section-actions">
                <label>
                  <span className="sr-only">排序方式</span>
                  <select
                    value={memoSort}
                    onChange={(event) => setMemoSort(event.target.value as MemoSort)}
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
                  <button
                    className={memo.id === selectedId ? "memo-row selected" : "memo-row"}
                    key={memo.id}
                    onClick={() => selectMemo(memo)}
                  >
                    <span className={`memo-type-icon ${memo.type}`}>
                      {memo.audio_mime_type ? "●" : viewCopy[memo.type].icon}
                    </span>
                    <span className="memo-copy">
                      <strong>{memo.starred ? "★ " : ""}{memo.title}</strong>
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
                          ? `${sourceHost(memo.source_url)} · ${categoryLabel(memo.resource_category)} · ${resourceKindLabel(memo.resource_kind)} · ${readingStatusLabel(memo.resource_reading_status)}`
                          : memo.type === "word"
                            ? `熟悉度 ${memo.familiarity}/5 · 已复习 ${memo.review_count} 次`
                            : memo.audio_mime_type ? "语音灵感" : "灵感"}
                        {` · 版本 ${memo.version}`}
                      </small>
                      {memo.type === "resource" && memo.resource_auto_tags.length > 0 && (
                        <span className="auto-tag-list">
                          {memo.resource_auto_tags.slice(0, 3).map((tag) => (
                            <span key={tag}>{tag}</span>
                          ))}
                        </span>
                      )}
                    </span>
                    <time dateTime={memo.updated_at}>
                      {timeFormatter.format(new Date(memo.updated_at))}
                    </time>
                  </button>
                ))}
              </div>
            )}
          </section>
        </main>
      </div>

      {selectedMemo && (
        <aside className="editor-panel" aria-label={`编辑${selectedCopy.itemLabel}`}>
          <div className="editor-header">
            <div>
              <span className="type-label">
                {selectedCopy.icon} {selectedCopy.itemLabel}
              </span>
              <h2>
                {selectedMemo.type === "resource"
                  ? "整理资料"
                  : selectedMemo.type === "word" ? "学习单词" : "继续整理"}
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
          {selectedMemo.type === "resource" && (
            <div className="resource-insight-card">
              {selectedMemo.resource_image_url && (
                <img
                  className="resource-cover"
                  src={selectedMemo.resource_image_url}
                  alt="网页封面"
                  onError={(event) => {
                    event.currentTarget.style.display = "none";
                  }}
                />
              )}
              <div>
                <span className="category-badge">
                  {categoryLabel(selectedMemo.resource_category)}
                </span>
                <span className={`process-status ${selectedMemo.resource_metadata_status}`}>
                  {metadataStatusLabel(selectedMemo)}
                </span>
              </div>
              {selectedMemo.resource_description && (
                <p>{selectedMemo.resource_description}</p>
              )}
              <div className="resource-insight-meta">
                <span>{selectedMemo.resource_site_name || sourceHost(selectedMemo.source_url)}</span>
                {selectedMemo.resource_category_source && (
                  <span>
                    分类来源：
                    {selectedMemo.resource_category_source === "manual"
                      ? "人工修正"
                      : selectedMemo.resource_category_source === "llm"
                        ? "大模型"
                        : "自动规则"}
                  </span>
                )}
              </div>
              <button
                type="button"
                disabled={enrichingResource}
                onClick={() => void handleEnrichResource()}
              >
                {enrichingResource ? "正在更新网页信息…" : "重新读取并自动分类"}
              </button>
            </div>
          )}
          <form onSubmit={handleUpdate}>
            <label>{selectedMemo.type === "word" ? "单词或短语" : "标题"}
              <input value={editorTitle} onChange={(event) => setEditorTitle(event.target.value)} maxLength={200} />
            </label>
            {selectedMemo.type === "resource" && (
              <>
                <label>原始链接
                  <input
                    value={editorUrl}
                    onChange={(event) => setEditorUrl(event.target.value)}
                    inputMode="url"
                    autoCapitalize="none"
                    maxLength={2_048}
                  />
                  {selectedMemo.source_url && (
                    <a className="source-link" href={selectedMemo.source_url} target="_blank" rel="noreferrer">
                      在新窗口打开原网页 ↗
                    </a>
                  )}
                </label>
                <label>收藏分类
                  <select
                    value={editorCategory}
                    onChange={(event) =>
                      setEditorCategory(event.target.value as ResourceCategory)
                    }
                  >
                    <option value="" disabled>等待自动分类</option>
                    {resourceCategories.map((category) => (
                      <option key={category.value} value={category.value}>
                        {category.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label>资源类型
                  <select
                    value={editorResourceKind}
                    onChange={(event) =>
                      setEditorResourceKind(event.target.value as ResourceKind)
                    }
                  >
                    {resourceKinds.map((kind) => (
                      <option key={kind.value} value={kind.value}>{kind.label}</option>
                    ))}
                  </select>
                </label>
                <label>阅读状态
                  <select
                    value={editorReadingStatus}
                    onChange={(event) =>
                      setEditorReadingStatus(
                        event.target.value as ResourceReadingStatus,
                      )
                    }
                  >
                    {resourceReadingStatuses.map((readingStatus) => (
                      <option key={readingStatus.value} value={readingStatus.value}>
                        {readingStatus.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label>标签
                  <input
                    value={editorTags}
                    onChange={(event) => setEditorTags(event.target.value)}
                    maxLength={500}
                    placeholder="多个标签使用逗号分隔"
                  />
                </label>
                <label>收藏夹
                  <input
                    value={editorCollections}
                    onChange={(event) => setEditorCollections(event.target.value)}
                    maxLength={500}
                    placeholder="多个收藏夹使用逗号分隔"
                  />
                </label>
                <label className="editor-checkbox">
                  <input
                    type="checkbox"
                    checked={editorStarred}
                    onChange={(event) => setEditorStarred(event.target.checked)}
                  />
                  星标这条资料
                </label>
                <label>资料状态
                  <select
                    value={editorStatus}
                    onChange={(event) =>
                      setEditorStatus(event.target.value as MemoStatus)
                    }
                  >
                    <option value="inbox">收件箱</option>
                    <option value="active">使用中</option>
                    <option value="archived">已归档</option>
                    <option value="trashed">移入回收站</option>
                  </select>
                </label>
              </>
            )}
            {selectedMemo.type === "word" && (
              <label>音标
                <input
                  value={editorPhonetic}
                  onChange={(event) => setEditorPhonetic(event.target.value)}
                  maxLength={120}
                  placeholder="音标（可选）"
                />
              </label>
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
              {selectedMemo.type === "resource"
                ? "个人备注"
                : selectedMemo.type === "word" ? "释义" : "内容"}
              <textarea
                value={editorBody}
                onChange={(event) => setEditorBody(event.target.value)}
                rows={selectedMemo.type === "resource" ? 7 : 12}
                maxLength={50_000}
                placeholder={selectedMemo.type === "resource" ? "添加阅读重点或保存原因（可选）" : undefined}
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
                    : selectedMemo.type === "resource" ? !editorUrl.trim() : false)
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
          onImported={() => void loadCurrentMemos()}
        />
      )}

      {healthCenterOpen && (
        <LinkHealthDialog
          onClose={() => setHealthCenterOpen(false)}
          onChanged={() => {
            void refreshHealthSummary();
            void loadCurrentMemos();
          }}
        />
      )}

      <nav className="mobile-navigation" aria-label="移动端主导航">
        <button className={activeType === "all" ? "active" : ""} onClick={() => switchType("all")}>□<span>全部</span></button>
        <button className={activeType === "resource" ? "active" : ""} onClick={() => switchType("resource")}>↗<span>资料</span></button>
        <button className="mobile-create" onClick={focusCapture}>＋<span>新建</span></button>
        <button className={activeType === "idea" ? "active" : ""} onClick={() => switchType("idea")}>✦<span>灵感</span></button>
        <button className={activeType === "word" ? "active" : ""} onClick={() => switchType("word")}>Aa<span>单词</span></button>
      </nav>
    </div>
  );
}
