import os
import shutil
import tempfile
import pytest
from fastapi.testclient import TestClient

from app.core.security import normalize_path, paths_overlap, find_overlapping_path
from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.db.repository import Repository
from app.main import app, db_manager


@pytest.fixture
def client_env():
    """Sets up a temporary database and FastAPI test client."""
    tmp_dir = tempfile.mkdtemp(prefix="filemind_p1_2_")
    db_path = os.path.join(tmp_dir, "test.db")
    custom_mgr = DatabaseManager(db_path=db_path)
    with custom_mgr.session() as conn:
        apply_migrations(conn)

    old_mgr = app.dependency_overrides.get("db_manager")
    # Point the global db_manager to our temporary database
    import app.main as main_module
    saved_mgr = main_module.db_manager
    main_module.db_manager = custom_mgr

    client = TestClient(app)
    yield client, tmp_dir, custom_mgr

    main_module.db_manager = saved_mgr
    shutil.rmtree(tmp_dir, ignore_errors=True)


def test_paths_overlap_unit_logic():
    """Unit tests for paths_overlap pure logic."""
    # 1. Exact matches
    assert paths_overlap(r"C:\Data", r"C:\Data") is True

    # 2. Child vs Parent
    assert paths_overlap(r"C:\Data\Projects", r"C:\Data") is True
    assert paths_overlap(r"C:\Data", r"C:\Data\Projects") is True

    # 3. Case insensitivity
    assert paths_overlap(r"c:\data\projects", r"C:\DATA") is True
    assert paths_overlap(r"C:\DATA", r"c:\data\projects") is True

    # 4. Trailing separator differences
    assert paths_overlap(r"C:\Data\Projects\\", r"C:\Data") is True
    assert paths_overlap(r"C:\Data\\", r"C:\Data\Projects") is True

    # 5. Similar-but-not-overlapping (prefix sharing without boundary)
    assert paths_overlap(r"C:\Data", r"C:\Database") is False
    assert paths_overlap(r"C:\Database", r"C:\Data") is False

    # 6. Sibling directories sharing parent
    assert paths_overlap(r"C:\Data\Project", r"C:\Data\Projects") is False
    assert paths_overlap(r"C:\Data\Projects", r"C:\Data\Project") is False
    assert paths_overlap(r"C:\Data\Project1", r"C:\Data\Project2") is False

    # 7. find_overlapping_path helper
    existing = [r"C:\Vault\Personal", r"C:\Vault\Work"]
    assert find_overlapping_path(r"C:\Vault\Personal\Notes", existing) == r"C:\Vault\Personal"
    assert find_overlapping_path(r"C:\Vault", existing) in (r"C:\Vault\Personal", r"C:\Vault\Work")
    assert find_overlapping_path(r"C:\Vault\Finance", existing) is None


def test_p1_2_api_exact_duplicate_rejected(client_env):
    """Scenario 1 & 4 & 5: Exact duplicate and case/trailing-slash variations are rejected."""
    client, tmp_dir, _ = client_env
    data_dir = os.path.join(tmp_dir, "Data")
    os.makedirs(data_dir, exist_ok=True)

    # 1. Register base folder
    resp1 = client.post("/folders", json={"path": data_dir, "recursive": True, "indexing_enabled": False})
    assert resp1.status_code == 201
    folder_id = resp1.json()["folder_id"]

    # 2. Exact duplicate
    resp2 = client.post("/folders", json={"path": data_dir, "recursive": True, "indexing_enabled": False})
    assert resp2.status_code == 409
    assert "already registered" in resp2.json()["detail"].lower()

    # 3. Case variation (e.g. data vs Data)
    case_variant = os.path.join(tmp_dir, "DATA" if os.name == "nt" else "Data")
    resp_case = client.post("/folders", json={"path": case_variant, "recursive": True, "indexing_enabled": False})
    if os.name == "nt":
        assert resp_case.status_code == 409
        assert "already registered" in resp_case.json()["detail"].lower()

    # 4. Trailing separator variant
    trailing_variant = data_dir + os.sep
    resp_trailing = client.post("/folders", json={"path": trailing_variant, "recursive": True, "indexing_enabled": False})
    assert resp_trailing.status_code == 409


