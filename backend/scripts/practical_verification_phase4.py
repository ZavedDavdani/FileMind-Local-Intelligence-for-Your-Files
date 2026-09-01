"""Practical Verification Script for Phase 4: Reranking / Cross-Encoder.

Target directory: C:\\FileMind-Practical-Test
Documents:
1. sample.txt
2. test.txt
3. notes.md

Tests:
1. Ingestion and indexing into local SQLite + sqlite-vec + FTS5 database.
2. Cross-Encoder Model warm load and verification.
3. Execution of all required test queries.
4. Detailed output of:
   - Rank
   - Source File
   - Snippet
   - Final Score
   - Reranker Score
   - RRF Score
   - Dense Score
   - Lexical Score
   - Retrieval Method
   - Latency Breakdown (normalization, lexical_search, query_embedding, dense_search, rrf_fusion, reranker_inference, total_request)
5. Comparison between pure RRF (un-reranked) vs Reranked output.
"""

import json
import os
import sys
import tempfile
import time
from typing import Any, Dict, List

# Ensure backend app is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.config import DEFAULT_RERANK_MODEL_NAME
DEFAULT_EMBEDDING_MODEL_NAME = "BAAI/bge-small-en-v1.5"
from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.db.repository import Repository
from app.intelligence.chunker.hierarchical import HierarchicalChunker
from app.intelligence.parsers.registry import default_parser_registry
from app.retrieval.embeddings import default_embedding_engine
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.reranker import default_reranker
from app.retrieval.vector_store import SqliteVecStore


