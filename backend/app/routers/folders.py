"""Folder management API routes."""

import os
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.context import AppContext
from app.core.deps import get_app_context, get_repo
from app.core.security import is_path_within_root, normalize_path, paths_overlap
from app.db.repository import Repository
from app.schemas import FolderCreate, FolderResponse, FolderUpdate

router = APIRouter(tags=["Folders"])


@router.get("/folders", response_model=List[FolderResponse])
def list_registered_folders(repo: Repository = Depends(get_repo)) -> List[FolderResponse]:
    """Lists all registered folders tracked by FileMind."""
    folders = repo.list_folders()
    return [FolderResponse(**f) for f in folders]


@router.post("/folders", response_model=FolderResponse, status_code=status.HTTP_201_CREATED)
def register_folder(
    payload: FolderCreate,
    repo: Repository = Depends(get_repo),
    ctx: AppContext = Depends(get_app_context),
) -> FolderResponse:
    """Registers a new folder for indexing and discovery."""
    try:
        norm_path = normalize_path(payload.path)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    if not os.path.exists(norm_path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Directory not found: {norm_path}")

    if not os.path.isdir(norm_path):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Path is not a directory: {norm_path}")

    from app.core.config import APP_DATA_DIR
    app_data_str = str(APP_DATA_DIR)
    if is_path_within_root(norm_path, app_data_str) or is_path_within_root(app_data_str, norm_path) or os.path.normcase(norm_path) == os.path.normcase(app_data_str):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot register FileMind's internal application data directory.",
        )

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
    repo.conn.commit()

    # Trigger discovery scan and sync watcher asynchronously in background
    if payload.indexing_enabled:
        import threading
        threading.Thread(
            target=ctx.engine_coordinator.scan_single_folder,
            args=(folder["folder_id"],),
            daemon=True,
        ).start()

    return FolderResponse(**folder)


@router.get("/folders/{folder_id}", response_model=FolderResponse)
def get_folder(folder_id: str, repo: Repository = Depends(get_repo)) -> FolderResponse:
    folder = repo.get_folder(folder_id)
    if not folder:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Folder not found")
    return FolderResponse(**folder)


@router.patch("/folders/{folder_id}", response_model=FolderResponse)
def update_folder(
    folder_id: str,
    payload: FolderUpdate,
    repo: Repository = Depends(get_repo),
    ctx: AppContext = Depends(get_app_context),
) -> FolderResponse:
    updated = repo.update_folder(
        folder_id=folder_id,
        recursive=payload.recursive,
        integrity_mode=payload.integrity_mode.value if payload.integrity_mode else None,
        indexing_enabled=payload.indexing_enabled,
        exclude_patterns=payload.exclude_patterns,
    )
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Folder not found")

    repo.conn.commit()
    ctx.engine_coordinator.sync_watches()
    return FolderResponse(**updated)


@router.delete("/folders/{folder_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_folder(
    folder_id: str,
    repo: Repository = Depends(get_repo),
    ctx: AppContext = Depends(get_app_context),
):
    deleted = repo.delete_folder(folder_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Folder not found")

    repo.conn.commit()
    ctx.engine_coordinator.sync_watches()
    return None
