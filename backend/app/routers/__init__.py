"""FastAPI modular route definitions for FileMind."""

from app.routers.ai import router as ai_router
from app.routers.events import router as events_router
from app.routers.files import router as files_router
from app.routers.folders import router as folders_router
from app.routers.fs_actions import router as fs_actions_router
from app.routers.indexing import router as indexing_router
from app.routers.jobs import router as jobs_router
from app.routers.search import router as search_router

__all__ = [
    "ai_router",
    "events_router",
    "files_router",
    "folders_router",
    "fs_actions_router",
    "indexing_router",
    "jobs_router",
    "search_router",
]
