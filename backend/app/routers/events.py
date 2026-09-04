"""Filesystem event audit API routes."""

from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.core.deps import get_repo
from app.db.repository import Repository
from app.schemas import EventItem, EventListResponse

router = APIRouter(tags=["Events"])


@router.get("/events", response_model=EventListResponse)
def list_events(
    folder_id: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    repo: Repository = Depends(get_repo),
) -> EventListResponse:
    """Returns the normalized filesystem event audit trail."""
    events = repo.list_events(folder_id=folder_id, limit=limit)
    return EventListResponse(total=len(events), events=[EventItem(**ev) for ev in events])
