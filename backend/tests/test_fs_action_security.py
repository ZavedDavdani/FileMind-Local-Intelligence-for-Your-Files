"""Bug B — /fs/action Registered-Folder Scope Security Tests.

Validates:
B1. COPY_PATH for a file inside a registered folder -> 200 OK.
B2. OPEN_FILE for a file inside a registered folder -> 200 OK (OS action mocked).
B3. OPEN_FOLDER for an allowed registered-folder target -> 200 OK (OS action mocked).
B4. COPY_PATH for an existing file outside every registered folder -> HTTP 403.
B5. OPEN_FILE for an existing file outside every registered folder -> HTTP 403.
B6. Path-prefix confusion: C:\\FileMind-Test must NOT authorize C:\\FileMind-Test-Evil.
B7. ../ traversal cannot escape the registered folder.
B8. Canonical path comparison is case-insensitive on Windows.
B9. Existing legitimate search-result COPY_PATH action continues to work.
"""

import os
import sys
import tempfile
import unittest.mock as mock
import pytest

from fastapi.testclient import TestClient

from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.db.repository import Repository
from app.main import app, db_manager


# ---------------------------------------------------------------------------
# Test-level DB override: point db_manager to an isolated test database
# ---------------------------------------------------------------------------

@pytest.fixture
def isolated_app(tmp_path):
    """Provides a TestClient with an isolated DB containing one registered folder."""
    db_path = str(tmp_path / "test_fsa_security.db")

    # Patch db_manager in main so app uses our isolated DB
    test_db = DatabaseManager(db_path)
    with test_db.session() as conn:
        apply_migrations(conn)

    with mock.patch("app.main.db_manager", test_db):
        with TestClient(app, raise_server_exceptions=True) as client:
            yield client, test_db, tmp_path


@pytest.fixture
def registered_folder(isolated_app):
    """Creates a registered folder with a real file inside it."""
    client, test_db, tmp_path = isolated_app

    folder_path = str(tmp_path / "registered_folder")
    os.makedirs(folder_path, exist_ok=True)
    file_path = os.path.join(folder_path, "allowed_file.txt")
    with open(file_path, "w") as f:
        f.write("This file is inside the registered folder.")

    with test_db.session() as conn:
        repo = Repository(conn)
        repo.create_folder(folder_path)

    return client, test_db, folder_path, file_path, tmp_path


# ---------------------------------------------------------------------------
# B1: COPY_PATH inside registered folder
# ---------------------------------------------------------------------------

def test_b1_copy_path_inside_registered_folder(registered_folder):
    """B1: COPY_PATH for a file inside a registered folder must succeed."""
    client, _, folder_path, file_path, _ = registered_folder
    resp = client.post("/fs/action", json={"action": "COPY_PATH", "target_path": file_path})
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert data["success"] is True


# ---------------------------------------------------------------------------
# B2: OPEN_FILE inside registered folder (OS startfile mocked)
# ---------------------------------------------------------------------------

def test_b2_open_file_inside_registered_folder(registered_folder):
    """B2: OPEN_FILE for a file inside a registered folder must succeed (OS call mocked)."""
    client, _, folder_path, file_path, _ = registered_folder
    with mock.patch("os.startfile"), mock.patch("subprocess.Popen"):
        resp = client.post("/fs/action", json={"action": "OPEN_FILE", "target_path": file_path})
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert data["success"] is True


# ---------------------------------------------------------------------------
# B3: OPEN_FOLDER inside registered folder (OS action mocked)
# ---------------------------------------------------------------------------

def test_b3_open_folder_inside_registered_folder(registered_folder):
    """B3: OPEN_FOLDER for a target within a registered folder must succeed."""
    client, _, folder_path, file_path, _ = registered_folder
    with mock.patch("os.startfile"), mock.patch("subprocess.Popen"):
        resp = client.post("/fs/action", json={"action": "OPEN_FOLDER", "target_path": file_path})
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert data["success"] is True


# ---------------------------------------------------------------------------
# B4: COPY_PATH outside every registered folder -> 403
# ---------------------------------------------------------------------------

