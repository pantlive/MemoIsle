import type {
  BookmarkImportBatch,
  BookmarkImportPreview,
  BookmarkInput,
  BrowserBookmarkSnapshot,
  BrowserCaptureContext,
  BrowserOpenTab,
  BrowserOpenTabListResponse,
  LinkHealthAction,
  LinkHealthCenter,
  LinkHealthStatus,
  Memo,
  MemoCounts,
  MemoCreateRequest,
  MemoListResponse,
  MemoSort,
  MemoStatus,
  MemoType,
  MemoUpdateRequest,
  ResourceCategoryCreateRequest,
  ResourceCategoryOption,
  ResourceCategoryRule,
  ResourceCategoryRuleCreateRequest,
  ResourceCategoryRuleUpdateRequest,
  ResourceCategoryUpdateRequest,
  ResourceCategory,
  ResourceKind,
  ResourceReadingStatus,
  ReviewFeedback,
  ReviewQueueResponse,
} from "./types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";

export class ApiError extends Error {
  readonly status: number;
  readonly code?: string;
  readonly current?: Memo;

  constructor(message: string, status: number, code?: string, current?: Memo) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.current = current;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });

  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as {
      detail?: string | {
        message?: string;
        code?: string;
        current?: Memo;
      };
    } | null;
    const detail = payload?.detail;
    const message =
      typeof detail === "string"
        ? detail
        : detail?.message ?? `请求失败（${response.status}）`;
    const code = typeof detail === "object" ? detail?.code : undefined;
    const current = typeof detail === "object" ? detail?.current : undefined;
    throw new ApiError(message, response.status, code, current);
  }
  return (await response.json()) as T;
}

export interface MemoListFilters {
  type?: MemoType;
  query?: string;
  category?: ResourceCategory;
  resourceKind?: ResourceKind;
  readingStatus?: ResourceReadingStatus;
  health?: LinkHealthStatus;
  tag?: string;
  collection?: string;
  starred?: boolean;
  status?: MemoStatus;
  createdFrom?: string;
  createdTo?: string;
  sort?: MemoSort;
  limit?: number;
  offset?: number;
}

export async function listMemos(
  filters: MemoListFilters = {},
): Promise<MemoListResponse> {
  const searchParams = new URLSearchParams();
  if (filters.type) {
    searchParams.set("type", filters.type);
  }
  if (filters.query?.trim()) {
    searchParams.set("q", filters.query.trim());
  }
  if (filters.category) {
    searchParams.set("category", filters.category);
  }
  if (filters.resourceKind) {
    searchParams.set("resource_kind", filters.resourceKind);
  }
  if (filters.readingStatus) {
    searchParams.set("reading_status", filters.readingStatus);
  }
  if (filters.health) {
    searchParams.set("health", filters.health);
  }
  if (filters.tag?.trim()) {
    searchParams.set("tag", filters.tag.trim());
  }
  if (filters.collection?.trim()) {
    searchParams.set("collection", filters.collection.trim());
  }
  if (filters.starred !== undefined) {
    searchParams.set("starred", String(filters.starred));
  }
  if (filters.status) {
    searchParams.set("status", filters.status);
  }
  if (filters.createdFrom) {
    searchParams.set("created_from", filters.createdFrom);
  }
  if (filters.createdTo) {
    searchParams.set("created_to", filters.createdTo);
  }
  if (filters.sort) {
    searchParams.set("sort", filters.sort);
  }
  if (filters.limit) {
    searchParams.set("limit", String(filters.limit));
  }
  if (filters.offset) {
    searchParams.set("offset", String(filters.offset));
  }
  const queryString = searchParams.toString();
  const response = await request<MemoListResponse>(
    `/memos${queryString ? `?${queryString}` : ""}`,
  );
  return response;
}

export async function getMemoCounts(): Promise<MemoCounts> {
  return request<MemoCounts>("/memos/counts");
}

export async function getResourceCategories(): Promise<ResourceCategoryOption[]> {
  return request<ResourceCategoryOption[]>("/resource-categories");
}

