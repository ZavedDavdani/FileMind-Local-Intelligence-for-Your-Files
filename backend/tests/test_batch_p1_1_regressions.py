import sqlite3
import pytest
from app.db.migrations import apply_migrations
from app.db.repository import Repository
from app.retrieval.hybrid import HybridRetriever
from app.schemas import SearchResponse


@pytest.fixture
def memory_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    apply_migrations(conn)
    return conn


def test_batch_p1_1_file_pagination_and_total_count(memory_db):
    """Verify that >100 files are tracked with correct total count and retrieved via pagination."""
    repo = Repository(memory_db)
    folder = repo.create_folder(r"C:\test_vault", recursive=True, integrity_mode="NORMAL")
    folder_id = folder["folder_id"]

    # Insert 150 files across two statuses
    for i in range(150):
        status = "INDEXED" if i < 100 else "QUEUED"
        repo.upsert_file(
            folder_id=folder_id,
            path=rf"C:\test_vault\doc_{i:03d}.txt",
            relative_path=rf"doc_{i:03d}.txt",
            filename=rf"doc_{i:03d}.txt",
            extension=".txt",
            size_bytes=1024,
            modified_at=f"2026-09-02T10:00:{i%60:02d}Z",
            sha256=f"sha256_hash_value_{i:03d}",
            index_status=status,
        )

    # 1. Verify total without filters is 150
    total_all = repo.count_files()
    assert total_all == 150

    # 2. Verify total with status filter is exact
    total_indexed = repo.count_files(status="INDEXED")
    assert total_indexed == 100

    total_queued = repo.count_files(status="QUEUED")
    assert total_queued == 50

    # 3. Verify pagination with limit and offset
    page_1 = repo.list_files(limit=50, offset=0)
    assert len(page_1) == 50

    page_2 = repo.list_files(limit=50, offset=50)
    assert len(page_2) == 50

    page_3 = repo.list_files(limit=50, offset=100)
    assert len(page_3) == 50

    page_4 = repo.list_files(limit=50, offset=150)
    assert len(page_4) == 0

    # Ensure pages contain distinct items
    page_1_ids = {f["file_id"] for f in page_1}
    page_2_ids = {f["file_id"] for f in page_2}
    page_3_ids = {f["file_id"] for f in page_3}
    assert len(page_1_ids.intersection(page_2_ids)) == 0
    assert len(page_2_ids.intersection(page_3_ids)) == 0


def test_batch_p1_1_server_side_filename_and_sha_search(memory_db):
    """Verify that search queries match filename, relative_path, and sha256 even beyond page 1."""
    repo = Repository(memory_db)
    folder = repo.create_folder(r"C:\test_vault", recursive=True, integrity_mode="NORMAL")
    folder_id = folder["folder_id"]

    # Insert 120 dummy files
    for i in range(120):
        repo.upsert_file(
            folder_id=folder_id,
            path=rf"C:\test_vault\generic_file_{i:03d}.md",
            relative_path=rf"generic_file_{i:03d}.md",
            filename=rf"generic_file_{i:03d}.md",
            extension=".md",
            size_bytes=500,
            modified_at=f"2026-09-02T10:00:{i%60:02d}Z",
            sha256=f"sha_generic_{i:03d}",
            index_status="INDEXED",
        )

    # Insert a specific target file at the end
    repo.upsert_file(
        folder_id=folder_id,
        path=r"C:\test_vault\deep\secret_financial_report.pdf",
        relative_path=r"deep\secret_financial_report.pdf",
        filename="secret_financial_report.pdf",
        extension=".pdf",
        size_bytes=9999,
        modified_at="2026-09-01T08:00:00Z",  # Old mtime so it would be on later pages
        sha256="deadbeefcafe1234567890abcdef",
        index_status="INDEXED",
    )

    # Search by filename
    results_fn = repo.list_files(search="secret_financial")
    assert len(results_fn) == 1
    assert results_fn[0]["filename"] == "secret_financial_report.pdf"
    assert repo.count_files(search="secret_financial") == 1

    # Search by relative path
    results_path = repo.list_files(search="deep\\secret")
    assert len(results_path) == 1
    assert results_path[0]["relative_path"] == "deep\\secret_financial_report.pdf"

    # Search by SHA-256
    results_sha = repo.list_files(search="deadbeefcafe")
    assert len(results_sha) == 1
    assert results_sha[0]["sha256"] == "deadbeefcafe1234567890abcdef"


def test_batch_p1_1_explicit_filename_intent_metadata(memory_db):
    """Verify that SearchResponse and HybridRetriever expose explicit_filename_intent accurately."""
    from app.retrieval.vector_store import MemoryCosineStore
    vector_store = MemoryCosineStore(dimension=384)
    retriever = HybridRetriever(db_conn=memory_db, vector_store=vector_store, reranker=None)

    # 1. Semantic queries must have explicit_filename_intent == None
    res_semantic_1 = retriever.search("v2.0 pricing", mode="bm25")
    assert res_semantic_1["explicit_filename_intent"] is None

    res_semantic_2 = retriever.search("3.14 report", mode="hybrid", quality="fast")
    assert res_semantic_2["explicit_filename_intent"] is None

    res_semantic_3 = retriever.search("how does memory leak debugging work?", mode="hybrid")
    assert res_semantic_3["explicit_filename_intent"] is None

    # 2. Nonexistent filename query must set explicit_filename_intent and return empty
    res_nonexistent = retriever.search("nonexistent_document.pdf", mode="hybrid")
    assert res_nonexistent["explicit_filename_intent"] == "nonexistent_document.pdf"
    assert res_nonexistent["total_found"] == 0
    assert res_nonexistent["results"] == []

    # 3. Validate SearchResponse schema validation
    schema_obj = SearchResponse(**res_nonexistent)
    assert schema_obj.explicit_filename_intent == "nonexistent_document.pdf"
    assert schema_obj.total_found == 0
