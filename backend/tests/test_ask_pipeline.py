"""
Comprehensive test suite for Phase 5.3: Ask FileMind End-to-End Local RAG Pipeline.
"""

from typing import Any, Dict, List, Optional
import pytest
from fastapi.testclient import TestClient

from app.ai.ask_service import AskService
from app.ai.context import (
    BoundedContextPackage,
    BudgetAccounting,
    ContextBudgetConfig,
    ContextBuilder,
    ContextItem,
    EvidenceStatus,
    TokenEstimator,
)
from app.ai.generation import (
    GenerationConfig,
    GenerationStatus,
    GroundedGenerationResponse,
    GroundedGenerationService,
    ModelIdentity,
)
from app.ai.ollama_provider import (
    OllamaConnectionError,
    OllamaGenerationError,
    OllamaResponse,
    OllamaTimeoutError,
)
from app.ai.prompt import (
    CitationSource,
    GroundedPrompt,
    PromptBuilder,
)
from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.db.repository import Repository
from app.main import app
from app.schemas import (
    AskRequest,
    AskResponse,
    CitationItem,
    ModelIdentitySchema,
    RetrievalMetadata,
)


class FakeLLMProvider:
    """Deterministic in-memory LLM provider for tests."""

    def __init__(
        self,
        canned_response: str = "According to the files, FileMind uses hybrid search [E1].",
        model: str = "qwen3:4b",
        raise_error: Optional[Exception] = None,
    ):
        self.canned_response = canned_response
        self.model = model
        self.raise_error = raise_error
        self.recorded_prompts: List[str] = []

    def generate(self, prompt: str) -> OllamaResponse:
        self.recorded_prompts.append(prompt)
        if self.raise_error:
            raise self.raise_error

        return OllamaResponse(
            model=self.model,
            response=self.canned_response,
            done=True,
            done_reason="stop",
            prompt_eval_count=len(prompt) // 4,
            eval_count=len(self.canned_response) // 4,
        )


@pytest.fixture
def test_db(tmp_path):
    """Creates a seeded test database with files and chunks."""
    db_path = tmp_path / "test_filemind.db"
    mgr = DatabaseManager(db_path)

    with mgr.session() as conn:
        apply_migrations(conn)
        repo = Repository(conn)
        folder = repo.create_folder(str(tmp_path / "docs"), True, "NORMAL", True, [])
        folder_id = folder["folder_id"]
        file_rec = repo.upsert_file(
            folder_id=folder_id,
            path=str(tmp_path / "docs" / "architecture.md"),
            relative_path="architecture.md",
            filename="architecture.md",
            extension=".md",
            size_bytes=1024,
            modified_at="2026-01-01T00:00:00Z",
            sha256="hash_arch",
            index_status="INDEXED",
        )
        file_id = file_rec["file_id"]

        # Insert test chunks
        repo.replace_file_chunks(
            file_id,
            [
                {
                    "chunk_id": "chunk_arch_1",
                    "source_file": "architecture.md",
                    "source_path": str(tmp_path / "docs" / "architecture.md"),
                    "chunk_index": 0,
                    "content": "FileMind uses hybrid BM25 and dense retrieval with RRF fusion for high recall.",
                    "char_start": 0,
                    "char_end": 75,
                    "line_start": 1,
                    "line_end": 5,
                    "page": 1,
                    "section": "Retrieval Engine",
                    "h1_parent": "Architecture",
                    "h2_parent": "Search",
                    "content_hash": "hash_c1",
                    "metadata": {},
                },
                {
                    "chunk_id": "chunk_arch_2",
                    "source_file": "architecture.md",
                    "source_path": str(tmp_path / "docs" / "architecture.md"),
                    "chunk_index": 1,
                    "content": "Local SQLite database with sqlite-vec manages vector embeddings safely on disk.",
                    "char_start": 76,
                    "char_end": 155,
                    "line_start": 6,
                    "line_end": 12,
                    "page": 2,
                    "section": "Vector Storage",
                    "h1_parent": "Architecture",
                    "h2_parent": "Database",
                    "content_hash": "hash_c2",
                    "metadata": {},
                },
            ],
        )

    return mgr


