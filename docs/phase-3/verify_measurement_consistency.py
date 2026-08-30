"""Programmatic measurement consistency verifier for Phase 3."""

import json
import os
import sys


def verify_phase3_consistency():
    json_path = os.path.join(os.path.dirname(__file__), "measurements.json")
    bench_json_path = os.path.join(os.path.dirname(__file__), "retrieval-benchmark.json")
    md_path = os.path.join(os.path.dirname(__file__), "validation-report.md")

    for p in [json_path, bench_json_path, md_path]:
        if not os.path.exists(p):
            print(f"ERROR: {p} not found.")
            sys.exit(1)

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    with open(bench_json_path, "r", encoding="utf-8") as f:
        bench_data = json.load(f)

    with open(md_path, "r", encoding="utf-8") as f:
        md_text = f.read()

    modes = data["modes_comparison"]
    emb = bench_data["embedding_models"]["sentence-transformers/all-MiniLM-L6-v2"]

    checks = [
        ("BM25 Recall@5", f"{modes['bm25']['recall_at_5']:.4f}"),
        ("BM25 MRR", f"{modes['bm25']['mrr']:.4f}"),
        ("Dense Recall@5", f"{modes['dense']['recall_at_5']:.4f}"),
        ("Dense MRR", f"{modes['dense']['mrr']:.4f}"),
        ("Hybrid Recall@5", f"{modes['hybrid']['recall_at_5']:.4f}"),
        ("Hybrid Recall@10", f"{modes['hybrid']['recall_at_10']:.4f}"),
        ("Hybrid MRR", f"{modes['hybrid']['mrr']:.4f}"),
        ("Hybrid NDCG@10", f"{modes['hybrid']['ndcg_at_10']:.4f}"),
        ("MiniLM Load Delta RSS", f"{emb['model_load_rss_delta_mb']:.2f}"),
        ("MiniLM Absolute Process RSS", f"{emb['absolute_process_rss_mb']:.2f}"),
        ("MiniLM Historical Invalid RSS", f"{emb['historical_invalid_measurement_mb']:.2f}"),
    ]

    mismatches = 0
    print("Verifying Phase 3 Measurement Consistency:")
    for label, val in checks:
        if val in md_text:
            print(f"  [MATCH] {label}: {val}")
        else:
            print(f"  [MISMATCH] {label}: '{val}' not found in validation-report.md")
            mismatches += 1

    if mismatches > 0:
        print(f"\nFAILURE: {mismatches} measurement mismatches found.")
        sys.exit(1)
    else:
        print(f"\nSUCCESS: All {len(checks)} Phase 3 measurements consistently verified!")


if __name__ == "__main__":
    verify_phase3_consistency()
