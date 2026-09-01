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


def test_sqlite_vec_store_validity_verification(test_db):
    """Verifies that SqliteVecStore validates index identity correctly against expected model."""
    with test_db.session() as conn:
        store = SqliteVecStore(conn, dimension=384)
        
        # When uninitialized, returns True
        assert store.verify_index_validity({
            "provider": "fastembed",
            "model_name": "sentence-transformers/all-MiniLM-L6-v2",
            "model_version": "1.0.0",
            "dimension": 384,
        }) is True

        # Upsert a dummy vector which records metadata
        store.upsert_vectors([
            {"chunk_id": "c1", "file_id": "f1", "embedding": [0.1] * 384}
        ])

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
