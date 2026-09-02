"""Tests for Batch A2: Corpus Encoding & PDF Integrity Hardening.

Verifies:
1. Strict shared text decoding utility (read_text_file_strictly, decode_bytes_strictly).
2. Valid UTF-8 across all supported extensions (TXT, Markdown, Python/Rust/JS code, CSV, JSON).
3. Handling of UTF-8 with BOM and legitimate Unicode replacement characters (U+FFFD).
4. Explicit rejection of invalid/undecodable byte sequences (raises CorruptedDocumentError).
5. Zero silent replacement-character corruption in indexed text.
6. Checked PDF decryption for empty passwords in PyPDFParser and PyMuPDFParser (raises EncryptedDocumentError).
7. End-to-end worker error transitions for unparseable/corrupted encoding (status FAILED, permanent).
"""

import csv
import json
import os
import tempfile
import unittest.mock as mock
import pytest

from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.db.repository import Repository
from app.engine.queue import JobQueue
from app.engine.worker import WorkerPool
from app.intelligence.parsers.base import (
    CorruptedDocumentError,
    EncryptedDocumentError,
)
from app.intelligence.parsers.decoder import (
    decode_bytes_strictly,
    read_text_file_strictly,
)
from app.intelligence.parsers.pdf_parser import PyMuPDFParser, PyPDFParser
from app.intelligence.parsers.tabular_parser import TabularParser
from app.intelligence.parsers.text_parser import TextAndCodeParser


# =============================================================================
# 1. Direct Decoder Utility Unit Tests
# =============================================================================

def test_1_decoder_utf8_with_rich_unicode():
    """Verifies that decode_bytes_strictly correctly decodes diverse Unicode without error."""
    text = "Hello 世界! Café, Fußball, 🚀, ∑(x_i), Русский язык, 日本語."
    raw_bytes = text.encode("utf-8")
    decoded = decode_bytes_strictly(raw_bytes, "test.txt")
    assert decoded == text


def test_2_decoder_utf8_bom_support():
    """Verifies that UTF-8 BOM is transparently stripped and decoded strictly."""
    text = "File with UTF-8 BOM header."
    raw_bytes = b"\xef\xbb\xbf" + text.encode("utf-8")
    decoded = decode_bytes_strictly(raw_bytes, "bom.txt")
    assert decoded == text
    assert not decoded.startswith("\ufeff")


def test_3_decoder_invalid_utf8_raises_corrupted_document_error():
    """Verifies that invalid UTF-8 byte sequences raise CorruptedDocumentError with diagnostic details."""
    # 0xFF is an invalid UTF-8 lead byte; 0xC0 is an overlong encoding
    invalid_bytes = b"Valid ASCII header \xff\xfe corrupted payload \xc0\xaf footer."
    with pytest.raises(CorruptedDocumentError) as exc_info:
        decode_bytes_strictly(invalid_bytes, "corrupted.txt")

    err_msg = str(exc_info.value)
    assert "Corrupted or invalid character encoding in 'corrupted.txt'" in err_msg
    assert "invalid UTF-8 byte sequence" in err_msg
    assert "Corpus integrity policy rejects silent replacement" in err_msg


def test_4_decoder_empty_bytes():
    """Verifies that empty bytes return an empty string without raising an exception."""
    assert decode_bytes_strictly(b"", "empty.txt") == ""


def test_5_decoder_literal_ufffd_in_valid_utf8():
    """Verifies that a file containing legitimate U+FFFD as valid UTF-8 bytes decodes cleanly."""
    text = "Legitimate replacement character: \ufffd inside valid UTF-8."
    raw_bytes = text.encode("utf-8")
    decoded = decode_bytes_strictly(raw_bytes, "literal_ufffd.txt")
    assert decoded == text
    assert "\ufffd" in decoded


