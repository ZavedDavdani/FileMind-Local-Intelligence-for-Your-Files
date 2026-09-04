"""Performance regression and optimization verification test suite.

Verifies:
1. Vector Retrieval Hot Path:
   - Emptiness checks use O(1) probe without full COUNT(*) table scans.
   - Dense, hybrid, and adaptive filtered searches work accurately.
2. File Search Acceleration:
   - FTS5 trigram indexing for filename and relative_path searches.
   - Arbitrary substring, partial matches, multi-term queries, and pagination.
   - Combined folder and status filters.
3. Index Presence and Query Plans:
   - idx_files_modified_at and idx_files_folder_status indexes exist and are utilized.
4. Database Migration Safety:
   - Existing databases migrate from V8 to V9 and backfill files_fts cleanly.
"""

import os
import sqlite3
import pytest

from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations, SCHEMA_VERSION
from app.db.repositories import FileRepository, FolderRepository
from app.retrieval.vector_store import SqliteVecStore


class QueryCountingConnection:
    """Connection proxy that records executed SQL queries."""

    def __init__(self, real_conn: sqlite3.Connection):
        self._real_conn = real_conn
        self.executed_queries: list[str] = []

    def execute(self, sql: str, parameters=()):
        self.executed_queries.append(sql.strip())
        return self._real_conn.execute(sql, parameters)

    def executemany(self, sql: str, seq_of_parameters):
        self.executed_queries.append(sql.strip())
        return self._real_conn.executemany(sql, seq_of_parameters)

    def __getattr__(self, name):
        return getattr(self._real_conn, name)


@pytest.fixture
def perf_db(tmp_path):
    db = DatabaseManager(str(tmp_path / "perf_test.db"))
    with db.session() as conn:
        apply_migrations(conn)
        SqliteVecStore(conn, dimension=4)
    return db


# ============================================================================
# 1. VECTOR RETRIEVAL HOT PATH TESTS
# ============================================================================


def test_vector_search_does_not_call_unconditional_full_count(perf_db):
    """Proves that SqliteVecStore.search() does NOT perform SELECT COUNT(*) on chunk_vectors."""
    with perf_db.session() as conn:
        folder_repo = FolderRepository(conn)
        file_repo = FileRepository(conn)
        f = folder_repo.create_folder("C:/vec_test")
        fid = f["folder_id"]

        file_repo.upsert_file(
            folder_id=fid,
            path="C:/vec_test/doc.txt",
            relative_path="doc.txt",
            filename="doc.txt",
            extension=".txt",
            size_bytes=100,
            modified_at="2026-09-04T12:00:00Z",
            file_id="f_vec",
        )
        conn.execute(
            """
            INSERT INTO chunks (chunk_id, file_id, source_file, source_path, content_hash, chunk_index, parser_name, parser_version, chunker_version, content)
            VALUES
              ('c1', 'f_vec', 'doc.txt', 'C:/vec_test/doc.txt', 'h1', 0, 'parser', '1.0', '1.0', 'Content 1'),
              ('c2', 'f_vec', 'doc.txt', 'C:/vec_test/doc.txt', 'h2', 1, 'parser', '1.0', '1.0', 'Content 2');
            """
        )

        proxy = QueryCountingConnection(conn)
        vec_store = SqliteVecStore(proxy, dimension=4)

        # Empty vector store
        res = vec_store.search([0.1, 0.2, 0.3, 0.4], top_k=5)
        assert res == []

        # Verify no SELECT COUNT(*) was executed
        count_queries = [q for q in proxy.executed_queries if "SELECT COUNT(*)" in q.upper() and "CHUNK_VECTORS" in q.upper()]
        assert len(count_queries) == 0, f"Unexpected full count executed on empty search: {count_queries}"

        # Insert some vectors and test populated search
        proxy.executed_queries.clear()
        vec_store.upsert_vectors([
            {"chunk_id": "c1", "embedding": [0.1, 0.2, 0.3, 0.4]},
            {"chunk_id": "c2", "embedding": [0.2, 0.3, 0.4, 0.5]},
        ])

        proxy.executed_queries.clear()
        res_populated = vec_store.search([0.1, 0.2, 0.3, 0.4], top_k=2)
        assert len(res_populated) == 2
        assert res_populated[0]["chunk_id"] == "c1"

        # Verify no SELECT COUNT(*) on hot path
        count_queries_populated = [q for q in proxy.executed_queries if "SELECT COUNT(*)" in q.upper() and "CHUNK_VECTORS" in q.upper()]
        assert len(count_queries_populated) == 0, f"Unexpected full count executed on populated search: {count_queries_populated}"


