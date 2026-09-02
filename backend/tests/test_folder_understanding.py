"""
FileMind Phase 5.5 Batch 3.1 — Folder Understanding Test Suite.

Covers:
- Database migration V7, indexes, constraints, and cascade deletion.
- FolderUnderstandingService structural metrics (counts, size, types, status).
- Dominant topics aggregation from document_insights.
- Deterministic representative file selection.
- Composite hash computation and freshness invalidation.
- Grounded generation lifecycle (NOT_GENERATED, READY, STALE, NO_EVIDENCE, MODEL_UNAVAILABLE, FAILED).
- Grounding prompt boundary, citation validation, and provenance.
- Concurrency protection.
- FastAPI REST endpoints (GET and POST /ai/folder-insight/{folder_id}).
"""

import json
import sqlite3
from typing import Any, Dict, List, Optional
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations, SCHEMA_VERSION
from app.db.repository import Repository
from app.ai.ollama_provider import (
    OllamaProvider,
    OllamaResponse,
    OllamaConnectionError,
    OllamaTimeoutError,
    OllamaGenerationError,
)
from app.ai.folder_understanding import FolderUnderstandingService
from app.ai.generation import GenerationConfig


@pytest.fixture
def test_db(tmp_path):
    """Creates a temporary in-memory/file SQLite database with all migrations applied."""
    db_file = str(tmp_path / "test_filemind.db")
    db = DatabaseManager(db_file)
    with db.session() as conn:
        apply_migrations(conn)
        conn.execute("CREATE TABLE IF NOT EXISTS chunk_vectors (chunk_id TEXT PRIMARY KEY);")
    return db


@pytest.fixture
def populated_folder(test_db):
    """Creates a sample folder with multiple files and chunks in the test database."""
    with test_db.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder(path="C:/dev/project_alpha", recursive=True)
        folder_id = folder["folder_id"]

        # File 1: Markdown doc (Indexed)
        f1 = repo.upsert_file(
            folder_id=folder_id,
            path="C:/dev/project_alpha/spec.md",
            relative_path="spec.md",
            filename="spec.md",
            extension=".md",
            size_bytes=2000,
            modified_at="2026-09-02T10:00:00Z",
            mime_type="text/markdown",
            sha256="hash_spec_123",
            index_status="INDEXED",
        )
        repo.replace_file_chunks(f1["file_id"], [
            {
                "chunk_id": "c_spec_1",
                "file_id": f1["file_id"],
                "source_file": "spec.md",
                "source_path": "C:/dev/project_alpha/spec.md",
                "page": 1,
                "section": "Overview",
                "h1_parent": "Project Alpha Spec",
                "h2_parent": None,
                "line_start": 1,
                "line_end": 20,
                "char_start": 0,
                "char_end": 400,
                "content_hash": "chash_spec_1",
                "chunk_index": 0,
                "parser_name": "markdown",
                "parser_version": "v1.0",
                "chunker_version": "phase2-hierarchical-v2",
                "content": "Project Alpha is a high-speed local vector search engine [E1].",
                "content_type": "text",
                "token_count": 60,
                "metadata": {},
            },
            {
                "chunk_id": "c_spec_2",
                "file_id": f1["file_id"],
                "source_file": "spec.md",
                "source_path": "C:/dev/project_alpha/spec.md",
                "page": 1,
                "section": "Architecture",
                "h1_parent": "Project Alpha Spec",
                "h2_parent": "Storage",
                "line_start": 21,
                "line_end": 40,
                "char_start": 401,
                "char_end": 800,
                "content_hash": "chash_spec_2",
                "chunk_index": 1,
                "parser_name": "markdown",
                "parser_version": "v1.0",
                "chunker_version": "phase2-hierarchical-v2",
                "content": "SQLite WAL mode with memory-mapped I/O is selected for persistent storage.",
                "content_type": "text",
                "token_count": 70,
                "metadata": {},
            },
        ])

        # Existing document insight for File 1
        repo.upsert_document_insight(
            file_id=f1["file_id"],
            status="READY",
            content_hash="hash_spec_123",
            parser_version="v1.0",
            chunker_version="phase2-hierarchical-v2",
            model_provider="ollama",
            model_name="qwen3:4b",
            structural_summary={"total_chunks": 2, "size_bytes": 2000},
            executive_summary="Project Alpha provides local vector retrieval backed by SQLite.",
            key_topics=["Vector Search", "SQLite WAL", "Performance"],
            key_decisions=["Use SQLite WAL for persistent storage"],
            citations=[],
        )

        # File 2: PDF report (Indexed)
        f2 = repo.upsert_file(
            folder_id=folder_id,
            path="C:/dev/project_alpha/report.pdf",
            relative_path="report.pdf",
            filename="report.pdf",
            extension=".pdf",
            size_bytes=5000,
            modified_at="2026-09-02T10:05:00Z",
            mime_type="application/pdf",
            sha256="hash_pdf_456",
            index_status="INDEXED",
        )
        repo.replace_file_chunks(f2["file_id"], [
            {
                "chunk_id": "c_pdf_1",
                "file_id": f2["file_id"],
                "source_file": "report.pdf",
                "source_path": "C:/dev/project_alpha/report.pdf",
                "page": 1,
                "section": "Quarterly Evaluation",
                "h1_parent": "Performance Report",
                "h2_parent": None,
                "line_start": 1,
                "line_end": 30,
                "char_start": 0,
                "char_end": 600,
                "content_hash": "chash_pdf_1",
                "chunk_index": 0,
                "parser_name": "pdf",
                "parser_version": "v1.0",
                "chunker_version": "phase2-hierarchical-v2",
                "content": "Evaluation demonstrates 99.5% precision on hybrid queries [E2].",
                "content_type": "text",
                "token_count": 80,
                "metadata": {},
            }
        ])

        # File 3: Discovered but unindexed Python script
        repo.upsert_file(
            folder_id=folder_id,
            path="C:/dev/project_alpha/script.py",
            relative_path="script.py",
            filename="script.py",
            extension=".py",
            size_bytes=800,
            modified_at="2026-09-02T10:10:00Z",
            mime_type="text/x-python",
            sha256="hash_py_789",
            index_status="DISCOVERED",
        )

        # File 4: Failed file
        repo.upsert_file(
            folder_id=folder_id,
            path="C:/dev/project_alpha/corrupt.docx",
            relative_path="corrupt.docx",
            filename="corrupt.docx",
            extension=".docx",
            size_bytes=300,
            modified_at="2026-09-02T10:15:00Z",
            mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            sha256="hash_corrupt_000",
            index_status="FAILED",
        )

        return folder_id


