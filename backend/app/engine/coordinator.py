"""Engine coordinator: orchestrates discovery, watchers, job queues, workers, and recovery."""

import logging
import threading
import time
from typing import Any, Dict, List, Optional

from app.db.connection import DatabaseManager, db_manager
from app.db.migrations import apply_migrations
from app.db.repository import Repository
from app.engine.discovery import FilesystemScanner
from app.engine.watcher import WatcherService
from app.engine.worker import WorkerPool

logger = logging.getLogger("FileMind.Coordinator")


class EngineCoordinator:
    """High-level coordinator managing the lifecycle of the FileMind Filesystem Engine."""

    def __init__(self, db: DatabaseManager = db_manager, embedding_engine: Optional[Any] = None):
        self.db = db
        self._embedding_engine = embedding_engine
        self.worker_pool = WorkerPool(db, embedding_engine=embedding_engine)
        self.watcher_service = WatcherService(db)
        self._is_initialized = False
        self._lock = threading.Lock()

    @property
    def embedding_engine(self):
        if self._embedding_engine is not None:
            return self._embedding_engine
        from app.retrieval.embeddings import default_embedding_engine
        return default_embedding_engine

    def initialize(self):
        """Initializes database migrations, recovers stale jobs, and starts background services."""
        with self._lock:
            if self._is_initialized:
                return

            logger.info("Initializing FileMind Filesystem Engine...")
            # 1. Apply SQLite migrations
            with self.db.session() as conn:
                apply_migrations(conn)
                repo = Repository(conn)
                
                # 2. Crash Recovery: Recover any jobs left in PROCESSING
                recovered = repo.recover_stale_processing_jobs()
                if recovered > 0:
                    logger.info("Crash recovery: recovered %d interrupted jobs to PENDING", recovered)

                # 2b. Embedding index validity check: surface any embedding
                # model/version/dimension mismatch against the previously
                # recorded vector index identity as early as possible (at
                # startup), rather than only discovering it lazily the next
                # time a file happens to be written. This does not block
                # startup — dense search degradation/reindexing decisions
                # are handled by the retrieval layer and worker — but it
                # ensures the mismatch is never silent.
                try:
                    from app.retrieval.vector_store import SqliteVecStore
                    vec_store = SqliteVecStore(conn, dimension=self.embedding_engine.dimension)
                    stored_identity = vec_store.get_index_metadata()
                    if stored_identity is not None:
                        active_identity = self.embedding_engine.get_identity()
                        if not vec_store.verify_index_validity(active_identity):
                            logger.error(
                                "Embedding model mismatch detected at startup: stored vector "
                                "index identity %s does not match the currently configured "
                                "embedding model %s. Dense search results may be invalid "
                                "until the corpus is fully re-embedded.",
                                stored_identity, active_identity,
                            )
                except Exception as exc:
                    logger.warning("Embedding index validity check failed at startup: %s", str(exc))

            # 3. Start background workers & filesystem watchers
            self.worker_pool.start()
            self.watcher_service.start()
            self._is_initialized = True
            logger.info("Filesystem Engine initialized successfully")

    def shutdown(self):
        """Gracefully stops workers and watchers."""
        with self._lock:
            if not self._is_initialized:
                return
            logger.info("Shutting down Filesystem Engine...")
            self.watcher_service.stop()
            self.worker_pool.stop()
            self._is_initialized = False
            logger.info("Filesystem Engine shutdown complete")

    def scan_all_enabled_folders(self) -> Dict[str, Any]:
        """Runs recursive discovery across all registered, enabled folders."""
        results = {}
        with self.db.session() as conn:
            repo = Repository(conn)
            folders = repo.list_folders()
            scanner = FilesystemScanner(repo)

            for f in folders:
                if f["indexing_enabled"]:
                    try:
                        res = scanner.scan_folder(f["folder_id"])
                        results[f["folder_id"]] = {
                            "total_scanned": res.total_scanned,
                            "new_files": res.new_files,
                            "modified_files": res.modified_files,
                            "unchanged_files": res.unchanged_files,
                            "skipped_exclusions": res.skipped_exclusions,
                            "errors": res.errors,
                        }
                    except Exception as exc:
                        results[f["folder_id"]] = {"error": str(exc)}

        self.watcher_service.sync_watches()
        return results

    def scan_single_folder(self, folder_id: str, force_strict: bool = False) -> Dict[str, Any]:
        with self.db.session() as conn:
            repo = Repository(conn)
            scanner = FilesystemScanner(repo)
            res = scanner.scan_folder(folder_id, force_strict_rehash=force_strict)

        self.watcher_service.sync_watches()
        return {
            "total_scanned": res.total_scanned,
            "new_files": res.new_files,
            "modified_files": res.modified_files,
            "unchanged_files": res.unchanged_files,
            "skipped_exclusions": res.skipped_exclusions,
            "errors": res.errors,
        }

    def get_aggregate_status(self) -> Dict[str, Any]:
        """Calculates live progressive indexing statistics across all registered folders."""
        with self.db.session() as conn:
            repo = Repository(conn)
            file_counts = repo.count_files_by_status()
            job_counts = repo.count_jobs_by_status()
            folders = repo.list_folders()

        total = file_counts["TOTAL"]
        indexed = file_counts["INDEXED"]
        progress_pct = round((indexed / total * 100), 1) if total > 0 else 100.0

        return {
            "is_running": self.worker_pool.is_running,
            "is_paused": self.worker_pool.is_paused,
            "total_folders": len(folders),
            "total_files": total,
            "discovered": file_counts["DISCOVERED"],
            "queued": file_counts["QUEUED"] + job_counts["PENDING"],
            "processing": file_counts["PROCESSING"] + job_counts["PROCESSING"],
            "indexed": indexed,
            "failed": file_counts["FAILED"],
            "skipped": file_counts["SKIPPED"],
            "missing": file_counts["MISSING"],
            "progress_percent": progress_pct,
            "last_updated": time.time(),
        }

    def pause_indexing(self):
        self.worker_pool.pause()

    def resume_indexing(self):
        self.worker_pool.resume()

    def sync_watches(self):
        self.watcher_service.sync_watches()


# Global engine coordinator singleton
coordinator = EngineCoordinator()
