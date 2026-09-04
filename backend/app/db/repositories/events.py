"""Filesystem event audit log repository domain operations."""

import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class EventRepository:
    """Provides strongly typed CRUD queries for filesystem event audit trail."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def log_event(
        self,
        folder_id: str,
        event_type: str,
        path: str,
        old_path: Optional[str] = None,
        file_id: Optional[str] = None,
        status: str = "PENDING",
        event_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        eid = event_id or str(uuid.uuid4())
        now = _utcnow_iso()

        query = """
        INSERT INTO file_events (event_id, folder_id, file_id, event_type, path, old_path, observed_at, processing_status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        RETURNING *;
        """
        cursor = self.conn.execute(
            query, (eid, folder_id, file_id, event_type.upper(), path, old_path, now, status)
        )
        row = cursor.fetchone()
        return dict(row)

    def mark_event_processed(self, event_id: str, status: str = "PROCESSED") -> bool:
        now = _utcnow_iso()
        cursor = self.conn.execute(
            "UPDATE file_events SET processing_status = ?, processed_at = ? WHERE event_id = ?;",
            (status, now, event_id),
        )
        return cursor.rowcount > 0

    def list_events(self, folder_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        query = "SELECT * FROM file_events"
        params = []
        if folder_id:
            query += " WHERE folder_id = ?"
            params.append(folder_id)
        query += " ORDER BY observed_at DESC LIMIT ?;"
        params.append(limit)

        cursor = self.conn.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]