# ---------------------------------------------------------------------------
# Test 1, 2, 3: Valid Ask Request & Hybrid Fast Path
# ---------------------------------------------------------------------------
def test_ask_pipeline_valid_hybrid_fast(test_db):
    fake_provider = FakeLLMProvider(canned_response="FileMind combines BM25 and dense search [E1].")
    gen_service = GroundedGenerationService(provider=fake_provider)
    ask_svc = AskService(
        db_manager_instance=test_db,
        generation_service=gen_service,
    )

    req = AskRequest(
        query="hybrid BM25 retrieval",
        mode="hybrid",
        quality="fast",
        top_k=5,
    )
    resp = ask_svc.ask(req)

    assert resp.query == "hybrid BM25 retrieval"
    assert resp.generation_status in ("READY", "BUDGET_LIMITED")
    assert resp.evidence_status in ("READY", "BUDGET_LIMITED")
    assert "FileMind combines BM25 and dense search" in resp.answer
    assert len(resp.citations) >= 1
    assert resp.citations[0].citation_id == "E1"
    assert resp.citations[0].source_file == "architecture.md"
    assert resp.model_identity.is_local is True
    assert resp.model_identity.provider == "ollama"
    assert len(fake_provider.recorded_prompts) == 1
    # Verify raw prompt is NOT returned in AskResponse
    assert not hasattr(resp, "raw_prompt")


# ---------------------------------------------------------------------------
# Test 4: Quality Reranking Path
# ---------------------------------------------------------------------------
def test_ask_pipeline_hybrid_quality(test_db):
    fake_provider = FakeLLMProvider(canned_response="Storage is handled by sqlite-vec [E1].")
    gen_service = GroundedGenerationService(provider=fake_provider)
    ask_svc = AskService(
        db_manager_instance=test_db,
        generation_service=gen_service,
    )

    req = AskRequest(
        query="vector database storage",
        mode="hybrid",
        quality="quality",
        top_k=5,
    )
    resp = ask_svc.ask(req)

    assert resp.generation_status in ("READY", "BUDGET_LIMITED")
    assert resp.retrieval_metadata.quality == "quality"


# ---------------------------------------------------------------------------
# Test 5 & 6: Invalid Mode / Quality Rejected
# ---------------------------------------------------------------------------
def test_ask_pipeline_invalid_mode_and_quality(test_db):
    ask_svc = AskService(db_manager_instance=test_db)

    with pytest.raises(ValueError, match="Invalid retrieval mode"):
        ask_svc.ask(AskRequest(query="Test", mode="invalid_mode"))

    with pytest.raises(ValueError, match="Invalid quality mode"):
        ask_svc.ask(AskRequest(query="Test", mode="hybrid", quality="ultra"))

    with pytest.raises(ValueError, match="Quality mode is only supported with hybrid retrieval"):
        ask_svc.ask(AskRequest(query="Test", mode="bm25", quality="quality"))


# ---------------------------------------------------------------------------
# Test 7: No Evidence Prevents Ollama Call
# ---------------------------------------------------------------------------
def test_ask_pipeline_no_evidence_short_circuit(test_db):
    fake_provider = FakeLLMProvider()
    gen_service = GroundedGenerationService(provider=fake_provider)
    ask_svc = AskService(
        db_manager_instance=test_db,
        generation_service=gen_service,
    )

    req = AskRequest(
        query="nonexistentquerythatmatchesabsolutelynothing12345xyz",
        mode="bm25",
        quality="fast",
    )
    resp = ask_svc.ask(req)

    assert resp.generation_status == "NO_EVIDENCE"
    assert resp.evidence_status == "NO_EVIDENCE"
    assert "do not contain sufficient evidence" in resp.answer
    assert len(resp.citations) == 0
    assert len(fake_provider.recorded_prompts) == 0  # Ollama NOT invoked!


