import os
import sys
import time
import json
import sqlite3
import struct
import numpy as np
from pathlib import Path

# Add backend to sys.path
backend_dir = Path(r"c:\dev\FileMind\backend")
sys.path.insert(0, str(backend_dir))

from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.db.repository import Repository
from app.retrieval.vector_store import SqliteVecStore
from app.retrieval.lexical import LexicalRetriever
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.related import RelatedContentService
from app.ai.knowledge_connections import KnowledgeConnectionService
from app.ai.context import TokenEstimator


def run_benchmarks():
    print("=== FileMind Performance Benchmark Baseline ===")
    results = {}
    
    # 1. Database Connection & Pragma Lifecycle
    db_path = r"c:\dev\FileMind\backend\tests\performance\bench_db.sqlite"
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except Exception:
            pass
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    
    db = DatabaseManager(db_path)
    with db.session() as conn:
        apply_migrations(conn)
        vec_store = SqliteVecStore(conn, dimension=384)
        repo = Repository(conn)
        
        # Populate benchmark dataset: 1 folder, 200 files, 1000 chunks
        folder = repo.create_folder(r"C:\test_folder")
        folder_id = folder["folder_id"]
        
        print("Populating synthetic benchmark dataset (200 files, 1000 chunks)...")
        file_ids = []
        for i in range(200):
            fid = f"file_{i:04d}"
            fn = f"report_{i}.pdf" if i % 2 == 0 else f"notes_{i}.md"
            ext = ".pdf" if i % 2 == 0 else ".md"
            repo.upsert_file(
                folder_id=folder_id,
                path=f"C:\\test_folder\\{fn}",
                relative_path=fn,
                filename=fn,
                extension=ext,
                size_bytes=1024 * (i + 1),
                modified_at="2026-09-05T12:00:00Z",
                file_id=fid,
            )
            repo.update_file_status(fid, "INDEXED")
            file_ids.append(fid)
            
            # 5 chunks per file
            chunk_records = []
            vec_records = []
            for c in range(5):
                cid = f"chk_{i:04d}_{c:02d}"
                content = f"Financial summary and quarterly earnings report {i} section {c}. Revenue grew by {i*10} percent. Machine learning embeddings."
                repo.conn.execute(
                    """
                    INSERT INTO chunks (chunk_id, file_id, source_file, source_path, h1_parent, h2_parent, section, page, chunk_index, content_hash, parser_name, parser_version, chunker_version, content)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (cid, fid, fn, f"C:\\test_folder\\{fn}", f"Header {c}", f"Subheader {c}", f"Section {c}", c + 1, c, f"hash_{i}_{c}", "test_parser", "1.0", "1.0", content)
                )
                vec = np.random.randn(384).astype(np.float32)
                vec = (vec / np.linalg.norm(vec)).tolist()
                vec_records.append({
                    "chunk_id": cid,
                    "embedding": vec,
                    "file_id": fid
                })
            vec_store.upsert_vectors(vec_records)
            
            # Document insight for first 50 files
            if i < 50:
                repo.upsert_document_insight(
                    file_id=fid,
                    status="READY",
                    content_hash=f"hash_{i}_0",
                    parser_version="1.0.0",
                    chunker_version="1.0.0",
                    model_provider="ollama",
                    model_name="qwen3:4b",
                    model_tag="qwen3:4b",
                    executive_summary=f"Executive summary for file {i}.",
                    key_topics=["financials", "revenue growth", f"topic_{i%10}"],
                    key_decisions=["Approved expansion"],
                    citations=[{"chunk_id": f"chk_{i:04d}_00", "source_file": fn, "section": "Section 0", "content_hash": f"hash_{i}_0"}],
                )

    # Benchmark 1: DB Connection Creation
    t0 = time.perf_counter()
    N_CONNS = 50
    for _ in range(N_CONNS):
        with db.session() as conn:
            conn.execute("SELECT 1;").fetchone()
    db_conn_ms = ((time.perf_counter() - t0) / N_CONNS) * 1000.0
    results["db_connection_open_and_close_ms"] = round(db_conn_ms, 3)
    print(f"1. DB Session open + PRAGMAs + sqlite-vec load + close: {db_conn_ms:.3f} ms / session")

    # Benchmark 2: Vector Packing (struct.pack vs numpy tobytes)
    sample_vec = np.random.randn(384).astype(np.float32).tolist()
    sample_arr = np.array(sample_vec, dtype=np.float32)
    
    t0 = time.perf_counter()
    N_VECS = 10000
    for _ in range(N_VECS):
        struct.pack("384f", *sample_vec)
    struct_ms = (time.perf_counter() - t0) * 1000.0
    
    t0 = time.perf_counter()
    for _ in range(N_VECS):
        sample_arr.astype(np.float32, copy=False).tobytes()
    numpy_ms = (time.perf_counter() - t0) * 1000.0
    
    results["struct_pack_10k_ms"] = round(struct_ms, 3)
    results["numpy_tobytes_10k_ms"] = round(numpy_ms, 3)
    print(f"2. Vector packing 10,000 vectors: struct.pack={struct_ms:.2f} ms vs numpy tobytes={numpy_ms:.2f} ms ({struct_ms/numpy_ms:.1f}x speedup)")

    # Benchmark 3: Token Estimation
    estimator = TokenEstimator()
    ascii_text = "The quick brown fox jumps over the lazy dog. Financial earnings summary." * 50
    cjk_text = "这是一个测试文本，用于测试中文字符的标记估计性能。文件管理系统。" * 50
    
    t0 = time.perf_counter()
    N_TOK = 5000
    for _ in range(N_TOK):
        estimator.estimate(ascii_text)
    ascii_tok_ms = (time.perf_counter() - t0) * 1000.0
    
    t0 = time.perf_counter()
    for _ in range(N_TOK):
        estimator.estimate(cjk_text)
    cjk_tok_ms = (time.perf_counter() - t0) * 1000.0
    
    results["token_estimate_ascii_5k_ms"] = round(ascii_tok_ms, 3)
    results["token_estimate_cjk_5k_ms"] = round(cjk_tok_ms, 3)
    print(f"3. Token Estimator 5,000 runs: ASCII={ascii_tok_ms:.2f} ms, CJK={cjk_tok_ms:.2f} ms")

    # Benchmark 4: Search Latency & Payload Size
    with db.session() as conn:
        lexical = LexicalRetriever(conn)
        vec_store = SqliteVecStore(conn, dimension=384)
        
        # BM25 Search
        t0 = time.perf_counter()
        for _ in range(20):
            lex_res = lexical.search("financial earnings report", top_k=10)
        lex_ms = ((time.perf_counter() - t0) / 20) * 1000.0
        results["bm25_search_latency_ms"] = round(lex_ms, 3)
        print(f"4a. BM25 Search latency: {lex_ms:.3f} ms (results count={len(lex_res)})")
        
        # Dense Search
        q_vec = np.random.randn(384).astype(np.float32)
        q_vec = (q_vec / np.linalg.norm(q_vec)).tolist()
        t0 = time.perf_counter()
        for _ in range(20):
            dense_res = vec_store.search(q_vec, top_k=10)
        dense_ms = ((time.perf_counter() - t0) / 20) * 1000.0
        results["dense_search_latency_ms"] = round(dense_ms, 3)
        print(f"4b. Dense Search latency: {dense_ms:.3f} ms (results count={len(dense_res)})")
        
        # Filtered Dense Search
        t0 = time.perf_counter()
        for _ in range(20):
            filtered_res = vec_store.search(q_vec, top_k=10, filters={"extension": ".pdf"})
        filtered_dense_ms = ((time.perf_counter() - t0) / 20) * 1000.0
        results["filtered_dense_search_latency_ms"] = round(filtered_dense_ms, 3)
        print(f"4c. Filtered Dense Search latency: {filtered_dense_ms:.3f} ms (results count={len(filtered_res)})")

    # Benchmark 5: Knowledge Connections
    kc_service = KnowledgeConnectionService(db)
    t0 = time.perf_counter()
    kc_res = kc_service.get_connections("file_0000")
    kc_ms = (time.perf_counter() - t0) * 1000.0
    results["knowledge_connections_latency_ms"] = round(kc_ms, 3)
    results["knowledge_connections_found"] = len(kc_res["connections"])
    print(f"5. Knowledge Connections latency: {kc_ms:.3f} ms (found {len(kc_res['connections'])} connections)")

    # Benchmark 6: Related Content
    rel_service = RelatedContentService(db_manager=db)
    t0 = time.perf_counter()
    rel_res = rel_service.get_related_files("file_0000", limit=5, quality="fast")
    rel_ms = (time.perf_counter() - t0) * 1000.0
    results["related_content_latency_ms"] = round(rel_ms, 3)
    results["related_content_found"] = rel_res["total_found"]
    print(f"6. Related Content latency: {rel_ms:.3f} ms (found {rel_res['total_found']} related files)")

    # Save benchmark results
    out_file = r"c:\dev\FileMind\docs\performance\baseline_measurements.json"
    os.makedirs(os.path.dirname(out_file), exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved baseline measurements to {out_file}")

if __name__ == "__main__":
    run_benchmarks()
