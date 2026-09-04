"""Request-scoped FastAPI dependency providers for FileMind."""

from __future__ import annotations

import sys
from typing import Callable, Iterator

from fastapi import Depends

from app.db.connection import DatabaseManager, db_manager
from app.db.repository import Repository


def get_db() -> DatabaseManager:
    """Returns active DatabaseManager from app.main or global default."""
    main_mod = sys.modules.get("app.main")
    if main_mod and hasattr(main_mod, "db_manager"):
        return main_mod.db_manager
    return db_manager


def make_repo_dependency(manager: DatabaseManager) -> Callable[[], Iterator[Repository]]:
    """Factory creating a request-scoped Repository dependency."""

    def _get_repo() -> Iterator[Repository]:
        with manager.session() as conn:
            yield Repository(conn)

    return _get_repo


def get_repo(db: DatabaseManager = Depends(get_db)) -> Iterator[Repository]:
    """Default request-scoped repository dependency provider."""
    with db.session() as conn:
        yield Repository(conn)