def test_b4_copy_path_outside_registered_folder(registered_folder, tmp_path):
    """B4: COPY_PATH for an existing file outside every registered folder must return 403."""
    client, _, folder_path, file_path, _ = registered_folder

    # Create a file that exists on disk but is NOT inside the registered folder
    outside_dir = str(tmp_path / "outside_dir")
    os.makedirs(outside_dir, exist_ok=True)
    outside_file = os.path.join(outside_dir, "secret.txt")
    with open(outside_file, "w") as f:
        f.write("This file is OUTSIDE all registered folders.")

    resp = client.post("/fs/action", json={"action": "COPY_PATH", "target_path": outside_file})
    assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"
    assert "denied" in resp.json().get("detail", "").lower()


# ---------------------------------------------------------------------------
# B5: OPEN_FILE outside registered folder -> 403
# ---------------------------------------------------------------------------

def test_b5_open_file_outside_registered_folder(registered_folder, tmp_path):
    """B5: OPEN_FILE for an existing file outside every registered folder must return 403."""
    client, _, folder_path, file_path, _ = registered_folder

    outside_dir = str(tmp_path / "evil_dir")
    os.makedirs(outside_dir, exist_ok=True)
    outside_file = os.path.join(outside_dir, "evil.txt")
    with open(outside_file, "w") as f:
        f.write("I am evil.")

    with mock.patch("os.startfile"), mock.patch("subprocess.Popen"):
        resp = client.post("/fs/action", json={"action": "OPEN_FILE", "target_path": outside_file})
    assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"


# ---------------------------------------------------------------------------
# B6: Path-prefix confusion — registered_folder must NOT authorize -Evil sibling
# ---------------------------------------------------------------------------

def test_b6_path_prefix_confusion(isolated_app, tmp_path):
    """B6: C:\\FileMind-Test registered must NOT authorize C:\\FileMind-Test-Evil."""
    client, test_db, _ = isolated_app

    allowed_dir = str(tmp_path / "FileMind-Test")
    evil_dir = str(tmp_path / "FileMind-Test-Evil")
    os.makedirs(allowed_dir, exist_ok=True)
    os.makedirs(evil_dir, exist_ok=True)
    evil_file = os.path.join(evil_dir, "hack.txt")
    with open(evil_file, "w") as f:
        f.write("Path prefix confusion exploit attempt.")

    with test_db.session() as conn:
        repo = Repository(conn)
        repo.create_folder(allowed_dir)

    resp = client.post("/fs/action", json={"action": "COPY_PATH", "target_path": evil_file})
    assert resp.status_code == 403, (
        f"Path-prefix confusion: expected 403 for sibling directory, got {resp.status_code}"
    )


# ---------------------------------------------------------------------------
# B7: ../ traversal cannot escape registered folder
# ---------------------------------------------------------------------------

def test_b7_traversal_cannot_escape(registered_folder, tmp_path):
    """B7: A path using ../ to escape the registered folder must be rejected."""
    client, _, folder_path, file_path, _ = registered_folder

    # Construct a traversal path that resolves outside the registered folder
    # After normalization, os.path.normpath resolves the .. — so we need a file
    # that actually exists outside. Create one and craft the raw traversal path.
    outside_dir = str(tmp_path / "escape_target")
    os.makedirs(outside_dir, exist_ok=True)
    escape_file = os.path.join(outside_dir, "secret.txt")
    with open(escape_file, "w") as f:
        f.write("Escaped file content.")

    # The traversal raw path: registered_folder/../escape_target/secret.txt
    traversal_path = os.path.join(folder_path, "..", "escape_target", "secret.txt")

    resp = client.post("/fs/action", json={"action": "COPY_PATH", "target_path": traversal_path})
    # normalize_path will canonicalize the traversal — the canonical path will be outside
    # the registered folder, so the scope check should 403 it.
    assert resp.status_code == 403, (
        f"Traversal escape: expected 403, got {resp.status_code}. Traversal: {traversal_path}"
    )


# ---------------------------------------------------------------------------
# B8: Windows case-insensitive canonical path comparison
# ---------------------------------------------------------------------------

@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only case-insensitivity test")
def test_b8_windows_case_insensitive_path(registered_folder):
    """B8: COPY_PATH with mixed-case registered-folder path works correctly on Windows."""
    client, _, folder_path, file_path, _ = registered_folder

    # Uppercase the full path — Windows paths are case-insensitive
    upper_path = file_path.upper()
    resp = client.post("/fs/action", json={"action": "COPY_PATH", "target_path": upper_path})
    # The file exists (case-insensitive FS) and is within the registered folder
    assert resp.status_code in (200, 404), (
        f"Case-insensitive path: unexpected status {resp.status_code}: {resp.text}"
    )


