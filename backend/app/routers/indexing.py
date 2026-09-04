"""Indexing coordinator control API routes."""

from fastapi import APIRouter, HTTPException, status

from app.engine.coordinator import coordinator
from app.schemas import (
    IndexingControlAction,
    IndexingControlRequest,
    IndexingControlResponse,
    IndexingStatusResponse,
)

router = APIRouter(tags=["Indexing"])


@router.get("/indexing/status", response_model=IndexingStatusResponse)
def get_indexing_status() -> IndexingStatusResponse:
    """Returns live progressive indexing statistics across all folders."""
    stats = coordinator.get_aggregate_status()
    return IndexingStatusResponse(**stats)


@router.post("/indexing/control", response_model=IndexingControlResponse)
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
