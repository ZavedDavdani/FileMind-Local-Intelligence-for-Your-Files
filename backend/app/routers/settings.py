"""
Settings, Storage Stats & Diagnostics Router for FileMind .
"""

import os
import sys
import time
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, Depends

from app import __version__
from app.ai.ollama_provider import default_ollama_provider
from app.core.config import get_app_data_dir
from app.core.context import AppContext
from app.core.deps import get_app_context
from app.db.repository import Repository
from app.schemas import DiagnosticsResponse, StorageStatsResponse

router = APIRouter(prefix="/api/settings", tags=["Settings"])

_START_TIME = time.time()


@router.get("/storage", response_model=StorageStatsResponse)
def get_storage_stats(
    ctx: AppContext = Depends(get_app_context),
) -> StorageStatsResponse:
    """Returns persistent knowledge storage statistics."""
    app_data = get_app_data_dir()
    db_path = app_data / "filemind.db"
    wal_path = app_data / "filemind.db-wal"

    db_size = db_path.stat().st_size if db_path.exists() else 0
    wal_size = wal_path.stat().st_size if wal_path.exists() else 0

    with ctx.db_manager.session() as conn:
        total_files = conn.execute("SELECT COUNT(*) FROM files WHERE index_status = 'INDEXED';").fetchone()[0]
        total_chunks = conn.execute("SELECT COUNT(*) FROM chunks;").fetchone()[0]
        doc_insights = conn.execute("SELECT COUNT(*) FROM document_insights;").fetchone()[0]
        folder_insights = conn.execute("SELECT COUNT(*) FROM folder_insights;").fetchone()[0]
        conversations = conn.execute("SELECT COUNT(*) FROM conversations;").fetchone()[0]

    return StorageStatsResponse(
        app_data_path=str(app_data),
        db_size_bytes=db_size,
        total_files_indexed=total_files,
        total_chunks=total_chunks,
        wal_size_bytes=wal_size,
        document_insights_count=doc_insights,
        folder_insights_count=folder_insights,
        conversations_count=conversations,
    )


@router.get("/diagnostics", response_model=DiagnosticsResponse)
def get_diagnostics(
    ctx: AppContext = Depends(get_app_context),
) -> DiagnosticsResponse:
    """Returns comprehensive diagnostic status for all internal subsystems."""
    db_status = "healthy"
    vec_status = "healthy"
    worker_status = "healthy"
    watcher_status = "active"

    try:
        with ctx.db_manager.session() as conn:
            conn.execute("SELECT 1;").fetchone()
    except Exception:
        db_status = "unhealthy"

    try:
        with ctx.db_manager.session() as conn:
            conn.execute("SELECT vec_version();").fetchone()
    except Exception:
        vec_status = "unhealthy"

    engine_coord = getattr(ctx, "engine_coordinator", None)
    if engine_coord and getattr(engine_coord.worker_pool, "is_running", False):
        worker_status = "running"
    else:
        worker_status = "idle"

    return DiagnosticsResponse(
        version=__version__,
        platform=sys.platform,
        database_status=db_status,
        vector_store_status=vec_status,
        worker_pool_status=worker_status,
        watcher_status=watcher_status,
        ollama_status="configured (" + default_ollama_provider.model + ")",
        uptime_seconds=round(time.time() - _START_TIME, 2),
    )
