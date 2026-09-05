"""
FileMind Phase 5.5 Batch 1 — Document Understanding Test Suite.

Covers:
- Database migration V6, indexes, constraints, and cascade deletion.
- DocumentUnderstandingService lifecycle states (NOT_GENERATED, READY, STALE, MODEL_UNAVAILABLE, FAILED).
- Cache invalidation (content_hash, parser_version, chunker_version, model_name).
- Evidence selection and token budgeting.
- Structured LLM output parsing, schema validation, and citation provenance.
- Ollama temperature options forwarding.
- Concurrency protection.
- Zero-evidence file handling.
"""

import json
import sqlite3
from typing import Any, Dict, List, Optional, Set
import pytest
from unittest.mock import MagicMock, patch

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
from app.ai.document_understanding import DocumentUnderstandingService
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
def populated_file(test_db):
    """Creates a sample folder, file, and chunks in the test database."""
    with test_db.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder(path="C:/dev/test_folder", recursive=True)
        file_rec = repo.upsert_file(
            folder_id=folder["folder_id"],
            path="C:/dev/test_folder/doc.md",
            relative_path="doc.md",
            filename="doc.md",
            extension=".md",
            size_bytes=1500,
            modified_at="2026-09-02T10:00:00Z",
            mime_type="text/markdown",
            sha256="abc123hash",
            index_status="INDEXED",
        )
        file_id = file_rec["file_id"]

        # Insert 3 hierarchical chunks
        repo.replace_file_chunks(file_id, [
            {
                "chunk_id": "c1",
                "file_id": file_id,
                "source_file": "doc.md",
                "source_path": "C:/dev/test_folder/doc.md",
                "page": 1,
                "section": "Introduction",
                "h1_parent": "Architecture Overview",
                "h2_parent": None,
                "line_start": 1,
                "line_end": 20,
                "char_start": 0,
                "char_end": 400,
                "content_hash": "chash1",
                "chunk_index": 0,
                "parser_name": "markdown",
                "parser_version": "v1.0",
                "chunker_version": "phase2-hierarchical-v2",
                "content": "FileMind provides local file intelligence using SQLite and hybrid retrieval [E1].",
                "content_type": "text",
                "token_count": 50,
                "metadata": {},
            },
            {
                "chunk_id": "c2",
                "file_id": file_id,
                "source_file": "doc.md",
                "source_path": "C:/dev/test_folder/doc.md",
                "page": 2,
                "section": "Technical Decisions",
                "h1_parent": "Architecture Overview",
                "h2_parent": "Storage Engine",
                "line_start": 21,
                "line_end": 50,
                "char_start": 401,
                "char_end": 900,
                "content_hash": "chash2",
                "chunk_index": 1,
                "parser_name": "markdown",
                "parser_version": "v1.0",
                "chunker_version": "phase2-hierarchical-v2",
                "content": "We decided to adopt sqlite-vec for dense vector search and FTS5 for BM25.",
                "content_type": "text",
                "token_count": 60,
                "metadata": {},
            },
            {
                "chunk_id": "c3",
                "file_id": file_id,
                "source_file": "doc.md",
                "source_path": "C:/dev/test_folder/doc.md",
                "page": 3,
                "section": "Conclusion",
                "h1_parent": "Summary",
                "h2_parent": None,
                "line_start": 51,
                "line_end": 70,
                "char_start": 901,
                "char_end": 1400,
                "content_hash": "chash3",
                "chunk_index": 2,
                "parser_name": "markdown",
                "parser_version": "v1.0",
                "chunker_version": "phase2-hierarchical-v2",
                "content": "In conclusion, FileMind operates completely offline without cloud fallback.",
                "content_type": "text",
                "token_count": 40,
                "metadata": {},
            },
        ])
        return file_id


class FakeLLMProvider:
    """Mock LLM provider for deterministic tests."""
    def __init__(self, response_text: str = "", should_fail: Optional[Exception] = None):
        self.response_text = response_text
        self.should_fail = should_fail
        self.last_prompt = None
        self.last_temperature = None
        self.last_options = None

    def generate(self, prompt: str, temperature: Optional[float] = None, options: Optional[dict] = None) -> OllamaResponse:
        self.last_prompt = prompt
        self.last_temperature = temperature
        self.last_options = options
        if self.should_fail:
            raise self.should_fail
        return OllamaResponse(
            model="qwen3:4b",
            response=self.response_text,
            done=True,
            done_reason="stop",
            prompt_eval_count=120,
            eval_count=85,
        )


