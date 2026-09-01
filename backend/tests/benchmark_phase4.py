"""Phase 4 Fast / Quality Benchmark Runner and Evaluation Harness.

Evaluates 4 retrieval configurations across the canonical 28-query evaluation dataset:
1. BM25 Fast (Lexical only)
2. Dense Fast (Vector only)
3. Hybrid Fast (BM25 + Dense + RRF)
4. Hybrid Quality (BM25 + Dense + RRF + Cross-Encoder BAAI/bge-reranker-base)

Measures:
- Retrieval Quality: Recall@1, Recall@3, Recall@5, Recall@10, MRR, NDCG@10
- Performance: p50, p95, min, max, mean latencies, per-stage timing
- System Footprint: CPU %, Process RSS RAM
- Cold-start vs Warm-start performance
- Semantic reordering cases
- Generates:
  - docs/phase-4/benchmark_results.json
  - docs/phase-4/reranker-benchmark.md
"""

import json
import math
import os
import platform
import psutil
import statistics
import sys
import tempfile
import time
from typing import Any, Dict, List, Tuple

# Ensure backend root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.config import DEFAULT_RERANK_MODEL_NAME
from app.db.connection import DatabaseManager
from app.retrieval.embeddings import DEFAULT_MODEL_NAME as DEFAULT_EMBEDDING_MODEL_NAME, EmbeddingEngine
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.reranker import Reranker
from app.retrieval.vector_store import SqliteVecStore
from tests.fixtures.benchmark_corpus import setup_benchmark_corpus



def compute_ndcg_at_k(retrieved_chunk_ids: list, graded_rel_map: dict, k: int = 10) -> float:
    if not graded_rel_map:
        return 0.0
    dcg = 0.0
    for rank, cid in enumerate(retrieved_chunk_ids[:k], start=1):
        rel = graded_rel_map.get(cid, 0)
        gain = (2.0 ** rel) - 1.0
        discount = math.log2(rank + 1.0)
        dcg += gain / discount

    ideal_rels = sorted(list(graded_rel_map.values()), reverse=True)[:k]
    idcg = 0.0
    for rank, rel in enumerate(ideal_rels, start=1):
        gain = (2.0 ** rel) - 1.0
        discount = math.log2(rank + 1.0)
        idcg += gain / discount

    return round(dcg / idcg, 4) if idcg > 0.0 else 0.0


def compute_mrr(retrieved_chunk_ids: list, expected_chunk_ids: set) -> float:
    for rank, cid in enumerate(retrieved_chunk_ids, start=1):
        if cid in expected_chunk_ids:
            return round(1.0 / rank, 4)
    return 0.0


def compute_recall_at_k(retrieved_chunk_ids: list, expected_chunk_ids: set, k: int) -> float:
    if not expected_chunk_ids:
        return 1.0
    top_k_retrieved = set(retrieved_chunk_ids[:k])
    matched = top_k_retrieved.intersection(expected_chunk_ids)
    return round(len(matched) / len(expected_chunk_ids), 4)