def test_6_read_text_file_strictly_roundtrip():
    """Verifies file-based strict reading on temporary disk files."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        file_path = os.path.join(tmp_dir, "test.md")
        content = "# Heading\n\n- Japanese: テスト\n- Emoji: 🧠"
        with open(file_path, "wb") as f:
            f.write(content.encode("utf-8"))

        read_content = read_text_file_strictly(file_path)
        assert read_content == content


# =============================================================================
# 2. Text, Markdown & Source Code Parser Tests
# =============================================================================

def test_7_text_parser_valid_utf8_txt():
    """Verifies plain text parser decodes UTF-8 with Unicode paragraphs cleanly."""
    parser = TextAndCodeParser()
    with tempfile.TemporaryDirectory() as tmp_dir:
        file_path = os.path.join(tmp_dir, "sample.txt")
        text = "Paragraph 1 with French: déjà vu et café.\n\nParagraph 2 with German: Grüße aus München!"
        with open(file_path, "wb") as f:
            f.write(text.encode("utf-8"))

        doc = parser.parse(file_path, "file_txt_1", "text/plain")
        assert len(doc.elements) == 2
        assert "déjà vu" in doc.elements[0].text
        assert "München" in doc.elements[1].text


def test_8_text_parser_valid_utf8_markdown():
    """Verifies markdown parser preserves heading hierarchies and tables with Unicode."""
    parser = TextAndCodeParser()
    with tempfile.TemporaryDirectory() as tmp_dir:
        file_path = os.path.join(tmp_dir, "doc.md")
        md_content = (
            "# Main Title: 🚀 Project Overview\n\n"
            "## Section: Multilingual Features\n\n"
            "| Language | Greeting | Notes |\n"
            "|---|---|---|\n"
            "| Japanese | こんにちは | Non-Latin |\n"
            "| Spanish | ¡Hola! | Inverted exclamation |\n"
        )
        with open(file_path, "wb") as f:
            f.write(md_content.encode("utf-8"))

        doc = parser.parse(file_path, "file_md_1", "text/markdown")
        assert len(doc.elements) >= 3
        headings = [e for e in doc.elements if e.element_type.name == "HEADING"]
        tables = [e for e in doc.elements if e.element_type.name == "TABLE"]
        assert any("🚀 Project Overview" in h.text for h in headings)
        assert len(tables) == 1
        assert "こんにちは" in tables[0].text


def test_9_text_parser_valid_utf8_source_code():
    """Verifies source code parser handles Unicode comments and strings across languages."""
    parser = TextAndCodeParser()
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Python test
        py_path = os.path.join(tmp_dir, "module.py")
        py_code = (
            "# -*- coding: utf-8 -*-\n"
            "# Mathematical constants: π ≈ 3.14159, θ = 45°\n"
            "def calculate_area(radius: float) -> float:\n"
            "    \"\"\"Calculates circular area with Unicode symbol π.\"\"\"\n"
            "    return 3.14159 * radius ** 2\n"
        )
        with open(py_path, "wb") as f:
            f.write(py_code.encode("utf-8"))

        doc_py = parser.parse(py_path, "file_py_1", "text/x-python")
        assert len(doc_py.elements) >= 1
        assert any("calculate_area" in e.text for e in doc_py.elements)

        # Rust test
        rs_path = os.path.join(tmp_dir, "lib.rs")
        rs_code = (
            "// 🚀 Rust high-performance module\n"
            "pub fn greet(name: &str) -> String {\n"
            "    format!(\"Bonjour, {}! ✨\", name)\n"
            "}\n"
        )
        with open(rs_path, "wb") as f:
            f.write(rs_code.encode("utf-8"))

        doc_rs = parser.parse(rs_path, "file_rs_1", "text/x-rust")
        assert len(doc_rs.elements) >= 1
        assert any("Bonjour" in e.text for e in doc_rs.elements)


def test_10_text_parser_invalid_utf8_rejected():
    """Verifies that TXT/Markdown/Code containing invalid UTF-8 bytes raises CorruptedDocumentError."""
    parser = TextAndCodeParser()
    with tempfile.TemporaryDirectory() as tmp_dir:
        for ext, mime in [(".txt", "text/plain"), (".md", "text/markdown"), (".py", "text/x-python"), (".rs", "text/x-rust")]:
            file_path = os.path.join(tmp_dir, f"corrupted{ext}")
            # Invalid UTF-8 byte sequence
            with open(file_path, "wb") as f:
                f.write(b"# Corrupted document\n\x80\x81\x82 invalid continuation bytes\n")

            with pytest.raises(CorruptedDocumentError) as exc_info:
                parser.parse(file_path, f"file_err_{ext}", mime)

            assert "Corrupted or invalid character encoding" in str(exc_info.value)


# =============================================================================
# 3. Tabular (CSV & JSON) Parser Tests
# =============================================================================

def test_11_tabular_parser_valid_utf8_csv():
    """Verifies CSV parser correctly extracts Unicode headers and cells without replacement."""
    parser = TabularParser()
    with tempfile.TemporaryDirectory() as tmp_dir:
        csv_path = os.path.join(tmp_dir, "records.csv")
        csv_content = (
            "ID,City,Specialty,Rating\n"
            "1,Tokyo (東京),Ramen (ラーメン),4.9\n"
            "2,São Paulo,Feijoada,4.8\n"
            "3,Zürich,Fondue,4.7\n"
        )
        with open(csv_path, "wb") as f:
            f.write(csv_content.encode("utf-8"))

        doc = parser.parse(csv_path, "file_csv_1", "text/csv")
        assert len(doc.elements) == 1
        table_elem = doc.elements[0]
        assert table_elem.table_data is not None
        assert table_elem.table_data.headers == ["ID", "City", "Specialty", "Rating"]
        assert "東京" in table_elem.text
        assert "São Paulo" in table_elem.text
        assert "Zürich" in table_elem.text


def test_12_tabular_parser_valid_utf8_json():
    """Verifies JSON parser correctly handles nested Unicode dictionaries and arrays."""
    parser = TabularParser()
    with tempfile.TemporaryDirectory() as tmp_dir:
        json_path = os.path.join(tmp_dir, "dataset.json")
        data = [
            {"id": "rec_1", "title": "Quantum AI / 量子人工知能", "author": "Dr. Müller"},
            {"id": "rec_2", "title": "Natural Language Processing (NLP)", "author": "Émile Zola"},
        ]
        with open(json_path, "wb") as f:
            f.write(json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))

        doc = parser.parse(json_path, "file_json_1", "application/json")
        assert len(doc.elements) >= 1
        assert any("量子人工知能" in e.text for e in doc.elements)
        assert any("Dr. Müller" in e.text for e in doc.elements)


def test_13_tabular_parser_invalid_utf8_csv_rejected():
    """Verifies that CSV with corrupted/invalid UTF-8 bytes raises CorruptedDocumentError."""
    parser = TabularParser()
    with tempfile.TemporaryDirectory() as tmp_dir:
        csv_path = os.path.join(tmp_dir, "corrupted.csv")
        # Invalid byte 0xFF
        with open(csv_path, "wb") as f:
            f.write(b"Name,Age,Notes\nAlice,30,Normal\nBob,25,\xff\xfe corrupted byte\n")

        with pytest.raises(CorruptedDocumentError) as exc_info:
            parser.parse(csv_path, "file_csv_bad", "text/csv")

        assert "Corrupted or invalid character encoding" in str(exc_info.value)


def test_14_tabular_parser_invalid_utf8_json_rejected():
    """Verifies that JSON with invalid UTF-8 bytes raises CorruptedDocumentError."""
    parser = TabularParser()
    with tempfile.TemporaryDirectory() as tmp_dir:
        json_path = os.path.join(tmp_dir, "corrupted.json")
        with open(json_path, "wb") as f:
            f.write(b"{\"key\": \"value with \xc3 invalid tail\"}")

        with pytest.raises(CorruptedDocumentError) as exc_info:
            parser.parse(json_path, "file_json_bad", "application/json")

        assert "Corrupted or invalid character encoding" in str(exc_info.value)


# =============================================================================
# 4. PDF Encryption Handling Tests
# =============================================================================

def test_15_pypdf_encrypted_pdf_unsuccessful_decrypt_raises_encrypted_document_error():
    """Verifies that when pypdf reader.decrypt('') returns 0 / PasswordType.NOT_DECRYPTED, EncryptedDocumentError is raised."""
    parser = PyPDFParser()

    mock_reader = mock.MagicMock()
    mock_reader.is_encrypted = True
    # Simulate return value 0 (PasswordType.NOT_DECRYPTED)
    mock_reader.decrypt.return_value = 0

    with mock.patch("pypdf.PdfReader", return_value=mock_reader):
        with pytest.raises(EncryptedDocumentError, match="PDF is password protected or encrypted: locked.pdf"):
            parser.parse("C:/fake/path/locked.pdf", "f_locked", "application/pdf")


def test_16_pypdf_encrypted_pdf_exception_on_decrypt_raises_encrypted_document_error():
    """Verifies that when pypdf reader.decrypt('') raises an exception, EncryptedDocumentError is raised."""
    parser = PyPDFParser()

    mock_reader = mock.MagicMock()
    mock_reader.is_encrypted = True
    mock_reader.decrypt.side_effect = Exception("Wrong password")

    with mock.patch("pypdf.PdfReader", return_value=mock_reader):
        with pytest.raises(EncryptedDocumentError, match="PDF is encrypted: locked.pdf"):
            parser.parse("C:/fake/path/locked.pdf", "f_locked", "application/pdf")


def test_17_pypdf_encrypted_pdf_successful_empty_decrypt_proceeds():
    """Verifies that when pypdf reader.decrypt('') succeeds (returns truthy 1 or 2), parsing proceeds."""
    parser = PyPDFParser()

    mock_page = mock.MagicMock()
    mock_page.extract_text.return_value = "Decrypted content with empty user password."
    mock_page.images = []

    mock_reader = mock.MagicMock()
    mock_reader.is_encrypted = True
    # 1 represents PasswordType.USER_PASSWORD
    mock_reader.decrypt.return_value = 1
    mock_reader.pages = [mock_page]

    with mock.patch("pypdf.PdfReader", return_value=mock_reader):
        doc = parser.parse("C:/fake/path/unlocked.pdf", "f_unlocked", "application/pdf")
        assert len(doc.elements) >= 1
        assert "Decrypted content" in doc.elements[0].text


def test_18_pymupdf_encrypted_pdf_failure_raises_encrypted_document_error():
    """Verifies that PyMuPDF parser also raises EncryptedDocumentError when authenticate('') fails."""
    parser = PyMuPDFParser()

    mock_pdf_doc = mock.MagicMock()
    mock_pdf_doc.is_encrypted = True
    mock_pdf_doc.authenticate.return_value = 0  # 0 indicates authentication failed

    with mock.patch("fitz.open", return_value=mock_pdf_doc):
        with pytest.raises(EncryptedDocumentError, match="PDF is password protected or encrypted: secret.pdf"):
            parser.parse("C:/fake/path/secret.pdf", "f_secret", "application/pdf")


# =============================================================================
# 5. Worker Ingestion & Permanent Error State Transition Tests
# =============================================================================

def test_19_worker_corrupted_encoding_document_fails_permanently():
    """Verifies end-to-end that an undecodable document processed by WorkerPool transitions to FAILED without infinite retry."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "test_encoding.db")
        db = DatabaseManager(db_path)
        queue = JobQueue(db)
        worker = WorkerPool(db)

        with db.session() as conn:
            apply_migrations(conn)
            repo = Repository(conn)
            folder = repo.create_folder(tmp_dir)
            fid = folder["folder_id"]

            bad_file = os.path.join(tmp_dir, "bad_utf8.txt")
            with open(bad_file, "wb") as f:
                f.write(b"Hello \xff\xfe corrupted bytes")

            f_rec = repo.upsert_file(
                folder_id=fid,
                path=bad_file,
                relative_path="bad_utf8.txt",
                filename="bad_utf8.txt",
                extension=".txt",
                size_bytes=os.path.getsize(bad_file),
                modified_at="2026-09-02T11:00:00Z",
                file_id="f_bad_1",
            )
            job = repo.enqueue_job(file_id="f_bad_1", folder_id=fid, job_type="CHUNK_GENERATION")

        claimed = queue.claim_job()
        assert claimed is not None

        worker._process_job(claimed)

        with db.session() as conn:
            repo = Repository(conn)
            file_record = repo.get_file_by_id("f_bad_1")
            assert file_record["index_status"] == "FAILED"
            assert "Corrupted or invalid character encoding" in file_record["indexing_error"]
            assert "invalid UTF-8 byte sequence" in file_record["indexing_error"]


            status_counts = repo.count_jobs_by_status()
            assert status_counts["FAILED"] == 1
            assert status_counts["COMPLETED"] == 0
            assert status_counts["PENDING"] == 0

            # No chunks or vectors created
            assert len(repo.get_chunks_by_file("f_bad_1")) == 0
