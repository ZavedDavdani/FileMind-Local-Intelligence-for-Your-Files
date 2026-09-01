"""Regression tests for Bug #19: Adaptive dense fetch_k iteration cap."""

import os
import tempfile
import time
import pytest
from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.db.repository import Repository
from app.intelligence.chunker.provenance import ChunkProvenance
from app.retrieval.vector_store import SqliteVecStore


class CountingConnectionProxy:
    """Wraps an sqlite3 connection to count query executions without modifying the C-extension type."""

    def __init__(self, target_conn):
        self._conn = target_conn
        self.execute_count = 0

    def execute(self, sql, *args):
        if "FROM chunk_vectors" in sql:
            self.execute_count += 1
        return self._conn.execute(sql, *args)

    def fetchall(self):
        return self._conn.fetchall()

    def __getattr__(self, item):
        return getattr(self._conn, item)


def test_adaptive_search_respects_iteration_cap():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "test_cap_vec.db")
        db = DatabaseManager(db_path)
        with db.session() as conn:
            apply_migrations(conn)
            vec_store = SqliteVecStore(conn, dimension=4)
            repo = Repository(conn)
            folder_a = repo.create_folder(os.path.join(tmp_dir, "folder_a"))["folder_id"]

            vec_records = []
            for i in range(50):
                fid = f"fa_{i}"
                cid = f"ca_{i}"
                f_path = os.path.join(tmp_dir, f"file_{i}.txt")
                with open(f_path, "w", encoding="utf-8") as f:
                    f.write(f"content {i}")
                repo.upsert_file(folder_a, f_path, f"file_{i}.txt", f"file_{i}.txt", ".txt", 10, "2026-09-01T00:00:00Z", file_id=fid)
                chunk = ChunkProvenance(
                    chunk_id=cid,
                    file_id=fid,
                    source_file=f"file_{i}.txt",
                    source_path=f_path,
                    page=None,
                    section=None,
                    h1_parent=None,
                    h2_parent=None,
                    line_start=1,
                    line_end=1,
                    char_start=0,
                    char_end=10,
                    content_hash=f"h_{i}",
                    chunk_index=0,
                    parser_name="test_parser",
                    parser_version="1.0",
                    chunker_version="1.0",
                    content=f"content {i}",
                    content_type="text",
                    token_count=2,
                )
                repo.replace_file_chunks(fid, [chunk])
                vec_records.append({"chunk_id": cid, "file_id": fid, "embedding": [0.1 * (i % 4 + 1), 0.2, 0.3, 0.4]})

            vec_store.upsert_vectors(vec_records)

            proxy = CountingConnectionProxy(conn)
            vec_store.conn = proxy

            # Query with a filter that matches NO files (non-existent folder 'non_existent_folder_xyz')
            # Without cap, this could iterate indefinitely until fetch_k >= total_vectors
            # With cap (MAX_ADAPTIVE_ITERATIONS = 5), it must stop in at most 5 iterations
            q_vec = [0.1, 0.2, 0.3, 0.4]
            results = vec_store.search(q_vec, top_k=10, filters={"folder_id": "non_existent_folder_xyz"})
            assert results == []
            assert proxy.execute_count <= 5, f"Expected at most 5 vector queries, got {proxy.execute_count}"
            assert proxy.execute_count >= 1, f"Expected at least 1 vector query, got {proxy.execute_count}"
