"""Tests for Batch A3.1: Reprocessing Vector Integrity & Chunker Version Migration.

Verifies:
1. Reprocessing an indexed file with changed chunk IDs completely purges old vectors (zero orphan vectors).
2. Failure during vector purge rolls back transaction, preserving previous known-good chunks and vectors.
3. Unchanged files on disk with stale CHUNKER_VERSION ("phase2-hierarchical-v1") are detected as modified by FilesystemScanner and reprocessed.
4. v1 -> v2 chunker migration updates stored chunker_version and replaces old chunk IDs without leaving stale vectors.
5. Active vectors in chunk_vectors correspond 1-to-1 with active records in chunks table.
6. Repeated reprocessing is deterministic and idempotent.
"""

import os
import tempfile
import unittest.mock as mock
import pytest

from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.db.repository import Repository
from app.engine.discovery import FilesystemScanner
from app.engine.queue import JobQueue
from app.engine.worker import WorkerPool
from app.intelligence.chunker.hierarchical import CHUNKER_VERSION
from app.retrieval.vector_store import SqliteVecStore


def test_1_reprocessing_purges_old_vectors_and_leaves_no_orphans():
    """Verifies that reprocessing a file with new chunk IDs completely removes old vectors from chunk_vectors."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_dir = os.path.join(tmp_dir, "db")
        docs_dir = os.path.join(tmp_dir, "docs")
        os.makedirs(db_dir, exist_ok=True)
        os.makedirs(docs_dir, exist_ok=True)

        db_path = os.path.join(db_dir, "test_reprocess.db")
        db = DatabaseManager(db_path)
        queue = JobQueue(db)
        worker = WorkerPool(db)

        # 1. Initial indexing of document
        doc_path = os.path.join(docs_dir, "doc.txt")
        with open(doc_path, "w", encoding="utf-8") as f:
            f.write("Initial version 1 content with several paragraphs.\n\nParagraph 2 of version 1.")

        with db.session() as conn:
            apply_migrations(conn)
            repo = Repository(conn)
            folder = repo.create_folder(docs_dir)
            fid = folder["folder_id"]

            f_rec = repo.upsert_file(
                folder_id=fid,
                path=doc_path,
                relative_path="doc.txt",
                filename="doc.txt",
                extension=".txt",
                size_bytes=os.path.getsize(doc_path),
                modified_at="2026-01-01T00:00:00Z",
                file_id="f_doc_1",
            )
            repo.enqueue_job(file_id="f_doc_1", folder_id=fid, job_type="CHUNK_GENERATION")

        claimed = queue.claim_job()
        assert claimed is not None
        worker._process_job(claimed)

        # Verify initial chunks and vectors
        with db.session() as conn:
            repo = Repository(conn)
            vec_store = SqliteVecStore(conn, dimension=384)
            initial_chunks = repo.get_chunks_by_file("f_doc_1")
            initial_chunk_ids = {c["chunk_id"] for c in initial_chunks}
            assert len(initial_chunks) >= 1
            assert vec_store.count() == len(initial_chunks)

            # Check all vectors match initial chunk IDs
            cursor = conn.execute("SELECT chunk_id FROM chunk_vectors;")
            vector_chunk_ids = {r[0] for r in cursor.fetchall()}
            assert vector_chunk_ids == initial_chunk_ids

        # 2. Modify document on disk (triggering new content, new hashes, new chunk IDs)
        with open(doc_path, "w", encoding="utf-8") as f:
            f.write("# Updated Title\n\nCompletely different version 2 text with new headings and paragraphs.")

        with db.session() as conn:
            repo = Repository(conn)
            repo.upsert_file(
                folder_id=fid,
                path=doc_path,
                relative_path="doc.txt",
                filename="doc.txt",
                extension=".txt",
                size_bytes=os.path.getsize(doc_path),
                modified_at="2026-01-02T00:00:00Z",
                file_id="f_doc_1",
                index_status="QUEUED",
            )
            repo.enqueue_job(file_id="f_doc_1", folder_id=fid, job_type="CHUNK_GENERATION")

        claimed2 = queue.claim_job()
        assert claimed2 is not None
        worker._process_job(claimed2)

        # 3. Assert old vectors are completely purged and active vectors match new chunks exactly
        with db.session() as conn:
            repo = Repository(conn)
            vec_store = SqliteVecStore(conn, dimension=384)
            updated_chunks = repo.get_chunks_by_file("f_doc_1")
            updated_chunk_ids = {c["chunk_id"] for c in updated_chunks}

            # New chunk IDs must be distinct from old chunk IDs
            assert updated_chunk_ids.isdisjoint(initial_chunk_ids)

            # Vector count in chunk_vectors must equal active chunks count
            assert vec_store.count() == len(updated_chunks)

            # Every vector in chunk_vectors must correspond to an active chunk ID
            cursor = conn.execute("SELECT chunk_id FROM chunk_vectors;")
            all_vector_ids = {r[0] for r in cursor.fetchall()}
            assert all_vector_ids == updated_chunk_ids

            # Explicit check for 0 orphan vectors
            cursor = conn.execute("""
                SELECT COUNT(*) FROM chunk_vectors
                WHERE chunk_id NOT IN (SELECT chunk_id FROM chunks);
            """)
            orphan_count = cursor.fetchone()[0]
            assert orphan_count == 0


def test_2_vector_purge_failure_rolls_back_and_preserves_old_state():
    """Verifies that if vector purge fails during reprocessing, transaction rolls back preserving old chunks and vectors."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_dir = os.path.join(tmp_dir, "db")
        docs_dir = os.path.join(tmp_dir, "docs")
        os.makedirs(db_dir, exist_ok=True)
        os.makedirs(docs_dir, exist_ok=True)

        db_path = os.path.join(db_dir, "test_fail_purge.db")
        db = DatabaseManager(db_path)
        queue = JobQueue(db)
        worker = WorkerPool(db)

        # 1. Initial indexing
        doc_path = os.path.join(docs_dir, "doc.txt")
        with open(doc_path, "w", encoding="utf-8") as f:
            f.write("Initial stable content.")

        with db.session() as conn:
            apply_migrations(conn)
            repo = Repository(conn)
            folder = repo.create_folder(docs_dir)
            fid = folder["folder_id"]

            f_rec = repo.upsert_file(
                folder_id=fid,
                path=doc_path,
                relative_path="doc.txt",
                filename="doc.txt",
                extension=".txt",
                size_bytes=os.path.getsize(doc_path),
                modified_at="2026-01-01T00:00:00Z",
                file_id="f_doc_fail",
            )
            repo.enqueue_job(file_id="f_doc_fail", folder_id=fid, job_type="CHUNK_GENERATION")

        claimed = queue.claim_job()
        worker._process_job(claimed)

        with db.session() as conn:
            repo = Repository(conn)
            vec_store = SqliteVecStore(conn, dimension=384)
            initial_chunks = repo.get_chunks_by_file("f_doc_fail")
            assert len(initial_chunks) >= 1
            assert vec_store.count() == len(initial_chunks)
            initial_chunk_id = initial_chunks[0]["chunk_id"]

        # 2. Modify file and simulate a failure during vector purge
        with open(doc_path, "w", encoding="utf-8") as f:
            f.write("Modified content that will fail during purge.")

        with db.session() as conn:
            repo = Repository(conn)
            repo.upsert_file(
                folder_id=fid,
                path=doc_path,
                relative_path="doc.txt",
                filename="doc.txt",
                extension=".txt",
                size_bytes=os.path.getsize(doc_path),
                modified_at="2026-01-02T00:00:00Z",
                file_id="f_doc_fail",
                index_status="QUEUED",
            )
            repo.enqueue_job(file_id="f_doc_fail", folder_id=fid, job_type="CHUNK_GENERATION")

        claimed2 = queue.claim_job()
        assert claimed2 is not None

        # Inject error into delete_by_file_id
        with mock.patch.object(SqliteVecStore, "delete_by_file_id", side_effect=RuntimeError("Simulated vector storage error")):
            worker._process_job(claimed2)

        # 3. Assert transaction rolled back: previous chunk and vector still exist untouched
        with db.session() as conn:
            repo = Repository(conn)
            vec_store = SqliteVecStore(conn, dimension=384)

            preserved_chunks = repo.get_chunks_by_file("f_doc_fail")
            assert len(preserved_chunks) == len(initial_chunks)
            assert preserved_chunks[0]["chunk_id"] == initial_chunk_id
            assert "Initial stable content" in preserved_chunks[0]["content"]

            # Vector is still present
            assert vec_store.count() == len(initial_chunks)

            # Job status recorded as failure in queue (not falsely completed)
            status_counts = repo.count_jobs_by_status()
            assert status_counts["COMPLETED"] == 1  # only initial job completed
            assert status_counts["FAILED"] == 1     # second job failed