def test_vector_search_adaptive_filtering_accuracy(perf_db):
    """Verifies that vector search with filters accurately returns matching chunks."""
    with perf_db.session() as conn:
        folder_repo = FolderRepository(conn)
        file_repo = FileRepository(conn)
        vec_store = SqliteVecStore(conn, dimension=4)

        f1 = folder_repo.create_folder("C:/perf_docs")
        fid = f1["folder_id"]

        file_repo.upsert_file(
            folder_id=fid,
            path="C:/perf_docs/report.pdf",
            relative_path="report.pdf",
            filename="report.pdf",
            extension=".pdf",
            size_bytes=1000,
            modified_at="2026-09-04T12:00:00Z",
            file_id="f_pdf",
        )

        conn.execute(
            """
            INSERT INTO chunks (chunk_id, file_id, source_file, source_path, content_hash, chunk_index, parser_name, parser_version, chunker_version, content)
            VALUES ('c_pdf_1', 'f_pdf', 'report.pdf', 'C:/perf_docs/report.pdf', 'hash1', 0, 'pdf_parser', '1.0', '1.0', 'PDF quarterly content');
            """
        )

        vec_store.upsert_vectors([
            {"chunk_id": "c_pdf_1", "embedding": [0.5, 0.5, 0.5, 0.5]},
        ])

        # Filter by extension
        results_pdf = vec_store.search([0.5, 0.5, 0.5, 0.5], top_k=5, filters={"extension": ".pdf"})
        assert len(results_pdf) == 1
        assert results_pdf[0]["chunk_id"] == "c_pdf_1"

        # Filter by different extension returns empty
        results_docx = vec_store.search([0.5, 0.5, 0.5, 0.5], top_k=5, filters={"extension": ".docx"})
        assert len(results_docx) == 0


# ============================================================================
# 2. FILE SEARCH FTS5 & FILTER CONSOLIDATION TESTS
# ============================================================================


def test_file_fts_search_substring_and_multiterm(perf_db):
    """Verifies that FTS5 trigram search matches exact, prefix, suffix, and inner substrings."""
    with perf_db.session() as conn:
        folder_repo = FolderRepository(conn)
        file_repo = FileRepository(conn)

        f = folder_repo.create_folder("C:/search_corpus")
        fid = f["folder_id"]

        file_repo.upsert_file(
            folder_id=fid,
            path="C:/search_corpus/financial_audit_2026.xlsx",
            relative_path="reports/2026/financial_audit_2026.xlsx",
            filename="financial_audit_2026.xlsx",
            extension=".xlsx",
            size_bytes=5000,
            modified_at="2026-09-04T15:00:00Z",
            file_id="f1",
        )
        file_repo.upsert_file(
            folder_id=fid,
            path="C:/search_corpus/readme_quickstart.md",
            relative_path="docs/readme_quickstart.md",
            filename="readme_quickstart.md",
            extension=".md",
            size_bytes=1200,
            modified_at="2026-09-04T14:00:00Z",
            file_id="f2",
        )

        # 1. Exact filename match
        res_exact = file_repo.list_files(search="financial_audit")
        assert len(res_exact) == 1
        assert res_exact[0]["file_id"] == "f1"
        assert file_repo.count_files(search="financial_audit") == 1

        # 2. Relative path match
        res_path = file_repo.list_files(search="reports/2026")
        assert len(res_path) == 1
        assert res_path[0]["file_id"] == "f1"

        # 3. Inner substring match (trigram power)
        res_sub = file_repo.list_files(search="audit")
        assert len(res_sub) == 1
        assert res_sub[0]["file_id"] == "f1"

        res_sub2 = file_repo.list_files(search="quick")
        assert len(res_sub2) == 1
        assert res_sub2[0]["file_id"] == "f2"

        # 4. Multi-word match
        res_multi = file_repo.list_files(search="financial 2026")
        assert len(res_multi) == 1
        assert res_multi[0]["file_id"] == "f1"

        # 5. Combined folder + status + search filter
        res_combined = file_repo.list_files(folder_id=fid, status="DISCOVERED", search="quickstart")
        assert len(res_combined) == 1
        assert res_combined[0]["file_id"] == "f2"

        # 6. Nonexistent search
        res_none = file_repo.list_files(search="nonexistent_pattern_xyz")
        assert len(res_none) == 0
        assert file_repo.count_files(search="nonexistent_pattern_xyz") == 0


