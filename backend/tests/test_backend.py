"""Unit tests for FileMind Phase 0 Backend API."""

import os
import sys
import tempfile
from fastapi.testclient import TestClient
import pytest

# Add backend directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.main import app, PORT
from app.schemas import HealthResponse, ActionType

client = TestClient(app)
if not app.state.context.engine_coordinator._is_initialized:
    app.state.context.engine_coordinator.initialize()


def test_health_endpoint_deterministic():
    """Verify GET /health returns meaningful health and subsystem readiness payload."""
    with TestClient(app) as c:
        response = c.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "FileMind Backend"
        assert data["version"] == "0.1.0"
        assert data["port"] == 24823
        assert data["ready"] is True
        assert data["database"] == "healthy"
        assert data["vector_store"] == "healthy"
        assert data["worker"] == "healthy"


def test_health_schema_validation():
    """Verify health response validates cleanly against Pydantic schema."""
    with TestClient(app) as c:
        response = c.get("/health")
        assert response.status_code == 200
        health = HealthResponse(**response.json())
        assert health.status == "healthy"
        assert health.port == 24823
        assert health.ready is True
        assert health.database == "healthy"
        assert health.vector_store == "healthy"
        assert health.worker == "healthy"


def test_enumerate_valid_folder():
    """Verify recursive file enumeration on a temporary folder hierarchy."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Create nested structure
        sub_dir = os.path.join(tmp_dir, "nested_folder")
        os.makedirs(sub_dir)

        file1 = os.path.join(tmp_dir, "doc1.txt")
        file2 = os.path.join(sub_dir, "doc2.pdf")

        with open(file1, "w", encoding="utf-8") as f:
            f.write("Hello FileMind")
        with open(file2, "wb") as f:
            f.write(b"%PDF-1.4 dummy content")

        reg_resp = client.post("/folders", json={"path": tmp_dir})
        assert reg_resp.status_code == 201
        folder_id = reg_resp.json()["folder_id"]
        try:
            response = client.post("/fs/enumerate", json={"folder_path": tmp_dir})
            assert response.status_code == 200
            data = response.json()

            assert data["folder_path"] == os.path.normpath(os.path.abspath(tmp_dir))
            assert data["file_count"] == 2
            assert data["scan_duration_ms"] >= 0.0
            assert len(data["files"]) == 2

            filenames = [f["filename"] for f in data["files"]]
            assert "doc1.txt" in filenames
            assert "doc2.pdf" in filenames

            # Check extensions
            ext_map = {f["filename"]: f["extension"] for f in data["files"]}
            assert ext_map["doc1.txt"] == ".txt"
            assert ext_map["doc2.pdf"] == ".pdf"
        finally:
            client.delete(f"/folders/{folder_id}")


def test_enumerate_nonexistent_folder():
    """Verify 404 response for nonexistent directory path."""
    nonexistent = r"C:\FileMindNonExistentDirectory_12345XYZ"
    response = client.post("/fs/enumerate", json={"folder_path": nonexistent})
    assert response.status_code == 404
    assert "Directory does not exist" in response.json()["detail"]


def test_enumerate_file_instead_of_folder():
    """Verify 400 response when passing a file path instead of a directory."""
    with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
        tmp_file.write(b"content")
        tmp_path = tmp_file.name

    try:
        response = client.post("/fs/enumerate", json={"folder_path": tmp_path})
        assert response.status_code == 400
        assert "not a directory" in response.json()["detail"]
    finally:
        os.unlink(tmp_path)


def test_enumerate_path_with_null_byte():
    """Verify 400 response when path contains illegal null bytes."""
    response = client.post("/fs/enumerate", json={"folder_path": "C:\\fake\x00dir"})
    assert response.status_code == 400


def test_action_copy_path():
    """Verify COPY_PATH returns validated canonical absolute path.

    The /fs/action endpoint requires target paths to be within a registered
    FileMind folder.  This test registers the temp directory via POST /folders
    and deregisters it after the assertion.
    """
    tmp_dir = tempfile.mkdtemp()
    tmp_path = os.path.join(tmp_dir, "test_action_file.txt")
    with open(tmp_path, "w") as f:
        f.write("test content")

    folder_id = None
    try:
        # Register the dedicated temp directory so the scope check passes
        reg_resp = client.post(
            "/folders",
            json={"path": tmp_dir, "recursive": False, "indexing_enabled": False},
        )
        assert reg_resp.status_code in (200, 201), (
            f"Failed to register temp dir: {reg_resp.status_code} {reg_resp.text}"
        )
        folder_id = reg_resp.json().get("folder_id")

        response = client.post(
            "/fs/action",
            json={"action": "COPY_PATH", "target_path": tmp_path},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["action"] == "COPY_PATH"
        assert data["target_path"] == os.path.normpath(os.path.abspath(tmp_path))
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        if folder_id:
            client.delete(f"/folders/{folder_id}")
        if os.path.exists(tmp_dir):
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)


def test_action_nonexistent_path():
    """Verify 404 response for safe action on nonexistent path."""
    response = client.post(
        "/fs/action",
        json={"action": "COPY_PATH", "target_path": r"C:\fake\nonexistent.txt"},
    )
    assert response.status_code == 404


def test_action_invalid_action_type():
    """Verify 422 validation error for disallowed/unsupported action."""
    with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
        tmp_path = tmp_file.name

    try:
        response = client.post(
            "/fs/action",
            json={"action": "DELETE_FILE", "target_path": tmp_path},
        )
        assert response.status_code == 422
    finally:
        os.unlink(tmp_path)


def test_search_endpoint():
    """Verify POST /search returns 200 with structured latency and results."""
    response = client.post(
        "/search",
        json={"query": "test query", "mode": "hybrid", "top_k": 5},
    )
    assert response.status_code == 200
    data = response.json()
    assert "query" in data
    assert "mode" in data
    assert "latency_breakdown_ms" in data
    assert "results" in data
    assert isinstance(data["results"], list)