def test_p1_2_api_child_root_rejected_when_parent_exists(client_env):
    """Scenario 2: Child root is rejected when parent already exists."""
    client, tmp_dir, custom_mgr = client_env
    parent_dir = os.path.join(tmp_dir, "ParentVault")
    child_dir = os.path.join(parent_dir, "ChildProject")
    os.makedirs(child_dir, exist_ok=True)

    # 1. Register parent
    resp_p = client.post("/folders", json={"path": parent_dir, "recursive": True, "indexing_enabled": False})
    assert resp_p.status_code == 201

    # 2. Attempt registering child -> MUST be rejected with 400
    resp_c = client.post("/folders", json={"path": child_dir, "recursive": True, "indexing_enabled": False})
    assert resp_c.status_code == 400
    assert "cannot register subdirectory" in resp_c.json()["detail"].lower()

    # 3. Ensure folder set remains exactly 1
    with custom_mgr.session() as conn:
        repo = Repository(conn)
        folders = repo.list_folders()
        assert len(folders) == 1
        assert folders[0]["path"] == normalize_path(parent_dir)


def test_p1_2_api_parent_root_rejected_when_child_exists(client_env):
    """Scenario 3: Parent root is rejected when child already exists."""
    client, tmp_dir, custom_mgr = client_env
    parent_dir = os.path.join(tmp_dir, "MainVault")
    child_dir = os.path.join(parent_dir, "SubProject")
    os.makedirs(child_dir, exist_ok=True)

    # 1. Register child first
    resp_c = client.post("/folders", json={"path": child_dir, "recursive": True, "indexing_enabled": False})
    assert resp_c.status_code == 201

    # 2. Attempt registering parent -> MUST be rejected with 400
    resp_p = client.post("/folders", json={"path": parent_dir, "recursive": True, "indexing_enabled": False})
    assert resp_p.status_code == 400
    assert "cannot register parent directory" in resp_p.json()["detail"].lower()

    # 3. Ensure folder set remains exactly 1
    with custom_mgr.session() as conn:
        repo = Repository(conn)
        folders = repo.list_folders()
        assert len(folders) == 1
        assert folders[0]["path"] == normalize_path(child_dir)


def test_p1_2_api_similar_non_overlapping_paths_allowed(client_env):
    """Scenario 6 & 7: Sibling and prefix-sharing paths that do NOT overlap are allowed."""
    client, tmp_dir, custom_mgr = client_env
    data_dir = os.path.join(tmp_dir, "Data")
    database_dir = os.path.join(tmp_dir, "Database")
    project1_dir = os.path.join(tmp_dir, "DataProject1")
    project2_dir = os.path.join(tmp_dir, "DataProject2")

    for d in (data_dir, database_dir, project1_dir, project2_dir):
        os.makedirs(d, exist_ok=True)

    # Register all four distinct directories
    r1 = client.post("/folders", json={"path": data_dir, "recursive": True, "indexing_enabled": False})
    assert r1.status_code == 201

    r2 = client.post("/folders", json={"path": database_dir, "recursive": True, "indexing_enabled": False})
    assert r2.status_code == 201

    r3 = client.post("/folders", json={"path": project1_dir, "recursive": True, "indexing_enabled": False})
    assert r3.status_code == 201

    r4 = client.post("/folders", json={"path": project2_dir, "recursive": True, "indexing_enabled": False})
    assert r4.status_code == 201

    # Ensure all 4 were registered cleanly
    with custom_mgr.session() as conn:
        repo = Repository(conn)
        assert len(repo.list_folders()) == 4


def test_p1_2_failed_registration_enqueues_no_work(client_env):
    """Scenario 8 & 9: Failed registration does not mutate DB or trigger coordinator indexing."""
    client, tmp_dir, custom_mgr = client_env
    parent_dir = os.path.join(tmp_dir, "SafeParent")
    child_dir = os.path.join(parent_dir, "Sub")
    os.makedirs(child_dir, exist_ok=True)

    # Register parent
    resp1 = client.post("/folders", json={"path": parent_dir, "recursive": True, "indexing_enabled": False})
    assert resp1.status_code == 201

    # Attempt registering child with indexing_enabled = True
    resp2 = client.post("/folders", json={"path": child_dir, "recursive": True, "indexing_enabled": True})
    assert resp2.status_code == 400

    # Ensure no files, chunks, or jobs were created for child
    with custom_mgr.session() as conn:
        repo = Repository(conn)
        assert len(repo.list_folders()) == 1
        assert repo.count_files() == 0