export async function createResourceCategory(
  payload: ResourceCategoryCreateRequest,
): Promise<ResourceCategoryOption> {
  return request<ResourceCategoryOption>("/resource-categories", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function updateResourceCategory(
  categoryId: string,
  payload: ResourceCategoryUpdateRequest,
): Promise<ResourceCategoryOption> {
  return request<ResourceCategoryOption>(`/resource-categories/${categoryId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function getResourceCategoryRules(): Promise<ResourceCategoryRule[]> {
  return request<ResourceCategoryRule[]>("/resource-category-rules");
}

export async function createResourceCategoryRule(
  payload: ResourceCategoryRuleCreateRequest,
): Promise<ResourceCategoryRule> {
  return request<ResourceCategoryRule>("/resource-category-rules", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function updateResourceCategoryRule(
  ruleId: string,
  payload: ResourceCategoryRuleUpdateRequest,
): Promise<ResourceCategoryRule> {
  return request<ResourceCategoryRule>(`/resource-category-rules/${ruleId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function deleteResourceCategoryRule(
  ruleId: string,
): Promise<{ deleted: boolean }> {
  return request<{ deleted: boolean }>(`/resource-category-rules/${ruleId}`, {
    method: "DELETE",
  });
}

export async function enrichResource(memoId: string): Promise<Memo> {
  return request<Memo>(`/resources/${memoId}/enrich`, {
    method: "POST",
  });
}

export async function previewBookmarkImport(
  items: BookmarkInput[],
): Promise<BookmarkImportPreview> {
  return request<BookmarkImportPreview>("/bookmark-imports/preview", {
    method: "POST",
    body: JSON.stringify({ items }),
  });
}

export async function getCurrentBrowserBookmarks(): Promise<BrowserBookmarkSnapshot> {
  return request<BrowserBookmarkSnapshot>("/browser-bookmarks/current");
}

export async function createBookmarkImport(
  items: BookmarkInput[],
): Promise<BookmarkImportBatch> {
  return request<BookmarkImportBatch>("/bookmark-imports", {
    method: "POST",
    body: JSON.stringify({ items }),
  });
}

export async function getBookmarkImport(
  batchId: string,
): Promise<BookmarkImportBatch> {
  return request<BookmarkImportBatch>(`/bookmark-imports/${batchId}`);
}

export async function retryBookmarkImport(
  batchId: string,
): Promise<BookmarkImportBatch> {
  return request<BookmarkImportBatch>(`/bookmark-imports/${batchId}/retry`, {
    method: "POST",
  });
}

export async function undoBookmarkImport(
  batchId: string,
): Promise<BookmarkImportBatch> {
  return request<BookmarkImportBatch>(`/bookmark-imports/${batchId}/undo`, {
    method: "POST",
  });
}

export async function exchangeBrowserCapture(
  token: string,
): Promise<BrowserCaptureContext> {
  return request<BrowserCaptureContext>("/browser-captures/exchange", {
    method: "POST",
    body: JSON.stringify({ token }),
  });
}

export async function listOpenBrowserTabs(): Promise<BrowserOpenTab[]> {
  const response = await request<BrowserOpenTabListResponse>(
    "/browser-tabs/open",
  );
  return response.items;
}

export function browserExtensionDownloadUrl(): string {
  return `${API_BASE_URL}/browser-extension/download`;
}

export async function getLinkHealthCenter(
  status?: LinkHealthStatus,
): Promise<LinkHealthCenter> {
  const query = status ? `?status=${encodeURIComponent(status)}` : "";
  return request<LinkHealthCenter>(`/resources/link-health${query}`);
}

export async function applyLinkHealthAction(
  memoId: string,
  expectedVersion: number,
  action: LinkHealthAction,
  newUrl?: string,
): Promise<Memo> {
  return request<Memo>(`/resources/${memoId}/link-health-actions`, {
    method: "POST",
    body: JSON.stringify({
      expected_version: expectedVersion,
      action,
      new_url: newUrl,
    }),
  });
}

export async function createMemo(
  payload: Omit<MemoCreateRequest, "client_id">,
  clientId: string = crypto.randomUUID(),
): Promise<Memo> {
  const requestPayload: MemoCreateRequest = {
    client_id: clientId,
    ...payload,
  };
  return request<Memo>("/memos", {
    method: "POST",
    body: JSON.stringify(requestPayload),
  });
}

export async function updateMemo(
  memoId: string,
  payload: MemoUpdateRequest,
): Promise<Memo> {
  return request<Memo>(`/memos/${memoId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function mergeWord(
  memoId: string,
  payload: {
    expectedVersion: number;
    wordPhonetic?: string;
    wordMeaning?: string;
    wordExample?: string;
    sourceUrl?: string;
    sourceTitle?: string;
  },
): Promise<Memo> {
  return request<Memo>(`/words/${memoId}/merge`, {
    method: "POST",
    body: JSON.stringify({
      expected_version: payload.expectedVersion,
      word_phonetic: payload.wordPhonetic,
      word_meaning: payload.wordMeaning,
      word_example: payload.wordExample,
      source_url: payload.sourceUrl,
      source_title: payload.sourceTitle,
    }),
  });
}

export async function reviewWord(
  memoId: string,
  expectedVersion: number,
  feedback: ReviewFeedback,
): Promise<Memo> {
  return request<Memo>(`/words/${memoId}/reviews`, {
    method: "POST",
    body: JSON.stringify({
      expected_version: expectedVersion,
      feedback,
    }),
  });
}

export async function getReviewQueue(options: {
  type?: MemoType;
  limit?: number;
} = {}): Promise<ReviewQueueResponse> {
  const searchParams = new URLSearchParams();
  if (options.type) {
    searchParams.set("type", options.type);
  }
  if (options.limit) {
    searchParams.set("limit", String(options.limit));
  }
  const suffix = searchParams.toString();
  return request<ReviewQueueResponse>(
    `/review-queue${suffix ? `?${suffix}` : ""}`,
  );
}

export async function skipReview(
  memoId: string,
  expectedVersion: number,
): Promise<Memo> {
  return request<Memo>(`/review-queue/${memoId}/skip`, {
    method: "POST",
    body: JSON.stringify({ expected_version: expectedVersion }),
  });
}

export async function uploadMemoAudio(
  memoId: string,
  expectedVersion: number,
  audio: Blob,
  durationMs: number,
): Promise<Memo> {
  const response = await fetch(
    `${API_BASE_URL}/memos/${memoId}/audio?expected_version=${expectedVersion}`,
    {
      method: "POST",
      headers: {
        "Content-Type": audio.type || "audio/webm",
        "X-Audio-Duration-Ms": String(durationMs),
      },
      body: audio,
    },
  );
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as {
      detail?: string | { message?: string };
    } | null;
    const detail = payload?.detail;
    const message =
      typeof detail === "string"
        ? detail
        : detail?.message ?? `录音上传失败（${response.status}）`;
    throw new ApiError(message, response.status);
  }
  return (await response.json()) as Memo;
}

export function memoAudioUrl(memoId: string): string {
  return `${API_BASE_URL}/memos/${memoId}/audio`;
}
