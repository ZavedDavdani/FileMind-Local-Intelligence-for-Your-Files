"""FileMind Local Backend Service - Phase 1 Filesystem Engine."""

import os
import sys
import time
import subprocess
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from app import __version__
from app.core.logging_config import setup_logging
from app.core.security import is_path_within_root, normalize_path, paths_overlap
from app.db.connection import db_manager
from app.db.repository import Repository
from app.engine.coordinator import coordinator
from app.schemas import (
    AIStatusResponse,
    ActionRequest,
    ActionResponse,
    ActionType,
    AskRequest,
    AskResponse,
    CloudAIStatus,
    ComponentAIStatus,
    DocumentInsightResponse,
    EnumerateRequest,
    EnumerateResponse,
    EventItem,
    EventListResponse,
    FileItem,
    FileListResponse,
    FolderCreate,
    FolderResponse,
    FolderUpdate,
    HealthResponse,
    IndexingControlAction,
    IndexingControlRequest,
    IndexingControlResponse,
    IndexingStatusResponse,
    JobItem,
    JobListResponse,
    LocalAIStatus,
    OllamaReadinessStatus,
    RelatedFilesResponse,
    SearchRequest,
    SearchResponse,
)
from app.retrieval.model_registry import ModelType, default_model_registry


PORT = 24823
HOST = "127.0.0.1"

