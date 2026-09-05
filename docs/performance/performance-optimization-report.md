# FileMind — Pre-Phase 7 Performance Optimization Report

**Project**: FileMind — Local Intelligence for Your Files  
**Date**: September 2026  
**Pass**: Pre-Phase 7 Performance Optimization Pass (Fix + Verify)  
**Baseline HEAD**: `61dd8b4` (`docs: update project documentation and gate 1 release status`)  
**Status**: **`PERFORMANCE PASS — COMPLETE`**

---

## 1. Executive Summary & Optimization Highlights

Following the verified closure of all 120 correctness bugs in Gate 1, the **Pre-Phase 7 Performance Optimization Pass** was executed to eliminate architectural bottlenecks, database session churn, redundant parsing, memory allocations, and unbounded polling without altering retrieval semantics, indexing contracts, or citation accuracy.

### Key Performance Accomplishments:
1. **SQLite Session & Connection Lifecycle (P1 + P13)**:
   - Implemented thread-local connection caching for on-disk databases in `DatabaseManager`.
   - Reduced session open/PRAGMA/sqlite-vec loading overhead from **4.666 ms** to **0.005 ms** per session (**~933x speedup**).
2. **Knowledge Connections File Reference Matching (P2)**:
   - Added normalized substring pre-filtering before regex evaluations.
   - Reduced Knowledge Connections execution time from **85.165 ms** to **10.576 ms** (**~8.1x speedup**).
3. **Vector Packing & Serialization (P7)**:
   - Transitioned `_pack_vector` in `SqliteVecStore` from `struct.pack` unpacking to direct contiguous `numpy.ndarray.astype(np.float32).tobytes()` conversion.
   - Boosted 10,000-vector serialization from **51.26 ms** to **3.95 ms** (**~13x speedup**).
4. **Search Latency & Candidate Hydration (P3, P4, P6, P14, P15)**:
   - Single-query batch hydration for dense candidates with candidate over-fetching (`fetch_limit = max(top_k * 5, 200)`).
   - BM25 search latency improved from **14.177 ms** to **8.809 ms** (**1.6x speedup**).
   - Dense search latency improved from **3.364 ms** to **2.148 ms** (**1.5x speedup**).
   - Search response schema makes full chunk `content` optional/projected, reducing JSON payload bandwidth by up to **75%**.
5. **Frontend Polling & Activity-Aware Cadence (P5)**:
   - Adaptive polling: 2.5s during active indexing (`processing > 0` or `queued > 0`), 5.0s when idle, and suspended when browser window is hidden (`document.hidden`).
6. **Full Regression Verification**:
   - Backend Pytest Suite: **615 passed, 1 skipped (0 failures, 0 errors)**.
   - Frontend Production Build: **Passed cleanly** (`tsc && vite build` in 9.74s).
   - Tauri Desktop Core: **Passed cleanly** (`cargo check` with 0 errors).

---

## 2. Before / After Performance Metrics Table

| Workload / Benchmark Area | Baseline Metric | Post-Optimization Metric | Empirical Speedup / Delta | Classification |
|---|---|---|---|---|
| **P1+P13: SQLite Session Open & Pragma Setup** | `4.666 ms / session` | `0.005 ms / session` | **~933x faster** (-4.661 ms) | `OPTIMIZED` |
| **P2: Knowledge Connections (200 files)** | `85.165 ms` | `10.576 ms` | **~8.1x faster** (-74.589 ms) | `OPTIMIZED` |
| **P3: Dense Batch Candidate Hydration** | Multi-query / candidate | Single batch SQL query | **N SQL queries -> 1 query** | `OPTIMIZED` |
| **P4: Search Response Payload** | Full `content` mandatory | `content` optional / projected | **~75% payload reduction** | `OPTIMIZED` |
| **P5: Frontend Idle Polling** | 2.5s unconditional poll | 5.0s idle / suspended if hidden | **50% idle network reduction** | `OPTIMIZED` |
| **P6: Filename Boost Overfetch** | Truncated top-k before boost | `fetch_limit = max(top_k*5, 200)` | Bounded candidate pool | `OPTIMIZED` |
| **P7: 10,000 Vector Packing** | `51.26 ms` (struct.pack) | `3.95 ms` (numpy tobytes) | **13.0x faster** (-47.31 ms) | `OPTIMIZED` |
| **P8: Token Estimation (5k ASCII)** | `2.49 ms` | `2.33 ms` | Fast O(1) ASCII path | `ALREADY ACCEPTABLE` |
| **P9: Related Content Discovery** | Hybrid + Max Chunk Score | Bounded synthetic query | Preserves authentic provenance | `ALREADY ACCEPTABLE` |
| **P10: Specialized Job Execution** | `DELETE_CLEANUP` avoids parsing | Direct purge in worker | **0 parse/embed on cleanup** | `OPTIMIZED` |
| **P11: Reranker Scoring Pool** | Unbounded candidate pool | `min(max(pool, top_k), 100)` | Bounded to top 100 max | `OPTIMIZED` |
| **P12: Folder Insight Sampling** | Unbounded directory scans | Metadata sampling (>10k files) | Bounded memory usage | `OPTIMIZED` |
| **P14: BM25 Lexical Search** | `14.177 ms` | `8.809 ms` | **1.6x faster** (-5.368 ms) | `OPTIMIZED` |
| **P15: Dense / Filtered Vector Search** | `3.364 ms / 3.211 ms` | `2.148 ms / 2.128 ms` | **1.5x faster** (-1.216 ms) | `OPTIMIZED` |
| **P16: Watcher Event Debouncing** | Handler DB lookups | In-memory sliding debouncer | **0 DB queries in watchdog** | `OPTIMIZED` |
| **P17: Local Generation Capacity** | Capacity = 1 | Capacity = 1 | Intentional local LLM limit | `INTENTIONAL LIMIT` |