def run_phase4_benchmark(num_warm_runs: int = 5) -> Dict[str, Any]:
    print("=" * 80)
    print("PHASE 4 BENCHMARK: FAST / QUALITY RETRIEVAL AND RERANKER EVALUATION")
    print("=" * 80)

    process = psutil.Process(os.getpid())
    ram_before_mb = process.memory_info().rss / (1024 * 1024)

    # 1. Setup isolated test corpus and database
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "filemind_bench_p4.db")
    print(f"Ingesting benchmark corpus in temporary vault: {temp_dir}")
    meta = setup_benchmark_corpus(temp_dir, db_path)
    db = DatabaseManager(db_path)

    embedding_engine = EmbeddingEngine(DEFAULT_EMBEDDING_MODEL_NAME)
    reranker = Reranker(DEFAULT_RERANK_MODEL_NAME)

    # Ingest dense vectors
    texts = [c["content"] for c in meta["chunks"]]
    vectors = embedding_engine.embed_texts(texts, batch_size=16)
    with db.session() as conn:
        vec_store = SqliteVecStore(conn, dimension=embedding_engine.dimension)
        records = [
            {"chunk_id": c["chunk_id"], "file_id": c["file_id"], "embedding": v}
            for c, v in zip(meta["chunks"], vectors)
        ]
        vec_store.upsert_vectors(records)

    # 2. Load dataset
    dataset_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "docs", "phase-4", "evaluation_dataset_v1.json")
    )
    with open(dataset_path, "r", encoding="utf-8") as f:
        eval_data = json.load(f)

    queries = eval_data["queries"]
    active_queries = [q for q in queries if q["category"] != "negative"]

    configurations = [
        {"name": "BM25 Fast", "mode": "bm25", "quality": "fast"},
        {"name": "Dense Fast", "mode": "dense", "quality": "fast"},
        {"name": "Hybrid Fast (RRF)", "mode": "hybrid", "quality": "fast"},
        {"name": "Hybrid Quality (RRF + bge-reranker-base)", "mode": "hybrid", "quality": "quality"},
    ]

    benchmark_results: Dict[str, Any] = {
        "metadata": {
            "benchmark_version": "phase4-bench-v1.0",
            "dataset_version": eval_data.get("dataset_version", "phase4-eval-v1.0"),
            "corpus_version": eval_data.get("corpus_version", "phase3-benchmark-corpus-v1"),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "python_version": sys.version,
            "os": platform.platform(),
            "cpu_count": os.cpu_count(),
            "embedding_model": DEFAULT_EMBEDDING_MODEL_NAME,
            "reranker_model": DEFAULT_RERANK_MODEL_NAME,
            "num_warm_runs": num_warm_runs,
            "total_queries": len(queries),
            "active_queries_count": len(active_queries),
        },
        "configurations": {},
        "semantic_reorder_examples": [],
    }

    with db.session() as conn:
        vec_store = SqliteVecStore(conn, dimension=embedding_engine.dimension)
        retriever = HybridRetriever(
            db_conn=conn,
            embedding_engine=embedding_engine,
            vector_store=vec_store,
            reranker=reranker,
            rrf_k=60,
            candidate_pool_size=50,
            rerank_candidate_pool_size=25,
        )

        for cfg in configurations:
            cfg_name = cfg["name"]
            mode = cfg["mode"]
            quality = cfg["quality"]
            print(f"\n>>> Running Configuration: {cfg_name} (Mode: {mode}, Quality: {quality})")

            all_r1, all_r3, all_r5, all_r10 = [], [], [], []
            all_mrr, all_ndcg = [], []
            all_total_latencies = []
            stage_latencies = {
                "normalization": [],
                "lexical_search": [],
                "query_embedding": [],
                "dense_search": [],
                "rrf_fusion": [],
                "reranker_inference": [],
                "total_request": [],
            }
            query_level_results = []
            cold_latency = 0.0

            for q_idx, q in enumerate(active_queries):
                qid = q["query_id"]
                qtext = q["query_text"]
                expected_cids = set(q.get("expected_chunk_ids", []))
                graded_rel = q.get("graded_relevance", {})

                # Warm runs
                runs_data = []
                for r_idx in range(num_warm_runs):
                    res = retriever.search(
                        query=qtext,
                        top_k=10,
                        mode=mode,
                        quality=quality,
                    )
                    runs_data.append(res)
                    if q_idx == 0 and r_idx == 0:
                        cold_latency = res["latency_breakdown_ms"]["total_request"]

                final_run = runs_data[-1]
                retrieved_cids = [item["chunk_id"] for item in final_run["results"]]

                r1 = compute_recall_at_k(retrieved_cids, expected_cids, 1)
                r3 = compute_recall_at_k(retrieved_cids, expected_cids, 3)
                r5 = compute_recall_at_k(retrieved_cids, expected_cids, 5)
                r10 = compute_recall_at_k(retrieved_cids, expected_cids, 10)
                mrr = compute_mrr(retrieved_cids, expected_cids)
                ndcg = compute_ndcg_at_k(retrieved_cids, graded_rel, 10)

                all_r1.append(r1)
                all_r3.append(r3)
                all_r5.append(r5)
                all_r10.append(r10)
                all_mrr.append(mrr)
                all_ndcg.append(ndcg)

                # Collect latencies across runs
                for r_data in runs_data:
                    lat = r_data["latency_breakdown_ms"]
                    all_total_latencies.append(lat["total_request"])
                    for k in stage_latencies.keys():
                        if k in lat and lat[k] is not None:
                            stage_latencies[k].append(lat[k])

                query_level_results.append({
                    "query_id": qid,
                    "query_text": qtext,
                    "category": q["category"],
                    "recall_at_1": r1,
                    "recall_at_3": r3,
                    "recall_at_5": r5,
                    "recall_at_10": r10,
                    "mrr": mrr,
                    "ndcg_at_10": ndcg,
                    "retrieved_top3": [
                        {
                            "chunk_id": item["chunk_id"],
                            "score": item["score"],
                            "source_file": item["source_file"],
                            "reranker_score": item.get("reranker_score"),
                            "rrf_score": item.get("rrf_score"),
                        }
                        for item in final_run["results"][:3]
                    ],
                })

            # Aggregate stats
            sorted_lat = sorted(all_total_latencies)
            p50 = statistics.median(sorted_lat)
            p95 = sorted_lat[int(len(sorted_lat) * 0.95)]
            mean_lat = statistics.mean(sorted_lat)
            mean_rerank_lat = (
                statistics.mean(stage_latencies["reranker_inference"])
                if stage_latencies["reranker_inference"]
                else 0.0
            )

            benchmark_results["configurations"][cfg_name] = {
                "mode": mode,
                "quality": quality,
                "metrics": {
                    "recall_at_1": round(statistics.mean(all_r1), 4),
                    "recall_at_3": round(statistics.mean(all_r3), 4),
                    "recall_at_5": round(statistics.mean(all_r5), 4),
                    "recall_at_10": round(statistics.mean(all_r10), 4),
                    "mrr": round(statistics.mean(all_mrr), 4),
                    "ndcg_at_10": round(statistics.mean(all_ndcg), 4),
                },
                "latency_ms": {
                    "cold_start_ms": round(cold_latency, 2),
                    "p50_ms": round(p50, 2),
                    "p95_ms": round(p95, 2),
                    "mean_ms": round(mean_lat, 2),
                    "min_ms": round(min(sorted_lat), 2),
                    "max_ms": round(max(sorted_lat), 2),
                    "mean_reranker_inference_ms": round(mean_rerank_lat, 2),
                },
                "stage_breakdown_ms": {
                    k: round(statistics.mean(v), 2) for k, v in stage_latencies.items() if v
                },
                "queries": query_level_results,
            }

    ram_after_mb = process.memory_info().rss / (1024 * 1024)
    benchmark_results["metadata"]["memory_rss_mb"] = round(ram_after_mb, 2)
    benchmark_results["metadata"]["ram_delta_mb"] = round(ram_after_mb - ram_before_mb, 2)

    # 3. Analyze semantic reordering differences between Hybrid Fast and Hybrid Quality
    fast_queries = {
        q["query_id"]: q for q in benchmark_results["configurations"]["Hybrid Fast (RRF)"]["queries"]
    }
    quality_queries = {
        q["query_id"]: q
        for q in benchmark_results["configurations"]["Hybrid Quality (RRF + bge-reranker-base)"]["queries"]
    }

    reorders = []
    for qid, fq in fast_queries.items():
        qq = quality_queries.get(qid)
        if not qq:
            continue
        f_top = [x["chunk_id"] for x in fq["retrieved_top3"]]
        q_top = [x["chunk_id"] for x in qq["retrieved_top3"]]
        if f_top != q_top:
            reorders.append({
                "query_id": qid,
                "query_text": fq["query_text"],
                "category": fq["category"],
                "fast_top1": fq["retrieved_top3"][0] if fq["retrieved_top3"] else None,
                "quality_top1": qq["retrieved_top3"][0] if qq["retrieved_top3"] else None,
                "fast_ndcg": fq["ndcg_at_10"],
                "quality_ndcg": qq["ndcg_at_10"],
                "ndcg_delta": round(qq["ndcg_at_10"] - fq["ndcg_at_10"], 4),
            })

    benchmark_results["semantic_reorder_examples"] = reorders

    # 4. Save JSON and Markdown artifacts
    out_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "docs", "phase-4"))
    os.makedirs(out_dir, exist_ok=True)

    json_path = os.path.join(out_dir, "benchmark_results.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(benchmark_results, f, indent=2)
    print(f"\n[PASS] Machine-readable benchmark results saved to: {json_path}")

    # Generate Markdown Report
    md_path = os.path.join(out_dir, "reranker-benchmark.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# Phase 4 Fast vs Quality Retrieval Benchmark Report\n\n")
        f.write("## Execution Environment\n")
        f.write(f"- **Dataset Version**: {benchmark_results['metadata']['dataset_version']}\n")
        f.write(f"- **Corpus Version**: {benchmark_results['metadata']['corpus_version']}\n")
        f.write(f"- **Embedding Model**: `{benchmark_results['metadata']['embedding_model']}`\n")
        f.write(f"- **Reranker Model**: `{benchmark_results['metadata']['reranker_model']}`\n")
        f.write(f"- **OS / Platform**: {benchmark_results['metadata']['os']}\n")
        f.write(f"- **Python**: {benchmark_results['metadata']['python_version'].split()[0]}\n")
        f.write(f"- **RAM Footprint**: {benchmark_results['metadata']['memory_rss_mb']} MB (Delta: +{benchmark_results['metadata']['ram_delta_mb']} MB)\n\n")

        f.write("## Retrieval Quality and Latency Summary Table\n\n")
        f.write("| Configuration | Recall@1 | Recall@5 | Recall@10 | MRR | NDCG@10 | p50 Latency | p95 Latency | Mean Latency | Rerank Latency |\n")
        f.write("|---|---|---|---|---|---|---|---|---|---|\n")
        for cname, cdata in benchmark_results["configurations"].items():
            m = cdata["metrics"]
            l = cdata["latency_ms"]
            f.write(
                f"| **{cname}** | {m['recall_at_1']:.4f} | {m['recall_at_5']:.4f} | {m['recall_at_10']:.4f} | "
                f"{m['mrr']:.4f} | {m['ndcg_at_10']:.4f} | {l['p50_ms']:.2f} ms | {l['p95_ms']:.2f} ms | "
                f"{l['mean_ms']:.2f} ms | {l['mean_reranker_inference_ms']:.2f} ms |\n"
            )

        f.write("\n## Semantic Reordering Analysis\n\n")
        f.write(f"Reranking produced reordered top-3 candidates across **{len(reorders)}** queries:\n\n")
        for ro in reorders:
            f.write(f"### `{ro['query_id']}`: \"{ro['query_text']}\"\n")
            f.write(f"- **Category**: {ro['category']}\n")
            f.write(f"- **Fast Top-1 (RRF)**: `{ro['fast_top1']['source_file']}` (RRF Score: {ro['fast_top1']['score']})\n")
            f.write(f"- **Quality Top-1 (Cross-Encoder)**: `{ro['quality_top1']['source_file']}` (Rerank Score: {ro['quality_top1']['reranker_score']})\n")
            f.write(f"- **NDCG@10**: Fast = {ro['fast_ndcg']:.4f} -> Quality = {ro['quality_ndcg']:.4f} (Delta: {ro['ndcg_delta']:+.4f})\n\n")

    print(f"[PASS] Human-readable markdown report saved to: {md_path}")
    return benchmark_results


if __name__ == "__main__":
    run_phase4_benchmark(num_warm_runs=5)
