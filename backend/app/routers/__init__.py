"""FastAPI modular route definitions for FileMind."""

from app.routers.ai import router as ai_router
from app.routers.chat import router as chat_router
from app.routers.events import router as events_router
from app.routers.export import router as export_router
from app.routers.files import router as files_router
from app.routers.folders import router as folders_router
from app.routers.fs_actions import router as fs_actions_router
from app.routers.indexing import router as indexing_router
from app.routers.jobs import router as jobs_router
from app.routers.knowledge import router as knowledge_router
from app.routers.models import router as models_router
from app.routers.search import router as search_router
from app.routers.settings import router as settings_router

__all__ = [
    "ai_router",
    "chat_router",
    "events_router",
    "export_router",
    "files_router",
    "folders_router",
    "fs_actions_router",
    "indexing_router",
    "jobs_router",
    "knowledge_router",
    "models_router",
    "search_router",
    "settings_router",
]