# ---------------------------------------------------------------------------
# Test 8, 9, 10: Context Budget Enforcement & Grounded Prompt Delivery
# ---------------------------------------------------------------------------
def test_ask_pipeline_context_budget_and_prompt_assembly(test_db):
    fake_provider = FakeLLMProvider(canned_response="Answer based on [E1].")
    gen_service = GroundedGenerationService(provider=fake_provider)

    # Restrict budget to small token size
    small_budget = ContextBudgetConfig(max_context_tokens=1600, reserved_system_tokens=500, reserved_output_tokens=1000)
    ctx_builder = ContextBuilder(default_budget=small_budget)

    ask_svc = AskService(
        db_manager_instance=test_db,
        context_builder=ctx_builder,
        generation_service=gen_service,
    )

    req = AskRequest(query="hybrid BM25", mode="hybrid")
    resp = ask_svc.ask(req)

    assert len(fake_provider.recorded_prompts) == 1
    sent_prompt = fake_provider.recorded_prompts[0]
    assert "GROUNDING & CITATION RULES:" in sent_prompt
    assert "--- EVIDENCE ---" in sent_prompt
    assert "--- USER QUESTION ---\nhybrid BM25" in sent_prompt


# ---------------------------------------------------------------------------
# Test 11: Model Unavailable
# ---------------------------------------------------------------------------
def test_ask_pipeline_model_unavailable(test_db):
    fake_provider = FakeLLMProvider(
        raise_error=OllamaConnectionError("Unable to connect to local Ollama at http://127.0.0.1:11434")
    )
    gen_service = GroundedGenerationService(provider=fake_provider)
    ask_svc = AskService(
        db_manager_instance=test_db,
        generation_service=gen_service,
    )

    req = AskRequest(query="hybrid BM25", mode="hybrid")
    resp = ask_svc.ask(req)

    assert resp.generation_status == "MODEL_UNAVAILABLE"
    assert "Unable to connect" in (resp.error or "")


# ---------------------------------------------------------------------------
# Test 12: Timeout
# ---------------------------------------------------------------------------
def test_ask_pipeline_timeout(test_db):
    fake_provider = FakeLLMProvider(
        raise_error=OllamaTimeoutError("Ollama request timed out after 120.0 seconds.")
    )
    gen_service = GroundedGenerationService(provider=fake_provider)
    ask_svc = AskService(
        db_manager_instance=test_db,
        generation_service=gen_service,
    )

    req = AskRequest(query="hybrid BM25", mode="hybrid")
    resp = ask_svc.ask(req)

    assert resp.generation_status == "TIMEOUT"
    assert "timed out" in (resp.error or "")


# ---------------------------------------------------------------------------
# Test 13: Generation Failure
# ---------------------------------------------------------------------------
def test_ask_pipeline_generation_failure(test_db):
    fake_provider = FakeLLMProvider(
        raise_error=OllamaGenerationError("Ollama returned HTTP 500: Out of memory")
    )
    gen_service = GroundedGenerationService(provider=fake_provider)
    ask_svc = AskService(
        db_manager_instance=test_db,
        generation_service=gen_service,
    )

    req = AskRequest(query="hybrid BM25", mode="hybrid")
    resp = ask_svc.ask(req)

    assert resp.generation_status == "GENERATION_FAILED"
    assert "HTTP 500" in (resp.error or "")


# ---------------------------------------------------------------------------
# Test 14 & 15: Valid and Unresolved Citations
# ---------------------------------------------------------------------------
def test_ask_pipeline_unresolved_citations(test_db):
    # Model hallucinated [E999] in its answer
    fake_provider = FakeLLMProvider(canned_response="FileMind is fast [E1], and scalable [E999].")
    gen_service = GroundedGenerationService(provider=fake_provider)
    ask_svc = AskService(
        db_manager_instance=test_db,
        generation_service=gen_service,
    )

    req = AskRequest(query="hybrid BM25", mode="hybrid")
    resp = ask_svc.ask(req)

    assert len(resp.citations) == 1
    assert resp.citations[0].citation_id == "E1"
    assert "E999" in resp.unresolved_citations


