"""Integration test suite: Deep Lifecycle & Integrity Verification of Filesystem Engine."""

import os
import tempfile
import time
import pytest
from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.db.repository import Repository
from app.engine.coordinator import EngineCoordinator
from app.engine.hasher import compute_file_sha256


def test_full_filesystem_engine_lifecycle():
    with tempfile.TemporaryDirectory() as tmp_root:
        db_file = os.path.join(tempfile.gettempdir(), f"test_engine_{int(time.time()*1000)}.db")
        db = DatabaseManager(db_file)
        coordinator = EngineCoordinator(db)
        coordinator.initialize()

        try:
            # -------------------------------------------------------------
            # A. Initial Setup & Discovery
            # -------------------------------------------------------------
            f1 = os.path.join(tmp_root, "doc1.txt")
            f2 = os.path.join(tmp_root, "notes.md")
            sub_dir = os.path.join(tmp_root, "sub")
            os.makedirs(sub_dir, exist_ok=True)
            f3 = os.path.join(sub_dir, "nested.json")

            with open(f1, "w", encoding="utf-8") as f:
                f.write("Initial Content 1")
            with open(f2, "w", encoding="utf-8") as f:
                f.write("# Markdown Notes Header")
            with open(f3, "w", encoding="utf-8") as f:
                f.write('{"config_key": "initial_value"}')

            with db.session() as conn:
                repo = Repository(conn)
                folder = repo.create_folder(tmp_root, recursive=True, integrity_mode="NORMAL")
                folder_id = folder["folder_id"]

            scan_res = coordinator.scan_single_folder(folder_id)
            assert scan_res["total_scanned"] == 3
            assert scan_res["new_files"] == 3
            assert scan_res["modified_files"] == 0
            assert scan_res["errors"] == []

            # Wait for workers to process all 3 initial jobs
            for _ in range(60):
                time.sleep(0.05)
                stats = coordinator.get_aggregate_status()
                if stats["indexed"] == 3 and stats["queued"] == 0 and stats["processing"] == 0:
                    break

            # Assert SQLite State Consistency for Initial Discovery
            with db.session() as conn:
                repo = Repository(conn)
                files = repo.list_files(folder_id=folder_id)
                assert len(files) == 3

                file_map = {f["filename"]: f for f in files}
                assert "doc1.txt" in file_map
                assert "notes.md" in file_map
                assert "nested.json" in file_map

                assert file_map["doc1.txt"]["index_status"] == "INDEXED"
                assert file_map["doc1.txt"]["sha256"] is not None
                assert file_map["doc1.txt"]["size_bytes"] == len("Initial Content 1")
                assert file_map["doc1.txt"]["extension"] == ".txt"
                assert file_map["doc1.txt"]["indexed_at"] is not None

                assert file_map["nested.json"]["relative_path"] in ("sub/nested.json", "sub\\nested.json")
                assert file_map["nested.json"]["index_status"] == "INDEXED"

                f1_initial_sha = file_map["doc1.txt"]["sha256"]
                f1_id = file_map["doc1.txt"]["file_id"]

            # -------------------------------------------------------------
            # B. Live File Creation After Indexing
            # -------------------------------------------------------------
            f4 = os.path.join(tmp_root, "created_later.txt")
            time.sleep(0.05)
            with open(f4, "w", encoding="utf-8") as f:
                f.write("File created dynamically after initial index")

            scan_res_new = coordinator.scan_single_folder(folder_id)
            assert scan_res_new["new_files"] == 1
            assert scan_res_new["total_scanned"] == 4

            for _ in range(60):
                time.sleep(0.05)
                stats = coordinator.get_aggregate_status()
                if stats["indexed"] == 4 and stats["queued"] == 0:
                    break

            with db.session() as conn:
                repo = Repository(conn)
                f4_rec = repo.get_file_by_path(f4)
                assert f4_rec is not None
                assert f4_rec["index_status"] == "INDEXED"
                assert f4_rec["sha256"] is not None

            # -------------------------------------------------------------
            # C. File Modification (Content & Timestamp update)
            # -------------------------------------------------------------
            time.sleep(0.05)
            with open(f1, "w", encoding="utf-8") as f:
                f.write("Updated Content 1 with distinct cryptographic SHA-256")

            scan_res_mod = coordinator.scan_single_folder(folder_id)
            assert scan_res_mod["modified_files"] == 1

            for _ in range(60):
                time.sleep(0.05)
                with db.session() as conn:
                    repo = Repository(conn)
                    f1_updated = repo.get_file_by_path(f1)
                    if f1_updated and f1_updated["index_status"] == "INDEXED" and f1_updated["sha256"] != f1_initial_sha:
                        break

            with db.session() as conn:
                repo = Repository(conn)
                f1_updated = repo.get_file_by_path(f1)
                assert f1_updated["file_id"] == f1_id  # Preserves file identity
                assert f1_updated["sha256"] != f1_initial_sha  # Validates hash change
                assert f1_updated["size_bytes"] == len("Updated Content 1 with distinct cryptographic SHA-256")

            # -------------------------------------------------------------
            # D. File Deletion Handling
            # -------------------------------------------------------------
            os.remove(f2)
            with db.session() as conn:
                repo = Repository(conn)
                repo.mark_file_missing(f2)
                f2_rec = repo.get_file_by_path(f2)
                assert f2_rec["index_status"] == "MISSING"

            # -------------------------------------------------------------
            # E. File Rename Handling (Preserves ID & Updates Stored Path)
            # -------------------------------------------------------------
            f4_renamed = os.path.join(tmp_root, "renamed_file.txt")
            os.rename(f4, f4_renamed)

            with db.session() as conn:
                repo = Repository(conn)
                f4_old_rec = repo.get_file_by_path(f4)
                f4_old_id = f4_old_rec["file_id"]
                repo.rename_file_path(
                    old_path=f4,
                    new_path=f4_renamed,
                    new_rel_path="renamed_file.txt",
                    new_filename="renamed_file.txt",
                    new_ext=".txt",
                )

                f4_new_rec = repo.get_file_by_path(f4_renamed)
                assert f4_new_rec is not None
                assert f4_new_rec["file_id"] == f4_old_id  # File ID identity preserved
                assert f4_new_rec["filename"] == "renamed_file.txt"
                assert repo.get_file_by_path(f4) is None  # Old path no longer indexed

            # -------------------------------------------------------------
            # F. File Move Handling (Moved into Subdirectory)
            # -------------------------------------------------------------
            f4_moved = os.path.join(sub_dir, "renamed_file.txt")
            os.rename(f4_renamed, f4_moved)

            with db.session() as conn:
                repo = Repository(conn)
                repo.rename_file_path(
                    old_path=f4_renamed,
                    new_path=f4_moved,
                    new_rel_path="sub/renamed_file.txt",
                    new_filename="renamed_file.txt",
                    new_ext=".txt",
                )
                f4_moved_rec = repo.get_file_by_path(f4_moved)
                assert f4_moved_rec is not None
                assert f4_moved_rec["file_id"] == f4_old_id
                assert f4_moved_rec["relative_path"] in ("sub/renamed_file.txt", "sub\\renamed_file.txt")

            # -------------------------------------------------------------
            # G. SQLite Foreign Key Integrity & Job Queue Consistency
            # -------------------------------------------------------------
            with db.session() as conn:
                repo = Repository(conn)
                counts = repo.count_files_by_status(folder_id)
                assert counts["INDEXED"] >= 2
                assert counts["MISSING"] == 1

                # Verify no orphan jobs exist
                cursor = conn.execute(
                    "SELECT COUNT(*) FROM indexing_jobs WHERE file_id NOT IN (SELECT file_id FROM files);"
                )
                assert cursor.fetchone()[0] == 0

            # -------------------------------------------------------------
            # H. Folder Removal CASCADE
            # -------------------------------------------------------------
            with db.session() as conn:
                repo = Repository(conn)
                deleted = repo.delete_folder(folder_id)
                assert deleted is True
                assert repo.get_folder(folder_id) is None
                assert len(repo.list_files(folder_id=folder_id)) == 0

        finally:
            coordinator.shutdown()
            try:
                if os.path.exists(db_file):
                    os.remove(db_file)
            except Exception:
                pass


