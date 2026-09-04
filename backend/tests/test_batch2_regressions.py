"""Focused regression tests for Pre-Phase-5 Bug Fix Batch 2:
- Bug #7: enqueue_job() deduplication by (file_id, job_type)
- Bug #8: SQL LIKE wildcard escaping for directories with %, _, etc.
- Bug #9: Rust source heading and function extraction (.rs extension)
- Bug #10: HealthResponse authoritative version synchronization
- Bug #11: SQLite schema migration version consistency
"""

import os
import sys
import tempfile
import sqlite3
import pytest
from fastapi.testclient import TestClient

from app import __version__
from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations, SCHEMA_VERSION
from app.db.repository import Repository, escape_like_wildcards
from app.intelligence.parsers.text_parser import TextAndCodeParser
from app.intelligence.detector import detect_file_format
from app.intelligence.models import ElementType
from app.main import app
from app.schemas import HealthResponse


# ---------------------------------------------------------------------------
# Test Fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def repo_env():
    """Provides a fresh isolated in-memory or temp SQLite database with full migrations."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "batch2_regressions.db")
        mgr = DatabaseManager(db_path)
        with mgr.session() as conn:
            apply_migrations(conn)
        yield mgr, tmp_dir


# ---------------------------------------------------------------------------
# Bug #7: enqueue_job() deduplication by (file_id, job_type)
# ---------------------------------------------------------------------------

def test_job_enqueue_deduplication_by_file_id_and_type(repo_env):
    """Bug #7: Deduplication must be scoped to (file_id, job_type)."""
    mgr, tmp_dir = repo_env

    with mgr.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder(tmp_dir)
        fid = folder["folder_id"]
        file_rec = repo.upsert_file(
            folder_id=fid,
            path=os.path.join(tmp_dir, "test.txt"),
            relative_path="test.txt",
            filename="test.txt",
            extension=".txt",
            size_bytes=100,
            modified_at="2026-01-01T00:00:00Z",
        )
        file_id = file_rec["file_id"]

        # 1. Enqueue DOCUMENT_PARSE
        job1 = repo.enqueue_job(file_id=file_id, folder_id=fid, job_type="DOCUMENT_PARSE")
        assert job1["status"] == "PENDING"
        assert job1["job_type"] == "DOCUMENT_PARSE"

        # 2. Enqueue same job_type -> returns existing job (deduplicated)
        job1_dup = repo.enqueue_job(file_id=file_id, folder_id=fid, job_type="DOCUMENT_PARSE")
        assert job1_dup["job_id"] == job1["job_id"]

        # 3. Enqueue different job_type -> creates a separate new job
        job2 = repo.enqueue_job(file_id=file_id, folder_id=fid, job_type="DELETE_CLEANUP")
        assert job2["job_id"] != job1["job_id"]
        assert job2["job_type"] == "DELETE_CLEANUP"
        assert job2["status"] == "PENDING"

        # 4. Enqueue third distinct job_type -> creates a separate job
        job3 = repo.enqueue_job(file_id=file_id, folder_id=fid, job_type="HASH_VERIFICATION")
        assert job3["job_id"] not in (job1["job_id"], job2["job_id"])
        assert job3["job_type"] == "HASH_VERIFICATION"

        # 5. Verify all active jobs exist in DB
        cursor = conn.execute(
            "SELECT job_id, job_type FROM indexing_jobs WHERE file_id = ? AND status = 'PENDING';",
            (file_id,),
        )
        active_jobs = {r["job_type"]: r["job_id"] for r in cursor.fetchall()}
        assert len(active_jobs) == 3
        assert "DOCUMENT_PARSE" in active_jobs
        assert "DELETE_CLEANUP" in active_jobs
        assert "HASH_VERIFICATION" in active_jobs


# ---------------------------------------------------------------------------
# Bug #8: SQL LIKE wildcard escaping
# ---------------------------------------------------------------------------

def test_escape_like_wildcards_unit():
    """Bug #8: Unit tests for escape_like_wildcards function."""
    assert escape_like_wildcards("Client_A") == "Client\\_A"
    assert escape_like_wildcards("50%_Complete") == "50\\%\\_Complete"
    assert escape_like_wildcards("Folder\\Sub_Path%100") == "Folder\\\\Sub\\_Path\\%100"
    assert escape_like_wildcards("normal_folder") == "normal\\_folder"


