"""Tests for Bug 3: Vector-write skip on model mismatch populates indexing_error while keeping INDEXED.

Verifies:
1. Model identity mismatch skips vector writing, preserves INDEXED status, and populates indexing_error.
2. BM25 / relational chunks are preserved during mismatch.
3. Matching model identity successfully writes vectors and keeps indexing_error clean (None).
4. Combination of PARSE_WARNING and vector mismatch merges both messages into indexing_error.
5. Embedding generation failure populates indexing_error as a warning while keeping INDEXED.
"""

import os
import unittest.mock as mock
import pytest

from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.db.repository import Repository
from app.engine.worker import WorkerPool
from app.intelligence.models import Document, DocumentElement, ElementType
from app.intelligence.parsers.quality import PDFQualityAssessment



@pytest.fixture
def test_db(tmp_path):
    db_file = tmp_path / "test_vector_visibility.db"
    db_manager = DatabaseManager(str(db_file))
    with db_manager.session() as conn:
        apply_migrations(conn)
    return db_manager


def test_vector_mismatch_populates_indexing_error_and_keeps_indexed(test_db, tmp_path):
    # Setup test file on disk
    test_dir = tmp_path / "docs"
    test_dir.mkdir()
    doc_file = test_dir / "sample.txt"
    doc_file.write_text("The quick brown fox jumps over the lazy dog. A second sentence for chunking.", encoding="utf-8")
    doc_path = os.path.normpath(str(doc_file))

    with test_db.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder(str(test_dir))
        folder_id = folder["folder_id"]

        # Seed embedding metadata with an incompatible model
        repo.set_embedding_metadata(
            provider="fastembed",
            model_name="nomic-ai/nomic-embed-text-v1.5",
            model_version="1.0.0",
            dimension=768,
        )

        file_rec = repo.upsert_file(
            folder_id=folder_id,
            path=doc_path,
            relative_path="sample.txt",
            filename="sample.txt",
            extension=".txt",
            size_bytes=os.path.getsize(doc_path),
            modified_at="2026-09-04T12:00:00Z",
            index_status="QUEUED",
        )
        file_id = file_rec["file_id"]

        job_rec = repo.enqueue_job(
            file_id=file_id,
            folder_id=folder_id,
            job_type="DOCUMENT_PARSE",
            priority=1,
        )
        job_id = job_rec["job_id"]

    # Process job using WorkerPool
    pool = WorkerPool(test_db, max_workers=1)
    with test_db.session() as conn:
        repo = Repository(conn)
        job = repo.claim_next_job()
    assert job is not None
    pool._process_job(job)

    # Verify DB state
    with test_db.session() as conn:
        repo = Repository(conn)
        # Job must be COMPLETED
        jobs = [j for j in repo.list_jobs() if j["job_id"] == job_id]
        assert len(jobs) == 1
        assert jobs[0]["status"] == "COMPLETED"

        # File must be INDEXED (BM25 indexed), NOT FAILED

        refreshed_file = repo.get_file_by_id(file_id)
        assert refreshed_file["index_status"] == "INDEXED"

        # indexing_error MUST contain the vector mismatch explanation
        assert refreshed_file["indexing_error"] is not None
        assert "Vector write skipped" in refreshed_file["indexing_error"]
        assert "differs from existing vector index" in refreshed_file["indexing_error"]

        # Relational chunks must exist for BM25 search
        chunks = repo.get_chunks_by_file(file_id)
        assert len(chunks) > 0


def test_matching_identity_clears_indexing_error(test_db, tmp_path):
    test_dir = tmp_path / "docs_clean"
    test_dir.mkdir()
    doc_file = test_dir / "clean.txt"
    doc_file.write_text("Clean document content for indexing verification.", encoding="utf-8")
    doc_path = os.path.normpath(str(doc_file))

    with test_db.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder(str(test_dir))
        folder_id = folder["folder_id"]

        from app.retrieval.embeddings import default_embedding_engine
        ident = default_embedding_engine.get_identity()
        repo.set_embedding_metadata(
            provider=ident["provider"],
            model_name=ident["model_name"],
            model_version=ident["model_version"],
            dimension=ident["dimension"],
        )

        file_rec = repo.upsert_file(
            folder_id=folder_id,
            path=doc_path,
            relative_path="clean.txt",
            filename="clean.txt",
            extension=".txt",
            size_bytes=os.path.getsize(doc_path),
            modified_at="2026-09-04T12:00:00Z",
            index_status="QUEUED",
        )
        file_id = file_rec["file_id"]

        repo.enqueue_job(
            file_id=file_id,
            folder_id=folder_id,
            job_type="DOCUMENT_PARSE",
            priority=1,
        )

    pool = WorkerPool(test_db, max_workers=1)
    with test_db.session() as conn:
        repo = Repository(conn)
        job = repo.claim_next_job()
    assert job is not None
    pool._process_job(job)

    with test_db.session() as conn:
        repo = Repository(conn)
        refreshed_file = repo.get_file_by_id(file_id)
        assert refreshed_file["index_status"] == "INDEXED"
        assert refreshed_file["indexing_error"] is None


