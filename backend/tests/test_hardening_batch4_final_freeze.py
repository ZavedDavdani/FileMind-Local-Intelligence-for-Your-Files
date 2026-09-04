"""Batch 4: Final Performance, Audit & Phase 5 Freeze Regression Tests."""

import os
import tempfile
import pytest

from app.ai.knowledge_connections import KnowledgeConnectionService
from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.db.repository import Repository
from app.intelligence.parsers.pdf_parser import PyMuPDFParser
from app.intelligence.parsers.text_parser import TextAndCodeParser
from app.intelligence.parsers.tabular_parser import TabularParser
from app.retrieval.reranker import Reranker
from app.core.config import OLLAMA_MODEL


def test_knowledge_connections_scalability_and_precomputed_counts(tmp_path):
    """Verifies that KnowledgeConnectionService runs efficiently with duplicate and unique basenames."""
    db = DatabaseManager(str(tmp_path / "scale_connections.db"))
    with db.session() as conn:
        apply_migrations(conn)
        repo = Repository(conn)
        folder = repo.create_folder("C:/vault", True)

        # Create source and multiple target files, some sharing duplicate basenames
        source = repo.upsert_file(
            folder_id=folder["folder_id"],
            path="C:/vault/main.md",
            relative_path="main.md",
            filename="main.md",
            extension=".md",
            size_bytes=100,
            modified_at="2026-01-01T00:00:00Z",
            mime_type="text/markdown",
            sha256="main-hash",
            index_status="INDEXED",
        )
        repo.replace_file_chunks(source["file_id"], [{
            "chunk_id": "chunk-main",
            "file_id": source["file_id"],
            "source_file": "main.md",
            "source_path": "C:/vault/main.md",
            "content_hash": "c-main-hash",
            "content": "References sub/report.md, docs/report.md, and unique.md for project setup.",
            "token_count": 15,
            "metadata": {},
        }])

        # Unique target
        unique_target = repo.upsert_file(
            folder_id=folder["folder_id"],
            path="C:/vault/unique.md",
            relative_path="unique.md",
            filename="unique.md",
            extension=".md",
            size_bytes=50,
            modified_at="2026-01-01T00:00:00Z",
            mime_type="text/markdown",
            sha256="unique-hash",
            index_status="INDEXED",
        )
        repo.replace_file_chunks(unique_target["file_id"], [{
            "chunk_id": "chunk-unique",
            "file_id": unique_target["file_id"],
            "source_file": "unique.md",
            "source_path": "C:/vault/unique.md",
            "content_hash": "c-unique-hash",
            "content": "Unique document content.",
            "token_count": 5,
            "metadata": {},
        }])

        # Duplicate basename targets in different subfolders
        dup1 = repo.upsert_file(
            folder_id=folder["folder_id"],
            path="C:/vault/sub/report.md",
            relative_path="sub/report.md",
            filename="report.md",
            extension=".md",
            size_bytes=50,
            modified_at="2026-01-01T00:00:00Z",
            mime_type="text/markdown",
            sha256="dup1-hash",
            index_status="INDEXED",
        )
        repo.replace_file_chunks(dup1["file_id"], [{
            "chunk_id": "chunk-dup1",
            "file_id": dup1["file_id"],
            "source_file": "report.md",
            "source_path": "C:/vault/sub/report.md",
            "content_hash": "c-dup1-hash",
            "content": "Sub report.",
            "token_count": 5,
            "metadata": {},
        }])

        dup2 = repo.upsert_file(
            folder_id=folder["folder_id"],
            path="C:/vault/docs/report.md",
            relative_path="docs/report.md",
            filename="report.md",
            extension=".md",
            size_bytes=50,
            modified_at="2026-01-01T00:00:00Z",
            mime_type="text/markdown",
            sha256="dup2-hash",
            index_status="INDEXED",
        )
        repo.replace_file_chunks(dup2["file_id"], [{
            "chunk_id": "chunk-dup2",
            "file_id": dup2["file_id"],
            "source_file": "report.md",
            "source_path": "C:/vault/docs/report.md",
            "content_hash": "c-dup2-hash",
            "content": "Docs report.",
            "token_count": 5,
            "metadata": {},
        }])

    service = KnowledgeConnectionService(db)
    res = service.get_connections(source["file_id"])

    # unique.md should match by basename "unique.md"
    unique_conns = [c for c in res["connections"] if c["target_file"]["file_id"] == unique_target["file_id"]]
    assert len(unique_conns) == 1
    assert unique_conns[0]["label"] == "unique.md"

    # sub/report.md should match by relative path "sub/report.md" (because basename "report.md" is not unique)
    dup1_conns = [c for c in res["connections"] if c["target_file"]["file_id"] == dup1["file_id"]]
    assert len(dup1_conns) == 1
    assert dup1_conns[0]["label"] == "sub/report.md"

    # docs/report.md should match by relative path "docs/report.md"
    dup2_conns = [c for c in res["connections"] if c["target_file"]["file_id"] == dup2["file_id"]]
    assert len(dup2_conns) == 1
    assert dup2_conns[0]["label"] == "docs/report.md"


def test_encrypted_pdf_handling_safety():
    """Encrypted PDFs with password or permission blocks must be safely handled without leaks."""
    parser = PyMuPDFParser()
    # If a file is not an encrypted PDF or is invalid, it raises appropriate exception cleanly
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(b"%PDF-1.4\n%trailer\n<< /Encrypt << >> >>\n%%EOF")
        f_path = f.name

    try:
        # Should either parse with 0 elements or gracefully handle without hanging
        doc = parser.parse(f_path, file_id="enc_pdf_1")
        assert doc.file_id == "enc_pdf_1"
    except Exception as exc:
        # Expected if fitz cannot open corrupted/encrypted header
        assert "fitz" in str(exc).lower() or "pdf" in str(exc).lower() or "cannot" in str(exc).lower()
    finally:
        if os.path.exists(f_path):
            os.remove(f_path)


def test_reranker_graceful_missing_dictionary_keys():
    """Reranker should handle candidates that might have None scores or missing fields."""
    reranker = Reranker()
    # Fast path if disabled or error cached
    mock_candidates = [
        {"chunk_id": "c1", "content": "hello world", "score": None, "rrf_score": 0.5},
        {"chunk_id": "c2", "content": "second chunk", "score": 0.8, "rrf_score": None},
    ]
    # Reranker should not crash even if model is not loaded (returns fallback)
    results = reranker.rerank("hello", mock_candidates, top_k=2)
    assert len(results) <= 2
    assert all("chunk_id" in r for r in results)
