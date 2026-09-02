export type MemoType = "word" | "resource" | "idea";
export type MemoStatus = "inbox" | "active" | "archived" | "trashed";
export type MemoSort =
  | "updated_desc"
  | "updated_asc"
  | "created_desc"
  | "created_asc"
  | "title_asc"
  | "title_desc";
export type ReviewFeedback = "forgot" | "fuzzy" | "remembered";
export type ResourceCategory =
  | "learning"
  | "article"
  | "media"
  | "tool"
  | "book_paper"
  | "product"
  | "other";
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
  resource_category_status: ResourceProcessStatus;
  resource_category_confidence: number | null;
  resource_category_source: string | null;
  resource_kind: ResourceKind | null;
  resource_reading_status: ResourceReadingStatus | null;
  resource_auto_tags: string[];
  resource_last_enriched_at: string | null;
  resource_import_folder: string | null;
  resource_import_batch_id: string | null;
  link_health_status: LinkHealthStatus;
  link_health_http_status: number | null;
  link_health_error: string | null;
  link_last_checked_at: string | null;
  link_last_success_at: string | null;
  link_next_check_at: string | null;
  link_consecutive_failures: number;
  link_effective_url: string | null;
  word_phonetic: string | null;
  word_meaning: string | null;
  word_example: string | null;
  familiarity: number;
  review_count: number;
  last_review_at: string | null;
  next_review_at: string | null;
  audio_mime_type: string | null;
  audio_size_bytes: number | null;
  audio_duration_ms: number | null;
  transcript: string | null;
  transcript_status: string;
  tags: string[];
  collections: string[];
  starred: boolean;
  status: MemoStatus;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface MemoListResponse {
  items: Memo[];
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
  tags: string[];
  collections?: string[];
  resource_kind?: ResourceKind;
  resource_reading_status?: ResourceReadingStatus;
  starred?: boolean;
}

export interface MemoUpdateRequest {
  expected_version: number;
  title?: string;
  body?: string;
  source_url?: string;
  source_title?: string;
  word_phonetic?: string;
  word_meaning?: string;
  word_example?: string;
  resource_category?: ResourceCategory;
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
  folder_path?: string;
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
  counts: Record<LinkHealthStatus, number>;
}