def test_sql_like_wildcard_escaping_for_mark_directory_missing(repo_env):
    """Bug #8: mark_directory_missing on 'Client_A' must not affect 'Client-A' or 'Client1A'."""
    mgr, tmp_dir = repo_env

    with mgr.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder(tmp_dir)
        fid = folder["folder_id"]

        # Create 3 directories with names that would trigger false positive unescaped LIKE matches
        # Target directory: Client_A
        # Sibling directories: Client-A, Client1A
        dir_target = os.path.join(tmp_dir, "Client_A")
        dir_sibling1 = os.path.join(tmp_dir, "Client-A")
        dir_sibling2 = os.path.join(tmp_dir, "Client1A")
        # Another target with %: 50%_Done
        dir_percent = os.path.join(tmp_dir, "50%_Done")
        dir_percent_sibling = os.path.join(tmp_dir, "500_Done")

        for d in (dir_target, dir_sibling1, dir_sibling2, dir_percent, dir_percent_sibling):
            os.makedirs(d, exist_ok=True)

        f_target = repo.upsert_file(fid, os.path.join(dir_target, "f1.txt"), "Client_A/f1.txt", "f1.txt", ".txt", 10, "2026-01-01T00:00:00Z", index_status="INDEXED")
        f_sib1 = repo.upsert_file(fid, os.path.join(dir_sibling1, "f2.txt"), "Client-A/f2.txt", "f2.txt", ".txt", 10, "2026-01-01T00:00:00Z", index_status="INDEXED")
        f_sib2 = repo.upsert_file(fid, os.path.join(dir_sibling2, "f3.txt"), "Client1A/f3.txt", "f3.txt", ".txt", 10, "2026-01-01T00:00:00Z", index_status="INDEXED")
        f_pct = repo.upsert_file(fid, os.path.join(dir_percent, "f4.txt"), "50%_Done/f4.txt", "f4.txt", ".txt", 10, "2026-01-01T00:00:00Z", index_status="INDEXED")
        f_pct_sib = repo.upsert_file(fid, os.path.join(dir_percent_sibling, "f5.txt"), "500_Done/f5.txt", "f5.txt", ".txt", 10, "2026-01-01T00:00:00Z", index_status="INDEXED")

        # Mark Client_A missing
        affected = repo.mark_directory_missing(fid, dir_target)
        assert affected == 1

        # Check statuses
        assert repo.get_file_by_id(f_target["file_id"])["index_status"] == "MISSING"
        assert repo.get_file_by_id(f_sib1["file_id"])["index_status"] == "INDEXED"
        assert repo.get_file_by_id(f_sib2["file_id"])["index_status"] == "INDEXED"

        # Mark 50%_Done missing
        affected_pct = repo.mark_directory_missing(fid, dir_percent)
        assert affected_pct == 1
        assert repo.get_file_by_id(f_pct["file_id"])["index_status"] == "MISSING"
        assert repo.get_file_by_id(f_pct_sib["file_id"])["index_status"] == "INDEXED"


def test_sql_like_wildcard_escaping_for_rename_directory_path(repo_env):
    """Bug #8: rename_directory_path on 'Client_A' must not rename files in 'Client-A'."""
    mgr, tmp_dir = repo_env

    with mgr.session() as conn:
        repo = Repository(conn)
        folder = repo.create_folder(tmp_dir)
        fid = folder["folder_id"]

        dir_old = os.path.join(tmp_dir, "Client_A")
        dir_new = os.path.join(tmp_dir, "Client_Renamed")
        dir_sib = os.path.join(tmp_dir, "Client-A")

        os.makedirs(dir_old, exist_ok=True)
        os.makedirs(dir_sib, exist_ok=True)

        f_target = repo.upsert_file(fid, os.path.join(dir_old, "file.txt"), "Client_A/file.txt", "file.txt", ".txt", 10, "2026-01-01T00:00:00Z", index_status="INDEXED")
        f_sib = repo.upsert_file(fid, os.path.join(dir_sib, "file.txt"), "Client-A/file.txt", "file.txt", ".txt", 10, "2026-01-01T00:00:00Z", index_status="INDEXED")

        renamed_count = repo.rename_directory_path(fid, dir_old, dir_new, tmp_dir)
        assert renamed_count == 1

        updated_target = repo.get_file_by_id(f_target["file_id"])
        updated_sib = repo.get_file_by_id(f_sib["file_id"])

        assert "Client_Renamed" in updated_target["path"]
        assert "Client-A" in updated_sib["path"]