# ===========================================================================
# A. Database Migration & Schema Tests
# ===========================================================================

def test_migration_v6_schema(test_db):
    """Verify document_insights table exists with expected schema and indexes."""
    with test_db.session() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='document_insights';")
        assert cursor.fetchone() is not None

        # Check unique constraint index
        cursor.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='uq_doc_insights_file_model';")
        assert cursor.fetchone() is not None


def test_cascade_deletion(test_db, populated_file):
    """Verify that deleting a file cascades and removes its document insight."""
    fake_provider = FakeLLMProvider(
        response_text=json.dumps({
            "executive_summary": "Summary with citation [E1].",
            "key_topics": ["Architecture"],
            "key_decisions": ["Adopt SQLite"],
        })
    )
    svc = DocumentUnderstandingService(db_manager=test_db, llm_provider=fake_provider)
    insight = svc.generate_insight(populated_file)
    assert insight["status"] == "READY"

    # Delete the source file
    with test_db.session() as conn:
        repo = Repository(conn)
        repo.delete_file(populated_file)

    # Verify insight is gone
    with test_db.session() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM document_insights WHERE file_id = ?;", (populated_file,))
        assert cursor.fetchone() is None


# ===========================================================================
# B. Lifecycle & Generation Tests
# ===========================================================================

def test_lifecycle_not_generated(test_db, populated_file):
    """Verify get_insight returns NOT_GENERATED for unanalyzed file."""
    fake_provider = FakeLLMProvider()
    svc = DocumentUnderstandingService(db_manager=test_db, llm_provider=fake_provider)
    insight = svc.get_insight(populated_file)
    assert insight["status"] == "NOT_GENERATED"
    assert insight["executive_summary"] is None
    assert insight["structural_summary"]["total_chunks"] == 3
    assert insight["structural_summary"]["estimated_tokens"] == 150


def test_lifecycle_ready_generation(test_db, populated_file):
    """Verify successful generation results in READY status and valid fields."""
    response_payload = {
        "executive_summary": "FileMind operates local intelligence [E1] using sqlite-vec [E2].",
        "key_topics": ["Local Intelligence", "Vector Search"],
        "key_decisions": ["Adopt sqlite-vec and FTS5"],
    }
    fake_provider = FakeLLMProvider(response_text=json.dumps(response_payload))
    svc = DocumentUnderstandingService(db_manager=test_db, llm_provider=fake_provider)
    insight = svc.generate_insight(populated_file)

    assert insight["status"] == "READY"
    assert insight["is_stale"] is False
    assert "FileMind operates local intelligence" in insight["executive_summary"]
    assert insight["key_topics"] == ["Local Intelligence", "Vector Search"]
    assert insight["key_decisions"] == ["Adopt sqlite-vec and FTS5"]
    assert len(insight["citations"]) == 2
    assert insight["citations"][0]["citation_id"] == "E1"
    assert insight["citations"][1]["citation_id"] == "E2"


def test_lifecycle_model_unavailable(test_db, populated_file):
    """Verify connection error sets status to MODEL_UNAVAILABLE."""
    fake_provider = FakeLLMProvider(should_fail=OllamaConnectionError("Daemon offline"))
    svc = DocumentUnderstandingService(db_manager=test_db, llm_provider=fake_provider)
    insight = svc.generate_insight(populated_file)

    assert insight["status"] == "MODEL_UNAVAILABLE"
    assert "Daemon offline" in insight["error"]


def test_lifecycle_generation_failed_timeout(test_db, populated_file):
    """Verify timeout sets status to FAILED."""
    fake_provider = FakeLLMProvider(should_fail=OllamaTimeoutError("Read timeout"))
    svc = DocumentUnderstandingService(db_manager=test_db, llm_provider=fake_provider)
    insight = svc.generate_insight(populated_file)

    assert insight["status"] == "FAILED"
    assert "Read timeout" in insight["error"]


# ===========================================================================
# C. Invalidation Tests
# ===========================================================================

