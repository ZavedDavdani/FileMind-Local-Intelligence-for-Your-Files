"""Tests for Pre-Phase-5 Audit Cleanup.

Verifies:
1. Item 1: SearchRequest.quality schema default ("fast"), API validation, and combinations.
2. Item 2: ChunkProvenance and Document default parser_version ("unknown"), parser version propagation, and fallback invalidation.
"""

import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from app.main import app
from app.db.connection import DatabaseManager
from app.db.repository import Repository
from app.intelligence.chunker.provenance import ChunkProvenance
from app.intelligence.models import Document
from app.intelligence.parsers.registry import default_parser_registry
from app.intelligence.parsers.text_parser import TEXT_PARSER_VERSION
from tests.fixtures.benchmark_corpus import setup_benchmark_corpus


@pytest.fixture
def test_vault(tmp_path):
    """Sets up an isolated test vault with indexed documents and vectors."""
    target_dir = str(tmp_path / "docs")
    db_path = str(tmp_path / "test_audit.db")
    meta = setup_benchmark_corpus(target_dir, db_path)
    db = DatabaseManager(db_path)
    return db, meta


def test_search_request_quality_default_and_combinations(test_vault):
    """Verifies that omitting 'quality' in SearchRequest cleanly defaults to 'fast'."""
    db, meta = test_vault
    client = TestClient(app)

    with patch("app.main.db_manager", db):
        # 1. SearchRequest with mode='hybrid' and NO quality field provided
        res = client.post("/search", json={"query": "architecture", "mode": "hybrid", "top_k": 5})
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["quality"] == "fast"
        assert data["mode"] == "hybrid"
        assert data["degraded"] is False
        assert len(data["results"]) > 0
        for r in data["results"]:
            assert r["reranker_score"] is None

        # 2. SearchRequest with mode='bm25' and NO quality field provided
        res_bm25 = client.post("/search", json={"query": "architecture", "mode": "bm25", "top_k": 5})
        assert res_bm25.status_code == 200, res_bm25.text
        data_bm25 = res_bm25.json()
        assert data_bm25["quality"] == "fast"
        assert data_bm25["mode"] == "bm25"

        # 3. SearchRequest with mode='dense' and NO quality field provided
        res_dense = client.post("/search", json={"query": "architecture", "mode": "dense", "top_k": 5})
        assert res_dense.status_code == 200, res_dense.text
        data_dense = res_dense.json()
        assert data_dense["quality"] == "fast"
        assert data_dense["mode"] == "dense"

        # 4. SearchRequest with no mode and no quality (pure default)
        res_default = client.post("/search", json={"query": "architecture"})
        assert res_default.status_code == 200, res_default.text
        data_default = res_default.json()
        assert data_default["mode"] == "hybrid"
        assert data_default["quality"] == "fast"

        # 5. SearchRequest with explicit quality='quality' on bm25 -> 400
        res_invalid = client.post("/search", json={"query": "architecture", "mode": "bm25", "quality": "quality"})
        assert res_invalid.status_code == 400
        assert "Quality mode is only supported with hybrid retrieval" in res_invalid.json()["detail"]


def test_parser_version_dataclass_defaults_and_propagation():
    """Verifies that ChunkProvenance and Document default parser_version to 'unknown' rather than obsolete hardcoded versions."""
    # 1. ChunkProvenance dataclass default
    chunk = ChunkProvenance(
        chunk_id="chk_test_1",
        file_id="f_test_1",
        source_file="test.txt",
        source_path="/test.txt",
    )
    assert chunk.parser_name == "unknown"
    assert chunk.parser_version == "unknown"

    # 2. Document dataclass default
    doc = Document(
        file_id="f_test_1",
        source_path="/test.txt",
        filename="test.txt",
        mime_type="text/plain",
    )
    assert doc.parser_name == "unknown"
    assert doc.parser_version == "unknown"

    # 3. All real parsers in registry have non-unknown parser names and versions
    text_parser = default_parser_registry.get_parser_for_file("file.txt", "text/plain")
    assert text_parser is not None
    assert text_parser.parser_name == "text-code-parser"
    assert text_parser.parser_version == TEXT_PARSER_VERSION == "1.1.0"

    pdf_parser = default_parser_registry.get_parser_for_file("file.pdf", "application/pdf")
    assert pdf_parser is not None
    assert pdf_parser.parser_name == "pymupdf-parser"
    assert pdf_parser.parser_version == "1.0.0"

    docx_parser = default_parser_registry.get_parser_for_file("file.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    assert docx_parser is not None
    assert docx_parser.parser_name == "docx-parser"
    assert docx_parser.parser_version == "1.0.0"


def test_repository_save_chunks_fallback_parser_version(tmp_path):
    """Verifies that repository saving chunks without parser_version persists 'unknown'."""
    db_file = tmp_path / "test_repo_fallback.db"
    db_manager = DatabaseManager(str(db_file))

    with db_manager.session() as conn:
        from app.db.migrations import apply_migrations
        apply_migrations(conn)
        repo = Repository(conn)
        folder = repo.create_folder(str(tmp_path))
        file_rec = repo.upsert_file(
            folder_id=folder["folder_id"],
            path=str(tmp_path / "sample.txt"),
            relative_path="sample.txt",
            filename="sample.txt",
            extension=".txt",
            size_bytes=100,
            modified_at="2026-09-02T00:00:00Z",
            mime_type="text/plain",
            index_status="DISCOVERED",
        )


        # Save chunk without specifying parser_name or parser_version in the dict
        raw_chunk = {
            "chunk_id": "chk_fallback_1",
            "source_file": "sample.txt",
            "source_path": str(tmp_path / "sample.txt"),
            "content_hash": "hash123",
            "content": "Sample content without explicit parser version.",
        }
        repo.replace_file_chunks(file_rec["file_id"], [raw_chunk])

        chunk_row = repo.get_chunk_by_id("chk_fallback_1")
        assert chunk_row is not None
        assert chunk_row["parser_name"] == "unknown"
        assert chunk_row["parser_version"] == "unknown"