# ---------------------------------------------------------------------------
# Bug #9: Rust source heading and function extraction
# ---------------------------------------------------------------------------

def test_rust_source_heading_detection():
    """Bug #9: Verify text parser extracts struct, enum, impl, trait, and fn from .rs files."""
    parser = TextAndCodeParser()
    rust_code = """
// Module documentation
use std::collections::HashMap;

pub struct Config {
    pub port: u16,
    pub host: String,
}

enum Status {
    Active,
    Inactive,
}

pub(crate) trait Handler {
    fn handle(&self);
}

impl Config {
    pub fn new(port: u16) -> Self {
        Config { port, host: "127.0.0.1".into() }
    }

    pub async fn start(&self) {
        println!("Starting server");
    }
}

fn private_helper() -> bool {
    true
}
"""
    with tempfile.NamedTemporaryFile(suffix=".rs", mode="w", encoding="utf-8", delete=False) as f:
        f.write(rust_code)
        f_path = f.name

    try:
        mime, _ = detect_file_format(f_path)
        doc = parser.parse(f_path, file_id="rust_test_doc", mime_type=mime)
        headings = [elem for elem in doc.elements if elem.element_type == ElementType.HEADING]
        heading_texts = [h.text for h in headings]

        # Verify struct, enum, trait, impl are extracted as level 1 headings
        assert any("pub struct Config" in h for h in heading_texts)
        assert any("enum Status" in h for h in heading_texts)
        assert any("pub(crate) trait Handler" in h for h in heading_texts)
        assert any("impl Config" in h for h in heading_texts)

        # Verify functions are extracted
        assert any("fn handle(&self)" in h for h in heading_texts)
        assert any("pub fn new(port: u16) -> Self" in h for h in heading_texts)
        assert any("pub async fn start(&self)" in h for h in heading_texts)
        assert any("fn private_helper() -> bool" in h for h in heading_texts)

        # Verify parent heading association: methods inside impl Config should have parent_heading_id of impl Config
        impl_elem = next(h for h in headings if "impl Config" in h.text)
        new_fn_elem = next(h for h in headings if "pub fn new" in h.text)
        assert new_fn_elem.parent_heading_id == impl_elem.element_id
    finally:
        if os.path.exists(f_path):
            os.remove(f_path)


# ---------------------------------------------------------------------------
# Bug #10: HealthResponse authoritative version synchronization
# ---------------------------------------------------------------------------

def test_health_response_authoritative_version():
    """Bug #10: HealthResponse schema default and /health endpoint return authoritative version '0.1.0'."""
    # 1. Schema default
    hr = HealthResponse()
    assert hr.version == "0.1.0"
    assert hr.version == __version__

    # 2. Runtime API endpoint
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["version"] == "0.1.0"
    assert data["version"] == __version__


# ---------------------------------------------------------------------------
# Bug #11: Schema migration version consistency
# ---------------------------------------------------------------------------

def test_schema_migration_version_consistency():
    """SCHEMA_VERSION constant equals active version and apply_migrations returns version idempotently."""
    assert SCHEMA_VERSION == 9

    conn = sqlite3.connect(":memory:")
    v_first = apply_migrations(conn)
    assert v_first == 9

    # Verify schema_migrations table has records 1 through SCHEMA_VERSION
    cursor = conn.cursor()
    cursor.execute("SELECT version FROM schema_migrations ORDER BY version;")
    versions = [r[0] for r in cursor.fetchall()]
    assert versions == list(range(1, SCHEMA_VERSION + 1))

    # Re-running migrations is idempotent
    v_second = apply_migrations(conn)
    assert v_second == 9

    conn.close()
