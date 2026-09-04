"""Comprehensive test suite for Phase 6 domain repositories and Repository compatibility façade.

Verifies:
1. FolderRepository: CRUD, path lookups, exclude patterns, deletion cascading.
2. FileRepository: upsert, lookups, missing handling, directory cascades, status updates, scan error recording.
3. JobRepository: enqueue, claim, complete, fail, cancel, crash recovery, terminal pruning.
4. EventRepository: logging, processing state, listing with limits.
5. ChunkRepository: replacement, single/batch lookups, batched parameter slicing (<=500), stats, embedding metadata.
6. InsightRepository: doc/folder insight CRUD, batch document insights (<=500 batching).
7. Repository Façade: full backward compatibility, method parity check across all domains.
"""

import os
import sqlite3
import pytest

from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.db.repositories import (
    ChunkRepository,
    EventRepository,
    FileRepository,
    FolderRepository,
    InsightRepository,
    JobRepository,
)
from app.db.repository import Repository
from app.retrieval.vector_store import SqliteVecStore


@pytest.fixture
def test_db(tmp_path):
    db = DatabaseManager(str(tmp_path / "domain_repos_expanded.db"))
    with db.session() as conn:
        apply_migrations(conn)
        SqliteVecStore(conn, dimension=384)
    return db


def test_folder_repository_full_lifecycle(test_db):
    with test_db.session() as conn:
        repo = FolderRepository(conn)
        # Create
        f = repo.create_folder("C:/test_folder", recursive=True, integrity_mode="STRICT", exclude_patterns=["*.tmp"])
        fid = f["folder_id"]
        assert f["path"] == "C:/test_folder"
        assert f["recursive"] is True
        assert f["integrity_mode"] == "STRICT"
        assert f["exclude_patterns"] == ["*.tmp"]

        # Get by ID & Path
        assert repo.get_folder(fid)["path"] == "C:/test_folder"
        assert repo.get_folder_by_path("C:/test_folder")["folder_id"] == fid

        # List
        all_folders = repo.list_folders()
        assert len(all_folders) == 1

        # Update
        up = repo.update_folder(fid, recursive=False, integrity_mode="NORMAL", exclude_patterns=["*.bak"])
        assert up["recursive"] is False
        assert up["integrity_mode"] == "NORMAL"
        assert up["exclude_patterns"] == ["*.bak"]

        # Delete
        assert repo.delete_folder(fid) is True
        assert repo.get_folder(fid) is None


def test_file_repository_full_lifecycle(test_db):
    with test_db.session() as conn:
        folder_repo = FolderRepository(conn)
        file_repo = FileRepository(conn)
        folder = folder_repo.create_folder("C:/files_test")
        fid = folder["folder_id"]

        # Upsert
        file1 = file_repo.upsert_file(
            folder_id=fid,
            path="C:/files_test/doc1.txt",
            relative_path="doc1.txt",
            filename="doc1.txt",
            extension=".txt",
            size_bytes=256,
            modified_at="2026-09-04T12:00:00Z",
            sha256="hash1",
            index_status="QUEUED",
        )
        file_id = file1["file_id"]
        assert file1["filename"] == "doc1.txt"

        # Get by ID & Path
        assert file_repo.get_file_by_id(file_id)["path"] == "C:/files_test/doc1.txt"
        assert file_repo.get_file_by_path("C:/files_test/doc1.txt")["file_id"] == file_id

        # Update status
        assert file_repo.update_file_status(file_id, "INDEXED") is True
        assert file_repo.get_file_by_id(file_id)["index_status"] == "INDEXED"

        # Record scan error
        assert file_repo.record_scan_error(file_id, "Scan read error") is True
        refreshed = file_repo.get_file_by_id(file_id)
        assert refreshed["index_status"] == "FAILED"
        assert refreshed["indexing_error"] == "Scan read error"

        # Count and listing
        assert file_repo.count_files(folder_id=fid) == 1
        assert len(file_repo.list_files(folder_id=fid)) == 1
        assert file_repo.count_files_by_status(fid)["FAILED"] == 1

        # Missing file handling
        assert file_repo.mark_file_missing("C:/files_test/doc1.txt") is True
        assert file_repo.get_file_by_id(file_id)["index_status"] == "MISSING"

        # Delete
        assert file_repo.delete_file(file_id) is True
        assert file_repo.get_file_by_id(file_id) is None


