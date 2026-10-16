export type MemoType = "word" | "resource" | "idea" | "image";
export type AuthProvider = "google" | "wechat" | "apple";

export interface AuthProviderInfo {
  provider: AuthProvider;
  label: string;
  enabled: boolean;
}

export interface AuthProvidersResponse {
  providers: AuthProviderInfo[];
  dev_login_available: boolean;
  email_login_enabled: boolean;
}

export interface AuthUser {
  id: string;
  email: string | null;
  email_verified: boolean;
  display_name: string;
  created_at: string;
  updated_at: string;
}

export interface AuthSession {
  access_token: string;
  token_type: string;
  expires_at: string;
  user: AuthUser;
}

export interface EmailRegisterResponse {
  user: AuthUser;
}
export type MemoStatus = "inbox" | "active" | "archived" | "trashed";
export type MemoSort =
  | "updated_desc"
  | "updated_asc"
  | "created_desc"
  | "created_asc"
  | "title_asc"
  | "title_desc"
  | "opened_desc";
export type ReviewFeedback = "forgot" | "fuzzy" | "remembered";
export interface WordLookupSense {
  index: number;
  part_of_speech: string | null;
  definition: string;
  example: string | null;
}

export interface WordLookupResponse {
  word: string;
  lemma: string;
  phonetic: string | null;
  us_audio_url: string | null;
  uk_audio_url: string | null;
  senses: WordLookupSense[];
  source_name?: string | null;
  source_url?: string | null;
}

export interface WordImportError {
  row: number;
  message: string;
}

export interface WordImportResponse {
  total_count: number;
  imported_count: number;
  duplicate_count: number;
  skipped_count: number;
  failed_count: number;
  errors: WordImportError[];
}

export type ResourceCategory = string;
export type ResourceCategoryRuleMatchType = "domain" | "url" | "text";
export type ResourceKind =
  | "article"
  | "video"
  | "course"
  | "tool"
  | "book"
  | "other";
export type ResourceReadingStatus =
  | "unread"
  | "reading"
  | "completed"
  | "archived";
export type ResourceProcessStatus =
  | "none"
  | "pending"
  | "processing"
  | "ready"
  | "failed";
export type ImageOcrStatus =
  | "none"
  | "pending"
  | "processing"
  | "ready"
  | "failed"
  | "disabled";
export type ImageOcrSource = "local" | "llm";
export type LinkHealthStatus =
  | "unchecked"
  | "healthy"
  | "redirected"
  | "changed"
  | "auth_required"
  | "temporary_failure"
  | "failed"
  | "ignored";
export type LinkHealthAction =
  | "retry"
  | "ignore"
  | "resume"
  | "adopt_redirect"
  | "update_url"
  | "update_metadata"
  | "delete";

export interface ResourceClassificationAssessment {
  status: "classified" | "uncertain";
  reason_code: string;
  confidence: number | null;
  threshold: number;
  candidates: Array<{ code: string; label: string; probability: number | null }>;
  input_source: "metadata" | "public_excerpt" | "image_ocr";
  input_excerpt: string | null;
  model: string;
  attempted_at: string;
  // 模型写下的判定依据；fallback_used 为 true 表示这条用了系统兜底分类。
  // reason_code 为 "no_match" 时表示所有自定义分类口径都不匹配。
  reason?: string;
  fallback_used?: boolean;
  // 对话模型列出的全部成立标签；Jev 定案后仍保留。
  proposed_categories?: Array<{ code: string; label: string; probability: number | null }>;
}

export type ResourceClassificationReviewAction = "adopt" | "keep" | "assign";

export interface ResourceClassificationConfirmation {
  action: ResourceClassificationReviewAction;
  confirmed_at: string;
  category_code: string | null;
  category_label: string | null;
}

export interface ResourceClassificationReviewItem {
  id: string;
  version: number;
  title: string;
  source_url: string;
  current_category_label: string | null;
  assessment: ResourceClassificationAssessment | null;
  candidates: Array<{ code: string; label: string; probability: number | null; available: boolean }>;
}

export interface ResourceClassificationReviewList {
  items: ResourceClassificationReviewItem[];
  total_count: number;
  limit: number;
  offset: number;
}

