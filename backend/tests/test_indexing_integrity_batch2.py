"""Regression tests for Batch 2 atomic indexing transactions, stale-job safety, and purge invariant."""

import os
import sqlite3
import tempfile
import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.db.repository import Repository
from app.engine.pipeline import IndexingPipeline, IndexingPipelineResult
from app.engine.queue import JobQueue
from app.engine.worker import WorkerPool
from app.retrieval.vector_store import SqliteVecStore


@pytest.fixture
def temp_db():
    temp_dir = tempfile.mkdtemp()
    db_file = os.path.join(temp_dir, "test_indexing.db")
    db_mgr = DatabaseManager(db_file)
    with db_mgr.session() as conn:
        apply_migrations(conn)
    yield db_mgr
    # Cleanup
    try:
        if os.path.exists(db_file):
            os.remove(db_file)
        os.rmdir(temp_dir)
    except Exception:
        pass


def test_purge_file_index_invariant(temp_db):
    """Verifies purge_file_index deletes vectors first, then chunks."""
    with temp_db.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder(r"C:\test\folder")
        file_rec = repo.upsert_file(
            folder_id=folder["folder_id"],
            path=r"C:\test\folder\doc.txt",
            relative_path="doc.txt",
            filename="doc.txt",
            extension=".txt",
            size_bytes=100,
            modified_at="2026-01-01T00:00:00Z",
            sha256="hash1",
        )
        file_id = file_rec["file_id"]

        chunks = [
            {
                "chunk_id": f"chunk_{file_id}_0",
                "source_file": "doc.txt",
                "source_path": r"C:\test\folder\doc.txt",
                "content": "Sample chunk text for indexing",
                "content_hash": "chash0",
                "chunk_index": 0,
            }
        ]
        repo.replace_file_chunks(file_id, chunks)

        vec_store = SqliteVecStore(conn, dimension=384)
        dummy_vec = [0.1] * 384
        vec_store.upsert_vectors([{"chunk_id": f"chunk_{file_id}_0", "file_id": file_id, "embedding": dummy_vec}])

        assert len(repo.get_chunks_by_file(file_id)) == 1
        assert vec_store.count() == 1

        # Purge index
        purged_count = repo.purge_file_index(file_id)
        assert purged_count == 1
        assert len(repo.get_chunks_by_file(file_id)) == 0
        assert vec_store.count() == 0


def test_atomic_persistence_and_job_completion(temp_db):
    """Verifies that chunks, vectors, file status, and job status are persisted in one atomic transaction."""
    with temp_db.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder(r"C:\test\folder")
        file_rec = repo.upsert_file(
            folder_id=folder["folder_id"],
            path=r"C:\test\folder\doc.txt",
            relative_path="doc.txt",
            filename="doc.txt",
            extension=".txt",
            size_bytes=100,
            modified_at="2026-01-01T00:00:00Z",
            sha256="hash1",
        )
        file_id = file_rec["file_id"]
        job = repo.enqueue_job(file_id, folder["folder_id"], job_type="METADATA_DISCOVERY")
        job_id = job["job_id"]

        claimed = repo.claim_next_job()
        assert claimed is not None

    worker_pool = WorkerPool(temp_db)

    pipeline_result = IndexingPipelineResult(
        file_id=file_id,
        job_id=job_id,
        status="INDEXED",
        sha256="hash1",
        chunks=[
            {
                "chunk_id": f"c_{file_id}_0",
                "source_file": "doc.txt",
                "source_path": r"C:\test\folder\doc.txt",
                "content": "Hello world",
                "content_hash": "h0",
                "chunk_index": 0,
            }
        ],
        vector_records=[
            {"chunk_id": f"c_{file_id}_0", "file_id": file_id, "embedding": [0.05] * 384}
        ],
        dimension=384,
    )

    worker_pool._persist_pipeline_outcome(job_id, file_id, pipeline_result)

    with temp_db.session() as conn:
        repo = Repository(conn)
        f_rec = repo.get_file_by_id(file_id)
        assert f_rec["index_status"] == "INDEXED"
        assert len(repo.get_chunks_by_file(file_id)) == 1

        vec_store = SqliteVecStore(conn, dimension=384)
        assert vec_store.count() == 1

        jobs = repo.list_jobs(status="COMPLETED")
        assert any(j["job_id"] == job_id for j in jobs)