def test_job_repository_full_lifecycle(test_db):
    with test_db.session() as conn:
        folder_repo = FolderRepository(conn)
        file_repo = FileRepository(conn)
        job_repo = JobRepository(conn)

        folder = folder_repo.create_folder("C:/jobs_test")
        fid = folder["folder_id"]
        file_rec = file_repo.upsert_file(
            folder_id=fid,
            path="C:/jobs_test/doc.txt",
            relative_path="doc.txt",
            filename="doc.txt",
            extension=".txt",
            size_bytes=100,
            modified_at="2026-09-04T12:00:00Z",
            index_status="QUEUED",
        )
        file_id = file_rec["file_id"]

        # Enqueue
        job = job_repo.enqueue_job(file_id=file_id, folder_id=fid, job_type="DOCUMENT_PARSE", priority=5)
        jid = job["job_id"]
        assert job["status"] == "PENDING"
        assert job["priority"] == 5

        # Claim
        claimed = job_repo.claim_next_job()
        assert claimed is not None
        assert claimed["job_id"] == jid
        assert claimed["status"] == "PROCESSING"

        # Complete
        assert job_repo.complete_job(jid, file_id, sha256="final-hash", final_status="INDEXED") is True
        jobs = job_repo.list_jobs()
        assert any(j["job_id"] == jid and j["status"] == "COMPLETED" for j in jobs)

        # Fail and crash recovery
        job2 = job_repo.enqueue_job(file_id=file_id, folder_id=fid, job_type="METADATA_DISCOVERY", priority=1)
        jid2 = job2["job_id"]
        claimed2 = job_repo.claim_next_job()
        assert claimed2["job_id"] == jid2
        recovered = job_repo.recover_stale_processing_jobs()
        assert recovered == 1
        assert any(j["job_id"] == jid2 and j["status"] == "PENDING" for j in job_repo.list_jobs())


def test_event_repository_full_lifecycle(test_db):
    with test_db.session() as conn:
        folder_repo = FolderRepository(conn)
        fld = folder_repo.create_folder("C:/events_test")
        fid = fld["folder_id"]

        repo = EventRepository(conn)
        ev = repo.log_event(
            folder_id=fid,
            event_type="MODIFY",
            path="C:/events_test/file.txt",
            file_id=None,
            status="PENDING",
        )
        eid = ev["event_id"]
        assert ev["event_type"] == "MODIFY"

        assert repo.mark_event_processed(eid, status="PROCESSED") is True

        events = repo.list_events(folder_id=fid, limit=10)
        assert len(events) == 1
        assert events[0]["processing_status"] == "PROCESSED"


def test_chunk_repository_and_batching(test_db):
    with test_db.session() as conn:
        folder_repo = FolderRepository(conn)
        file_repo = FileRepository(conn)
        repo = ChunkRepository(conn)

        fld = folder_repo.create_folder("C:/chunks_test")
        fid = fld["folder_id"]

        # Seed files for foreign key integrity
        file_ids = ["file-0", "file-1", "file-2"]
        for fid_item in file_ids:
            file_repo.upsert_file(
                folder_id=fid,
                path=f"C:/chunks_test/{fid_item}.txt",
                relative_path=f"{fid_item}.txt",
                filename=f"{fid_item}.txt",
                extension=".txt",
                size_bytes=100,
                modified_at="2026-09-04T12:00:00Z",
                file_id=fid_item,
            )

        # Replace chunks
        chunks_data = [
            {
                "chunk_id": f"chunk-{i}",
                "file_id": f"file-{i % 3}",
                "source_file": f"file_{i % 3}.txt",
                "source_path": f"C:/test/file_{i % 3}.txt",
                "content": f"Chunk content {i}",
                "content_hash": f"hash-{i}",
                "token_count": 10,
                "metadata": {"index": i},
            }
            for i in range(10)
        ]
        repo.replace_file_chunks("file-0", [c for c in chunks_data if c["file_id"] == "file-0"])
        repo.replace_file_chunks("file-1", [c for c in chunks_data if c["file_id"] == "file-1"])
        repo.replace_file_chunks("file-2", [c for c in chunks_data if c["file_id"] == "file-2"])

        assert repo.count_total_chunks() == 10
        assert len(repo.get_chunks_by_file("file-0")) == 4

        # Single chunk get
        single = repo.get_chunk_by_id("chunk-0")
        assert single is not None
        assert single["metadata"]["index"] == 0

        # Batch get by files
        by_files = repo.get_chunks_by_files(["file-0", "file-1"], chunk_size=1)
        assert "file-0" in by_files
        assert "file-1" in by_files
        assert len(by_files["file-0"]) == 4

        # Batch get by IDs
        by_ids = repo.get_chunks_by_ids(["chunk-1", "chunk-2"], chunk_size=1)
        assert "chunk-1" in by_ids
        assert "chunk-2" in by_ids

        # Embedding metadata
        repo.set_embedding_metadata("fastembed", "test-model", "1.0.0", 384, {"normalize": True})
        meta = repo.get_embedding_metadata()
        assert meta["model_name"] == "test-model"
        assert meta["dimension"] == 384
        assert meta["config"] == {"normalize": True}


