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
  sheet_name?: string | null;
  slide_number?: number | null;
  time_start?: number | null;
  time_end?: number | null;
  frame_index?: number | null;
  media_type?: string | null;
  extraction_method?: string | null;
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
  sheet_name?: string | null;
  slide_number?: number | null;
  time_start?: number | null;
  time_end?: number | null;
  frame_index?: number | null;
  media_type?: string | null;
  extraction_method?: string | null;
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
  quality: "fast" | "quality" | string;
  total_found: number;
  latency_breakdown_ms: SearchLatencyBreakdown;
  results: SearchResultItem[];
  degraded?: boolean;
  degraded_reason?: string | null;
  retrieval_method?: string | null;
  explicit_filename_intent?: string | null;
}

export interface SearchRequest {
  query: string;
  mode?: "hybrid" | "bm25" | "dense";
  quality?: "fast" | "quality";
  top_k?: number;
  folder_id?: string;
  extension?: string;
  file_id?: string;
}

// ---------------------------------------------------------------------------
// Ask FileMind Types
// ---------------------------------------------------------------------------

export interface CitationItem {
  citation_id: string;
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
  sheet_name?: string | null;
  slide_number?: number | null;
  time_start?: number | null;
  time_end?: number | null;
  frame_index?: number | null;
  media_type?: string | null;
  extraction_method?: string | null;
  content_hash?: string | null;
  score?: number | null;
  reranker_score?: number | null;
  retrieval_method?: string | null;
}

export interface ModelIdentityInfo {
  provider: string;
  model_name: string;
  is_local: boolean;
  model_tag?: string | null;
}

export interface AskRetrievalMetadata {
  mode: string;
  quality: string;
  total_found: number;
  latency_breakdown_ms?: Record<string, number>;
  degraded?: boolean;
  degraded_reason?: string | null;
}

export interface AskBudgetAccounting {
  total_budget?: number;
  system_reserved?: number;
  output_reserved?: number;
  evidence_budget?: number;
  evidence_used?: number;
  evidence_remaining?: number;
  candidates_considered?: number;
  candidates_included?: number;
  candidates_omitted?: number;
}

export interface AskRequest {
  query: string;
  mode?: "hybrid" | "bm25" | "dense";
  quality?: "fast" | "quality";
  top_k?: number;
  folder_id?: string;
  extension?: string;
  file_id?: string;
}

export interface AskResponse {
  answer: string;
  query: string;
  generation_status:
    | "READY"
    | "NO_EVIDENCE"
    | "BUDGET_LIMITED"
    | "MODEL_UNAVAILABLE"
    | "TIMEOUT"
    | "GENERATION_FAILED"
    | "INVALID_RESPONSE"
    | string;
  evidence_status: "READY" | "NO_EVIDENCE" | "BUDGET_LIMITED" | string;
  citations: CitationItem[];
  unresolved_citations: string[];
  model_identity: ModelIdentityInfo;
  retrieval_metadata: AskRetrievalMetadata;
  context_budget: AskBudgetAccounting;
  error?: string | null;
}

export interface OllamaReadinessStatus {
  is_ollama_online: boolean;
  has_default_model: boolean;
  model_name: string;
  endpoint: string;
  error?: string | null;
}

export interface ComponentAIStatus {
  model_name: string;
  provider: string;
  dimension?: number | null;
  status: string;
  error?: string | null;
}

export interface LocalAIStatus {
  status: string;
  embedding: ComponentAIStatus;
  reranker: ComponentAIStatus;
  ollama?: OllamaReadinessStatus | null;
}

export interface CloudAIStatus {
  enabled: boolean;
  status: string;
}

export interface AIStatusResponse {
  local_ai: LocalAIStatus;
  cloud_ai: CloudAIStatus;
}

// ---------------------------------------------------------------------------
// Document Understanding Types
// ---------------------------------------------------------------------------

export interface StructuralSummary {
  filename: string;
  extension: string;
  mime_type?: string | null;
  size_bytes: number;
  total_chunks: number;
  estimated_tokens: number;
  sections: string[];
  pages: number[];
  headings: string[];
}

export interface DocumentInsight {
  insight_id?: string | null;
  file_id: string;
  filename: string;
  status:
    | "NOT_GENERATED"
    | "GENERATING"
    | "READY"
    | "STALE"
    | "MODEL_UNAVAILABLE"
    | "FAILED"
    | string;
  content_hash?: string | null;
  parser_version?: string | null;
  chunker_version?: string | null;
  model_identity: ModelIdentityInfo;
  structural_summary: StructuralSummary;
  executive_summary?: string | null;
  key_topics: string[];
  key_decisions: string[];
  citations: CitationItem[];
  unresolved_citations: string[];
  is_stale: boolean;
  created_at?: string | null;
  updated_at?: string | null;
  error?: string | null;
}

export interface RelatedFileChunkSummary {
  chunk_id: string;
  section?: string | null;
  page?: number | null;
  line_start?: number | null;
  line_end?: number | null;
  snippet: string;
}

export interface RelatedFileItem {
  file_id: string;
  filename: string;
  path: string;
  relative_path?: string | null;
  extension?: string | null;
  size_bytes: number;
  score: number;
  retrieval_method: string;
  explanation: string;
  matching_chunk_count: number;
  primary_matched_chunk: RelatedFileChunkSummary;
  supporting_chunks: RelatedFileChunkSummary[];
}

export interface RelatedFilesResponse {
  source_file_id: string;
  source_filename: string;
  total_found: number;
  retrieval_method: string;
  quality: string;
  query_used?: string | null;
  results: RelatedFileItem[];
}

