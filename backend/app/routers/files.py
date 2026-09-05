"""File and document intelligence query API routes."""

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.context import AppContext
from app.core.deps import get_app_context, get_repo
from app.db.repository import Repository
from app.schemas import (
    FileItem,
    FileListResponse,
    RegisteredFileResult,
    RegisterFilesRequest,
    RegisterFilesResponse,
)

router = APIRouter()


@router.post("/files/register", response_model=RegisterFilesResponse, status_code=status.HTTP_200_OK, tags=["Files"])
def register_individual_files(
    payload: RegisterFilesRequest,
    repo: Repository = Depends(get_repo),
    ctx: AppContext = Depends(get_app_context),
) -> RegisterFilesResponse:
    """
    Registers and queues individual files for indexing without recursively
    indexing their parent directories.
    """
    import os
    from datetime import datetime, timezone
    from app.core.config import APP_DATA_DIR, MAX_FILE_SIZE_BYTES
    from app.core.security import normalize_path, is_path_within_root, is_symlink_or_junction
    from app.intelligence.detector import detect_file_format, is_supported_document

    results = []
    total_enqueued = 0
    total_skipped = 0

    existing_folders = repo.list_folders()

    for raw_path in payload.paths:
        if not raw_path or not raw_path.strip():
            continue
        try:
            norm_path = normalize_path(raw_path.strip())
        except Exception as exc:
            results.append(RegisteredFileResult(path=raw_path, status="SKIPPED", error=f"Invalid path: {exc}"))
            total_skipped += 1
            continue

        if not os.path.exists(norm_path) or not os.path.isfile(norm_path):
            results.append(RegisteredFileResult(path=norm_path, status="SKIPPED", error="File does not exist or is not a regular file"))
            total_skipped += 1
            continue

        if is_symlink_or_junction(norm_path):
            results.append(RegisteredFileResult(path=norm_path, status="SKIPPED", error="Symlinks and junctions are excluded for safety"))
            total_skipped += 1
            continue

        app_data_str = str(APP_DATA_DIR)
        if is_path_within_root(norm_path, app_data_str) or os.path.normcase(norm_path) == os.path.normcase(app_data_str):
            results.append(RegisteredFileResult(path=norm_path, status="SKIPPED", error="Cannot index internal FileMind data files"))
            total_skipped += 1
            continue

        size = os.path.getsize(norm_path)
        if size > MAX_FILE_SIZE_BYTES:
            results.append(RegisteredFileResult(path=norm_path, status="SKIPPED", error=f"File exceeds maximum allowed size ({MAX_FILE_SIZE_BYTES // (1024*1024)} MB)"))
            total_skipped += 1
            continue

        if not is_supported_document(norm_path):
            results.append(RegisteredFileResult(path=norm_path, status="SKIPPED", error="Unsupported file format"))
            total_skipped += 1
            continue

        # Find matching parent folder or register parent folder as non-recursive container
        parent_dir = normalize_path(os.path.dirname(norm_path))
        target_folder = None
        for f in existing_folders:
            if is_path_within_root(norm_path, f["path"]):
                target_folder = f
                break

        if not target_folder:
            target_folder = repo.create_folder(
                path=parent_dir,
                recursive=False,
                integrity_mode="NORMAL",
                indexing_enabled=True,
                exclude_patterns=["*"],
            )
            existing_folders.append(target_folder)

        folder_id = target_folder["folder_id"]
        filename = os.path.basename(norm_path)
        ext = os.path.splitext(norm_path)[1].lower()
        rel_path = os.path.relpath(norm_path, target_folder["path"])
        mime_type, _ = detect_file_format(norm_path)
        mtime = datetime.fromtimestamp(os.path.getmtime(norm_path), tz=timezone.utc).isoformat()

        file_rec = repo.upsert_file(
            folder_id=folder_id,
            path=norm_path,
            relative_path=rel_path,
            filename=filename,
            extension=ext,
            size_bytes=size,
            modified_at=mtime,
            mime_type=mime_type,
        )

        repo.enqueue_job(
            file_id=file_rec["file_id"],
            folder_id=folder_id,
            job_type="METADATA_DISCOVERY",
            priority=5,
        )
        repo.update_file_status(file_rec["file_id"], "QUEUED")
        total_enqueued += 1
        results.append(RegisteredFileResult(
            path=norm_path,
            status="QUEUED",
            file_id=file_rec["file_id"],
            filename=filename,
        ))

    repo.conn.commit()
    if total_enqueued > 0:
        ctx.engine_coordinator.worker_pool.notify_job_available()

    return RegisterFilesResponse(
        total_requested=len(payload.paths),
        total_enqueued=total_enqueued,
        total_skipped=total_skipped,
        results=results,
    )


@router.get("/files", response_model=FileListResponse, tags=["Files"])
def list_files(
    folder_id: Optional[str] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    search: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    repo: Repository = Depends(get_repo),
) -> FileListResponse:
    """Lists tracked files with optional status filtering, keyword/SHA search, and pagination."""
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


@router.get("/files/{file_id}", response_model=FileItem, tags=["Files"])
def get_file(file_id: str, repo: Repository = Depends(get_repo)) -> FileItem:
    file_rec = repo.get_file_by_id(file_id)
    if not file_rec:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    return FileItem(**file_rec)


@router.get("/files/{file_id}/chunks", response_model=Dict[str, Any], tags=["Document Intelligence"])
def get_file_chunks(file_id: str, repo: Repository = Depends(get_repo)) -> Dict[str, Any]:
    """Retrieves all generated chunks and provenance records for a file."""
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


@router.get("/chunks/{chunk_id}", response_model=Dict[str, Any], tags=["Document Intelligence"])
def get_chunk_by_id(chunk_id: str, repo: Repository = Depends(get_repo)) -> Dict[str, Any]:
    """Retrieves a single chunk by its deterministic chunk_id."""
    chunk = repo.get_chunk_by_id(chunk_id)
    if not chunk:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Chunk not found: {chunk_id}")
    return chunk


@router.get("/intelligence/status", response_model=Dict[str, Any], tags=["Document Intelligence"])
def get_document_intelligence_status(repo: Repository = Depends(get_repo)) -> Dict[str, Any]:
    """Returns aggregate document intelligence statistics (chunks, parsed files, failures)."""
    return repo.get_document_intelligence_stats()
