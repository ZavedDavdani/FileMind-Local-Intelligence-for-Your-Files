"""Indexing jobs repository domain operations."""

import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobRepository:
    """Provides strongly typed CRUD queries for indexing jobs."""

    TERMINAL_JOB_RETENTION = 1000

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def prune_terminal_jobs(self, retain: int = TERMINAL_JOB_RETENTION) -> int:
        """Prunes only old terminal jobs, preserving runnable/recoverable work."""
        if retain < 0:
            raise ValueError("retain must be non-negative")
        cursor = self.conn.execute(
            """
            DELETE FROM indexing_jobs
            WHERE job_id IN (
                SELECT job_id FROM indexing_jobs
                WHERE status IN ('COMPLETED', 'FAILED', 'CANCELLED')
                ORDER BY COALESCE(completed_at, created_at) DESC, job_id DESC
                LIMIT -1 OFFSET ?
            );
            """,
            (retain,),
        )
        return cursor.rowcount

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

        cursor = self.conn.execute(
            """
            SELECT * FROM indexing_jobs
            WHERE file_id = ? AND job_type = ? AND status = 'PENDING';
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

    def is_current_processing_job(self, job_id: str, file_id: str) -> bool:
        """Whether a runnable job still owns the latest write for its file."""
        cursor = self.conn.execute(
            """
            SELECT 1
            FROM indexing_jobs AS current_job
            WHERE current_job.job_id = ?
              AND current_job.file_id = ?
              AND current_job.status IN ('PENDING', 'PROCESSING')
              AND NOT EXISTS (
                  SELECT 1 FROM indexing_jobs AS newer_job
                  WHERE newer_job.file_id = current_job.file_id
                    AND newer_job.job_id != current_job.job_id
                    AND (
                        (newer_job.status = 'PENDING' AND (
                            newer_job.created_at > current_job.created_at
                            OR (newer_job.created_at = current_job.created_at AND current_job.status = 'PROCESSING')
                        ))
                        OR (newer_job.status = 'PROCESSING' AND (
                            (newer_job.started_at IS NOT NULL AND current_job.started_at IS NOT NULL AND newer_job.started_at > current_job.started_at)
                            OR (newer_job.created_at > current_job.created_at)
                        ))
                        OR (newer_job.status = 'COMPLETED' AND (
                            (newer_job.started_at IS NOT NULL AND current_job.started_at IS NOT NULL AND newer_job.started_at > current_job.started_at)
                            OR (newer_job.created_at > current_job.created_at)
                        ))
                    )
              );
            """,
            (job_id, file_id),
        )
        return cursor.fetchone() is not None

    def claim_next_job(self) -> Optional[Dict[str, Any]]:
        """Atomically claims the highest-priority pending or retryable job with an existing file and folder."""
        while True:
            now = _utcnow_iso()
            query = """
            UPDATE indexing_jobs
            SET status = 'PROCESSING', started_at = ?, attempts = attempts + 1
            WHERE job_id = (
                SELECT j.job_id FROM indexing_jobs j
                LEFT JOIN folders fo ON j.folder_id = fo.folder_id
                WHERE j.status = 'PENDING'
                  AND (j.retry_at IS NULL OR j.retry_at <= ?)
                  AND (fo.folder_id IS NULL OR fo.indexing_enabled = 1 OR j.job_type = 'DELETE_CLEANUP')
                ORDER BY j.priority DESC, j.created_at ASC
                LIMIT 1
            )
            RETURNING *;
            """
            cursor = self.conn.execute(query, (now, now))
            row = cursor.fetchone()
            if not row:
                return None

            job = dict(row)
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
                if job.get("job_type") != "DELETE_CLEANUP":
                    self.conn.execute(
                        "UPDATE files SET index_status = 'PROCESSING' WHERE file_id = ? AND index_status != 'MISSING';",
                        (job["file_id"],),
                    )
                return job

            # Orphan job referencing missing file/folder -> permanently fail it and continue claiming
            self.conn.execute(
                """
                UPDATE indexing_jobs
                SET status = 'FAILED', error = 'Orphan job: file or folder record not found'
                WHERE job_id = ?;
                """,
                (job["job_id"],),
            )
            self.prune_terminal_jobs()

    def complete_job(
        self,
        job_id: str,
        file_id: str,
        sha256: Optional[str] = None,
        final_status: Optional[str] = None,
        indexing_error: Optional[str] = None,
    ) -> bool:
        status_to_set = (final_status.upper() if final_status else "INDEXED")
        if status_to_set not in ("DISCOVERED", "QUEUED", "PROCESSING", "INDEXED", "FAILED", "SKIPPED", "MISSING"):
            raise ValueError(f"Invalid file index_status: {status_to_set}")

        now = _utcnow_iso()
        current_job = self.is_current_processing_job(job_id, file_id)
        job_cursor = self.conn.execute(
            """
            UPDATE indexing_jobs
            SET status = 'COMPLETED', completed_at = ?, error = NULL
            WHERE job_id = ? AND status != 'CANCELLED';
            """,
            (now, job_id),
        )
        if (job_cursor.rowcount > 0) and current_job:
            self.conn.execute(
                """
                UPDATE files
                SET index_status = ?, sha256 = COALESCE(?, sha256), indexing_error = ?,
                    indexed_at = CASE WHEN ? = 'INDEXED' THEN ? ELSE indexed_at END
                WHERE file_id = ? AND index_status != 'MISSING';
                """,
                (status_to_set, sha256, indexing_error, status_to_set, now, file_id),
            )
        if job_cursor.rowcount > 0:
            self.prune_terminal_jobs()
        return True

    def fail_job(self, job_id: str, file_id: str, error_message: str, retry_at: Optional[str] = None) -> bool:
        now = _utcnow_iso()
        status = "PENDING" if retry_at else "FAILED"
        current_job = self.is_current_processing_job(job_id, file_id)
        job_cursor = self.conn.execute(
            """
            UPDATE indexing_jobs
            SET status = ?, error = ?, retry_at = ?
            WHERE job_id = ? AND status != 'CANCELLED';
            """,
            (status, error_message, retry_at, job_id),
        )
        file_status = "QUEUED" if retry_at else "FAILED"
        if job_cursor.rowcount > 0 and current_job:
            self.conn.execute(
                "UPDATE files SET index_status = ?, indexing_error = ? WHERE file_id = ? AND index_status != 'MISSING';",
                (file_status, error_message, file_id),
            )
        if job_cursor.rowcount > 0 and status == "FAILED":
            self.prune_terminal_jobs()
        return True

    def cancel_pending_jobs_for_file(self, file_id: str) -> int:
        cursor = self.conn.execute(
            "UPDATE indexing_jobs SET status = 'CANCELLED' WHERE file_id = ? AND status = 'PENDING';",
            (file_id,),
        )
        if cursor.rowcount > 0:
            self.prune_terminal_jobs()
        return cursor.rowcount

    def recover_stale_processing_jobs(self, stale_threshold_seconds: Optional[float] = None) -> int:
        """Crash Recovery: Identifies any jobs stuck in PROCESSING and resets them to PENDING."""
        if stale_threshold_seconds is not None:
            cutoff = (datetime.now(timezone.utc) - timedelta(seconds=stale_threshold_seconds)).isoformat()
            cursor = self.conn.execute(
                """
                UPDATE indexing_jobs
                SET status = 'PENDING', started_at = NULL, attempts = MAX(0, attempts - 1), error = 'Recovered after stale timeout'
                WHERE status = 'PROCESSING' AND (started_at IS NULL OR started_at <= ?)
                RETURNING file_id;
                """,
                (cutoff,),
            )
        else:
            cursor = self.conn.execute(
                """
                UPDATE indexing_jobs
                SET status = 'PENDING', started_at = NULL, attempts = MAX(0, attempts - 1), error = 'Recovered after engine restart'
                WHERE status = 'PROCESSING'
                RETURNING file_id;
                """
            )
        recovered_rows = cursor.fetchall()
        recovered_count = len(recovered_rows)
        if recovered_count > 0:
            file_ids = list({r["file_id"] for r in recovered_rows})
            placeholders = ",".join("?" * len(file_ids))
            self.conn.execute(
                f"""
                UPDATE files
                SET index_status = 'QUEUED'
                WHERE file_id IN ({placeholders}) AND index_status = 'PROCESSING';
                """,
                file_ids,
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