# ---------------------------------------------------------------------------
# B9: Existing legitimate search-result COPY_PATH still works
# ---------------------------------------------------------------------------

def test_b9_legitimate_search_result_copy_path_works(registered_folder):
    """B9: A COPY_PATH from a real search result (file inside registered folder) succeeds."""
    client, _, folder_path, file_path, _ = registered_folder

    resp = client.post("/fs/action", json={"action": "COPY_PATH", "target_path": file_path})
    assert resp.status_code == 200, f"Legitimate COPY_PATH failed: {resp.status_code}: {resp.text}"
    body = resp.json()
    assert body["success"] is True
    assert "allowed_file.txt" in body["target_path"]


# ---------------------------------------------------------------------------
# B10: Symlink pointing outside registered folder -> 403 Forbidden
# ---------------------------------------------------------------------------

def test_b10_symlink_pointing_outside_rejected(registered_folder, tmp_path):
    """B10: Symlink inside registered folder pointing outside must be rejected with 403."""
    client, _, folder_path, _, _ = registered_folder

    outside_target = str(tmp_path / "outside_target.txt")
    with open(outside_target, "w") as f:
        f.write("Secret outside content")

    symlink_path = os.path.join(folder_path, "symlink_outside.txt")
    symlink_created = False
    try:
        os.symlink(outside_target, symlink_path)
        symlink_created = True
    except OSError:
        pass

    if symlink_created:
        resp = client.post("/fs/action", json={"action": "COPY_PATH", "target_path": symlink_path})
        assert resp.status_code == 403, f"Expected 403 for symlink, got {resp.status_code}: {resp.text}"
    else:
        # If unprivileged Windows user without Developer Mode, verify via mock
        with mock.patch("app.core.security.is_symlink_or_junction", return_value=True):
            resp = client.post("/fs/action", json={"action": "COPY_PATH", "target_path": str(tmp_path / "registered_folder" / "allowed_file.txt")})
            assert resp.status_code == 403


# ---------------------------------------------------------------------------
# B11: Symlink pointing inside registered folder -> 403 Forbidden
# ---------------------------------------------------------------------------

def test_b11_symlink_pointing_inside_rejected(registered_folder):
    """B11: Symlinks pointing inside the registered folder are also forbidden."""
    client, _, folder_path, file_path, _ = registered_folder

    symlink_path = os.path.join(folder_path, "symlink_inside.txt")
    symlink_created = False
    try:
        os.symlink(file_path, symlink_path)
        symlink_created = True
    except OSError:
        pass

    if symlink_created:
        resp = client.post("/fs/action", json={"action": "COPY_PATH", "target_path": symlink_path})
        assert resp.status_code == 403, f"Expected 403 for internal symlink, got {resp.status_code}: {resp.text}"
    else:
        with mock.patch("app.core.security.is_symlink_or_junction", return_value=True):
            resp = client.post("/fs/action", json={"action": "COPY_PATH", "target_path": file_path})
            assert resp.status_code == 403


# ---------------------------------------------------------------------------
# B12: Directory containing symlink/junction in parent hierarchy -> 403 Forbidden
# ---------------------------------------------------------------------------

def test_b12_intermediate_symlink_directory_rejected(registered_folder):
    """B12: Path where a parent directory is a symlink/junction must be rejected."""
    client, _, folder_path, file_path, _ = registered_folder

    with mock.patch("app.core.security.contains_symlink_or_junction", return_value=True):
        resp = client.post("/fs/action", json={"action": "COPY_PATH", "target_path": file_path})
        assert resp.status_code == 403
        assert "symlinks and junctions" in resp.json().get("detail", "").lower()


# ---------------------------------------------------------------------------
# B13: Normal registered folder for OPEN_FOLDER -> 200 OK
# ---------------------------------------------------------------------------

def test_b13_normal_registered_folder_open_allowed(registered_folder):
    """B13: Opening a legitimate registered folder itself must succeed."""
    client, _, folder_path, _, _ = registered_folder

    with mock.patch("os.startfile"), mock.patch("subprocess.Popen"):
        resp = client.post("/fs/action", json={"action": "OPEN_FOLDER", "target_path": folder_path})
    assert resp.status_code == 200
    assert resp.json()["success"] is True