export interface FolderStructuralSummary {
  folder_id: string;
  folder_name: string;
  path: string;
  total_files: number;
  indexed_files: number;
  unindexed_files: number;
  failed_files: number;
  missing_files: number;
  skipped_files: number;
  total_size_bytes: number;
  total_chunks: number;
  estimated_tokens: number;
  file_type_distribution: Record<string, number>;
  dominant_topics: string[];
  representative_files: string[];
}

export interface FolderInsight {
  insight_id?: string | null;
  folder_id: string;
  folder_name: string;
  status:
    | "NOT_GENERATED"
    | "GENERATING"
    | "READY"
    | "STALE"
    | "NO_EVIDENCE"
    | "MODEL_UNAVAILABLE"
    | "FAILED"
    | string;
  composite_hash?: string | null;
  model_identity: ModelIdentityInfo;
  structural_summary: FolderStructuralSummary;
  executive_summary?: string | null;
  key_themes: string[];
  key_decisions: string[];
  citations: CitationItem[];
  unresolved_citations: string[];
  is_stale: boolean;
  created_at?: string | null;
  updated_at?: string | null;
  error?: string | null;
}

export interface ConnectionEvidence {
  chunk_id: string;
  file_id: string;
  source_file: string;
  source_path: string;
  content_hash?: string | null;
  page?: number | null;
  section?: string | null;
  line_start?: number | null;
  line_end?: number | null;
}

export interface KnowledgeConnection {
  connection_type: "shared_topic" | "file_reference" | string;
  label: string;
  explanation: string;
  target_file: { file_id: string; filename: string; path: string; relative_path?: string | null; content_hash?: string | null };
  source_evidence: ConnectionEvidence[];
  target_evidence: ConnectionEvidence[];
}

export interface KnowledgeConnectionsResponse {
  source_file: { file_id: string; filename: string; path: string; relative_path?: string | null; content_hash?: string | null };
  connections: KnowledgeConnection[];
}


// ---------------------------------------------------------------------------
// : Persistent Chat & Multi-Turn Types
// ---------------------------------------------------------------------------

export type ChatScope = "ALL" | "FOLDER" | "FILE";

export interface ChatMessageItem {
  message_id: string;
  conversation_id: string;
  role: "user" | "assistant" | "system";
  content: string;
  citations: CitationItem[];
  generation_status?: string | null;
  evidence_status?: string | null;
  model_name?: string | null;
  created_at: string;
}

export interface ConversationItem {
  conversation_id: string;
  title: string;
  scope_type: ChatScope;
  scope_id?: string | null;
  message_count: number;
  created_at: string;
  updated_at: string;
}

export interface ConversationDetail {
  conversation_id: string;
  title: string;
  scope_type: ChatScope;
  scope_id?: string | null;
  messages: ChatMessageItem[];
  created_at: string;
  updated_at: string;
}

export interface CreateConversationRequest {
  title?: string;
  scope_type?: ChatScope;
  scope_id?: string | null;
}

export interface SendChatMessageRequest {
  content: string;
  scope_type?: ChatScope;
  scope_id?: string | null;
  quality?: "fast" | "quality" | string;
  mode?: "hybrid" | "bm25" | "dense" | string;
}

// ---------------------------------------------------------------------------
// : Cross-File Intelligence & Synthesis Types
// ---------------------------------------------------------------------------

export interface ComparisonPoint {
  aspect: string;
  file_details: Record<string, string>;
  summary: string;
}

export interface FileComparisonResponse {
  file_ids: string[];
  files: Array<{ file_id: string; filename: string; path: string }>;
  comparison_points: ComparisonPoint[];
  executive_summary: string;
  citations: CitationItem[];
  generation_status: string;
}

export interface FileSynthesisResponse {
  file_ids: string[];
  files: Array<{ file_id: string; filename: string; path: string }>;
  topic: string;
  synthesized_summary: string;
  common_themes: string[];
  key_insights: string[];
  citations: CitationItem[];
  generation_status: string;
}

export interface TopicCluster {
  topic: string;
  file_count: number;
  files: Array<{ file_id: string; filename: string; preview: string }>;
}

export interface KnowledgeOverviewResponse {
  total_indexed_files: number;
  total_chunks: number;
  estimated_tokens: number;
  dominant_topics: string[];
  clusters: TopicCluster[];
  recent_insights: Array<{
    file_id: string;
    filename: string;
    summary_preview: string;
    updated_at: string;
  }>;
}

// ---------------------------------------------------------------------------
// : Models & Diagnostics Settings Types
// ---------------------------------------------------------------------------

export interface ModelStatusResponse {
  available_models: string[];
  active_chat_model: string;
  active_embedding_model: string;
  active_reranker_model: string;
  is_ollama_online: boolean;
  endpoint: string;
  system_recommendations: Record<string, string>;
}

export interface StorageStatsResponse {
  database_size_bytes: number;
  database_size_mb: number;
  fts_size_bytes: number;
  vec_size_bytes: number;
  total_storage_mb: number;
  db_path: string;
}

export interface DiagnosticsResponse {
  app_version: string;
  version: string;
  system_os: string;
  platform: string;
  schema_version: number;
  database_status: string;
  sqlite_version: string;
  vec_version: string;
  vector_store_status: string;
  worker_pool_status: string;
  active_workers: number;
  watcher_status: string;
  total_folders_watched: number;
  indexed_file_count: number;
  error_count: number;
  recent_errors: string[];
  ollama_status: string;
  uptime_seconds: number;
}

// ---------------------------------------------------------------------------
// : Export Types
// ---------------------------------------------------------------------------

export interface ExportResponse {
  format: string;
  filename: string;
  mime_type: string;
  content: string;
}
