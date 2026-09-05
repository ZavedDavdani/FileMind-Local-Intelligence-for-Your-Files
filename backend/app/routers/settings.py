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
    active_workers = 0
    watcher_status = "stopped"
    schema_ver = 10
    sqlite_ver = "3.x"
    vec_ver = "Loaded"
    total_folders = 0
    indexed_files = 0
    error_count = 0
    recent_errors: List[str] = []

    try:
        import sqlite3
        sqlite_ver = sqlite3.sqlite_version
        with ctx.db_manager.session() as conn:
            conn.execute("SELECT 1;").fetchone()
            try:
                row = conn.execute("PRAGMA user_version;").fetchone()
                if row:
                    schema_ver = int(row[0])
            except Exception:
                pass
            try:
                f_count = conn.execute("SELECT COUNT(*) FROM folders WHERE indexing_enabled = 1;").fetchone()
                if f_count:
                    total_folders = int(f_count[0])
                idx_count = conn.execute("SELECT COUNT(*) FROM files WHERE index_status = 'INDEXED';").fetchone()
                if idx_count:
                    indexed_files = int(idx_count[0])
                err_count = conn.execute("SELECT COUNT(*) FROM files WHERE index_status = 'ERROR';").fetchone()
                if err_count:
                    error_count = int(err_count[0])
                err_rows = conn.execute(
                    "SELECT path, last_error FROM files WHERE index_status = 'ERROR' AND last_error IS NOT NULL ORDER BY updated_at DESC LIMIT 5;"
                ).fetchall()
                recent_errors = [f"{os.path.basename(r[0])}: {r[1]}" for r in err_rows]
            except Exception:
                pass
    except Exception:
        db_status = "unhealthy"

    try:
        with ctx.db_manager.session() as conn:
            res = conn.execute("SELECT vec_version();").fetchone()
            if res:
                vec_ver = f"v{res[0]}"
    except Exception:
        vec_status = "unhealthy"
        vec_ver = "Unavailable"

    engine_coord = getattr(ctx, "engine_coordinator", None)
    if engine_coord:
        wp = getattr(engine_coord, "worker_pool", None)
        if wp and getattr(wp, "is_running", False):
            worker_status = "running"
            active_workers = getattr(wp, "worker_count", 2)
        else:
            worker_status = "idle"
            active_workers = 0

        ws = getattr(engine_coord, "watcher_service", None)
        if ws and hasattr(ws, "status"):
            watcher_status = ws.status
        elif ws and getattr(ws, "observer", None) and ws.observer.is_alive():
            watcher_status = "active"
        else:
            watcher_status = "stopped"
    else:
        worker_status = "idle"
        watcher_status = "stopped"

    return DiagnosticsResponse(
        app_version=__version__,
        version=__version__,
        system_os=sys.platform,
        platform=sys.platform,
        schema_version=schema_ver,
        database_status=db_status,
        sqlite_version=sqlite_ver,
        vec_version=vec_ver,
        vector_store_status=vec_status,
        worker_pool_status=worker_status,
        active_workers=active_workers,
        watcher_status=watcher_status,
        total_folders_watched=total_folders,
        indexed_file_count=indexed_files,
        error_count=error_count,
        recent_errors=recent_errors,
        ollama_status="configured (" + default_ollama_provider.model + ")",
        uptime_seconds=round(time.time() - _START_TIME, 2),
    )