# Initialize persistent rotating application logging as early as possible so
# that all subsequent module-level and lifespan-level log calls (coordinator,
# watcher, worker, retrieval, etc.) are actually captured. Previously this
# infrastructure existed (app.core.logging_config.setup_logging) but was
# never invoked anywhere, so every logger.info/warning/error call in the app
# silently went nowhere (no handlers configured on the root logger).
_app_logger = setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager: initializes database migrations, crash recovery, and worker pool."""
    _app_logger.info("FileMind backend starting up (version=%s)", __version__)
    coordinator.initialize()
    yield
    _app_logger.info("FileMind backend shutting down")
    coordinator.shutdown()


app = FastAPI(
    title="FileMind Backend",
    description="FileMind Local-First Desktop Service - Phase 1 Filesystem Engine",
    version=__version__,
    lifespan=lifespan,
)

ALLOWED_ORIGINS = [
    "http://localhost",
    "http://localhost:1420",
    "http://localhost:5173",
    "http://127.0.0.1",
    "http://127.0.0.1:1420",
    "http://127.0.0.1:5173",
    "tauri://localhost",
    "https://tauri.localhost",
    "http://tauri.localhost",
]

# Enable CORS for explicit local webview and dev origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse, tags=["Health"])
def get_health() -> HealthResponse:
    """Deterministic health check endpoint for Tauri desktop supervisor."""
    return HealthResponse(
        status="healthy",
        service="FileMind Backend",
        version=__version__,
        port=PORT,
    )


@app.get("/ai/status", response_model=AIStatusResponse, tags=["AI Readiness"])
def get_ai_status() -> AIStatusResponse:
    """Returns authoritative readiness status for local AI / retrieval components."""
    emb_model = default_model_registry.get_active_model(ModelType.EMBEDDING)
    rerank_model = default_model_registry.get_active_model(ModelType.RERANKER)

    # NOTE: the "else" fallbacks below only trigger if the registry has no
    # entry at all for this model type (should not happen in practice, since
    # both models are registered at import time in model_registry.py). We
    # deliberately default to "unavailable" here, not "ready" — a missing
    # registry entry must never be reported as a verified-ready model.
    emb_status = ComponentAIStatus(
        model_name=emb_model.name if emb_model else "sentence-transformers/all-MiniLM-L6-v2",
        provider=emb_model.provider if emb_model else "fastembed",
        dimension=emb_model.dimension if emb_model else 384,
        status=emb_model.readiness.value if emb_model else "unavailable",
        error=emb_model.error if emb_model else None,
    )

    rerank_status = ComponentAIStatus(
        model_name=rerank_model.name if rerank_model else "BAAI/bge-reranker-base",
        provider=rerank_model.provider if rerank_model else "fastembed",
        dimension=None,
        status=rerank_model.readiness.value if rerank_model else "unavailable",
        error=rerank_model.error if rerank_model else None,
    )

    # Aggregate local AI status. Models use deferred lazy loading, so on a
    # fresh backend start (before the first search request) both components
    # legitimately report "unavailable" — that must surface as a non-ready
    # aggregate state, not silently fall through to "ready".
    if emb_status.status == "failed" and rerank_status.status == "failed":
        local_status = "failed"
    elif emb_status.status in ("failed", "degraded") or rerank_status.status in ("failed", "degraded"):
        local_status = "degraded"
    elif emb_status.status in ("loading", "downloading", "preparing") or rerank_status.status in ("loading", "downloading", "preparing"):
        local_status = "loading"
    elif emb_status.status == "unavailable" or rerank_status.status == "unavailable":
        local_status = "unavailable"
    else:
        local_status = "ready"

    from app.ai.ollama_provider import check_ollama_readiness
    ollama_info = check_ollama_readiness()
    ollama_status = OllamaReadinessStatus(
        is_ollama_online=ollama_info["is_ollama_online"],
        has_default_model=ollama_info["has_default_model"],
        model_name=ollama_info["model_name"],
        endpoint=ollama_info["endpoint"],
        error=ollama_info.get("error"),
    )

    return AIStatusResponse(
        local_ai=LocalAIStatus(
            status=local_status,
            embedding=emb_status,
            reranker=rerank_status,
            ollama=ollama_status,
        ),
        cloud_ai=CloudAIStatus(
            enabled=False,
            status="unavailable",
        ),
    )



# ---------------------------------------------------------------------------
# Folders API
# ---------------------------------------------------------------------------

@app.get("/folders", response_model=List[FolderResponse], tags=["Folders"])
def list_registered_folders() -> List[FolderResponse]:
    """Lists all registered folders tracked by FileMind."""
    with db_manager.session() as conn:
        repo = Repository(conn)
        folders = repo.list_folders()
        return [FolderResponse(**f) for f in folders]


@app.post("/folders", response_model=FolderResponse, status_code=status.HTTP_201_CREATED, tags=["Folders"])
def register_folder(payload: FolderCreate) -> FolderResponse:
    """Registers a new folder for indexing and discovery."""
    try:
        norm_path = normalize_path(payload.path)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    if not os.path.exists(norm_path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Directory not found: {norm_path}")

    if not os.path.isdir(norm_path):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Path is not a directory: {norm_path}")

    with db_manager.session() as conn:
        repo = Repository(conn)
        existing_folders = repo.list_folders()
        for f in existing_folders:
            existing_path = f["path"]
            if paths_overlap(norm_path, existing_path):
                norm_cand = os.path.normcase(norm_path)
                norm_exist = os.path.normcase(existing_path)
                if norm_cand == norm_exist:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=f"Folder is already registered: '{existing_path}'",
                    )
                elif is_path_within_root(norm_path, existing_path):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Cannot register subdirectory '{norm_path}' because parent root '{existing_path}' is already registered.",
                    )
                elif is_path_within_root(existing_path, norm_path):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Cannot register parent directory '{norm_path}' because subdirectory root '{existing_path}' is already registered.",
                    )
                else:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Cannot register folder '{norm_path}' because it overlaps with existing registered root '{existing_path}'.",
                    )

        folder = repo.create_folder(
            path=norm_path,
            recursive=payload.recursive,
            integrity_mode=payload.integrity_mode.value,
            indexing_enabled=payload.indexing_enabled,
            exclude_patterns=payload.exclude_patterns,
        )

    # Trigger discovery scan and sync watcher
    if payload.indexing_enabled:
        coordinator.scan_single_folder(folder["folder_id"])

    return FolderResponse(**folder)


@app.get("/folders/{folder_id}", response_model=FolderResponse, tags=["Folders"])
def get_folder(folder_id: str) -> FolderResponse:
    with db_manager.session() as conn:
        repo = Repository(conn)
        folder = repo.get_folder(folder_id)
        if not folder:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Folder not found")
        return FolderResponse(**folder)


@app.patch("/folders/{folder_id}", response_model=FolderResponse, tags=["Folders"])
def update_folder(folder_id: str, payload: FolderUpdate) -> FolderResponse:
    with db_manager.session() as conn:
        repo = Repository(conn)
        updated = repo.update_folder(
            folder_id=folder_id,
            recursive=payload.recursive,
            integrity_mode=payload.integrity_mode.value if payload.integrity_mode else None,
            indexing_enabled=payload.indexing_enabled,
            exclude_patterns=payload.exclude_patterns,
        )
        if not updated:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Folder not found")

    coordinator.sync_watches()
    return FolderResponse(**updated)


@app.delete("/folders/{folder_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Folders"])
def delete_folder(folder_id: str):
    with db_manager.session() as conn:
        repo = Repository(conn)
        deleted = repo.delete_folder(folder_id)
        if not deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Folder not found")

    coordinator.sync_watches()
    return None


# ---------------------------------------------------------------------------
# Files API
# ---------------------------------------------------------------------------

@app.get("/files", response_model=FileListResponse, tags=["Files"])
def list_files(
    folder_id: Optional[str] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    search: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> FileListResponse:
    """Lists tracked files with optional status filtering, keyword/SHA search, and pagination."""
    with db_manager.session() as conn:
        repo = Repository(conn)
        files = repo.list_files(
            folder_id=folder_id,
            status=status_filter,
            search=search,
            limit=limit,
            offset=offset,
        )
        total = repo.count_files(
            folder_id=folder_id,
            status=status_filter,
            search=search,
        )
        return FileListResponse(
            total=total,
            files=[FileItem(**f) for f in files],
        )


@app.get("/files/{file_id}", response_model=FileItem, tags=["Files"])
def get_file(file_id: str) -> FileItem:
    with db_manager.session() as conn:
        repo = Repository(conn)
        file_rec = repo.get_file_by_id(file_id)
        if not file_rec:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
        return FileItem(**file_rec)


# ---------------------------------------------------------------------------
# Indexing & Control API
# ---------------------------------------------------------------------------

@app.get("/indexing/status", response_model=IndexingStatusResponse, tags=["Indexing"])
def get_indexing_status() -> IndexingStatusResponse:
    """Returns live progressive indexing statistics across all folders."""
    stats = coordinator.get_aggregate_status()
    return IndexingStatusResponse(**stats)


@app.post("/indexing/control", response_model=IndexingControlResponse, tags=["Indexing"])
def control_indexing(payload: IndexingControlRequest) -> IndexingControlResponse:
    """Controls the background indexing engine (Start, Pause, Resume, Stop, Rescan)."""
    action = payload.action

    if action == IndexingControlAction.PAUSE:
        coordinator.pause_indexing()
        msg = "Indexing paused"
    elif action == IndexingControlAction.RESUME:
        coordinator.resume_indexing()
        msg = "Indexing resumed"
    elif action == IndexingControlAction.START:
        coordinator.resume_indexing()
        if payload.folder_id:
            coordinator.scan_single_folder(payload.folder_id)
        else:
            coordinator.scan_all_enabled_folders()
        msg = "Indexing started"
    elif action == IndexingControlAction.RESCAN:
        if payload.folder_id:
            coordinator.scan_single_folder(payload.folder_id, force_strict=True)
            msg = f"Rescanning folder {payload.folder_id}"
        else:
            coordinator.scan_all_enabled_folders()
            msg = "Rescanning all folders"
    elif action == IndexingControlAction.STOP:
        coordinator.pause_indexing()
        msg = "Indexing stopped"
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown action: {action}")

    current_status = coordinator.get_aggregate_status()
    return IndexingControlResponse(
        success=True,
        action=action.value,
        message=msg,
        status=IndexingStatusResponse(**current_status),
    )


# ---------------------------------------------------------------------------
# Events & Jobs API
# ---------------------------------------------------------------------------

@app.get("/events", response_model=EventListResponse, tags=["Events"])
def list_events(folder_id: Optional[str] = None, limit: int = Query(100, ge=1, le=500)) -> EventListResponse:
    """Returns the normalized filesystem event audit trail."""
    with db_manager.session() as conn:
        repo = Repository(conn)
        events = repo.list_events(folder_id=folder_id, limit=limit)
        return EventListResponse(total=len(events), events=[EventItem(**ev) for ev in events])


@app.get("/jobs", response_model=JobListResponse, tags=["Jobs"])
def list_jobs(status_filter: Optional[str] = Query(None, alias="status"), limit: int = Query(50, ge=1, le=200)) -> JobListResponse:
    """Returns active and historical indexing jobs."""
    with db_manager.session() as conn:
        repo = Repository(conn)
        jobs = repo.list_jobs(status=status_filter, limit=limit)
        return JobListResponse(total=len(jobs), jobs=[JobItem(**j) for j in jobs])


# ---------------------------------------------------------------------------
# Filesystem Actions & Legacy Smoke-Test
# ---------------------------------------------------------------------------

@app.post("/fs/action", response_model=ActionResponse, tags=["Filesystem"])
def execute_safe_action(payload: ActionRequest) -> ActionResponse:
    """Execute allowlisted, safe, deterministic desktop filesystem actions.

    Security boundary: the target path MUST resolve inside at least one currently
    registered FileMind folder.  This prevents arbitrary filesystem access even
    when the API is reachable locally.
    """
    from app.core.security import is_path_within_root, is_symlink_or_junction, contains_symlink_or_junction

    try:
        target_path = normalize_path(payload.target_path)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    if not os.path.exists(target_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Target path does not exist: {target_path}",
        )

    # -----------------------------------------------------------------------
    # Registered-folder scope & symlink/junction check
    # -----------------------------------------------------------------------
    with db_manager.session() as _scope_conn:
        _scope_repo = Repository(_scope_conn)
        registered_folders = _scope_repo.list_folders()

    matched_rf_path = None
    for rf in registered_folders:
        rf_path = rf.get("path", "")
        if not rf_path:
            continue
        try:
            if is_path_within_root(target_path, rf_path):
                matched_rf_path = rf_path
                break
        except Exception:
            continue

    if not matched_rf_path:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: target path is outside all registered FileMind folders.",
        )

    if is_symlink_or_junction(target_path) or contains_symlink_or_junction(target_path, matched_rf_path):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: symlinks and junctions are not permitted for filesystem actions.",
        )
    # -----------------------------------------------------------------------

    action = payload.action

    if action == ActionType.OPEN_FILE:
        if not os.path.isfile(target_path):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Target is not a regular file: {target_path}",
            )
        try:
            if sys.platform == "win32":
                os.startfile(target_path)
            else:
                subprocess.Popen(["xdg-open", target_path])
            return ActionResponse(
                success=True,
                action=action.value,
                target_path=target_path,
                message="File opened with default OS application",
            )
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to open file: {str(exc)}",
            )

    elif action == ActionType.OPEN_FOLDER:
        try:
            if sys.platform == "win32":
                if os.path.isfile(target_path):
                    subprocess.Popen(["explorer.exe", f"/select,{target_path}"])
                else:
                    os.startfile(target_path)
            else:
                parent_dir = target_path if os.path.isdir(target_path) else os.path.dirname(target_path)
                subprocess.Popen(["xdg-open", parent_dir])
            return ActionResponse(
                success=True,
                action=action.value,
                target_path=target_path,
                message="Folder opened in OS file explorer",
            )
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to open folder: {str(exc)}",
            )

    elif action == ActionType.COPY_PATH:
        return ActionResponse(
            success=True,
            action=action.value,
            target_path=target_path,
            message="Canonical path validated successfully",
        )

    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported action: {action}",
        )


@app.post("/fs/enumerate", response_model=EnumerateResponse, tags=["Filesystem"])
def enumerate_folder(payload: EnumerateRequest) -> EnumerateResponse:
    """Safe recursive directory scan (Phase 0 legacy endpoint)."""
    try:
        folder_path = normalize_path(payload.folder_path)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    if not os.path.exists(folder_path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Directory does not exist: {folder_path}")

    if not os.path.isdir(folder_path):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Specified path is not a directory: {folder_path}")

    start_time = time.perf_counter()
    file_items: List[FileItem] = []

    try:
        for root, _, files in os.walk(folder_path):
            for file_name in files:
                abs_path = os.path.normpath(os.path.join(root, file_name))
                try:
                    rel_path = os.path.relpath(abs_path, folder_path)
                    st = os.stat(abs_path)
                    from datetime import datetime, timezone
                    mod_iso = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat()
                    _, ext = os.path.splitext(file_name)
                    file_items.append(
                        FileItem(
                            relative_path=rel_path,
                            path=abs_path,
                            filename=file_name,
                            size_bytes=st.st_size,
                            modified_at=mod_iso,
                            extension=ext.lower(),
                        )
                    )
                except (OSError, PermissionError):
                    continue
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    scan_duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
    return EnumerateResponse(
        folder_path=folder_path,
        file_count=len(file_items),
        scan_duration_ms=scan_duration_ms,
        files=file_items,
    )


# ---------------------------------------------------------------------------
# Phase 2: Document Intelligence & Chunks API
# ---------------------------------------------------------------------------

@app.get("/files/{file_id}/chunks", response_model=Dict[str, Any], tags=["Document Intelligence"])
def get_file_chunks(file_id: str) -> Dict[str, Any]:
    """Retrieves all generated chunks and provenance records for a file."""
    with db_manager.session() as conn:
        repo = Repository(conn)
        file_rec = repo.get_file_by_id(file_id)
        if not file_rec:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"File not found: {file_id}")
        chunks = repo.get_chunks_by_file(file_id)
        return {
            "total": len(chunks),
            "file_id": file_id,
            "filename": file_rec["filename"],
            "source_path": file_rec["path"],
            "chunks": chunks,
        }


@app.get("/chunks/{chunk_id}", response_model=Dict[str, Any], tags=["Document Intelligence"])
def get_chunk_by_id(chunk_id: str) -> Dict[str, Any]:
    """Retrieves a single chunk by its deterministic chunk_id."""
    with db_manager.session() as conn:
        repo = Repository(conn)
        chunk = repo.get_chunk_by_id(chunk_id)
        if not chunk:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Chunk not found: {chunk_id}")
        return chunk


@app.get("/intelligence/status", response_model=Dict[str, Any], tags=["Document Intelligence"])
def get_document_intelligence_status() -> Dict[str, Any]:
    """Returns aggregate document intelligence statistics (chunks, parsed files, failures)."""
    with db_manager.session() as conn:
        repo = Repository(conn)
        return repo.get_document_intelligence_stats()


# ---------------------------------------------------------------------------
# Phase 3: Retrieval API
# ---------------------------------------------------------------------------

@app.post("/search", response_model=SearchResponse, tags=["Retrieval"])
def search_evidence(req: SearchRequest) -> SearchResponse:
    """
    Local hybrid evidence retrieval endpoint.
    Supports Fast and Quality search modes across BM25, Dense, and Hybrid retrieval.
    """
    valid_modes = {"hybrid", "bm25", "dense"}
    valid_qualities = {"fast", "quality"}

    mode_lower = (req.mode or "").lower().strip()
    quality_lower = (req.quality or "").lower().strip()

    if mode_lower not in valid_modes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid retrieval mode '{req.mode}'. Valid options are: 'hybrid', 'bm25', 'dense'.",
        )

    if quality_lower not in valid_qualities:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid quality mode '{req.quality}'. Valid options are: 'fast', 'quality'.",
        )

    if quality_lower == "quality" and mode_lower != "hybrid":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Quality mode is only supported with hybrid retrieval (received mode='{req.mode}', quality='{req.quality}').",
        )

    filters = {}
    if req.folder_id:
        filters["folder_id"] = req.folder_id
    if req.extension:
        filters["extension"] = req.extension
    if req.file_id:
        filters["file_id"] = req.file_id

    with db_manager.session() as conn:
        from app.retrieval.hybrid import HybridRetriever
        retriever = HybridRetriever(conn)
        resp = retriever.search(
            query=req.query,
            top_k=req.top_k,
            filters=filters,
            mode=mode_lower,
            quality=quality_lower,
        )
        return SearchResponse(**resp)


@app.get("/retrieval/related/{file_id}", response_model=RelatedFilesResponse, tags=["Retrieval"])
def get_related_files(
    file_id: str,
    limit: int = Query(5, ge=1, le=50, description="Max related files to return"),
    quality: str = Query("fast", description="Search quality: fast or quality"),
) -> RelatedFilesResponse:
    """
    Discovers indexed files related to the specified file using hybrid retrieval.
    Operates at file level with Max Chunk Score aggregation and self-exclusion.
    """
    valid_qualities = {"fast", "quality"}
    quality_lower = (quality or "fast").lower().strip()
    if quality_lower not in valid_qualities:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid quality mode '{quality}'. Valid options are: 'fast', 'quality'.",
        )

    try:
        from app.retrieval.related import RelatedContentService
        svc = RelatedContentService(db_manager=db_manager)
        resp = svc.get_related_files(file_id=file_id, limit=limit, quality=quality_lower)
        return RelatedFilesResponse(**resp)
    except ValueError as exc:
        msg = str(exc)
        if "not found" in msg.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=msg,
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=msg,
        )
    except Exception as exc:
        _app_logger.error("Failed to retrieve related files for %s: %s", file_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while discovering related files.",
        )


# ---------------------------------------------------------------------------
# Phase 5: Ask FileMind API
# ---------------------------------------------------------------------------

@app.post("/ai/ask", response_model=AskResponse, tags=["Ask FileMind"])
def ask_filemind(req: AskRequest) -> AskResponse:
    """
    End-to-end grounded question-answering endpoint for local files.
    Orchestrates hybrid retrieval, context budgeting, grounded prompt assembly,
    local Ollama generation, and citation validation.
    """
    try:
        from app.ai import default_ask_service
        return default_ask_service.ask(req)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except Exception as exc:
        _app_logger.error("Ask FileMind pipeline error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while processing the request.",
        )


# ---------------------------------------------------------------------------
# Phase 5.5: Document Understanding API
# ---------------------------------------------------------------------------

@app.get("/ai/document-insight/{file_id}", response_model=DocumentInsightResponse, tags=["Document Understanding"])
def get_document_insight(file_id: str) -> DocumentInsightResponse:
    """Retrieves cached document insight or returns NOT_GENERATED/STALE."""
    try:
        from app.ai.document_understanding import DocumentUnderstandingService
        svc = DocumentUnderstandingService(db_manager=db_manager)
        res = svc.get_insight(file_id)
        return DocumentInsightResponse(**res)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    except Exception as exc:
        _app_logger.error("Failed to retrieve document insight: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while retrieving document insight.",
        )


@app.post("/ai/document-insight/{file_id}/generate", response_model=DocumentInsightResponse, tags=["Document Understanding"])
def generate_document_insight(file_id: str) -> DocumentInsightResponse:
    """Generates grounded document understanding with local LLM and stores insight atomically."""
    try:
        from app.ai.document_understanding import DocumentUnderstandingService
        svc = DocumentUnderstandingService(db_manager=db_manager)
        res = svc.generate_insight(file_id)
        return DocumentInsightResponse(**res)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )
    except Exception as exc:
        _app_logger.error("Failed to generate document insight: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while generating document insight.",
        )




def start():
    """Main entrypoint for running the backend service."""
    uvicorn.run(
        app,
        host=HOST,
        port=PORT,
        log_level="info",
        access_log=False,
    )


if __name__ == "__main__":
    start()