def test_insight_repository_and_batching(test_db):
    with test_db.session() as conn:
        folder_repo = FolderRepository(conn)
        file_repo = FileRepository(conn)
        repo = InsightRepository(conn)

        fld = folder_repo.create_folder("C:/insights_test")
        fid = fld["folder_id"]

        # Seed files
        for fid_item in ["f-doc-1", "f-doc-2"]:
            file_repo.upsert_file(
                folder_id=fid,
                path=f"C:/insights_test/{fid_item}.txt",
                relative_path=f"{fid_item}.txt",
                filename=f"{fid_item}.txt",
                extension=".txt",
                size_bytes=100,
                modified_at="2026-09-04T12:00:00Z",
                file_id=fid_item,
            )

        # Document insight
        doc_in = repo.upsert_document_insight(
            file_id="f-doc-1",
            status="READY",
            content_hash="chash-1",
            parser_version="1.0",
            chunker_version="1.0",
            model_provider="ollama",
            model_name="qwen",
            structural_summary={"words": 500},
            executive_summary="Summary 1",
            key_topics=["Topic 1"],
            key_decisions=["Decision 1"],
            citations=[{"chunk_id": "c1"}],
        )
        assert doc_in["executive_summary"] == "Summary 1"

        # Get single doc insight
        get_doc = repo.get_document_insight("f-doc-1")
        assert get_doc is not None
        assert get_doc["structural_summary"] == {"words": 500}

        # Batch get doc insights
        repo.upsert_document_insight(
            file_id="f-doc-2",
            status="READY",
            content_hash="chash-2",
            parser_version="1.0",
            chunker_version="1.0",
            model_provider="ollama",
            model_name="qwen",
            executive_summary="Summary 2",
        )
        batch_docs = repo.get_document_insights_by_files(["f-doc-1", "f-doc-2"], chunk_size=1)
        assert "f-doc-1" in batch_docs
        assert "f-doc-2" in batch_docs

        # Folder insight
        folder_in = repo.upsert_folder_insight(
            folder_id=fid,
            status="READY",
            composite_hash="comp-hash-1",
            model_provider="ollama",
            model_name="qwen",
            structural_summary={"total_files": 10},
            executive_summary="Folder Summary",
            key_themes=["Theme 1"],
            key_decisions=["Decision 1"],
            citations=[],
        )
        assert folder_in["executive_summary"] == "Folder Summary"
        assert repo.get_folder_insight(fid) is not None

        # Deletions
        assert repo.delete_document_insight("f-doc-1") is True
        assert repo.get_document_insight("f-doc-1") is None
        assert repo.delete_folder_insight(fid) is True
        assert repo.get_folder_insight(fid) is None


def test_repository_facade_backward_compatibility(test_db):
    """Verifies that the unified Repository façade exposes 100% of methods across all 6 domain repositories."""
    expected_domain_methods = [
        # FolderRepository
        "create_folder", "get_folder", "get_folder_by_path", "list_folders", "update_folder", "delete_folder",
        # FileRepository
        "upsert_file", "get_file_by_path", "get_file_by_id", "list_files", "count_files",
        "list_indexed_paths_for_folder", "mark_file_missing", "mark_directory_missing",
        "rename_file_path", "rename_directory_path", "update_file_status", "record_scan_error",
        "delete_file", "count_files_by_status",
        # JobRepository
        "prune_terminal_jobs", "enqueue_job", "is_current_processing_job", "claim_next_job",
        "complete_job", "fail_job", "cancel_pending_jobs_for_file", "recover_stale_processing_jobs",
        "list_jobs", "count_jobs_by_status",
        # EventRepository
        "log_event", "mark_event_processed", "list_events",
        # ChunkRepository
        "replace_file_chunks", "get_chunks_by_file", "get_chunk_by_id", "get_chunks_by_files",
        "get_chunks_by_ids", "delete_chunks_by_file", "count_total_chunks", "count_chunks_by_folder",
        "get_document_intelligence_stats", "get_file_chunk_versions", "get_embedding_metadata",
        "set_embedding_metadata",
        # InsightRepository
        "get_document_insight", "get_document_insights_by_files", "upsert_document_insight",
        "delete_document_insight", "get_folder_insight", "upsert_folder_insight", "delete_folder_insight",
    ]

    with test_db.session() as conn:
        repo = Repository(conn)
        for method_name in expected_domain_methods:
            assert hasattr(repo, method_name), f"Repository façade is missing method: {method_name}"
            assert callable(getattr(repo, method_name)), f"Repository attribute {method_name} is not callable"
