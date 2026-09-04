"""Background indexing worker pool with retry/backoff, concurrency limits, and Document Intelligence parsing."""

import logging
import os
import threading
import time
from typing import Any, Optional

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

    def __init__(
        self,
        db_manager: DatabaseManager,
        max_workers: int = DEFAULT_MAX_WORKERS,
        embedding_engine: Optional[Any] = None,
    ):
        self.db = db_manager
        self.queue = JobQueue(db_manager)
        self.max_workers = max_workers
        self.threads = []
        self._running = False
        self._paused = False
        self._lock = threading.Lock()
        self.chunker = HierarchicalChunker()
        self._embedding_engine = embedding_engine

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
                    from app.retrieval.vector_store import SqliteVecStore
                    vec_store = SqliteVecStore(conn)
                    vec_store.delete_by_file_id(file_id)
                    repo.delete_chunks_by_file(file_id)
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
                    # Non-parseable or unsupported format -> complete hashing, skip chunking truthfully
                    is_image = (mime_type and mime_type.startswith("image/")) or file_path.lower().endswith(
                        (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".ico", ".tiff")
                    )
                    diag_reason = (
                        "Image indexing deferred to Phase 7 (no text parser registered)"
                        if is_image
                        else "Unsupported file format (no parser registered)"
                    )
                    logger.info("File %s skipped: %s", file_path, diag_reason)

                    # Purge any stale vectors and relational chunks if file was previously indexed
                    with self.db.session() as conn:
                        repo = Repository(conn)
                        from app.retrieval.vector_store import SqliteVecStore
                        vec_store = SqliteVecStore(conn)
                        vec_store.delete_by_file_id(file_id)
                        repo.delete_chunks_by_file(file_id)

                    self.queue.complete_job(
                        job_id,
                        file_id,
                        sha256=sha256_hash,
                        final_status="SKIPPED",
                        indexing_error=diag_reason,
                    )
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
                                # Purge any stale vectors and chunks (vectors first while chunks still contain IDs)
                                from app.retrieval.vector_store import SqliteVecStore
                                vec_store = SqliteVecStore(conn)
                                vec_store.delete_by_file_id(file_id)
                                repo.delete_chunks_by_file(file_id)

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
                    vector_write_skipped_reason: Optional[str] = None
                    if chunks:
                        try:
                            dimension = self.embedding_engine.dimension
                            texts = [c.content if hasattr(c, "content") else c["content"] for c in chunks]
                            chunk_ids = [c.chunk_id if hasattr(c, "chunk_id") else c["chunk_id"] for c in chunks]
                            vectors = self.embedding_engine.embed_texts(texts)
                            vec_records = [
                                {"chunk_id": cid, "file_id": file_id, "embedding": vec}
                                for cid, vec in zip(chunk_ids, vectors)
                            ]
                        except Exception as vec_exc:
                            logger.warning("Vector embedding generation warning for file %s: %s", file_id, str(vec_exc))
                            vector_write_skipped_reason = f"Vector embedding generation warning: {str(vec_exc)}"

                    # 4. Atomic Persistence & Vector Indexing
                    with self.db.session() as conn:
                        repo = Repository(conn)
                        file_rec_current = repo.get_file_by_id(file_id)
                        if file_rec_current is None or file_rec_current.get("index_status") == "MISSING":
                            logger.info("File %s was deleted or marked missing during processing — skipping chunk persistence", file_id)
                            return
                        if not repo.is_current_processing_job(job_id, file_id):
                            # A filesystem event queued a successor while this
                            # job parsed an older snapshot.  Leave chunks/vectors
                            # and file state for that newer job to own.
                            logger.info("File %s changed during processing — skipping stale chunk persistence", file_id)
                            # Use this transaction's repository rather than
                            # opening a second SQLite write transaction.
                            repo.complete_job(job_id, file_id)
                            return

                        from app.retrieval.vector_store import SqliteVecStore
                        vec_store = SqliteVecStore(conn, dimension=dimension)

                        # A1/A3.1 Invariant: Purge existing vectors before destroying old relational chunk pointers
                        vec_store.delete_by_file_id(file_id)

                        repo.replace_file_chunks(file_id, chunks)

                        if vec_records:
                            identity = self.embedding_engine.get_identity()
                            if not vec_store.verify_index_validity(identity):
                                # The existing vector index was built with a different
                                # embedding model/version/dimension than the one active
                                # now. Writing this file's vectors into the same vec0
                                # table would silently mix incommensurable embeddings in
                                # cosine search (same-dimension model swaps produce no
                                # error otherwise). Refuse the write and surface loudly;
                                # a full corpus re-embed is required before dense search
                                # can be trusted again.
                                vector_write_skipped_reason = (
                                    "Vector write skipped: active embedding identity "
                                    f"({identity.get('provider')}:{identity.get('model_name')}:{identity.get('dimension')}d) "
                                    "differs from existing vector index. Dense search is unavailable for this file; "
                                    "a full corpus re-embed/rebuild is required."
                                )
                                logger.error(
                                    "Embedding model identity mismatch for file %s: %s",
                                    file_id,
                                    vector_write_skipped_reason,
                                )
                            else:
                                vec_store.upsert_vectors(vec_records)
                                # Record/refresh the active embedding identity so future
                                # writes (and startup checks) can detect a model change.
                                vec_store.set_index_metadata(
                                    provider=identity["provider"],
                                    model_name=identity["model_name"],
                                    model_version=identity["model_version"],
                                    dimension=identity["dimension"],
                                )


                    # 5. Mark Job Complete
                    parse_warning_msg = None
                    if (
                        hasattr(doc, "quality_assessment")
                        and doc.quality_assessment
                        and doc.quality_assessment.status == "PARSE_WARNING"
                    ):
                        parse_warning_msg = doc.quality_assessment.to_json()

                    final_error = None
                    if parse_warning_msg and vector_write_skipped_reason:
                        final_error = f"{parse_warning_msg} | {vector_write_skipped_reason}"
                    elif parse_warning_msg:
                        final_error = parse_warning_msg
                    elif vector_write_skipped_reason:
                        final_error = vector_write_skipped_reason

                    self.queue.complete_job(
                        job_id,
                        file_id,
                        sha256=sha256_hash,
                        final_status="INDEXED",
                        indexing_error=final_error,
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
                    self.queue.fail_job(job_id, file_id, str(corp_exc), permanent=True)

                except Exception as parse_exc:
                    logger.error("Parser failed on %s: %s", file_path, str(parse_exc), exc_info=True)
                    self.queue.fail_job(job_id, file_id, f"Parse failure: {str(parse_exc)}", permanent=True)

            else:
                self.queue.complete_job(job_id, file_id)

        except Exception as exc:
            logger.error("Job %s encountered unhandled error: %s", job_id, str(exc), exc_info=True)
            self.queue.fail_job(job_id, file_id, f"Unhandled error: {str(exc)}", attempts=attempts)
