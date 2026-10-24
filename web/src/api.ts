import type {
  AuthProvidersResponse,
  AuthProvider,
  AuthSession,
  AuthUser,
  BookmarkFolderMappingList,
  BookmarkImportBatch,
  BookmarkImportPreview,
  BookmarkInput,
  BrowserBookmarkSnapshot,
  BrowserCaptureContext,
  BrowserHistoryDevice,
  BrowserHistoryListResponse,
  BrowserHistorySettings,
  BrowserOpenTab,
  BrowserOpenTabListResponse,
  CloudAccount,
  CloudAccountCreateRequest,
  EbookJob,
  EbookJobCreateRequest,
  EmailRegisterResponse,
  LinkHealthAction,
  LinkHealthCenter,
  LinkHealthStatus,
  Memo,
  MemoBatchAction,
  MemoBatchResult,
  ImageDuplicateList,
  ImageOrganizationState,
  ImageOrganizationAction,
  MemoCounts,
  MemoCreateRequest,
  MemoListResponse,
  MemoSort,
  MemoStatus,
  MemoType,
  MemoUpdateRequest,
  ModelConnectionResult,
  ModelProvider,
  ModelSetting,
  ModelSettingUpdate,
  ResourceCategoryCreateRequest,
  ResourceCategoryGenerateMode,
  ResourceCategoryGenerateResponse,
  ResourceCategoryOption,
  ResourceCategoryRule,
  ResourceCategoryRuleCreateRequest,
  ResourceCategoryRuleUpdateRequest,
  ResourceCategoryUpdateRequest,
  ResourceCategory,
  ResourceClassificationState,
  ResourceClassificationReviewList,
  ResourceClassificationReviewRequest,
  ResourceClassificationReviewResult,
  ResourceKind,
  ResourceReadingStatus,
  ReviewFeedback,
  ReviewQueueResponse,
  ReviewSettings,
  WordImportResponse,
  WordLookupResponse,
} from "./types";
import extensionManifest from "../../extension/manifest.json";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";
const ACCESS_TOKEN_STORAGE_KEY = "memoisle_access_token";
const EXTENSION_MESSAGE_SOURCE = "memoisle-web";
const EXTENSION_RESPONSE_SOURCE = "memoisle-extension";
const REQUEST_WEB_CONTEXT_MESSAGE = "request-web-context";
const WEB_CONTEXT_MESSAGE = "web-context";

// 扩展按这个地址回连 API。开发时 Vite 会把 /api 代理到真实后端，
// 所以本地端口由启动器改到 5174/5175 也不会让扩展连错地址。
function extensionApiBaseUrl(): string | null {
  try {
    const resolved = new URL(API_BASE_URL, window.location.origin);
    if (resolved.protocol !== "http:" && resolved.protocol !== "https:") {
      return null;
    }
    return resolved.toString().replace(/\/$/, "");
  } catch {
    return null;
  }
}

function notifyBrowserExtension(
  accessToken: string | null,
  requestId?: string,
): void {
  // 扩展内容脚本只在 MemoIsle 页面接收此消息，token 不进入 URL 或服务端日志。
  window.postMessage(
    {
      source: EXTENSION_MESSAGE_SOURCE,
      type: "set-access-token",
      accessToken,
      requestId,
      webOrigin: window.location.origin,
      apiBaseUrl: extensionApiBaseUrl(),
    },
    window.location.origin,
  );
}

function notifyBrowserExtensionWebContext(): void {
  window.postMessage(
    {
      source: EXTENSION_MESSAGE_SOURCE,
      type: WEB_CONTEXT_MESSAGE,
      webOrigin: window.location.origin,
      apiBaseUrl: extensionApiBaseUrl(),
    },
    window.location.origin,
  );
}

// 扩展内容脚本注入后会询问当前地址，网页先回答，未登录也能回答。
window.addEventListener("message", (event) => {
  if (
    event.source !== window ||
    event.origin !== window.location.origin ||
    event.data?.source !== EXTENSION_RESPONSE_SOURCE ||
    event.data.type !== REQUEST_WEB_CONTEXT_MESSAGE
  ) {
    return;
  }
  notifyBrowserExtensionWebContext();
});

