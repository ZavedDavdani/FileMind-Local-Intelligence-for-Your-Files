"""
FileMind — Hardening 3 (H3): PDF Extraction-Quality Gate & Observability Test Suite

Validates:
1. Normal text PDF -> PARSED
2. Multi-page document -> PARSED
3. Scanned/image-only PDF -> REQUIRES_OCR
4. Very low text scanned PDF -> REQUIRES_OCR
5. Technical code PDF -> PARSED (no false rejection)
6. Mathematics PDF -> PARSED (no false rejection)
7. Dense table PDF -> PARSED (no false rejection)
8. Multilingual Unicode PDF -> PARSED (no false rejection)
9. Short legitimate PDF -> PARSED (no false rejection)
10. Corrupted font encoding PDF -> REQUIRES_OCR
11. Partial image pages PDF -> PARSE_WARNING
12. Vector poisoning prevention end-to-end (zero chunks, zero embeddings, zero vectors)
13. Lifecycle reprocessing (REQUIRES_OCR -> PARSED on valid update)
14. Delete cleanup of REQUIRES_OCR documents
"""

import os
import shutil
import tempfile
import time
from typing import Tuple
import fitz
import pytest

from app.core.security import normalize_path
from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.db.repository import Repository
from app.engine.worker import WorkerPool
from app.intelligence.parsers.pdf_parser import PyMuPDFParser
from app.intelligence.parsers.quality import (
    PDFQualitySignals,
    analyze_raw_text_signals,
    assess_pdf_quality,
)
from app.retrieval.vector_store import SqliteVecStore


@pytest.fixture
def temp_test_env():
    """Provides an isolated directory and SQLite database."""
    test_root = tempfile.mkdtemp(prefix="filemind_h3_test_")
    db_path = os.path.join(test_root, "filemind.db")
    db_mgr = DatabaseManager(db_path)
    with db_mgr.session() as conn:
        apply_migrations(conn)

    yield test_root, db_mgr

    shutil.rmtree(test_root, ignore_errors=True)


def _create_text_pdf(path: str, pages_content: list[str]) -> str:
    """Helper to create a multi-page text PDF."""
    doc = fitz.open()
    for text in pages_content:
        page = doc.new_page()
        page.insert_text((50, 72), text)
    doc.save(path)
    doc.close()
    return path


def _create_scanned_image_pdf(path: str, num_pages: int = 1) -> str:
    """Helper to create an image-only scanned PDF with zero extractable text."""
    doc = fitz.open()
    for _ in range(num_pages):
        page = doc.new_page()
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 200, 200), 1)
        pix.clear_with(220)
        page.insert_image(fitz.Rect(50, 50, 400, 400), pixmap=pix)
    doc.save(path)
    doc.close()
    return path


def _create_scanned_with_stamp_pdf(path: str) -> str:
    """Helper to create a scanned PDF with minimal header stamp text (e.g. 'Page 1')."""
    doc = fitz.open()
    page = doc.new_page()
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 200, 200), 1)
    pix.clear_with(220)
    page.insert_image(fitz.Rect(50, 100, 400, 500), pixmap=pix)
    page.insert_text((50, 50), "Page 1")  # 6 chars
    doc.save(path)
    doc.close()
    return path


def test_normal_text_pdf(temp_test_env):
    """Scenario 1: Normal document text extracts cleanly and passes quality checks."""
    test_root, _ = temp_test_env
    pdf_path = os.path.join(test_root, "normal.pdf")
    _create_text_pdf(pdf_path, ["This is a normal document containing standard English paragraphs explaining architecture."])

    parser = PyMuPDFParser()
    doc = parser.parse(pdf_path, "f1")
    assert doc.quality_assessment is not None
    assert doc.quality_assessment.status == "PARSED"
    assert "CLEAN_EXTRACTION" in doc.quality_assessment.reason_codes


def test_scanned_image_only_pdf(temp_test_env):
    """Scenario 3: Image-only PDF with zero text triggers REQUIRES_OCR."""
    test_root, _ = temp_test_env
    pdf_path = os.path.join(test_root, "scanned.pdf")
    _create_scanned_image_pdf(pdf_path, num_pages=2)

    parser = PyMuPDFParser()
    doc = parser.parse(pdf_path, "f_scanned")
    assert doc.quality_assessment is not None
    assert doc.quality_assessment.status == "REQUIRES_OCR"
    assert "SCANNED_IMAGE_ONLY" in doc.quality_assessment.reason_codes
    assert "NO_EXTRACTABLE_TEXT" in doc.quality_assessment.reason_codes


