"""Request-scoped and application-scoped FastAPI dependency providers for FileMind."""

from __future__ import annotations

import sys
from typing import Callable, Iterator, Optional

from fastapi import Depends, Request

from app.core.context import AppContext, default_app_context
from app.db.connection import DatabaseManager, db_manager
from app.db.repository import Repository


def get_app_context(request: Request = None) -> AppContext:
    """Provides the active application context from request.app.state, app.main, or default."""
    if request is not None and hasattr(request, "app") and hasattr(request.app.state, "context"):
        return request.app.state.context
    main_mod = sys.modules.get("app.main")
    if main_mod and hasattr(main_mod, "app") and hasattr(main_mod.app.state, "context"):
        return main_mod.app.state.context
    return default_app_context


def get_db(ctx: AppContext = Depends(get_app_context)) -> DatabaseManager:
    """Returns active DatabaseManager from the application context."""
    if not isinstance(ctx, AppContext):
        ctx = get_app_context()
    return ctx.db_manager


def make_repo_dependency(manager: DatabaseManager) -> Callable[[], Iterator[Repository]]:
    """Factory creating a request-scoped Repository dependency."""

    def _get_repo() -> Iterator[Repository]:
        with manager.session() as conn:
            yield Repository(conn)

    return _get_repo


def get_repo(db: DatabaseManager = Depends(get_db)) -> Iterator[Repository]:
    """Default request-scoped repository dependency provider."""
    if not isinstance(db, DatabaseManager):
        db = get_db()
    with db.session() as conn:
        yield Repository(conn)
