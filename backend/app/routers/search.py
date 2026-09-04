"""Search and related files retrieval API routes."""

import logging
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.deps import get_db
from app.db.connection import DatabaseManager
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.related import RelatedContentService
from app.schemas import RelatedFilesResponse, SearchRequest, SearchResponse

logger = logging.getLogger("filemind.retrieval")
router = APIRouter(tags=["Retrieval"])


@router.post("/search", response_model=SearchResponse)
def search_evidence(req: SearchRequest, db: DatabaseManager = Depends(get_db)) -> SearchResponse:
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

    with db.session() as conn:
        retriever = HybridRetriever(conn)
        resp = retriever.search(
            query=req.query,
            top_k=req.top_k,
            filters=filters,
            mode=mode_lower,
            quality=quality_lower,
        )
        return SearchResponse(**resp)


@router.get("/retrieval/related/{file_id}", response_model=RelatedFilesResponse)
def get_related_files(
    file_id: str,
    limit: int = Query(5, ge=1, le=50, description="Max related files to return"),
    quality: str = Query("fast", description="Search quality: fast or quality"),
    db: DatabaseManager = Depends(get_db),
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
        svc = RelatedContentService(db_manager=db)
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
        logger.error("Failed to retrieve related files for %s: %s", file_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while discovering related files.",
        )
