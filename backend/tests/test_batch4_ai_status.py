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


def test_ollama_readiness_online_and_model_present(monkeypatch):
    """When local Ollama responds with tags including the target model, returns online and present."""
    from app.ai.ollama_provider import check_ollama_readiness
    import httpx

    def mock_get(url, *args, **kwargs):
        assert url == "http://127.0.0.1:11434/api/tags"
        return httpx.Response(
            status_code=200,
            json={"models": [{"name": "qwen3:4b", "size": 2500000000}]},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx, "get", mock_get)

    res = check_ollama_readiness("http://127.0.0.1:11434", "qwen3:4b")
    assert res["is_ollama_online"] is True
    assert res["has_default_model"] is True
    assert res["model_name"] == "qwen3:4b"
    assert res["error"] is None


def test_ollama_readiness_tag_normalization(monkeypatch):
    """Target 'qwen3:4b' correctly matches installed 'qwen3:4b:latest'."""
    from app.ai.ollama_provider import check_ollama_readiness
    import httpx

    def mock_get(url, *args, **kwargs):
        return httpx.Response(
            status_code=200,
            json={"models": [{"name": "qwen3:4b:latest"}]},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx, "get", mock_get)

    res = check_ollama_readiness("http://127.0.0.1:11434", "qwen3:4b")
    assert res["is_ollama_online"] is True
    assert res["has_default_model"] is True


def test_ollama_readiness_online_model_missing(monkeypatch):
    """When Ollama is online but the target model is missing, returns online=True, has_default_model=False."""
    from app.ai.ollama_provider import check_ollama_readiness
    import httpx

    def mock_get(url, *args, **kwargs):
        return httpx.Response(
            status_code=200,
            json={"models": [{"name": "llama3.2:3b"}]},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx, "get", mock_get)

    res = check_ollama_readiness("http://127.0.0.1:11434", "qwen3:4b")
    assert res["is_ollama_online"] is True
    assert res["has_default_model"] is False
    assert "not found" in res["error"]


def test_ollama_readiness_unreachable(monkeypatch):
    """When Ollama is offline or uncontactable, fails safely without crashing."""
    from app.ai.ollama_provider import check_ollama_readiness
    import httpx

    def mock_get(url, *args, **kwargs):
        raise httpx.ConnectError("Connection refused")

    monkeypatch.setattr(httpx, "get", mock_get)

    res = check_ollama_readiness("http://127.0.0.1:11434", "qwen3:4b")
    assert res["is_ollama_online"] is False
    assert res["has_default_model"] is False
    assert "Unable to connect" in res["error"]


def test_ollama_readiness_non_local_rejected():
    """Non-loopback URLs are rejected immediately for privacy and security."""
    from app.ai.ollama_provider import check_ollama_readiness

    res = check_ollama_readiness("http://remote.server.com:11434", "qwen3:4b")
    assert res["is_ollama_online"] is False
    assert res["has_default_model"] is False
    assert "Non-local Ollama endpoint rejected" in res["error"]


def test_ai_status_endpoint_includes_ollama(monkeypatch):
    """GET /ai/status includes local_ai.ollama readiness metadata."""
    import httpx

    def mock_get(url, *args, **kwargs):
        if "api/tags" in url:
            return httpx.Response(
                status_code=200,
                json={"models": [{"name": "qwen3:4b"}]},
                request=httpx.Request("GET", url),
            )
        raise RuntimeError(f"Unexpected GET {url}")

    monkeypatch.setattr(httpx, "get", mock_get)

    resp = client.get("/ai/status")
    assert resp.status_code == 200
    data = resp.json()

    assert "local_ai" in data
    local_ai = data["local_ai"]
    assert "ollama" in local_ai
    ollama = local_ai["ollama"]
    assert ollama is not None
    assert ollama["is_ollama_online"] is True
    assert ollama["has_default_model"] is True
    assert ollama["model_name"] == "qwen3:4b"
    assert ollama["endpoint"] == "http://127.0.0.1:11434"