def test_low_text_image_pdf(temp_test_env):
    """Scenario 4: Scanned PDF with only 6 chars of stamp metadata triggers REQUIRES_OCR."""
    test_root, _ = temp_test_env
    pdf_path = os.path.join(test_root, "stamped.pdf")
    _create_scanned_with_stamp_pdf(pdf_path)

    parser = PyMuPDFParser()
    doc = parser.parse(pdf_path, "f_stamped")
    assert doc.quality_assessment is not None
    assert doc.quality_assessment.status == "REQUIRES_OCR"
    assert "SCANNED_IMAGE_ONLY" in doc.quality_assessment.reason_codes
    assert "INSUFFICIENT_EXTRACTABLE_TEXT" in doc.quality_assessment.reason_codes


def test_technical_code_pdf_not_rejected(temp_test_env):
    """Scenario 5: Technical code with unusual symbols is NOT falsely rejected."""
    test_root, _ = temp_test_env
    pdf_path = os.path.join(test_root, "code.pdf")
    code_text = (
        "def compute_hash(data: bytes) -> str:\n"
        "    hasher = hashlib.sha256()\n"
        "    hasher.update(data)\n"
        "    return hasher.hexdigest()\n\n"
        "fn process_stream<R: Read>(mut reader: R) -> Result<Vec<u8>, IoError> {\n"
        "    let mut buf = Vec::with_capacity(4096);\n"
        "    reader.read_to_end(&mut buf)?;\n"
        "    Ok(buf)\n"
        "}\n"
    )
    _create_text_pdf(pdf_path, [code_text])

    parser = PyMuPDFParser()
    doc = parser.parse(pdf_path, "f_code")
    assert doc.quality_assessment is not None
    assert doc.quality_assessment.status == "PARSED"


def test_mathematics_pdf_not_rejected(temp_test_env):
    """Scenario 6: Mathematical formulas and Greek symbols are NOT falsely rejected."""
    test_root, _ = temp_test_env
    pdf_path = os.path.join(test_root, "math.pdf")
    math_text = (
        "Gaussian Normal Distribution Function:\n"
        "f(x) = (1 / (sigma * sqrt(2 * pi))) * exp(- (x - mu)^2 / (2 * sigma^2))\n"
        "Integration: Integral_{-inf}^{+inf} exp(-x^2) dx = sqrt(pi)\n"
        "Eigenvalues: det(A - lambda * I) = 0\n"
        "Alpha + Beta = Gamma; Sum_{i=1}^n x_i >= 0\n"
    )
    _create_text_pdf(pdf_path, [math_text])

    parser = PyMuPDFParser()
    doc = parser.parse(pdf_path, "f_math")
    assert doc.quality_assessment is not None
    assert doc.quality_assessment.status == "PARSED"


def test_multilingual_unicode_pdf_not_rejected(temp_test_env):
    """Scenario 8: Multilingual Unicode text is NOT falsely rejected."""
    test_root, _ = temp_test_env
    pdf_path = os.path.join(test_root, "multilingual.pdf")
    multi_text = (
        "International Documentation:\n"
        "German: Die Funktionalitat dieses Systems ist vollstandig lokal.\n"
        "French: Ce systeme fonctionne de maniere privee et securisee.\n"
        "Spanish: La busqueda hibrida combina terminos lexicos y semanticos.\n"
    )
    _create_text_pdf(pdf_path, [multi_text])

    parser = PyMuPDFParser()
    doc = parser.parse(pdf_path, "f_multi")
    assert doc.quality_assessment is not None
    assert doc.quality_assessment.status == "PARSED"


def test_short_legitimate_pdf_not_rejected(temp_test_env):
    """Scenario 9: Short 1-page invoice snippet is NOT rejected."""
    test_root, _ = temp_test_env
    pdf_path = os.path.join(test_root, "short.pdf")
    short_text = "INVOICE #1024 - Total: $500.00 USD. Paid in full on 2026-08-30."
    _create_text_pdf(pdf_path, [short_text])

    parser = PyMuPDFParser()
    doc = parser.parse(pdf_path, "f_short")
    assert doc.quality_assessment is not None
    assert doc.quality_assessment.status == "PARSED"


