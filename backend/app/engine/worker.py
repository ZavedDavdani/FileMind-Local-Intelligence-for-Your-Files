"""Background indexing worker pool with retry/backoff, concurrency limits, and Document Intelligence parsing."""

import logging
import os
import threading
import time
from typing import Optional

from app.core.config import DEFAULT_MAX_WORKERS
from app.db.connection import DatabaseManager
from app.db.repository import Repository
from app.engine.hasher import compute_file_sha256
from app.engine.queue import JobQueue
from app.intelligence.chunker.hierarchical import HierarchicalChunker
from app.intelligence.detector import detect_file_format, is_supported_document
from app.intelligence.parsers.base import (
    CorruptedDocumentError,
    DocumentParserError,
    EncryptedDocumentError,
    UnsupportedFormatError,
)
from app.intelligence.parsers.registry import default_parser_registry

logger = logging.getLogger("FileMind.Worker")


class WorkerPool:
    """Manages background worker threads that process indexing and document intelligence jobs asynchronously."""

    def __init__(self, db_manager: DatabaseManager, max_workers: int = DEFAULT_MAX_WORKERS):
        self.db = db_manager
        self.queue = JobQueue(db_manager)
        self.max_workers = max_workers
        self.threads = []
        self._running = False
        self._paused = False
        self._lock = threading.Lock()
        self.chunker = HierarchicalChunker()

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
        logger.info("Worker pool started with %d workers", self.max_workers)

    def pause(self):
        """Pauses processing of new jobs (active jobs finish)."""
        with self._lock:
            self._paused = True
        logger.info("Worker pool paused")

    def resume(self):
        """Resumes processing of jobs."""
        with self._lock:
            self._paused = False
        logger.info("Worker pool resumed")

    def stop(self, timeout_sec: float = 3.0):
        """Stops all worker threads cleanly."""
        with self._lock:
            self._running = False
            self._paused = False

        for t in self.threads:
            t.join(timeout=timeout_sec)
        self.threads = []
        logger.info("Worker pool stopped")

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def is_paused(self) -> bool:
        return self._paused

    def _worker_loop(self):
        """Worker thread main loop."""
        while self._running:
            if self._paused:
                time.sleep(0.2)
                continue

            try:
                job = self.queue.claim_job()
                if not job:
                    time.sleep(0.2)
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
            # Handle DELETE_CLEANUP even if file is already deleted on disk
            if job_type == "DELETE_CLEANUP":
                with self.db.session() as conn:
                    repo = Repository(conn)
                    repo.delete_chunks_by_file(file_id)
                    try:
                        from app.retrieval.vector_store import SqliteVecStore
                        vec_store = SqliteVecStore(conn)
                        vec_store.delete_by_file_id(file_id)
                    except Exception as vec_err:
                        logger.warning("Vector delete warning for file %s: %s", file_id, str(vec_err))
                self.queue.complete_job(job_id, file_id)
                return

            if not file_path or not os.path.exists(file_path):
                # File disappeared before processing — permanent failure (not retryable)
                self.queue.fail_job(job_id, file_id, "File not found or deleted on disk", permanent=True)
                return

            if job_type in ("METADATA_DISCOVERY", "HASH_VERIFICATION", "DOCUMENT_PARSE", "CHUNK_GENERATION"):
                # 0. Check Max File Size Ingestion Guard
                from app.core.config import MAX_FILE_SIZE_BYTES
                try:
                    file_size = os.path.getsize(file_path)
                except OSError:
                    file_size = 0

                if file_size > MAX_FILE_SIZE_BYTES:
                    err_msg = f"File size ({file_size} bytes) exceeds limit ({MAX_FILE_SIZE_BYTES} bytes)"
                    logger.info("File %s exceeds max size limit: %d bytes", file_path, file_size)
                    with self.db.session() as conn:
                        repo = Repository(conn)
                        repo.update_file_status(file_id, "SKIPPED", error=err_msg)
                    self.queue.complete_job(job_id, file_id, final_status="SKIPPED", indexing_error=err_msg)
                    return

                # 1. Compute SHA-256 Hash
                sha256_hash, error = compute_file_sha256(file_path)
                if error:
                    logger.warning("Job %s for file %s failed hashing: %s", job_id, file_path, error)
                    self.queue.fail_job(job_id, file_id, error, attempts=attempts)
                    return

                # 2. Check if file format is supported for Document Intelligence
                mime_type, _ = detect_file_format(file_path)
                parser = default_parser_registry.get_parser_for_file(file_path, mime_type)

                if not parser:
                    # Non-parseable or unsupported format -> complete hashing, skip chunking
                    self.queue.complete_job(job_id, file_id, sha256=sha256_hash)
                    return

                # Check unchanged hash & version bypass for Strict Integrity verification
                with self.db.session() as conn:
                    repo = Repository(conn)
                    file_rec = repo.get_file_by_id(file_id)
                    chunk_vers = repo.get_file_chunk_versions(file_id)

                if file_rec and file_rec.get("index_status") == "INDEXED" and file_rec.get("sha256") == sha256_hash and chunk_vers:
                    if (chunk_vers.get("parser_version") == parser.parser_version and
                        chunk_vers.get("chunker_version") == self.chunker.chunker_version):
                        # Strict Integrity verification passed: hash and versions match existing index
                        logger.info("File %s integrity verified (unchanged SHA-256 and versions)", file_path)
                        self.queue.complete_job(job_id, file_id, sha256=sha256_hash, final_status="INDEXED")
                        return

                # 3. Document Parsing & Hierarchical Chunking
                try:
                    doc = parser.parse(file_path, file_id=file_id, mime_type=mime_type)


                    # Hardening H3: Quality Gate & Vectorization Boundary Check
                    if hasattr(doc, "quality_assessment") and doc.quality_assessment:
                        qa = doc.quality_assessment
                        if qa.status == "REQUIRES_OCR":
                            logger.info("File %s requires OCR: %s", file_path, qa.reason_codes)
                            with self.db.session() as conn:
                                repo = Repository(conn)
                                # Purge any stale chunks or vectors
                                repo.delete_chunks_by_file(file_id)
                                try:
                                    from app.retrieval.vector_store import SqliteVecStore
                                    vec_store = SqliteVecStore(conn)
                                    vec_store.delete_by_file_id(file_id)
                                except Exception as vec_err:
                                    logger.warning("Vector cleanup warning for file %s: %s", file_id, str(vec_err))

                            self.queue.complete_job(
                                job_id,
                                file_id,
                                sha256=sha256_hash,
                                final_status="SKIPPED",
                                indexing_error=qa.to_json()
                            )
                            return

                    chunks = self.chunker.chunk_document(doc)

                    # Compute vector embeddings outside the SQLite write transaction
                    vec_records = []
                    dimension = 384
                    if chunks:
                        try:
                            from app.retrieval.embeddings import default_embedding_engine
                            dimension = default_embedding_engine.dimension
                            texts = [c.content if hasattr(c, "content") else c["content"] for c in chunks]
                            chunk_ids = [c.chunk_id if hasattr(c, "chunk_id") else c["chunk_id"] for c in chunks]
                            vectors = default_embedding_engine.embed_texts(texts)
                            vec_records = [
                                {"chunk_id": cid, "file_id": file_id, "embedding": vec}
                                for cid, vec in zip(chunk_ids, vectors)
                            ]
                        except Exception as vec_exc:
                            logger.warning("Vector embedding generation warning for file %s: %s", file_id, str(vec_exc))

                    # 4. Atomic Persistence & Vector Indexing
                    with self.db.session() as conn:
                        repo = Repository(conn)
                        repo.replace_file_chunks(file_id, chunks)

                        if vec_records:
                            try:
                                from app.retrieval.vector_store import SqliteVecStore
                                vec_store = SqliteVecStore(conn, dimension=dimension)
                                vec_store.upsert_vectors(vec_records)
                            except Exception as vec_store_exc:
                                logger.warning("Vector indexing storage warning for file %s: %s", file_id, str(vec_store_exc))

                    # 5. Mark Job Complete
                    if hasattr(doc, "quality_assessment") and doc.quality_assessment and doc.quality_assessment.status == "PARSE_WARNING":
                        self.queue.complete_job(
                            job_id,
                            file_id,
                            sha256=sha256_hash,
                            final_status="INDEXED",
                            indexing_error=doc.quality_assessment.to_json()
                        )
                    else:
                        self.queue.complete_job(
                            job_id,
                            file_id,
                            sha256=sha256_hash,
                            final_status="INDEXED",
                            indexing_error=None
                        )

                except EncryptedDocumentError as enc_exc:
                    logger.info("File %s is encrypted/password protected: %s", file_path, str(enc_exc))
                    self.queue.complete_job(
                        job_id,
                        file_id,
                        sha256=sha256_hash,
                        final_status="SKIPPED",
                        indexing_error=f"Encrypted/Password Protected: {str(enc_exc)}"
                    )

                except CorruptedDocumentError as corp_exc:
                    logger.warning("File %s is corrupted: %s", file_path, str(corp_exc))
                    with self.db.session() as conn:
                        repo = Repository(conn)
                        repo.update_file_status(file_id, "FAILED", error=f"Corrupted: {str(corp_exc)}")
                    self.queue.fail_job(job_id, file_id, str(corp_exc), permanent=True)

                except Exception as parse_exc:
                    logger.error("Parser failed on %s: %s", file_path, str(parse_exc), exc_info=True)
                    with self.db.session() as conn:
                        repo = Repository(conn)
                        repo.update_file_status(file_id, "FAILED", error=f"Parse Error: {str(parse_exc)}")
                    self.queue.fail_job(job_id, file_id, f"Parse failure: {str(parse_exc)}", permanent=True)

            else:
                self.queue.complete_job(job_id, file_id)

        except Exception as exc:
            logger.error("Job %s encountered unhandled error: %s", job_id, str(exc), exc_info=True)
            self.queue.fail_job(job_id, file_id, f"Unhandled error: {str(exc)}", attempts=attempts)
