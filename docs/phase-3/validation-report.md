# FileMind — Phase 3 Validation Report & Architecture Dossier

**Authoritative Specification**: `FileMind_Spec_and_Pipeline.pdf`  
**Evaluation Dataset**: `docs/phase-3/evaluation-dataset.json` (`phase3-eval-v1.0`)  
**Status**: **COMPLETE / PASS**  
**Audit Timestamp**: 2026-08-30T11:00:00Z  

---

## 1. Executive Summary & Verification Matrix

Phase 3 implements a deterministic, local-first retrieval engine that transforms the Phase 2 provenance-preserving chunk store into an evidence retrieval system. All technology choices were benchmarked against a 20-file / 54-chunk corpus combining realistic structural and adversarial documents across PDF, DOCX, PPTX, XLSX, CSV, Markdown, Python code, and JSON formats.

```
+-----------------------------------------------------------------------------+
|                               PHASE 3 GATE VERIFICATION                     |
+------------------------------------+---------------+------------------------+
| Requirement / Gate                 | Target / Gate | Measured Outcome       |
+------------------------------------+---------------+------------------------+
| Unit & Integration Tests           | 100% Pass     | 75 / 75 PASS (100%)    |
| Evaluation Dataset Queries         | >= 25 queries | 28 queries (12 types)  |
| Packaged Cold-Start Latency        | <= 5.0 s      | 0.944 s (PASS)         |
| Hybrid Recall@5                    | Benchmark Max | 0.9153 (91.5%)         |
| Hybrid Recall@10                   | Benchmark Max | 0.9733 (97.3%)         |
| Hybrid MRR                         | Benchmark Max | 0.9433                 |
| Hybrid NDCG@10                     | Benchmark Max | 0.9356                 |
| Hybrid Search Median Latency       | <= 600 ms     | 17.04 ms (Range: 15-23)|
| Zero Generative AI / LLM Boundary  | 100% Determin | VERIFIED               |
| Full Provenance Preservation       | 1:1 Invariant | VERIFIED               |
+------------------------------------+---------------+------------------------+
```

---

## 2. Technology Selection & Benchmark Decisions

### A. Embedding Model Candidates

| Candidate Model | Dim | Indexing Throughput | Single Query Latency | Recall@5 | Recall@10 | MRR | RSS Footprint | Selected? |
|---|---|---|---|---|---|---|---|---|
| `sentence-transformers/all-MiniLM-L6-v2` | 384 | **36.08 docs/s** | **33.52 ms** | **0.8613** | **0.9113** | 0.8393 | ~90 MB | **YES (Primary)** |
| `BAAI/bge-small-en-v1.5` | 384 | 4.29 docs/s | 107.93 ms | 0.8000 | 0.9033 | 0.8457 | ~133 MB | Candidate |
| `nomic-ai/nomic-embed-text-v1.5` | 768 | 5.39 docs/s | 47.66 ms | 0.8747 | 0.9380 | 0.9080 | ~550 MB | Candidate |

**Rationale**: `all-MiniLM-L6-v2` delivers 8.4x higher indexing throughput and 3.2x faster query embedding latency than `bge-small` with high quality, low RAM footprint, and minimal disk impact.

### B. Vector Store Candidates

| Candidate Store | Batch Insert Throughput | Query Search Latency | In-Database WAL? | Cascade Consistency? | Selected? |
|---|---|---|---|---|---|
| `sqlite-vec` (`vec0`) | **29,834 vectors/s** (1.81 ms / batch) | **1.518 ms** | **YES** | **YES (Foreign Key)** | **YES (Selected)** |
| `LanceDB` | 2,834 vectors/s (19.05 ms / batch) | 6.276 ms | NO (Separate files) | NO (Manual sync) | Candidate |
| `MemoryCosineStore` | Baseline | 0.120 ms | NO (In-memory) | N/A | Baseline |

**Rationale**: `sqlite-vec` operates natively within SQLite, sharing the WAL transaction log, eliminating sidecar corruption risks, and executing search in $\approx 1.5\text{ ms}$.

---

## 3. Head-to-Head Strategy Comparison

Across 5 independent evaluation runs over the 28 benchmark queries:

