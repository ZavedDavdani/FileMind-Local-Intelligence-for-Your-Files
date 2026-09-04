"""File repository domain operations."""

import os
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.core.security import normalize_path


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def escape_like_wildcards(pattern: str, escape_char: str = "\\") -> str:
    """Escapes SQL LIKE wildcards (%, _, and escape_char itself)."""
    return (
        pattern.replace(escape_char, escape_char + escape_char)
        .replace("%", escape_char + "%")
        .replace("_", escape_char + "_")
    )


class FileRepository:
    """Provides strongly typed CRUD queries for tracked files."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def upsert_file(
        self,
        folder_id: str,
        path: str,
        relative_path: str,
        filename: str,
        extension: str,
        size_bytes: int,
        modified_at: str,
        created_at: Optional[str] = None,
        sha256: Optional[str] = None,
        mime_type: Optional[str] = None,
        index_status: str = "DISCOVERED",
        indexing_error: Optional[str] = None,
        file_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        fid = file_id or str(uuid.uuid4())
        now = _utcnow_iso()
        clean_path = path

        query = """
        INSERT INTO files (
            file_id, folder_id, path, relative_path, filename, extension,
            mime_type, size_bytes, modified_at, created_at, last_seen_at,
            sha256, index_status, indexing_error, indexed_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(path) DO UPDATE SET
            folder_id = excluded.folder_id,
            relative_path = excluded.relative_path,
            filename = excluded.filename,
            extension = excluded.extension,
            mime_type = COALESCE(excluded.mime_type, files.mime_type),
            size_bytes = excluded.size_bytes,
            modified_at = excluded.modified_at,
            last_seen_at = excluded.last_seen_at,
            sha256 = COALESCE(excluded.sha256, files.sha256),
            index_status = CASE
                WHEN excluded.index_status IN ('INDEXED', 'FAILED', 'SKIPPED') THEN excluded.index_status
                WHEN excluded.modified_at != files.modified_at OR excluded.size_bytes != files.size_bytes THEN excluded.index_status
                WHEN files.index_status = 'MISSING' THEN excluded.index_status
                WHEN files.index_status IN ('PROCESSING', 'INDEXED', 'FAILED', 'SKIPPED') THEN files.index_status
                ELSE excluded.index_status
            END,
            indexing_error = CASE
                WHEN excluded.index_status IN ('INDEXED', 'FAILED', 'SKIPPED') THEN excluded.indexing_error
                WHEN excluded.modified_at != files.modified_at OR excluded.size_bytes != files.size_bytes THEN excluded.indexing_error
                WHEN files.index_status IN ('PROCESSING', 'INDEXED', 'FAILED', 'SKIPPED') THEN files.indexing_error
                ELSE excluded.indexing_error
            END,
            indexed_at = CASE WHEN excluded.index_status = 'INDEXED' THEN excluded.last_seen_at ELSE files.indexed_at END
        RETURNING *;
        """
        indexed_at = now if index_status == "INDEXED" else None
        cursor = self.conn.execute(
            query,
            (
                fid,
                folder_id,
                clean_path,
                relative_path,
                filename,
                extension,
                mime_type,
                size_bytes,
                modified_at,
                created_at,
                now,
                sha256,
                index_status,
                indexing_error,
                indexed_at,
            ),
        )
        row = cursor.fetchone()
        return dict(row)

    def get_file_by_path(self, path: str) -> Optional[Dict[str, Any]]:
        alt1 = path.replace('/', '\\')
        alt2 = path.replace('\\', '/')
        if os.name == "nt":
            cursor = self.conn.execute(
                "SELECT * FROM files WHERE path COLLATE NOCASE IN (?, ?, ?);",
                (path, alt1, alt2),
            )
        else:
            cursor = self.conn.execute("SELECT * FROM files WHERE path IN (?, ?, ?);", (path, alt1, alt2))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_file_by_id(self, file_id: str) -> Optional[Dict[str, Any]]:
        cursor = self.conn.execute("SELECT * FROM files WHERE file_id = ?;", (file_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_files_by_ids(self, file_ids: List[str], chunk_size: int = 500) -> Dict[str, Dict[str, Any]]:
        """Retrieves files mapped by file_id for a list of file_ids with parameter batching."""
        if not file_ids:
            return {}
        unique_file_ids = list(dict.fromkeys(file_ids))
        out: Dict[str, Dict[str, Any]] = {}
        for i in range(0, len(unique_file_ids), chunk_size):
            batch = unique_file_ids[i : i + chunk_size]
            placeholders = ",".join("?" * len(batch))
            cursor = self.conn.execute(
                f"SELECT * FROM files WHERE file_id IN ({placeholders});",
                batch,
            )
            for row in cursor.fetchall():
                d = dict(row)
                out[d["file_id"]] = d
        return out

    def purge_file_index(self, file_id: str) -> int:
        """
        Authoritatively purges all vector embeddings and relational chunks for a file.
        Strict invariant: chunk_vectors virtual table first, relational chunks table second.
        """
        from app.retrieval.vector_store import SqliteVecStore
        vec_store = SqliteVecStore(self.conn)
        vec_store.delete_by_file_id(file_id)
        cursor = self.conn.execute("DELETE FROM chunks WHERE file_id = ?;", (file_id,))
        return cursor.rowcount

    def _build_file_filters(
        self,
        folder_id: Optional[str] = None,
        status: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Tuple[str, str, List[Any]]:
        """Constructs FROM clause, WHERE clause, and parameter list for file listing and counting."""
        conditions: List[str] = []
        params: List[Any] = []
        use_fts = False
        fts_query = None

        if folder_id:
            conditions.append("f.folder_id = ?")
            params.append(folder_id)
        if status:
            conditions.append("f.index_status = ?")
            params.append(status.upper())

        if search and search.strip():
            raw_search = search.strip()
            words = [w.replace('"', '""') for w in raw_search.split() if w]
            has_short = any(len(w) < 3 for w in words)

            if words and not has_short:
                fts_expr = " AND ".join(f'"{w}"' for w in words)
                try:
                    self.conn.execute("SELECT 1 FROM files_fts LIMIT 1;")
                    use_fts = True
                    fts_query = fts_expr
                except Exception:
                    use_fts = False

            if use_fts and fts_query:
                conditions.append("files_fts MATCH ?")
                params.append(fts_query)
            else:
                escaped = escape_like_wildcards(raw_search)
                pattern = f"%{escaped}%"
                conditions.append(
                    "(f.filename LIKE ? ESCAPE '\\' OR f.relative_path LIKE ? ESCAPE '\\' OR f.sha256 LIKE ? ESCAPE '\\')"
                )
                params.extend([pattern, pattern, pattern])

        if use_fts:
            from_clause = "files f JOIN files_fts ON files_fts.rowid = f.rowid"
        else:
            from_clause = "files f"

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        return from_clause, where_clause, params

    def list_files(
        self,
        folder_id: Optional[str] = None,
        status: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        from_clause, where_clause, params = self._build_file_filters(folder_id, status, search)
        query = f"SELECT f.* FROM {from_clause} {where_clause} ORDER BY f.modified_at DESC LIMIT ? OFFSET ?;"
        exec_params = list(params)
        exec_params.extend([limit, offset])

        cursor = self.conn.execute(query, exec_params)
        return [dict(row) for row in cursor.fetchall()]

    def count_files(
        self,
        folder_id: Optional[str] = None,
        status: Optional[str] = None,
        search: Optional[str] = None,
    ) -> int:
        from_clause, where_clause, params = self._build_file_filters(folder_id, status, search)
        query = f"SELECT COUNT(*) as cnt FROM {from_clause} {where_clause};"
        cursor = self.conn.execute(query, params)
        row = cursor.fetchone()
        return row["cnt"] if row else 0

    def list_indexed_paths_for_folder(self, folder_id: str) -> List[Dict[str, Any]]:
        """Returns all non-MISSING files in a folder as a list of {file_id, path} dicts."""
        cursor = self.conn.execute(
            "SELECT file_id, path FROM files WHERE folder_id = ? AND index_status != 'MISSING';",
            (folder_id,),
        )
        return [{"file_id": row["file_id"], "path": row["path"]} for row in cursor.fetchall()]

    def mark_file_missing(self, path: str) -> bool:
        alt1 = path.replace('/', '\\')
        alt2 = path.replace('\\', '/')
        now = _utcnow_iso()
        if os.name == "nt":
            cursor = self.conn.execute(
                "UPDATE files SET index_status = 'MISSING', last_seen_at = ? WHERE path COLLATE NOCASE IN (?, ?, ?);",
                (now, path, alt1, alt2),
            )
        else:
            cursor = self.conn.execute(
                "UPDATE files SET index_status = 'MISSING', last_seen_at = ? WHERE path IN (?, ?, ?);",
                (now, path, alt1, alt2),
            )
        return cursor.rowcount > 0

    def mark_directory_missing(self, folder_id: str, dir_path: str) -> int:
        """
        Marks all files under a deleted directory subtree as MISSING in a single atomic query,
        and cancels all active/pending indexing jobs for those files.
        """
        dir_fwd = dir_path.replace('\\', '/').rstrip('/') + '/'
        dir_bwd = dir_path.replace('/', '\\').rstrip('\\') + '\\'
        clean_fwd = dir_path.replace('\\', '/').rstrip('/')
        clean_bwd = dir_path.replace('/', '\\').rstrip('\\')
        now = _utcnow_iso()

        pattern_fwd = escape_like_wildcards(dir_fwd) + "%"
        pattern_bwd = escape_like_wildcards(dir_bwd) + "%"

        cursor = self.conn.execute(
            """
            UPDATE files
            SET index_status = 'MISSING', last_seen_at = ?
            WHERE folder_id = ? AND (path LIKE ? ESCAPE '\\' OR path LIKE ? ESCAPE '\\' OR path = ? OR path = ?) AND index_status != 'MISSING';
            """,
            (now, folder_id, pattern_fwd, pattern_bwd, clean_fwd, clean_bwd),
        )
        affected = cursor.rowcount

        self.conn.execute(
            """
            UPDATE indexing_jobs
            SET status = 'CANCELLED'
            WHERE folder_id = ? AND status IN ('PENDING', 'PROCESSING')
              AND file_id IN (
                  SELECT file_id FROM files
                  WHERE folder_id = ? AND (path LIKE ? ESCAPE '\\' OR path LIKE ? ESCAPE '\\' OR path = ? OR path = ?)
              );
            """,
            (folder_id, folder_id, pattern_fwd, pattern_bwd, clean_fwd, clean_bwd),
        )
        return affected

    def rename_file_path(self, old_path: str, new_path: str, new_rel_path: str, new_filename: str, new_ext: str) -> bool:
        alt1 = old_path.replace('/', '\\')
        alt2 = old_path.replace('\\', '/')
        cursor = self.conn.execute(
            """
            UPDATE files
            SET path = ?, relative_path = ?, filename = ?, extension = ?, last_seen_at = ?
            WHERE path = ? OR path = ? OR path = ?;
            """,
            (new_path, new_rel_path, new_filename, new_ext, _utcnow_iso(), old_path, alt1, alt2),
        )
        return cursor.rowcount > 0

    def rename_directory_path(self, folder_id: str, old_dir_path: str, new_dir_path: str, root_folder_path: str) -> int:
        """
        Renames all files belonging to folder_id in an old directory subtree to the new directory path.
        Updates path, relative_path, and enqueues HASH_VERIFICATION jobs.
        """
        old_fwd = old_dir_path.replace('\\', '/').rstrip('/') + '/'
        old_bwd = old_dir_path.replace('/', '\\').rstrip('\\') + '\\'
        clean_fwd = old_dir_path.replace('\\', '/').rstrip('/')
        clean_bwd = old_dir_path.replace('/', '\\').rstrip('\\')

        pattern_fwd = escape_like_wildcards(old_fwd) + "%"
        pattern_bwd = escape_like_wildcards(old_bwd) + "%"

        cursor = self.conn.execute(
            """
            SELECT file_id, path FROM files
            WHERE folder_id = ? AND (path LIKE ? ESCAPE '\\' OR path LIKE ? ESCAPE '\\' OR path = ? OR path = ?);
            """,
            (folder_id, pattern_fwd, pattern_bwd, clean_fwd, clean_bwd),
        )
        rows = cursor.fetchall()
        now = _utcnow_iso()

        for row in rows:
            old_p = row["path"]
            sep = '/' if '/' in old_p and '\\' not in old_p else os.sep
            old_prefix = old_dir_path.replace('\\', sep).replace('/', sep).rstrip(sep) + sep
            new_prefix = new_dir_path.replace('\\', sep).replace('/', sep).rstrip(sep) + sep
            old_exact = old_dir_path.replace('\\', sep).replace('/', sep).rstrip(sep)
            new_exact = new_dir_path.replace('\\', sep).replace('/', sep).rstrip(sep)

            if old_p.startswith(old_prefix):
                rel_tail = old_p[len(old_prefix):]
                new_p = new_prefix + rel_tail
            elif old_p == old_exact:
                new_p = new_exact
            else:
                continue

            new_rel = os.path.relpath(new_p.replace('/', os.sep), root_folder_path.replace('/', os.sep)).replace("\\", "/")
            new_filename = os.path.basename(new_p)
            _, new_ext = os.path.splitext(new_filename)

            self.conn.execute(
                """
                UPDATE files
                SET path = ?, relative_path = ?, filename = ?, extension = ?, last_seen_at = ?
                WHERE file_id = ?;
                """,
                (new_p, new_rel, new_filename, new_ext.lower(), now, row["file_id"]),
            )
            if hasattr(self, "enqueue_job"):
                self.enqueue_job(
                    file_id=row["file_id"],
                    folder_id=folder_id,
                    job_type="HASH_VERIFICATION",
                    priority=2,
                )
            else:
                jid = str(uuid.uuid4())
                self.conn.execute(
                    """
                    INSERT INTO indexing_jobs (job_id, file_id, folder_id, job_type, status, priority, attempts, created_at)
                    VALUES (?, ?, ?, 'HASH_VERIFICATION', 'PENDING', 2, 0, ?);
                    """,
                    (jid, row["file_id"], folder_id, now),
                )

        return len(rows)

    def update_file_status(self, file_id: str, status: str, error: Optional[str] = None) -> bool:
        """Updates the index status and optional error message of a file."""
        now = _utcnow_iso()
        cursor = self.conn.execute(
            """
            UPDATE files
            SET index_status = ?, indexing_error = ?, last_seen_at = ?
            WHERE file_id = ?;
            """,
            (status.upper(), error, now, file_id),
        )
        return cursor.rowcount > 0

    def record_scan_error(self, file_id: str, error_message: str) -> bool:
        """
        Records a discovery-time filesystem/scan error for a file without requiring an indexing job.
        Sets index_status = 'FAILED' and indexing_error = error_message.
        Avoids changing files whose status is 'MISSING'.
        Persists a SCAN_ERROR event.
        Returns True if the file was updated, False otherwise.
        """
        now = _utcnow_iso()
        cursor = self.conn.execute(
            """
            UPDATE files
            SET index_status = 'FAILED', indexing_error = ?, last_seen_at = ?
            WHERE file_id = ? AND index_status != 'MISSING';
            """,
            (error_message, now, file_id),
        )
        if cursor.rowcount == 0:
            return False

        file_row = self.get_file_by_id(file_id)
        if file_row:
            if hasattr(self, "log_event"):
                self.log_event(
                    folder_id=file_row["folder_id"],
                    event_type="SCAN_ERROR",
                    path=file_row["path"],
                    file_id=file_id,
                    status="FAILED",
                )
            else:
                eid = str(uuid.uuid4())
                self.conn.execute(
                    """
                    INSERT INTO file_events (event_id, folder_id, file_id, event_type, path, observed_at, processing_status)
                    VALUES (?, ?, ?, 'SCAN_ERROR', ?, ?, 'FAILED');
                    """,
                    (eid, file_row["folder_id"], file_id, file_row["path"], now),
                )
        return True

    def delete_file(self, file_id: str) -> bool:
        # Clean up chunk_vectors virtual table entries before cascading relational delete
        cursor = self.conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='chunk_vectors';")
        if cursor.fetchone() is not None:
            self.conn.execute(
                """
                DELETE FROM chunk_vectors
                WHERE chunk_id IN (SELECT chunk_id FROM chunks WHERE file_id = ?);
                """,
                (file_id,),
            )
        cursor = self.conn.execute("DELETE FROM files WHERE file_id = ?;", (file_id,))
        return cursor.rowcount > 0

    def count_files_by_status(self, folder_id: Optional[str] = None) -> Dict[str, int]:
        query = "SELECT index_status, COUNT(*) as cnt FROM files"
        params = []
        if folder_id:
            query += " WHERE folder_id = ?"
            params.append(folder_id)
        query += " GROUP BY index_status;"

        cursor = self.conn.execute(query, params)
        counts = {
            "DISCOVERED": 0,
            "QUEUED": 0,
            "PROCESSING": 0,
            "INDEXED": 0,
            "FAILED": 0,
            "SKIPPED": 0,
            "MISSING": 0,
        }
        for row in cursor.fetchall():
            counts[row["index_status"]] = row["cnt"]
        counts["TOTAL"] = sum(counts.values())
        return counts