# ---------------------------------------------------------------------------
# Migration & Schema Tests
# ---------------------------------------------------------------------------

def test_migration_v7_schema_and_version(test_db):
    """Verifies that Migration V7 created folder_insights table and schema version is 7."""
    assert SCHEMA_VERSION == 7
    with test_db.session() as conn:
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='folder_insights';")
        assert cursor.fetchone() is not None

        # Check table columns
        cursor = conn.execute("PRAGMA table_info(folder_insights);")
        cols = {row[1] for row in cursor.fetchall()}
        expected_cols = {
            "insight_id", "folder_id", "status", "composite_hash", "model_provider",
            "model_name", "model_tag", "structural_summary_json", "executive_summary",
            "key_themes_json", "key_decisions_json", "citations_json", "error",
            "created_at", "updated_at"
        }
        assert expected_cols.issubset(cols)


def test_cascade_delete_folder_removes_insights(test_db, populated_folder):
    """Verifies that deleting a folder cascades to delete its folder_insights."""
    folder_id = populated_folder
    with test_db.session() as conn:
        repo = Repository(conn)
        repo.upsert_folder_insight(
            folder_id=folder_id,
            status="READY",
            composite_hash="comp_hash_1",
            model_provider="ollama",
            model_name="qwen3:4b",
            structural_summary={"total_files": 4},
            executive_summary="Summary of project alpha",
        )
        assert repo.get_folder_insight(folder_id) is not None

        # Delete folder
        repo.delete_folder(folder_id)
        assert repo.get_folder_insight(folder_id) is None


# ---------------------------------------------------------------------------
# Structural Understanding Tests
# ---------------------------------------------------------------------------

def test_structural_summary_empty_folder(test_db):
    """Verifies structural metrics for an empty folder."""
    with test_db.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder(path="C:/dev/empty_folder")
        folder_id = folder["folder_id"]

    svc = FolderUnderstandingService(db_manager=test_db)
    res = svc.get_folder_insight(folder_id)

    assert res["status"] == "NO_EVIDENCE"
    assert res["folder_name"] == "empty_folder"
    assert res["structural_summary"]["total_files"] == 0
    assert res["structural_summary"]["indexed_files"] == 0
    assert res["structural_summary"]["total_chunks"] == 0
    assert res["structural_summary"]["total_size_bytes"] == 0
    assert res["structural_summary"]["file_type_distribution"] == {}