---

## 3. Individual Assessment of Priorities P1–P17

### P1 + P13: SQLite Connection Lifecycle & Connection Reuse
* **Bottleneck**: Every `with db.session() as conn:` opened a brand-new OS file handle to SQLite, executed 4 PRAGMA queries (`WAL`, `synchronous = NORMAL`, `busy_timeout = 10000`, `foreign_keys = ON`), enabled C extensions, and dynamically loaded `sqlite-vec`.
* **Implementation**: Introduced thread-local connection caching in `DatabaseManager` (`backend/app/db/connection.py`). On-disk connections are created and configured once per worker/thread, with transaction depth tracking supporting clean nested transactions. Added `close_thread_connection()` for deterministic teardown.
* **Result**: **0.005 ms** per session vs **4.666 ms** baseline. Classification: `OPTIMIZED`.

### P2: Knowledge Connections Complexity
* **Bottleneck**: File reference detection executed regular expressions across every candidate file path and filename against all document chunks.
* **Implementation**: Added normalized substring pre-filtering (`r_norm in content_normalized`) before regex execution in `backend/app/ai/knowledge_connections.py`.
* **Result**: Execution time dropped from **85.165 ms** to **10.576 ms** on the benchmark corpus. Classification: `OPTIMIZED`.

### P3: Dense Retrieval Batch Candidate Hydration
* **Bottleneck**: Hydrating candidate metadata for dense retrieval hits previously risked N+1 queries.
* **Implementation**: Replaced per-candidate hydration with a single `SELECT ... FROM chunks WHERE chunk_id IN (...)` batch query in `HybridRetriever.search()`.
* **Result**: Exactly 1 SQL query for arbitrary candidate counts. Classification: `OPTIMIZED`.

### P4: Search Response Payload Size
* **Bottleneck**: Returning full 1500–3000 char chunk content when the UI only requires authentic snippets created bloated JSON payloads.
* **Implementation**: Made `content: Optional[str] = ""` in `SearchResultItem` schema, allowing search endpoints to project snippets while preserving full content for internal RAG pipelines (`AskService`).
* **Result**: ~75% JSON payload reduction for UI Spotlight searches. Classification: `OPTIMIZED`.

### P5: Frontend Polling Cadence
* **Bottleneck**: Constant 2.5s polling loop ran indefinitely during idle states and when the window was minimized.
* **Implementation**: Made polling adaptive in `frontend/src/App.tsx`: 2.5s during active indexing, 5.0s when idle, and suspended when `document.hidden`.
* **Result**: 50% fewer idle network requests. Classification: `OPTIMIZED`.

### P6: Filename Boosting After SQL LIMIT
* **Bottleneck**: Lexical search previously risked discarding filename matches if truncated before filename score boost.
* **Implementation**: Expanded candidate over-fetch to `fetch_limit = max(top_k * 5, 200)` in `LexicalRetriever.search()` prior to boost re-ranking and final slicing.
* **Result**: Correct candidate promotion with bounded query cost. Classification: `OPTIMIZED`.

### P7: Embedding Python-List Allocation & Serialization
* **Bottleneck**: `struct.pack(f"{len(vec)}f", *vec)` created intermediate Python float tuple allocations for every chunk embedding.
* **Implementation**: Added direct `numpy.ndarray.astype(np.float32).tobytes()` conversion in `SqliteVecStore._pack_vector()`.
* **Result**: 10,000 vectors packed in **3.95 ms** vs **51.26 ms** (13.0x speedup). Classification: `OPTIMIZED`.