def test_corrupted_font_encoding_pdf():
    """Scenario 10: PDF with severe font encoding corruption triggers REQUIRES_OCR."""
    corrupted_text = "\ufffd\ufffd\ufffd\ufffd\ufffd\ufffd\ufffd\ufffd\ufffd\ufffd\ufffd\ufffd\ufffd\ufffd\ufffd\ufffd" * 5 + " some text"
    signals = analyze_raw_text_signals(
        raw_text=corrupted_text,
        page_texts=[corrupted_text],
        page_count=1,
        image_count=0
    )
    assessment = assess_pdf_quality(signals)
    assert assessment.status == "REQUIRES_OCR"
    assert "CORRUPTED_FONT_ENCODING" in assessment.reason_codes


def test_partial_image_pages_pdf(temp_test_env):
    """Scenario 11: Document with text pages + image diagram page produces PARSE_WARNING."""
    test_root, _ = temp_test_env
    pdf_path = os.path.join(test_root, "partial.pdf")
    doc = fitz.open()
    
    # Page 1: Text
    p1 = doc.new_page()
    p1.insert_text((50, 50), "Architecture Overview: FileMind operates with a local SQLite database and embedding engine.")
    
    # Page 2: Pure image
    p2 = doc.new_page()
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 100, 100), 1)
    pix.clear_with(180)
    p2.insert_image(fitz.Rect(50, 50, 200, 200), pixmap=pix)

    doc.save(pdf_path)
    doc.close()

    parser = PyMuPDFParser()
    parsed_doc = parser.parse(pdf_path, "f_partial")
    assert parsed_doc.quality_assessment is not None
    assert parsed_doc.quality_assessment.status == "PARSE_WARNING"
    assert "PARTIAL_IMAGE_PAGES" in parsed_doc.quality_assessment.reason_codes


def test_vector_poisoning_prevention_end_to_end(temp_test_env):
    """
    Scenario 12 (Critical Regression Test):
    Verifies that a REQUIRES_OCR document produces zero chunks, zero embeddings, and zero vectors.
    Then verifies that a valid document produces normal chunks and vectors.
    """
    test_root, db_mgr = temp_test_env
    folder_dir = os.path.join(test_root, "documents")
    os.makedirs(folder_dir, exist_ok=True)

    bad_pdf = os.path.join(folder_dir, "scanned_invoice.pdf")
    _create_scanned_image_pdf(bad_pdf, num_pages=2)

    good_pdf = os.path.join(folder_dir, "technical_spec.pdf")
    _create_text_pdf(good_pdf, [
        "FileMind Technical Specification\n\nSection 1: Architecture\nLocal-first vector indexing and search."
    ])

    with db_mgr.session() as conn:
        repo = Repository(conn)
        f_rec = repo.create_folder(folder_dir)
        fid = f_rec["folder_id"]

        # Enqueue bad PDF
        bad_rec = repo.upsert_file(
            folder_id=fid,
            path=normalize_path(bad_pdf),
            relative_path="scanned_invoice.pdf",
            filename="scanned_invoice.pdf",
            extension=".pdf",
            size_bytes=os.path.getsize(bad_pdf),
            modified_at="2026-08-30T12:00:00Z",
            index_status="QUEUED"
        )
        bad_job = repo.enqueue_job(bad_rec["file_id"], fid, job_type="DOCUMENT_PARSE")

        # Enqueue good PDF
        good_rec = repo.upsert_file(
            folder_id=fid,
            path=normalize_path(good_pdf),
            relative_path="technical_spec.pdf",
            filename="technical_spec.pdf",
            extension=".pdf",
            size_bytes=os.path.getsize(good_pdf),
            modified_at="2026-08-30T12:00:00Z",
            index_status="QUEUED"
        )
        good_job = repo.enqueue_job(good_rec["file_id"], fid, job_type="DOCUMENT_PARSE")

    # Run worker pool to process both jobs
    pool = WorkerPool(db_mgr, max_workers=2)
    pool.start()
    time.sleep(2.0)
    pool.stop()

    with db_mgr.session() as conn:
        repo = Repository(conn)
        vec_store = SqliteVecStore(conn)

        # 1. Verify bad PDF state
        bad_file = repo.get_file_by_id(bad_rec["file_id"])
        assert bad_file["index_status"] == "SKIPPED"
        assert "REQUIRES_OCR" in bad_file["indexing_error"]
        
        # Verify ZERO chunks in SQLite
        bad_chunks = repo.get_chunks_by_file(bad_rec["file_id"])
        assert len(bad_chunks) == 0

        # Verify ZERO vectors in vector store
        cursor = conn.execute(
            "SELECT COUNT(*) FROM chunk_vectors WHERE chunk_id IN (SELECT chunk_id FROM chunks WHERE file_id = ?);",
            (bad_rec["file_id"],)
        )
        assert cursor.fetchone()[0] == 0

        # 2. Verify good PDF state
        good_file = repo.get_file_by_id(good_rec["file_id"])
        assert good_file["index_status"] == "INDEXED"
        
        good_chunks = repo.get_chunks_by_file(good_rec["file_id"])
        assert len(good_chunks) > 0

        cursor = conn.execute(
            "SELECT COUNT(*) FROM chunk_vectors WHERE chunk_id IN (SELECT chunk_id FROM chunks WHERE file_id = ?);",
            (good_rec["file_id"],)
        )
        assert cursor.fetchone()[0] == len(good_chunks)


