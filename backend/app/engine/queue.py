"""Persistent SQLite job queue manager."""

import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from app.core.config import INITIAL_BACKOFF_SECONDS, MAX_RETRY_ATTEMPTS
from app.db.connection import DatabaseManager
from app.db.repository import Repository


class JobQueue:
    """Manages transactional scheduling, claiming, retry backoff, and completion of indexing jobs."""

    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    def claim_job(self) -> Optional[Dict[str, Any]]:
        """Claims the next executable job from SQLite."""
        with self.db.session() as conn:
            repo = Repository(conn)
            return repo.claim_next_job()

    def complete_job(
        self,
        job_id: str,
        file_id: str,
        sha256: Optional[str] = None,
        final_status: Optional[str] = None,
        indexing_error: Optional[str] = None,
    ) -> bool:
        """Marks a job as COMPLETED and updates file status."""
        with self.db.session() as conn:
            repo = Repository(conn)
            return repo.complete_job(job_id, file_id, sha256, final_status, indexing_error)

    def fail_job(self, job_id: str, file_id: str, error_message: str, attempts: int) -> bool:
        """Calculates retry backoff or permanently fails the job if max attempts exceeded."""
        with self.db.session() as conn:
            repo = Repository(conn)
            if attempts < MAX_RETRY_ATTEMPTS:
                # Exponential backoff: 1s, 2s, 4s...
                delay_sec = INITIAL_BACKOFF_SECONDS * (2 ** (attempts - 1))
                retry_dt = datetime.now(timezone.utc) + timedelta(seconds=delay_sec)
                retry_at = retry_dt.isoformat()
            else:
                retry_at = None

            return repo.fail_job(job_id, file_id, error_message, retry_at)

    def recover_stale_jobs(self) -> int:
        """Resets any jobs left in PROCESSING by a prior interrupted session to PENDING."""
        with self.db.session() as conn:
            repo = Repository(conn)
            return repo.recover_stale_processing_jobs()

    def count_jobs(self) -> Dict[str, int]:
        with self.db.session() as conn:
            repo = Repository(conn)
            return repo.count_jobs_by_status()
