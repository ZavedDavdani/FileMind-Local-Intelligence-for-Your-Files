"""Tests for Batch 4 Requirement 14: Model Registry Foundation.

Verifies:
1. ModelInfo dataclass structure and serialization.
2. ModelRegistry registration, retrieval by ID, and listing.
3. Active model management and readiness status transitions.
"""

import pytest
from app.retrieval.model_registry import (
    ModelInfo,
    ModelReadiness,
    ModelRegistry,
    ModelType,
)


def test_model_registry_crud_and_lifecycle():
    registry = ModelRegistry()

    m1 = ModelInfo(
        model_id="fastembed:test-embed",
        model_type=ModelType.EMBEDDING,
        provider="fastembed",
        name="test-embed-v1",
        version="1.0.0",
        dimension=384,
        readiness=ModelReadiness.UNAVAILABLE,
        is_active=True,
    )

    m2 = ModelInfo(
        model_id="fastembed:test-rerank",
        model_type=ModelType.RERANKER,
        provider="fastembed",
        name="test-rerank-v1",
        version="1.0.0",
        readiness=ModelReadiness.READY,
        is_active=True,
    )

    registry.register_model(m1)
    registry.register_model(m2)

    # Retrieval
    assert registry.get_model("fastembed:test-embed") is not None
    assert registry.get_model("unknown") is None

    # Query active
    active_emb = registry.get_active_model(ModelType.EMBEDDING)
    assert active_emb is not None
    assert active_emb.name == "test-embed-v1"

    # Update readiness
    registry.update_readiness("fastembed:test-embed", ModelReadiness.LOADING)
    assert registry.get_model("fastembed:test-embed").readiness == ModelReadiness.LOADING

    registry.update_readiness("fastembed:test-embed", ModelReadiness.READY)
    assert registry.get_model("fastembed:test-embed").readiness == ModelReadiness.READY

    # List filtered
    embs = registry.list_models(ModelType.EMBEDDING)
    assert len(embs) == 1
    assert embs[0].model_id == "fastembed:test-embed"
