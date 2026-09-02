"""Tests for Batch 4 Requirement 3: Embedding Model Identity & Vector Index Validity.

Verifies:
1. Migration V5 creates embedding_index_metadata table.
2. Embedding identity is persisted and retrieved through Repository.
3. SqliteVecStore.verify_index_validity accurately detects model, provider, version, and dimension mismatches.
"""

import sqlite3
import pytest
from app.db.connection import DatabaseManager
from app.db.repository import Repository
from app.retrieval.vector_store import SqliteVecStore


from app.db.migrations import apply_migrations


@pytest.fixture
def test_db(tmp_path):
    db_file = tmp_path / "test_embedding_identity.db"
    db_manager = DatabaseManager(str(db_file))
    with db_manager.session() as conn:
        apply_migrations(conn)
    return db_manager



def test_embedding_metadata_persistence(test_db):
    """Verifies that embedding metadata can be set and queried through Repository."""
    with test_db.session() as conn:
        repo = Repository(conn)
        # Initially empty
        assert repo.get_embedding_metadata() is None

        # Set metadata
        repo.set_embedding_metadata(
            provider="fastembed",
            model_name="sentence-transformers/all-MiniLM-L6-v2",
            model_version="1.0.0",
            dimension=384,
            config={"normalize": True},
        )

        meta = repo.get_embedding_metadata()
        assert meta is not None
        assert meta["provider"] == "fastembed"
        assert meta["model_name"] == "sentence-transformers/all-MiniLM-L6-v2"
        assert meta["model_version"] == "1.0.0"
        assert meta["dimension"] == 384
        assert meta["config"] == {"normalize": True}


def test_sqlite_vec_store_upsert_does_not_fabricate_metadata(test_db):
    """Verifies that direct upsert_vectors does NOT create hardcoded default metadata."""
    with test_db.session() as conn:
        store = SqliteVecStore(conn, dimension=384)
        assert store.get_index_metadata() is None

        # Upsert a vector directly
        store.upsert_vectors([
            {"chunk_id": "c1", "file_id": "f1", "embedding": [0.1] * 384}
        ])

        # Metadata must remain None (not hardcoded to MiniLM)
        assert store.get_index_metadata() is None
        assert store.count() == 1


def test_sqlite_vec_store_custom_dimension_does_not_fabricate_metadata(test_db):
    """Verifies that small/custom dimension vector stores do not get stamped with default 384-dim model metadata."""
    with test_db.session() as conn:
        store_4d = SqliteVecStore(conn, dimension=4)
        assert store_4d.get_index_metadata() is None

        # Upsert a 4-dimensional vector
        store_4d.upsert_vectors([
            {"chunk_id": "c_4d", "file_id": "f_4d", "embedding": [1.0, 0.0, 0.0, 0.0]}
        ])

        # Metadata must remain None (must not claim MiniLM is dimension 4)
        assert store_4d.get_index_metadata() is None
        assert store_4d.count() == 1

        # Explicitly recording custom metadata works
        store_4d.set_index_metadata(
            provider="test-provider",
            model_name="test-4d-model",
            model_version="0.1.0",
            dimension=4,
        )
        meta = store_4d.get_index_metadata()
        assert meta == {
            "provider": "test-provider",
            "model_name": "test-4d-model",
            "model_version": "0.1.0",
            "dimension": 4,
        }
        assert store_4d.verify_index_validity({
            "provider": "test-provider",
            "model_name": "test-4d-model",
            "model_version": "0.1.0",
            "dimension": 4,
        }) is True


def test_sqlite_vec_store_validity_verification(test_db):
    """Verifies that SqliteVecStore validates index identity correctly against expected model when metadata is recorded."""
    with test_db.session() as conn:
        store = SqliteVecStore(conn, dimension=384)
        
        # When uninitialized (no metadata recorded), returns True
        assert store.verify_index_validity({
            "provider": "fastembed",
            "model_name": "sentence-transformers/all-MiniLM-L6-v2",
            "model_version": "1.0.0",
            "dimension": 384,
        }) is True

        # Upsert a dummy vector (does not write metadata)
        store.upsert_vectors([
            {"chunk_id": "c1", "file_id": "f1", "embedding": [0.1] * 384}
        ])
        assert store.get_index_metadata() is None

        # Explicitly record active embedding identity (as production worker does)
        store.set_index_metadata(
            provider="fastembed",
            model_name="sentence-transformers/all-MiniLM-L6-v2",
            model_version="1.0.0",
            dimension=384,
        )

        # Matching identity -> True
        assert store.verify_index_validity({
            "provider": "fastembed",
            "model_name": "sentence-transformers/all-MiniLM-L6-v2",
            "model_version": "1.0.0",
            "dimension": 384,
        }) is True

        # Mismatched model name -> False
        assert store.verify_index_validity({
            "provider": "fastembed",
            "model_name": "BAAI/bge-small-en-v1.5",
            "model_version": "1.0.0",
            "dimension": 384,
        }) is False

        # Mismatched version -> False
        assert store.verify_index_validity({
            "provider": "fastembed",
            "model_name": "sentence-transformers/all-MiniLM-L6-v2",
            "model_version": "2.0.0",
            "dimension": 384,
        }) is False

        # Mismatched provider -> False
        assert store.verify_index_validity({
            "provider": "ollama",
            "model_name": "sentence-transformers/all-MiniLM-L6-v2",
            "model_version": "1.0.0",
            "dimension": 384,
        }) is False

        # Mismatched dimension -> False
        assert store.verify_index_validity({
            "provider": "fastembed",
            "model_name": "sentence-transformers/all-MiniLM-L6-v2",
            "model_version": "1.0.0",
            "dimension": 768,
        }) is False