export function getAccessToken(): string | null {
  return window.localStorage.getItem(ACCESS_TOKEN_STORAGE_KEY);
}

export function setAccessToken(token: string): void {
  window.localStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, token);
  notifyBrowserExtension(token);
}

export function clearAccessToken(): void {
  window.localStorage.removeItem(ACCESS_TOKEN_STORAGE_KEY);
  notifyBrowserExtension(null);
}

export async function syncBrowserExtension(): Promise<boolean> {
  const accessToken = getAccessToken();
  if (!accessToken) {
    return false;
  }
  const requestId = crypto.randomUUID();
  return new Promise((resolve) => {
    let settled = false;
    const finish = (connected: boolean): void => {
      if (settled) {
        return;
      }
      settled = true;
      window.clearTimeout(timeoutId);
      window.removeEventListener("message", handleMessage);
      resolve(connected);
    };
    const handleMessage = (event: MessageEvent): void => {
      if (
        event.source !== window ||
        event.origin !== window.location.origin ||
        event.data?.source !== EXTENSION_RESPONSE_SOURCE ||
        event.data.type !== "access-token-synced" ||
        event.data.requestId !== requestId
      ) {
        return;
      }
      finish(event.data.ok === true);
    };
    const timeoutId = window.setTimeout(() => finish(false), 3_000);
    window.addEventListener("message", handleMessage);
    notifyBrowserExtension(accessToken, requestId);
  });
}

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

