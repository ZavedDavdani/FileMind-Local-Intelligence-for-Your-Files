"""Tests for Batch 4 Requirement 15: Unified AI Readiness Architecture (/ai/status).

Verifies:
1. GET /ai/status returns 200 OK.
2. Reports local embedding and reranker readiness.
3. Does NOT report fake Ollama or cloud models.
4. Correctly matches the AIStatusResponse schema.
"""

from fastapi.testclient import TestClient
from app.main import app
from app.retrieval.model_registry import default_model_registry, ModelReadiness


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
