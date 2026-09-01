"""SQLite Repository layer for folders, files, jobs, and event audit trail."""

import json
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


class Repository:
    """Provides strongly typed CRUD queries for the local FileMind database."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    # -------------------------------------------------------------------------
    # Folders
    # -------------------------------------------------------------------------

    def create_folder(
        self,
        path: str,
        recursive: bool = True,
        integrity_mode: str = "NORMAL",
        indexing_enabled: bool = True,
        exclude_patterns: List[str] = None,
        folder_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        fid = folder_id or str(uuid.uuid4())
        now = _utcnow_iso()
        patterns_json = json.dumps(exclude_patterns or [])

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
        cursor = self.conn.execute("SELECT * FROM folders WHERE path = ?;", (path,))
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
        exclude_patterns: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        existing = self.get_folder(folder_id)
        if not existing:
            return None

        now = _utcnow_iso()
        new_rec = 1 if (recursive if recursive is not None else existing["recursive"]) else 0
        new_mode = (integrity_mode or existing["integrity_mode"]).upper()
        new_enabled = 1 if (indexing_enabled if indexing_enabled is not None else existing["indexing_enabled"]) else 0
        new_patterns = json.dumps(exclude_patterns if exclude_patterns is not None else existing["exclude_patterns"])

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
        try:
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
        except Exception:
            pass

        cursor = self.conn.execute("DELETE FROM folders WHERE folder_id = ?;", (folder_id,))
        return cursor.rowcount > 0

    def _folder_row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        d = dict(row)
        d["recursive"] = bool(d["recursive"])
        d["indexing_enabled"] = bool(d["indexing_enabled"])
        try:
            d["exclude_patterns"] = json.loads(d["exclude_patterns"])
        except Exception:
            d["exclude_patterns"] = []
        return d

    # -------------------------------------------------------------------------
    # Files
    # -------------------------------------------------------------------------

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
            index_status = excluded.index_status,
            indexing_error = excluded.indexing_error,
            indexed_at = CASE WHEN excluded.index_status = 'INDEXED' THEN excluded.last_seen_at ELSE files.indexed_at END
        RETURNING *;
        """
        indexed_at = now if index_status == "INDEXED" else None
        cursor = self.conn.execute(
            query,
            (
                fid,
                folder_id,
                path,
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
        cursor = self.conn.execute("SELECT * FROM files WHERE path = ?;", (path,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_file_by_id(self, file_id: str) -> Optional[Dict[str, Any]]:
        cursor = self.conn.execute("SELECT * FROM files WHERE file_id = ?;", (file_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def list_files(
        self,
        folder_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        conditions = []
        params = []
        if folder_id:
            conditions.append("folder_id = ?")
            params.append(folder_id)
        if status:
            conditions.append("index_status = ?")
            params.append(status.upper())

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        query = f"SELECT * FROM files {where_clause} ORDER BY modified_at DESC LIMIT ? OFFSET ?;"
        params.extend([limit, offset])

        cursor = self.conn.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]

    def list_indexed_paths_for_folder(self, folder_id: str) -> List[Dict[str, Any]]:
        """Returns all non-MISSING files in a folder as a list of {file_id, path} dicts.

        Used by the scanner for offline deletion reconciliation: after a full walk,
        any file returned here that was not seen on disk should be marked missing
        and queued for DELETE_CLEANUP.
        """
        cursor = self.conn.execute(
            "SELECT file_id, path FROM files WHERE folder_id = ? AND index_status != 'MISSING';",
            (folder_id,),
        )
        return [{"file_id": row["file_id"], "path": row["path"]} for row in cursor.fetchall()]

    def mark_file_missing(self, path: str) -> bool:
        cursor = self.conn.execute(
            "UPDATE files SET index_status = 'MISSING', last_seen_at = ? WHERE path = ?;",
            (_utcnow_iso(), path),
        )
        return cursor.rowcount > 0

    def mark_directory_missing(self, folder_id: str, dir_path: str) -> int:
        """
        Marks all files under a deleted directory subtree as MISSING in a single atomic query,
        and cancels all active/pending indexing jobs for those files.
        """
        import os
        dir_clean = normalize_path(dir_path)
        dir_prefix = dir_clean + os.sep
        now = _utcnow_iso()
        like_pattern = escape_like_wildcards(dir_prefix) + "%"

        cursor = self.conn.execute(
            """
            UPDATE files
            SET index_status = 'MISSING', last_seen_at = ?
            WHERE folder_id = ? AND (path LIKE ? ESCAPE '\\' OR path = ?) AND index_status != 'MISSING';
            """,
            (now, folder_id, like_pattern, dir_clean),
        )
        affected = cursor.rowcount

        self.conn.execute(
            """
            UPDATE indexing_jobs
            SET status = 'CANCELLED'
            WHERE folder_id = ? AND status IN ('PENDING', 'PROCESSING')
              AND file_id IN (
                  SELECT file_id FROM files
                  WHERE folder_id = ? AND (path LIKE ? ESCAPE '\\' OR path = ?)
              );
            """,
            (folder_id, folder_id, like_pattern, dir_clean),
        )
        return affected

    def rename_file_path(self, old_path: str, new_path: str, new_rel_path: str, new_filename: str, new_ext: str) -> bool:
        cursor = self.conn.execute(
            """
            UPDATE files
            SET path = ?, relative_path = ?, filename = ?, extension = ?, last_seen_at = ?
            WHERE path = ?;
            """,
            (new_path, new_rel_path, new_filename, new_ext, _utcnow_iso(), old_path),
        )
        return cursor.rowcount > 0

    def rename_directory_path(self, folder_id: str, old_dir_path: str, new_dir_path: str, root_folder_path: str) -> int:
        """
        Renames all files belonging to folder_id in an old directory subtree to the new directory path.
        Updates path, relative_path, and enqueues HASH_VERIFICATION jobs.
        """
        import os
        old_clean = normalize_path(old_dir_path)
        new_clean = normalize_path(new_dir_path)
        old_prefix = old_clean + os.sep
        new_prefix = new_clean + os.sep
        like_pattern = escape_like_wildcards(old_prefix) + "%"

        cursor = self.conn.execute(
            "SELECT file_id, path FROM files WHERE folder_id = ? AND (path LIKE ? ESCAPE '\\' OR path = ?);",
            (folder_id, like_pattern, old_clean),
        )
        rows = cursor.fetchall()
        now = _utcnow_iso()

        for row in rows:
            old_p = row["path"]
            if old_p.startswith(old_prefix):
                rel_tail = old_p[len(old_prefix):]
                new_p = new_prefix + rel_tail
            elif old_p == old_clean:
                new_p = new_clean
            else:
                continue

            new_rel = os.path.relpath(new_p, root_folder_path).replace("\\", "/")
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
            self.enqueue_job(
                file_id=row["file_id"],
                folder_id=folder_id,
                job_type="HASH_VERIFICATION",
                priority=2,
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

    def delete_file(self, file_id: str) -> bool:
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

    # -------------------------------------------------------------------------
    # Indexing Jobs
    # -------------------------------------------------------------------------

    def enqueue_job(
        self,
        file_id: str,
        folder_id: str,
        job_type: str = "METADATA_DISCOVERY",
        priority: int = 0,
        job_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        jid = job_id or str(uuid.uuid4())
        now = _utcnow_iso()

        # Check if an active job of the same type already exists for this file
        cursor = self.conn.execute(
            """
            SELECT * FROM indexing_jobs
            WHERE file_id = ? AND job_type = ? AND status IN ('PENDING', 'PROCESSING');
            """,
            (file_id, job_type),
        )
        existing = cursor.fetchone()
        if existing:
            return dict(existing)

        query = """
        INSERT INTO indexing_jobs (job_id, file_id, folder_id, job_type, status, priority, attempts, created_at)
        VALUES (?, ?, ?, ?, 'PENDING', ?, 0, ?)
        RETURNING *;
        """
        cursor = self.conn.execute(query, (jid, file_id, folder_id, job_type, priority, now))
        row = cursor.fetchone()
        return dict(row)

    def claim_next_job(self) -> Optional[Dict[str, Any]]:
        """Atomically claims the highest-priority pending or retryable job."""
        now = _utcnow_iso()
        query = """
        UPDATE indexing_jobs
        SET status = 'PROCESSING', started_at = ?, attempts = attempts + 1
        WHERE job_id = (
            SELECT job_id FROM indexing_jobs
            WHERE status = 'PENDING' AND (retry_at IS NULL OR retry_at <= ?)
            ORDER BY priority DESC, created_at ASC
            LIMIT 1
        )
        RETURNING *;
        """
        cursor = self.conn.execute(query, (now, now))
        row = cursor.fetchone()
        if not row:
            return None

        job = dict(row)
        # Fetch file and folder metadata
        meta_cursor = self.conn.execute(
            """
            SELECT f.path as file_path, f.folder_id as file_folder_id, fo.integrity_mode
            FROM files f
            JOIN folders fo ON f.folder_id = fo.folder_id
            WHERE f.file_id = ?;
            """,
            (job["file_id"],),
        )
        meta_row = meta_cursor.fetchone()
        if meta_row:
            job.update(dict(meta_row))

        self.conn.execute(
            "UPDATE files SET index_status = 'PROCESSING' WHERE file_id = ?;",
            (job["file_id"],),
        )
        return job

    def complete_job(
        self,
        job_id: str,
        file_id: str,
        sha256: Optional[str] = None,
        final_status: Optional[str] = None,
        indexing_error: Optional[str] = None,
    ) -> bool:
        now = _utcnow_iso()
        self.conn.execute(
            """
            UPDATE indexing_jobs
            SET status = 'COMPLETED', completed_at = ?, error = NULL
            WHERE job_id = ?;
            """,
            (now, job_id),
        )
        if final_status:
            self.conn.execute(
                """
                UPDATE files
                SET index_status = ?, sha256 = COALESCE(?, sha256), indexing_error = ?, indexed_at = CASE WHEN ? = 'INDEXED' THEN ? ELSE indexed_at END
                WHERE file_id = ?;
                """,
                (final_status, sha256, indexing_error, final_status, now, file_id),
            )
        else:
            self.conn.execute(
                """
                UPDATE files
                SET index_status = 'INDEXED', sha256 = COALESCE(?, sha256), indexing_error = NULL, indexed_at = ?
                WHERE file_id = ?;
                """,
                (sha256, now, file_id),
            )
        return True

    def fail_job(self, job_id: str, file_id: str, error_message: str, retry_at: Optional[str] = None) -> bool:
        now = _utcnow_iso()
        status = "PENDING" if retry_at else "FAILED"
        self.conn.execute(
            """
            UPDATE indexing_jobs
            SET status = ?, error = ?, retry_at = ?
            WHERE job_id = ?;
            """,
            (status, error_message, retry_at, job_id),
        )
        file_status = "QUEUED" if retry_at else "FAILED"
        self.conn.execute(
            "UPDATE files SET index_status = ?, indexing_error = ? WHERE file_id = ?;",
            (file_status, error_message, file_id),
        )
        return True

    def cancel_pending_jobs_for_file(self, file_id: str) -> int:
        cursor = self.conn.execute(
            "UPDATE indexing_jobs SET status = 'CANCELLED' WHERE file_id = ? AND status = 'PENDING';",
            (file_id,),
        )
        return cursor.rowcount

    def recover_stale_processing_jobs(self) -> int:
        """Crash Recovery: Identifies any jobs stuck in PROCESSING and resets them to PENDING."""
        now = _utcnow_iso()
        cursor = self.conn.execute(
            """
            UPDATE indexing_jobs
            SET status = 'PENDING', started_at = NULL, error = 'Recovered after engine restart'
            WHERE status = 'PROCESSING';
            """
        )
        recovered_count = cursor.rowcount
        if recovered_count > 0:
            self.conn.execute(
                """
                UPDATE files
                SET index_status = 'QUEUED'
                WHERE index_status = 'PROCESSING';
                """
            )
        return recovered_count

    def list_jobs(self, status: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        query = "SELECT * FROM indexing_jobs"
        params = []
        if status:
            query += " WHERE status = ?"
            params.append(status.upper())
        query += " ORDER BY created_at DESC LIMIT ?;"
        params.append(limit)

        cursor = self.conn.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]

    def count_jobs_by_status(self) -> Dict[str, int]:
        cursor = self.conn.execute(
            "SELECT status, COUNT(*) as cnt FROM indexing_jobs GROUP BY status;"
        )
        counts = {"PENDING": 0, "PROCESSING": 0, "COMPLETED": 0, "FAILED": 0, "CANCELLED": 0}
        for row in cursor.fetchall():
            counts[row["status"]] = row["cnt"]
        return counts

    # -------------------------------------------------------------------------
    # Filesystem Event Audit Log
    # -------------------------------------------------------------------------

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

    # -------------------------------------------------------------------------
    # Phase 2: Document Chunks & Provenance Storage
    # -------------------------------------------------------------------------

    def replace_file_chunks(self, file_id: str, chunks: List[Any]) -> int:
        """
        Atomically replaces all chunks for a given file_id.
        Removes any stale active chunks and inserts newly generated chunks.
        """
        self.conn.execute("DELETE FROM chunks WHERE file_id = ?;", (file_id,))
        now = _utcnow_iso()

        insert_sql = """
        INSERT INTO chunks (
            chunk_id, file_id, source_file, source_path, page, section,
            h1_parent, h2_parent, line_start, line_end, char_start, char_end,
            content_hash, chunk_index, parser_name, parser_version,
            chunker_version, content, content_type, token_count, metadata_json,
            created_at, updated_at
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        );
        """
        rows_to_insert = []
        for c in chunks:
            c_dict = c if isinstance(c, dict) else (c.to_dict() if hasattr(c, "to_dict") else c.__dict__)
            meta_json = json.dumps(c_dict.get("metadata", {}))
            rows_to_insert.append((
                c_dict["chunk_id"],
                file_id,
                c_dict["source_file"],
                c_dict["source_path"],
                c_dict.get("page"),
                c_dict.get("section"),
                c_dict.get("h1_parent"),
                c_dict.get("h2_parent"),
                c_dict.get("line_start"),
                c_dict.get("line_end"),
                c_dict.get("char_start"),
                c_dict.get("char_end"),
                c_dict["content_hash"],
                c_dict.get("chunk_index", 0),
                c_dict.get("parser_name", "unknown"),
                c_dict.get("parser_version", "1.0.0"),
                c_dict.get("chunker_version", "phase2-hierarchical-v1"),
                c_dict["content"],
                c_dict.get("content_type", "text"),
                c_dict.get("token_count", 0),
                meta_json,
                now,
                now,
            ))

        if rows_to_insert:
            self.conn.executemany(insert_sql, rows_to_insert)

        return len(rows_to_insert)

    def get_chunks_by_file(self, file_id: str) -> List[Dict[str, Any]]:
        """Retrieves all chunks for a file ordered by chunk_index."""
        cursor = self.conn.execute(
            "SELECT * FROM chunks WHERE file_id = ? ORDER BY chunk_index ASC;",
            (file_id,),
        )
        results = []
        for row in cursor.fetchall():
            d = dict(row)
            try:
                d["metadata"] = json.loads(d.get("metadata_json") or "{}")
            except Exception:
                d["metadata"] = {}
            results.append(d)
        return results

    def get_chunk_by_id(self, chunk_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves a single chunk by chunk_id."""
        cursor = self.conn.execute("SELECT * FROM chunks WHERE chunk_id = ?;", (chunk_id,))
        row = cursor.fetchone()
        if not row:
            return None
        d = dict(row)
        try:
            d["metadata"] = json.loads(d.get("metadata_json") or "{}")
        except Exception:
            d["metadata"] = {}
        return d

    def delete_chunks_by_file(self, file_id: str) -> int:
        """Explicitly deletes all chunks associated with a file_id."""
        cursor = self.conn.execute("DELETE FROM chunks WHERE file_id = ?;", (file_id,))
        return cursor.rowcount

    def count_total_chunks(self) -> int:
        """Returns the total number of chunks across all files."""
        cursor = self.conn.execute("SELECT COUNT(*) FROM chunks;")
        return cursor.fetchone()[0]

    def count_chunks_by_folder(self, folder_id: str) -> int:
        """Returns the total number of chunks in a registered folder."""
        cursor = self.conn.execute(
            "SELECT COUNT(*) FROM chunks WHERE file_id IN (SELECT file_id FROM files WHERE folder_id = ?);",
            (folder_id,),
        )
        return cursor.fetchone()[0]

    def get_document_intelligence_stats(self) -> Dict[str, Any]:
        """Returns summary statistics for Document Intelligence."""
        total_chunks = self.count_total_chunks()
        cursor = self.conn.execute(
            "SELECT index_status, COUNT(*) as cnt FROM files GROUP BY index_status;"
        )
        file_counts = {}
        for r in cursor.fetchall():
            file_counts[r["index_status"]] = r["cnt"]

        # Count files that have chunks
        cursor2 = self.conn.execute("SELECT COUNT(DISTINCT file_id) FROM chunks;")
        files_with_chunks = cursor2.fetchone()[0]

        return {
            "total_chunks": total_chunks,
            "files_with_chunks": files_with_chunks,
            "indexed_files": file_counts.get("INDEXED", 0),
            "queued_files": file_counts.get("QUEUED", 0),
            "failed_files": file_counts.get("FAILED", 0),
            "skipped_files": file_counts.get("SKIPPED", 0),
        }

    def get_file_chunk_versions(self, file_id: str) -> Optional[Dict[str, str]]:
        """Returns the parser_name, parser_version, and chunker_version of indexed chunks for a file."""
        cursor = self.conn.execute(
            """
            SELECT parser_name, parser_version, chunker_version
            FROM chunks
            WHERE file_id = ?
            LIMIT 1;
            """,
            (file_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "parser_name": row["parser_name"],
            "parser_version": row["parser_version"],
            "chunker_version": row["chunker_version"],
        }

    def get_embedding_metadata(self) -> Optional[Dict[str, Any]]:
        """Returns the recorded active embedding model identity from database."""
        cursor = self.conn.execute(
            """
            SELECT provider, model_name, model_version, dimension, config_json, updated_at
            FROM embedding_index_metadata
            WHERE id = 1;
            """
        )
        row = cursor.fetchone()
        if not row:
            return None
        config = {}
        try:
            config = json.loads(row["config_json"] or "{}")
        except Exception:
            pass
        return {
            "provider": row["provider"],
            "model_name": row["model_name"],
            "model_version": row["model_version"],
            "dimension": row["dimension"],
            "config": config,
            "updated_at": row["updated_at"],
        }

    def set_embedding_metadata(
        self,
        provider: str,
        model_name: str,
        model_version: str,
        dimension: int,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Sets or replaces the active embedding model identity."""
        config_json = json.dumps(config or {})
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """
            INSERT OR REPLACE INTO embedding_index_metadata
            (id, provider, model_name, model_version, dimension, config_json, updated_at)
            VALUES (1, ?, ?, ?, ?, ?, ?);
            """,
            (provider, model_name, model_version, dimension, config_json, now),
        )