def test_parse_warning_and_vector_mismatch_combination(test_db, tmp_path):
    test_dir = tmp_path / "docs_warn"
    test_dir.mkdir()
    doc_file = test_dir / "warn.txt"
    doc_file.write_text("Doc with warnings and mismatch", encoding="utf-8")
    doc_path = os.path.normpath(str(doc_file))

    with test_db.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder(str(test_dir))
        folder_id = folder["folder_id"]

        # Incompatible metadata
        repo.set_embedding_metadata(
            provider="fastembed",
            model_name="incompatible-model",
            model_version="1.0.0",
            dimension=384,
        )

        file_rec = repo.upsert_file(
            folder_id=folder_id,
            path=doc_path,
            relative_path="warn.txt",
            filename="warn.txt",
            extension=".txt",
            size_bytes=os.path.getsize(doc_path),
            modified_at="2026-09-04T12:00:00Z",
            index_status="QUEUED",
        )
        file_id = file_rec["file_id"]

        repo.enqueue_job(
            file_id=file_id,
            folder_id=folder_id,
            job_type="DOCUMENT_PARSE",
            priority=1,
        )

    pool = WorkerPool(test_db, max_workers=1)

    mock_doc = Document(
        file_id=file_id,
        source_path=doc_path,
        filename="warn.txt",
        mime_type="text/plain",
        elements=[
            DocumentElement(
                element_id="elem_1",
                element_type=ElementType.PARAGRAPH,
                text="Doc with warnings and mismatch",
            )
        ],
        quality_assessment=PDFQualityAssessment(
            status="PARSE_WARNING",
            reason_codes=["low_text_density"],
            message="Low character count detected",
        ),
    )



    mock_parser = mock.MagicMock()
    mock_parser.parser_version = "1.0.0"
    mock_parser.parse.return_value = mock_doc

    with mock.patch(
        "app.intelligence.parsers.registry.default_parser_registry.get_parser_for_file",
        return_value=mock_parser,
    ):
        with test_db.session() as conn:
            repo = Repository(conn)
            job = repo.claim_next_job()
        assert job is not None
        pool._process_job(job)



    with test_db.session() as conn:
        repo = Repository(conn)
        refreshed_file = repo.get_file_by_id(file_id)
        assert refreshed_file["index_status"] == "INDEXED"
        err = refreshed_file["indexing_error"]
        assert err is not None
        assert "PARSE_WARNING" in err
        assert "low_text_density" in err
        assert " | " in err
        assert "Vector write skipped" in err


def test_embedding_generation_failure_preserves_indexed_with_warning(test_db, tmp_path):
    test_dir = tmp_path / "docs_emb_fail"
    test_dir.mkdir()
    doc_file = test_dir / "emb_fail.txt"
    doc_file.write_text("Embedding generation will fail here.", encoding="utf-8")
    doc_path = os.path.normpath(str(doc_file))

    with test_db.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder(str(test_dir))
        folder_id = folder["folder_id"]

        file_rec = repo.upsert_file(
            folder_id=folder_id,
            path=doc_path,
            relative_path="emb_fail.txt",
            filename="emb_fail.txt",
            extension=".txt",
            size_bytes=os.path.getsize(doc_path),
            modified_at="2026-09-04T12:00:00Z",
            index_status="QUEUED",
        )
        file_id = file_rec["file_id"]

        repo.enqueue_job(
            file_id=file_id,
            folder_id=folder_id,
            job_type="DOCUMENT_PARSE",
            priority=1,
        )

    pool = WorkerPool(test_db, max_workers=1)

    with mock.patch(
        "app.retrieval.embeddings.EmbeddingEngine.embed_texts",
        side_effect=RuntimeError("FastEmbed inference error"),
    ):
        with test_db.session() as conn:
            repo = Repository(conn)
            job = repo.claim_next_job()
        assert job is not None
        pool._process_job(job)

    with test_db.session() as conn:
        repo = Repository(conn)
        refreshed_file = repo.get_file_by_id(file_id)
        assert refreshed_file["index_status"] == "INDEXED"
        assert "Vector embedding generation warning" in refreshed_file["indexing_error"]
        assert "FastEmbed inference error" in refreshed_file["indexing_error"]
        # Relational chunks still created
        assert len(repo.get_chunks_by_file(file_id)) > 0