def test_stale_job_safety_does_not_overwrite(temp_db):
    """Verifies that a stale job finishing after a newer job does not overwrite the newer index."""
    with temp_db.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder(r"C:\test\folder")
        file_rec = repo.upsert_file(
            folder_id=folder["folder_id"],
            path=r"C:\test\folder\doc.txt",
            relative_path="doc.txt",
            filename="doc.txt",
            extension=".txt",
            size_bytes=100,
            modified_at="2026-01-01T00:00:00Z",
            sha256="hash1",
        )
        file_id = file_rec["file_id"]

        # Job A enqueued and claimed
        job_a = repo.enqueue_job(file_id, folder["folder_id"], job_type="METADATA_DISCOVERY")
        job_a_id = job_a["job_id"]
        repo.claim_next_job()

        # Job B enqueued (newer event arrives while A is running)
        job_b = repo.enqueue_job(file_id, folder["folder_id"], job_type="METADATA_DISCOVERY", job_id=str(uuid.uuid4()))
        job_b_id = job_b["job_id"]

    worker_pool = WorkerPool(temp_db)

    # Job A finishes with older chunks
    result_a = IndexingPipelineResult(
        file_id=file_id,
        job_id=job_a_id,
        status="INDEXED",
        sha256="hash_old",
        chunks=[
            {
                "chunk_id": f"c_old_{file_id}",
                "source_file": "doc.txt",
                "source_path": r"C:\test\folder\doc.txt",
                "content": "Old content from job A",
                "content_hash": "hold",
                "chunk_index": 0,
            }
        ],
        vector_records=[],
        dimension=384,
    )

    worker_pool._persist_pipeline_outcome(job_a_id, file_id, result_a)

    with temp_db.session() as conn:
        repo = Repository(conn)
        # Job A must NOT have written chunks
        assert len(repo.get_chunks_by_file(file_id)) == 0
        # File status must NOT be set to INDEXED by stale job A
        f_rec = repo.get_file_by_id(file_id)
        assert f_rec["index_status"] != "INDEXED"


def test_persistence_rollback_on_failure(temp_db):
    """Verifies SQLite rollback if an exception occurs during the persistence phase."""
    with temp_db.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder(r"C:\test\folder")
        file_rec = repo.upsert_file(
            folder_id=folder["folder_id"],
            path=r"C:\test\folder\doc.txt",
            relative_path="doc.txt",
            filename="doc.txt",
            extension=".txt",
            size_bytes=100,
            modified_at="2026-01-01T00:00:00Z",
            sha256="hash1",
        )
        file_id = file_rec["file_id"]
        job = repo.enqueue_job(file_id, folder["folder_id"], job_type="METADATA_DISCOVERY")
        job_id = job["job_id"]
        repo.claim_next_job()

    worker_pool = WorkerPool(temp_db)
    result = IndexingPipelineResult(
        file_id=file_id,
        job_id=job_id,
        status="INDEXED",
        sha256="hash1",
        chunks=[{"invalid": "broken"}],  # Will fail during insert
        dimension=384,
    )

    with pytest.raises(Exception):
        worker_pool._persist_pipeline_outcome(job_id, file_id, result)

    with temp_db.session() as conn:
        repo = Repository(conn)
        # Verify clean rollback: no orphaned chunks
        assert len(repo.get_chunks_by_file(file_id)) == 0
        f_rec = repo.get_file_by_id(file_id)
        assert f_rec["index_status"] == "PROCESSING"  # Rolled back to before persistence
