import logging
import os
import shutil
import tempfile
import pytest

from app.core.logging_config import SensitiveDataFilter, redact_sensitive_text
from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.db.repository import Repository
from app.engine.queue import JobQueue
from app.engine.worker import WorkerPool
from app.intelligence.chunker.hierarchical import (
    HierarchicalChunker,
    split_oversized_table,
)
from app.intelligence.models import Document, DocumentElement, ElementType


def test_image_and_unsupported_files_truthful_skipped_status():
    """
    Verifies that unsupported image files (e.g. .png, .jpg) and unsupported formats
    are NOT falsely marked as INDEXED, but truthfully marked as SKIPPED with a
    diagnostic reason, creating 0 chunks and 0 vector records.
    """
    tmp_dir = tempfile.mkdtemp(prefix="filemind_img_test_")
    db_path = os.path.join(tmp_dir, "test.db")
    db = DatabaseManager(db_path=db_path)
    with db.session() as conn:
        apply_migrations(conn)

    # Create dummy image file
    img_path = os.path.join(tmp_dir, "sample_diagram.png")
    with open(img_path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + b"\x00" * 50)

    with db.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder(tmp_dir, recursive=True, integrity_mode="NORMAL")
        file_rec = repo.upsert_file(
            folder_id=folder["folder_id"],
            path=img_path,
            relative_path="sample_diagram.png",
            filename="sample_diagram.png",
            extension=".png",
            size_bytes=os.path.getsize(img_path),
            modified_at="2026-08-30T12:00:00Z",
            index_status="QUEUED",
        )
        file_id = file_rec["file_id"]
        job = repo.enqueue_job(file_id=file_id, folder_id=folder["folder_id"])
        job_id = job["job_id"]

    # Process job using WorkerPool logic
    pool = WorkerPool(db, max_workers=1)
    claimed_job = pool.queue.claim_job()
    assert claimed_job is not None
    assert claimed_job["job_id"] == job_id

    pool._process_job(claimed_job)

    # Verify final status in repository
    with db.session() as conn:
        repo = Repository(conn)
        updated_file = repo.get_file_by_id(file_id)
        assert updated_file is not None
        # Must be SKIPPED, NEVER INDEXED
        assert updated_file["index_status"] == "SKIPPED"
        assert "Phase 7" in (updated_file.get("indexing_error") or "")

        # Verify 0 chunks were created
        cur = conn.execute("SELECT COUNT(*) FROM chunks WHERE file_id = ?;", (file_id,))
        count = cur.fetchone()[0]
        assert count == 0

    shutil.rmtree(tmp_dir, ignore_errors=True)


def test_oversized_table_splitting_and_header_preservation():
    """
    Verifies that tables exceeding max_chunk_chars are deterministically split
    into bounded slices while preserving markdown table headers on every slice.
    """
    header = "| Col A | Col B | Col C |\n| --- | --- | --- |"
    # Create a 6,000 character table (approx 120 rows)
    rows = [f"| Data Row {i:03d} Alpha | Data Row {i:03d} Beta | Data Row {i:03d} Gamma |" for i in range(120)]
    large_table_text = header + "\n" + "\n".join(rows)

    table_elem = DocumentElement(
        element_id="elem_tbl_1",
        element_type=ElementType.TABLE,
        text=large_table_text,
        page_number=1,
        line_start=1,
        line_end=122,
        char_start=0,
        char_end=len(large_table_text),
    )

    chunker = HierarchicalChunker(target_chunk_chars=1500, max_chunk_chars=3000)
    slices = split_oversized_table(table_elem, max_chunk_chars=3000, target_chunk_chars=1500)

    assert len(slices) > 1
    for s in slices:
        assert s.element_type == ElementType.TABLE
        assert len(s.text) <= 3000
        # Every slice must preserve the table header
        assert s.text.startswith("| Col A | Col B | Col C |")

    # Verify through full Document chunking
    doc = Document(
        file_id="doc_table_123",
        source_path="C:\\test\\large_table.md",
        filename="large_table.md",
        mime_type="text/markdown",
        elements=[table_elem],
    )
    chunks = chunker.chunk_document(doc)
    assert len(chunks) == len(slices)
    assert all(c.content_type == "table" for c in chunks)
    assert all(len(c.content) <= 3000 for c in chunks)


def test_logging_sensitive_data_redaction():
    """
    Verifies that SensitiveDataFilter and redact_sensitive_text deterministically
    redact auth tokens, API keys, passwords, and secret assignments while preserving
    ordinary log diagnostics and paths.
    """
    # 1. Bearer Token
    raw1 = "Incoming request with Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.secret"
    red1 = redact_sensitive_text(raw1)
    assert "Bearer [REDACTED]" in red1
    assert "eyJhbGci" not in red1

    # 2. OpenAI / Gemini sk- key
    raw2 = "Loaded provider with key sk-1234567890abcdef1234567890"
    red2 = redact_sensitive_text(raw2)
    assert "sk-[REDACTED]" in red2
    assert "1234567890" not in red2

    # 3. Password / secret assignment
    raw3 = "Database connection: user=admin password=MySecretPassword123 host=localhost"
    red3 = redact_sensitive_text(raw3)
    assert "password=[REDACTED]" in red3
    assert "MySecretPassword123" not in red3

    # 4. Standard path remains intact
    raw4 = "Indexed file at C:\\dev\\FileMind\\documents\\report.pdf successfully"
    red4 = redact_sensitive_text(raw4)
    assert red4 == raw4


def test_normal_small_table_remains_single_chunk():
    """
    Verifies that a standard small table (e.g. 300 chars) is not split and remains
    a single chunk.
    """
    small_table = "| Name | Role |\n| --- | --- |\n| Alice | Admin |\n| Bob | User |"
    elem = DocumentElement(element_id="elem_small_tbl", element_type=ElementType.TABLE, text=small_table)
    chunker = HierarchicalChunker(target_chunk_chars=1500, max_chunk_chars=3000)

    doc = Document(
        file_id="doc_small_table",
        source_path="C:\\test\\small.md",
        filename="small.md",
        mime_type="text/markdown",
        elements=[elem],
    )
    chunks = chunker.chunk_document(doc)
    assert len(chunks) == 1
    assert chunks[0].content == small_table
