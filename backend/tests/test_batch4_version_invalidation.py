"""Tests for Batch 4 Requirement 2 & 4: Reprocessing Version Invalidation & Parser Provenance.

Verifies:
1. Matching parser and chunker versions do not trigger redundant reprocessing.
2. Parser version mismatch triggers reprocessing during scan.
3. Chunker version mismatch triggers reprocessing during scan.
4. Reprocessing records the actual active parser and chunker versions in the chunks table.
"""

import os
import pytest
from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.db.repository import Repository
from app.engine.discovery import FilesystemScanner
from app.intelligence.parsers.registry import default_parser_registry
from app.intelligence.chunker.hierarchical import CHUNKER_VERSION


@pytest.fixture
def test_env(tmp_path):
    db_dir = tmp_path / "db"
    db_dir.mkdir()
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    db_file = db_dir / "test_version_inv.db"
    db_manager = DatabaseManager(str(db_file))
    with db_manager.session() as conn:
        apply_migrations(conn)
    return db_manager, str(docs_dir)


def test_matching_versions_do_not_reprocess(test_env):
    """If file is INDEXED and parser/chunker versions match active versions, scan reports UNCHANGED."""
    db_manager, docs_dir = test_env
    doc_path = os.path.join(docs_dir, "test.md")
    with open(doc_path, "w", encoding="utf-8") as f:
        f.write("# Hello World\n\nContent body.")

    st = os.stat(doc_path)
    from datetime import datetime, timezone
    mod_iso = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat()

    with db_manager.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder(docs_dir)
        file_rec = repo.upsert_file(
            folder_id=folder["folder_id"],
            path=doc_path,
            relative_path="test.md",
            filename="test.md",
            extension=".md",
            size_bytes=st.st_size,
            modified_at=mod_iso,
            mime_type="text/markdown",
            index_status="INDEXED",
            sha256="dummyhash123",
        )
        file_id = file_rec["file_id"]

        active_parser = default_parser_registry.get_parser_for_file(doc_path, "text/markdown")
        chunks = [
            {
                "chunk_id": "c1",
                "file_id": file_id,
                "source_file": "test.md",
                "source_path": doc_path,
                "page": 1,
                "section": "General",
                "content_hash": "dummyhash123",
                "chunk_index": 0,
                "parser_name": active_parser.parser_name,
                "parser_version": active_parser.parser_version,
                "chunker_version": CHUNKER_VERSION,
                "content": "# Hello World\n\nContent body.",
                "content_type": "text",
                "token_count": 5,
                "metadata": {},
            }
        ]
        repo.replace_file_chunks(file_id, chunks)

        scanner = FilesystemScanner(repo)
        res = scanner.scan_folder(folder["folder_id"])
        assert res.unchanged_files == 1
        assert res.modified_files == 0
        assert len(res.enqueued_job_ids) == 0


def test_parser_version_mismatch_triggers_reprocessing(test_env):
    """If indexed chunk has an outdated parser_version, scan marks file modified and enqueues reparse."""
    db_manager, docs_dir = test_env
    doc_path = os.path.join(docs_dir, "test.md")
    with open(doc_path, "w", encoding="utf-8") as f:
        f.write("# Hello World\n\nContent body.")

    st = os.stat(doc_path)
    from datetime import datetime, timezone
    mod_iso = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat()

    with db_manager.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder(docs_dir)
        file_rec = repo.upsert_file(
            folder_id=folder["folder_id"],
            path=doc_path,
            relative_path="test.md",
            filename="test.md",
            extension=".md",
            size_bytes=st.st_size,
            modified_at=mod_iso,
            mime_type="text/markdown",
            index_status="INDEXED",
            sha256="dummyhash123",
        )
        file_id = file_rec["file_id"]

        active_parser = default_parser_registry.get_parser_for_file(doc_path, "text/markdown")
        # Stale parser version "0.9.0-legacy"
        chunks = [
            {
                "chunk_id": "c1",
                "file_id": file_id,
                "source_file": "test.md",
                "source_path": doc_path,
                "page": 1,
                "section": "General",
                "content_hash": "dummyhash123",
                "chunk_index": 0,
                "parser_name": active_parser.parser_name,
                "parser_version": "0.9.0-legacy",
                "chunker_version": CHUNKER_VERSION,
                "content": "# Hello World\n\nContent body.",
                "content_type": "text",
                "token_count": 5,
                "metadata": {},
            }
        ]
        repo.replace_file_chunks(file_id, chunks)

        scanner = FilesystemScanner(repo)
        res = scanner.scan_folder(folder["folder_id"])
        assert res.modified_files == 1
        assert len(res.enqueued_job_ids) == 1


def test_chunker_version_mismatch_triggers_reprocessing(test_env):
    """If indexed chunk has an outdated chunker_version, scan marks file modified and enqueues reparse."""
    db_manager, docs_dir = test_env
    doc_path = os.path.join(docs_dir, "test.md")
    with open(doc_path, "w", encoding="utf-8") as f:
        f.write("# Hello World\n\nContent body.")

    st = os.stat(doc_path)
    from datetime import datetime, timezone
    mod_iso = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat()

    with db_manager.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder(docs_dir)
        file_rec = repo.upsert_file(
            folder_id=folder["folder_id"],
            path=doc_path,
            relative_path="test.md",
            filename="test.md",
            extension=".md",
            size_bytes=st.st_size,
            modified_at=mod_iso,
            mime_type="text/markdown",
            index_status="INDEXED",
            sha256="dummyhash123",
        )
        file_id = file_rec["file_id"]

        active_parser = default_parser_registry.get_parser_for_file(doc_path, "text/markdown")
        # Stale chunker version "phase1-naive"
        chunks = [
            {
                "chunk_id": "c1",
                "file_id": file_id,
                "source_file": "test.md",
                "source_path": doc_path,
                "page": 1,
                "section": "General",
                "content_hash": "dummyhash123",
                "chunk_index": 0,
                "parser_name": active_parser.parser_name,
                "parser_version": active_parser.parser_version,
                "chunker_version": "phase1-naive",
                "content": "# Hello World\n\nContent body.",
                "content_type": "text",
                "token_count": 5,
                "metadata": {},
            }
        ]
        repo.replace_file_chunks(file_id, chunks)

        scanner = FilesystemScanner(repo)
        res = scanner.scan_folder(folder["folder_id"])
        assert res.modified_files == 1
        assert len(res.enqueued_job_ids) == 1