def test_delete_handling_isolated():
    """Explicitly validates the delete handling contract: file removal on disk -> status MISSING & queue cleanup."""
    db_file = os.path.join(tempfile.gettempdir(), f"test_delete_iso_{int(time.time()*1000)}.db")
    db = DatabaseManager(db_file)
    with db.session() as conn:
        apply_migrations(conn)

    try:
        with tempfile.TemporaryDirectory() as tmp_root:
            file_path = os.path.join(tmp_root, "file_to_delete.txt")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("Delete test content")

            with db.session() as conn:
                repo = Repository(conn)
                folder = repo.create_folder(tmp_root)
                file_rec = repo.upsert_file(
                    folder_id=folder["folder_id"],
                    path=file_path,
                    relative_path="file_to_delete.txt",
                    filename="file_to_delete.txt",
                    extension=".txt",
                    size_bytes=len("Delete test content"),
                    modified_at="2026-08-30T00:00:00Z",
                    index_status="INDEXED",
                )
                file_id = file_rec["file_id"]

                # Enqueue a pending job
                job = repo.enqueue_job(file_id=file_id, folder_id=folder["folder_id"])
                assert job["status"] == "PENDING"

            # 1. Delete file on disk
            os.remove(file_path)
            assert not os.path.exists(file_path)

            # 2. Execute deletion handling contract in Repository
            with db.session() as conn:
                repo = Repository(conn)
                marked = repo.mark_file_missing(file_path)
                assert marked is True

                cancelled_count = repo.cancel_pending_jobs_for_file(file_id)
                assert cancelled_count >= 1

                # 3. Assert SQLite state consistency
                f_state = repo.get_file_by_id(file_id)
                assert f_state is not None
                assert f_state["index_status"] == "MISSING"

                # 4. Assert zero active/pending jobs remain for this deleted file
                cursor = conn.execute(
                    "SELECT COUNT(*) FROM indexing_jobs WHERE file_id = ? AND status IN ('PENDING', 'PROCESSING');",
                    (file_id,),
                )
                assert cursor.fetchone()[0] == 0

    finally:
        try:
            if os.path.exists(db_file):
                os.remove(db_file)
        except Exception:
            pass