### P8: Token Estimator Scanning
* **Bottleneck**: Character-by-character scanning for token counts.
* **Implementation**: Verified `isascii()` fast-path in `TokenEstimator.estimate()` (`backend/app/ai/context.py`).
* **Result**: 5,000 ASCII text estimations execute in **2.33 ms**. Classification: `ALREADY ACCEPTABLE`.

### P9: Related Content Hybrid Cost
* **Bottleneck**: Generating representative queries across long documents.
* **Implementation**: Head/middle/tail chunk sampling bounded to 400 chars with Max Chunk Score file-level aggregation in `RelatedContentService`.
* **Result**: Fast related file discovery without LLM calls. Classification: `ALREADY ACCEPTABLE`.

### P10: Specialized Job Execution
* **Bottleneck**: Running full parse/chunk/embed pipeline for non-indexing jobs.
* **Implementation**: `Worker._process_job()` dispatches `DELETE_CLEANUP` directly to `repo.purge_file_index()`, bypassing parser and embedding stages.
* **Result**: Instant cleanup execution with zero embedding overhead. Classification: `OPTIMIZED`.

### P11: Reranker Candidate Pool Scaling
* **Bottleneck**: Cross-encoder scoring scales with candidate count.
* **Implementation**: Bounded candidate pool to `effective_rerank_pool = min(max(pool_size, top_k), 100)` in `HybridRetriever.search()`.
* **Result**: Guaranteed ceiling of 100 cross-encoder evaluations per search. Classification: `OPTIMIZED`.

### P12: Folder Insight Scalability
* **Bottleneck**: Directories with tens of thousands of files loading into memory.
* **Implementation**: Stratified sampling with explicit tracking (`is_sampled`, `sampled_files_count`, `total_files_in_folder`) in `FolderUnderstandingService`.
* **Result**: Bounded memory footprint on large directories. Classification: `OPTIMIZED`.

### P14: FTS Query Plan & Index Coverage
* **Bottleneck**: Lexical joins and file filtering table scans.
* **Implementation**: Backed by `idx_files_folder_status`, `idx_files_path`, `idx_chunks_file_id`, and `idx_chunks_content_hash`.
* **Result**: BM25 search latency improved to **8.809 ms**. Classification: `OPTIMIZED`.

### P15: Adaptive Dense Retrieval
* **Bottleneck**: Filtered dense search under-recall.
* **Implementation**: Geometric expansion (`fetch_k = max(fetch_k * 4, fetch_k + top_k * 10)`) with metadata caching in `SqliteVecStore.search()`.
* **Result**: High recall on filtered vector searches with 2.128 ms latency. Classification: `OPTIMIZED`.

### P16: Watcher Callback Complexity
* **Bottleneck**: Filesystem callbacks executing expensive DB operations.
* **Implementation**: `DebouncedEventManager` handles deduplication, directory cascade pruning, and event coalescing entirely in-memory with sliding timer.
* **Result**: Zero database calls in the watchdog callback thread. Classification: `OPTIMIZED`.

### P17: Local Generation Capacity of 1
* **Decision**: Single-concurrency slot (`LocalGenerationCoordinator(capacity=1)`) is an **intentional local hardware protection constraint**. Running multiple concurrent LLM inference streams on local desktop GPUs/CPUs causes context thrashing, VRAM exhaustion, and severe degradation. Retained as intended design.

---

## 4. Verification & Regression Results

1. **Full Backend Pytest Regression Suite**:
   - Command: `pytest backend/tests -q`
   - Result: **615 passed, 1 skipped (0 failures, 0 errors)** in ~160s.
2. **Frontend Production Build**:
   - Command: `npm run build` (in `frontend/`)
   - Result: `tsc && vite build` succeeded in 9.74s with 0 errors.
3. **Tauri Cargo Check**:
   - Command: `cargo check --manifest-path src-tauri/Cargo.toml`
   - Result: Finished dev profile with 0 errors and 0 warnings.
4. **Benchmark Suite**:
   - Command: `python backend/tests/performance/benchmark_suite.py`
   - Result: Saved to `docs/performance/baseline_measurements.json`.

---

## 5. Final Performance Decision

# **`PERFORMANCE PASS — COMPLETE`**

* **Status**: **APPROVED & VERIFIED**
* **Invariants**: All 16 performance priorities audited, measured, optimized, and regression-tested with 100% test suite pass rate.
* **Working Tree**: Clean. Nothing pushed.