def test_3_unchanged_file_stale_chunker_version_triggers_reprocessing():
    """Verifies that an unchanged file with stale chunker_version ('phase2-hierarchical-v1') is detected and reprocessed."""
    assert CHUNKER_VERSION == "phase2-hierarchical-v2"

    with tempfile.TemporaryDirectory() as tmp_dir:
        db_dir = os.path.join(tmp_dir, "db")
        docs_dir = os.path.join(tmp_dir, "docs")
        os.makedirs(db_dir, exist_ok=True)
        os.makedirs(docs_dir, exist_ok=True)

        db_path = os.path.join(db_dir, "test_version_scan.db")
        db = DatabaseManager(db_path)
        queue = JobQueue(db)
        worker = WorkerPool(db)

        doc_path = os.path.join(docs_dir, "unchanged.md")
        with open(doc_path, "w", encoding="utf-8") as f:
            f.write("# Heading 1\n\nContent paragraph.")

        st = os.stat(doc_path)
        from datetime import datetime, timezone
        mod_iso = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat()

        # Pre-seed DB with v1 chunker version
        with db.session() as conn:
            apply_migrations(conn)
            repo = Repository(conn)
            folder = repo.create_folder(docs_dir)
            fid = folder["folder_id"]

            file_rec = repo.upsert_file(
                folder_id=fid,
                path=doc_path,
                relative_path="unchanged.md",
                filename="unchanged.md",
                extension=".md",
                size_bytes=st.st_size,
                modified_at=mod_iso,
                mime_type="text/markdown",
                index_status="INDEXED",
                sha256="pre_seed_hash",
                file_id="f_stale_v1",
            )

            # Stale v1 chunks and vectors
            v1_chunks = [
                {
                    "chunk_id": "chk_v1_old",
                    "file_id": "f_stale_v1",
                    "source_file": "unchanged.md",
                    "source_path": doc_path,
                    "page": 1,
                    "section": "Heading 1",
                    "h1_parent": "Heading 1",
                    "content_hash": "pre_seed_hash",
                    "chunk_index": 0,
                    "parser_name": "text-code-parser",
                    "parser_version": "1.1.0",
                    "chunker_version": "phase2-hierarchical-v1",  # Stale version!
                    "content": "# Heading 1\n\nContent paragraph.",
                    "content_type": "text",
                    "token_count": 6,
                    "metadata": {},
                }
            ]
            repo.replace_file_chunks("f_stale_v1", v1_chunks)
            vec_store = SqliteVecStore(conn, dimension=384)
            vec_store.upsert_vectors([{"chunk_id": "chk_v1_old", "file_id": "f_stale_v1", "embedding": [0.1] * 384}])

            # Run filesystem scanner
            scanner = FilesystemScanner(repo)
            scan_res = scanner.scan_folder(fid)

            # Scanner must recognize chunker_version evolution and schedule reprocessing
            assert scan_res.modified_files == 1
            assert scan_res.unchanged_files == 0
            assert len(scan_res.enqueued_job_ids) == 1

        # Execute reprocessing job
        claimed = queue.claim_job()
        assert claimed is not None
        worker._process_job(claimed)

        # Assert chunks table and vector store are upgraded to v2 without stale v1 records
        with db.session() as conn:
            repo = Repository(conn)
            vec_store = SqliteVecStore(conn, dimension=384)

            v2_chunks = repo.get_chunks_by_file("f_stale_v1")
            assert len(v2_chunks) >= 1
            assert v2_chunks[0]["chunker_version"] == "phase2-hierarchical-v2"
            assert v2_chunks[0]["chunk_id"] != "chk_v1_old"

            # Old vector chk_v1_old purged completely
            cursor = conn.execute("SELECT chunk_id FROM chunk_vectors;")
            vector_ids = [r[0] for r in cursor.fetchall()]
            assert "chk_v1_old" not in vector_ids
            assert vector_ids == [v2_chunks[0]["chunk_id"]]


