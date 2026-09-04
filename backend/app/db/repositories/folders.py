"""Folder repository domain operations."""

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_exclude_patterns(patterns: Any) -> str:
    """Normalizes exclude_patterns into a single canonical JSON-encoded list string."""
    if patterns is None:
        return "[]"
    if isinstance(patterns, str):
        p_str = patterns.strip()
        if not p_str:
            return "[]"
        try:
            parsed = json.loads(p_str)
            if isinstance(parsed, list):
                return json.dumps([str(x) for x in parsed if x is not None])
            elif isinstance(parsed, str):
                try:
                    inner = json.loads(parsed)
                    if isinstance(inner, list):
                        return json.dumps([str(x) for x in inner if x is not None])
                except Exception:
                    pass
                return json.dumps([parsed])
        except Exception:
            if "," in p_str:
                return json.dumps([x.strip() for x in p_str.split(",") if x.strip()])
            return json.dumps([p_str])
    if isinstance(patterns, (list, tuple, set)):
        return json.dumps([str(x) for x in patterns if x is not None])
    return "[]"


class FolderRepository:
    """Provides strongly typed CRUD queries for tracked folders."""

    normalize_exclude_patterns = staticmethod(normalize_exclude_patterns)

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def create_folder(
        self,
        path: str,
        recursive: bool = True,
        integrity_mode: str = "NORMAL",
        indexing_enabled: bool = True,
        exclude_patterns: Optional[Union[List[str], str]] = None,
        folder_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        fid = folder_id or str(uuid.uuid4())
        now = _utcnow_iso()
        patterns_json = normalize_exclude_patterns(exclude_patterns)

        query = """
        INSERT INTO folders (folder_id, path, recursive, integrity_mode, indexing_enabled, exclude_patterns, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        RETURNING *;
        """
        cursor = self.conn.execute(
            query,
            (fid, path, 1 if recursive else 0, integrity_mode.upper(), 1 if indexing_enabled else 0, patterns_json, now, now),
        )
        row = cursor.fetchone()
        return self._folder_row_to_dict(row)

    def get_folder(self, folder_id: str) -> Optional[Dict[str, Any]]:
        cursor = self.conn.execute("SELECT * FROM folders WHERE folder_id = ?;", (folder_id,))
        row = cursor.fetchone()
        return self._folder_row_to_dict(row) if row else None

    def get_folder_by_path(self, path: str) -> Optional[Dict[str, Any]]:
        alt1 = path.replace('/', '\\')
        alt2 = path.replace('\\', '/')
        if os.name == "nt":
            cursor = self.conn.execute(
                "SELECT * FROM folders WHERE path COLLATE NOCASE IN (?, ?, ?);",
                (path, alt1, alt2),
            )
        else:
            cursor = self.conn.execute("SELECT * FROM folders WHERE path IN (?, ?, ?);", (path, alt1, alt2))
        row = cursor.fetchone()
        return self._folder_row_to_dict(row) if row else None

    def list_folders(self) -> List[Dict[str, Any]]:
        cursor = self.conn.execute("SELECT * FROM folders ORDER BY created_at ASC;")
        return [self._folder_row_to_dict(row) for row in cursor.fetchall()]

    def update_folder(
        self,
        folder_id: str,
        recursive: Optional[bool] = None,
        integrity_mode: Optional[str] = None,
        indexing_enabled: Optional[bool] = None,
        exclude_patterns: Optional[Union[List[str], str]] = None,
    ) -> Optional[Dict[str, Any]]:
        existing = self.get_folder(folder_id)
        if not existing:
            return None

        now = _utcnow_iso()
        new_rec = 1 if (recursive if recursive is not None else existing["recursive"]) else 0
        new_mode = (integrity_mode or existing["integrity_mode"]).upper()
        new_enabled = 1 if (indexing_enabled if indexing_enabled is not None else existing["indexing_enabled"]) else 0
        raw_patterns = exclude_patterns if exclude_patterns is not None else existing["exclude_patterns"]
        new_patterns = normalize_exclude_patterns(raw_patterns)

        self.conn.execute(
            """
            UPDATE folders
            SET recursive = ?, integrity_mode = ?, indexing_enabled = ?, exclude_patterns = ?, updated_at = ?
            WHERE folder_id = ?;
            """,
            (new_rec, new_mode, new_enabled, new_patterns, now, folder_id),
        )
        return self.get_folder(folder_id)

    def delete_folder(self, folder_id: str) -> bool:
        # Clean up chunk_vectors virtual table entries for all chunks belonging to files in this folder
        cursor = self.conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='chunk_vectors';")
        if cursor.fetchone() is not None:
            self.conn.execute(
                """
                DELETE FROM chunk_vectors
                WHERE chunk_id IN (
                    SELECT c.chunk_id
                    FROM chunks c
                    JOIN files f ON c.file_id = f.file_id
                    WHERE f.folder_id = ?
                );
                """,
                (folder_id,),
            )

        cursor = self.conn.execute("DELETE FROM folders WHERE folder_id = ?;", (folder_id,))
        return cursor.rowcount > 0

    def _folder_row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        d = dict(row)
        d["recursive"] = bool(d["recursive"])
        d["indexing_enabled"] = bool(d["indexing_enabled"])
        try:
            val = json.loads(d["exclude_patterns"])
            if isinstance(val, str):
                try:
                    val = json.loads(val)
                except Exception:
                    val = [val]
            d["exclude_patterns"] = val if isinstance(val, list) else []
        except Exception:
            d["exclude_patterns"] = []
        return d