def test_structural_summary_populated_folder(test_db, populated_folder):
    """Verifies structural metrics calculation on mixed files (indexed, unindexed, failed)."""
    folder_id = populated_folder
    svc = FolderUnderstandingService(db_manager=test_db)
    res = svc.get_folder_insight(folder_id)

    assert res["status"] == "NOT_GENERATED"
    assert res["folder_name"] == "project_alpha"
    struct = res["structural_summary"]
    assert struct["total_files"] == 4
    assert struct["indexed_files"] == 2
    assert struct["unindexed_files"] == 1
    assert struct["failed_files"] == 1
    assert struct["total_size_bytes"] == 8100  # 2000 + 5000 + 800 + 300
    assert struct["total_chunks"] == 3  # 2 in spec.md, 1 in report.pdf
    assert struct["estimated_tokens"] == 210  # 60 + 70 + 80
    assert struct["file_type_distribution"] == {"md": 1, "pdf": 1, "py": 1, "docx": 1}
    assert "Vector Search" in struct["dominant_topics"]
    assert "spec.md" in struct["representative_files"]


def test_representative_files_ranking_deterministic(test_db, populated_folder):
    """Verifies that representative file selection prioritizes insight presence and chunk counts."""
    folder_id = populated_folder
    with test_db.session() as conn:
        repo = Repository(conn)
        files = repo.list_files(folder_id=folder_id)
        svc = FolderUnderstandingService(db_manager=test_db)
        rep = svc.select_representative_files(files, repo, max_files=2)

        # spec.md has a READY insight and 2 chunks -> rank #1
        # report.pdf has 1 chunk -> rank #2
        # script.py and corrupt.docx are not INDEXED -> excluded
        assert len(rep) == 2
        assert rep[0]["filename"] == "spec.md"
        assert rep[1]["filename"] == "report.pdf"


def test_composite_hash_freshness_invalidation(test_db, populated_folder):
    """Verifies that modifying a file changes the composite hash and triggers STALE state."""
    folder_id = populated_folder
    svc = FolderUnderstandingService(db_manager=test_db)

    # Fake a cached insight
    with test_db.session() as conn:
        repo = Repository(conn)
        files = repo.list_files(folder_id=folder_id)
        initial_hash = svc.compute_composite_hash(files)
        repo.upsert_folder_insight(
            folder_id=folder_id,
            status="READY",
            composite_hash=initial_hash,
            model_provider="ollama",
            model_name="qwen3:4b",
            structural_summary=svc.compute_structural_summary(repo.get_folder(folder_id), files, repo),
            executive_summary="Project Alpha overview.",
        )

    # 1. Inspect initial insight -> READY, not stale
    res = svc.get_folder_insight(folder_id)
    assert res["status"] == "READY"
    assert res["is_stale"] is False

    # 2. Modify a file in the folder (change size and sha256)
    with test_db.session() as conn:
        repo = Repository(conn)
        files = repo.list_files(folder_id=folder_id)
        target = [f for f in files if f["filename"] == "spec.md"][0]
        repo.upsert_file(
            folder_id=folder_id,
            path=target["path"],
            relative_path=target["relative_path"],
            filename=target["filename"],
            extension=target["extension"],
            size_bytes=2500,  # Changed size
            modified_at="2026-09-02T11:00:00Z",  # Changed timestamp
            sha256="new_hash_999",  # Changed hash
            index_status="INDEXED",
        )

    # 3. Inspect again -> composite hash changed, status becomes STALE
    res2 = svc.get_folder_insight(folder_id)
    assert res2["status"] == "STALE"
    assert res2["is_stale"] is True
    assert res2["executive_summary"] == "Project Alpha overview."


# ---------------------------------------------------------------------------
# Grounded Generation Tests
# ---------------------------------------------------------------------------

def test_generate_insight_grounded_success(test_db, populated_folder):
    """Verifies grounded folder insight generation with mocked local Ollama output."""
    folder_id = populated_folder
    mock_llm_response = OllamaResponse(
        response=json.dumps({
            "executive_summary": "Project Alpha is a high-performance vector search engine [E1]. The hybrid query evaluation demonstrated 99.5% precision [E2].",
            "key_themes": ["Vector Search", "Performance", "Hybrid Retrieval"],
            "key_decisions": ["Use SQLite WAL for persistent storage"]
        }),
        model="qwen3:4b",
        done=True,
        done_reason="stop",
        prompt_eval_count=100,
        eval_count=50,
    )

    mock_provider = MagicMock(spec=OllamaProvider)
    mock_provider.base_url = "http://127.0.0.1:11434"
    mock_provider.generate.return_value = mock_llm_response

    with patch("app.ai.folder_understanding.check_ollama_readiness") as mock_readiness:
        mock_readiness.return_value = MagicMock(is_ollama_online=True, has_default_model=True, error=None)

        svc = FolderUnderstandingService(
            db_manager=test_db,
            llm_provider=mock_provider,
            model_name="qwen3:4b",
        )

        res = svc.generate_insight(folder_id)

        assert res["status"] == "READY"
        assert res["is_stale"] is False
        assert "Project Alpha is a high-performance vector search engine" in res["executive_summary"]
        assert len(res["key_themes"]) == 3
        assert "Vector Search" in res["key_themes"]
        assert len(res["key_decisions"]) == 1
        assert len(res["citations"]) >= 1


