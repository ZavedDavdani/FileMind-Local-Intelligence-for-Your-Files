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


def test_batch_repository_methods_and_parameter_chunking(tmp_path):
    db = DatabaseManager(str(tmp_path / "batch_test.db"))
    with db.session() as conn:
        apply_migrations(conn)
        repo = Repository(conn)
        folder = repo.create_folder("C:/batch_corpus", True)
        # Create 600 files to exceed default batch chunk size of 500
        file_ids = []
        chunk_ids = []
        for i in range(600):
            fid = f"file-{i}"
            f = repo.upsert_file(
                folder_id=folder["folder_id"],
                path=f"C:/batch_corpus/file_{i}.md",
                relative_path=f"file_{i}.md",
                filename=f"file_{i}.md",
                extension=".md",
                size_bytes=100,
                modified_at="2026-01-01T00:00:00Z",
                mime_type="text/markdown",
                sha256=f"hash-{i}",
                index_status="INDEXED",
                file_id=fid,
            )
            file_ids.append(fid)
            cid = f"chunk-{i}"
            chunk_ids.append(cid)
            repo.replace_file_chunks(fid, [{
                "chunk_id": cid,
                "file_id": fid,
                "source_file": f["filename"],
                "source_path": f["path"],
                "content_hash": f"chash-{i}",
                "content": f"Content for file {i}",
                "token_count": 5,
                "metadata": {"custom_key": i},
            }])
            repo.upsert_document_insight(
                file_id=fid,
                status="READY",
                content_hash=f"hash-{i}",
                parser_version="1.0.0",
                chunker_version="1.0.0",
                model_provider="ollama",
                model_name=OLLAMA_MODEL,
                structural_summary={"headings": [f"H_{i}"]},
                executive_summary=f"Summary {i}",
                key_topics=[f"Topic {i % 10}"],
                key_decisions=[f"Decision {i}"],
                citations=[{"chunk_id": cid, "file_id": fid, "source_file": f["filename"], "source_path": f["path"], "content_hash": f"chash-{i}"}],
            )

        # Test get_chunks_by_files with chunk_size=200
        chunks_by_files = repo.get_chunks_by_files(file_ids, chunk_size=200)
        assert len(chunks_by_files) == 600
        assert chunks_by_files["file-0"][0]["metadata"] == {"custom_key": 0}

        # Test get_chunks_by_ids with chunk_size=200
        chunks_by_ids = repo.get_chunks_by_ids(chunk_ids, chunk_size=200)
        assert len(chunks_by_ids) == 600
        assert chunks_by_ids["chunk-599"]["chunk_id"] == "chunk-599"

        # Test get_document_insights_by_files with chunk_size=200
        insights_by_files = repo.get_document_insights_by_files(file_ids, model_name=OLLAMA_MODEL, chunk_size=200)
        assert len(insights_by_files) == 600
        assert insights_by_files["file-0"]["structural_summary"] == {"headings": ["H_0"]}
        assert insights_by_files["file-0"]["key_topics"] == ["Topic 0"]

        # Test empty input handling
        assert repo.get_chunks_by_files([]) == {}
        assert repo.get_chunks_by_ids([]) == {}
        assert repo.get_document_insights_by_files([]) == {}


def test_duplicate_filenames_only_match_relative_path(tmp_path):
    db = DatabaseManager(str(tmp_path / "dup_test.db"))
    with db.session() as conn:
        apply_migrations(conn)
        repo = Repository(conn)
        folder = repo.create_folder("C:/dup_corpus", True)

        # Two files with the same basename "notes.md" in different directories
        f1 = repo.upsert_file(
            folder_id=folder["folder_id"], path="C:/dup_corpus/a/notes.md", relative_path="a/notes.md",
            filename="notes.md", extension=".md", size_bytes=10, modified_at="2026-01-01T00:00:00Z",
            mime_type="text/markdown", sha256="h1", index_status="INDEXED",
        )
        f2 = repo.upsert_file(
            folder_id=folder["folder_id"], path="C:/dup_corpus/b/notes.md", relative_path="b/notes.md",
            filename="notes.md", extension=".md", size_bytes=10, modified_at="2026-01-01T00:00:00Z",
            mime_type="text/markdown", sha256="h2", index_status="INDEXED",
        )
        # Source file referencing only "notes.md" (not "a/notes.md" or "b/notes.md")
        source = repo.upsert_file(
            folder_id=folder["folder_id"], path="C:/dup_corpus/source.md", relative_path="source.md",
            filename="source.md", extension=".md", size_bytes=10, modified_at="2026-01-01T00:00:00Z",
            mime_type="text/markdown", sha256="h_src", index_status="INDEXED",
        )
        repo.replace_file_chunks(source["file_id"], [{
            "chunk_id": "c-src", "file_id": source["file_id"], "source_file": "source.md",
            "source_path": source["path"], "content_hash": "c-h_src",
            "content": "Please check notes.md for info. Also check a/notes.md specifically.",
            "token_count": 10, "metadata": {},
        }])

    service = KnowledgeConnectionService(db)
    res = service.get_connections(source["file_id"])
    ref_connections = [c for c in res["connections"] if c["connection_type"] == "file_reference"]

    # "a/notes.md" should match f1 because of the explicit relative path
    # "notes.md" alone should NOT match f2 because "notes.md" is ambiguous across f1 and f2
    assert len(ref_connections) == 1
    assert ref_connections[0]["target_file"]["file_id"] == f1["file_id"]
    assert ref_connections[0]["label"] == "a/notes.md"