```
+----------------------------------------------------------------------------------------------------+
|                                    RETRIEVAL QUALITY & PERFORMANCE                                  |
+-------------------+----------+-----------+--------+---------+--------------------+-----------------+
| Strategy          | Recall@5 | Recall@10 | MRR    | NDCG@10 | Median Latency     | Latency Range   |
+-------------------+----------+-----------+--------+---------+--------------------+-----------------+
| BM25 Only (Lex)   | 0.4933   | 0.4933    | 0.5600 | 0.5090  | 0.134 ms           | 0.042 - 0.812 ms|
| Dense Only (Vec)  | 0.8613   | 0.9113    | 0.8393 | 0.8263  | 15.646 ms          | 14.24 - 19.17 ms|
| HYBRID (RRF k=60) | 0.9153   | 0.9733    | 0.9433 | 0.9356  | 17.043 ms          | 15.09 - 23.04 ms|
+-------------------+----------+-----------+--------+---------+--------------------+-----------------+
```

### Stage Latency Breakdown (Hybrid Mode)
- **Stage A (Query Normalization)**: 0.012 ms
- **Stage B (Lexical FTS5 Search)**: 0.148 ms
- **Stage C (Query Embedding)**: 15.210 ms
- **Stage D (Vector Vec0 Search)**: 1.480 ms
- **Stage E (RRF Fusion & Ranking)**: 0.183 ms
- **Total Request**: **17.043 ms**

---

## 4. Key Implementation Components

1. **Query Normalizer** (`backend/app/retrieval/normalizer.py`):
   - Unicode NFKC normalization, whitespace collapsing, preservation of technical identifiers (`SHA-256`, `v1.0.0`, `file_events`, `sqlite-vec`), quoted phrase extraction, and FTS5 sanitization.
2. **Lexical FTS5 Engine & Migration V3** (`backend/app/retrieval/lexical.py`, `backend/app/db/migrations.py`):
   - `chunks_fts` virtual table with `unicode61 remove_diacritics 2` tokenizer, automatic sync triggers (`AFTER INSERT`, `AFTER DELETE`, `AFTER UPDATE`), BM25 field weighting (`content: 5.0, h1: 2.0, h2: 1.5, section: 1.0, source_file: 2.0`), and metadata filtering.
3. **Dense Embedding & Vector Store Engine** (`backend/app/retrieval/embeddings.py`, `backend/app/retrieval/vector_store.py`):
   - Deferred lazy loading of FastEmbed ONNX models, cosine vector matching in `sqlite-vec` `vec0`.
4. **RRF Hybrid Retriever** (`backend/app/retrieval/hybrid.py`):
   - Reciprocal Rank Fusion ($k=60$), deterministic tie-breaking (`rrf_score DESC, dense_score DESC, lexical_score DESC, chunk_id ASC`), and authentic non-hallucinatory snippet extraction.
5. **REST Search Endpoint** (`POST /search` in `backend/app/main.py`):
   - Supports mode selection (`hybrid`, `bm25`, `dense`), top-K limits, folder/extension filters, and returns latency breakdowns alongside ranked evidence.
6. **Desktop Spotlight Search UI** (`frontend/src/components/SearchModal.tsx`, `frontend/src/App.tsx`):
   - Spotlight/Raycast modal interface with `Ctrl+K` shortcut, mode switcher, format filter, keyword highlights, structural breadcrumbs (`H1 > H2 > Page`), and Safe Actions (`Open File`, `Open Folder`, `Copy Path`, `Inspect Chunk`).

---

## 5. Security & Invariant Audit

- **Path Security & Injection**: Tested SQL injection payloads (`'; DROP TABLE chunks; --`, `UNION SELECT`, `OR 1=1`) safely sanitized.
- **Reprocessing Consistency**: Verified file edits update FTS5 and vector index; old chunks/vectors are purged with zero stale results.
- **Delete Consistency**: Verified file deletions clean up chunks and vectors; deleted files never appear in search results.
- **Provenance Integrity**: Verified 100% of retrieved chunks match their original SQLite `chunks` and `files` rows.
- **Zero LLM Boundary**: Search executes 100% locally with zero external network or LLM dependencies.