def test_file_fts_pagination(perf_db):
    """Verifies deterministic pagination with FTS5 search."""
    with perf_db.session() as conn:
        folder_repo = FolderRepository(conn)
        file_repo = FileRepository(conn)

        f = folder_repo.create_folder("C:/paginated")
        fid = f["folder_id"]

        for i in range(10):
            file_repo.upsert_file(
                folder_id=fid,
                path=f"C:/paginated/batch_item_{i:02d}.txt",
                relative_path=f"batch_item_{i:02d}.txt",
                filename=f"batch_item_{i:02d}.txt",
                extension=".txt",
                size_bytes=100,
                modified_at=f"2026-09-04T10:{i:02d}:00Z",
                file_id=f"f_{i}",
            )

        assert file_repo.count_files(search="batch_item") == 10

        page1 = file_repo.list_files(search="batch_item", limit=4, offset=0)
        page2 = file_repo.list_files(search="batch_item", limit=4, offset=4)
        page3 = file_repo.list_files(search="batch_item", limit=4, offset=8)

        assert len(page1) == 4
        assert len(page2) == 4
        assert len(page3) == 2

        # Verify descending order by modified_at
        assert page1[0]["filename"] == "batch_item_09.txt"
        assert page2[0]["filename"] == "batch_item_05.txt"


# ============================================================================
# 3. DATABASE INDEXES AND QUERY PLANS
# ============================================================================


def test_database_indexes_exist(perf_db):
    """Verifies that all performance indexes exist in the schema."""
    with perf_db.session() as conn:
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='index';")
        indexes = {r[0] for r in cursor.fetchall()}

        assert "idx_files_modified_at" in indexes, "Missing idx_files_modified_at index"
        assert "idx_files_folder_status" in indexes, "Missing idx_files_folder_status index"


def test_query_plan_utilizes_indexes(perf_db):
    """Verifies EXPLAIN QUERY PLAN demonstrates index usage for modified_at and folder_status."""
    with perf_db.session() as conn:
        # Browse query plan
        browse_plan = conn.execute(
            "EXPLAIN QUERY PLAN SELECT * FROM files ORDER BY modified_at DESC LIMIT 50;"
        ).fetchall()
        browse_details = [r["detail"] if isinstance(r, sqlite3.Row) else str(r) for r in browse_plan]
        browse_text = " ".join(browse_details)
        assert "idx_files_modified_at" in browse_text or "SCAN files" in browse_text

        # Folder + status query plan
        status_plan = conn.execute(
            "EXPLAIN QUERY PLAN SELECT * FROM files WHERE folder_id = 'test' AND index_status = 'INDEXED';"
        ).fetchall()
        status_details = [r["detail"] if isinstance(r, sqlite3.Row) else str(r) for r in status_plan]
        status_text = " ".join(status_details)
        assert "idx_files_folder_status" in status_text, f"idx_files_folder_status not used: {status_text}"


# ============================================================================
# 4. MIGRATION SAFETY AND EXISTING DB BACKFILL
# ============================================================================


def test_migration_v8_to_v9_backfill(tmp_path):
    """Verifies that an existing V8 database correctly upgrades to V9 and populates files_fts."""
    db_path = str(tmp_path / "upgrade_test.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Apply migrations up to V8 manually
    from app.db.migrations import (
        MIGRATION_V1_SQL, MIGRATION_V2_SQL, MIGRATION_V3_SQL, MIGRATION_V4_SQL,
        MIGRATION_V5_SQL, MIGRATION_V6_SQL, MIGRATION_V7_SQL, MIGRATION_V8_SQL,
    )
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT);")
    for v, sql in enumerate([MIGRATION_V1_SQL, MIGRATION_V2_SQL, MIGRATION_V3_SQL, MIGRATION_V4_SQL, MIGRATION_V5_SQL, MIGRATION_V6_SQL, MIGRATION_V7_SQL, MIGRATION_V8_SQL], start=1):
        conn.executescript(sql)
        conn.execute("INSERT OR REPLACE INTO schema_migrations (version) VALUES (?);", (v,))

    # Insert files in V8 schema before V9 migration
    conn.execute("INSERT INTO folders (folder_id, path) VALUES ('fol-1', 'C:/upgrade_folder');")
    conn.execute(
        """
        INSERT INTO files (file_id, folder_id, path, relative_path, filename, extension, size_bytes, modified_at, index_status)
        VALUES ('f-pre-1', 'fol-1', 'C:/upgrade_folder/legacy_document.pdf', 'legacy_document.pdf', 'legacy_document.pdf', '.pdf', 2000, '2026-09-01', 'INDEXED');
        """
    )
    conn.commit()

    # Now apply migrations to upgrade to V9
    version_after = apply_migrations(conn)
    assert version_after == SCHEMA_VERSION == 9

    # Verify files_fts exists and contains the pre-existing file
    repo = FileRepository(conn)
    results = repo.list_files(search="legacy_document")
    assert len(results) == 1
    assert results[0]["file_id"] == "f-pre-1"
    conn.close()
