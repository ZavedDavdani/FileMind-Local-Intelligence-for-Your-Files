"""Focused Phase 5.5 Batch 3.2 connection regression tests."""

import pytest
from fastapi.testclient import TestClient

from app.ai.knowledge_connections import KnowledgeConnectionService
from app.core.config import OLLAMA_MODEL
from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.db.repository import Repository


@pytest.fixture
def corpus(tmp_path):
    db = DatabaseManager(str(tmp_path / "connections.db"))
    with db.session() as conn:
        apply_migrations(conn)
        repo = Repository(conn)
        folder = repo.create_folder("C:/corpus", True)
        files = {}
        for name, content, digest in [
            ("source.md", "See target.md and docs/target.md for the project plan.", "source-hash"),
            ("target.md", "The target file contains the project plan.", "target-hash"),
            ("other.md", "Independent content.", "other-hash"),
        ]:
            f = repo.upsert_file(
                folder_id=folder["folder_id"], path=f"C:/corpus/{name}", relative_path=name,
                filename=name, extension=".md", size_bytes=10, modified_at="2026-01-01T00:00:00Z",
                mime_type="text/markdown", sha256=digest, index_status="INDEXED",
            )
            files[name] = f
            repo.replace_file_chunks(f["file_id"], [{
                "chunk_id": f"chunk-{name}", "file_id": f["file_id"], "source_file": name,
                "source_path": f"C:/corpus/{name}", "content_hash": f"chunk-{digest}",
                "content": content, "token_count": 10, "metadata": {},
            }])
        for name, topic in [("source.md", "Project Plan"), ("target.md", " project   plan "), ("other.md", "Other")]:
            f = files[name]
            chunk_versions = repo.get_chunks_by_file(f["file_id"])[0]
            repo.upsert_document_insight(
                f["file_id"], "READY", f["sha256"], chunk_versions["parser_version"], chunk_versions["chunker_version"], "ollama", OLLAMA_MODEL,
                structural_summary={}, executive_summary="Grounded", key_topics=[topic], key_decisions=[],
                citations=[{"chunk_id": f"chunk-{name}", "file_id": f["file_id"], "source_file": name,
                            "source_path": f["path"], "content_hash": f"chunk-{f['sha256']}"}],
            )
    return db, files


def test_connections_are_explainable_deterministic_and_deduplicated(corpus):
    db, files = corpus
    service = KnowledgeConnectionService(db)
    first = service.get_connections(files["source.md"]["file_id"])
    second = service.get_connections(files["source.md"]["file_id"])
    assert first == second
    target = [c for c in first["connections"] if c["target_file"]["file_id"] == files["target.md"]["file_id"]]
    assert {c["connection_type"] for c in target} == {"shared_topic", "file_reference"}
    assert all(c["source_evidence"] for c in target)
    assert all(c["target_file"]["content_hash"] for c in target)
    assert all(c["target_file"]["file_id"] != files["source.md"]["file_id"] for c in first["connections"])


def test_stale_target_insight_does_not_produce_shared_topic_connection(corpus):
    db, files = corpus
    with db.session() as conn:
        repo = Repository(conn)
        repo.upsert_file(
            folder_id=files["target.md"]["folder_id"], path=files["target.md"]["path"],
            relative_path="target.md", filename="target.md", extension=".md", size_bytes=10,
            modified_at="2026-01-02T00:00:00Z", mime_type="text/markdown",
            sha256="changed-hash", index_status="INDEXED",
        )
    result = KnowledgeConnectionService(db).get_connections(files["source.md"]["file_id"])
    assert all(c["connection_type"] != "shared_topic" for c in result["connections"])


def test_missing_source_is_not_persisted_or_silently_recovered(corpus):
    db, _ = corpus
    with pytest.raises(ValueError):
        KnowledgeConnectionService(db).get_connections("missing")


def test_api_returns_404_for_missing_source(corpus, monkeypatch):
    db, _ = corpus
    import app.main as main
    monkeypatch.setattr(main, "db_manager", db)
    response = TestClient(main.app).get("/ai/connections/missing")
    assert response.status_code == 404
