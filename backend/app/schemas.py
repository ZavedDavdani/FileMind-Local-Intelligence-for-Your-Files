"""Pydantic schemas for FileMind API."""

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class IntegrityMode(str, Enum):
    NORMAL = "NORMAL"
    STRICT = "STRICT"


class IndexStatus(str, Enum):
    DISCOVERED = "DISCOVERED"
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    INDEXED = "INDEXED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    MISSING = "MISSING"


class ActionType(str, Enum):
    OPEN_FILE = "OPEN_FILE"
    OPEN_FOLDER = "OPEN_FOLDER"
    COPY_PATH = "COPY_PATH"


class HealthResponse(BaseModel):
    """Deterministic health check contract for Phase 0 and Phase 1."""
    status: str = "healthy"
    service: str = "FileMind Backend"
    version: str = "0.2.0"
    port: int = 24823


# ---------------------------------------------------------------------------
# Folders
# ---------------------------------------------------------------------------

class FolderCreate(BaseModel):
    path: str = Field(..., min_length=1, description="Absolute folder path to register")
    recursive: bool = Field(True, description="Whether to recursively scan subdirectories")
    integrity_mode: IntegrityMode = Field(IntegrityMode.NORMAL, description="Per-folder integrity mode")
    indexing_enabled: bool = Field(True, description="Whether indexing is enabled for this folder")
    exclude_patterns: List[str] = Field(default_factory=list, description="Custom glob exclusion patterns")


class FolderUpdate(BaseModel):
    recursive: Optional[bool] = None
    integrity_mode: Optional[IntegrityMode] = None
    indexing_enabled: Optional[bool] = None
    exclude_patterns: Optional[List[str]] = None


class FolderResponse(BaseModel):
    folder_id: str
    path: str
    recursive: bool
    integrity_mode: str
    indexing_enabled: bool
    exclude_patterns: List[str]
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------

class FileItem(BaseModel):
    file_id: Optional[str] = None
    folder_id: Optional[str] = None
    path: str
    relative_path: str
    filename: str
    extension: str
    mime_type: Optional[str] = None
    size_bytes: int
    modified_at: str
    created_at: Optional[str] = None
    last_seen_at: Optional[str] = None
    sha256: Optional[str] = None
    index_status: str = "DISCOVERED"
    indexing_error: Optional[str] = None
    indexed_at: Optional[str] = None


class FileListResponse(BaseModel):
    total: int
    files: List[FileItem]


# ---------------------------------------------------------------------------
# Phase 2: Document Chunks & Provenance
# ---------------------------------------------------------------------------

class ChunkItem(BaseModel):
    chunk_id: str
    file_id: str
    source_file: str
    source_path: str
    page: Optional[int] = None
    section: Optional[str] = None
    h1_parent: Optional[str] = None
    h2_parent: Optional[str] = None
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    char_start: Optional[int] = None
    char_end: Optional[int] = None
    content_hash: str
    chunk_index: int
    parser_name: str
    parser_version: str
    chunker_version: str
    content: str
    content_type: str = "text"
    token_count: int = 0
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ChunkListResponse(BaseModel):
    total: int
    file_id: str
    chunks: List[ChunkItem]


class DocumentIntelligenceStatsResponse(BaseModel):
    total_chunks: int
    files_with_chunks: int
    indexed_files: int
    queued_files: int
    failed_files: int
    skipped_files: int


# ---------------------------------------------------------------------------
# Indexing & Control
# ---------------------------------------------------------------------------

class IndexingStatusResponse(BaseModel):
    is_running: bool
    is_paused: bool
    total_folders: int
    total_files: int
    discovered: int
    queued: int
    processing: int
    indexed: int
    failed: int
    skipped: int
    missing: int
    progress_percent: float
    last_updated: float


class IndexingControlAction(str, Enum):
    START = "START"
    PAUSE = "PAUSE"
    RESUME = "RESUME"
    STOP = "STOP"
    RESCAN = "RESCAN"


class IndexingControlRequest(BaseModel):
    action: IndexingControlAction
    folder_id: Optional[str] = None


class IndexingControlResponse(BaseModel):
    success: bool
    action: str
    message: str
    status: IndexingStatusResponse


# ---------------------------------------------------------------------------
# Events & Jobs
# ---------------------------------------------------------------------------

class EventItem(BaseModel):
    event_id: str
    folder_id: str
    file_id: Optional[str] = None
    event_type: str
    path: str
    old_path: Optional[str] = None
    observed_at: Optional[str] = None
    processed_at: Optional[str] = None
    processing_status: str


class EventListResponse(BaseModel):
    total: int
    events: List[EventItem]


class JobItem(BaseModel):
    job_id: str
    file_id: str
    folder_id: str
    job_type: str
    status: str
    priority: int
    attempts: int
    error: Optional[str] = None
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    retry_at: Optional[str] = None


class JobListResponse(BaseModel):
    total: int
    jobs: List[JobItem]


# ---------------------------------------------------------------------------
# Filesystem Actions & Legacy Smoke-Test
# ---------------------------------------------------------------------------

class ActionRequest(BaseModel):
    action: ActionType
    target_path: str = Field(..., min_length=1, description="Target file or directory path")


class ActionResponse(BaseModel):
    success: bool
    action: str
    target_path: str
    message: str


class EnumerateRequest(BaseModel):
    folder_path: str = Field(..., min_length=1, description="Absolute folder path to enumerate")


class EnumerateResponse(BaseModel):
    folder_path: str
    file_count: int
    scan_duration_ms: float
    files: List[FileItem]


# ---------------------------------------------------------------------------
# Phase 3: Retrieval API Schemas
# ---------------------------------------------------------------------------

class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, description="Raw user query string")
    mode: str = Field("hybrid", description="Retrieval mode: hybrid, bm25, or dense")
    top_k: int = Field(10, ge=1, le=100, description="Max results to return")
    folder_id: Optional[str] = Field(None, description="Optional folder filter")
    extension: Optional[str] = Field(None, description="Optional file extension filter (e.g. .pdf)")
    file_id: Optional[str] = Field(None, description="Optional file filter")


class SearchResultItem(BaseModel):
    rank: int
    chunk_id: str
    file_id: str
    score: float
    reranker_score: Optional[float] = None
    rrf_score: Optional[float] = None
    lexical_score: Optional[float] = None
    dense_score: Optional[float] = None
    lexical_rank: Optional[int] = None
    dense_rank: Optional[int] = None
    retrieval_method: str
    source_file: str
    source_path: str
    page: Optional[int] = None
    section: Optional[str] = None
    h1_parent: Optional[str] = None
    h2_parent: Optional[str] = None
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    char_start: Optional[int] = None
    char_end: Optional[int] = None
    snippet: str
    content: str
    content_hash: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SearchResponse(BaseModel):
    query: str
    mode: str
    total_found: int
    latency_breakdown_ms: Dict[str, float]
    results: List[SearchResultItem]
    degraded: bool = False
    degraded_reason: Optional[str] = None
    retrieval_method: Optional[str] = None

