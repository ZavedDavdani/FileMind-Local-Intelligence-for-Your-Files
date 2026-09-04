"""Filesystem safe action and directory scan API routes."""

from datetime import datetime, timezone
import os
import subprocess
import sys
import time
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.deps import get_repo
from app.core.security import (
    normalize_path,
    resolve_and_authorize,
    SecurityForbiddenError,
    SecurityNotFoundError,
)
from app.db.repository import Repository
from app.schemas import (
    ActionRequest,
    ActionResponse,
    ActionType,
    EnumerateRequest,
    EnumerateResponse,
    FileItem,
)

router = APIRouter(tags=["Filesystem"])


@router.post("/fs/action", response_model=ActionResponse)
def execute_safe_action(payload: ActionRequest, repo: Repository = Depends(get_repo)) -> ActionResponse:
    """Execute allowlisted, safe, deterministic desktop filesystem actions.

    Security boundary: the target path MUST resolve inside at least one currently
    registered FileMind folder. This prevents arbitrary filesystem access even
    when the API is reachable locally.
    """
    registered_folders = repo.list_folders()

    try:
        target_path, _ = resolve_and_authorize(payload.target_path, registered_folders)
    except SecurityNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    except SecurityForbiddenError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

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
                subprocess.Popen(["xdg-open", target_path], close_fds=True)
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
                    subprocess.Popen(["explorer.exe", f'/select,"{target_path}"'])
                else:
                    os.startfile(target_path)
            else:
                parent_dir = target_path if os.path.isdir(target_path) else os.path.dirname(target_path)
                subprocess.Popen(["xdg-open", parent_dir], close_fds=True)
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


@router.post("/fs/enumerate", response_model=EnumerateResponse)
def enumerate_folder(payload: EnumerateRequest) -> EnumerateResponse:
    """Safe recursive directory scan (Phase 0 legacy endpoint) with bounded enumeration limit."""
    try:
        folder_path = normalize_path(payload.folder_path)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    if not os.path.exists(folder_path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Directory does not exist: {folder_path}")

    if not os.path.isdir(folder_path):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Specified path is not a directory: {folder_path}")

    MAX_ENUMERATE_LIMIT = 10000
    start_time = time.perf_counter()
    file_items: List[FileItem] = []

    try:
        for root, _, files in os.walk(folder_path):
            if len(file_items) >= MAX_ENUMERATE_LIMIT:
                break
            for file_name in files:
                if len(file_items) >= MAX_ENUMERATE_LIMIT:
                    break
                abs_path = os.path.normpath(os.path.join(root, file_name))
                try:
                    rel_path = os.path.relpath(abs_path, folder_path)
                    st = os.stat(abs_path)
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
