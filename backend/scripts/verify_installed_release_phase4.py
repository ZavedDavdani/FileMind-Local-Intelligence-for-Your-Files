import json
import urllib.request
import urllib.parse
from typing import Any, Dict

BASE_URL = "http://127.0.0.1:24823"

def send_search(query: str, mode: str = "hybrid", top_k: int = 5, filters: dict = None) -> Dict[str, Any]:
    payload = {
        "query": query,
        "mode": mode,
        "top_k": top_k,
        "filters": filters or {},
    }
    req = urllib.request.Request(
        f"{BASE_URL}/search",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))

def main():
    print("=" * 60)
    print("1. VERIFYING SEARCH MODES & SCORE CONTRACTS")
    print("=" * 60)

    # 1. BM25 Mode
    bm25_resp = send_search("sample", mode="bm25")
    print(f"BM25 Search: found={bm25_resp['total_found']}, method={bm25_resp.get('retrieval_method')}")
    assert bm25_resp["mode"] == "bm25"
    if bm25_resp["results"]:
        top1 = bm25_resp["results"][0]
        assert top1["reranker_score"] is None, f"Expected reranker_score=None in BM25 mode, got {top1['reranker_score']}"
        assert top1["dense_score"] is None, f"Expected dense_score=None in BM25 mode, got {top1['dense_score']}"
        assert top1["lexical_score"] is not None, f"Expected lexical_score populated in BM25 mode"
        print(f"  [PASS] BM25 mode: reranker_score={top1['reranker_score']}, dense_score={top1['dense_score']}, lexical_score={top1['lexical_score']}")

    # 2. Dense Mode
    dense_resp = send_search("sample", mode="dense")
    print(f"Dense Search: found={dense_resp['total_found']}, method={dense_resp.get('retrieval_method')}")
    assert dense_resp["mode"] == "dense"
    if dense_resp["results"]:
        top1 = dense_resp["results"][0]
        assert top1["reranker_score"] is None, f"Expected reranker_score=None in Dense mode, got {top1['reranker_score']}"
        assert top1["lexical_score"] is None, f"Expected lexical_score=None in Dense mode, got {top1['lexical_score']}"
        assert top1["dense_score"] is not None, f"Expected dense_score populated in Dense mode"
        print(f"  [PASS] Dense mode: reranker_score={top1['reranker_score']}, lexical_score={top1['lexical_score']}, dense_score={top1['dense_score']}")

    # 3. Hybrid Mode
    hybrid_resp = send_search("sample", mode="hybrid")
    print(f"Hybrid Search: found={hybrid_resp['total_found']}, method={hybrid_resp.get('retrieval_method')}")
    assert hybrid_resp["mode"] == "hybrid"
    if hybrid_resp["results"]:
        top1 = hybrid_resp["results"][0]
        assert top1["reranker_score"] is not None, f"Expected reranker_score populated in Hybrid mode, got {top1['reranker_score']}"
        assert top1["rrf_score"] is not None, f"Expected rrf_score populated in Hybrid mode"
        assert top1["source_file"] is not None, f"Expected source_file preserved"
        assert top1["source_path"] is not None, f"Expected source_path preserved"
        print(f"  [PASS] Hybrid mode: reranker_score={top1['reranker_score']:.4f}, rrf_score={top1['rrf_score']:.4f}, source_file={top1['source_file']}")
    print(f"  Latencies breakdown: {hybrid_resp['latency_breakdown_ms']}")

    print("\n" + "=" * 60)
    print("2. PRACTICAL SEARCH QUERIES (C:\\FileMind-Practical-Test)")
    print("=" * 60)

    queries = [
        ("sample", "sample.txt"),
        ("sample.txt", "sample.txt"),
        ("test", "test.txt"),
        ("notes", "notes.md"),
        ("practical", "test.txt"),
        ("verification", None),  # Semantic result
        ("practical verification", "test.txt"),
        ("FILEMIND_PRACTICAL_ALPHA", "sample.txt"),
        ("FILEMIND_PRACTICAL_ALPHA_7319", "sample.txt"),
        ("filemind practical", "test.txt"),
    ]

    all_passed = True
    for q, expected_file in queries:
        resp = send_search(q, mode="hybrid")
        results = resp.get("results", [])
        if not results:
            print(f"Query '{q}': NO RESULTS")
            all_passed = False
            continue
        top1 = results[0]
        top_file = top1["source_file"]
        is_match = (expected_file is None) or (top_file.lower() == expected_file.lower())
        status = "PASS" if is_match else "FAIL"
        if not is_match:
            all_passed = False
        print(f"[{status}] Query '{q}' -> Top-1: {top_file} (rerank_score={top1['reranker_score']:.4f}, rrf={top1['rrf_score']:.4f})")

    print("\n" + "=" * 60)
    print("3. SEMANTIC QUERIES: RRF TOP-1 VS RERANKED TOP-1")
    print("=" * 60)

    semantic_queries = [
        "How does FileMind find information from documents stored on the local computer?",
        "local document storage and multi-file indexing",
        "verification and testing workflows",
    ]

    for sq in semantic_queries:
        resp = send_search(sq, mode="hybrid", top_k=5)
        results = resp.get("results", [])
        if results:
            # Sorted by RRF
            rrf_sorted = sorted(results, key=lambda r: r.get("rrf_score") or 0.0, reverse=True)
            rrf_top1 = rrf_sorted[0]["source_file"]
            reranked_top1 = results[0]["source_file"]
            reordered = (rrf_top1 != reranked_top1)
            print(f"Query: \"{sq}\"")
            print(f"  RRF Top-1:       {rrf_top1} (score={rrf_sorted[0]['rrf_score']:.4f})")
            print(f"  Reranked Top-1:  {reranked_top1} (score={results[0]['reranker_score']:.4f})")
            print(f"  Reordered:       {'YES' if reordered else 'NO'}")
            print(f"  Reranker Latency: {resp['latency_breakdown_ms']['reranker_inference']} ms")
            print(f"  Total Latency:    {resp['latency_breakdown_ms']['total_request']} ms")
            print("-" * 50)

    print(f"\nPractical Tests Result: {'ALL PASSED' if all_passed else 'SOME FAILED'}")

if __name__ == '__main__':
    main()