function readApiErrorDetail(
  detail: string | { message?: string } | Array<{ msg?: string }> | undefined,
  fallback: string,
): string {
  if (typeof detail === "string") {
    return detail;
  }
  if (Array.isArray(detail)) {
    const msg = detail.find((item) => typeof item?.msg === "string")?.msg;
    return msg ? msg.replace(/^Value error, /, "") : fallback;
  }
  if (detail && typeof detail.message === "string") {
    return detail.message;
  }
  return fallback;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  if (import.meta.env.DEV && /^\/api\//.test(path)) {
    // API_BASE_URL 默认就是 /api/v1，调用方再写一遍会变成
    // /api/v1/api/v1/...，而 tsc 与打包都不会报错，只有运行时 404。
    // 开发期直接抛错，避免同类问题再次悄悄上线。
    throw new Error(`路径不要自带 /api 前缀：${path}`);
  }
  const accessToken = getAccessToken();
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      ...init?.headers,
    },
  });

  if (!response.ok) {
    if (response.status === 401) {
      clearAccessToken();
    }
    const payload = (await response.json().catch(() => null)) as {
      detail?: string | {
        message?: string;
        code?: string;
        current?: Memo;
      } | Array<{ msg?: string }>;
    } | null;
    const detail = payload?.detail;
    const message = readApiErrorDetail(detail, `请求失败（${response.status}）`);
    const code = detail && !Array.isArray(detail) && typeof detail === "object"
      ? detail.code
      : undefined;
    const current = detail && !Array.isArray(detail) && typeof detail === "object"
      ? detail.current
      : undefined;
    throw new ApiError(message, response.status, code, current);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export function authAuthorizationUrl(
  provider: AuthProvider,
  redirectTo: string,
): string {
  const searchParams = new URLSearchParams({ redirect_to: redirectTo });
  return `${API_BASE_URL}/auth/${provider}/authorize?${searchParams}`;
}

export function androidDownloadUrl(): string {
  return `${API_BASE_URL}/android/download`;
}

export async function getAuthProviders(): Promise<AuthProvidersResponse> {
  return request<AuthProvidersResponse>("/auth/providers");
}

export async function devLogin(): Promise<AuthSession> {
  return request<AuthSession>("/auth/dev-login", { method: "POST" });
}

export async function registerWithEmail(
  email: string,
  password: string,
  confirmPassword: string,
  verificationCode: string,
  displayName?: string,
): Promise<EmailRegisterResponse> {
  return request<EmailRegisterResponse>("/auth/register", {
    method: "POST",
    body: JSON.stringify({
      email,
      password,
      confirm_password: confirmPassword,
      verification_code: verificationCode,
      display_name: displayName?.trim() || undefined,
    }),
  });
}

export async function requestVerificationCode(email: string): Promise<void> {
  await request<{ status: string }>("/auth/verification-code", {
    method: "POST",
    body: JSON.stringify({ email }),
  });
}

export async function requestEmailVerification(email: string): Promise<void> {
  await request<{ status: string }>("/auth/verify-email/request", {
    method: "POST",
    body: JSON.stringify({ email }),
  });
}

export async function verifyEmailToken(token: string): Promise<void> {
  await request<{ status: string }>("/auth/verify-email", {
    method: "POST",
    body: JSON.stringify({ token }),
  });
}

export async function requestPasswordReset(email: string): Promise<void> {
  await request<{ status: string }>("/auth/password-reset/request", {
    method: "POST",
    body: JSON.stringify({ email }),
  });
}

export async function resetPassword(
  token: string,
  password: string,
  confirmPassword: string,
): Promise<void> {
  await request<{ status: string }>("/auth/password-reset", {
    method: "POST",
    body: JSON.stringify({
      token,
      password,
      confirm_password: confirmPassword,
    }),
  });
}

export async function loginWithEmail(
  email: string,
  password: string,
): Promise<AuthSession> {
  return request<AuthSession>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export async function changePassword(
  currentPassword: string,
  password: string,
  confirmPassword: string,
): Promise<void> {
  await request<{ status: string }>("/auth/password-change", {
    method: "POST",
    body: JSON.stringify({
      current_password: currentPassword,
      password,
      confirm_password: confirmPassword,
    }),
  });
}

export async function getAuthUser(): Promise<AuthUser> {
  return request<AuthUser>("/auth/me");
}

export type DataExportFormat = "json" | "csv" | "markdown";

export async function downloadUserData(
  format: DataExportFormat = "json",
): Promise<Blob> {
  const accessToken = getAccessToken();
  const response = await fetch(`${API_BASE_URL}/exports/${format}`, {
    headers: {
      Accept: "application/json",
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
    },
  });
  if (!response.ok) {
    if (response.status === 401) {
      clearAccessToken();
    }
    const payload = (await response.json().catch(() => null)) as {
      detail?: string;
    } | null;
    throw new ApiError(
      payload?.detail ?? `数据导出失败（${response.status}）`,
      response.status,
    );
  }
  return response.blob();
}

export async function importLibraryData(file: File): Promise<WordImportResponse> {
  const accessToken = getAccessToken();
  const format = file.name.toLowerCase().endsWith(".csv") ? "csv" : "json";
  const response = await fetch(`${API_BASE_URL}/imports?format=${format}`, {
    method: "POST",
    headers: {
      "Content-Type": format === "csv" ? "text/csv" : "application/json",
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
    },
    body: file,
  });
  if (!response.ok) {
    if (response.status === 401) {
      clearAccessToken();
    }
    const payload = (await response.json().catch(() => null)) as {
      detail?: string;
    } | null;
    throw new ApiError(
      payload?.detail ?? `数据导入失败（${response.status}）`,
      response.status,
    );
  }
  return (await response.json()) as WordImportResponse;
}

export async function importWords(file: File): Promise<WordImportResponse> {
  // 从 JSON 导出或 CSV 文件导入单词，原始文件内容只发送到当前 API。
  const accessToken = getAccessToken();
  const format = file.name.toLowerCase().endsWith(".csv") ? "csv" : "json";
  const response = await fetch(`${API_BASE_URL}/words/import?format=${format}`, {
    method: "POST",
    headers: {
      "Content-Type": format === "csv" ? "text/csv" : "application/json",
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
    },
    body: file,
  });
  if (!response.ok) {
    if (response.status === 401) {
      clearAccessToken();
    }
    const payload = (await response.json().catch(() => null)) as {
      detail?: string;
    } | null;
    throw new ApiError(
      payload?.detail ?? `单词导入失败（${response.status}）`,
      response.status,
    );
  }
  return (await response.json()) as WordImportResponse;
}

export async function logout(): Promise<void> {
  await request<{ revoked: boolean }>("/auth/logout", { method: "POST" });
  clearAccessToken();
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

export async function applyMemoBatch(action: MemoBatchAction, items: Array<{ memo_id: string; expected_version: number }>): Promise<MemoBatchResult> {
  return request<MemoBatchResult>("/memos/batch", { method: "POST", body: JSON.stringify({ action, items }) });
}

export async function getImageOrganization(): Promise<ImageOrganizationState> {
  return request<ImageOrganizationState>("/images/organization");
}
export async function startImageOrganization(action: ImageOrganizationAction, selected?: Memo[]): Promise<ImageOrganizationState> {
  return request<ImageOrganizationState>("/images/organization", { method: "POST", body: JSON.stringify({
    action, scope: selected ? "selected" : "all", items: selected ? selected.map((item) => ({ memo_id: item.id, expected_version: item.version })) : [],
  }) });
}
export async function resumeImageOrganization(): Promise<ImageOrganizationState> {
  return request<ImageOrganizationState>("/images/organization/resume", { method: "POST" });
}
export async function getImageDuplicates(offset = 0): Promise<ImageDuplicateList> {
  return request<ImageDuplicateList>(`/images/duplicates?offset=${offset}&limit=10`);
}
export async function getImageDuplicateGroup(hash: string, offset = 0): Promise<MemoListResponse> {
  return request<MemoListResponse>(`/images/duplicates/${encodeURIComponent(hash)}?offset=${offset}&limit=50`);
}

export async function getResourceCategories(): Promise<ResourceCategoryOption[]> {
  return request<ResourceCategoryOption[]>("/resource-categories");
}


export async function getResourceClassificationState(): Promise<ResourceClassificationState> {
  return request<ResourceClassificationState>("/resource-classification");
}

export async function startResourceClassification(): Promise<ResourceClassificationState> {
  return request<ResourceClassificationState>("/resource-classification", { method: "POST" });
}

export async function resumeResourceClassification(): Promise<ResourceClassificationState> {
  return request<ResourceClassificationState>("/resource-classification/resume", { method: "POST" });
}

export async function retryResourceClassificationReviews(): Promise<ResourceClassificationState> {
  return request<ResourceClassificationState>("/resource-classification/review/retry", { method: "POST" });
}

export async function retryClassifiedResources(): Promise<ResourceClassificationState> {
  return request<ResourceClassificationState>("/resource-classification/classified/retry", { method: "POST" });
}

export async function retryFolderClassifications(): Promise<ResourceClassificationState> {
  return request<ResourceClassificationState>("/resource-classification/folders/retry", { method: "POST" });
}

export async function getBookmarkFolderMappings(): Promise<BookmarkFolderMappingList> {
  return request<BookmarkFolderMappingList>("/resource-classification/folders");
}

export async function mapPendingBookmarkFolders(limit = 5): Promise<BookmarkFolderMappingList> {
  return request<BookmarkFolderMappingList>(`/resource-classification/folders/map?limit=${limit}`, { method: "POST" });
}

export async function setBookmarkFolderOverride(
  key: string,
  mode: "category" | "skip" | "auto",
  categoryCode?: string,
): Promise<BookmarkFolderMappingList> {
  return request<BookmarkFolderMappingList>("/resource-classification/folders/override", {
    method: "PUT",
    body: JSON.stringify({ key, mode, category_code: categoryCode ?? null }),
  });
}

export async function getResourceClassificationReviews(
  filters: { query: string; reason: string; candidate_code: string; max_confidence: string; offset: number },
): Promise<ResourceClassificationReviewList> {
  const params = new URLSearchParams({ limit: "50", offset: String(filters.offset) });
  for (const key of ["query", "reason", "candidate_code", "max_confidence"] as const) {
    if (filters[key]) params.set(key, filters[key]);
  }
  return request<ResourceClassificationReviewList>(`/resource-classification/review?${params}`);
}

export async function confirmResourceClassificationReviews(
  payload: ResourceClassificationReviewRequest,
): Promise<ResourceClassificationReviewResult> {
  return request<ResourceClassificationReviewResult>("/resource-classification/review/confirm", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function generateResourceCategories(
  instructions = "",
  mode: ResourceCategoryGenerateMode = "subcategories",
): Promise<ResourceCategoryGenerateResponse> {
  return request<ResourceCategoryGenerateResponse>("/resource-categories/generate", {
    method: "POST",
    body: JSON.stringify({ instructions, max_categories: 12, mode }),
  });
}

// payload 原样透传，包含 definition / include_examples / exclude_examples 三个口径字段。
export async function createResourceCategory(
  payload: ResourceCategoryCreateRequest,
): Promise<ResourceCategoryOption> {
  return request<ResourceCategoryOption>("/resource-categories", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

// payload 原样透传（含三个口径字段），expected_version 由调用方一并带上。
export async function updateResourceCategory(
  categoryId: string,
  payload: ResourceCategoryUpdateRequest,
): Promise<ResourceCategoryOption> {
  return request<ResourceCategoryOption>(`/resource-categories/${categoryId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function deleteResourceCategory(
  categoryId: string,
): Promise<{ deleted: boolean }> {
  return request<{ deleted: boolean }>(`/resource-categories/${categoryId}`, {
    method: "DELETE",
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

export interface ResourceOpenStats {
  resource_open_count: number;
  resource_last_opened_at: string;
}

// keepalive 让请求在页面随后跳走或关闭时仍能发出。
export async function recordResourceOpen(memoId: string): Promise<ResourceOpenStats> {
  return request<ResourceOpenStats>(`/resources/${memoId}/open`, {
    method: "POST",
    keepalive: true,
  });
}

export interface VaultKeyMaterial {
  kdf: string;
  kdf_iterations: number;
  kdf_salt: string;
  wrapped_key: string;
  wrap_iv: string;
}

export interface VaultStatus extends Partial<VaultKeyMaterial> {
  configured: boolean;
  version: number | null;
  item_count: number;
}

export interface VaultItemRecord {
  id: string;
  ciphertext: string;
  iv: string;
  version: number;
  created_at: string;
  updated_at: string;
}

// 密码库接口只收发密文，主密码和库密钥从不出现在请求里。
export async function getVaultStatus(): Promise<VaultStatus> {
  return request<VaultStatus>("/vault");
}

export async function createVault(material: VaultKeyMaterial): Promise<VaultStatus> {
  return request<VaultStatus>("/vault", { method: "POST", body: JSON.stringify(material) });
}

export async function updateVaultKey(
  material: VaultKeyMaterial,
  expectedVersion: number,
): Promise<VaultStatus> {
  return request<VaultStatus>("/vault/key", {
    method: "PUT",
    body: JSON.stringify({ ...material, expected_version: expectedVersion }),
  });
}

export async function resetVault(): Promise<void> {
  return request<void>("/vault?confirm=delete-all-vault-items", { method: "DELETE" });
}

export async function listVaultItems(): Promise<VaultItemRecord[]> {
  return request<VaultItemRecord[]>("/vault/items");
}

export async function createVaultItem(
  id: string,
  encrypted: { ciphertext: string; iv: string },
): Promise<VaultItemRecord> {
  return request<VaultItemRecord>("/vault/items", {
    method: "POST",
    body: JSON.stringify({ id, ...encrypted }),
  });
}

export async function updateVaultItem(
  id: string,
  encrypted: { ciphertext: string; iv: string },
  expectedVersion: number,
): Promise<VaultItemRecord> {
  return request<VaultItemRecord>(`/vault/items/${id}`, {
    method: "PUT",
    body: JSON.stringify({ ...encrypted, expected_version: expectedVersion }),
  });
}

export async function deleteVaultItem(id: string, expectedVersion: number): Promise<void> {
  return request<void>(`/vault/items/${id}?expected_version=${expectedVersion}`, {
    method: "DELETE",
  });
}

export async function listQuickAccess(limit = 8): Promise<Memo[]> {
  return request<Memo[]>(`/resources/quick-access?limit=${limit}`);
}

export async function setQuickAccessHidden(
  memoId: string,
  hidden: boolean,
): Promise<{ resource_quick_access_hidden: boolean }> {
  return request(`/resources/${memoId}/quick-access`, {
    method: "PUT",
    body: JSON.stringify({ hidden }),
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
  // 刷新页面后已有登录态不会触发重新登录，读取前主动恢复扩展同步。
  await syncBrowserExtension();
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), 8_000);
  try {
    const response = await request<BrowserOpenTabListResponse>(
      "/browser-tabs/open",
      { signal: controller.signal },
    );
    return response.items;
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new Error("读取当前浏览器网页超时，请确认扩展已连接后重试。");
    }
    throw error;
  } finally {
    window.clearTimeout(timer);
  }
}

export async function listBrowserHistory(options?: {
  query?: string;
  days?: number;
  limit?: number;
  offset?: number;
  /** 本地日期 YYYY-MM-DD，传了就按日期区间查，优先于 days。 */
  dateFrom?: string;
  dateTo?: string;
  /** 上一页返回的 next_cursor；传了就按游标定位，忽略 offset。 */
  cursor?: string;
  /** 只看某台设备；不传则合并同一账号下所有设备。 */
  deviceId?: string;
}): Promise<BrowserHistoryListResponse> {
  // 唤醒扩展放在打开面板时做一次，翻页和搜索不再重复握手上传。
  const params = new URLSearchParams();
  if (options?.query?.trim()) params.set("q", options.query.trim());
  // days=0 表示不限时间，是有效值，不能用真值判断跳过。
  if (options?.days !== undefined) params.set("days", String(options.days));
  if (options?.limit) params.set("limit", String(options.limit));
  if (options?.offset) params.set("offset", String(options.offset));
  if (options?.dateFrom) params.set("from", options.dateFrom);
  if (options?.dateTo) params.set("to", options.dateTo);
  if (options?.cursor) params.set("cursor", options.cursor);
  if (options?.deviceId) params.set("device_id", options.deviceId);
  // 日期边界必须按用户所在时区换算，否则「今天」会错位。
  params.set("tz_offset", String(new Date().getTimezoneOffset() * -1));
  const suffix = params.toString() ? `?${params}` : "";
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), 8_000);
  try {
    return await request<BrowserHistoryListResponse>(
      `/browser-history${suffix}`,
      { signal: controller.signal },
    );
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new Error("读取浏览历史超时，请确认扩展已连接后重试。");
    }
    throw error;
  } finally {
    window.clearTimeout(timer);
  }
}

/** 给设备改名，便于区分两台同款电脑。 */
export async function renameBrowserHistoryDevice(
  deviceId: string,
  deviceName: string,
): Promise<BrowserHistoryDevice> {
  return request<BrowserHistoryDevice>(
    `/browser-history/devices/${encodeURIComponent(deviceId)}`,
    {
      method: "PATCH",
      body: JSON.stringify({ device_name: deviceName }),
    },
  );
}

/** 删除一台设备及其历史，其他设备不受影响。 */
export async function deleteBrowserHistoryDevice(
  deviceId: string,
): Promise<void> {
  await request<void>(
    `/browser-history/devices/${encodeURIComponent(deviceId)}`,
    { method: "DELETE" },
  );
}

/** 把一台设备的历史并进另一台，用于确认「同一台机器重装」。 */
export async function mergeBrowserHistoryDevice(
  deviceId: string,
  targetDeviceId: string,
): Promise<void> {
  await request<void>(
    `/browser-history/devices/${encodeURIComponent(deviceId)}/merge`,
    {
      method: "POST",
      body: JSON.stringify({ target_device_id: targetDeviceId }),
    },
  );
}

export async function clearBrowserHistory(): Promise<void> {
  await request<void>("/browser-history", { method: "DELETE" });
}

export async function getBrowserHistorySettings(): Promise<BrowserHistorySettings> {
  return request<BrowserHistorySettings>("/browser-history/settings");
}

export async function updateBrowserHistorySettings(payload: {
  extended_search_enabled: boolean;
}): Promise<BrowserHistorySettings> {
  return request<BrowserHistorySettings>("/browser-history/settings", {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function browserExtensionDownloadUrl(): string {
  return `${API_BASE_URL}/browser-extension/download`;
}

export function browserExtensionArchiveFilename(): string {
  return `memoisle-browser-extension-${extensionManifest.version}.zip`;
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

export async function updateLinkHealthSettings(payload: {
  enabled?: boolean;
  interval_hours?: number;
}): Promise<LinkHealthCenter> {
  return request<LinkHealthCenter>("/resources/link-health/settings", {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function updateLinkHealthSitePause(
  hostname: string,
  paused: boolean,
): Promise<LinkHealthCenter> {
  return request<LinkHealthCenter>("/resources/link-health/site-pauses", {
    method: "POST",
    body: JSON.stringify({ hostname, paused }),
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

export async function lookupWord(word: string): Promise<WordLookupResponse> {
  return request<WordLookupResponse>("/words/lookup", {
    method: "POST",
    body: JSON.stringify({ word }),
  });
}

export async function synthesizeSpeech(
  text: string,
  voice?: string,
): Promise<Blob> {
  const accessToken = getAccessToken();
  const response = await fetch(`${API_BASE_URL}/speech/tts`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "audio/wav",
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
    },
    body: JSON.stringify({ text, voice }),
  });
  if (!response.ok) {
    if (response.status === 401) {
      clearAccessToken();
    }
    const payload = (await response.json().catch(() => null)) as {
      detail?: string | { message?: string };
    } | null;
    const detail = payload?.detail;
    const message =
      typeof detail === "string"
        ? detail
        : detail?.message ?? `语音合成失败（${response.status}）`;
    throw new ApiError(message, response.status);
  }
  return response.blob();
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

export async function getMemo(memoId: string): Promise<Memo> {
  return request<Memo>(`/memos/${memoId}`);
}

export async function recognizeMemoImageOcr(memoId: string): Promise<Memo> {
  // 服务端未启用 OCR 时返回 503，由调用方按状态码提示。
  return request<Memo>(`/memos/${memoId}/image/ocr`, { method: "POST" });
}

export async function trashMemo(
  memoId: string,
  expectedVersion: number,
): Promise<Memo> {
  return request<Memo>(
    `/memos/${memoId}?expected_version=${expectedVersion}`,
    { method: "DELETE" },
  );
}

export async function restoreMemo(
  memoId: string,
  expectedVersion: number,
): Promise<Memo> {
  return request<Memo>(
    `/memos/${memoId}/restore?expected_version=${expectedVersion}`,
    { method: "POST" },
  );
}

export async function restoreAllTrash(): Promise<{ restored_count: number }> {
  return request<{ restored_count: number }>("/memos/trash/restore", {
    method: "POST",
  });
}

export async function emptyTrash(): Promise<{ deleted_count: number }> {
  return request<{ deleted_count: number }>("/memos/trash", { method: "DELETE" });
}

export async function permanentlyDeleteMemo(
  memoId: string,
  expectedVersion: number,
): Promise<void> {
  await request<{ status: string }>(
    `/memos/${memoId}/permanent?expected_version=${expectedVersion}`,
    { method: "DELETE" },
  );
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

export async function getReviewSettings(): Promise<ReviewSettings> {
  return request<ReviewSettings>("/review-settings");
}

export async function updateReviewSettings(payload: {
  daily_limit?: number;
  intervals_days?: number[];
}): Promise<ReviewSettings> {
  return request<ReviewSettings>("/review-settings", {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
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
  const accessToken = getAccessToken();
  const response = await fetch(
    `${API_BASE_URL}/memos/${memoId}/audio?expected_version=${expectedVersion}`,
    {
      method: "POST",
      headers: {
        "Content-Type": audio.type || "audio/webm",
        "X-Audio-Duration-Ms": String(durationMs),
        ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
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

export async function loadMemoAudioUrl(memoId: string): Promise<string> {
  const accessToken = getAccessToken();
  const response = await fetch(`${API_BASE_URL}/memos/${memoId}/audio`, {
    headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
  });
  if (!response.ok) {
    clearAccessToken();
    throw new ApiError(`录音读取失败（${response.status}）`, response.status);
  }
  const audio = await response.blob();
  return URL.createObjectURL(audio);
}

export async function createImageMemo(
  title?: string,
  body = "",
  clientId: string = crypto.randomUUID(),
): Promise<Memo> {
  // 图片收藏允许正文为空，标题留空时由服务端回退为“图片收藏”。
  return createMemo(
    {
      type: "image",
      title: title?.trim() || undefined,
      body,
      tags: [],
    },
    clientId,
  );
}

export async function uploadMemoImage(
  memoId: string,
  file: File | Blob,
  expectedVersion: number,
): Promise<Memo> {
  // 图片接口接收原始二进制，不使用 multipart。
  const accessToken = getAccessToken();
  const response = await fetch(
    `${API_BASE_URL}/memos/${memoId}/image?expected_version=${expectedVersion}`,
    {
      method: "POST",
      headers: {
        "Content-Type": file.type || "application/octet-stream",
        ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      },
      body: file,
    },
  );
  if (!response.ok) {
    if (response.status === 401) {
      clearAccessToken();
    }
    const payload = (await response.json().catch(() => null)) as {
      detail?: string | { message?: string; code?: string; current?: Memo };
    } | null;
    const detail = payload?.detail;
    const message =
      typeof detail === "string"
        ? detail
        : detail?.message ?? `图片上传失败（${response.status}）`;
    const code = typeof detail === "object" ? detail?.code : undefined;
    const current = typeof detail === "object" ? detail?.current : undefined;
    throw new ApiError(message, response.status, code, current);
  }
  return (await response.json()) as Memo;
}

export async function loadMemoImageUrl(
  memoId: string,
  variant: "thumbnail" | "original" = "thumbnail",
): Promise<string> {
  // 图片接口需要 Bearer 头，因此先读取 Blob 再生成对象 URL。
  const accessToken = getAccessToken();
  const suffix = variant === "original" ? "" : "/thumbnail";
  const response = await fetch(`${API_BASE_URL}/memos/${memoId}/image${suffix}`, {
    headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
  });
  if (!response.ok) {
    if (response.status === 401) {
      clearAccessToken();
    }
    throw new ApiError(
      variant === "original"
        ? `原图读取失败（${response.status}）`
        : `缩略图读取失败（${response.status}）`,
      response.status,
    );
  }
  const image = await response.blob();
  return URL.createObjectURL(image);
}

export async function listModelSettings(): Promise<ModelSetting[]> {
  return request<ModelSetting[]>("/model-settings");
}

export async function saveModelSetting(
  provider: ModelProvider,
  payload: ModelSettingUpdate,
): Promise<ModelSetting> {
  return request<ModelSetting>(`/model-settings/${provider}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export async function resetModelSetting(
  provider: ModelProvider,
): Promise<ModelSetting> {
  return request<ModelSetting>(`/model-settings/${provider}`, {
    method: "DELETE",
  });
}

export async function testModelConnection(
  provider: ModelProvider,
  payload: ModelSettingUpdate,
): Promise<ModelConnectionResult> {
  return request<ModelConnectionResult>(`/model-settings/${provider}/test`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function listCloudAccounts(): Promise<CloudAccount[]> {
  return request<CloudAccount[]>("/cloud-accounts");
}

export async function createCloudAccount(
  payload: CloudAccountCreateRequest,
): Promise<CloudAccount> {
  return request<CloudAccount>("/cloud-accounts", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function deleteCloudAccount(
  accountId: string,
): Promise<{ deleted: boolean }> {
  return request<{ deleted: boolean }>(`/cloud-accounts/${accountId}`, {
    method: "DELETE",
  });
}

export async function verifyCloudAccount(
  accountId: string,
): Promise<CloudAccount> {
  return request<CloudAccount>(`/cloud-accounts/${accountId}/verify`, {
    method: "POST",
  });
}

export async function listEbookJobs(): Promise<EbookJob[]> {
  return request<EbookJob[]>("/ebooks/jobs");
}

export async function createEbookJob(
  payload: EbookJobCreateRequest,
): Promise<EbookJob> {
  return request<EbookJob>("/ebooks/jobs", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getEbookJob(jobId: string): Promise<EbookJob> {
  return request<EbookJob>(`/ebooks/jobs/${jobId}`);
}

export async function retryEbookJob(jobId: string): Promise<EbookJob> {
  return request<EbookJob>(`/ebooks/jobs/${jobId}/retry`, {
    method: "POST",
  });
}
