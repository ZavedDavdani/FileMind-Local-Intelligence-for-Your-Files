"""Focused regression coverage for Batch 4 integrity findings."""

import os
import tempfile

import pytest

from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.db.repository import Repository


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = DatabaseManager(path)
    with db.session() as conn:
        apply_migrations(conn)
    yield db
    os.remove(path)


def test_change_during_processing_queues_successor_and_blocks_stale_completion(temp_db):
    """An edit during v1 processing must leave v2 queued and current."""
    with temp_db.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder("C:/batch4")
        file_rec = repo.upsert_file(
            folder_id=folder["folder_id"], path="C:/batch4/doc.txt",
            relative_path="doc.txt", filename="doc.txt", extension=".txt",
            size_bytes=10, modified_at="2026-09-02T10:00:00Z", index_status="QUEUED",
        )
        old_job = repo.enqueue_job(file_rec["file_id"], folder["folder_id"], "DOCUMENT_PARSE")
        assert repo.claim_next_job()["job_id"] == old_job["job_id"]

        # The discovery/watcher update for v2 arrives while v1 is still parsing.
        repo.upsert_file(
            folder_id=folder["folder_id"], path="C:/batch4/doc.txt",
            relative_path="doc.txt", filename="doc.txt", extension=".txt",
            size_bytes=20, modified_at="2026-09-02T11:00:00Z", index_status="QUEUED",
            file_id=file_rec["file_id"],
        )
        new_job = repo.enqueue_job(file_rec["file_id"], folder["folder_id"], "DOCUMENT_PARSE")
        assert new_job["job_id"] != old_job["job_id"]
        assert repo.is_current_processing_job(old_job["job_id"], file_rec["file_id"]) is False

        # v1 finishing later cannot turn the v2 record back into INDEXED.
        repo.complete_job(old_job["job_id"], file_rec["file_id"], sha256="v1", final_status="INDEXED")
        current = repo.get_file_by_id(file_rec["file_id"])
        assert current["index_status"] == "QUEUED"
        assert current["sha256"] is None

        assert repo.claim_next_job()["job_id"] == new_job["job_id"]
        repo.complete_job(new_job["job_id"], file_rec["file_id"], sha256="v2", final_status="INDEXED")
        current = repo.get_file_by_id(file_rec["file_id"])
        assert current["index_status"] == "INDEXED"
        assert current["sha256"] == "v2"