def run_practical_verification(target_dir: str = r"C:\FileMind-Practical-Test"):
    print("=" * 80)
    print("FILEMIND PHASE 4 PRACTICAL VERIFICATION RUN")
    print("=" * 80)
    print(f"Target Directory: {target_dir}")
    print(f"Dense Model:     {DEFAULT_EMBEDDING_MODEL_NAME}")
    print(f"Reranker Model:  {DEFAULT_RERANK_MODEL_NAME}")
    print("-" * 80)

    if not os.path.isdir(target_dir):
        print(f"ERROR: Target directory does not exist: {target_dir}")
        return

    # Create temporary database for practical verification
    temp_dir = tempfile.mkdtemp(prefix="filemind_p4_")
    db_path = os.path.join(temp_dir, "practical_p4.db")
    print(f"Created isolated test DB at: {db_path}")

    db_mgr = DatabaseManager(db_path)
    with db_mgr.session() as conn:
        apply_migrations(conn)
        repo = Repository(conn)
        vec_store = SqliteVecStore(conn, dimension=default_embedding_engine.dimension)

        folder_rec = repo.create_folder(target_dir)
        folder_id = folder_rec["folder_id"]

        chunker = HierarchicalChunker()

        # Ingest files
        file_records = []
        files = sorted(os.listdir(target_dir))
        print(f"\nDiscovered {len(files)} files in {target_dir}:")

        for fname in files:
            fpath = os.path.join(target_dir, fname)
            if not os.path.isfile(fpath):
                continue
            ext = os.path.splitext(fname)[1].lower()
            size = os.path.getsize(fpath)
            mod_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(os.path.getmtime(fpath)))

            f_rec = repo.upsert_file(
                folder_id=folder_id,
                path=fpath,
                relative_path=fname,
                filename=fname,
                extension=ext,
                size_bytes=size,
                modified_at=mod_time,
                index_status="PROCESSING",
            )
            file_id = f_rec["file_id"]

            parser = default_parser_registry.get_parser_for_file(fpath)
            if not parser:
                print(f"  - No parser for {fname}, skipping")
                continue

            doc = parser.parse(fpath, file_id=file_id)
            chunks = chunker.chunk_document(doc)

            repo.replace_file_chunks(file_id, chunks)

            # Generate vectors
            embeddings = default_embedding_engine.embed_texts([c.content for c in chunks])
            vector_records = []
            for c, emb in zip(chunks, embeddings):
                vector_records.append({
                    "chunk_id": c.chunk_id,
                    "file_id": file_id,
                    "embedding": emb,
                })
            vec_store.upsert_vectors(vector_records)

            repo.update_file_status(file_id, "INDEXED")
            print(f"  - Indexed '{fname}' ({size} bytes, {len(chunks)} chunks, {len(vector_records)} vectors)")
            file_records.append(f_rec)

        print("\nAll files successfully indexed into FTS5 and sqlite-vec.")

        # Prepare retrievers
        retriever_with_reranker = HybridRetriever(
            db_conn=conn,
            embedding_engine=default_embedding_engine,
            vector_store=vec_store,
            reranker=default_reranker,
        )
        retriever_pure_rrf = HybridRetriever(
            db_conn=conn,
            embedding_engine=default_embedding_engine,
            vector_store=vec_store,
            reranker=None,
        )

        test_queries = [
            "sample",
            "sample.txt",
            "test",
            "notes",
            "practical",
            "verification",
            "practical verification",
            "FILEMIND_PRACTICAL_ALPHA",
            "FILEMIND_PRACTICAL_ALPHA_7319",
            "filemind practical",
            "How does FileMind find information from documents stored on the local computer?",
            "local document storage and multi-file indexing",
        ]

        print("\n" + "=" * 80)
        print("EXECUTING PRACTICAL TEST QUERIES")
        print("=" * 80)

        for q in test_queries:
            print(f"\n>>> QUERY: \"{q}\"")

            # Execute with Reranker
            res_rerank = retriever_with_reranker.search(q, top_k=3, mode="hybrid")
            # Execute with Pure RRF (Pre-Phase-4 baseline)
            res_rrf = retriever_pure_rrf.search(q, top_k=3, mode="hybrid")

            lat = res_rerank["latency_breakdown_ms"]
            print(f"    Latency: Total={lat['total_request']}ms | Norm={lat['normalization']}ms | Lex={lat['lexical_search']}ms | Emb={lat['query_embedding']}ms | Dense={lat['dense_search']}ms | RRF={lat['rrf_fusion']}ms | Rerank={lat['reranker_inference']}ms")
            print(f"    Degraded: {res_rerank['degraded']} | Method: {res_rerank['retrieval_method']}")
            print(f"    Results (Top {len(res_rerank['results'])}):")

            for item in res_rerank["results"]:
                rank = item["rank"]
                sf = item["source_file"]
                score = item["score"]
                rerank_sc = item.get("reranker_score")
                rrf_sc = item.get("rrf_score")
                dense_sc = item.get("dense_score")
                lex_sc = item.get("lexical_score")
                snippet = item.get("snippet", "").replace("\n", " ")
                if len(snippet) > 90:
                    snippet = snippet[:87] + "..."

                rerank_str = f"{rerank_sc:.4f}" if rerank_sc is not None else "None"
                rrf_str = f"{rrf_sc:.4f}" if rrf_sc is not None else "None"
                dense_str = f"{dense_sc:.3f}" if dense_sc is not None else "None"
                lex_str = f"{lex_sc:.1f}" if lex_sc is not None else "None"

                print(f"      #{rank} [{sf}] Score={score:.4f} (Rerank={rerank_str}, RRF={rrf_str}, Dense={dense_str}, BM25={lex_str})")
                print(f"         Snippet: \"{snippet}\"")

            # Compare RRF order vs Reranked order
            rrf_top = [r["source_file"] for r in res_rrf["results"][:3]]
            rerank_top = [r["source_file"] for r in res_rerank["results"][:3]]
            if rrf_top != rerank_top:
                print(f"    * REORDERING OBSERVED: RRF order {rrf_top} -> Reranked order {rerank_top}")
            else:
                print(f"    * Order maintained: {rerank_top}")


if __name__ == "__main__":
    run_practical_verification()