# ---------------------------------------------------------------------------
# Test 16: No Cloud Fallback
# ---------------------------------------------------------------------------
def test_ask_pipeline_no_cloud_fallback(test_db):
    fake_provider = FakeLLMProvider(raise_error=OllamaConnectionError("Daemon offline"))
    gen_service = GroundedGenerationService(provider=fake_provider)
    ask_svc = AskService(
        db_manager_instance=test_db,
        generation_service=gen_service,
    )

    req = AskRequest(query="hybrid BM25", mode="hybrid")
    resp = ask_svc.ask(req)

    assert resp.generation_status == "MODEL_UNAVAILABLE"
    assert resp.model_identity.is_local is True
    assert resp.model_identity.provider == "ollama"


# ---------------------------------------------------------------------------
# Test 17: Query Validation (Empty / Whitespace / Bounded)
# ---------------------------------------------------------------------------
def test_ask_pipeline_query_validation(test_db):
    from pydantic import ValidationError

    ask_svc = AskService(db_manager_instance=test_db)

    with pytest.raises((ValueError, ValidationError)):
        ask_svc.ask(AskRequest(query="   ", mode="hybrid"))

    long_query = "a" * 2000
    with pytest.raises(ValidationError):
        AskRequest(query=long_query, mode="hybrid")



# ---------------------------------------------------------------------------
# Test 18: FastAPI HTTP Endpoint (POST /ai/ask)
# ---------------------------------------------------------------------------
def test_fastapi_ask_endpoint(monkeypatch):
    client = TestClient(app)

    # Empty query validation
    resp_empty = client.post("/ai/ask", json={"query": ""})
    assert resp_empty.status_code in (400, 422)

    # Invalid mode validation
    resp_bad_mode = client.post("/ai/ask", json={"query": "Hello", "mode": "invalid"})
    assert resp_bad_mode.status_code in (400, 422)

    # Mock default_ask_service.ask
    mock_resp = AskResponse(
        answer="FileMind provides local private file intelligence [E1].",
        query="What is FileMind?",
        generation_status="READY",
        evidence_status="READY",
        citations=[
            CitationItem(
                citation_id="E1",
                chunk_id="chunk_1",
                file_id="file_1",
                source_file="readme.md",
                source_path="C:\\dev\\readme.md",
                score=0.95,
            )
        ],
        unresolved_citations=[],
        model_identity=ModelIdentitySchema(
            provider="ollama",
            model_name="qwen3:4b",
            is_local=True,
            model_tag="qwen3:4b",
        ),
        retrieval_metadata=RetrievalMetadata(
            mode="hybrid",
            quality="fast",
            total_found=1,
            latency_breakdown_ms={"bm25": 1.2, "dense": 5.4},
        ),
        context_budget={"evidence_used": 50, "evidence_remaining": 2546},
    )

    from app.ai import default_ask_service
    monkeypatch.setattr(default_ask_service, "ask", lambda req: mock_resp)

    # Valid ask request
    resp_ok = client.post("/ai/ask", json={"query": "What is FileMind?", "mode": "hybrid", "quality": "fast"})
    assert resp_ok.status_code == 200
    data = resp_ok.json()
    assert data["answer"] == "FileMind provides local private file intelligence [E1]."
    assert data["generation_status"] == "READY"
    assert data["evidence_status"] == "READY"
    assert len(data["citations"]) == 1
    assert data["citations"][0]["citation_id"] == "E1"
    assert data["model_identity"]["is_local"] is True
    assert data["retrieval_metadata"]["mode"] == "hybrid"