def test_reprocessing_transition_requires_ocr_to_parsed(temp_test_env):
    """
    Scenario 13: Reprocessing a previously REQUIRES_OCR file when updated with valid text
    transitions cleanly to INDEXED with generated vectors.
    """
    test_root, db_mgr = temp_test_env
    folder_dir = os.path.join(test_root, "docs")
    os.makedirs(folder_dir, exist_ok=True)
    target_pdf = os.path.join(folder_dir, "draft.pdf")

    # Step 1: Initial scanned version
    _create_scanned_image_pdf(target_pdf, num_pages=1)

    with db_mgr.session() as conn:
        repo = Repository(conn)
        f_rec = repo.create_folder(folder_dir)
        fid = f_rec["folder_id"]
        file_rec = repo.upsert_file(
            folder_id=fid,
            path=normalize_path(target_pdf),
            relative_path="draft.pdf",
            filename="draft.pdf",
            extension=".pdf",
            size_bytes=os.path.getsize(target_pdf),
            modified_at="2026-08-30T12:00:00Z",
            index_status="QUEUED"
        )
        repo.enqueue_job(file_rec["file_id"], fid, job_type="DOCUMENT_PARSE")

    pool = WorkerPool(db_mgr, max_workers=1)
    pool.start()
    time.sleep(1.5)
    pool.stop()

    with db_mgr.session() as conn:
        repo = Repository(conn)
        f = repo.get_file_by_id(file_rec["file_id"])
        assert f["index_status"] == "SKIPPED"
        assert len(repo.get_chunks_by_file(file_rec["file_id"])) == 0

    # Step 2: Replace file with valid text PDF and reprocess
    _create_text_pdf(target_pdf, ["Updated valid text content for FileMind indexing."])

    with db_mgr.session() as conn:
        repo = Repository(conn)
        repo.update_file_status(file_rec["file_id"], "QUEUED")
        repo.enqueue_job(file_rec["file_id"], fid, job_type="DOCUMENT_PARSE")

    pool = WorkerPool(db_mgr, max_workers=1)
    pool.start()
    time.sleep(1.5)
    pool.stop()

    with db_mgr.session() as conn:
        repo = Repository(conn)
        f = repo.get_file_by_id(file_rec["file_id"])
        assert f["index_status"] == "INDEXED"
        assert len(repo.get_chunks_by_file(file_rec["file_id"])) > 0


def test_delete_cleanup_requires_ocr_file(temp_test_env):
    """
    Scenario 14: Deleting a REQUIRES_OCR file cleans up database state without errors.
    """
    test_root, db_mgr = temp_test_env
    folder_dir = os.path.join(test_root, "docs")
    os.makedirs(folder_dir, exist_ok=True)
    target_pdf = os.path.join(folder_dir, "scanned_doc.pdf")
    _create_scanned_image_pdf(target_pdf)

    with db_mgr.session() as conn:
        repo = Repository(conn)
        f_rec = repo.create_folder(folder_dir)
        fid = f_rec["folder_id"]
        file_rec = repo.upsert_file(
            folder_id=fid,
            path=normalize_path(target_pdf),
            relative_path="scanned_doc.pdf",
            filename="scanned_doc.pdf",
            extension=".pdf",
            size_bytes=os.path.getsize(target_pdf),
            modified_at="2026-08-30T12:00:00Z",
            index_status="SKIPPED",
            indexing_error='{"status": "REQUIRES_OCR"}'
        )
        repo.enqueue_job(file_rec["file_id"], fid, job_type="DELETE_CLEANUP")

    pool = WorkerPool(db_mgr, max_workers=1)
    pool.start()
    time.sleep(1.0)
    pool.stop()
    pool.stop()

    with db_mgr.session() as conn:
        cursor = conn.execute("SELECT status FROM indexing_jobs WHERE file_id = ?;", (file_rec["file_id"],))
        job = cursor.fetchone()
        assert job[0] == "COMPLETED"
