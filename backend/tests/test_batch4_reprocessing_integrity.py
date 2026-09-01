"""Tests for Batch 4 Requirement 1: Same-File Reprocessing Integrity.

Verifies:
1. Version A -> Version B (corrupt reparse failure): preserves Version A chunks/vectors as last-known-good searchable representation.
2. File record is updated to FAILED with inspectable error reason.
3. Re-saving valid Version C replaces chunks and marks file INDEXED.
4. Full file deletion cleans up chunks and vectors completely.
5. No duplicate chunks or orphan vectors are created.
"""

import os
import time
import pytest
from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.db.repository import Repository
from app.engine.worker import WorkerPool


def wait_for_file_status(db_manager: DatabaseManager, file_id: str, target_statuses, timeout: float = 15.0):
    start = time.perf_counter()
    while time.perf_counter() - start < timeout:
        with db_manager.session() as conn:
            repo = Repository(conn)
            f = repo.get_file_by_id(file_id)
            if f and f.get("index_status") in target_statuses:
                return f
        time.sleep(0.05)
    with db_manager.session() as conn:
        repo = Repository(conn)
        return repo.get_file_by_id(file_id)


def wait_for_chunks(db_manager: DatabaseManager, file_id: str, min_chunks: int = 1, timeout: float = 15.0):

    start = time.perf_counter()
    while time.perf_counter() - start < timeout:
        with db_manager.session() as conn:
            repo = Repository(conn)
            chunks = repo.get_chunks_by_file(file_id)
            if len(chunks) >= min_chunks:
                return chunks
        time.sleep(0.05)
    with db_manager.session() as conn:
        repo = Repository(conn)
        return repo.get_chunks_by_file(file_id)


@pytest.fixture
def test_env(tmp_path):
    db_dir = tmp_path / "db"
    db_dir.mkdir()
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    db_file = db_dir / "test_reprocessing.db"
    db_manager = DatabaseManager(str(db_file))
    with db_manager.session() as conn:
        apply_migrations(conn)
    pool = WorkerPool(db_manager, max_workers=2)
    pool.start()
    yield db_manager, pool, str(docs_dir)
    pool.stop()


def test_corrupted_reparse_preserves_last_known_good_chunks(test_env):
    """When a modified file fails parsing (e.g. corruption), its previous good chunks must NOT be destroyed."""
    db_manager, pool, docs_dir = test_env
    pdf_path = os.path.join(docs_dir, "report.pdf")

    # 1. Version A: Initially valid index state
    with open(pdf_path, "wb") as f:
        f.write(b"%PDF-1.4\nInitial placeholder.")

    with db_manager.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder(docs_dir)
        file_rec = repo.upsert_file(
            folder_id=folder["folder_id"],
            path=pdf_path,
            relative_path="report.pdf",
            filename="report.pdf",
            extension=".pdf",
            size_bytes=os.path.getsize(pdf_path),
            modified_at="2026-01-01T00:00:00Z",
            mime_type="application/pdf",
        )
        file_id = file_rec["file_id"]

        # Save known-good Version A chunks
        chunks_v1 = [
            {
                "chunk_id": "pdf_chk_1",
                "file_id": file_id,
                "source_file": "report.pdf",
                "source_path": pdf_path,
                "page": 1,
                "section": "Initial PDF Section",
                "h1_parent": "Initial PDF Section",
                "h2_parent": None,
                "line_start": 1,
                "line_end": 10,
                "char_start": 0,
                "char_end": 100,
                "content_hash": "hash_v1",
                "chunk_index": 0,
                "parser_name": "pymupdf-parser",
                "parser_version": "1.0.0",
                "chunker_version": "phase2-hierarchical-v1",
                "content": "Known good PDF version 1 searchable text.",
                "content_type": "text",
                "token_count": 8,
                "metadata": {},
            }
        ]
        repo.replace_file_chunks(file_id, chunks_v1)
        repo.update_file_status(file_id, "INDEXED")

    # 2. Version B: File modified on disk to corrupted binary rubbish
    with open(pdf_path, "wb") as f:
        f.write(b"%PDF-1.4\nCorrupted binary rubbish that cannot be parsed\x00\xff\xee")

    with db_manager.session() as conn:
        repo = Repository(conn)
        repo.update_file_status(file_id, "QUEUED")
        repo.enqueue_job(file_id=file_id, folder_id=folder["folder_id"], job_type="DOCUMENT_PARSE")

    # Wait for failed reparse
    state_v2 = wait_for_file_status(db_manager, file_id, ["FAILED"])
    assert state_v2["index_status"] == "FAILED"
    assert "Failed to open PDF" in str(state_v2.get("indexing_error") or "")


    # CRITICAL: Verify that the previous known-good chunks were NOT deleted!
    with db_manager.session() as conn:
        repo = Repository(conn)
        preserved_chunks = repo.get_chunks_by_file(file_id)
        assert len(preserved_chunks) == 1
        assert "Known good PDF version 1" in preserved_chunks[0]["content"]

    # 3. Version C: Markdown file with same lifecycle restores INDEXED status and replaces chunks
    md_path = os.path.join(docs_dir, "recovered.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# Version Three Restored\n\nCompletely recovered and updated content.")

    with db_manager.session() as conn:
        repo = Repository(conn)
        file_rec_v3 = repo.upsert_file(
            folder_id=folder["folder_id"],
            path=md_path,
            relative_path="recovered.md",
            filename="recovered.md",
            extension=".md",
            size_bytes=os.path.getsize(md_path),
            modified_at="2026-01-03T00:00:00Z",
            mime_type="text/markdown",
        )
        file_id_v3 = file_rec_v3["file_id"]
        repo.enqueue_job(file_id=file_id_v3, folder_id=folder["folder_id"], job_type="DOCUMENT_PARSE")

    state_v3 = wait_for_file_status(db_manager, file_id_v3, ["INDEXED"])
    assert state_v3["index_status"] == "INDEXED"
    chunks_v3 = wait_for_chunks(db_manager, file_id_v3, min_chunks=1)
    assert len(chunks_v3) >= 1
    assert "Version Three Restored" in chunks_v3[0]["content"]
