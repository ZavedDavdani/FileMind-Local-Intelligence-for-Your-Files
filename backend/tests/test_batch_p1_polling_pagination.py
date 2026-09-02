import os
import shutil
import tempfile
import pytest
from fastapi.testclient import TestClient

from app.core.security import normalize_path
from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.db.repository import Repository
from app.main import app


@pytest.fixture
def test_client_env():
    """Sets up a temporary database and FastAPI test client with 120 populated files."""
    tmp_dir = tempfile.mkdtemp(prefix="filemind_polling_")
    db_path = os.path.join(tmp_dir, "test.db")
    custom_mgr = DatabaseManager(db_path=db_path)
    with custom_mgr.session() as conn:
        apply_migrations(conn)

    import app.main as main_module
    saved_mgr = main_module.db_manager
    main_module.db_manager = custom_mgr

    # Populate 120 test files in the database
    with custom_mgr.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder(r"C:\TestVault", recursive=True, integrity_mode="NORMAL")
        fid = folder["folder_id"]
        for i in range(1, 121):
            status = "INDEXED" if i <= 100 else "QUEUED"
            repo.upsert_file(
                folder_id=fid,
                path=f"C:\\TestVault\\document_{i:03d}.txt",
                relative_path=f"document_{i:03d}.txt",
                filename=f"document_{i:03d}.txt",
                extension=".txt",
                size_bytes=1000 + i,
                modified_at=f"2026-08-30T12:{i % 60:02d}:00Z",
                index_status=status,
                sha256=f"hash_{i:03d}"
            )

    client = TestClient(app)
    yield client, custom_mgr

    main_module.db_manager = saved_mgr
    shutil.rmtree(tmp_dir, ignore_errors=True)


def test_pagination_depth_preservation_on_refresh(test_client_env):
    """
    Verifies that querying with an expanded depth (e.g. limit=100 after 2 pages loaded)
    returns the complete expanded dataset without pagination reset or missing rows.
    """
    client, _ = test_client_env

    # 1. Page 1 (initial load, 50 items)
    resp1 = client.get("/files?limit=50&offset=0")
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert data1["total"] == 120
    assert len(data1["files"]) == 50

    # 2. Page 2 (Load More, next 50 items)
    resp2 = client.get("/files?limit=50&offset=50")
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert len(data2["files"]) == 50

    # Verify no overlap between page 1 and page 2
    page1_ids = {f["file_id"] for f in data1["files"]}
    page2_ids = {f["file_id"] for f in data2["files"]}
    assert len(page1_ids.intersection(page2_ids)) == 0

    # 3. Background refresh at depth 100 (simulating FileList refresh effect)
    resp_refresh = client.get("/files?limit=100&offset=0")
    assert resp_refresh.status_code == 200
    data_refresh = resp_refresh.json()
    assert len(data_refresh["files"]) == 100

    # Verify that the refreshed 100 files exactly contain page 1 + page 2
    combined_ids = page1_ids.union(page2_ids)
    refresh_ids = {f["file_id"] for f in data_refresh["files"]}
    assert refresh_ids == combined_ids


def test_search_and_filter_with_pagination_depth(test_client_env):
    """
    Verifies that filtered and searched datasets maintain accurate totals
    and slice integrity when refreshing at expanded depth.
    """
    client, _ = test_client_env

    # 1. Filter by QUEUED (20 items in database)
    resp_queued = client.get("/files?status=QUEUED&limit=50&offset=0")
    assert resp_queued.status_code == 200
    data_queued = resp_queued.json()
    assert data_queued["total"] == 20
    assert len(data_queued["files"]) == 20

    # 2. Search for specific keyword "document_01" (matches document_010 to document_019, plus document_001.. etc)
    resp_search = client.get("/files?search=document_01&limit=50&offset=0")
    assert resp_search.status_code == 200
    data_search = resp_search.json()
    assert data_search["total"] > 0
    assert all("document_01" in f["filename"] for f in data_search["files"])