def test_generate_insight_model_unavailable(test_db, populated_folder):
    """Verifies that offline Ollama produces MODEL_UNAVAILABLE status without crashing."""
    folder_id = populated_folder
    mock_provider = MagicMock(spec=OllamaProvider)
    mock_provider.base_url = "http://127.0.0.1:11434"

    with patch("app.ai.folder_understanding.check_ollama_readiness") as mock_readiness:
        mock_readiness.return_value = MagicMock(
            is_ollama_online=False, has_default_model=False, error="Ollama daemon unreachable"
        )

        svc = FolderUnderstandingService(
            db_manager=test_db,
            llm_provider=mock_provider,
            model_name="qwen3:4b",
        )

        res = svc.generate_insight(folder_id)
        assert res["status"] == "MODEL_UNAVAILABLE"
        assert "Ollama daemon unreachable" in res["error"]


def test_generate_insight_ollama_timeout(test_db, populated_folder):
    """Verifies that LLM timeouts produce FAILED status and record the error."""
    folder_id = populated_folder
    mock_provider = MagicMock(spec=OllamaProvider)
    mock_provider.base_url = "http://127.0.0.1:11434"
    mock_provider.generate.side_effect = OllamaTimeoutError("Request timed out after 30s")

    with patch("app.ai.folder_understanding.check_ollama_readiness") as mock_readiness:
        mock_readiness.return_value = MagicMock(is_ollama_online=True, has_default_model=True, error=None)

        svc = FolderUnderstandingService(
            db_manager=test_db,
            llm_provider=mock_provider,
            model_name="qwen3:4b",
        )

        res = svc.generate_insight(folder_id)
        assert res["status"] == "FAILED"
        assert "Request timed out" in res["error"]


def test_generate_insight_concurrency_lock(test_db, populated_folder):
    """Verifies that concurrent generations for the same folder raise a conflict error."""
    folder_id = populated_folder
    svc = FolderUnderstandingService(db_manager=test_db)
    svc._active_generations.add(folder_id)

    with pytest.raises(RuntimeError, match="already in progress"):
        svc.generate_insight(folder_id)


# ---------------------------------------------------------------------------
# FastAPI API Endpoint Tests
# ---------------------------------------------------------------------------

