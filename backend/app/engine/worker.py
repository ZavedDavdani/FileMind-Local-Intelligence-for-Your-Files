"""Background indexing worker pool with retry/backoff, concurrency limits, and Document Intelligence parsing."""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Optional

from app.core.config import DEFAULT_MAX_WORKERS
from app.db.connection import DatabaseManager
from app.db.repository import Repository
from app.engine.pipeline import IndexingPipeline, IndexingPipelineResult
from app.engine.queue import JobQueue
from app.intelligence.chunker.hierarchical import HierarchicalChunker
from app.retrieval.vector_store import SqliteVecStore

logger = logging.getLogger("FileMind.Worker")


class WorkerPool:
    """Manages background worker threads that process indexing and document intelligence jobs asynchronously."""

    def __init__(
        self,
        db_manager: DatabaseManager,
        max_workers: int = DEFAULT_MAX_WORKERS,
        embedding_engine: Optional[Any] = None,
    ):
        self.db = db_manager
        self.queue = JobQueue(db_manager)
        self.max_workers = max_workers
        self.threads: list[threading.Thread] = []
        self._running = False
        self._paused = False
        self._lock = threading.Lock()
        self._wake_event = threading.Event()
        self.chunker = HierarchicalChunker()
        self._embedding_engine = embedding_engine
        self.pipeline = IndexingPipeline(
            chunker=self.chunker,
            embedding_engine=embedding_engine,
        )

    @property
    def embedding_engine(self):
        if self._embedding_engine is not None:
            return self._embedding_engine
        from app.retrieval.embeddings import default_embedding_engine
        return default_embedding_engine

    def start(self):
        """Starts the worker pool threads."""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._paused = False
            self.threads = []
            for i in range(self.max_workers):
                t = threading.Thread(
                    target=self._worker_loop,
                    name=f"FileMind-Worker-{i+1}",
                    daemon=True,
                )
                t.start()
                self.threads.append(t)
        self._wake_event.set()
        logger.info("Worker pool started with %d workers", self.max_workers)

    def pause(self):
        """Pauses processing of new jobs (active jobs finish)."""
        with self._lock:
            self._paused = True
        self._wake_event.set()
        logger.info("Worker pool paused")

    def resume(self):
        """Resumes processing of jobs."""
        with self._lock:
            self._paused = False
        self._wake_event.set()
        logger.info("Worker pool resumed")

    def stop(self, timeout_sec: float = 3.0):
        """Stops all worker threads cleanly."""
        with self._lock:
            self._running = False
            self._paused = False
        self._wake_event.set()

        for t in self.threads:
            t.join(timeout=timeout_sec)
        self.threads = []
        logger.info("Worker pool stopped")

    def notify_job_available(self):
        """Signals worker threads that runnable jobs have been enqueued."""
        self._wake_event.set()

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def is_paused(self) -> bool:
        return self._paused

    def _worker_loop(self):
        """Worker thread main loop with event-driven wake-up."""
        while self._running:
            if self._paused:
                self._wake_event.wait(timeout=0.2)
                continue

            try:
                job = self.queue.claim_job()
                if not job:
                    self._wake_event.clear()
                    self._wake_event.wait(timeout=0.2)
                    continue

                self._process_job(job)
            except Exception as exc:
                logger.error("Unexpected worker exception: %s", str(exc), exc_info=True)
                time.sleep(0.5)

    def _process_job(self, job: dict):
        """Executes a single claimed job with strict error isolation."""
        job_id = job["job_id"]
        file_id = job["file_id"]
        file_path = job.get("file_path")
        attempts = job.get("attempts", 1)
        job_type = job.get("job_type", "METADATA_DISCOVERY")

        try:
            # Handle DELETE_CLEANUP in one atomic transaction
            if job_type == "DELETE_CLEANUP":
                with self.db.session() as conn:
                    repo = Repository(conn)
                    repo.purge_file_index(file_id)
                    repo.complete_job(job_id, file_id, final_status="MISSING")
                return

            if not file_path or not os.path.exists(file_path):
                # File disappeared before processing — permanent failure
                self.queue.fail_job(
                    job_id,
                    file_id,
                    "File not found or deleted on disk",
                    permanent=True,
                )
                return

            if job_type in (
                "METADATA_DISCOVERY",
                "HASH_VERIFICATION",
                "DOCUMENT_PARSE",
                "CHUNK_GENERATION",
            ):
                with self.db.session() as conn:
                    repo = Repository(conn)
                    file_rec = repo.get_file_by_id(file_id)
                    if file_rec is None or file_rec.get("index_status") == "MISSING":
                        logger.info("File %s is missing/deleted — skipping job %s", file_id, job_id)
                        repo.fail_job(job_id=job_id, file_id=file_id, error_message="File missing or deleted")
                        return
                    if not repo.is_current_processing_job(job_id, file_id):
                        logger.info("Job %s for file %s superseded by newer job — skipping", job_id, file_id)
                        repo.complete_job(job_id, file_id)
                        return
                    chunk_vers = repo.get_file_chunk_versions(file_id)

                pipeline_result = self.pipeline.execute(
                    file_path=file_path,
                    file_id=file_id,
                    job_id=job_id,
                    existing_file_rec=file_rec,
                    existing_chunk_vers=chunk_vers,
                )

                if pipeline_result.status == "FAILED":
                    self.queue.fail_job(
                        job_id=job_id,
                        file_id=file_id,
                        error_message=pipeline_result.indexing_error or "Indexing failure",
                        attempts=attempts,
                        permanent=pipeline_result.permanent_failure,
                    )
                    return

                self._persist_pipeline_outcome(job_id, file_id, pipeline_result)
            else:
                self.queue.complete_job(job_id, file_id)

        except Exception as exc:
            logger.error("Job %s encountered unhandled error: %s", job_id, str(exc), exc_info=True)
            self.queue.fail_job(job_id, file_id, f"Unhandled error: {str(exc)}", attempts=attempts, permanent=True)

    def _persist_pipeline_outcome(
        self,
        job_id: str,
        file_id: str,
        result: IndexingPipelineResult,
    ) -> None:
        """Atomically persists chunks, vectors, metadata, file status, and job completion

        within ONE single SQLite write transaction. If any error occurs prior to COMMIT,
        the entire transaction is rolled back by DatabaseManager.session().
        """
        with self.db.session() as conn:
            repo = Repository(conn)
            file_rec_current = repo.get_file_by_id(file_id)
            if file_rec_current is None or file_rec_current.get("index_status") == "MISSING":
                logger.info(
                    "File %s was deleted or marked missing during processing — reconciling terminal job state",
                    file_id,
                )
                repo.fail_job(
                    job_id=job_id,
                    file_id=file_id,
                    error_message="File was deleted or marked missing during processing",
                )
                return

            if not repo.is_current_processing_job(job_id, file_id):
                logger.info(
                    "File %s changed during processing — skipping stale chunk persistence",
                    file_id,
                )
                repo.complete_job(job_id, file_id)
                return

            if result.is_unchanged_bypass:
                repo.complete_job(
                    job_id,
                    file_id,
                    sha256=result.sha256,
                    final_status="INDEXED",
                )
                return

            # Purge existing vectors and chunks (vectors first)
            repo.purge_file_index(file_id)

            final_error = result.indexing_error
            final_status = result.status

            if result.status == "INDEXED":
                if result.chunks:
                    repo.replace_file_chunks(file_id, result.chunks)

                if result.vector_records:
                    vec_store = SqliteVecStore(conn, dimension=result.dimension)
                    identity = self.embedding_engine.get_identity()
                    if not vec_store.verify_index_validity(identity):
                        prov = identity.get("provider")
                        mname = identity.get("model_name")
                        dim = identity.get("dimension")
                        vec_mismatch_reason = (
                            "Vector write skipped: active embedding identity "
                            f"({prov}:{mname}:{dim}d) "
                            "differs from existing vector index. Dense search is unavailable for this file; "
                            "a full corpus re-embed/rebuild is required."
                        )
                        logger.warning(
                            "Embedding model identity mismatch for file %s: %s",
                            file_id,
                            vec_mismatch_reason,
                        )
                        final_error = (
                            f"{final_error} | {vec_mismatch_reason}"
                            if final_error
                            else vec_mismatch_reason
                        )
                    else:
                        vec_store.upsert_vectors(result.vector_records)
                        vec_store.set_index_metadata(
                            provider=identity["provider"],
                            model_name=identity["model_name"],
                            model_version=identity["model_version"],
                            dimension=identity["dimension"],
                        )

            # Atomically update file status and complete job in the same transaction
            repo.complete_job(
                job_id=job_id,
                file_id=file_id,
                sha256=result.sha256,
                final_status=final_status,
                indexing_error=final_error,
            )