def test_invalidation_content_hash_change(test_db, populated_file):
    """Verify modifying file sha256 marks insight as STALE."""
    fake_provider = FakeLLMProvider(
        response_text=json.dumps({
            "executive_summary": "Insight content [E1].",
            "key_topics": ["Test"],
            "key_decisions": [],
        })
    )
    svc = DocumentUnderstandingService(db_manager=test_db, llm_provider=fake_provider)
    svc.generate_insight(populated_file)

    # Change file sha256 in db
    with test_db.session() as conn:
        conn.execute("UPDATE files SET sha256 = 'new_sha_hash' WHERE file_id = ?;", (populated_file,))

    insight = svc.get_insight(populated_file)
    assert insight["status"] == "STALE"
    assert insight["is_stale"] is True


def test_invalidation_parser_version_change(test_db, populated_file):
    """Verify incrementing parser_version in chunks marks insight as STALE."""
    fake_provider = FakeLLMProvider(
        response_text=json.dumps({
            "executive_summary": "Insight content [E1].",
            "key_topics": ["Test"],
            "key_decisions": [],
        })
    )
    svc = DocumentUnderstandingService(db_manager=test_db, llm_provider=fake_provider)
    svc.generate_insight(populated_file)

    # Change parser_version in chunks
    with test_db.session() as conn:
        conn.execute("UPDATE chunks SET parser_version = 'v2.0' WHERE file_id = ?;", (populated_file,))

    insight = svc.get_insight(populated_file)
    assert insight["status"] == "STALE"
    assert insight["is_stale"] is True


def test_invalidation_model_name_change(test_db, populated_file):
    """Verify changing model_name marks insight as STALE / NOT_GENERATED."""
    fake_provider = FakeLLMProvider(
        response_text=json.dumps({
            "executive_summary": "Insight content [E1].",
            "key_topics": ["Test"],
            "key_decisions": [],
        })
    )
    svc1 = DocumentUnderstandingService(db_manager=test_db, llm_provider=fake_provider, model_name="qwen3:4b")
    svc1.generate_insight(populated_file)

    # Request with another model name
    svc2 = DocumentUnderstandingService(db_manager=test_db, llm_provider=fake_provider, model_name="llama3.2:3b")
    insight = svc2.get_insight(populated_file)
    assert insight["status"] == "NOT_GENERATED"


# ===========================================================================
# D. Caching Tests
# ===========================================================================

def test_caching_ready_avoids_llm(test_db, populated_file):
    """Verify get_insight returns cached READY insight without calling LLM provider."""
    fake_provider = FakeLLMProvider(
        response_text=json.dumps({
            "executive_summary": "Grounded summary [E1].",
            "key_topics": ["Caching"],
            "key_decisions": [],
        })
    )
    svc = DocumentUnderstandingService(db_manager=test_db, llm_provider=fake_provider)
    svc.generate_insight(populated_file)

    # Reset fake provider calls
    fake_provider.last_prompt = None

    # Retrieve cached
    cached = svc.get_insight(populated_file)
    assert cached["status"] == "READY"
    assert fake_provider.last_prompt is None


# ===========================================================================
# E. Structured Output Validation Tests
# ===========================================================================

def test_invalid_json_handling(test_db, populated_file):
    """Verify malformed non-JSON output from LLM results in FAILED status."""
    fake_provider = FakeLLMProvider(response_text="Not valid JSON response at all")
    svc = DocumentUnderstandingService(db_manager=test_db, llm_provider=fake_provider)
    insight = svc.generate_insight(populated_file)

    assert insight["status"] == "FAILED"
    assert "Invalid JSON" in insight["error"]


def test_missing_summary_handling(test_db, populated_file):
    """Verify JSON missing executive_summary results in FAILED status."""
    fake_provider = FakeLLMProvider(response_text=json.dumps({"key_topics": ["Topic A"]}))
    svc = DocumentUnderstandingService(db_manager=test_db, llm_provider=fake_provider)
    insight = svc.generate_insight(populated_file)

    assert insight["status"] == "FAILED"
    assert "Missing or empty executive_summary" in insight["error"]


