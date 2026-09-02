import type {
  BookmarkImportBatch,
  BookmarkImportPreview,
  BookmarkInput,
  BrowserCaptureContext,
  BrowserOpenTab,
  BrowserOpenTabListResponse,
  LinkHealthAction,
  LinkHealthCenter,
  LinkHealthStatus,
  Memo,
  MemoCreateRequest,
  MemoListResponse,
  MemoSort,
  MemoStatus,
  MemoType,
  MemoUpdateRequest,
  ResourceCategory,
  ResourceKind,
  ResourceReadingStatus,
  ReviewFeedback,
} from "./types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
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
      detail?: string | { message?: string };
    } | null;
    const detail = payload?.detail;
    const message =
      typeof detail === "string"
        ? detail
        : detail?.message ?? `请求失败（${response.status}）`;
    throw new ApiError(message, response.status);
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
}

export async function listMemos(filters: MemoListFilters = {}): Promise<Memo[]> {
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
  const queryString = searchParams.toString();
  const response = await request<MemoListResponse>(
    `/memos${queryString ? `?${queryString}` : ""}`,
  );
  return response.items;
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
