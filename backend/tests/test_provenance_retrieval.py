"""Integration tests verifying full provenance integrity from query through search results."""

import os
import sys
import tempfile
import pytest

from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.db.repository import Repository
from app.retrieval.hybrid import HybridRetriever
from tests.fixtures.benchmark_corpus import setup_benchmark_corpus


def test_provenance_chain_survives_retrieval():
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "prov_test.db")
    meta = setup_benchmark_corpus(temp_dir, db_path)
    db = DatabaseManager(db_path)

    test_queries = [
        "Cryptographic hashing with streaming SHA-256 validation",
        "Write-Ahead Logging (WAL) mode enabled",
        "def get_config():",
        "quarterly business revenue and financial profit margins",
    ]

    with db.session() as conn:
        retriever = HybridRetriever(conn)
        repo = Repository(conn)

        for q in test_queries:
            resp = retriever.search(q, top_k=5)
            assert len(resp["results"]) > 0

            for res in resp["results"]:
                retrieved_cid = res["chunk_id"]
                retrieved_fid = res["file_id"]

                # 1. Join with SQLite chunks table
                db_chunk = repo.get_chunk_by_id(retrieved_cid)
                assert db_chunk is not None, f"Retrieved chunk {retrieved_cid} not found in SQLite chunks table"
                assert db_chunk["chunk_id"] == retrieved_cid
                assert db_chunk["file_id"] == retrieved_fid
                assert db_chunk["source_file"] == res["source_file"]
                assert db_chunk["source_path"] == res["source_path"]
                assert db_chunk["content"] == res["content"]

                # 2. Join with SQLite files table
                db_file = repo.get_file_by_id(retrieved_fid)
                assert db_file is not None, f"Retrieved file {retrieved_fid} not found in SQLite files table"
                assert db_file["path"] == res["source_path"]
                assert db_file["filename"] == res["source_file"]