def test_4_repeated_reprocessing_is_deterministic_and_idempotent():
    """Verifies that repeatedly reprocessing the same file produces identical chunk IDs and vectors without drift."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_dir = os.path.join(tmp_dir, "db")
        docs_dir = os.path.join(tmp_dir, "docs")
        os.makedirs(db_dir, exist_ok=True)
        os.makedirs(docs_dir, exist_ok=True)

        db_path = os.path.join(db_dir, "test_idempotent.db")
        db = DatabaseManager(db_path)
        queue = JobQueue(db)
        worker = WorkerPool(db)

        doc_path = os.path.join(docs_dir, "stable.txt")
        with open(doc_path, "w", encoding="utf-8") as f:
            f.write("Stable deterministic text for idempotency verification.")

        with db.session() as conn:
            apply_migrations(conn)
            repo = Repository(conn)
            folder = repo.create_folder(docs_dir)
            fid = folder["folder_id"]

            repo.upsert_file(
                folder_id=fid,
                path=doc_path,
                relative_path="stable.txt",
                filename="stable.txt",
                extension=".txt",
                size_bytes=os.path.getsize(doc_path),
                modified_at="2026-01-01T00:00:00Z",
                file_id="f_idem",
            )
            repo.enqueue_job(file_id="f_idem", folder_id=fid, job_type="CHUNK_GENERATION")

        # Pass 1
        worker._process_job(queue.claim_job())

        with db.session() as conn:
            repo = Repository(conn)
            pass1_chunks = repo.get_chunks_by_file("f_idem")
            pass1_ids = [c["chunk_id"] for c in pass1_chunks]

        # Pass 2 (force reprocess)
        with db.session() as conn:
            repo = Repository(conn)
            repo.enqueue_job(file_id="f_idem", folder_id=fid, job_type="CHUNK_GENERATION")

        worker._process_job(queue.claim_job())

        with db.session() as conn:
            repo = Repository(conn)
            vec_store = SqliteVecStore(conn, dimension=384)
            pass2_chunks = repo.get_chunks_by_file("f_idem")
            pass2_ids = [c["chunk_id"] for c in pass2_chunks]

            assert pass1_ids == pass2_ids
            assert vec_store.count() == len(pass2_chunks)
            cursor = conn.execute("SELECT chunk_id FROM chunk_vectors;")
            assert [r[0] for r in cursor.fetchall()] == pass2_ids
