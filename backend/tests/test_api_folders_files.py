"""API Integration tests for Phase 1 folder, file, job, and indexing control endpoints."""

import os
import tempfile
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.engine.coordinator import coordinator


def test_folders_api_crud():
    with TestClient(app) as client:
        with tempfile.TemporaryDirectory() as tmp_folder:
            # 1. Register Folder
            create_resp = client.post(
                "/folders",
                json={
                    "path": tmp_folder,
                    "recursive": True,
                    "integrity_mode": "STRICT",
                    "indexing_enabled": True,
                    "exclude_patterns": ["*.tmp", "node_modules"],
                },
            )
            assert create_resp.status_code == 201
            folder_data = create_resp.json()
            folder_id = folder_data["folder_id"]
            assert folder_data["integrity_mode"] == "STRICT"
            assert folder_data["recursive"] is True
            assert "*.tmp" in folder_data["exclude_patterns"]

            # 2. List Folders
            list_resp = client.get("/folders")
            assert list_resp.status_code == 200
            folders = list_resp.json()
            assert any(f["folder_id"] == folder_id for f in folders)

            # 3. Get Single Folder
            get_resp = client.get(f"/folders/{folder_id}")
            assert get_resp.status_code == 200
            assert get_resp.json()["folder_id"] == folder_id

            # 4. Update Folder
            patch_resp = client.patch(
                f"/folders/{folder_id}",
                json={"integrity_mode": "NORMAL", "indexing_enabled": False},
            )
            assert patch_resp.status_code == 200
            assert patch_resp.json()["integrity_mode"] == "NORMAL"
            assert patch_resp.json()["indexing_enabled"] is False

            # 5. Delete Folder
            del_resp = client.delete(f"/folders/{folder_id}")
            assert del_resp.status_code == 204

            # 6. Verify Deletion
            get_deleted = client.get(f"/folders/{folder_id}")
            assert get_deleted.status_code == 404


def test_indexing_status_and_control():
    with TestClient(app) as client:
        # 1. Get Status
        status_resp = client.get("/indexing/status")
        assert status_resp.status_code == 200
        status_data = status_resp.json()
        assert "is_running" in status_data
        assert "total_files" in status_data
        assert "indexed" in status_data
        assert "progress_percent" in status_data

        # 2. Control: Pause
        pause_resp = client.post("/indexing/control", json={"action": "PAUSE"})
        assert pause_resp.status_code == 200
        assert pause_resp.json()["status"]["is_paused"] is True

        # 3. Control: Resume
        resume_resp = client.post("/indexing/control", json={"action": "RESUME"})
        assert resume_resp.status_code == 200
        assert resume_resp.json()["status"]["is_paused"] is False
