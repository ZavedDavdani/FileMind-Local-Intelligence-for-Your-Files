"""Tests for FileMind Application Dependency Context (AppContext) and Dependency Injection."""

import tempfile
import pytest
from fastapi.testclient import TestClient

from app.core.context import AppContext, default_app_context
from app.core.deps import get_app_context, get_db, get_repo
from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.db.repository import Repository
from app.main import app
from app.retrieval.model_registry import ModelRegistry, ModelType, ModelInfo, ModelReadiness


@pytest.fixture
def temp_db():
    """Provides an isolated in-memory or temp SQLite database with migrations applied."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    manager = DatabaseManager(db_path=db_path)
    with manager.session() as conn:
        apply_migrations(conn)
    yield manager


def test_app_context_defaults():
    """Verifies that default_app_context and default AppContext instantiate all runtime singletons."""
    ctx = AppContext()
    assert ctx.db_manager is not None
    assert ctx.embedding_engine is not None
    assert ctx.reranker is not None
    assert ctx.model_registry is not None
    assert ctx.generation_coordinator is not None
    assert ctx.engine_coordinator is not None

    # Verify default_app_context singleton
    assert default_app_context.db_manager is ctx.db_manager
    assert default_app_context.embedding_engine is ctx.embedding_engine


def test_app_context_custom_components(temp_db):
    """Verifies that custom components can be supplied to AppContext for isolated testing."""
    custom_registry = ModelRegistry()
    custom_ctx = AppContext(
        db_manager=temp_db,
        model_registry=custom_registry,
    )
    assert custom_ctx.db_manager is temp_db
    assert custom_ctx.model_registry is custom_registry


def test_get_app_context_resolution():
    """Verifies get_app_context falls back to default when no request is passed."""
    resolved = get_app_context(None)
    assert resolved is default_app_context


def test_get_db_and_get_repo_with_custom_context(temp_db):
    """Verifies get_db and get_repo resolve using the injected AppContext."""
    custom_ctx = AppContext(db_manager=temp_db)
    resolved_db = get_db(custom_ctx)
    assert resolved_db is temp_db

    repo_gen = get_repo(resolved_db)
    repo = next(repo_gen)
    assert isinstance(repo, Repository)
    # Check that repo queries the temp_db
    assert repo.list_folders() == []


def test_api_route_with_app_context_override(temp_db):
    """Verifies that overriding get_app_context in FastAPI dependency_overrides works end-to-end."""
    custom_registry = ModelRegistry()
    custom_registry.register_model(
        ModelInfo(
            model_id="fastembed:custom-test-embedder",
            name="custom-test-embedder",
            model_type=ModelType.EMBEDDING,
            provider="fastembed",
            dimension=384,
            readiness=ModelReadiness.READY,
            is_active=True,
        )
    )

    custom_ctx = AppContext(
        db_manager=temp_db,
        model_registry=custom_registry,
    )

    client = TestClient(app)

    # Set dependency override
    app.dependency_overrides[get_app_context] = lambda: custom_ctx
    try:
        response = client.get("/ai/status")
        assert response.status_code == 200
        data = response.json()
        assert data["local_ai"]["embedding"]["model_name"] == "custom-test-embedder"
        assert data["local_ai"]["embedding"]["status"] == "ready"
    finally:
        app.dependency_overrides.pop(get_app_context, None)


def test_search_route_with_app_context_override(temp_db):
    """Verifies /search endpoint works with custom AppContext."""
    custom_ctx = AppContext(db_manager=temp_db)
    client = TestClient(app)

    app.dependency_overrides[get_app_context] = lambda: custom_ctx
    try:
        response = client.post(
            "/search",
            json={"query": "test query", "top_k": 5, "mode": "bm25", "quality": "fast"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "results" in data
        assert data["total_found"] == 0
    finally:
        app.dependency_overrides.pop(get_app_context, None)