export interface ResourceClassificationReviewRequest {
  action: ResourceClassificationReviewAction;
  items: Array<{ memo_id: string; expected_version: number; candidate_code?: string }>;
  category_code?: string;
}

export interface ResourceClassificationReviewResult {
  updated_count: number;
  skipped_count: number;
  results: Array<{
    memo_id: string;
    status: "updated" | "skipped";
    reason: "missing" | "conflict" | "not_pending" | "no_candidate" | "category_unavailable" | null;
  }>;
}

export interface Memo {
  id: string;
  client_id: string;
  type: MemoType;
  title: string;
  body: string;
  source_url: string | null;
  source_title: string | null;
  resource_page_title: string | null;
  resource_description: string | null;
  resource_site_name: string | null;
  resource_favicon_url: string | null;
  resource_image_url: string | null;
  resource_metadata_status: ResourceProcessStatus;
  resource_metadata_error: string | null;
  resource_category: ResourceCategory | null;
  resource_category_label: string | null;
  resource_categories?: ResourceCategory[];
  resource_category_status: ResourceProcessStatus;
  resource_category_confidence: number | null;
  resource_category_source: string | null;
  resource_ai_classified_at: string | null;
  resource_ai_review_required: boolean;
  resource_text_excerpt?: string | null;
  resource_ai_assessment?: ResourceClassificationAssessment | null;
  resource_ai_confirmation_pending?: boolean;
  resource_ai_confirmation?: ResourceClassificationConfirmation | null;
  resource_kind: ResourceKind | null;
  resource_reading_status: ResourceReadingStatus | null;
  resource_auto_tags: string[];
  resource_last_enriched_at: string | null;
  resource_import_folder: string | null;
  resource_import_batch_id: string | null;
  ebook_provider: CloudProvider | null;
  ebook_file_id: string | null;
  ebook_path: string | null;
  ebook_share_url: string | null;
  ebook_format: string | null;
  ebook_size_bytes: number | null;
  ebook_snapshot: Record<string, unknown> | null;
  link_health_status: LinkHealthStatus;
  link_health_http_status: number | null;
  link_health_error: string | null;
  link_last_checked_at: string | null;
  link_last_success_at: string | null;
  link_next_check_at: string | null;
  link_consecutive_failures: number;
  link_effective_url: string | null;
  word_phonetic: string | null;
  word_us_audio_url: string | null;
  word_uk_audio_url: string | null;
  word_meaning: string | null;
  word_example: string | null;
  familiarity: number;
  review_count: number;
  last_review_at: string | null;
  next_review_at: string | null;
  audio_mime_type: string | null;
  audio_size_bytes: number | null;
  audio_duration_ms: number | null;
  image_mime_type: string | null;
  image_size_bytes: number | null;
  image_width: number | null;
  image_height: number | null;
  image_hash: string | null;
  image_ocr_text: string | null;
  image_ocr_status: ImageOcrStatus;
  image_ocr_error: string | null;
  image_ocr_source: ImageOcrSource | null;
  image_auto_tags: string[];
  image_ocr_updated_at: string | null;
  transcript: string | null;
  transcript_status: string;
  tags: string[];
  collections: string[];
  starred: boolean;
  // 网页资料的打开统计，快速访问按它排序；不随版本号变化。
  resource_open_count: number;
  resource_last_opened_at: string | null;
  // 用户从快速访问移除后仍继续计数。
  resource_quick_access_hidden: boolean;
  status: MemoStatus;
  deleted_at: string | null;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface MemoListResponse {
  items: Memo[];
  total_count: number;
}

export type MemoBatchAction = "trash" | "restore" | "permanent";
export type ImageOrganizationAction = "ocr" | "classify" | "ocr_classify";
export interface ImageOrganizationState {
  pending_ocr_count: number;
  pending_classification_count: number;
  duplicate_group_count: number;
  job: { id: string; action: ImageOrganizationAction; status: "pending" | "processing" | "completed" | "failed";
    total_count: number; processed_count: number; succeeded_count: number; failed_count: number; skipped_count: number; error: string | null } | null;
}
export interface ImageDuplicateList {
  groups: Array<{ image_hash: string; count: number; items: Array<{ id: string; title: string; version: number }> }>;
  total_count: number;
  limit: number;
  offset: number;
}
export interface MemoBatchResult {
  updated_count: number;
  skipped_count: number;
  results: Array<{ memo_id: string; status: "updated" | "skipped"; reason: "missing" | "conflict" | "not_applicable" | null }>;
}

export interface MemoCounts {
  total_count: number;
  word_count: number;
  resource_count: number;
  idea_count: number;
  image_count: number;
  inbox_count: number;
}

export interface ReviewQueueResponse {
  items: Memo[];
  word_count: number;
  resource_count: number;
  idea_count: number;
  daily_limit: number;
  scheduled_count: number;
}

export interface ReviewSettings {
  daily_limit: number;
  intervals_days: number[];
}

export interface ResourceCategoryOption {
  id: string | null;
  code: ResourceCategory;
  name: string;
  description: string | null;
  // 分类口径、属于与不属于的例子，是模型判定的主要依据。
  definition?: string | null;
  include_examples?: string | null;
  exclude_examples?: string | null;
  is_system: boolean;
  is_active: boolean;
  version: number;
  parent_code?: string | null;
  depth?: number;
  path?: string;
}

export interface ResourceCategoryRule {
  id: string;
  name: string;
  category_code: ResourceCategory;
  category_label: string;
  match_type: ResourceCategoryRuleMatchType;
  pattern: string;
  priority: number;
  enabled: boolean;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface ResourceCategoryCreateRequest {
  name: string;
  description?: string;
  parent_code?: string;
  definition?: string | null;
  include_examples?: string | null;
  exclude_examples?: string | null;
}

export interface ResourceCategorySuggestion {
  name: string;
  description: string | null;
  parent_code: string | null;
  existing_code?: string | null;
  examples?: string[];
}

export type ResourceCategoryGenerateMode = "subcategories" | "top_level";

export interface ResourceCategoryGenerateResponse {
  model: string;
  categories: ResourceCategorySuggestion[];
}

export interface ResourceCategoryUpdateRequest {
  expected_version: number;
  name?: string;
  description?: string | null;
  definition?: string | null;
  include_examples?: string | null;
  exclude_examples?: string | null;
  is_active?: boolean;
  parent_code?: string | null;
}

export interface ResourceCategoryRuleCreateRequest {
  name?: string;
  category_code: ResourceCategory;
  match_type: ResourceCategoryRuleMatchType;
  pattern: string;
  priority?: number;
  enabled?: boolean;
}

export interface ResourceCategoryRuleUpdateRequest {
  expected_version: number;
  name?: string;
  category_code?: ResourceCategory;
  match_type?: ResourceCategoryRuleMatchType;
  pattern?: string;
  priority?: number;
  enabled?: boolean;
}

export interface MemoCreateRequest {
  client_id: string;
  type: MemoType;
  title?: string;
  body: string;
  source_url?: string;
  source_title?: string;
  word_phonetic?: string;
  word_meaning?: string;
  word_example?: string;
  allow_duplicate?: boolean;
  tags: string[];
  collections?: string[];
  resource_kind?: ResourceKind;
  resource_reading_status?: ResourceReadingStatus;
  starred?: boolean;
}

export interface MemoUpdateRequest {
  expected_version: number;
  type?: MemoType;
  title?: string;
  body?: string;
  source_url?: string;
  source_title?: string;
  word_phonetic?: string;
  word_meaning?: string;
  word_example?: string;
  resource_category?: ResourceCategory;
  resource_categories?: ResourceCategory[];
  resource_kind?: ResourceKind;
  resource_reading_status?: ResourceReadingStatus;
  tags?: string[];
  collections?: string[];
  starred?: boolean;
  status?: MemoStatus;
}

export interface BookmarkInput {
  client_item_id: string;
  title: string;
  url: string;
  folder_path?: string | null;
}

export interface BrowserBookmarkSnapshot {
  extension_connected: boolean;
  synced_at: string | null;
  total_count: number;
  truncated: boolean;
  items: BookmarkInput[];
}

export interface BookmarkPreviewItem {
  client_item_id: string;
  title: string;
  url: string;
  normalized_url: string | null;
  folder_path: string | null;
  status: "valid" | "duplicate" | "invalid";
  existing_memo_id: string | null;
  error_code: string | null;
}

export interface BookmarkImportPreview {
  total_count: number;
  valid_count: number;
  duplicate_count: number;
  invalid_count: number;
  items: BookmarkPreviewItem[];
}

export interface BookmarkImportItem {
  client_item_id: string;
  title: string;
  source_url: string;
  normalized_url: string;
  folder_path: string | null;
  status: string;
  memo_id: string | null;
  existing_memo_id: string | null;
  error_code: string | null;
}

export interface BookmarkImportBatch {
  id: string;
  status: string;
  total_count: number;
  valid_count: number;
  duplicate_count: number;
  invalid_count: number;
  imported_count: number;
  failed_count: number;
  created_at: string;
  updated_at: string;
  undone_at: string | null;
  items: BookmarkImportItem[];
}

export interface BrowserCaptureContext {
  page_url: string;
  page_title: string;
  favicon_url: string | null;
  nonce: string;
}

export interface BrowserOpenTab {
  id: string;
  tab_id: number;
  window_id: number | null;
  page_url: string;
  page_title: string;
  favicon_url: string | null;
  last_seen_at: string;
}

export interface BrowserOpenTabListResponse {
  items: BrowserOpenTab[];
}

export interface LinkHealthCenter {
  items: Memo[];
  counts: Record<LinkHealthStatus, number> & { review_pending?: number };
  settings: LinkHealthSettings;
}

export interface LinkHealthSettings {
  enabled: boolean;
  interval_hours: number;
  paused_sites: string[];
}

export type CloudProvider = "aliyun" | "baidu";

export type ModelProvider = "deepseek" | "jev";

export interface ModelSetting {
  provider: ModelProvider;
  model: string;
  base_url: string;
  default_base_url: string;
  custom_base_url: string | null;
  enabled: boolean;
  has_api_key: boolean;
  key_hint: string;
  credential_source: "account" | "environment" | "none";
  has_custom_settings: boolean;
  error: string | null;
  min_confidence: number;
  default_min_confidence: number;
}

export interface ModelSettingUpdate {
  model: string;
  enabled: boolean;
  api_key?: string;
  base_url?: string | null;
  /** 留空（null）恢复服务器默认阈值。 */
  min_confidence?: number | null;
}

export interface ModelConnectionResult {
  provider: ModelProvider;
  model: string;
  message: string;
}


export interface ResourceClassificationJob {
  id: string;
  status: "pending" | "processing" | "completed" | "failed";
  model: string;
  automatic: boolean;
  total_count: number;
  processed_count: number;
  succeeded_count: number;
  failed_count: number;
  skipped_count: number;
  error: string | null;
  error_code: string | null;
  retry_count: number;
  retry_limit: number;
  next_retry_at: string | null;
  created_at: string;
  finished_at: string | null;
}

export interface ResourceClassificationState {
  pending_count: number;
  classified_count: number;
  protected_count: number;
  deferred_count: number;
  review_count: number;
  classified_retry_count: number;
  job: ResourceClassificationJob | null;
}

export interface CloudAccount {
  id: string;
  provider: CloudProvider;
  display_name: string;
  credential_hint: string;
  default_folder: string;
  status: string;
  last_checked_at: string | null;
  last_error: string | null;
  created_at: string;
  updated_at: string;
}

export interface CloudAccountCreateRequest {
  provider: CloudProvider;
  credential: string;
  default_folder?: string | null;
}

export type EbookJobMode = "transfer" | "upload";

export type EbookJobStatus = "pending" | "running" | "success" | "failed";

export interface EbookJob {
  id: string;
  memo_id: string | null;
  source_url: string;
  provider: CloudProvider;
  mode: EbookJobMode;
  status: EbookJobStatus;
  progress: number;
  stage: string;
  target_folder: string;
  cloud_file_id: string | null;
  cloud_path: string | null;
  error: string | null;
  attempts: number;
  created_at: string;
  updated_at: string;
  finished_at: string | null;
}

export interface EbookJobCreateRequest {
  url: string;
  provider?: CloudProvider | null;
  share_password?: string | null;
  target_folder?: string | null;
  tags?: string[];
  collections?: string[];
  note?: string | null;
}
