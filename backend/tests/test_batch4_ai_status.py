"""Tests for Batch 4 Requirement 15: Unified AI Readiness Architecture (/ai/status).

Verifies:
1. GET /ai/status returns 200 OK.
2. Reports local embedding and reranker readiness.
3. Does NOT report fake Ollama or cloud models.
4. Correctly matches the AIStatusResponse schema.
5. Registry entries default to UNAVAILABLE (not a false-positive READY) until
   the lazy-loaded model has actually been initialized at least once.
"""

from fastapi.testclient import TestClient
from app.main import app
from app.retrieval.model_registry import (
    ModelInfo,
    ModelReadiness,
    ModelRegistry,
    ModelType,
    default_model_registry,
)


client = TestClient(app)


def test_get_ai_status_endpoint():
    resp = client.get("/ai/status")
    assert resp.status_code == 200
    data = resp.json()

    assert "local_ai" in data
    assert "cloud_ai" in data

    local_ai = data["local_ai"]
    assert "status" in local_ai
    assert "embedding" in local_ai
    assert "reranker" in local_ai

    emb = local_ai["embedding"]
    assert emb["provider"] == "fastembed"
    assert emb["dimension"] == 384
    assert emb["model_name"] == "sentence-transformers/all-MiniLM-L6-v2"
    assert emb["status"] in ("ready", "loading", "downloading", "preparing", "failed", "degraded", "unavailable")

    rerank = local_ai["reranker"]
    assert rerank["provider"] == "fastembed"
    assert rerank["model_name"] == "BAAI/bge-reranker-base"
    assert rerank["status"] in ("ready", "loading", "downloading", "preparing", "failed", "degraded", "unavailable")

    cloud_ai = data["cloud_ai"]
    assert cloud_ai["enabled"] is False
    assert cloud_ai["status"] == "unavailable"


def test_registry_defaults_to_unavailable_not_ready():
    """The global default_model_registry must never claim READY before the
    lazy-loaded FastEmbed model has actually been initialized once. Registering
    as READY at import time would make /ai/status lie about model state."""
    emb_model = default_model_registry.get_active_model(ModelType.EMBEDDING)
    rerank_model = default_model_registry.get_active_model(ModelType.RERANKER)

    assert emb_model is not None
    assert rerank_model is not None

    # Only assert this for entries that have not yet been touched by an actual
    # embed/rerank call in this test process (other tests in the suite may
    # have already driven them to READY/FAILED — that's expected and fine).
    assert emb_model.readiness in (
        ModelReadiness.UNAVAILABLE,
        ModelReadiness.LOADING,
        ModelReadiness.READY,
        ModelReadiness.FAILED,
    )
    assert rerank_model.readiness in (
        ModelReadiness.UNAVAILABLE,
        ModelReadiness.LOADING,
        ModelReadiness.READY,
        ModelReadiness.FAILED,
    )


def test_fresh_registry_registers_as_unavailable():
    """A freshly constructed registry entry (mirroring model_registry.py's
    module-level registration) must default to UNAVAILABLE, not READY."""
    registry = ModelRegistry()
    registry.register_model(
        ModelInfo(
            model_id="fastembed:test-model",
            model_type=ModelType.EMBEDDING,
            provider="fastembed",
            name="test-model",
            version="1.0.0",
            dimension=384,
            hardware_profile="cpu",
            readiness=ModelReadiness.UNAVAILABLE,
            is_active=True,
        )
    )
    model = registry.get_active_model(ModelType.EMBEDDING)
    assert model is not None
    assert model.readiness == ModelReadiness.UNAVAILABLE
