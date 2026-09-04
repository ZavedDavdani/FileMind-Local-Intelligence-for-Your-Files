"""Focused tests for Phase 6 domain repository classes."""

import os
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


@pytest.fixture
def test_db(tmp_path):
    db = DatabaseManager(str(tmp_path / "domain_repos.db"))
    with db.session() as conn:
        apply_migrations(conn)
    return db


def test_individual_domain_repositories_instantiation(test_db):
    with test_db.session() as conn:
        folder_repo = FolderRepository(conn)
        file_repo = FileRepository(conn)
        job_repo = JobRepository(conn)
        event_repo = EventRepository(conn)
        chunk_repo = ChunkRepository(conn)
        insight_repo = InsightRepository(conn)

        # 1. Folder operations
        folder = folder_repo.create_folder("C:/domain_test", True)
        assert folder["path"] == "C:/domain_test"
        assert folder_repo.get_folder(folder["folder_id"]) is not None

        # 2. File operations
        file_rec = file_repo.upsert_file(
            folder_id=folder["folder_id"],
            path="C:/domain_test/file.txt",
            relative_path="file.txt",
            filename="file.txt",
            extension=".txt",
            size_bytes=100,
            modified_at="2026-01-01T00:00:00Z",
            sha256="test-hash",
            index_status="INDEXED",
        )
        assert file_rec["file_id"] is not None
        assert file_repo.get_file_by_id(file_rec["file_id"]) is not None

        # 3. Job operations
        job = job_repo.enqueue_job(
            file_id=file_rec["file_id"],
            folder_id=folder["folder_id"],
            job_type="METADATA_DISCOVERY",
            priority=1,
        )
        assert job["status"] == "PENDING"
        claimed = job_repo.claim_next_job()
        assert claimed is not None
        assert claimed["job_id"] == job["job_id"]

        # 4. Event operations
        event = event_repo.log_event(
            folder_id=folder["folder_id"],
            event_type="CREATE",
            path="C:/domain_test/file.txt",
            file_id=file_rec["file_id"],
        )
        assert event["event_type"] == "CREATE"
        events = event_repo.list_events(folder_id=folder["folder_id"])
        assert len(events) == 1

        # 5. Chunk operations
        chunk_repo.replace_file_chunks(file_rec["file_id"], [{
            "chunk_id": "c-1",
            "file_id": file_rec["file_id"],
            "source_file": "file.txt",
            "source_path": "C:/domain_test/file.txt",
            "content": "Hello chunk content",
            "content_hash": "c-hash",
            "token_count": 3,
            "metadata": {"section": "intro"},
        }])
        chunks = chunk_repo.get_chunks_by_file(file_rec["file_id"])
        assert len(chunks) == 1
        assert chunks[0]["metadata"] == {"section": "intro"}

        # 6. Insight operations
        insight = insight_repo.upsert_document_insight(
            file_id=file_rec["file_id"],
            status="READY",
            content_hash="test-hash",
            parser_version="1.0",
            chunker_version="1.0",
            model_provider="ollama",
            model_name="test-model",
            structural_summary={"headings": ["Intro"]},
            executive_summary="Executive summary text",
            key_topics=["Topic A"],
            key_decisions=["Decision A"],
            citations=[],
        )
        assert insight["executive_summary"] == "Executive summary text"
        retrieved_insight = insight_repo.get_document_insight(file_rec["file_id"], model_name="test-model")
        assert retrieved_insight is not None
        assert retrieved_insight["key_topics"] == ["Topic A"]


def test_repository_facade_composes_all_domains(test_db):
    with test_db.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder("C:/facade_test", True)
        file_rec = repo.upsert_file(
            folder_id=folder["folder_id"],
            path="C:/facade_test/f.txt",
            relative_path="f.txt",
            filename="f.txt",
            extension=".txt",
            size_bytes=50,
            modified_at="2026-01-01T00:00:00Z",
            sha256="f-hash",
            index_status="INDEXED",
        )
        assert repo.get_folder(folder["folder_id"]) is not None
        assert repo.get_file_by_id(file_rec["file_id"]) is not None
        assert repo.count_files() == 1
