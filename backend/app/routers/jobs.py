"""Indexing jobs inspection API routes."""

from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.core.deps import get_repo
from app.db.repository import Repository
from app.schemas import JobItem, JobListResponse

router = APIRouter(tags=["Jobs"])


@router.get("/jobs", response_model=JobListResponse)
def list_jobs(
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    repo: Repository = Depends(get_repo),
) -> JobListResponse:
    """Returns active and historical indexing jobs."""
    jobs = repo.list_jobs(status=status_filter, limit=limit)
    return JobListResponse(total=len(jobs), jobs=[JobItem(**j) for j in jobs])