def test_api_get_folder_insight(test_db, populated_folder):
    """Verifies GET /ai/folder-insight/{folder_id} endpoint."""
    from app.main import app
    from app.db.connection import db_manager

    with patch.object(db_manager, "session", test_db.session):
        client = TestClient(app)
        resp = client.get(f"/ai/folder-insight/{populated_folder}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["folder_id"] == populated_folder
        assert data["status"] in ("NOT_GENERATED", "READY")
        assert data["structural_summary"]["total_files"] == 4


def test_api_get_folder_insight_not_found(test_db):
    """Verifies GET /ai/folder-insight/{folder_id} returns 404 for nonexistent folder."""
    from app.main import app
    from app.db.connection import db_manager

    with patch.object(db_manager, "session", test_db.session):
        client = TestClient(app)
        resp = client.get("/ai/folder-insight/nonexistent_folder_id")
        assert resp.status_code == 404


def test_insufficient_evidence_zero_indexed_chunks(test_db):
    """Verifies that empty folder returns NO_EVIDENCE without invoking LLM."""
    with test_db.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder(path="C:/dev/empty_project")
        folder_id = folder["folder_id"]

    mock_provider = MagicMock(spec=OllamaProvider)
    svc = FolderUnderstandingService(
        db_manager=test_db,
        llm_provider=mock_provider,
        model_name="qwen3:4b",
    )

    res = svc.generate_insight(folder_id)
    assert res["status"] == "NO_EVIDENCE"
    mock_provider.generate.assert_not_called()


def test_api_post_generate_folder_insight(test_db, populated_folder):
    """Verifies POST /ai/folder-insight/{folder_id}/generate endpoint."""
    from app.main import app
    from app.db.connection import db_manager

    mock_llm_response = OllamaResponse(
        response=json.dumps({
            "executive_summary": "Folder project_alpha contains core vector search specs [E1].",
            "key_themes": ["Vector Search"],
            "key_decisions": []
        }),
        model="qwen3:4b",
        done=True,
        done_reason="stop",
        prompt_eval_count=80,
        eval_count=40,
    )

    with patch.object(db_manager, "session", test_db.session), \
         patch("app.ai.folder_understanding.check_ollama_readiness") as mock_readiness, \
         patch("app.ai.folder_understanding.OllamaProvider.generate", return_value=mock_llm_response):
        mock_readiness.return_value = MagicMock(is_ollama_online=True, has_default_model=True, error=None)
        client = TestClient(app)
        resp = client.post(f"/ai/folder-insight/{populated_folder}/generate?force_regenerate=true")
        assert resp.status_code == 200
        data = resp.json()
        assert data["folder_id"] == populated_folder
        assert data["status"] == "READY"
        assert "vector search specs" in data["executive_summary"]


def test_representative_files_large_folder_bounded(test_db):
    """Verifies deterministic selection remains bounded to max_files on a large folder."""
    with test_db.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder(path="C:/dev/large_folder", recursive=True)
        folder_id = folder["folder_id"]

        # Insert 30 indexed files with varying chunk counts
        for i in range(30):
            f = repo.upsert_file(
                folder_id=folder_id,
                path=f"C:/dev/large_folder/file_{i:02d}.txt",
                relative_path=f"file_{i:02d}.txt",
                filename=f"file_{i:02d}.txt",
                extension=".txt",
                size_bytes=1000 + i * 50,
                modified_at="2026-09-02T10:00:00Z",
                mime_type="text/plain",
                sha256=f"hash_{i}",
                index_status="INDEXED",
            )
            # Add (i % 5 + 1) chunks for each file
            chunk_records = [
                {
                    "chunk_id": f"chunk_{i}_{c}",
                    "file_id": f["file_id"],
                    "source_file": f["filename"],
                    "source_path": f["path"],
                    "page": 1,
                    "section": f"Section {c}",
                    "h1_parent": "Title",
                    "h2_parent": None,
                    "line_start": 1,
                    "line_end": 10,
                    "char_start": 0,
                    "char_end": 100,
                    "content_hash": f"chash_{i}_{c}",
                    "chunk_index": c,
                    "parser_name": "plaintext",
                    "parser_version": "v1.0",
                    "chunker_version": "phase2-hierarchical-v2",
                    "content": f"Content for file {i} chunk {c}",
                    "content_type": "text",
                    "token_count": 20,
                    "metadata": {},
                }
                for c in range(i % 5 + 1)
            ]
            repo.replace_file_chunks(f["file_id"], chunk_records)

    svc = FolderUnderstandingService(db_manager=test_db)
    res = svc.get_folder_insight(folder_id)

    assert res["structural_summary"]["total_files"] == 30
    assert res["structural_summary"]["indexed_files"] == 30
    assert len(res["structural_summary"]["representative_files"]) == 5


def test_grounded_generation_unresolved_citations_recorded(test_db, populated_folder):
    """Verifies that hallucinated citations (e.g. [E99]) are safely ignored and do not crash."""
    folder_id = populated_folder
    mock_llm_response = OllamaResponse(
        response=json.dumps({
            "executive_summary": "Summary with a hallucinated citation [E99] and valid citation [E1].",
            "key_themes": ["Vector Search"],
            "key_decisions": []
        }),
        model="qwen3:4b",
        done=True,
        done_reason="stop",
        prompt_eval_count=80,
        eval_count=40,
    )

    with patch("app.ai.folder_understanding.check_ollama_readiness") as mock_readiness:
        mock_readiness.return_value = MagicMock(is_ollama_online=True, has_default_model=True, error=None)

        mock_provider = MagicMock(spec=OllamaProvider)
        mock_provider.base_url = "http://127.0.0.1:11434"
        mock_provider.generate.return_value = mock_llm_response

        svc = FolderUnderstandingService(
            db_manager=test_db,
            llm_provider=mock_provider,
            model_name="qwen3:4b",
        )

        res = svc.generate_insight(folder_id)
        assert res["status"] == "READY"
        # Only valid [E1] resolved
        assert len(res["citations"]) == 1
        assert res["citations"][0]["citation_id"] == "E1"