def test_rename_handling_isolated():
    """Explicitly validates the rename handling contract: file rename preserves file_id identity and updates SQLite path."""
    db_file = os.path.join(tempfile.gettempdir(), f"test_rename_iso_{int(time.time()*1000)}.db")
    db = DatabaseManager(db_file)
    with db.session() as conn:
        apply_migrations(conn)

    try:
        with tempfile.TemporaryDirectory() as tmp_root:
            src_path = os.path.join(tmp_root, "original_name.txt")
            dst_path = os.path.join(tmp_root, "new_name.txt")
            with open(src_path, "w", encoding="utf-8") as f:
                f.write("Rename test content")

            with db.session() as conn:
                repo = Repository(conn)
                folder = repo.create_folder(tmp_root)
                file_rec = repo.upsert_file(
                    folder_id=folder["folder_id"],
                    path=src_path,
                    relative_path="original_name.txt",
                    filename="original_name.txt",
                    extension=".txt",
                    size_bytes=len("Rename test content"),
                    modified_at="2026-08-30T00:00:00Z",
                    index_status="INDEXED",
                )
                original_file_id = file_rec["file_id"]

            # 1. Rename file on disk
            os.rename(src_path, dst_path)
            assert not os.path.exists(src_path)
            assert os.path.exists(dst_path)

            # 2. Execute rename handling in Repository
            with db.session() as conn:
                repo = Repository(conn)
                renamed = repo.rename_file_path(
                    old_path=src_path,
                    new_path=dst_path,
                    new_rel_path="new_name.txt",
                    new_filename="new_name.txt",
                    new_ext=".txt",
                )
                assert renamed is True

                # 3. Assert old path is gone and new path has identical file_id
                assert repo.get_file_by_path(src_path) is None
                new_rec = repo.get_file_by_path(dst_path)
                assert new_rec is not None
                assert new_rec["file_id"] == original_file_id  # Provenance / file_id identity preserved
                assert new_rec["filename"] == "new_name.txt"
                assert new_rec["extension"] == ".txt"

    finally:
        try:
            if os.path.exists(db_file):
                os.remove(db_file)
        except Exception:
            pass


def test_move_handling_isolated():
    """Explicitly validates the move handling contract: file moved to subfolder updates relative_path and preserves folder_id and file_id."""
    db_file = os.path.join(tempfile.gettempdir(), f"test_move_iso_{int(time.time()*1000)}.db")
    db = DatabaseManager(db_file)
    with db.session() as conn:
        apply_migrations(conn)

    try:
        with tempfile.TemporaryDirectory() as tmp_root:
            sub_folder = os.path.join(tmp_root, "subfolder")
            os.makedirs(sub_folder, exist_ok=True)

            src_path = os.path.join(tmp_root, "moved_doc.txt")
            dst_path = os.path.join(sub_folder, "moved_doc.txt")
            with open(src_path, "w", encoding="utf-8") as f:
                f.write("Move test content")

            with db.session() as conn:
                repo = Repository(conn)
                folder = repo.create_folder(tmp_root)
                folder_id = folder["folder_id"]
                file_rec = repo.upsert_file(
                    folder_id=folder_id,
                    path=src_path,
                    relative_path="moved_doc.txt",
                    filename="moved_doc.txt",
                    extension=".txt",
                    size_bytes=len("Move test content"),
                    modified_at="2026-08-30T00:00:00Z",
                    index_status="INDEXED",
                )
                original_file_id = file_rec["file_id"]

            # 1. Move file on disk
            os.rename(src_path, dst_path)
            assert not os.path.exists(src_path)
            assert os.path.exists(dst_path)

            # 2. Execute move update in Repository
            with db.session() as conn:
                repo = Repository(conn)
                moved = repo.rename_file_path(
                    old_path=src_path,
                    new_path=dst_path,
                    new_rel_path="subfolder/moved_doc.txt",
                    new_filename="moved_doc.txt",
                    new_ext=".txt",
                )
                assert moved is True

                # 3. Assert relative path is updated and parent folder association remains intact
                assert repo.get_file_by_path(src_path) is None
                moved_rec = repo.get_file_by_path(dst_path)
                assert moved_rec is not None
                assert moved_rec["file_id"] == original_file_id
                assert moved_rec["folder_id"] == folder_id
                assert moved_rec["relative_path"] == "subfolder/moved_doc.txt"

    finally:
        try:
            if os.path.exists(db_file):
                os.remove(db_file)
        except Exception:
            pass