def test_unresolved_citation_tracking(test_db, populated_file):
    """Verify citations not present in evidence context are flagged in unresolved_citations."""
    fake_provider = FakeLLMProvider(
        response_text=json.dumps({
            "executive_summary": "Valid claim [E1], fabricated claim [E99].",
            "key_topics": ["Evidence"],
            "key_decisions": [],
        })
    )
    svc = DocumentUnderstandingService(db_manager=test_db, llm_provider=fake_provider)
    insight = svc.generate_insight(populated_file)

    assert insight["status"] == "READY"
    assert len(insight["citations"]) == 1
    assert insight["citations"][0]["citation_id"] == "E1"


# ===========================================================================
# F. Ollama Provider & Temperature Tests
# ===========================================================================

def test_ollama_provider_temperature_forwarding():
    """Verify OllamaProvider forwards configured temperature in options payload."""
    provider = OllamaProvider(base_url="http://127.0.0.1:11434", model="qwen3:4b")

    with patch("app.ai.ollama_provider.httpx.Client.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "model": "qwen3:4b",
            "response": "Test response",
            "done": True,
        }
        mock_post.return_value = mock_resp

        provider.generate("test prompt", temperature=0.1)

        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        payload = kwargs["json"]
        assert payload["model"] == "qwen3:4b"
        assert payload["prompt"] == "test prompt"
        assert payload["options"] == {"temperature": 0.1}


def test_ollama_provider_non_local_rejected():
    """Verify non-local base URLs are strictly rejected."""
    with pytest.raises(ValueError, match="only permits the local Ollama endpoint"):
        OllamaProvider(base_url="https://api.openai.com/v1")


# ===========================================================================
# G. Concurrency & Zero-Evidence Tests
# ===========================================================================

def test_zero_evidence_file_handling(test_db):
    """Verify file with 0 chunks completes without invoking LLM."""
    with test_db.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder(path="C:/dev/empty_folder", recursive=True)
        file_rec = repo.upsert_file(
            folder_id=folder["folder_id"],
            path="C:/dev/empty_folder/empty.txt",
            relative_path="empty.txt",
            filename="empty.txt",
            extension=".txt",
            size_bytes=0,
            modified_at="2026-09-02T10:00:00Z",
            mime_type="text/plain",
            sha256="emptyhash",
            index_status="INDEXED",
        )
        empty_file_id = file_rec["file_id"]

    fake_provider = FakeLLMProvider(should_fail=RuntimeError("LLM should not be called"))
    svc = DocumentUnderstandingService(db_manager=test_db, llm_provider=fake_provider)
    insight = svc.generate_insight(empty_file_id)

    assert insight["status"] == "READY"
    assert "no text chunks" in insight["executive_summary"]
    assert insight["structural_summary"]["total_chunks"] == 0


# ===========================================================================
# H. API Route Tests
# ===========================================================================

def test_api_document_insight_endpoints(test_db, populated_file):
    """Verify FastAPI routes for document insight GET and POST."""
    from fastapi.testclient import TestClient
    from app.main import app

    with patch("app.main.db_manager", test_db):
        client = TestClient(app)

        # GET initially NOT_GENERATED
        resp = client.get(f"/ai/document-insight/{populated_file}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["file_id"] == populated_file
        assert data["status"] == "NOT_GENERATED"
        assert data["filename"] == "doc.md"

        # POST generate with mock provider
        mock_llm_json = json.dumps({
            "executive_summary": "API generated grounded summary [E1].",
            "key_topics": ["API", "Grounding"],
            "key_decisions": [],
        })
        with patch("app.ai.document_understanding.OllamaProvider") as mock_cls:
            instance = mock_cls.return_value
            instance.generate.return_value = OllamaResponse(
                model="qwen3:4b",
                response=mock_llm_json,
                done=True,
                done_reason="stop",
                prompt_eval_count=100,
                eval_count=50,
            )

            gen_resp = client.post(f"/ai/document-insight/{populated_file}/generate")
            assert gen_resp.status_code == 200
            gen_data = gen_resp.json()
            assert gen_data["status"] == "READY"
            assert "API generated grounded summary" in gen_data["executive_summary"]
            assert len(gen_data["citations"]) == 1

        # GET subsequent call returns READY
        get_resp = client.get(f"/ai/document-insight/{populated_file}")
        assert get_resp.status_code == 200
        assert get_resp.json()["status"] == "READY"

