"""Tests for app.core.deps and app.core.errors."""

import logging
import pytest
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.testclient import TestClient

from app.core.deps import make_repo_dependency, get_repo
from app.core.errors import map_service_errors
from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.db.repository import Repository

test_logger = logging.getLogger("test_logger")


def test_make_repo_dependency_lifecycle(tmp_path):
    db = DatabaseManager(str(tmp_path / "dep_test.db"))
    with db.session() as conn:
        apply_migrations(conn)

    custom_get_repo = make_repo_dependency(db)
    
    app_test = FastAPI()

    @app_test.get("/test-repo")
    def route_using_repo(repo: Repository = Depends(custom_get_repo)):
        folders = repo.list_folders()
        return {"folders_count": len(folders)}

    client = TestClient(app_test)
    resp = client.get("/test-repo")
    assert resp.status_code == 200
    assert resp.json() == {"folders_count": 0}


def test_dependency_override_works(tmp_path):
    class FakeRepository:
        def list_folders(self):
            return [{"folder_id": "fake-1", "path": "C:/fake"}]

    app_test = FastAPI()

    @app_test.get("/folders")
    def route_using_repo(repo: Repository = Depends(get_repo)):
        return repo.list_folders()

    app_test.dependency_overrides[get_repo] = lambda: FakeRepository()

    client = TestClient(app_test)
    resp = client.get("/folders")
    assert resp.status_code == 200
    assert resp.json() == [{"folder_id": "fake-1", "path": "C:/fake"}]


def test_map_service_errors_value_error():
    @map_service_errors(test_logger, "test action")
    def fn_value_error():
        raise ValueError("Item not found on disk")

    with pytest.raises(HTTPException) as exc_info:
        fn_value_error()
    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Item not found on disk"


def test_map_service_errors_runtime_error():
    @map_service_errors(test_logger, "test action")
    def fn_runtime_error():
        raise RuntimeError("Generation job in progress")

    with pytest.raises(HTTPException) as exc_info:
        fn_runtime_error()
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Generation job in progress"


def test_map_service_errors_http_exception_preserved():
    @map_service_errors(test_logger, "test action")
    def fn_http_error():
        raise HTTPException(status_code=403, detail="Custom forbidden")

    with pytest.raises(HTTPException) as exc_info:
        fn_http_error()
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Custom forbidden"


def test_map_service_errors_generic_exception():
    @map_service_errors(test_logger, "processing files", custom_500_detail="Custom 500 msg")
    def fn_generic_error():
        raise KeyError("unexpected key")

    with pytest.raises(HTTPException) as exc_info:
        fn_generic_error()
    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "Custom 500 msg"
