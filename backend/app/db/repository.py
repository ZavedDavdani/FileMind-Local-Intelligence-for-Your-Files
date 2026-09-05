"""SQLite Repository layer for folders, files, jobs, chunks, and event audit trail.

This module provides the unified authoritative Repository façade composing the
domain-specific repositories:
  - FolderRepository
  - FileRepository
  - JobRepository
  - EventRepository
  - ChunkRepository
  - InsightRepository
"""

import sqlite3

from app.db.repositories.chat import ChatRepository
from app.db.repositories.chunks import ChunkRepository
from app.db.repositories.events import EventRepository
from app.db.repositories.files import FileRepository, escape_like_wildcards
from app.db.repositories.folders import FolderRepository
from app.db.repositories.insights import InsightRepository
from app.db.repositories.jobs import JobRepository

__all__ = [
    "ChatRepository",
    "ChunkRepository",
    "EventRepository",
    "FileRepository",
    "FolderRepository",
    "InsightRepository",
    "JobRepository",
    "Repository",
    "escape_like_wildcards",
]


class Repository(
    FolderRepository,
    FileRepository,
    JobRepository,
    EventRepository,
    ChunkRepository,
    InsightRepository,
    ChatRepository,
):
    """Provides strongly typed CRUD queries for the local FileMind database."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
