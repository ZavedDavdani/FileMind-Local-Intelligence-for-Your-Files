"""FileMind Local Backend Service - Phase 1 Filesystem Engine."""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from app import __version__
from app.core.context import AppContext, default_app_context
from app.core.deps import get_app_context
from app.core.logging_config import setup_logging
from app.db.connection import db_manager
from app.engine.coordinator import coordinator
from app.routers import (
    ai_router,
    events_router,
    files_router,
    folders_router,
    fs_actions_router,
    indexing_router,
    jobs_router,
    search_router,
)
from app.schemas import HealthResponse

PORT = 24823
HOST = "127.0.0.1"

# Initialize persistent rotating application logging as early as possible so
# that all subsequent module-level and lifespan-level log calls (coordinator,
# watcher, worker, retrieval, etc.) are actually captured.
_app_logger = setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager: initializes database migrations, crash recovery, and worker pool."""
    _app_logger.info("FileMind backend starting up (version=%s)", __version__)
    context: AppContext = getattr(app.state, "context", None)
    if context is None:
        context = default_app_context
        app.state.context = context
    context.engine_coordinator.initialize()
    yield
    _app_logger.info("FileMind backend shutting down")
    context.engine_coordinator.shutdown()


app = FastAPI(
    title="FileMind Backend",
    description="FileMind Local-First Desktop Service - Phase 1 Filesystem Engine",
    version=__version__,
    lifespan=lifespan,
)
app.state.context = default_app_context

ALLOWED_ORIGINS = [
    "http://localhost",
    "http://localhost:1420",
    "http://localhost:5173",
    "http://127.0.0.1",
    "http://127.0.0.1:1420",
    "http://127.0.0.1:5173",
    "tauri://localhost",
    "https://tauri.localhost",
    "http://tauri.localhost",
]

# Enable CORS for explicit local webview and dev origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse, tags=["Health"])
def get_health(
    response: Response,
    ctx: AppContext = Depends(get_app_context),
) -> HealthResponse:
    """Meaningful health and readiness check endpoint for Tauri desktop supervisor."""
    db_status = "healthy"
    vec_status = "healthy"
    worker_status = "healthy"
    is_ready = True
    errors = {}

    # 1. Database availability check
    try:
        with ctx.db_manager.session() as conn:
            conn.execute("SELECT 1;").fetchone()
    except Exception as exc:
        db_status = "unhealthy"
        is_ready = False
        errors["database"] = str(exc)

    # 2. Vector store / sqlite-vec check
    if db_status == "healthy":
        try:
            with ctx.db_manager.session() as conn:
                conn.execute("SELECT vec_version();").fetchone()
        except Exception as exc:
            vec_status = "unhealthy"
            is_ready = False
            errors["vector_store"] = str(exc)
    else:
        vec_status = "unhealthy"
        is_ready = False
        errors["vector_store"] = "Database unavailable"

    # 3. Engine coordinator & worker initialization check
    engine_coord = getattr(ctx, "engine_coordinator", None)
    if engine_coord is not None and not getattr(engine_coord, "_is_initialized", False):
        if db_status == "healthy" and vec_status == "healthy":
            try:
                engine_coord.initialize()
            except Exception:
                pass

    if engine_coord is None or not getattr(engine_coord, "_is_initialized", False):
        worker_status = "initializing"
        is_ready = False
        errors["worker"] = "Filesystem engine not initialized"
    elif not getattr(engine_coord.worker_pool, "is_running", False):
        worker_status = "unhealthy"
        is_ready = False
        errors["worker"] = "Worker pool is stopped"

    if not is_ready:
        if db_status == "unhealthy" or vec_status == "unhealthy" or worker_status == "unhealthy":
            overall_status = "unhealthy"
        else:
            overall_status = "initializing"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    else:
        overall_status = "healthy"
        response.status_code = status.HTTP_200_OK

    return HealthResponse(
        status=overall_status,
        service="FileMind Backend",
        version=__version__,
        port=PORT,
        ready=is_ready,
        database=db_status,
        vector_store=vec_status,
        worker=worker_status,
        details=errors if errors else None,
    )


@app.get("/health/liveness", tags=["Health"])
def get_liveness():
    """Simple process liveness check verifying the HTTP server is responsive."""
    return {"status": "alive", "service": "FileMind Backend", "version": __version__}


# Include modular domain routers
app.include_router(folders_router)
app.include_router(files_router)
app.include_router(indexing_router)
app.include_router(events_router)
app.include_router(jobs_router)
app.include_router(fs_actions_router)
app.include_router(search_router)
app.include_router(ai_router)


def start():
    """Main entrypoint for running the backend service."""
    uvicorn.run(
        app,
        host=HOST,
        port=PORT,
        log_level="info",
        access_log=False,
    )


if __name__ == "__main__":
    start()
