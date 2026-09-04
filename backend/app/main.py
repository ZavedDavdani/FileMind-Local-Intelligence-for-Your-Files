"""FileMind Local Backend Service - Phase 1 Filesystem Engine."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from app import __version__
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
    coordinator.initialize()
    yield
    _app_logger.info("FileMind backend shutting down")
    coordinator.shutdown()


app = FastAPI(
    title="FileMind Backend",
    description="FileMind Local-First Desktop Service - Phase 1 Filesystem Engine",
    version=__version__,
    lifespan=lifespan,
)

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
def get_health() -> HealthResponse:
    """Deterministic health check endpoint for Tauri desktop supervisor."""
    return HealthResponse(
        status="healthy",
        service="FileMind Backend",
        version=__version__,
        port=PORT,
    )


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
