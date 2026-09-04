"""File and document intelligence query API routes."""

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.deps import get_repo
from app.db.repository import Repository
from app.schemas import FileItem, FileListResponse

router = APIRouter()


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
