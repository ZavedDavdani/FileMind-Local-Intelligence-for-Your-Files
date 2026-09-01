export type IntegrityMode = "NORMAL" | "STRICT";

export type IndexStatus =
  | "DISCOVERED"
  | "QUEUED"
  | "PROCESSING"
  | "INDEXED"
  | "FAILED"
  | "SKIPPED"
  | "MISSING";

export interface Folder {
  folder_id: string;
  path: string;
  recursive: boolean;
  integrity_mode: IntegrityMode;
  indexing_enabled: boolean;
  exclude_patterns: string[];
  created_at?: string;
  updated_at?: string;
}

export interface FileItem {
  file_id?: string;
  folder_id?: string;
  path: string;
  relative_path: string;
  filename: string;
  extension: string;
  mime_type?: string | null;
  size_bytes: number;
  modified_at: string;
  created_at?: string | null;
  last_seen_at?: string | null;
  sha256?: string | null;
  index_status: IndexStatus;
  indexing_error?: string | null;
  indexed_at?: string | null;
}

export interface ChunkItem {
  chunk_id: string;
  file_id: string;
  source_file: string;
  source_path: string;
  page?: number | null;
  section?: string | null;
  h1_parent?: string | null;
  h2_parent?: string | null;
  line_start?: number | null;
  line_end?: number | null;
  char_start?: number | null;
  char_end?: number | null;
  content_hash: string;
  chunk_index: number;
  parser_name: string;
  parser_version: string;
  chunker_version: string;
  content: string;
  content_type: string;
  token_count: number;
  metadata?: Record<string, any>;
  created_at?: string | null;
}

export interface ChunkListResponse {
  total: number;
  file_id: string;
  filename: string;
  source_path: string;
  chunks: ChunkItem[];
}

export interface DocumentIntelligenceStats {
  total_chunks: number;
  files_with_chunks: number;
  indexed_files: number;
  queued_files: number;
  failed_files: number;
  skipped_files: number;
}

export interface IndexingStatus {
  is_running: boolean;
  is_paused: boolean;
  total_folders: number;
  total_files: number;
  discovered: number;
  queued: number;
  processing: number;
  indexed: number;
  failed: number;
  skipped: number;
  missing: number;
  progress_percent: number;
  last_updated: number;
}

export interface EventItem {
  event_id: string;
  folder_id: string;
  file_id?: string | null;
  event_type: "CREATE" | "MODIFY" | "DELETE" | "MOVE" | "RENAME";
  path: string;
  old_path?: string | null;
  observed_at?: string | null;
  processed_at?: string | null;
  processing_status: "PENDING" | "PROCESSED" | "IGNORED" | "FAILED";
}

export interface JobItem {
  job_id: string;
  file_id: string;
  folder_id: string;
  job_type: string;
  status: "PENDING" | "PROCESSING" | "COMPLETED" | "FAILED" | "CANCELLED";
  priority: number;
  attempts: number;
  error?: string | null;
  created_at?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  retry_at?: string | null;
}

export interface HealthResponse {
  status: string;
  service: string;
  version: string;
  port: number;
}

export interface ActionResponse {
  success: boolean;
  action: string;
  target_path: string;
  message: string;
}

export interface SearchResultItem {
  rank: number;
  chunk_id: string;
  file_id: string;
  score: number;
  reranker_score?: number | null;
  rrf_score?: number | null;
  lexical_score?: number | null;
  dense_score?: number | null;
  lexical_rank?: number | null;
  dense_rank?: number | null;
  retrieval_method: "hybrid" | "bm25" | "dense" | string;
  source_file: string;
  source_path: string;
  page?: number | null;
  section?: string | null;
  h1_parent?: string | null;
  h2_parent?: string | null;
  line_start?: number | null;
  line_end?: number | null;
  char_start?: number | null;
  char_end?: number | null;
  snippet: string;
  content: string;
  content_hash: string;
  metadata?: Record<string, any>;
}

export interface FolderListResponse {
  value?: Folder[];
  folders?: Folder[];
  Count?: number;
  total?: number;
}

export interface FileListResponse {
  total: number;
  files: FileItem[];
  value?: FileItem[];
  Count?: number;
}

export interface EventListResponse {
  total?: number;
  events?: EventItem[];
  value?: EventItem[];
  Count?: number;
}

export interface JobListResponse {
  total?: number;
  jobs?: JobItem[];
  value?: JobItem[];
  Count?: number;
}

export interface SearchLatencyBreakdown {
  normalization: number;
  lexical_search: number;
  query_embedding: number;
  dense_search: number;
  rrf_fusion: number;
  reranker_inference?: number;
  total_request: number;
}

export interface SearchResponse {
  query: string;
  mode: "hybrid" | "bm25" | "dense" | string;
  total_found: number;
  latency_breakdown_ms: SearchLatencyBreakdown;
  results: SearchResultItem[];
  degraded?: boolean;
  degraded_reason?: string | null;
  retrieval_method?: string | null;
}

export interface SearchRequest {
  query: string;
  mode?: "hybrid" | "bm25" | "dense";
  top_k?: number;
  folder_id?: string;
  extension?: string;
  file_id?: string;
}

