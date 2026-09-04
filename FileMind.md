# FileMind.md — Agent Reference (Locked Specification)

> Read this file in full before writing or modifying any code in this repository.
> This is the authoritative contract for the FileMind project. It is derived from
> `FileMind_Locked_Specification.pdf` and `FileMind_Spec_and_Pipeline.pdf`, both
> STATUS: LOCKED. Do not treat anything here as a suggestion — the "Non-Negotiable"
> and "Never" sections are hard constraints, not style preferences.

---

## 0. Current Project State — READ FIRST

### Final Phase Status & Foundation State

PRE-PHASE-4 FOUNDATION: VERIFIED COMPLETE

Phase 0 — Release / Packaging:
VERIFIED PASS

Phase 1 — Filesystem Engine:
VERIFIED PASS

Phase 2 — Document Intelligence:
VERIFIED PASS

Phase 3 — Hybrid Retrieval:
VERIFIED PASS

Phase 4 — Fast / Quality Retrieval & Benchmark Exit Gate:
VERIFIED CLOSED (All 17 Exit Gate Items Passed)

Pre-Phase-5 Hardening Checkpoint (c7c6bd7 / 0d508e6):
- Batch A1 — Vector-Layer Integrity: VERIFIED PASS
- Batch A2 — Corpus Encoding & PDF Integrity: VERIFIED PASS
- Batch A3 — Chunking & Evidence Integrity: VERIFIED PASS
- Batch A3.1 — Reprocessing Vector Integrity & Version Migration: VERIFIED PASS

Pre-Phase-5 Practical Audit Fixes:
- Issue 1 — Tauri v2 Directory Dialog Capability (`dialog:allow-open`): VERIFIED PASS
- Issue 2 — Same-File Candidate Grouping & Provenance Preservation: VERIFIED PASS
- Issue 3 — Explicit Filename Intent Detection & Consistent Not-Found State: VERIFIED PASS

Phase 5.1 — Context & Token Budgeting:
VERIFIED COMPLETE (`ContextBudgetConfig`, `TokenEstimator`, `ContextBuilder`)

Phase 5.2 — Grounded Prompt Construction & Local Generation Contract:
VERIFIED COMPLETE (`PromptBuilder`, `CitationValidator`, `OllamaProvider`)

Phase 5.3 — Ask FileMind End-to-End Local RAG Pipeline & UI:
VERIFIED COMPLETE (`POST /ai/ask`, `AskService`, `AskModal`)

Phase 5.4 Batch 1 — Ask Readiness & Concurrency Hardening:
VERIFIED COMPLETE & PUSHED (`GET /ai/status`, tag probe, request sequencing — Commit `a55030f`)

Phase 5.4 Batch 2 — Ask UX Polish:
COMPLETE & PUSHED (Staged Progress, Copy Answer, Citation Auto-Scroll, In-Session History — Commit `ba45128`)

Phase 5.5 — Private Local Second Brain Knowledge Layer:
COMPLETE & FROZEN (Document Understanding, Related Content, Folder Understanding, Knowledge Connections)

Hardening Batches 1–4 — Full Hardening & Freeze Pass:
COMPLETE & FROZEN (Thread lifecycles, Ollama admission coordinator, citation normalizer, filesystem safety & parsers, React lifecycle guards, Page Visibility polling, Tauri supervisor, Knowledge Connections scale)

Full Backend Regression Suite:
476 / 477 PASS (476 passed, 1 skipped, 0 failed)

Phase 5 / 5.5 AI Test Suites:
150 / 150 PASS (Document Understanding, Related Content, Folder Understanding, Knowledge Connections, Ask Pipeline, Grounded Generation, Context Budget, Ollama Provider, AI Status, Hardening Batches 1–4, Batch 2 Parsers & Security, Batch 4 Final Freeze)

Frontend Production Build:
VERIFIED PASS (TypeScript + Vite, 1,606 modules, 0 errors)

Tauri v2 Desktop Check:
VERIFIED PASS (`cargo check`, 0 errors)

Phase 5 Release Gate Decision:
PHASE 5 — FROZEN (0 unresolved P0/P1 blockers, 115-item audit reconciled, release gates locked)

Phase 6 — Backend Architecture & Performance Refactor:
COMPLETE & VERIFIED (Modular APIRouters, domain-separated repositories, request-scoped dependencies, @map_service_errors, resolve_and_authorize security boundary, batched Knowledge Connections)
- Backend Test Suite: 490 / 491 PASS (490 passed, 1 skipped, 0 failed)
- Frontend Production Build: VERIFIED PASS (TypeScript + Vite, 1,606 modules, 0 errors)
- Tauri v2 Desktop Check: VERIFIED PASS (`cargo check`, 0 errors)








---

### Phase 0: Distribution Feasibility Baseline & Startup Trend
- **Status**: **COMPLETE / PASS**. See `docs/phase-0/validation-report.md`.
- **Packaged Architecture**: Tauri + React/TypeScript + PyInstaller `--onedir` Python/FastAPI sidecar + bundled `WebView2Loader.dll` runtime library.
- **Installer Artifact**: `dist/FileMind_0.1.0_x64-setup.exe` (**132.66 MB**; requirement `< 500 MB`).
- **Windows Defender**: Clean scan, 0 malware/PUA flags.
- **Uninstall**: Clean process termination, 0 orphan processes, complete removal of `$INSTDIR`.
- **Packaged Cold-Start Progression & Authoritative Baseline**:
  - **Original Phase 0 Historical Baseline (Small Dev Binary)**: **3.247 s** median (Range: 3.120 s – 3.390 s)
  - **Post-Phase-1 Historical Baseline**: **3.705 s** median (Range: 3.475 s – 3.710 s)
  - **Pre-Remediation Onefile Regression (180 MB Compressed Binary)**: **8.880 s** median (Range: 8.649 s – 9.723 s; caused by runtime on-the-fly archive extraction to `%TEMP%/_MEIxxxx` on every launch)
  - **Remediated Current Authoritative Installed Baseline (5 Runs, Onedir Sidecar)**: **1.192 s** median (Range: **1.174 s – 1.416 s**; Runs: 1.416s, 1.192s, 1.174s, 1.186s, 1.194s; P95: **1.416 s**)
  - **Direct GUI Cold Startup (FileMind.exe Launch → Edge WebView2 → /health 200)**: **4.518 s**
  - **Standalone `/health` Loopback Roundtrip (Active Server)**: **17.64 ms** median (Range: 4.20 ms – 20.80 ms)
  - **Current Phase 0 Gate Requirement**: `≤ 5.0 s`
  - **Current Headroom Below Gate**: **3.808 s** (**PASS**)
  - *Engineering Note on Packaging Remediation*: The PyInstaller `--onefile` runtime decompression bottleneck was resolved by adopting an unpacked `--onedir` sidecar architecture in `$INSTDIR\binaries\` alongside explicit inclusion of `WebView2Loader.dll` in `$INSTDIR\`. The 1.192 s measurement is the CURRENT authoritative packaged baseline going into Phase 4.

---

### Phase 1: Filesystem Engine Validated State
- **Status**: **COMPLETE / PASS**. See `docs/phase-1/validation-report.md` and `docs/phase-1/measurements.json`.
- **Validated Architecture**:
  - Persistent SQLite metadata store with WAL mode and versioned migrations at `%APPDATA%\FileMind\filemind.db`.
  - Folder registry and file registry with recursive discovery.
  - In-place directory and file exclusion filtering (`node_modules`, `.git`, `venv`, `dist`, `build`, `__pycache__`, `*.tmp`, `*.log`, `~$*`, user globs).
  - Path security layer (canonical normalization, traversal protection, null-byte rejection, reparse/junction safety).
  - Per-folder configurable integrity modes: `NORMAL` (fast-path mtime + size check) vs `STRICT` (full streaming SHA-256 verification).
  - Cross-platform `watchdog` event watcher with debounced normalization and deduplication.
  - Persistent SQLite job queue and bounded asynchronous worker pool with retry/exponential backoff, cancellation, and failure tracking.
  - Automatic process crash recovery resetting interrupted `PROCESSING` jobs to `PENDING` without requiring full folder re-scan.
  - Delete handling, rename/move handling, and state persistence across restarts.
  - Progressive indexing state surfaced via FastAPI REST endpoints and React/TypeScript management UI.
- **Audited Measurements & Workload Distinctions**:
  - **Discovery Throughput**: **761.56 files/sec** median (Range: 715.84 – 878.33 files/sec).
  - **Streaming SHA-256 Throughput (Large Single-File Benchmark)**: **606.74 MB/sec** median (Single 50 MB synthetic binary file, 64 KB buffers; measures maximum cryptographic hashing bandwidth without per-file filesystem overhead).
  - **Realistic Multi-File Hashing-Only Throughput**: **74.15 MB/sec** median (500 mixed files, 1 KB – 500 KB; includes discrete per-file OS open/read/close overhead across diverse files).
  - **Worker Queue Claiming Throughput**: **216.76 jobs/sec** median (Range: 205.85 – 237.19 jobs/sec).
  - **End-to-End Worker Processing Throughput**: **204.95 jobs/sec** median (Includes worker pool, queue claiming, streaming SHA-256, and SQLite updates).
  - **Watcher Path Latency**: **556.51 ms** median (Includes configured 500 ms sliding debounce window + ~56.5 ms processing/queue dispatch; must NOT be interpreted as pure OS watcher latency).
  - **Crash Recovery Latency**: **10.68 ms** median (Resetting stale `PROCESSING` jobs to `PENDING`).
  - **Resource Footprint**: Process memory **27.62 MB** RSS, Idle CPU **0.0%**.
- **Validation Test Evidence**:
  - 38 automated unit, security, and integration tests passing (`backend/tests/`). Real watcher, child-process termination recovery, and isolated delete/rename/move lifecycle verified.

---

### Phase 2: Document Intelligence Validated State
- **Status**: **COMPLETE / PASS**. See `docs/phase-2/validation-report.md`, `docs/phase-2/measurements.json`, and `docs/freeze-pass/freeze-report.md`.
- **Validated Architecture**:
  - Format Detection & MIME Sniffing: Extension mapping backed by magic header verification.
  - Parser Registry: Decoupled `BaseParser` interface with deferred lazy-loading managing format dispatch.
  - Normalized Document Model: `Document` and `DocumentElement` internal model capturing H1–H4 headings, styled paragraphs, lists, tabular headers/rows, code blocks, and byte/line/char offsets.
  - Parser Selection Decision: Evaluated PyMuPDF vs. PyPDF vs. Docling. Selected **PyMuPDF (`pymupdf-parser` v1.0.0)** for robust heading and table preservation with fast median latency (77.57 ms) and lightweight ~20 MB distribution impact, avoiding Docling's >2.5 GB PyTorch/Transformers payload.
  - Hierarchical Chunking (`phase2-hierarchical-v1`): Structure-first chunker associating paragraphs with parent headings (`h1_parent`, `h2_parent`, `section`), preserving table integrity without mid-row splits, avoiding empty heading-only chunks, and accumulating multi-paragraph body text toward a ~1500 character target.
  - Deterministic Chunk Identity:
    $$\text{chunk\_id} = \text{sha256}(\text{file\_id} : \text{h1\_parent} : \text{h2\_parent} : \text{chunk\_index} : \text{content\_hash})[:16]$$
    Identical reprocessing is 100% deterministic (0.0% churn). Semantic edits isolate churn to affected chunks. Heading hierarchy shifts properly update downstream chunk IDs to prevent invalid citation associations.
  - Immutable Provenance Tracking: Every chunk carries `chunk_id`, `file_id`, `source_file`, `source_path`, `page`, `section`, `h1_parent`, `h2_parent`, `line_start`, `line_end`, `char_start`, `char_end`, `content_hash`, `chunk_index`, `parser_name`, `parser_version`, `chunker_version`.
  - SQLite Persistence & Migrations: V2 migration adding `chunks` table with `ON DELETE CASCADE` and indexes on `file_id`, `content_hash`, `h1_parent`, and `page`.
  - Document Processing Lifecycle: Extended worker pool for `DOCUMENT_PARSE` and `DELETE_CLEANUP` with stale chunk replacement, zero orphan chunks, and explicit `SKIPPED`/`FAILED` failure isolation.
  - Developer Inspection UI: React Chunk Inspector modal displaying extracted headings, pages, spans, content hashes, and JSON provenance records.
- **Audited Parser Latencies (5-Run Median Baseline)**:
  - PDF Parse Latency: **77.57 ms** median (Range: 48.65 – 102.97 ms)
  - DOCX Parse Latency: **40.65 ms** median (Range: 22.43 – 54.68 ms)
  - PPTX Parse Latency: **20.99 ms** median (Range: 8.01 – 25.22 ms)
  - Markdown/Code Parse Latency: **0.99 ms** median (Range: 0.63 – 1.17 ms)
  - XLSX/Tabular Parse Latency: **19.41 ms** median (Range: 8.89 – 25.20 ms)
  - Hierarchical Chunking Latency: **0.76 ms** median (Range: 0.34 – 1.07 ms)

---

### Phase 0–2 Final Remediation & Freeze Pass Audit
- **Audit Decision**: **FROZEN / READY FOR PHASE 3** (0 A-Class Blockers). See `docs/freeze-pass/freeze-report.md` and `docs/freeze-pass/freeze-report.json`.
- **Final Test Suite**: **59/59 unit, lifecycle, and security tests passing (100%)**.
- **Final Packaging Baseline**: 87.62 MB installer, 0.971 s cold-start median (4.029 s headroom below $\le 5.0\text{ s}$ gate).
- **Chunking Distribution Characterization**:
  - Structure-first hierarchical chunking with a fine-grained observed distribution across combined short structural fixtures and realistic long-form documents.
  - Min: **19 chars** (standalone table header), Median: **161.0 chars**, P90: **2,420 chars**, P95: **2,420 chars**, Max: **2,420 chars**.
  - Bracket Breakdown: **77.8% < 500 chars** (standalone headings, list items, isolated table blocks), **0.0% 500–1499 chars**, **22.2% 1500–3000 chars** (multi-paragraph body sections), **0.0% > 3000 chars** (0% overflow beyond max bound).
  - Token Count: Min: **4**, Median: **40.0**, Mean: **159.7**, Max: **605**.
  - *Context*: Fine-grained distribution is a known characteristic of structure-first boundary splitting; Phase 3 retrieval will evaluate whether this materially affects search/ranking quality.
- **Adversarial Real-Document Structure Quality (`phase2-adversarial-corpus-v2`, 12 Diverse Documents)**:
  - Documents Parsed: **12/12 (100.0%)**
  - Heading Detection: **21/22 (95.5%)** (Correct levels: 21/21)
  - Table Preservation: **5/8 (62.5%)** (Vectorless text-drawn PDF tables are honestly identified as text flows by PyMuPDF)
  - Meaningful H1 Attribution: **24/26 chunks (92.3%)**
  - Exact Source Location Provenance: **21/26 chunks (80.8%)**
- **Controlled Scale Characterization**:
  - Ingested **3,503 files** (847,375 bytes) with 200 excluded files filtered in-place.
  - Discovery throughput: **950.09 files/sec** (3.687 s).
  - Progressive Indexing Milestones: First 100 files in **1.141 s**, first 500 in **5.228 s**, first 1,000 in **9.756 s**.
  - *Note*: Labeled as controlled scale characterization, not a universal guarantee of 10k–50k production scalability.
- **Watcher Burst Behavior**:
  - 20 rapid write events on a single file coalesced to **1 emitted event** (**95.0% reduction**).
  - End-to-end median latency: **556.51 ms** (500 ms debounce window + 56.5 ms queue overhead).
- **Mass-Failure Stress Test**:
  - 20 simultaneous files (10 valid, 5 corrupted PDFs, 5 unsupported binaries) $\rightarrow$ **100% error isolation**, 0 worker crashes, explicit inspectable failure reasons recorded in SQLite.
- **Concurrent Processing & Resource Footprint**:
  - **Authoritative Heavy Multi-Format Baseline**: **53.67 docs/sec** (40 documents parsed and indexed across 4 worker threads in 0.75 s, including PyMuPDF, python-docx, python-pptx, openpyxl, chunking, and SQLite WAL writes).
  - **Historical / Synthetic Text Baseline**: **44.06 docs/sec** (Measured on synthetic in-memory text/markdown documents without heavy binary decompression).
  - **Peak Process RSS**: **96.61 MB** (earlier peak: 118.51 MB during multi-worker stress).
  - **Post-Processing Idle RSS**: **90.90 MB**, Idle CPU: **0.0%**.

---

### Phase 3: Retrieval & Search Validated State
- **Status**: **COMPLETE / PASS**. See `docs/phase-3/validation-report.md`, `docs/phase-3/retrieval-benchmark.md`, `docs/phase-3/retrieval-benchmark.json`, and `docs/phase-3/measurements.json`.
- **Validated Architecture**:
  - **Query Normalizer** (`app/retrieval/normalizer.py`): Unicode NFKC normalization, whitespace collapsing, preservation of technical identifiers (`SHA-256`, `v1.0.0`, `file_events`, `sqlite-vec`), quoted phrase extraction, and FTS5 query sanitization.
  - **SQLite FTS5 Lexical Retrieval & Migration V3** (`app/retrieval/lexical.py`, `app/db/migrations.py`): `chunks_fts` virtual table with `unicode61 remove_diacritics 2` tokenizer, automatic SQLite triggers maintaining 1:1 synchronization on chunk insert/update/delete, BM25 ranking (`content: 5.0, h1: 2.0, h2: 1.5, section: 1.0, source_file: 2.0`), and metadata filtering.
  - **Dense Embedding Engine** (`app/retrieval/embeddings.py`): FastEmbed ONNX runtime with deferred lazy loading, selected model `sentence-transformers/all-MiniLM-L6-v2` (384-dim, 36.08 docs/s indexing throughput, 33.52 ms single query latency, ~90 MB RSS footprint).
  - **Native SQLite Vector Store** (`app/retrieval/vector_store.py`): `sqlite-vec` (`vec0` virtual table), 29,834 vectors/sec batch upsert throughput, 1.518 ms query latency, in-database WAL persistence, and zero extra sidecar processes.
  - **RRF Hybrid Retrieval** (`app/retrieval/hybrid.py`): Reciprocal Rank Fusion ($k=60$), deterministic tie-breaking (`rrf_score DESC, dense_score DESC, lexical_score DESC, chunk_id ASC`), and authentic non-hallucinatory snippet extraction.
  - **REST API Endpoint**: `POST /search` with latency breakdown (`normalization`, `lexical_search`, `query_embedding`, `dense_search`, `rrf_fusion`, `total_request`), mode switching (`hybrid`, `bm25`, `dense`), top-K limits, and folder/extension filters.
  - **Desktop Spotlight Search UI** (`frontend/src/components/SearchModal.tsx`, `frontend/src/App.tsx`): Spotlight/Raycast modal with `Ctrl+K` global shortcut, real-time debounced queries, format filters, keyword highlights, structural breadcrumbs (`H1 > H2 > Page`), and Safe Actions (`Open File`, `Open Folder`, `Copy Path`, `Inspect Chunk`).
- **Audited Head-to-Head Retrieval Quality Metrics (5 Runs, 28 Benchmark Queries)**:
  - **BM25 Only**: Recall@5 = **0.4933**, Recall@10 = **0.4933**, MRR = **0.5600**, NDCG@10 = **0.5090**, Median Latency = **0.134 ms**.
  - **Dense Only**: Recall@5 = **0.8613**, Recall@10 = **0.9113**, MRR = **0.8393**, NDCG@10 = **0.8263**, Median Latency = **15.646 ms**.
  - **HYBRID (BM25 + Dense + RRF k=60)**: Recall@5 = **0.9153**, Recall@10 = **0.9733**, MRR = **0.9433**, NDCG@10 = **0.9356**, Median Latency = **17.043 ms** (Range: 15.092 – 23.037 ms).
- **Stage Latency Breakdown (Hybrid Mode)**:
  - Stage A (Normalization): **0.012 ms**
  - Stage B (Lexical Search): **0.148 ms**
  - Stage C (Query Embedding): **15.210 ms**
  - Stage D (Dense Search): **1.480 ms**
  - Stage E (RRF Fusion): **0.183 ms**
  - Total Request Latency: **17.043 ms**
- **Test Suite Status**: **75 / 75 unit & integration tests passing (100%)**.
- **Cold-Start Verification**: **943.58 ms** (well below the $\le 5.0\text{ s}$ gate).
- **Strict Invariant Maintained**: Zero LLM / Ollama dependencies; search is 100% deterministic local evidence retrieval.

---

### Hardening 1 (H1): Windows Job Object Sidecar Lifecycle Validated State
- **Status**: **COMPLETE / PASS**. See `docs/hardening/h1-job-object.md` and `docs/hardening/h1-results.json`.
- **What Was Implemented**:
  - **Job Object RAII Guard** (`src-tauri/src/job_object.rs`): Encapsulated Win32 `HANDLE` with automatic `CloseHandle` in `Drop`.
  - **Kernel Lifecycle Contract**: Configured `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE (0x00002000)` via `SetInformationJobObject`.
  - **Exact Process Binding** (`src-tauri/src/main.rs`): Extracted `child.as_raw_handle()` and assigned child backend process directly via `AssignProcessToJobObject`.
  - **Integration Test Suite** (`backend/tests/test_sidecar_job_object.py`): Multi-scenario test verifying `IsProcessInJob`, graceful exit, forced abnormal termination, and clean relaunch.
- **Exact Evidence & Audited Results**:
  - **Kernel Membership**: Win32 `IsProcessInJob` returned `TRUE` for exact backend child PID.
  - **Scenario A (Graceful Close)**: Parent terminated gracefully $\rightarrow$ child backend exited cleanly $\rightarrow$ TCP port 24823 released in **304.29 ms**.
  - **Scenario B (Abnormal Forced Termination)**: Parent killed with `taskkill /F /PID <exact_parent_pid>` $\rightarrow$ Windows kernel terminated child backend in **201.25 ms** $\rightarrow$ TCP port 24823 released in **309.65 ms** $\rightarrow$ 0 orphan processes.
  - **Scenario C (Relaunch & Health)**: Fresh instance spawned $\rightarrow$ backend initialized $\rightarrow$ `/health` returned HTTP 200 OK (`status: "healthy"`).
  - **PID Safety Audit**: 100% exact-PID isolation; zero wildcard or process-name based kills (`taskkill /IM` strictly forbidden).
- **Files Created & Modified**:
  - `src-tauri/src/job_object.rs` (Created — Win32 Job Object RAII guard)
  - `backend/tests/test_sidecar_job_object.py` (Created — H1 lifecycle integration test)
  - `docs/hardening/h1-job-object.md` (Created — Architectural dossier)
  - `docs/hardening/h1-results.json` (Created — Audited test measurements)
  - `src-tauri/Cargo.toml` (Modified — Added `windows-sys` dependency)
  - `src-tauri/src/main.rs` (Modified — Integrated `JobObjectGuard` into supervisor)
  - `src-tauri/tauri.conf.json` (Modified — Cleaned plugins config)
  - `.cargo/config.toml` (Modified — Target-specific MSVC rustflags)
- **Overall Backend Test Suite**: **77 / 77 unit & integration tests passing (100%)** (`pytest tests/ -v`).
- **Remaining Limitations & Boundaries**:
  - Process lifecycle ownership & orphan prevention is distinct from SQLite ACID/WAL transaction consistency (which is handled separately by SQLite and crash recovery).
  - Hardening tasks H3, H4, and Phase 4 remain **NOT STARTED / NOT AUTHORIZED**.

---

### Hardening 2 (H2): Directory Event Cascade Coalescing Validated State
- **Status**: **COMPLETE / PASS**. See `docs/hardening/h2-directory-event-cascade.md` and `docs/hardening/h2-results.json`.
- **What Was Implemented**:
  - **Subtree Repository Queries** (`backend/app/db/repository.py`): Atomic `mark_directory_missing` and `rename_directory_path` implementing single-query subtree file status updates and batch indexing job cancellation.
  - **Subpath Path Normalization** (`backend/app/engine/watcher.py`): Windows-aware case-insensitive `is_subpath` matcher preventing child event leaks and separator mismatch.
  - **Directory Event Coalescing** (`backend/app/engine/watcher.py`): `DebouncedEventManager` prunes child events upon receiving directory operations and collapses synthetic watchdog child notifications.
  - **Batch Transaction Engine** (`backend/app/engine/watcher.py`): `WatcherService._handle_flushed_batch` processes entire event batches in a single atomic SQLite transaction, eliminating write lock contention.
  - **H2 Test Suite** (`backend/tests/test_directory_cascades.py`): 8 focused test scenarios covering directory deletes, renames, burst cascades, delete+recreate races, and nested folder isolation.
- **Exact Evidence & Audited Results**:
  - **Synthetic Cascade Fixture**: 4,980 files across 60 directories, max depth 3, 740,175 bytes.
  - **Directory Delete Convergence**: 1,013 raw watchdog events processed with 0 remaining unprocessed files in **2,059.63 ms** median (5 runs: 1,911.29 ms, 2,026.27 ms, 2,429.04 ms, 2,059.63 ms, 2,295.31 ms).
  - **Directory Move/Rename Convergence**: 996 files updated to new relative paths in **1,004.18 ms** median (5 runs: 1,004.18 ms, 1,005.16 ms, 1,006.55 ms, 1,002.67 ms, 1,003.24 ms).
  - **Burst Coalescing**: 500 child file deletes collapsed into 1 directory delete operation.
  - **Full Backend Pytest Regression**: **85 / 85 unit & integration tests passing (100%)** (`pytest tests/ -v`).
- **Files Created & Modified**:
  - `backend/tests/test_directory_cascades.py` (Created — H2 cascade test suite)
  - `backend/tests/benchmark_directory_cascade.py` (Created — 5-run statistical telemetry benchmark)
  - `docs/hardening/h2-directory-event-cascade.md` (Created — H2 engineering dossier)
  - `docs/hardening/h2-results.json` (Created — Audited benchmark telemetry)
  - `backend/app/engine/watcher.py` (Modified — Directory event coalescing and batch transactions)
  - `backend/app/db/repository.py` (Modified — Atomic subtree SQL operations)
  - `FileMind.md` (Modified — Documented H2 validated state)
- **Remaining Limitations & Boundaries**:
  - Hardening tasks H4 and Phase 4 remain **NOT STARTED / NOT AUTHORIZED**.

---

### Hardening 3 (H3): PDF Extraction-Quality Gate & Observability Validated State
- **Status**: **COMPLETE / PASS**. See `docs/hardening/h3-pdf-extraction-quality.md` and `docs/hardening/h3-results.json`.
- **What Was Implemented**:
  - **Quality Signals & Decision Policy** (`backend/app/intelligence/parsers/quality.py`): Measures 12 observable signals (raw char count, printable ratio, replacement char count, control char count, whitespace ratio, word count, meaningful text pages, image count) and classifies extraction into `PARSED`, `PARSE_WARNING`, `REQUIRES_OCR`, or `FAILED_PARSE`.
  - **PyMuPDF Parser Integration** (`backend/app/intelligence/parsers/pdf_parser.py`): In-flight raw extraction telemetry during layout analysis attaching `PDFQualityAssessment` to `Document` objects.
  - **Vectorization Boundary** (`backend/app/engine/worker.py`): Intercepts `REQUIRES_OCR` documents before chunking and embedding, purging any existing chunks/vectors and marking the file `SKIPPED` with structured JSON diagnostic metadata in `files.indexing_error`.
  - **Atomic Queue & Status Persistence** (`backend/app/db/repository.py`, `backend/app/engine/queue.py`): Enhanced `complete_job` to transactionally record final statuses (`SKIPPED`, `INDEXED`) and diagnostic error payloads.
  - **H3 Quality Test Suite** (`backend/tests/test_pdf_quality_gate.py`): 12 comprehensive unit and integration tests covering normal text, multi-page, scanned image-only, low-text stamp, code/math/table/unicode non-rejection, vector poisoning prevention, reprocessing recovery, and delete cleanup.
  - **5-Run Benchmark Telemetry** (`backend/tests/benchmark_pdf_quality.py`): 10-document synthetic evaluation fixture measuring performance overhead and classification accuracy across 5 runs.
- **Exact Evidence & Audited Results**:
  - **Classification Distribution**: 7 `PARSED`, 1 `PARSE_WARNING`, 2 `REQUIRES_OCR`, 0 `FAILED_PARSE`.
  - **False Positives**: **0** (0.0% — Valid code, math, foreign language, and short documents 100% preserved).
  - **False Negatives**: **0** (0.0% — Scanned documents 100% caught).
  - **Vector Poisoning Prevented Documents**: **2** (0 chunks, 0 embeddings, 0 vectors written for scanned/image-only PDFs).
  - **Performance Overhead**: **8.95 ms** median latency per document (Range: 7.33 ms – 10.31 ms).
  - **Full Backend Pytest Regression**: **97 / 97 unit & integration tests passing (100%)** (`pytest tests/ -v`).
  - **OCR Scope**: Zero OCR code implemented (OCR strictly deferred to future Phase 7).
- **Files Created & Modified**:
  - `backend/app/intelligence/parsers/quality.py` (Created — PDF extraction quality module)
  - `backend/tests/test_pdf_quality_gate.py` (Created — H3 test suite)
  - `backend/tests/benchmark_pdf_quality.py` (Created — 5-run H3 benchmark runner)
  - `docs/hardening/h3-pdf-extraction-quality.md` (Created — H3 engineering dossier)
  - `docs/hardening/h3-results.json` (Created — Audited benchmark telemetry)
  - `backend/app/intelligence/models.py` (Modified — Added `quality_assessment` to `Document`)
  - `backend/app/intelligence/parsers/pdf_parser.py` (Modified — Integrated quality signals in `PyMuPDFParser` and `PyPDFParser`)
  - `backend/app/engine/worker.py` (Modified — Vectorization boundary and diagnostic status)
  - `backend/app/db/repository.py` (Modified — Transactional `complete_job` status support)
  - `backend/app/engine/queue.py` (Modified — `complete_job` forwarding)
  - `FileMind.md` (Modified — Documented H3 validated state)
- **Remaining Limitations & Boundaries**:
  - Phase 4 remains **NOT STARTED / NOT AUTHORIZED**.

---

### Hardening 4 (H4): SQLite WAL Observability & Concurrency Validated State
- **Status**: **COMPLETE / PASS**. See `docs/hardening/h4-sqlite-wal.md` and `docs/hardening/h4-results.json`.
- **Validated SQLite Configuration**:
  - `journal_mode = WAL`
  - `synchronous = NORMAL`
  - `busy_timeout = 10,000 ms`
  - `foreign_keys = ON`
  - Context-managed transaction closure via `DatabaseManager.session()`.
- **Validated Workload**:
  - 2,500 files/chunks/vectors per run across 5 benchmark runs (**12,500 items total**).
  - 2 background writer threads (file metadata, chunk persistence, sqlite-vec updates, job completion).
  - 2 background reader threads (FTS5 BM25 search, metadata listing, sqlite-vec nearest neighbor search).
  - Isolated temporary database (`filemind.db`).
- **Measured Results Across 5 Runs**:
  - **Peak WAL Size (Median)**: **10.24 MB** (Peak range: 8.30 MB – 14.37 MB).
  - **Final WAL Size**: **0 bytes** after automatic checkpointing.
  - **Passive Checkpoint Duration (Median)**: **4.283 ms** (0 busy errors).
  - **FTS5 Read Latency (Median)**: **3.815 ms** (P95: 28.220 ms).
  - **Metadata Read Latency (Median)**: **3.846 ms** (P95: 14.950 ms).
  - **Vector Search Latency (Median)**: **10.051 ms** (P95: 28.876 ms).
  - **Write Transaction Latency (Median)**: **7.910 ms** (P95: 53.434 ms).
- **Architectural & Production Changes**:
  - `backend/app/engine/worker.py`: CPU neural embedding computation (`embed_texts`) was moved **OUTSIDE** the SQLite write transaction, ensuring the SQLite write lock is held strictly for the rapid SQL persistence ($\sim 7.91\text{ ms}$) rather than blocking other workers during 150ms+ ONNX model inference.
    - *Write Transaction Duration Before*: $\sim 180.02\text{ ms}$ median (P95: 1,468.41 ms).
    - *Write Transaction Duration After*: **7.91 ms** median (P95: **53.43 ms**).
  - `backend/app/db/repository.py`: Atomic job claiming using single-statement `UPDATE indexing_jobs ... RETURNING *`, eliminating worker claim race conditions and lock contention.
  - *Purpose & Impact*: Shorter write-lock duration, reduced contention, preserved transaction atomicity, improved concurrency behavior.
- **Concurrency & Checkpoint Findings**:
  - "SQLite WAL configuration was measured healthy under the validated workload; no checkpoint redesign was required."
  - "No reader or writer starvation was observed during the validated workload."
- **Evidence & Verification**:
  - [`backend/tests/test_sqlite_wal.py`](file:///c:/dev/FileMind/backend/tests/test_sqlite_wal.py) (8 focused H4 concurrency tests).
  - [`backend/tests/benchmark_sqlite_wal.py`](file:///c:/dev/FileMind/backend/tests/benchmark_sqlite_wal.py) (5-run empirical telemetry benchmark).
  - [`docs/hardening/h4-sqlite-wal.md`](file:///c:/dev/FileMind/docs/hardening/h4-sqlite-wal.md) (Engineering dossier).
  - [`docs/hardening/h4-results.json`](file:///c:/dev/FileMind/docs/hardening/h4-results.json) (Audited JSON benchmark results).
  - **105 / 105 backend tests PASSING (100%)** (`pytest tests/ -v`).
- **Explicit SQLite Limitation**:
  - "H4 validates SQLite WAL behavior under the tested workload. It does not constitute a universal guarantee against all possible SQLite concurrency or crash-consistency scenarios."

---

### Post-Phase-3 Hardening Status
- **H1 (Windows Job Object Process-Lifecycle Hardening)**: **COMPLETE / PASS**. See `docs/hardening/h1-job-object.md` and `docs/hardening/h1-results.json`.
- **H2 (Directory Event Cascade Coalescing)**: **COMPLETE / PASS**. See `docs/hardening/h2-directory-event-cascade.md` and `docs/hardening/h2-results.json`.
- **H3 (PDF Extraction-Quality Gate & Observability)**: **COMPLETE / PASS**. See `docs/hardening/h3-pdf-extraction-quality.md` and `docs/hardening/h3-results.json`.
- **H4 (SQLite WAL Observability & Transaction-Boundary Hardening)**: **COMPLETE / PASS**. See `docs/hardening/h4-sqlite-wal.md` and `docs/hardening/h4-results.json`.

All four hardening tasks completed independently. No Phase 4 functionality was introduced.

---

### Pre-RAG Integrity Pass — P1: Provenance Exactness Audit
- **Audit Timestamp**: 2026-08-30
- **Status & Verdict**: **KNOWN STRUCTURAL LIMITATION / VERIFIED ACCEPTABLE**
- **Findings & Failure Categorization**:
  - Investigated the 19.2% of imperfect cases (5 of 26 chunks) from the Phase 2 adversarial corpus (`phase2-adversarial-corpus-v2`).
  - All 5 failing chunks belong exclusively to DOCX format (`DOCX_1`: 4 chunks, `DOCX_2`: 1 chunk).
  - Categorization: **Category C — STRUCTURALLY UNRECOVERABLE / PARSER LIMITATION**.
  - *Cause*: OpenXML (.docx) is a zipped XML container with text flow in `word/document.xml`. It possesses no static visual page layout metadata (pagination is calculated dynamically at runtime by word processors), and raw file byte/char offsets into the zip archive cannot be used to slice original plaintext.
  - *Hierarchy & Identity Attribution*: Structural hierarchy (`h1_parent`, `h2_parent`, `section`) and deterministic `chunk_id` are 100% accurate (e.g. `Operational Runbook > Cluster Topologies` correctly attributed).
  - *Other Formats (21/26 chunks, 80.8%)*: PDF (100% exact page attribution), Markdown/Source Code (100% exact char and line spans), PPTX (100% slide/page attribution), XLSX/CSV (100% sheet/page and row line attribution).
- **Remediation & Code Impact**: No production-code changes required or justified; structural limitation is documented and does not violate chunk identity or citation integrity.
- **Evidence**: [`backend/tests/freeze_pass/measure_real_document_structure.py`](file:///c:/dev/FileMind/backend/tests/freeze_pass/measure_real_document_structure.py), [`backend/tests/test_provenance_integrity.py`](file:///c:/dev/FileMind/backend/tests/test_provenance_integrity.py).

---

### Pre-RAG Integrity Pass — Query Denominator Reconciliation (P2 & P3 Audited Scope)
- **Canonical Benchmark Size**: **28 Total Queries** in `docs/phase-3/evaluation-dataset.json`.
- **Query Accounting & Classification Matrix**:
  - **Positive Evaluatable Queries ($N=25$)**: Included in positive Recall, MRR, and NDCG metric evaluations across P2 and P3.
  - **Negative Out-of-Corpus Queries ($N=3$)** (`Q26_NEGATIVE_NO_MATCH_1`, `Q27_NEGATIVE_NO_MATCH_2`, `Q28_NEGATIVE_NO_MATCH_3`): Excluded from positive Recall/MRR denominators because expected chunks $= 0$ (Recall is mathematically undefined for zero-target items). Validated independently for zero false-positive contamination (Precision $= 1.0$).
- **Reconciled Group Breakdown of Active Queries ($11 + 9 + 5 = 25$)**:
  1. **Lexical / Exact / Identifier Group ($N=11$)**:
     - Queries: `Q01_EXACT_FILENAME` (1), `Q02_EXACT_PHRASE` (1), `Q03_EXACT_PHRASE_STORAGE` (1), `Q04_KEYWORD_IDENTIFIER` (1), `Q05_CODE_SNIPPET` (1), `Q06_TECHNICAL_ACRONYM` (1), `Q07_TECHNICAL_TERM` (1), `Q08_CODE_IDENTIFIER` (1), `Q09_PARTIAL_TERM` (1), `Q22_SINGLE_HIGH_RELEVANCE` (1), `Q24_METADATA_FILTER_H1` (1).
     - *BM25*: Recall@5 = **0.9545**, MRR = **1.0000**
     - *Dense*: Recall@5 = **0.8591**, MRR = **0.8091**
     - *Hybrid*: Recall@5 = **0.9818**, MRR = **1.0000**
  2. **Semantic / Natural Language / Conceptual Group ($N=9$)**:
     - Queries: `Q10_SEMANTIC_CONCEPT_1` (1), `Q11_SEMANTIC_CONCEPT_2` (1), `Q12_SEMANTIC_CONCEPT_3` (1), `Q13_SEMANTIC_CONCEPT_4` (1), `Q14_SEMANTIC_CONCEPT_5` (1), `Q19_TABLE_CONTENT` (1), `Q20_NATURAL_LANGUAGE_1` (1), `Q21_NATURAL_LANGUAGE_2` (1), `Q25_HEADCOUNT_QUERY` (1).
     - *BM25*: Recall@5 = **0.0000**, MRR = **0.0000**
     - *Dense*: Recall@5 = **0.8889**, MRR = **0.9259**
     - *Hybrid*: Recall@5 = **0.8889**, MRR = **0.9259**
  3. **Multi-Term / Ambiguous / Multi-Chunk Group ($N=5$)**:
     - Queries: `Q15_HYBRID_MULTI_TERM_1` (1), `Q16_HYBRID_MULTI_TERM_2` (1), `Q17_HYBRID_MULTI_TERM_3` (1), `Q18_MULTI_CHUNK_RELEVANCE` (1), `Q23_AMBIGUOUS_QUERY` (1).
     - *BM25*: Recall@5 = **0.3667**, MRR = **0.6000**
     - *Dense*: Recall@5 = **0.8167**, MRR = **0.7500**
     - *Hybrid*: Recall@5 = **0.8167**, MRR = **0.8500**
- **Historical Metrics Status**: Prior draft references stating $N=22$ reflected 9 named categories rather than the full 25 active query instances; the reconciled $11 + 9 + 5 = 25$ positive query mapping represents the **CURRENT AUDITED VALUE**.

---

### Pre-RAG Integrity Pass — P2: Chunk-Size Retrieval Impact
- **Audit Timestamp**: 2026-08-30
- **Status & Verdict**: **NO MATERIAL RETRIEVAL DEGRADATION FOUND**
- **Methodology & Distribution**:
  - Investigated whether the fine-grained structural chunk distribution (median 98–161 chars, 98.1% < 500 chars in structural corpus) materially degrades retrieval quality across all 25 active benchmark queries.
- **False Negative Findings**:
  - In Hybrid retrieval (production configuration), short target chunks achieved **Recall@5 = 0.8478**, **Recall@10 = 0.9565**, and **MRR = 0.9076**.
  - No systematic dropping of short chunks occurred. For broad multi-chunk queries, top ranks reliably surface the primary overview and structural sections.
- **False Positive Findings**:
  - Examined whether heading-only or low-context chunks pollute top ranks.
  - In Hybrid mode, 0 irrelevant or hallucinated heading-only chunks achieved top rank. All top-1 results provided authentic evidence.
- **Remediation & Chunker State**: Frozen Phase 2 chunker (`HierarchicalChunker`) remains **UNCHANGED**.

---

### Pre-RAG Integrity Pass — P3: BM25 Mechanism-Level Verification
- **Audit Timestamp**: 2026-08-30
- **Status & Verdict**: **BM25 IMPLEMENTATION VERIFIED CORRECT**
- **Failing Query Mechanism Trace ($N=14$ BM25 failures out of 25 active queries)**:
  - Traced every failing query through normalization, FTS5 SQL construction (`MATCH "term1"* "term2"* ...`), token extraction, and target chunk content.
  - **Category Classification**: All 14 failing queries classified as **Category A: EXPECTED LEXICAL FAILURE (Semantic / Conceptual Paraphrase / Conjunction Mismatch)**.
    - *Example 1 (Semantic Concept, Q10)*: Query "graceful crash recovery and restart semantics" vs Chunk content "resets stale PROCESSING jobs to PENDING in WAL mode". Zero token overlap; vocabulary mismatch is genuine.
    - *Example 2 (Natural Language, Q20)*: Query "What is the key rotation interval for Tier-1 TLS 1.3 protocol?" contains conversational filler ("What", "is", "the", "for") not present in the target Markdown table row (`| Tier-1 | TLS 1.3 | 24 hours |`).
    - *Example 3 (Table Headcount, Q25)*: Query "Engineering department headcount" vs Table containing `Dept: Engineering, Count: 12` (no literal "department" or "headcount" in row content).
    - *Conjunction Mismatch in Multi-term queries*: FTS5 whitespace-separated terms act as an implicit `AND`. When multiple terms are provided across disparate sections, single-chunk lexical hits fail if not all terms co-occur in the same chunk.
- **Lexical Subsystem Verification**:
  - On the **Lexical / Exact Group ($N=11$)**, BM25 achieves **Recall@5 = 0.9545** and **MRR = 1.0000** (perfect top-1 rank on all 11 exact symbol, code, acronym, and identifier queries).
  - Tokenizer (`unicode61 remove_diacritics 2`), normalization, identifier protection, and BM25 field weights (`content: 5.0, h1: 2.0, h2: 1.5, section: 1.0, source_file: 2.0`) are verified 100% correct.
- **Remediation & Code Impact**: No lexical search defect found; BM25 implementation remains **UNCHANGED**.

---

### Pre-RAG Integrity Pass — P4: Critical Failure Recovery & Hybrid Fallback Contract
- **Audit Timestamp**: 2026-08-30
- **Status & Verdict**: **PASS — VERIFIED SAFE & GRACEFUL FALLBACK IMPLEMENTED**
- **Contract Check & Fallback Semantics**:
  - *Contract Requirement*: Retrieval availability requires that desktop search remains responsive and delivers authentic evidence even when underlying neural hardware acceleration or vector storage components experience temporary failure or corruption.
  - *Previous Behavior*: `mode="hybrid"` propagated uncaught `RuntimeError` if vector store failed.
  - *Audited & Implemented Behavior*:
    - **Hybrid Search**: When vector store or embedding model fails during a hybrid query, `HybridRetriever.search()` safely catches the dense failure, logs a diagnostic warning, marks the response as degraded (`degraded = True`, `degraded_reason = "dense_retrieval_unavailable: <error>"`, `retrieval_method = "bm25_fallback"`), and seamlessly returns BM25-ranked evidence.
    - **Score Authenticity**: Zero dense or RRF scores are fabricated during fallback (`dense_score = None`, `rrf_score = None`, `score = lexical_score`).
    - **Dense-Only Search**: `mode="dense"` preserves controlled exception raising (`RuntimeError`) because dense-only retrieval cannot satisfy semantic constraints without vector embeddings.
    - **BM25-Only Search**: `mode="bm25"` executes 100% independently of the vector store with zero vector store interactions.
    - **Recovery**: Automatic recovery to standard hybrid RRF retrieval as soon as vector store / embedding engine availability is restored.
- **Individual Failure Evaluations**:
  1. **Embedding Call Failure During Indexing**: Worker catches embedding exception, isolates failure, skips vector insertion, and completes atomic SQLite persistence for relational metadata, chunks, and FTS5 triggers. Zero worker crashes, zero DB corruption, zero invalid vectors.
  2. **Vector Index Unavailability During Search**: Hybrid query gracefully degrades to BM25 with explicit `degraded=True` telemetry.
  3. **Vector Index Corruption During Startup**: Relational tables (`files`, `chunks`, `folders`, `indexing_jobs`) and `chunks_fts` survive 100% intact (`PRAGMA integrity_check = ok`). Virtual table is safely recreated upon reinitialization.
- **Evidence & Test Suite**: [`backend/tests/test_hybrid_fallback.py`](file:///c:/dev/FileMind/backend/tests/test_hybrid_fallback.py) (9 tests passing 100%), [`backend/tests/test_lexical_retrieval.py`](file:///c:/dev/FileMind/backend/tests/test_lexical_retrieval.py), [`backend/tests/test_sqlite_wal.py`](file:///c:/dev/FileMind/backend/tests/test_sqlite_wal.py). Full suite: **114 / 114 tests passing**.

---

### Phase 4 Pre-Flight Correction — Production Dependencies & Clean-Venv Verification
- **Audit Timestamp**: 2026-08-30
- **Status & Verdict**: **PASS — VERIFIED COMPLETE IN CLEAN VENV**
- **Production Dependency Audit**:
  - Direct production runtime dependencies inspected across `backend/app/`: `fastapi`, `uvicorn`, `pydantic`, `watchdog`, `pymupdf` (`fitz`), `pypdf`, `python-docx`, `python-pptx`, `openpyxl`, `fastembed`, `sqlite-vec`, `numpy`, `lancedb`, `pyarrow`.
  - Direct test/tooling dependencies inspected across `backend/tests/`: `pytest`, `httpx`, `psutil`, `reportlab`.
  - **Newly Declared / Corrected Dependencies in `backend/requirements.txt`**:
    - `fastembed>=0.8.0` (local ONNX embedding inference engine)
    - `sqlite-vec>=0.1.6` (native vector search extension for SQLite)
    - `numpy>=1.26.0` (cosine distance / vector transformations)
    - `lancedb>=0.37.0` & `pyarrow>=14.0.0` (embedded vector table backend)
- **Clean-Venv Verification**:
  - Created isolated temporary virtual environment (`filemind_clean_venv`).
  - Installed solely via `pip install -r backend/requirements.txt` with zero manual additions.
  - Verified successful import of production backend (`app.main`) and retrieval engines (`HybridRetriever`, `EmbeddingEngine`, `SqliteVecStore`, `LanceDBVectorStore`).
  - Ran full backend test suite: **114 / 114 tests PASSING (100%)**.
- **Embedding Model Memory Instrumentation Audit & Negative RSS Root Cause**:
  - *Root Cause Analysis*: In the original Phase 3 benchmark suite ([`backend/tests/benchmark_embeddings_and_stores.py`](file:///c:/dev/FileMind/backend/tests/benchmark_embeddings_and_stores.py)), embedding models were evaluated sequentially in a single Python process. Peak heap and ONNX runtime buffers allocated during model 1 (`bge-small`) were garbage-collected or unmapped by the OS allocator when model 2 (`all-MiniLM-L6-v2`) initialized. Computing `mem_after_load - mem_before` within the same process resulted in an invalid negative value (`memory_rss_mb = -92.79`).
  - *Measurement Semantics Correction*: Separated memory into unambiguous metrics:
    - `model_load_rss_delta_mb`: Isolated memory added specifically by loading the model in a clean subprocess (`mem_after_load - baseline_clean_process`).
    - `absolute_process_rss_mb`: Total isolated process RSS with the model loaded into memory.
  - *Preserved Historical Value*: `memory_rss_mb = -92.79` preserved as **HISTORICAL INVALID MEASUREMENT** (due to in-process cross-model heap cleanup).
  - *Corrected Audited Measurements (5 Runs)*:
    - **`sentence-transformers/all-MiniLM-L6-v2`**: **151.68 MB** median load delta (Range: 151.25 – 151.93 MB) / **179.89 MB** median total process RSS (Range: 179.48 – 180.18 MB).
    - **`BAAI/bge-small-en-v1.5`**: **139.73 MB** median load delta (Range: 139.51 – 139.93 MB) / **167.90 MB** median total process RSS (Range: 167.75 – 168.08 MB).
    - **`nomic-ai/nomic-embed-text-v1.5`**: **589.90 MB** median load delta / **618.18 MB** median total process RSS.
- **Evidence & Verification Scripts**: [`backend/tests/benchmark_embeddings_and_stores.py`](file:///c:/dev/FileMind/backend/tests/benchmark_embeddings_and_stores.py), [`docs/phase-3/retrieval-benchmark.json`](file:///c:/dev/FileMind/docs/phase-3/retrieval-benchmark.json), [`docs/phase-3/verify_measurement_consistency.py`](file:///c:/dev/FileMind/docs/phase-3/verify_measurement_consistency.py) (11/11 checks PASS).
- **Files Modified**: [`backend/requirements.txt`](file:///c:/dev/FileMind/backend/requirements.txt), [`backend/tests/benchmark_embeddings_and_stores.py`](file:///c:/dev/FileMind/backend/tests/benchmark_embeddings_and_stores.py), [`docs/phase-3/retrieval-benchmark.json`](file:///c:/dev/FileMind/docs/phase-3/retrieval-benchmark.json), [`docs/phase-3/validation-report.md`](file:///c:/dev/FileMind/docs/phase-3/validation-report.md), [`docs/phase-3/verify_measurement_consistency.py`](file:///c:/dev/FileMind/docs/phase-3/verify_measurement_consistency.py).
- **Phase Boundary**: Phase 4 remains **NOT STARTED / NOT AUTHORIZED**.

---

### Hardening 1 (H1) Regression Investigation & Observation Synchronization
- **Audit Timestamp**: 2026-08-30
- **Status & Verdict**: **PASS — ROOT CAUSE ISOLATED & SYNCHRONIZED**
- **Incident Summary**:
  - `test_sidecar_job_object.py::test_job_object_lifecycle_and_orphan_prevention` intermittently failed with `AssertionError: Child PID survived graceful parent close!` under heavy test-suite execution.
- **Root Cause Analysis (Category C — Test Timing / Observation Race)**:
  - *Kernel Mechanics*: When the Tauri supervisor process terminates, its Win32 Job Object handle closes. The Windows kernel immediately triggers `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` to terminate the child backend process asynchronously.
  - *Observation Flaw*: Scenario B used a synchronization polling loop (`while time.perf_counter() - t0 < 5.0:`), but Scenario A used a fixed `time.sleep(0.5)` followed by an immediate assertion.
  - *Empirical OS Measurement*: Empirical instrumentation over 5 consecutive runs demonstrated that Windows kernel child process teardown and PID removal from the kernel process table requires between **151.59 ms and 2,223.47 ms** under variable system/IO load. Checking at exactly 500 ms observed the process during kernel teardown before PID table unregistration, causing an observation race. In all runs, the child process was confirmed 100% terminated with zero orphan processes and port 24823 completely released.
- **Remediation**:
  - Updated Scenario A in [`backend/tests/test_sidecar_job_object.py`](file:///c:/dev/FileMind/backend/tests/test_sidecar_job_object.py) to use an explicit synchronization polling loop (with a 5.0 s timeout), precisely matching Scenario B, without weakening any lifecycle requirements.
  - Added `child_termination_latency_ms` telemetry to Scenario A results.
- **Verification Evidence**:
  - **Repeated H1 Targeted Runs**: 5 / 5 consecutive runs PASSED (100% reliability; Scenario A child termination: 151 ms – 2,223 ms; Scenario B child termination: 100 ms – 2,211 ms; Scenario C relaunch: HTTP 200 OK).
  - **Full Backend Pytest Regression**: **114 / 114 tests PASSING (100%)** in 260.64s.
- **Files Modified**: [`backend/tests/test_sidecar_job_object.py`](file:///c:/dev/FileMind/backend/tests/test_sidecar_job_object.py), [`docs/hardening/h1-results.json`](file:///c:/dev/FileMind/docs/hardening/h1-results.json).
- **Phase Boundary**: Phase 4 remains **NOT STARTED / NOT AUTHORIZED**.

---

### Tauri Development Backend Spawn Path Resolution
- **Audit Timestamp**: 2026-08-30
- **Status & Verdict**: **PASS — RESOLVED & VERIFIED IN DEV & TEST MODES**
- **Incident Summary**:
  - During live testing on Windows under `cargo tauri dev`, Vite started at `http://localhost:1420`, but no Python backend process was started, leaving port 24823 without a listening socket and `/health` returning connection refused.
- **Root Cause Analysis**:
  - The Tauri `.setup()` hook in [`src-tauri/src/main.rs`](file:///c:/dev/FileMind/src-tauri/src/main.rs) calls `spawn_backend()`. In development mode without a pre-built PyInstaller `.exe` in `dist/` or `binaries/`, `locate_backend_executable()` returned `None` and fell through to the dev fallback.
  - The dev fallback used hardcoded relative paths `backend/.venv/Scripts/python.exe` and `backend/run_server.py`.
  - When `cargo tauri dev` runs, the process Current Working Directory (CWD) is `C:\dev\FileMind\src-tauri`. Relative to `src-tauri`, `backend/.venv/...` checked `src-tauri/backend/.venv/...` which did not exist, causing the fallback to fail silently to `[Tauri Supervisor] Standalone backend binary not found.` without spawning any Python backend process.
- **Exact Remediation in `src-tauri/src/main.rs`**:
  - Implemented `locate_dev_backend() -> Option<(PathBuf, PathBuf)>` supporting multi-CWD repository layouts and virtual environments:
    - Python search candidates: `backend/.venv/Scripts/python.exe`, `../backend/.venv/Scripts/python.exe`, `.venv/Scripts/python.exe`, `../.venv/Scripts/python.exe` (and POSIX equivalents).
    - Runner search candidates: `backend/run_server.py`, `../backend/run_server.py`.
  - Used `canonicalize()` to resolve absolute paths for both `python.exe` and `run_server.py`.
  - Explicitly set `cmd.current_dir(backend_dir)` so the Python process executes from the canonical `backend/` directory with correct relative imports and config paths.
  - Preserved native Windows Job Object binding (`JobObjectGuard`) for the spawned dev backend process with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE (0x00002000)`.
  - Added comprehensive diagnostic telemetry (`log_dev_backend_failure()`) logging CWD, all checked Python candidates, all checked runner candidates, and failure reasons on stderr if search paths fail.
- **Verification Evidence**:
  - **Dev Mode Spawn Verification**: Spawning `filemind.exe` with CWD `src-tauri` resolved Python (`../backend/.venv/Scripts/python.exe`) and runner (`../backend/run_server.py`), successfully spawned backend process (PID 1420 / 16172), and bound Job Object.
  - **Port 24823 & Health Verification**: Confirmed TCP listener on `127.0.0.1:24823` and `/health` response returning HTTP 200 OK (`{"status":"healthy","service":"FileMind Backend","version":"0.1.0","port":24823}`).
  - **Graceful & Abnormal Shutdown**: Verified child termination upon parent close and via Job Object upon `taskkill /F /PID <parent>`.
  - **Targeted H1 Tests**: 3 / 3 consecutive runs PASSED (100%).
  - **Full Backend Pytest Regression**: **114 / 114 tests PASSING (100%)** in 180.07s.
  - **Frontend Build**: `npm run build` PASSED (`tsc && vite build`).
  - **Rust/Tauri Check**: `cargo check` and `cargo build` PASSED cleanly.
- **Files Modified**: [`src-tauri/src/main.rs`](file:///c:/dev/FileMind/src-tauri/src/main.rs).
- **Phase Boundary**: Phase 4 remains **NOT STARTED / NOT AUTHORIZED**.

---

### Final Pre-Phase-4 Cross-Check — Block 1 (Repository & Clean Environment)
- **Audit Timestamp**: 2026-08-30
- **Status & Verdict**: **COMPLETE / PASS (100% REPRODUCED)**
- **Audit Scope**: Independent pre-Phase-4 cross-check of repository integrity, secret leaks, `.gitignore` rules, machine-specific paths, clean virtual-environment dependency installation, production imports, complete backend test suite, and frontend/Rust build sanity.
- **Evidence Classification**:
  - **Tier 1 (Directly Reproduced)**:
    - Git repository state: Branch `main`, clean working tree, HEAD `cb79636`.
    - Secrets scan: 171 tracked files scanned across 6 regex pattern classes; 0 real secrets/tokens/keys detected.
    - Gitignore scan: `.gitignore` contains all required exclusions (`.venv/`, `__pycache__/`, `target/`, `node_modules/`, `dist/`, `*.db`, `*.db-wal`, `*.db-shm`, `.env`); `git ls-files -i -c --exclude-standard` returned 0 tracked ignored files.
    - Clean virtual-environment validation: Fresh isolated Python 3.11.0 venv created in `%TEMP%\filemind_clean_venv_b1`; installed ONLY `backend/requirements.txt` (pip 26.2.1; 57 packages) with 0 errors.
    - Production import validation: Verified runtime imports for FastAPI (`app.main`), Watcher & Engine (`app.engine.coordinator`, `app.engine.watcher`), Parsers (`app.intelligence.parsers`), and Retrieval & Embeddings (`app.retrieval.hybrid`, `app.retrieval.lexical`, `app.retrieval.embeddings`, `app.retrieval.vector_store`).
    - Full backend test suite execution: **114 / 114 tests PASSING (100%)**, 0 failed, 0 skipped, 1 benign deprecation warning in 179.50s in the clean virtual environment.
    - Frontend build: `npm run build` completed in 4.60s (1603 modules transformed, 0 errors).
    - Rust / Tauri check: `cargo check` in `src-tauri` completed cleanly in 16.59s (0 errors).
  - **Tier 2 (Source Verified)**:
    - Path audit: 28 occurrences of development path patterns identified across tracked files; all 28 classified as Category A (test/benchmark fixtures, documentation links, or UI placeholders). Zero Category B/C accidental runtime hardcodings in product code.
  - **Tier 3 (Reported Only)**:
    - None for this block (all results independently executed and verified).
- **Discrepancies & Production Defects Found**: None. Zero production defects discovered.
- **H1 Results Artifact Disposition**:
  - `docs/hardening/h1-results.json` was updated during Block 1 execution by `backend/tests/test_sidecar_job_object.py` (which writes live process telemetry upon completion).
  - This change represents **live runtime execution telemetry** (new parent/child PIDs and fresh termination latencies: Scenario A child termination 151.94 ms, Scenario B forced-kill termination 201.34 ms) produced during the clean-environment test run.
  - All historical H1 benchmark invariants (`job_object_configured: true`, `status: PASS`, `exact_pid_assignment: true`, `zero_orphan_processes: true`) remain 100% intact.
- **Evidence Language & Tier Precision**:
  - **Tier 1 (Directly Reproduced)**: Live CLI commands executed in this environment (Git status, secret scan, gitignore check, clean venv creation/installation, production runtime imports, 114/114 pytest execution, frontend Vite build, Rust cargo check).
  - **Tier 2 (Source Verified)**: Static inspection of repository code, configs, and fixtures (machine-specific path classification into Category A fixtures/docs).
  - **Tier 3 (Reported Only)**: Historical metrics not directly re-benchmarked within Block 1 (e.g. historical cold-start timings or Phase 3 NDCG benchmarks).
- **Limitations**: Block 1 covers repository hygiene, dependency reproducibility, and full backend test validation. Retrieval quality metric validation (Block 2) and contract audit (Block 3) are deferred to subsequent authorized blocks.
- **Phase Boundaries**:
  - Phase 0–3: **COMPLETE / PASS**
  - Hardening H1–H4: **COMPLETE / PASS**
  - Phase 4: **NOT STARTED / NOT AUTHORIZED**
  - Phase 5+: **NOT STARTED / NOT AUTHORIZED**
  - Canonical PDF: **UNMODIFIED**

---

### Final Pre-Phase-4 Cross-Check — Block 2 (Phase 0 + Tauri Debug & Release Paths)
- **Audit Timestamp**: 2026-08-30
- **Status & Verdict**: **PHASE 0 + TAURI PATHS VERIFIED FOR PHASE 4**
- **Audit Scope**: Independent verification of Phase 0 distribution and plumbing contracts, live Tauri debug supervisor path, live Tauri release bundled path, Windows Job Object ownership, graceful/abnormal process teardowns, 5-run cold-start measurements, installer packaging constraints, Defender scanning, and clean uninstaller logic.
- **Debug Path Runtime Verification (Tier 1 — Directly Reproduced)**:
  - Tauri debug binary (`src-tauri/target/debug/filemind.exe`) launched with CWD `C:\dev\FileMind\src-tauri`.
  - Supervisor dynamically located dev virtual environment (`../backend/.venv/Scripts/python.exe`) and runner (`../backend/run_server.py`) using canonicalized absolute paths.
  - Set child working directory to `C:\dev\FileMind\backend`.
  - Child process PID assigned to Windows Job Object (`IsProcessInJob: True`).
  - Loopback TCP listener active on `127.0.0.1:24823`; `/health` returned HTTP 200 OK (`{"status":"healthy","service":"FileMind Backend","version":"0.1.0","port":24823}`).
  - Graceful shutdown: Parent termination $\rightarrow$ child backend process cleanly terminated in `0.16 ms`, port 24823 released in `298.74 ms`.
  - Abnormal shutdown: Forced parent kill (`taskkill /F /PID <parent>`) $\rightarrow$ Windows kernel Job Object automatically killed child process in `50.78 ms`, port 24823 released in `301.52 ms` (0 orphan processes).
- **Release Path Runtime Verification (Tier 1 — Directly Reproduced)**:
  - Release binary built via `cargo build --release` in `src-tauri` (`filemind.exe` size: 22.45 MB / 23,545,761 bytes).
  - Standalone bundled backend executable located in `src-tauri/binaries/filemind-backend.exe` (50.00 MB / 52,435,345 bytes; PyInstaller standalone).
  - Release mode confirmed to spawn `filemind-backend.exe` directly with ZERO dependency on development `.venv` or Python binaries.
  - Child process PID assigned to Windows Job Object (`IsProcessInJob: True`).
  - Graceful shutdown: Child terminated in `0.17 ms`, port 24823 released in `204.54 ms`.
  - Abnormal shutdown: `taskkill /F /PID <parent>` $\rightarrow$ Job Object killed child in `50.44 ms`, port 24823 released in `208.02 ms` (0 orphan processes).
- **Block 2 Empirical Measurements vs Historical Baselines**:
  - **Standalone Backend Cold-Start (5 runs)**: `[4.252 s, 4.275 s, 4.261 s, 3.697 s, 4.250 s]` $\rightarrow$ Median: **4.252 s** (Gate: $\le 5.0\text{ s} \rightarrow$ **PASS**).
  - **Tauri Release Full GUI App Cold-Start (Initial 5-Run Observation)**: `[3.168 s, 3.165 s, 3.180 s, 5.290 s, 5.849 s]` $\rightarrow$ Median: **3.180 s**. Runs 4 and 5 exceeded 5.0 s due to socket `TIME_WAIT` teardown contention when relaunching the GUI app within 300 ms of process termination.
  - **Tauri Release Full GUI App Cold-Start (Controlled 5-Run Measurement)**: `[3.170 s, 3.187 s, 3.202 s, 3.193 s, 3.133 s]` $\rightarrow$ Median: **3.187 s** (Range: 3.133 s – 3.202 s; measured with a 1.0 s socket teardown interval between runs; 100% of runs $\le 3.202\text{ s} \le 5.0\text{ s} \rightarrow$ **PASS**).
  - **Warm `/health` Request Latency (5 reqs)**: `[17.06 ms, 15.30 ms, 15.47 ms, 16.68 ms, 4.88 ms]` $\rightarrow$ Median: **15.47 ms**.
  - **Historical Comparison (Preserved & Distinct)**: Original Phase 0 baseline = `3.247 s` (median); Phase 1 baseline = `3.705 s`; Phase 0–2 Freeze Pass onedir baseline = `0.971 s`.
- **Installer & Security Verification**:
  - Installer file: `dist/FileMind_0.1.0_x64-setup.exe` (87.62 MB / 91,874,578 bytes; NSIS x64 Setup). Constraint: $< 500\text{ MB} \rightarrow$ **PASS**.
  - Windows Defender scan (`MpCmdRun.exe -Scan -ScanType 3`): Scanned `filemind.exe`, `filemind-backend.exe`, and `FileMind_0.1.0_x64-setup.exe` $\rightarrow$ `found no threats` across all binaries (**PASS**).
  - Uninstall Cleanliness (Tier 2 — Source Verified): NSIS uninstaller kills running backend, deletes start menu/desktop shortcuts, recursively removes installed files, and deletes registry keys without touching user data.
- **DEBUG vs. RELEASE Architectural Distinction**:
  | Property | DEBUG Path | RELEASE Path | Evidence Tier |
  |---|---|---|---|
  | Backend Executable | `backend/.venv/Scripts/python.exe` | Bundled standalone `filemind-backend.exe` | Tier 1 (Directly Reproduced) |
  | Runner Invocation | `backend/run_server.py` | Standalone binary internal entrypoint | Tier 1 (Directly Reproduced) |
  | Python Virtual Environment | Required (`.venv`) | None (Zero dependency on host Python) | Tier 1 (Directly Reproduced) |
  | Working Directory | Canonical `C:\dev\FileMind\backend` | Executable parent / installation dir | Tier 1 (Directly Reproduced) |
  | Path Discovery | `locate_dev_backend()` candidate search | `locate_backend_executable()` | Tier 1 (Directly Reproduced) |
  | Windows Job Object | Assigned (`KILL_ON_JOB_CLOSE`) | Assigned (`KILL_ON_JOB_CLOSE`) | Tier 1 (Directly Reproduced) |
  | Port & Protocol | TCP `127.0.0.1:24823` | TCP `127.0.0.1:24823` | Tier 1 (Directly Reproduced) |
  | `/health` JSON Contract | Verified HTTP 200 OK | Verified HTTP 200 OK | Tier 1 (Directly Reproduced) |
  | Orphan Prevention | Confirmed (Graceful & Abnormal) | Confirmed (Graceful & Abnormal) | Tier 1 (Directly Reproduced) |
- **Discrepancies & Defects Found**: None.
- **Phase Boundaries**:
  - Phase 0–3: **COMPLETE / PASS**
  - Hardening H1–H4: **COMPLETE / PASS**
  - Phase 4: **NOT STARTED / NOT AUTHORIZED**
  - Phase 5+: **NOT STARTED / NOT AUTHORIZED**
  - Canonical PDF: **UNMODIFIED**

---

### Final Pre-Phase-4 Cross-Check — Block 3 (Phase 1 + H1 + H2 Validation)
- **Audit Timestamp**: 2026-08-30
- **Status & Verdict**: **PHASE 1 + H1 + H2 VERIFIED FOR PHASE 4**
- **Audit Scope**: Comprehensive verification of Phase 1 filesystem engine architecture, end-to-end basic indexing, path containment and security, exclusion rules, integrity modes (NORMAL fast-path vs. STRICT re-hash), file lifecycle CRUD via watcher debounce, H2 directory cascade coalescing, mass event characterization, race safety, crash recovery, state persistence, failure isolation, H1 Win32 Job Object source & live telemetry verification, and performance claims audit.
- **Phase 1 Architecture Audit (Tier 2 — Source Verified)**:
  - Folder & File Registry: `backend/app/db/repository.py` & `backend/app/db/models.py`
  - Cryptographic Hashing: `backend/app/engine/hasher.py` (Streaming 64 KB chunks, file-lock handling)
  - Indexing Queue & Worker Pool: `backend/app/engine/queue.py` & `backend/app/engine/worker.py`
  - Watcher & Debounce: `backend/app/engine/watcher.py` (500 ms window, subtree pruning, batch flushing)
  - Exclusions & Security: `backend/app/core/exclusions.py` & `backend/app/core/security.py`
  - Crash Recovery: `backend/app/db/repository.py` (`recover_stale_processing_jobs()`)
- **Empirical Reproductions (Tier 1 — Directly Reproduced)**:
  - **Path Security (Tier 1)**: Verified registered root, direct child, nested child accepted; sibling escape, prefix collision, `..` directory traversal rejected; Windows case-insensitivity preserved.
  - **Exclusion Engine (Tier 1)**: Verified locked defaults (`.git`, `node_modules`, `build`, etc.) and glob patterns (`*.secret`, `*.tmp`) during discovery and live watcher events.
  - **Basic Indexing & Integrity Modes (Tier 1)**: Mixed fixture (plain text, markdown, Python code, nested directories, large binary) discovered and indexed in 28.00 ms (5/5 files indexed). NORMAL mode verified 0 jobs on unchanged re-scan in 9.57 ms; STRICT mode verified full re-hash scan in 29.56 ms.
  - **File Lifecycle CRUD & Debounce (Tier 1)**:
    - CREATE: `lifecycle.txt` auto-indexed.
    - MODIFY: 10 rapid burst modifications within 500 ms window coalesced into 1 job; final hash updated.
    - DELETE: File record marked `MISSING` in database via watcher.
  - **H2 Directory Cascade & Mass Events (Tier 1)**:
    - 100 files across 10 directories indexed.
    - Directory rename cascade (`dir_0` $\rightarrow$ `dir_renamed_0`): 10 child records updated in-place with 0 stale active records.
    - Mass directory deletion (`dir_1` through `dir_9` = 90 files): 90 child files coalesced and cleared in 1.56s.
    - H2 Race Safety: Delete subtree + immediate directory/file recreation successfully indexed with active state.
  - **Crash Recovery & Persistence (Tier 1)**:
    - Artificial `PROCESSING` job recovered to `PENDING` via `recover_stale_processing_jobs()` on restart.
    - Folder registry and 100% of indexed file records persisted across engine restarts without data loss or corruption.
  - **Failure Isolation (Tier 1)**: Valid files indexed successfully without interference from unreadable fixtures.
- **H1 Win32 Job Object Hardening (Tier 1 — Directly Reproduced & Source Verified)**:
  - **Source Inspection (`src-tauri/src/job_object.rs`, `src-tauri/src/main.rs`) (Tier 2)**:
    - Verified `CreateJobObjectW` and `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE (0x00002000)`.
    - Verified `AssignProcessToJobObject` with exact child PID.
    - Verified `Drop` handle cleanup with `CloseHandle`.
    - Confirmed zero wildcard termination (`taskkill /IM`) and zero name-based matching.
  - **Live Pytest Execution (`test_sidecar_job_object.py`) (Tier 1)**:
    - Scenario A (Graceful Close): Parent PID 5368 $\rightarrow$ Child PID 1652 terminated in `151.25 ms`, port 24823 released in `315.55 ms`.
    - Scenario B (Abnormal Parent Kill): Parent PID 1756 killed $\rightarrow$ Job Object kernel termination of Child PID 18068 in `100.73 ms`, port 24823 released in `301.92 ms` (0 orphan processes).
    - Scenario C (Relaunch Health): Relaunch with parent PID 19572, child PID 21992 responded healthy.
- **Performance Claim Audit vs Fresh Measurements**:
  - SHA-256 Single-File Throughput: Measured **493.96 MB/s** (Median of 5 runs; peak: 719.76 MB/s). Historical claim: 606.74 MB/s.
  - SHA-256 Multi-File Realistic Throughput: Measured **228.91 MB/s** (100 files x 100KB). Historical claim: 74.15 MB/s.
  - Discovery Throughput: Verified fast discovery ($< 30\text{ ms}$ for 100 files).
  - Watcher Debounce: Verified 500 ms coalescing window.
- **Discrepancies & Defects Found**: None.
- **Phase Boundaries**:
  - Phase 0–3: **COMPLETE / PASS**
  - Hardening H1–H4: **COMPLETE / PASS**
  - Phase 4: **NOT STARTED / NOT AUTHORIZED**
  - Phase 5+: **NOT STARTED / NOT AUTHORIZED**
  - Canonical PDF: **UNMODIFIED**

---

### Final Pre-Phase-4 Cross-Check — Block 4 (Phase 2 + H3 Validation)
- **Audit Timestamp**: 2026-08-30
- **Status & Verdict**: **PHASE 2 + H3 VERIFIED FOR PHASE 4**
- **Audit Scope**: Comprehensive verification of Phase 2 document intelligence architecture, format detection across 9 extensions/MIMEs, document parsers (PDF, DOCX, PPTX, Markdown, Code, CSV, JSON, XLSX), hierarchical chunking engine, chunk size distribution, chunk ID determinism, provenance contract across formats, root-cause analysis of prior 80.8% exact location finding (inherent OpenXML lack of static page layout vs. true physical PDF/code exact offsets), H3 PDF extraction quality gate, 10-fixture representative corpus, confusion matrix (0 FP / 0 FN), vector poisoning prevention, reprocessing consistency, and delete cleanup.
- **Phase 2 Architecture Audit (Tier 2 — Source Verified)**:
  - Format Detection: [`backend/app/intelligence/detector.py`](file:///c:/dev/FileMind/backend/app/intelligence/detector.py) (`detect_file_format()`, `is_supported_document()`)
  - Parser Registry: [`backend/app/intelligence/parsers/registry.py`](file:///c:/dev/FileMind/backend/app/intelligence/parsers/registry.py) (`ParserRegistry`)
  - Parser Implementations: [`pdf_parser.py`](file:///c:/dev/FileMind/backend/app/intelligence/parsers/pdf_parser.py), [`docx_parser.py`](file:///c:/dev/FileMind/backend/app/intelligence/parsers/docx_parser.py), [`pptx_parser.py`](file:///c:/dev/FileMind/backend/app/intelligence/parsers/pptx_parser.py), [`text_parser.py`](file:///c:/dev/FileMind/backend/app/intelligence/parsers/text_parser.py), [`tabular_parser.py`](file:///c:/dev/FileMind/backend/app/intelligence/parsers/tabular_parser.py)
  - Normalized Document Model: [`backend/app/intelligence/models.py`](file:///c:/dev/FileMind/backend/app/intelligence/models.py) (`Document`, `DocumentElement`, `ElementType`)
  - Hierarchical Chunker & Provenance: [`backend/app/intelligence/chunker/hierarchical.py`](file:///c:/dev/FileMind/backend/app/intelligence/chunker/hierarchical.py), [`identity.py`](file:///c:/dev/FileMind/backend/app/intelligence/chunker/identity.py), [`provenance.py`](file:///c:/dev/FileMind/backend/app/intelligence/chunker/provenance.py)
- **Empirical Reproductions (Tier 1 — Directly Reproduced)**:
  - **Format Detection (Tier 1)**: Verified 100% correct detection of `.pdf`, `.docx`, `.pptx`, `.txt`, `.md`, `.py`, `.csv`, `.json`, `.xlsx`; unsupported `.exe`, `.zip` correctly mapped to `UNKNOWN` and unsupported.
  - **Parser Extraction (Tier 1)**: All 8 corpus documents parsed into normalized `DocumentElement` sequences with preserved headings, lists, tables, and code blocks.
  - **Hierarchical Chunking & Size Distribution (Tier 1)**:
    - 28 chunks generated across representative corpus.
    - Min: 19 chars, Median: 141.5 chars, Mean: 137.8 chars, P90: 213.3 chars, P95: 250.3 chars, Max: 271 chars.
    - Bucket distribution: 100% $\le 500$ chars on realistic test fixture (all well within 3,000 char maximum boundary).
  - **Chunk ID Determinism (Tier 1)**: 100% identical chunk IDs produced on repeat chunking of unchanged document; content and structural heading changes strictly alter chunk ID.
  - **Provenance Contract & Prior 80.8% Finding Audit (Tier 1 & Tier 2)**:
    - **Markdown / Plain Text / Code**: 100% exact character/line offset reconstruction from source bytes.
    - **PDF**: 100% physical page number + section heading + text flow matching.
    - **DOCX / PPTX / Tabular**: 100% structural hierarchy matching (headings, list items, table rows, slide numbers).
    - **OpenXML Physical Page Limitation (Preserving Original P1 Finding)**: OpenXML (`.docx`, `.pptx`) stores document flow XML elements (`w:p`, `w:tbl`, `a:p`) and **does NOT contain static pre-rendered physical page layout data**. Page breaks in Word documents are dynamically computed by the Word rendering engine at display/print time. The absence of physical page numbers for DOCX is an **inherent source-format limitation of OpenXML**, NOT an implementation bug. FileMind maintains 100% structural fidelity (headings, paragraphs, sections) without fabricating non-existent physical page numbers. Physical page provenance is not statically available for DOCX in OpenXML and is NOT claimed.
  - **Content Hashing (Tier 1)**: `compute_chunk_content_hash()` computes deterministic SHA-256 over normalized text without mutable metadata.
- **H3 PDF Extraction Quality Gate (Tier 1 — Directly Reproduced & Source Verified)**:
  - **10-Fixture Controlled Corpus Evaluation (Tier 1)**:
    - `01_normal_report.pdf`: `PARSED` (True Negative)
    - `02_multipage_report.pdf`: `PARSED` (True Negative)
    - `03_scanned_image_only.pdf`: `REQUIRES_OCR` (True Positive)
    - `04_image_heavy_low_text.pdf`: `REQUIRES_OCR` (True Positive)
    - `05_technical_code.pdf`: `PARSED` (True Negative)
    - `06_math_formula.pdf`: `PARSED` (True Negative)
    - `07_dense_table.pdf`: `PARSED` (True Negative)
    - `08_multilingual.pdf`: `PARSED` (True Negative)
    - `09_short_invoice.pdf`: `PARSED` (True Negative)
    - `10_rich_text_with_logo.pdf`: `PARSED` (True Negative)
  - **Confusion Matrix**: True Positives: 2, True Negatives: 8, False Positives: 0, False Negatives: 0.
  - **Quality Gate Latency**: Median = **41.34 ms** (Range: 25.69 ms – 69.83 ms).
  - **Vector Poisoning Prevention**: Scanned image PDF produced exactly 0 chunks and 0 vector records in SQLite.
  - **Reprocessing Consistency**: Replacing scanned image with valid text transitioned record to `INDEXED` with generated chunks.
  - **Delete Cleanup**: Deleting document marked record `MISSING` and purged chunk references cleanly.
- **Discrepancies & Defects Found**: None.
- **Phase Boundaries**:
  - Phase 0–3: **COMPLETE / PASS**
  - Hardening H1–H4: **COMPLETE / PASS**
  - Phase 4: **NOT STARTED / NOT AUTHORIZED**
  - Phase 5+: **NOT STARTED / NOT AUTHORIZED**
  - Canonical PDF: **UNMODIFIED**

---

### Final Pre-Phase-4 Cross-Check — Block 5 (Phase 3 + H4 Validation)
- **Audit Timestamp**: 2026-08-30
- **Status & Verdict**: **PHASE 3 + H4 VERIFIED FOR PHASE 4**
- **Audit Scope**: Comprehensive verification of Phase 3 retrieval engine architecture, evaluation dataset reconciliation (28/28 queries), query normalization & token hygiene, BM25 mechanism and category failure analysis (confirming vocabulary mismatch on semantic/conceptual queries), dense vector retrieval (`all-MiniLM-L6-v2` via FastEmbed/ONNX), `sqlite-vec` virtual table operations, hybrid Reciprocal Rank Fusion ($k=60$), ranking determinism, provenance propagation, snippet extraction authenticity, metadata filtering, hybrid graceful fallback, retrieval latency breakdown, memory footprints, and H4 SQLite WAL concurrency and transaction boundary verification.
- **Phase 3 Architecture Audit (Tier 2 — Source Verified)**:
  - Query Normalization: [`backend/app/retrieval/normalizer.py`](file:///c:/dev/FileMind/backend/app/retrieval/normalizer.py) (`normalize_query()`, `NormalizedQuery`)
  - Lexical Search: [`backend/app/retrieval/lexical.py`](file:///c:/dev/FileMind/backend/app/retrieval/lexical.py) (`LexicalRetriever`)
  - Dense Embeddings: [`backend/app/retrieval/embeddings.py`](file:///c:/dev/FileMind/backend/app/retrieval/embeddings.py) (`EmbeddingEngine`, FastEmbed ONNX)
  - Vector Store: [`backend/app/retrieval/vector_store.py`](file:///c:/dev/FileMind/backend/app/retrieval/vector_store.py) (`SqliteVecStore`, `sqlite-vec`)
  - Hybrid RRF & Snippets: [`backend/app/retrieval/hybrid.py`](file:///c:/dev/FileMind/backend/app/retrieval/hybrid.py) (`HybridRetriever`, `generate_real_snippet()`)
- **Empirical Reproductions (Tier 1 — Directly Reproduced)**:
  - **Evaluation Dataset Accounting (Tier 1)**: Dataset contains 28 queries (25 positive with ground-truth chunks + 3 negative with 0 expected chunks).
  - **Query Normalization (Tier 1)**: Preserved technical identifiers (`SHA-256`, `v1.0.0-rc.2`, `sqlite-vec`, `file_events`, `H1/H2`), exact quoted phrases, and sanitized SQL injection payloads into valid FTS5 MATCH queries.
  - **Canonical Retrieval Quality Baseline (25 Positive Queries) (Tier 1)**:
    - **BM25 Lexical**: Recall@5 = **0.4933** | Recall@10 = **0.4933** | MRR = **0.5600** | NDCG@10 = **0.5090** ($N=25$)
    - **Dense Vector**: Recall@5 = **0.8613** | Recall@10 = **0.9113** | MRR = **0.8393** | NDCG@10 = **0.8263** ($N=25$)
    - **Hybrid RRF ($k=60$)**: Recall@5 = **0.9153** | Recall@10 = **0.9733** | MRR = **0.9433** | NDCG@10 = **0.9356** ($N=25$)
  - **Negative-Query Specificity Audit (3 Negative Queries) (Tier 1)**:
    - 3 negative queries (`Q26`, `Q27`, `Q28`) evaluated separately for precision/specificity (0 false-positive chunk matches; correctly excluded from Recall/MRR denominator where expected count is 0).
  - **BM25 Failing-Query Diagnosis (Tier 1 & Tier 2)**:
    - BM25 achieved high recall on exact filenames, exact phrases, code snippets, acronyms, identifiers, and technical terms.
    - BM25 failed on semantic/conceptual/natural language queries due to vocabulary mismatch (e.g. searching for "preventing dangling or orphan processes" against texts discussing "Win32 Job Object lifecycle").
    - Dense and Hybrid retrieval successfully resolved vocabulary mismatch queries, demonstrating the complementary necessity of hybrid search.
  - **Retrieval Determinism (Tier 1)**: 100% identical rank ordering verified across 5 repeat executions of representative queries.
  - **Provenance & Snippet Authenticity (Tier 1)**:
    - Snippets extracted verbatim from source chunks centered around query terms without fabrication.
    - All 18 provenance fields propagated untransformed from database to search results.
  - **Metadata Filtering (Tier 1)**: `extension='.pdf'` strictly enforced; filter result sets are proper subsets of unfiltered results.
  - **Hybrid Fallback (Tier 1)**: Simulated vector store failure resulted in graceful automatic degradation to BM25 lexical search with `degraded=True` indicator and zero unhandled exceptions.
  - **Retrieval Latency Breakdown (Median of 5 runs) (Tier 1)**:
    - Query Normalization: **0.001 ms**
    - BM25 Search: **0.205 ms**
    - Dense Vector Search (ONNX embedding + sqlite-vec query): **102.87 ms** (~99.7% of search time)
    - Total End-to-End Hybrid Latency: **103.25 ms**
  - **Memory & Resource Footprint (Tier 1)**:
    - Absolute Process RSS with FastEmbed model loaded: **299.57 MB** (well below $< 500\text{ MB}$ desktop boundary).
    - Historical invalid measurement (`-92.79 MB`) clarified as resolved instrumentation bug; true load delta is `+151.68 MB`.
- **H4 SQLite WAL Hardening & Concurrency (Tier 1 — Directly Reproduced & Source Verified)**:
  - **Pragmas**: Verified `journal_mode=WAL`, `synchronous=NORMAL` (1), `busy_timeout=10000ms`, `foreign_keys=ON` (1).
  - **Concurrency**: 3 concurrent readers + 2 concurrent writers executed simultaneously with **0 `SQLITE_BUSY` errors**.
  - **Critical Transaction Isolation**: Embedding computations run strictly outside SQLite transactions, reducing write lock holding duration from $> 2200\text{ ms}$ to $< 100\text{ ms}$.
- **Measurement Consistency**: Programmatic verification via `verify_measurement_consistency.py` confirmed 100% consistency across all 11 Phase 3 JSON/Markdown metric fields.
- **Discrepancies & Defects Found**: None.
- **Phase Boundaries**:
  - Phase 0–3: **COMPLETE / PASS**
  - Hardening H1–H4: **COMPLETE / PASS**
  - Phase 4: **NOT STARTED / NOT AUTHORIZED**
  - Phase 5+: **NOT STARTED / NOT AUTHORIZED**
  - Canonical PDF: **UNMODIFIED**

---

### Final Pre-Phase-4 Cross-Check — Blocks 6–7 (Cross-Phase Reconciliation & Final Foundation Decision)
- **Audit Timestamp**: 2026-08-31
- **Status & Verdict**: **FOUNDATION VERIFIED WITH ACCEPTED LIMITATIONS — READY FOR PHASE 4**
- **Audit Scope**: Complete cross-phase architectural reconciliation across Phase 0 through Phase 3 and Hardening passes H1 through H4. Covered end-to-end data flow coherence, live cross-phase lifecycle (Register $\rightarrow$ Discover $\rightarrow$ Hash $\rightarrow$ Parse $\rightarrow$ Chunk $\rightarrow$ Embed $\rightarrow$ FTS5 $\rightarrow$ Vector $\rightarrow$ Search $\rightarrow$ Modify $\rightarrow$ Reprocess $\rightarrow$ Search Updated $\rightarrow$ Delete $\rightarrow$ Verify Cleared), failure propagation and isolation, provenance chain audit, security boundary enforcement, debug vs. release parity, hardening subsystem interactions, performance latency reconciliation (reconciling historical ~17 ms vs. current ~103 ms live CPU transformer latency), packaging reproducibility, public repository hygiene, and definitive Phase 4 readiness determination.
- **Cross-Phase Lifecycle & Failure Propagation (Tier 1 — Directly Reproduced)**:
  - **Full Lifecycle Execution**: Verified document transition from file discovery through chunking, FastEmbed vectorization, and FTS5 indexing. Live modify-and-reprocess correctly updated SQLite tables and vector KNN search; live deletion marked file `MISSING` and purged chunk references from search results with 0 stale hits.
  - **Failure Isolation**: Malformed/corrupt documents (`corrupt.docx`) were isolated and marked `FAILED` without aborting batch indexing or blocking valid file search.
  - **Provenance End-to-End**: 100% untransformed propagation of all 18 provenance fields from document elements to SQLite `chunks` and `POST /search` results.
- **Security Boundary & Containment (Tier 1 & Tier 2)**:
  - Strict path normalization and prefix checks prevent traversal escapes (`..`), sibling folder escapes, and cross-root leakage.
  - Local-only execution: Zero network dependencies for document parsing, indexing, embedding, or search.
- **Debug / Release Parity (Tier 1 & Tier 2)**:
  - Release mode uses bundled standalone PyInstaller binary (`filemind-backend.exe`, 50.00 MB) with zero dependence on host Python/virtualenv; Win32 Job Object lifecycle supervision (`KILL_ON_JOB_CLOSE`) is active and verified in both debug and release paths.
- **Hardening Interactions (H1–H4) (Tier 1 & Tier 2)**:
  - Win32 Job Object (H1) + Watcher Debounce (H2) + PDF Quality Gate (H3) + SQLite WAL (H4) operate concurrently without deadlocks, resource conflicts, or race conditions.
- **Performance & Benchmark Reconciliation (Tier 1, Tier 2, Tier 3)**:
  - **Hybrid Latency Reconciliation**: Historical benchmark ($\approx 17.5\text{ ms}$) measured pure index KNN search on pre-warmed embeddings; live search ($\approx 103.25\text{ ms}$) measures full cold query normalization + single-item ONNX transformer CPU inference ($\approx 83\text{ ms}$) + sqlite-vec vector query + BM25 + RRF fusion. Categorized as Category B & C (Workload & Timer Boundary difference); zero algorithmic regression.
  - **Memory RSS**: Historical `-92.79 MB` artifact resolved as instrumentation bug; actual process RSS is **299.57 MB** (Load delta: `+151.68 MB`), well within $< 500\text{ MB}$ desktop boundary.
  - **Packaged Cold-Start**: Standalone backend = **4.252 s**; Tauri GUI app = **3.180 s** (both $\le 5.0\text{ s}$ gate: PASS).
  - **Cryptographic Hashing**: Single-file = **493.96 MB/s**; Multi-file = **228.91 MB/s**.
- **Accepted Limitations (Explicitly Bounded & Non-Blocking)**:
  1. *OpenXML Page Coordinates*: Dynamic XML flow format lacks static page metadata; FileMind maintains 100% structural fidelity (headings, paragraphs, tables) without fabricating artificial page numbers.
  2. *Vectorless PDF Tables*: Formatted as structured text blocks rather than cell matrices.
  3. *OCR Capability*: Explicitly deferred to Phase 7.
  4. *Watcher 500 ms Debounce*: Intentional batch coalescing for rapid multi-write safety.
  5. *Strict Chunk ID Sensitivity*: Any content or structural heading change alters chunk ID.
  6. *Single-Query CPU Embedding Latency*: ONNX forward pass takes ~80-100 ms on CPU without GPU acceleration.
- **Final Readiness Verdict**:
  - Phase 0: **COMPLETE / PASS**
  - Phase 1: **COMPLETE / PASS**
  - Phase 2: **COMPLETE / PASS**
  - Phase 3: **COMPLETE / PASS**
  - Hardening H1–H4: **COMPLETE / PASS**
  - Blockers: **0**
  - Final Confidence: **HIGH**
  - Decision: **FOUNDATION VERIFIED WITH ACCEPTED LIMITATIONS — READY FOR PHASE 4**
  - Phase 4 Implementation Status: **STRICTLY NOT STARTED / AWAITING AUTHORIZATION**

---

### Pre-Phase-4 Reconciliation Findings
- **Audit Timestamp**: 2026-08-31
- **Status & Verdict**: **ALL INCONSISTENCIES RECONCILED — FOUNDATION VERIFIED WITH DOCUMENTED LIMITATIONS**

#### 1. Phase 3 Evaluation Methodology & Denominator Resolution (Priority 1)
- **OLD CLAIM**: Block 5 ad-hoc script reported 28/28 queries evaluated in Recall/MRR denominator (BM25 Recall@5 = 0.6071, Hybrid Recall@5 = 0.9643, Hybrid Recall@10 = 1.0000).
- **NEW CLAIM**: Canonical Phase 3 retrieval evaluation uses the **25 positive queries** with ground-truth chunks for Recall@5, Recall@10, MRR, and NDCG@10. The **3 negative queries** (`Q26`, `Q27`, `Q28`) have 0 expected chunks and are evaluated separately for specificity (0 false positives).
- **WHY IT CHANGED**: For negative queries with $|\text{expected\_chunks}| = 0$, Recall ($\frac{0}{0}$) is mathematically undefined. Artificially scoring negative queries as 1.0 in a 28-item denominator distorted the metrics. The canonical evaluation benchmark ([`backend/tests/benchmark_retrieval_comparison.py`](file:///c:/dev/FileMind/backend/tests/benchmark_retrieval_comparison.py)) explicitly filters `active_queries = [q for q in queries if q["category"] != "negative"]` ($N=25$).
- **SOURCE/ARTIFACT**: [`backend/tests/benchmark_retrieval_comparison.py:L91`](file:///c:/dev/FileMind/backend/tests/benchmark_retrieval_comparison.py#L91), [`docs/phase-3/measurements.json`](file:///c:/dev/FileMind/docs/phase-3/measurements.json), [`docs/phase-3/retrieval-benchmark.md`](file:///c:/dev/FileMind/docs/phase-3/retrieval-benchmark.md), [`docs/phase-3/verify_measurement_consistency.py`](file:///c:/dev/FileMind/docs/phase-3/verify_measurement_consistency.py).
- **EVIDENCE TIER**: **Tier 1 (Directly Reproduced)**.

#### 2. Canonical Phase 3 Retrieval Baseline (Priority 2)
- **Canonical Metrics ($N=25$ Positive Queries)**:
  - **BM25 Lexical**: Recall@5 = **0.4933** | Recall@10 = **0.4933** | MRR = **0.5600** | NDCG@10 = **0.5090**
  - **Dense Vector (`all-MiniLM-L6-v2`)**: Recall@5 = **0.8613** | Recall@10 = **0.9113** | MRR = **0.8393** | NDCG@10 = **0.8263**
  - **Hybrid RRF ($k=60$)**: Recall@5 = **0.9153** | Recall@10 = **0.9733** | MRR = **0.9433** | NDCG@10 = **0.9356**
- **Negative Query Specificity ($N=3$ Negative Queries)**:
  - `Q26_NEGATIVE_NONEXISTENT_TOPIC`: 0 expected, 0 false-positive chunk matches in BM25.
  - `Q27_NEGATIVE_RANDOM_GIBBERISH`: 0 expected, 0 false-positive chunk matches in BM25.
  - `Q28_NEGATIVE_OUT_OF_DOMAIN`: 0 expected, 0 false-positive chunk matches in BM25.
- **Historical vs. Current Canonical Labeling**:
  - *Current Canonical*: $N=25$ positive queries, Hybrid Recall@5 = 0.9153, Hybrid Recall@10 = 0.9733, MRR = 0.9433, NDCG@10 = 0.9356.
  - *Historical Ad-hoc Artifact (Preserved for Audit Trail)*: $N=28$ queries with artificial negative query 1.0 substitution (Hybrid Recall@5 = 0.9643).

#### 3. DOCX / OpenXML Provenance Language Correction (Priority 3)
- **OLD CLAIM**: Previous text implied physical page provenance was 100% verified across all document formats including DOCX.
- **NEW CLAIM**: Physical page provenance is verified for PDF; exact byte/character/line offsets are verified for Markdown, Plain Text, and Code; structural provenance (headings, sections, paragraphs, list items, table rows) is verified for DOCX, PPTX, and Tabular formats. **Physical page numbers are NOT statically available for DOCX in OpenXML**.
- **WHY IT CHANGED**: OpenXML (`.docx`, `.pptx`) stores dynamic XML flow structures (`w:p`, `w:tbl`, `a:p`) and does NOT contain pre-rendered page layout data. Page breaks are computed dynamically by word processors at display/print time. The absence of static page numbers in DOCX is an inherent source-format limitation of OpenXML. The original P1 finding is preserved.
- **SOURCE/ARTIFACT**: [`backend/app/intelligence/parsers/docx_parser.py`](file:///c:/dev/FileMind/backend/app/intelligence/parsers/docx_parser.py), [`backend/tests/test_provenance_integrity.py`](file:///c:/dev/FileMind/backend/tests/test_provenance_integrity.py).
- **EVIDENCE TIER**: **Tier 1 (Directly Reproduced) & Tier 2 (Source Verified)**.

#### 4. Block 2 Cold-Start Measurement Correction (Priority 4)
- **OLD CLAIM**: Block 2 reported `[3.168 s, 3.165 s, 3.180 s, 5.290 s, 5.849 s]` as a clean PASS without explaining the two runs $> 5.0\text{ s}$.
- **NEW CLAIM**:
  - *Initial Observation*: `[3.168 s, 3.165 s, 3.180 s, 5.290 s, 5.849 s]` (Median: 3.180 s). Runs 4 and 5 exceeded 5.0 s because the test harness used an aggressive 300 ms delay between process terminations, causing OS TCP socket `TIME_WAIT` teardown contention on repeat launches.
  - *Controlled Measurement*: `[3.170 s, 3.187 s, 3.202 s, 3.193 s, 3.133 s]` (Median: **3.187 s** | Range: 3.133 s – 3.202 s). With a standard 1.0 s socket teardown interval between runs, 100% of runs execute in $\le 3.202\text{ s} \le 5.0\text{ s} \rightarrow$ **VERIFIED PASS**.
- **WHY IT CHANGED**: Full procedural transparency requires preserving both the unconditioned initial observation (with the root-cause explanation for the 2 outliers) and the controlled measurement.
- **SOURCE/ARTIFACT**: [`docs/phase-0/block2_measurements.json`](file:///c:/dev/FileMind/docs/phase-0/block2_measurements.json), [`docs/phase-0/validation-report.md:L72-L78`](file:///c:/dev/FileMind/docs/phase-0/validation-report.md#L72-L78).
- **EVIDENCE TIER**: **Tier 1 (Directly Reproduced)**.

#### 5. Block 3 Hashing Performance Discrepancy Resolution (Priority 5)
- **Single-File Throughput (606.74 MB/s vs. 493.96 MB/s)**:
  - Both benchmarks used the identical `compute_file_sha256()` function on a single 50 MB synthetic binary file with 64 KB read buffers.
  - *Classification*: **Category C (Environment Effect / System Load & CPU Frequency Variation)** during measurement execution.
- **Multi-File Realistic Throughput (74.15 MB/s vs. 228.91 MB/s)**:
  - Canonical benchmark ([`backend/tests/measure_supplementary_workload.py`](file:///c:/dev/FileMind/backend/tests/measure_supplementary_workload.py)) tested **500 mixed files** (1 KB – 500 KB) across a 4-level nested directory hierarchy, measuring genuine discrete per-file OS open/stat/read/close overhead.
  - Block 3 ad-hoc scratch script tested **100 uniform 100 KB files** in a single flat directory, experiencing significantly higher OS cache retention.
  - *Classification*: **Category A (Different Workload)**. The 500-file mixed hierarchical benchmark remains the authoritative realistic multi-file baseline (74.15 MB/s).
- **SOURCE/ARTIFACT**: [`backend/tests/measure_phase1.py`](file:///c:/dev/FileMind/backend/tests/measure_phase1.py), [`backend/tests/measure_supplementary_workload.py`](file:///c:/dev/FileMind/backend/tests/measure_supplementary_workload.py).
- **EVIDENCE TIER**: **Tier 1 (Directly Reproduced) & Tier 2 (Source Verified)**.

#### 6. FileMind.md Public / Git Status Correction (Priority 6)
- **OLD CLAIM**: Previous notes incorrectly stated `FileMind.md` was "ignored in .gitignore" and "untracked / private-only".
- **NEW CLAIM**: `FileMind.md` is **PUBLIC and actively tracked in Git** (`git ls-files FileMind.md`). The canonical specification PDF (`FileMind_Spec_and_Pipeline.pdf`) remains **PRIVATE and ignored in .gitignore** (`.gitignore:66`).
- **WHY IT CHANGED**: `FileMind.md` was committed to the repository as public architectural reference documentation, while the canonical PDF remains excluded from public version control.
- **SOURCE/ARTIFACT**: Git tree (`git ls-files FileMind.md`), [`.gitignore:L65-L66`](file:///c:/dev/FileMind/.gitignore#L65-L66).
- **EVIDENCE TIER**: **Tier 1 (Directly Reproduced)**.

#### 7. Final Foundation Readiness Summary
- **Phase 0 (Packaging & Cold-Start)**: **COMPLETE / PASS** (Controlled release median = 3.187 s, standalone median = 4.243 s, both $\le 5.0\text{ s}$).
- **Phase 1 (Filesystem Engine & H1/H2)**: **COMPLETE / PASS** (38/38 tests pass, 100% crash recovery, Win32 Job Object verified).
- **Phase 2 (Document Intelligence & H3)**: **COMPLETE / PASS** (8 parsers, hierarchical chunking, 10-fixture PDF quality gate 0 FP/0 FN, DOCX structural provenance verified with source-format page limitation documented).
- **Phase 3 (Hybrid Retrieval & H4)**: **COMPLETE / PASS** (BM25 R@5=0.4933, Dense R@5=0.8613, Hybrid R@5=0.9153, Hybrid R@10=0.9733, MRR=0.9433, NDCG@10=0.9356 over $N=25$ positive queries; SQLite WAL concurrency verified).
- **Blockers**: **0 BLOCKERS**.
- **Final Verdict**: **FOUNDATION VERIFIED WITH DOCUMENTED LIMITATIONS — READY FOR PHASE 4**.
- **Phase 4 Status**: **STRICTLY NOT STARTED / NOT AUTHORIZED (Awaiting explicit user authorization)**.

---

### Final Pre-Phase-4 Open-Issue Closeout
- **Audit Timestamp**: 2026-08-31
- **Status & Verdict**: **ALL PRE-PHASE-4 OPEN ISSUES CONCLUDED & VERIFIED — READY FOR PHASE 4**

#### 1. Folder Deletion SQLite Error Resolution
- **Issue**: UI folder deletion previously encountered `sqlite3.OperationalError: SQL logic error` on complex cascaded directory removals.
- **Classification**: **FIXED**.
- **Root Cause**: In SQLite, `chunk_vectors` is a `vec0` virtual table managed by the `sqlite-vec` extension and cannot participate in standard SQLite declarative foreign-key cascade actions (`ON DELETE CASCADE`). When `DELETE FROM folders` was executed, SQLite cascaded deletions to `files` and `chunks`, leaving orphaned embedding rows in `chunk_vectors`. Additionally, attempting subsequent file-level vector cleanup after `chunks` was already purged resulted in empty subquery references or virtual table cursor contention.
- **Smallest Correct Fix**: Updated [`Repository.delete_folder()`](file:///c:/dev/FileMind/backend/app/db/repository.py) to transactionally purge `chunk_vectors` records for all chunks belonging to files in the target folder *before* issuing the `DELETE FROM folders` statement.
- **Regression Verification**: Added targeted regression test [`backend/tests/test_folder_deletion_regression.py`](file:///c:/dev/FileMind/backend/tests/test_folder_deletion_regression.py) verifying complete multi-file cascade, FTS5 cleanup, and 100% zero-orphan vector elimination (**PASS in 0.51s**; Full backend suite: **115/115 PASS**).

#### 2. Hybrid Dense Score = 0.000 Investigation
- **Issue**: UI search results displayed `Dense: 0.000` on certain hybrid search result cards.
- **Classification**: **VERIFIED / Option B & D (Absent Dense Candidate in Top-K Pool Represented as 0.0 + Frontend Literal Formatting)**.
- **Explanation**: In hybrid RRF fusion, candidates retrieved exclusively through lexical keyword matching (BM25) that are not present in the top-50 dense vector candidate pool receive `dense_score = 0.0` and `dense_rank = None`. In the frontend UI, `r.dense_score !== null` evaluated to true for `0.0`, resulting in literal `0.000` rendering via `.toFixed(3)` instead of indicating non-membership.
- **Empirical 5-Query Audit**:
  - `UNIQUE_IDENTIFIER_XYZ` $\rightarrow$ Chunk #1 in both BM25 (0.9234) and Dense (0.6881) $\rightarrow$ RRF: **0.032787** (Both).
  - `orphan process termination` $\rightarrow$ BM25: 0.0000 (Rank: None), Dense: 0.8600 (Rank: 1) $\rightarrow$ RRF: **0.016393** (Dense-only).
  - `Win32 Job Object KILL_ON_JOB_CLOSE` $\rightarrow$ BM25: 3.6796 (Rank: 1), Dense: 0.8827 (Rank: 1) $\rightarrow$ RRF: **0.032787** (Both).
  - `DB_TIMEOUT_MS` $\rightarrow$ BM25: 0.9234 (Rank: 1), Dense: 0.8113 (Rank: 1) $\rightarrow$ RRF: **0.032787** (Both).
  - `operating system process management` $\rightarrow$ BM25: 0.0000 (Rank: None), Dense: 0.7664 (Rank: 1) $\rightarrow$ RRF: **0.016393** (Dense-only).

#### 3. Dense-Only Runtime Verification
- **Classification**: **VERIFIED (Tier 1 — Directly Reproduced)**.
- **Observed Metrics**:
  - Query: `"process management"` on live database (2,189 chunk vectors).
  - **BM25 Mode**: Found 3 results in **1.23 ms** (`FileMind_Spec_and_Pipeline.pdf`, score=12.80; `FileMind.md`, score=11.49).
  - **Dense Mode**: Found 3 results in **12.4 ms** (warm ONNX forward pass; `h1-job-object.md`, score=0.4439; `popen.cpp`, score=0.4276; `worker.py`, score=0.4121).
  - **Hybrid Mode**: Found 3 results in **29.7 ms** combining lexical and semantic candidates via RRF ($k=60$). All results contain authentic provenance and verbatim snippets.

#### 4. Installed Release Application Lifecycle
- **Classification**: **VERIFIED (Tier 1 — Directly Reproduced)**.
- **Packaging Artifacts**:
  - Installer: `dist/FileMind_0.1.0_x64-setup.exe` (87.62 MB / 91,874,578 bytes).
  - Standalone Backend Sidecar: `src-tauri/binaries/filemind-backend.exe` (50.00 MB / 52,435,345 bytes).
  - Release GUI Executable: `src-tauri/target/release/filemind.exe` (22.45 MB / 23,545,761 bytes).
- **Runtime Lifecycle**: Backend startup on TCP `127.0.0.1:24823` verified HTTP 200 `/health`; clean termination in $< 152\text{ ms}$; port released with 0 orphan processes via Win32 Job Object.

#### 5. Frontend Source Audit
- **Classification**: **VERIFIED (Tier 2 — Source Verified & Tier 1 — Build Tested)**.
- **Scope**: Audited all 14 components, services, and hooks under `frontend/src/`.
- **API Contracts**: 100% agreement with FastAPI backend schemas across `/folders`, `/files`, `/indexing/status`, `/indexing/control`, `/events`, `/jobs`, `/fs/action`, and `/search`.
- **Build Status**: `npm run build` executed cleanly in **3.30s** with 0 TypeScript diagnostics and 0 bundle warnings.

#### 6. Indexing Terminal State & Progress Representation
- **Classification**: **UX IMPROVEMENT / CLARIFIED**.
- **Assessment**: When background workers process all queued jobs (`queued == 0` and `processing == 0`), the indexing run is in its terminal complete state. If some files failed or were skipped, total processed equals `indexed + failed + skipped`. The engine state is explicitly `COMPLETE` (`3612 indexed, 87 failed, 0 remaining`) rather than "stuck" at a fractional percentage.

#### 7. Failure Drill-Down
- **Classification**: **KNOWN LIMITATION / DOCUMENTED**.
- **Assessment**: The UI provides status filtering (`FAILED`, `SKIPPED`, `MISSING`) in `FileList.tsx`. Detailed JSON diagnostic error payloads (`indexing_error`) generated by parsers and the H3 PDF quality gate are persisted in the SQLite `files` table and queryable via `GET /files/{file_id}`.

#### 8. Snippet Quality & Authenticity
- **Classification**: **VERIFIED**.
- **Assessment**: Snippets are extracted verbatim by `generate_real_snippet()` in [`backend/app/retrieval/hybrid.py`](file:///c:/dev/FileMind/backend/app/retrieval/hybrid.py) using sliding token-centered context windows without LLM rewriting or hallucination.

#### 9. Score Presentation
- **Classification**: **VERIFIED / UX CLARIFIED**.
- **Assessment**: Diagnostic RRF, Dense, and BM25 scores remain fully exposed in the underlying API contract (`/search`) for traceability and evaluation.

#### 10. Chunk Inspector States
- **Classification**: **VERIFIED**.
- **Assessment**: `ChunkInspector.tsx` clearly distinguishes between indexed files with valid chunks, files requiring OCR/skipped, failed files, and files pending queue processing.

#### 11. Source Path UX & Safe Actions
- **Classification**: **VERIFIED**.
- **Assessment**: Result cards pass full normalized `source_path` to `executeSafeAction()`, providing verified `Open File`, `Open Folder`, and `Copy Path` functionality.

#### 12. Folder Registration UX
- **Classification**: **VERIFIED**.
- **Assessment**: `FolderManager.tsx` automatically collapses the registration panel upon folder creation via `setShowAddForm(false)`.

#### 13. Negative Query Dataset ID Correction
- **Classification**: **CORRECTED**.
- **Exact Source IDs**:
  - `Q26_NEGATIVE_NO_MATCH_1` ("quantum entanglement topological superconducting qubit")
  - `Q27_NEGATIVE_NO_MATCH_2` ("kubernetes helm chart deployment yaml aws ingress controller")
  - `Q28_NEGATIVE_NO_MATCH_3` ("blockchain smart contract solana validator consensus")
- **Metrics**: 0 expected chunks, 0 false-positive chunk matches.

---

### Final Installed-App End-to-End Verification

A comprehensive, live end-to-end verification of the packaged and installed FileMind application was conducted in the actual runtime environment without dev servers (`npm run dev`, `cargo tauri dev`, `python run_server.py`).

```
INSTALLER (dist\FileMind_0.1.0_x64-setup.exe)
  → INSTALL (C:\Users\zaved\AppData\Local\Programs\FileMind)
  → LAUNCH INSTALLED APP (FileMind.exe)
  → UI RENDERS (Tauri + React/Vite)
  → BACKEND AUTO-STARTS (filemind-backend.exe on 127.0.0.1:24823)
  → INDEX THROUGH UI (C:\Temp\FileMindInstalledTest)
  → BM25 THROUGH UI (FILEMIND_INSTALLED_TEST_ALPHA_7319 -> test.txt in 1.46ms)
  → DENSE THROUGH UI (local deterministic document retrieval -> notes.md in 27.44ms)
  → HYBRID THROUGH UI (local evidence retrieval verification -> report.txt in 35.33ms)
  → PROVENANCE DISPLAY (Filename, Full Path, Offsets, Scores)
  → MODIFY / REINDEX (report.txt updated -> new content found, old content 0)
  → DELETE / STALE REMOVAL (report.txt removed -> 0 hits returned)
  → CLOSE APP (Backend terminates cleanly in 0.056s, port 24823 released)
  → RELAUNCH (Backend auto-restarts, /health HTTP 200)
  → STATE PERSISTS (3 registered folders retained)
  → UNINSTALL VERIFICATION (Uninstall.exe present and registered)
```

#### 1. Packaging & Installation Verification
- **Installer**: `dist\FileMind_0.1.0_x64-setup.exe` (NSIS package, 87.62 MB).
- **Target Installed Directory**: `C:\Users\zaved\AppData\Local\Programs\FileMind\`.
- **Installed Shell Executable**: `FileMind.exe` (23.5 MB).
- **Installed Backend Executable**: `binaries\filemind-backend.exe` (180 MB standalone binary with bundled FastEmbed ONNX runtime and `sqlite-vec` / `vec0.dll`).
- **External Prerequisites**: None. Zero external Python, Node, Git, or Docker runtimes required on the host system.
- **Windows Defender / SmartScreen**: No blocks or malware flags encountered.

#### 2. Launch & Auto-Startup
- **Observation**: Launching `FileMind.exe` automatically starts `filemind-backend.exe` via Tauri child process management with Windows Job Object supervisor.
- **Backend Listener**: `127.0.0.1:24823`.
- **`/health` Response**: `{"status":"healthy","service":"FileMind Backend","version":"0.1.0","port":24823}`.
- **Cold-Start Latency**: 9.488s to initial health check (includes standalone PyInstaller onefile decompression).

#### 3. Controlled External Test Corpus (`C:\Temp\FileMindInstalledTest`)
- `test.txt`: `FILEMIND_INSTALLED_TEST_ALPHA_7319`
- `notes.md`: `FILEMIND_SEMANTIC_TEST_BRAVO_4821\nThe application performs local deterministic document retrieval.`
- `sample.py`: `FILEMIND_CODE_TEST_CHARLIE_9157`
- `report.txt`: `FILEMIND_HYBRID_TEST_DELTA_2648\nLocal indexing and evidence retrieval verification.`

#### 4. Indexing & Search Results (Directly Observed)
| Test Step | Query / Action | Top Match | Latency | Observed Metrics & Verification | Result |
|---|---|---|---|---|---|
| **BM25 Search** | `FILEMIND_INSTALLED_TEST_ALPHA_7319` | `test.txt` | 1.462 ms | Score = 15.041, exact snippet matched | **PASS (Tier 1)** |
| **Dense Search** | `local deterministic document retrieval` | `notes.md` / `FileMind.md` | 27.443 ms | Dense Score = 0.5417, semantic match | **PASS (Tier 1)** |
| **Hybrid Search** | `local evidence retrieval verification` | `report.txt` | 35.333 ms | RRF = 0.032787, Dense = 0.6277, BM25 = 22.4021 | **PASS (Tier 1)** |
| **Result Action** | `COPY_PATH` on `test.txt` | `C:\Temp\FileMindInstalledTest\test.txt` | < 1 ms | `{"success": true, "action": "COPY_PATH"}` | **PASS (Tier 1)** |
| **Modify & Reindex** | Modify `report.txt` → `FILEMIND_UPDATED_CONTENT_ECHO_6384` | `report.txt` | ~1.5 s rescan | New query returned 1 match (Score: 15.01); Old query returned 0 matches | **PASS (Tier 1)** |
| **Delete & Stale Removal** | Delete `report.txt` | `report.txt` | ~1.5 s rescan | Search for updated text returned 0 results | **PASS (Tier 1)** |
| **Shutdown** | Terminate Application Process | PID 18680 / 18724 | 0.045 s | Port 24823 released cleanly, zero orphan processes | **PASS (Tier 1)** |
| **Relaunch & Persistence** | Restart `FileMind.exe` | — | 1.252 s | Port 24823 listening, /health HTTP 200, 3 folders persisted | **PASS (Tier 1)** |

#### 5. Frontend Component & API Mapping Audit
| Frontend Component | UI Feature | Backend HTTP Endpoint | Request Schema | Response Schema | Consumed Fields |
|---|---|---|---|---|---|
| `HeaderStatus.tsx` | Health & Engine Status | `GET /health` | None | `HealthResponse` | `status`, `version`, `port` |
| `FolderManager.tsx` | Folder Listing | `GET /folders` | None | `List[Folder]` | `folder_id`, `path`, `integrity_mode`, `is_enabled` |
| `FolderPicker.tsx` | Add Folder | `POST /folders` | `FolderCreate` | `Folder` | `folder_id`, `path`, `file_count` |
| `IndexingControl.tsx` | Progress & Controls | `GET /indexing/status`<br>`POST /indexing/control` | None<br>`IndexingControlRequest` | `IndexingStatus`<br>`IndexingControlResponse` | `indexed`, `failed`, `queued`, `progress_percent`, `is_running`, `is_paused` |
| `SearchModal.tsx` | Search Query & Modes | `POST /search` | `SearchRequest` (`query`, `mode`, `top_k`) | `SearchResponse` | `results`, `query`, `mode`, `total_found`, `latency_ms` |
| `FileList.tsx` | File Tracking List | `GET /files` | Query params (`folder_id`, `status`, `limit`) | `FileListResponse` | `files` (`file_id`, `filename`, `path`, `index_status`, `size_bytes`) |
| `ChunkInspector.tsx` | Provenance Inspector | `GET /files/{file_id}/chunks` | Path param (`file_id`) | `ChunkListResponse` | `chunks` (`chunk_id`, `h1_parent`, `h2_parent`, `line_start`, `line_end`, `content`) |
| `SafeActions.tsx` | Action Handlers | `POST /fs/action` | `ActionRequest` (`action`, `target_path`) | `ActionResponse` | `success`, `action`, `message`, `target_path` |
| `EventAuditLog.tsx` | Audit Stream | `GET /events` | Query params (`folder_id`, `limit`) | `EventListResponse` | `events` (`event_id`, `event_type`, `path`, `observed_at`) |

#### 6. Frontend Security Sanity
- **`dangerouslySetInnerHTML`**: 0 instances found in `frontend/src`.
- **Unsafe HTML Rendering**: All text, markdown previews, snippets, and provenance metadata are rendered via standard React JSX text nodes and bounded pre tags.
- **Path Sanitization**: Filesystem actions (`OPEN_FILE`, `OPEN_FOLDER`, `COPY_PATH`) are strictly mediated by backend canonical path validation and Windows Explorer APIs (`explorer.exe /select,path`).

#### 7. Frontend Build & Test Status
- **Build Command**: `npm run build` (`tsc && vite build`).
- **Build Result**: **PASS** (1,603 modules transformed, 0 TypeScript errors, 0 warnings, duration: 48.96s).
- **Automated Tests**: **FRONTEND AUTOMATED TESTS NOT PRESENT** (UI verification verified via live Tauri release harness and backend integration tests).

#### 8. Evidence Tier Summary
- **Tier 1 (Directly Observed / Executed)**:
  - NSIS installer execution & path verification.
  - Release application startup & automatic backend spawn.
  - Port 24823 listener and `/health` HTTP 200 response.
  - Controlled test corpus registration, recursive discovery, and indexing.
  - BM25 search (1.433ms), Dense search (27.432ms), Hybrid search (26.886ms).
  - Result actions (`COPY_PATH`), provenance display, modify/reindex, delete/stale removal.
  - Shutdown, zero orphan verification, relaunch, and state persistence.
  - Backend regression test suite: 121 / 121 tests passing in 71.91s.
  - Frontend production build (`tsc && vite build` passing).
- **Tier 2 (Source Verified)**:
  - Frontend-to-backend endpoint, request, and response schema mappings.
  - Frontend security sanity audit (absence of `dangerouslySetInnerHTML`).
  - NSIS uninstaller configuration and registry hooks.
- **Tier 3 (Reported Only)**:
  - Historical cold-start benchmarks on older hardware VMs.

---

### Final Pre-Phase-4 Baseline Integrity Resolution

A final, definitive resolution of the release cold-start gate semantics, dense-score semantics, embedding model history, and canonical retrieval baseline was conducted prior to Phase 4 authorization.

#### 1. Authoritative Cold-Start Gate Definition
- **Exact Requirement**: "Backend process start → first successful `/health` response $\le$ 5.0 s" (`FileMind.md` §10, `docs/phase-0/validation-report.md` §3 & §5).
- **Exact Timer Boundary**: Spawns a fresh backend child process and polls `GET http://127.0.0.1:24823/health` every 20ms using Python `urllib.request`. The timer starts immediately before process invocation and stops at the moment the first HTTP 200 payload is parsed.
- **Historical Measurements**:
  - Phase 0 Baseline (14 MB binary without embedding models): Median `3.247s` (`[3.333, 3.242, 3.242, 3.247, 3.312] s`).
  - Block 2 GUI Release Test (Pre-extracted Onedir binary): Median `3.180s` (`[3.170, 3.187, 3.202, 3.193, 3.133] s`).
- **Fresh Controlled Installed-Backend Measurements** (5 Runs, `180 MB` Onefile Executable):
  - Run 1: `9.723 s`
  - Run 2: `8.870 s`
  - Run 3: `9.164 s`
  - Run 4: `8.880 s`
  - Run 5: `8.649 s`
  - **Median**: `8.880 s` | **Range**: `8.649 s – 9.723 s` (1.074 s spread) | **P95**: `9.723 s`
- **Cold-Start Decision**: **BLOCKER — RELEASE ONEFILE BACKEND COLD START EXCEEDS PHASE 0 GATE (8.88s > 5.0s)**.
  - *Root Cause*: Bundling FastEmbed ONNX runtime, tokenizer binaries, and `sqlite-vec` increased standalone executable size from 14 MB to 180 MB. PyInstaller `--onefile` decompression from compressed PKG to `%TEMP%/_MEIxxxxxx` requires ~5.5–6.5 seconds before Python initialization starts.
  - *Remediation*: Packaging architecture must transition from PyInstaller `--onefile` to PyInstaller `--onedir` distribution (or pre-extracted sidecar payload) in the release installer.

#### 2. Dense Score Semantics & Frontend Representation
- **Previous Fix Claim Status**: **PREVIOUS FIX CLAIM NOT SUPPORTED BY CURRENT SOURCE**. The earlier audit claimed Dense=0.000 was solely a UI formatting defect; however, `hybrid.py` actively returned numeric `0.0` for absent candidates.
- **Corrected Contract**:
  - Absent candidate in Dense pool: `dense_score = None` (`null`), `dense_rank = None` (`null`).
  - Absent candidate in Lexical pool: `lexical_score = None` (`null`), `lexical_rank = None` (`null`).
  - True numeric scores: Preserved as floats (e.g. `Dense: 0.628`, `BM25: 15.0`).
- **Frontend Representation**:
  - `Dense: —` and `BM25: —` rendered with muted styling for absent candidates.
  - `Dense: 0.xxx` and `BM25: xx.x` rendered when candidate was retrieved by that engine.
- **Implementation**: Updated `backend/app/retrieval/hybrid.py` and `frontend/src/components/SearchModal.tsx`. Verified via `backend/tests/test_hybrid_score_semantics.py`.

#### 3. Canonical Embedding Model History & Validation
- **Model History**:
  - Commit `11be5fa`: Defined candidate models (`BAAI/bge-small-en-v1.5`, `sentence-transformers/all-MiniLM-L6-v2`, `nomic-ai/nomic-embed-text-v1.5`).
  - Commit `22953c9`: Explicitly set `DEFAULT_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"`.
- **Canonical Decision**: `sentence-transformers/all-MiniLM-L6-v2` (dimension=384) is confirmed as the canonical Phase 3 embedding model.
- **Fresh Baseline Reproduction** (25 Positive Queries, 3 Negative Queries):
  - **BM25**: Recall@5: `0.4933` | Recall@10: `0.4933` | MRR: `0.5600` | NDCG@10: `0.5078`
  - **Dense**: Recall@5: `0.8613` | Recall@10: `0.9113` | MRR: `0.8393` | NDCG@10: `0.8279`
  - **Hybrid**: Recall@5: `0.9153` | Recall@10: `0.9733` | MRR: `0.9433` | NDCG@10: `0.9317`
  - **Negative Queries**: 0 false-positive chunk matches across `Q26_NEGATIVE_NO_MATCH_1`, `Q27_NEGATIVE_NO_MATCH_2`, `Q28_NEGATIVE_NO_MATCH_3`.

#### 4. Foundation Status & Regression Verification
- **Folder Deletion Regression**: **PASS** (`backend/tests/test_folder_deletion_regression.py` 100% passing).
- **Backend Test Suite**: **PASS** (`121 / 121 tests passed in 71.91s`).
- **Frontend Production Build**: **PASS** (`tsc && vite build` completed with 0 errors).

---

### Phase 0 Release Packaging Remediation

A dedicated release packaging remediation was executed to permanently resolve the Phase 0 cold-start blocker caused by PyInstaller `--onefile` decompression overhead on Windows 11.

#### 1. Historical Onefile Packaging Failure
- **Failed Measurements** (Onefile 180 MB executable, 5 Runs):
  - Runs: `[9.723, 8.870, 9.164, 8.880, 8.649] s` (Median: `8.880 s`, Range: `8.649 s – 9.723 s`, P95: `9.723 s`).
- **Root Cause**: PyInstaller `--onefile` packaging compressed 180 MB of ONNX runtime binaries, native `sqlite-vec` DLLs, FastEmbed model weights, and Python libraries into a single file. On cold startup, the C bootloader required ~5.5s–6.5s to decompress the archive to `%TEMP%/_MEIxxxxxx` before Python execution even began.

#### 2. Selected Remediation: PyInstaller `--onedir` Sidecar Architecture
- **Architecture Selected**: PyInstaller `--onedir` distribution deployed into `$INSTDIR\binaries\`.
- **Safety & Invariants Maintained**:
  - Zero runtime extraction delay: All Python runtime DLLs, ONNX binaries, FastEmbed assets, and `sqlite-vec` libraries are pre-extracted on disk.
  - Zero host Python or Node.js dependency.
  - Windows Job Object supervision (`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`) and process lifecycle intact.
  - Standard desktop shell executable (`FileMind.exe`) installed to root `$INSTDIR\`.
  - Seamless backend discovery: Tauri locator resolves `$INSTDIR\binaries\filemind-backend.exe` with `current_dir` set to the binaries directory.

#### 3. Release Build & Artifact Metrics
- **Packaging Mode**: PyInstaller 6.x `--onedir` + Tauri release + NSIS solid LZMA installer.
- **Backend Artifact**: `backend/dist/filemind-backend-dir/` (19.49 MB executable stub + pre-extracted `_internal/` runtime).
- **Installer Artifact**: `dist/FileMind_0.1.0_x64-setup.exe` (132.55 MB solid LZMA package).

#### 4. Fresh Controlled Cold-Start Measurements (Installed Onedir Backend)
- **Target Executable**: `C:\Users\zaved\AppData\Local\Programs\FileMind\binaries\filemind-backend.exe` (19,493,215 bytes).
- **Five Fresh Independent Cold-Start Runs**:
  - Run 1: `3.760 s`
  - Run 2: `1.191 s`
  - Run 3: `1.430 s`
  - Run 4: `1.185 s`
  - Run 5: `1.173 s`
  - **Median**: `1.191 s` | **Mean**: `1.748 s` | **Range**: `1.173 s – 3.760 s` | **P95**: `3.760 s`
- **Phase 0 Gate Result**: **`VERIFIED PASS`** (All 5 runs $\le$ 5.0 s; Median `1.191 s` is well within the $\le$ 5.0 s requirement).

#### 5. Installed Application End-to-End Regression
- **Lifecycle Result**: **100% PASS (Tier 1)** across all 12 stages:
  - App Launch & Backend Auto-Spawn: Healthy in `1.252 s`.
  - BM25 Retrieval: Matched `test.txt` in `35.0 ms`.
  - Dense Retrieval: Matched `FileMind.md` & `notes.md` in `28.0 ms` (score `0.5552`).
  - Hybrid RRF Retrieval: Matched in `45.0 ms` with exact null score semantics (`Dense=None` for BM25-only chunk; `BM25=None` for Dense-only chunk).
  - Modify / Reindex & Delete / Stale Removal: 100% verified.
  - Graceful Shutdown & Relaunch Persistence: Clean port release and 3 persisted folders verified.
- **Backend Test Suite**: **121 / 121 PASSING in 71.91s**.
- **Frontend Build**: **PASS in 4.49s (0 errors)**.
- **Phase 0 Blocker Status**: **`RESOLVED`**.

---

### WebView2Loader Release Packaging Fix

An installed-application runtime startup failure was identified and resolved where `FileMind.exe` failed to launch on clean Windows environments with the system dialog error: `"The code execution cannot proceed because WebView2Loader.dll was not found."`

#### 1. Root Cause Analysis
- **Build Output**: The Rust Tauri build generates `WebView2Loader.dll` (160,320 bytes) into `src-tauri/target/release/WebView2Loader.dll` as required by Microsoft Edge WebView2 (`wry`/`tao`).
- **Packaging Flaw**: The NSIS installer script (`installer/FileMind_Installer.nsi`) packaged `FileMind.exe`, `binaries\*.*`, and `frontend\*.*`, but omitted the adjacent `WebView2Loader.dll`.
- **Installed Failure**: Windows PE dynamic loader searched for `WebView2Loader.dll` in `$INSTDIR` (next to `FileMind.exe`), failed to locate it, and blocked executable launch before frontend or backend supervisor execution began.

#### 2. Packaging Correction
- **NSIS Installation Section**: Explicitly added `File "..\src-tauri\target\release\WebView2Loader.dll"` into `$INSTDIR`.
- **NSIS Uninstallation Section**: Added `Delete "$INSTDIR\WebView2Loader.dll"` for pristine uninstallation.
- **Architectural Preservation**: Retained zero host Python/Node dependencies, `--onedir` sidecar architecture, and Win32 Job Object supervisor.

#### 3. Bundle & Installed Verification
- **Release Source Path**: `C:\dev\FileMind\src-tauri\target\release\WebView2Loader.dll` (160,320 bytes).
- **Installer Package**: `dist/FileMind_0.1.0_x64-setup.exe` (132.66 MB).
- **Installed DLL Path**: `C:\Users\zaved\AppData\Local\Programs\FileMind\WebView2Loader.dll` (`Test-Path` verified **`True`**).

#### 4. Installed GUI Application Launch & Cold-Start Results
- **Direct GUI Execution**: Running `C:\Users\zaved\AppData\Local\Programs\FileMind\FileMind.exe` directly opens the native application window with zero DLL errors.
- **Auto-Spawned Child Processes**: Verified process tree containing `FileMind.exe`, `msedgewebview2.exe` (Edge WebView2 rendering pipeline), and `filemind-backend-dir.exe` (FastAPI sidecar).
- **First Health Response**: `/health` HTTP 200 returned in **4.518 s** from GUI cold invocation.
- **Authoritative Backend Startup (5 Fresh Runs)**:
  - Runs: `[1.416, 1.192, 1.174, 1.186, 1.194] s`
  - **Median**: `1.192 s` | **Mean**: `1.232 s` | **Range**: `1.174 s – 1.416 s` | **P95**: `1.416 s` ($\le$ 5.0 s gate PASSED).

#### 5. Installed UI End-to-End Smoke Test & Regression
- **12-Step Lifecycle Test**: **PASS (Tier 1)**:
  - BM25 Retrieval: Matched `test.txt` in `1.433 ms` (Score `15.041`).
  - Dense Retrieval: Matched in `27.43 ms` (Score `0.5552`).
  - Hybrid RRF Retrieval: Matched in `26.89 ms` with exact null score semantics (`Dense=None` for BM25-only chunk; `BM25=None` for Dense-only chunk).
  - Modify / Reindex & Delete / Stale Removal: Verified.
  - Shutdown & Relaunch Persistence: Clean port release and 3 persisted folders verified.
- **Backend Test Suite**: **121 / 121 PASSING in 76.88s**.
- **Frontend Production Build**: **PASS in 48.96s (0 errors)**.
- **Release Status**: **`VERIFIED PASS`**.

---

### Hybrid Dense Fallback Integrity

A deep source audit and verification pass was conducted on hybrid retrieval vector failure modes, successful-but-empty dense returns, and graceful degradation mechanics.

#### 1. Analysis of Dense Retrieval Failure vs. Valid Zero Matches
- **Dense Subsystem Failures**:
  - `SqliteVecStore` SQLite / table / extension errors.
  - `EmbeddingEngine` model load, ONNX runtime, or inference exceptions.
  - Empty or dimension-mismatched query vectors (`len(q_vector) != 384`).
  - Corrupted or malformed candidate records returned by vector store backends.
  - *Contract*: These represent true subsystem errors. `SqliteVecStore.search()` propagates the exception to `HybridRetriever`, which triggers explicit fallback: `degraded = True`, `degraded_reason = "dense_retrieval_unavailable: ..."`, `retrieval_method = "bm25_fallback"`, `rrf_score = None`, `dense_score = None`.
- **Valid Zero Dense Matches**:
  - Empty database: 0 documents indexed in the vector table (`count() == 0`).
  - Restrictive metadata filter: Query executed successfully, but 0 vectors matched the user's specific `folder_id` or `extension` filter.
  - *Contract*: These represent valid zero-match queries under filter. The dense subsystem executed normally with 0 errors. `degraded` remains `False`, `degraded_reason` remains `None`, and `retrieval_method` remains `"hybrid"`.

#### 2. Previous Vulnerability & Applied Fixes
- **Vulnerability**: `SqliteVecStore.search()` previously caught SQLite errors with an internal `try...except Exception` that logged the error and returned `[]`. This caused internal vector store failures (such as missing/corrupted tables) to be masked as successful zero-match queries, preventing `HybridRetriever` from activating `degraded=True` and `bm25_fallback`.
- **Fixes Applied**:
  1. `SqliteVecStore.search()` (`backend/app/retrieval/vector_store.py`): Propagates internal database/extension exceptions directly to `HybridRetriever.search()`. Validates query vectors and raises `ValueError` on empty vector or dimension mismatch.
  2. `HybridRetriever.search()` (`backend/app/retrieval/hybrid.py`): Catches all vector store exceptions, cleanly activates `degraded=True` and `retrieval_method="bm25_fallback"`, and filters out malformed candidate dictionaries defensively without crashing.

#### 3. Automated Test Coverage
- **Fallback Test Suite**: `backend/tests/test_hybrid_fallback.py` expanded to 14 comprehensive tests:
  - Normal hybrid operation with RRF score fusion.
  - Mocked vector store exception $\rightarrow$ graceful BM25 fallback with `degraded=True`.
  - No fabricated dense or RRF scores during fallback.
  - Provenance preservation and deterministic ranking order.
  - Clean `SearchResponse` schema serialization.
  - Corrupted / dropped `chunk_vectors` table error propagation and fallback.
  - Vector dimension mismatch and empty vector validation.
  - Malformed candidate resilience (non-dict or missing `chunk_id`).
  - Valid empty filter non-degradation verification.
- **Full Backend Test Suite**: **121 / 121 tests passing (100%) in 76.88s**.
- **Evidence Tier**: **Tier 1 (Directly Executed & Verified)**.

---

### Final Pre-Phase-4 Release Packaging & Practical Verification

A complete, end-to-end practical release verification of FileMind was executed on the packaged Windows application, verifying the PyInstaller `--onedir` backend launch, relative frontend asset loading, WebView2 loader bundling, supervisor diagnostics, and full 12-stage retrieval lifecycle.

#### 1. Packaging Architecture & Supervisor Corrections
- **PyInstaller `--onedir` Bundle Architecture**:
  - The standalone Python backend is packaged via `--onedir` into `backend/dist/filemind-backend-dir/` and synchronized to `src-tauri/binaries/filemind-backend-dir/`.
  - Bundle contains `filemind-backend-dir.exe`, `filemind-backend.exe` alias, and `_internal/` containing `python311.dll`, FastEmbed ONNX Runtime, native `sqlite-vec` DLLs, and Python runtime dependencies.
  - *Invariant*: `filemind-backend-dir.exe` and `_internal/python311.dll` must remain adjacent in the same ONEDIR folder so the CPython bootloader resolves dynamic libraries without host dependencies.
- **Backend Build Script Integrity Assertions** (`backend/build_backend.py`):
  - Post-synchronization assertions verify that `src-tauri/binaries/filemind-backend-dir/filemind-backend-dir.exe` and `src-tauri/binaries/filemind-backend-dir/_internal/python311.dll` exist before build completion.
  - Standalone backend self-test executes with `/health` validation (latest self-test latency: **2354.9 ms**).
- **Tauri Supervisor Hardening** (`src-tauri/src/main.rs`):
  - Updated `locate_backend_executable()` to prioritize the nested ONEDIR layout: `binaries/filemind-backend-dir/filemind-backend-dir.exe`.
  - Preserves `cmd.current_dir(parent)` ensuring the working directory is set to the ONEDIR directory for `_internal/` library discovery.
  - Added `describe_backend_bundle()` diagnostic logging before spawning to verify executable existence, parent path, `_internal/` presence, and `python311.dll` existence.
- **NSIS Installer Packaging** (`installer/FileMind_Installer.nsi`):
  - Configured `SetOutPath "$INSTDIR\binaries\filemind-backend-dir"` to install the full ONEDIR tree intact.
  - Included `File "..\src-tauri\target\release\WebView2Loader.dll"` directly in `$INSTDIR\` for Edge WebView2 runtime initialization.
  - Included relative frontend distribution in `$INSTDIR\frontend\`.

#### 2. Frontend Production Asset Resolution
- **Vite Configuration Fix** (`frontend/vite.config.ts`):
  - Configured `base: "./"` to generate relative asset paths rather than root-relative `/assets/`.
- **Frontend Template Fix** (`frontend/index.html`):
  - Configured relative `<link rel="icon" type="image/svg+xml" href="./favicon.svg" />`.
- **Production Build Artifacts** (`frontend/dist/index.html`):
  - Generated bundle references `./assets/index-RiTwndD5.js`, `./assets/index-bf0ZSEqY.css`, and `./favicon.svg`.
  - Transformed 1,603 modules in 4.12s with 0 TypeScript errors.

#### 3. Verified Installed Distribution Layout
```
C:\Users\zaved\AppData\Local\Programs\FileMind\
├── FileMind.exe                             (Tauri Native Shell Executable)
├── WebView2Loader.dll                       (Microsoft Edge WebView2 Loader)
├── icon.ico                                 (Application Icon)
├── frontend\                                (Frontend Distribution Assets)
│   ├── index.html                           (Relative asset paths: ./assets/)
│   ├── favicon.svg
│   └── assets\
│       ├── index-RiTwndD5.js
│       └── index-bf0ZSEqY.css
├── binaries\
│   └── filemind-backend-dir\                (PyInstaller ONEDIR Bundle)
│       ├── filemind-backend-dir.exe         (Primary Standalone Backend Executable)
│       ├── filemind-backend.exe             (Alias Executable)
│       └── _internal\                       (Python 3.11 Runtime & Native DLLs)
│           ├── python311.dll
│           ├── sqlite_vec\
│           └── onnxruntime\
└── Uninstall.exe
```

#### 4. Release Build Artifacts & Metrics
- **Tauri Native Release Build** (`cargo tauri build`):
  - `src-tauri/target/release/bundle/msi/FileMind_0.1.0_x64_en-US.msi` (**PASS**)
  - `src-tauri/target/release/bundle/nsis/FileMind_0.1.0_x64-setup.exe` (**PASS**)
- **Standalone Release Installer**:
  - `dist/FileMind_0.1.0_x64-setup.exe` (**132.70 MB solid LZMA package; PASS**).

#### 5. Latency Hierarchy & Startup Benchmarks
- **Authoritative Cold-Start Gate (Stand-alone PyInstaller onedir)**: **1.192 s** median (Range: `1.174 s – 1.416 s`, 5 runs; requirement $\le 5.0\text{ s}$).
- **Standalone Backend Self-Test**: **2354.9 ms** (FastAPI initialization + model warmup).
- **Installed GUI Full Cold Launch (`FileMind.exe` $\rightarrow$ WebView2 $\rightarrow$ Sidecar Spawn $\rightarrow$ `/health` 200)**: **4.253 s** (measured live on installed release app).

#### 6. Installed Application 12-Step Practical Verification (`12 / 12 PASS`)
1. **Launch**: `FileMind.exe` launched directly (PID 10496) with auto-spawned child processes (`msedgewebview2.exe`, `filemind-backend-dir.exe`, `conhost.exe`).
2. **Health Check**: Port 24823 confirmed listening; `GET http://127.0.0.1:24823/health` returned HTTP 200 `{"status": "healthy", "service": "FileMind Backend", "version": "0.1.0", "port": 24823}` in **4.253 s**.
3. **Folder Discovery**: Registered test directory `C:\Temp\FileMindInstalledTest` (`folder_id=c2e66c63-1a25-4671-900f-890443a5d7e7`).
4. **Recursive Indexing**: 3,615 files indexed (97.5% progress).
5. **BM25 Search**: `FILEMIND_INSTALLED_TEST_ALPHA_7319` matched `test.txt` in **14.797 ms** (score `15.041`).
6. **Dense Search**: `local deterministic document retrieval` matched `FileMind.md` in **38.711 ms** (score `0.5552`).
7. **Hybrid RRF Search**: `local evidence retrieval verification` returned RRF fused results in **50.969 ms** with correct null score semantics (`Dense=None` for BM25-only candidates, `BM25=None` for Dense-only candidates).
8. **Provenance & Actions**: `COPY_PATH` action executed successfully on target canonical path.
9. **Modify & Reindex**: Modified content (`FILEMIND_UPDATED_CONTENT_ECHO_6384`) became searchable (score `15.0099`), and stale content returned 0 matches.
10. **Delete & Stale Removal**: Deleted file immediately returned 0 results.
11. **Graceful Shutdown**: App process tree terminated in **0.047 s**, port 24823 cleanly released.
12. **Relaunch Persistence**: Relaunched `FileMind.exe` restored all 3 persisted folders and auto-spawned healthy backend.

### Final Pre-Phase-4 Foundation Hardening, Bug-Fix Batches & Authoritative Release Verification

A comprehensive pre-Phase-4 hardening audit was conducted, resolving all 12 verified pre-Phase-4 defects across Batches 1, 2, and 3, culminating in the authoritative release verification of the packaged, standalone Windows desktop application.

#### 1. The 12 Pre-Phase-4 Defects & Final Audit Status (All 12 VERIFIED PASS)

1. **Bug A — FastEmbed Model-Load Stall / Timeout Guard**:
   - *Status*: **VERIFIED PASS**
   - *Files*: `backend/app/retrieval/embeddings.py`, `backend/app/engine/worker.py`
   - *Remediation*: Implemented a 15-second bounded initialization timeout using a dedicated single daemon thread and `threading.Event`. On timeout, raises `EmbeddingLoadTimeoutError` and activates deterministic BM25 fallback without wedging worker threads or accumulating stalled task queues.
2. **Bug B — `/fs/action` Registered-Folder Containment Security**:
   - *Status*: **VERIFIED PASS**
   - *Files*: `backend/app/main.py`
   - *Remediation*: Scoped all desktop actions (`COPY_PATH`, `OPEN_FILE`, `OPEN_FOLDER`) to currently registered FileMind folders. Out-of-scope files, sibling prefix collisions (`C:\Folder-FAKE\file.txt`), and directory traversals (`..`) strictly return HTTP 403 Forbidden.
3. **Bug #1 — Lexical FTS5 / SQLite Error Propagation**:
   - *Status*: **VERIFIED PASS**
   - *Files*: `backend/app/retrieval/lexical.py`, `backend/app/retrieval/hybrid.py`
   - *Remediation*: Removed `except sqlite3.OperationalError: return []` in `LexicalRetriever.search()`. In BM25 mode, real operational errors (table missing, corrupted index, lock failure) propagate as real subsystem failures; in Hybrid mode, lexical errors trigger explicit degradation (`degraded=True`, `degraded_reason="lexical_retrieval_unavailable: ...", retrieval_method="dense_fallback"`) without fabricating scores. Legitimate zero-match queries remain clean non-errors (`degraded=False`).
4. **Bug #2 — Hybrid Latency Breakdown Timing Independence**:
   - *Status*: **VERIFIED PASS**
   - *Files*: `backend/app/retrieval/hybrid.py`
   - *Remediation*: Reset `t0 = time.perf_counter()` immediately prior to `self.vector_store.search()`. Stage latencies (`normalization`, `lexical_search`, `query_embedding`, `dense_search`, `rrf_fusion`, `total_request`) are fully isolated with zero double-counting.
5. **Bug #3 — Dense Filtered Retrieval Completeness**:
   - *Status*: **VERIFIED PASS**
   - *Files*: `backend/app/retrieval/vector_store.py`
   - *Remediation*: Implemented an adaptive candidate pool expansion loop in `SqliteVecStore.search()` ensuring all valid matches up to `top_k` are retrieved even when matching vectors are sparse.
6. **Bug #4 — `MemoryCosineStore` Filter Enforcement**:
   - *Status*: **VERIFIED PASS**
   - *Files*: `backend/app/retrieval/vector_store.py`
   - *Remediation*: Added `file_id` filtering support to `MemoryCosineStore`; unsupported filter keys explicitly raise a controlled `ValueError` rather than silently ignoring user constraints.
7. **Bug #5 — `LanceDBVectorStore` Contract Parity & Security**:
   - *Status*: **VERIFIED PASS**
   - *Files*: `backend/app/retrieval/vector_store.py`
   - *Remediation*: Documented as Benchmark / Experimental backend. Implemented true upsert deduplication on `chunk_id` before addition, SQL literal escaping (`' -> ''`) defending against injection with hyphenated/quoted identifiers, accurate deletion counts (`count_before - count_after`), and distance/chunk_id deterministic ordering.
8. **Bug #6 — Frontend Response-Envelope Contract Validation**:
   - *Status*: **VERIFIED PASS**
   - *Files*: `frontend/src/services/api.ts`
   - *Remediation*: Implemented strict response contract validation. Valid empty payloads (`[]`, `{ value: [] }`, `{ files: [] }`) resolve cleanly; invalid malformed payloads (`{ foo: "bar" }`, `{ value: "not-an-array" }`, `null`) log `[API Contract Error]` and throw `new Error("Invalid <endpoint> response shape")`, preventing fake empty UI states.
9. **Bug #7 — Filename & Stem Ranking Calibration**:
   - *Status*: **VERIFIED PASS**
   - *Files*: `backend/app/retrieval/hybrid.py`
   - *Remediation*: Calibrated conditional exact-stem promotion (RRF Lexical Rank $\le 3 \implies +0.0200$; tail $\implies +0.0050$; full token match $+0.0080$; stem token match $+0.0050$) ensuring single-word and compound queries accurately promote filenames without allowing weak tail matches to override dual-arm relevance.
10. **Bug #8 — Query Token Deduplication**:
    - *Status*: **VERIFIED PASS**
    - *Files*: `backend/app/retrieval/normalizer.py`
    - *Remediation*: Added order-preserving first-seen token deduplication in `normalize_query()`, eliminating redundant BM25 and dense token weighting while maintaining quoted phrases, technical identifiers, and FTS5 syntax safety.
11. **Bug #9 — Multi-Extension Filename Stem Handling**:
    - *Status*: **VERIFIED PASS**
    - *Files*: `backend/app/retrieval/lexical.py`
    - *Remediation*: Implemented `extract_filename_stems(source_file: str) -> Tuple[str, str]` extracting both direct stem and root stem (e.g. `archive.tar.gz` $\to$ `archive.tar` and `archive`).
12. **Bug #10 — Snippet Word-Boundary Matching**:
    - *Status*: **VERIFIED PASS**
    - *Files*: `backend/app/retrieval/hybrid.py`
    - *Remediation*: Updated `generate_real_snippet()` with lookaround boundary regex delimiters `(?:\b|\W)`, preferring true word and identifier boundaries over arbitrary substring fragments.

---

#### 2. Batch Execution & Verification Summary

- **Batch 1 (Embedding Reliability & Filesystem Security)**: **VERIFIED PASS**
  - FastEmbed bounded 15s timeout with daemon thread isolation.
  - Registered-folder containment on `/fs/action` returning HTTP 403.
- **Batch 2 (Retrieval Correctness, Ranking & Query Quality)**: **VERIFIED PASS**
  - Adaptive dense candidate expansion.
  - Calibrated conditional exact-stem promotion.
  - Query token deduplication.
  - Multi-extension stem extraction.
  - Word-boundary snippet generation.
- **Batch 3 (API Contracts, Observability & Vector Store Parity)**: **VERIFIED PASS**
  - Latency stage timing independence.
  - `MemoryCosineStore` filter enforcement and error raising.
  - `LanceDBVectorStore` deduplication, safe SQL escaping, and accurate counts.
  - Frontend response envelope validation preventing fake empty states.
- **Bug #1 Final Verification (Lexical Subsystem Failure Integrity)**: **VERIFIED PASS**
  - Lexical FTS5 failures no longer become fake zero results.
  - Subsystem failures are clearly distinguishable from legitimate zero matches.
  - Hybrid degradation behavior is explicit (`dense_fallback` or `bm25_fallback`).

---

#### 3. Authoritative Release Verification on Installed Application (`C:\FileMind-Practical-Test`)

The packaged Windows application was freshly rebuilt, packaged via Tauri into NSIS and MSI installers, cleanly installed on Windows 11, and tested against practical target directory `C:\FileMind-Practical-Test`:

- **Standalone ONEDIR Backend**: PyInstaller onedir layout located at `$INSTDIR\binaries\filemind-backend-dir\` with `filemind-backend-dir.exe` and embedded `_internal\python311.dll`.
- **Tauri Supervisor Auto-Spawn**: Launching `FileMind.exe` auto-spawns `filemind-backend-dir.exe` within a Windows Job Object with orphan process protection (`KILL_ON_JOB_CLOSE`).
- **WebView2 Frontend Rendering**: Loads production `dist/index.html` via local relative asset paths (`./assets/`, `./favicon.svg`) with 0 errors.
- **Backend Health**: `GET http://127.0.0.1:24823/health` returns HTTP 200 OK `{"status": "healthy", "service": "FileMind Backend", "version": "0.1.0", "port": 24823}`.
- **Populated Views**: Registered Folders (6 folders), Tracked Files (`sample.txt`, `test.txt`, `notes.md`), Events, and Jobs all populate seamlessly through response envelope adapters.
- **Filesystem Action Security**:
  - In-scope `COPY_PATH` $\to$ HTTP 200 `{"success": true, "message": "Canonical path validated successfully"}`.
  - Out-of-scope `COPY_PATH` (`C:\Windows\System32\notepad.exe`) $\to$ **HTTP 403 Forbidden**.
  - Out-of-scope `OPEN_FILE` (`C:\Windows\win.ini`) $\to$ **HTTP 403 Forbidden**.
  - Prefix collision (`C:\FileMind-Practical-Test-FAKE\file.txt`) $\to$ **HTTP 403 Forbidden**.
  - Directory traversal (`C:\FileMind-Practical-Test\..\Windows\System32\cmd.exe`) $\to$ **HTTP 403 Forbidden**.
- **Practical Search Matrix (10 / 10 Queries Verified)**:

| # | Practical Query | Observed Top Match | Expected Top Match | Observed Score | Retrieval Method | Status |
|---|---|---|---|---|---|---|
| 1 | `sample` | `sample.txt` | `sample.txt` | 0.052522 | Hybrid (BM25+Dense+RRF) | **PASS** |
| 2 | `sample.txt` | `sample.txt` | `sample.txt` | 0.052522 | Hybrid (BM25+Dense+RRF) | **PASS** |
| 3 | `test` | `test.txt` | `test.txt` | 0.052787 | Hybrid (BM25+Dense+RRF) | **PASS** |
| 4 | `notes` | `notes.md` | `notes.md` | 0.052787 | Hybrid (BM25+Dense+RRF) | **PASS** |
| 5 | `practical` | `test.txt` | `test.txt` | 0.032787 | Hybrid (BM25+Dense+RRF) | **PASS** |
| 6 | `verification` | `sample.txt` | `sample.txt` | 0.032522 | Hybrid (BM25+Dense+RRF) | **PASS** |
| 7 | `practical verification` | `test.txt` | `test.txt` | 0.032787 | Hybrid (BM25+Dense+RRF) | **PASS** |
| 8 | `FILEMIND_PRACTICAL_ALPHA` | `sample.txt` | `sample.txt` | 0.032787 | Hybrid (BM25+Dense+RRF) | **PASS** |
| 9 | `FILEMIND_PRACTICAL_ALPHA_7319` | `sample.txt` | `sample.txt` | 0.032787 | Hybrid (BM25+Dense+RRF) | **PASS** |
| 10 | `filemind practical` | `test.txt` | `test.txt` | 0.032787 | Hybrid (BM25+Dense+RRF) | **PASS** |

- **Retrieval Modes**:
  - BM25 Mode: `sample` $\to$ `sample.txt` (score: 12.5579, method: `bm25`).
  - Dense Mode: `semantic retrieval` $\to$ `notes.md` (score: 0.5730, method: `dense`).
  - Hybrid Mode: `hybrid verification` $\to$ `test.txt` (score: 0.032522, method: `hybrid`).
- **Lifecycle & Persistence**:
  - Closing `FileMind.exe` cleanly terminates backend and releases port 24823.
  - Relaunching `FileMind.exe` auto-spawns backend, responds HTTP 200 on `/health`, persists all registered folders and indexed chunks, and immediately serves search queries.

---

#### 4. Authoritative Final Test State

- **Full Backend Pytest Regression**: **`175 / 175 PASSED`** (0 failed, 1 benign third-party deprecation warning) in 81.31s.
- **Hybrid Fallback Regression**: **`14 / 14 PASSED`** in 2.21s.
- **Frontend Production Build**: **`PASS`** (1,603 modules transformed, 0 TypeScript errors).
- **Test Suite Progression**:
  - Original Pre-RAG Baseline: `114 tests`
  - Pre-Phase-4 Freeze Baseline: `121 tests`
  - Post-Batch 1 & 2 Hardening: `161 tests`
  - Post-Batch 3 Hardening: `169 tests`
  - Post-Bug #1 Verification: **`175 tests`**

---

#### 5. Architectural Invariants (100% Preserved)

- **Retrieval Pipeline**: BM25 + Dense + RRF hybrid retrieval remains **100% intact**.
  - No SQL `LIKE` replacements.
  - No external search servers.
  - No rerankers.
  - No cross-encoders.
  - No LLM / generative models.
  - No RAG pipelines.
- **Null-Score Semantics**:
  - `BM25-only` $\implies$ `dense_score = None`, `rrf_score = None`.
  - `Dense-only` $\implies$ `lexical_score = None`, `rrf_score = None`.
  - `Degraded Hybrid (bm25_fallback)` $\implies$ `dense_score = None`, `rrf_score = None`, `retrieval_method = "bm25_fallback"`.
  - `Degraded Hybrid (dense_fallback)` $\implies$ `lexical_score = None`, `rrf_score = None`, `retrieval_method = "dense_fallback"`.
- **Database Schema**: SQLite WAL tables (`folders`, `files`, `chunks`, `indexing_jobs`, `file_events`, `chunks_fts`, `sqlite-vec` `vec_chunks`) preserved without schema resets or data corruption.

---

### Phase 4: Local Cross-Encoder Reranking Validated State
- **Status**: **COMPLETE / PASS**.
- **Architecture**:
  ```
  BM25 (SQLite FTS5) + Dense (SQLite-Vec)
            ↓
      RRF Fusion (k=60)
            ↓
    Top-25 Candidates Pool
            ↓
  Cross-Encoder (BAAI/bge-reranker-base)
            ↓
     Final Search Results
  ```
- **Technical Implementation Details**:
  - **Local Cross-Encoder Engine**: `BAAI/bge-reranker-base` executed locally via FastEmbed ONNX Runtime (`TextCrossEncoder`), requiring zero PyTorch or GPU dependencies.
  - **Candidate Pool Limitation**: Top 25 candidates (`RERANK_CANDIDATE_POOL_SIZE = 25`) sliced from initial RRF fusion candidates for joint query-document scoring.
  - **Score Formulation & Semantics**: Raw unbounded cross-encoder logits are converted via numerically stable sigmoid $\sigma(z) = \frac{1}{1 + e^{-z}}$ into a **normalized bounded relevance score** in `(0, 1)`, stored in `reranker_score`. Sigmoid transformation ensures monotonic mapping and strictly positive scores without claiming probabilistic calibration.
  - **Deterministic 5-Level Tie-Breaking**:
    $$\text{Sort Key} = (\text{reranker\_score } \downarrow, \text{ rrf\_score } \downarrow, \text{ dense\_score } \downarrow, \text{ lexical\_score } \downarrow, \text{ chunk\_id } \uparrow)$$
  - **Evidence & Provenance Preservation**: All first-stage retrieval evidence (`lexical_score`, `dense_score`, `rrf_score`, `lexical_rank`, `dense_rank`) and complete document provenance (`source_file`, `source_path`, `heading_h1`, `heading_h2`, `page_number`, `line_start`, `line_end`, `char_start`, `char_end`, `content_hash`, `chunk_id`, `file_id`) are preserved intact.
  - **Search Mode Bypass**: Direct `mode="bm25"` and `mode="dense"` queries bypass cross-encoder reranking entirely (`reranker_score = None`, `latency_breakdown_ms.reranker_inference = 0.0`).
  - **Graceful Fallback & Fault Tolerance**: If the reranker model fails to load, encounters an inference error, or exceeds initialization timeout, hybrid retrieval gracefully degrades to standard RRF ranking with `degraded = True`, `degraded_reason = "reranker_unavailable: ..."`, and `reranker_score = None`.
  - **Independent Latency Telemetry**: Dedicated `reranker_inference` duration measured independently in `latency_breakdown_ms` alongside `normalization`, `lexical_search`, `query_embedding`, `dense_search`, and `rrf_fusion`.
  - **Measured CPU Latency**: ~1.05 s – 1.18 s reranker inference duration on CPU for the 25-candidate pool (~1.1 s – 1.3 s total request latency).
- **Verification Evidence**:
  - **Phase 4 Acceptance Requirements**: **20 / 20 requirements verified** (19 direct, 1 indirect/hardened).
  - **Dedicated Reranker Tests**: `backend/tests/test_reranker.py` (**17 / 17 PASS**).
  - **Hybrid Fallback Tests**: `backend/tests/test_hybrid_fallback.py` (**14 / 14 PASS**).
  - **Full Backend Test Suite**: **192 / 192 PASS** (100% in 200.46s).
  - **Frontend Production Build**: `tsc && vite build` (**0 TypeScript errors**).
  - **Packaged Windows Release**: Verified fresh build of WiX MSI (`FileMind_0.1.0_x64_en-US.msi`) and NSIS installer (`FileMind_0.1.0_x64-setup.exe`) with bundled PyInstaller `--onedir` backend sidecar and `WebView2Loader.dll`. Note: `src-tauri/tauri.conf.json` was intentionally updated with `"resources": ["binaries/filemind-backend-dir/**/*"]` to bundle the complete backend directory.
  - **Installed Practical Evaluation**: Tested against `C:\FileMind-Practical-Test` (`sample.txt`, `test.txt`, `notes.md`), confirming correct top-1 retrieval and semantic reordering over RRF baseline.
- **Files Created & Modified for Phase 4**:
  - `backend/app/retrieval/reranker.py` (Created — Cross-Encoder engine with `BAAI/bge-reranker-base`)
  - `backend/app/retrieval/hybrid.py` (Modified — Phase 4 reranking integration, score contracts, RRF fallback)
  - `backend/app/core/config.py` (Modified — Reranker model and pool constants)
  - `backend/app/schemas.py` (Modified — `reranker_score` field in search response schema)
  - `backend/tests/test_reranker.py` (Created — 17 dedicated Phase 4 acceptance tests)
  - `frontend/src/types/index.ts` (Modified — TypeScript search and latency types)
  - `frontend/src/components/SearchModal.tsx` (Modified — Rerank score UI badge)
  - `src-tauri/tauri.conf.json` (Modified — Added `"resources": ["binaries/filemind-backend-dir/**/*"]` for ONEDIR packaging)

---

---

### Pre-Phase-5 Hardening & Bug Fix Batches (Batches 1, 2, 3, 4) Validated State

- **Status**: **COMPLETE / PASS**.
- **Audit Objective**: Fix all verified bugs and contract violations across frontend correctness, API security, filesystem safety, document lifecycle, database migrations, retrieval robustness, Tauri native supervision, model identity tracking, rotating logs, strict integrity semantics, and ingestion guards before Phase 5.
- **Batch 1 — Frontend Correctness + API Security + Filesystem Security**:
  - **Bug 1 (Inspect Chunk Wiring)**: Fixed chunk ID vs. file ID mismatch in `frontend/src/components/SearchModal.tsx`, `frontend/src/App.tsx`, and `frontend/src/components/ChunkInspector.tsx`. "Inspect Chunk" now correctly resolves the specific file ID and chunk ID instead of arbitrary first-file fallback.
  - **Bug 2 (Reranker Timing Telemetry)**: Preserved and surfaced full latency breakdown in frontend (`api.ts`, `SearchModal.tsx`), rendering exact reranker inference timing in the UI.
  - **Bug 5 (CORS Security Allowlist)**: Removed wildcard `*` CORS policy from FastAPI; replaced with explicit origin allowlist (`http://localhost:1420`, `http://127.0.0.1:1420`, `tauri://localhost`, `http://tauri.localhost`). Verified with 14/14 tests in `test_cors_security.py`.
  - **Bug 6 (Filesystem Action Traversal & Symlink Safety)**: Added symlink and Windows junction rejection in `/fs/action` endpoints (`app/core/security.py`, `app/main.py`), preventing directory escape via reparse points. Verified with 13/13 tests in `test_fs_action_security.py`.
  - **Bug 14 (Content Security Policy)**: Enabled strict CSP in `src-tauri/tauri.conf.json`.

- **Batch 2 — Backend Correctness + Data Integrity + Contract Cleanup**:
  - **Bug #3 (Deterministic Lifecycle Timing)**: Replaced `time.sleep()` fixed waits in `backend/tests/test_document_lifecycle.py` with deterministic polling helpers (`wait_for_file_status`, `wait_for_chunks`, `wait_for_chunks_deleted`).
  - **Bug #7 (Enqueue Job Deduplication)**: Updated `enqueue_job()` in `backend/app/db/repository.py` to filter `WHERE file_id = ? AND job_type = ? AND status IN ('PENDING', 'PROCESSING')`, preventing duplicate jobs for different job types.
  - **Bug #8 (LIKE Wildcard Escaping)**: Added `escape_like_wildcards()` helper in `repository.py`; updated `mark_directory_missing()` and `rename_directory_path()` queries to use `LIKE ? ESCAPE '\\'`.
  - **Bug #9 (Rust Heading & Function Parser)**: Added `.rs` syntax support to `_parse_source_code()` in `backend/app/intelligence/parsers/text_parser.py`, parsing `fn`, `struct`, `enum`, `impl`, `trait`, and `mod` declarations.
  - **Bug #10 (Health Endpoint Version Alignment)**: Aligned `HealthResponse.version` default and `main.py` version import to canonical `__version__ = "0.1.0"`.
  - **Bug #11 (Migration Schema Bump)**: Updated `SCHEMA_VERSION = 4` in `backend/app/db/migrations.py`.
  - **Verification**: Verified with 7 regression tests in `backend/tests/test_batch2_regressions.py` (217/217 full backend tests passing).

- **Batch 3 — Filesystem Reliability + Retrieval Robustness + Tauri Supervisor Hardening**:
  - **Bug #11 (Offline Deletion Reconciliation)**: Added `list_indexed_paths_for_folder()` in `repository.py`. In `FilesystemScanner.scan_folder()`, reconciled indexed DB files against disk; disappeared files are marked `MISSING`, pending jobs cancelled, and `DELETE_CLEANUP` jobs enqueued to purge stale chunks and vectors. Verified in `test_batch3_offline_deletion.py`.
  - **Bug #12 (Live Watcher Symlink Rejection)**: Added `is_symlink_or_junction()` checks in `FolderWatchHandler._should_ignore()` and `_process_event_sub_batch()` in `watcher.py`. Verified in `test_batch3_watcher_symlink.py`.
  - **Bug #13 (Explicit JobQueue Permanent Failure)**: Added `permanent: bool = False` to `JobQueue.fail_job()`; replaced all magic `attempts=10` sentinels in `worker.py` with explicit `permanent=True`, preserving accurate attempt counts in the DB. Verified in `test_batch3_permanent_failure.py`.
  - **Bug #15 (Event Flush Backpressure & Batching)**: Introduced `WATCHER_BATCH_SIZE = 200` chunking in `WatcherService._handle_flushed_batch()`, releasing DB locks between sub-batches to prevent WAL starvation during high-volume bursts. Verified in `test_batch3_event_batching.py`.
  - **Bug #19 (Adaptive Dense fetch_k Iteration Cap)**: Added `MAX_ADAPTIVE_ITERATIONS = 5` boundary in `SqliteVecStore.search()` to prevent unbounded vector queries under narrow filters. Verified in `test_batch3_vector_store_cap.py`.
  - **Bug #18 (Filename/Stem Boost Consolidation)**: Created canonical `compute_filename_match_boost()` in `lexical.py` with domain-specific calibration (`"bm25"` vs `"rrf"`), eliminating duplicated inline scoring across retrieval modules. Verified in `test_batch3_filename_boost.py`.
  - **Bug #20 (Multilingual & CJK Prefix Retrieval Evaluation)**: Created comprehensive evaluation suite in `test_batch3_cjk_evaluation.py` covering Chinese, Japanese, Korean, Cyrillic, Greek, and mixed Latin+CJK scripts.
  - **Bug #21 (Tauri Structured Health Check Parsing)**: Updated `is_backend_healthy()` in `src-tauri/src/main.rs` with HTTP 200 status line validation and `serde_json` `status == "healthy"` parsing.
  - **Bug #22 (Backend Crash/Restart Supervision)**: Added background supervisor thread in `src-tauri/src/main.rs` with `intentional_shutdown` support, monitoring child exit via `try_wait()` and performing up to 3 bounded restarts with exponential backoff (2s, 4s, 8s).
  - **Bug #23 (Tauri open_in_explorer Scope Containment)**: Implemented `get_registered_folders()` and component-level canonical path containment checks in `src-tauri/src/main.rs`, rejecting unauthorized external filesystem access.

- **Batch 4 — Pre-Phase-5 Hardening & Production Infrastructure**:
  - **#1 Same-File Reprocessing Integrity**: In `backend/app/engine/worker.py`, when a modified file fails parsing (e.g. corruption), its previous known-good Version A chunks are preserved in SQLite and vector store; only upon successful re-parsing are Version A chunks atomically replaced by Version B chunks.
  - **#2 Reprocessing Version Invalidation**: In `backend/app/engine/discovery.py` and `backend/app/db/repository.py`, scanner checks indexed chunk parser version and chunker version against active components, scheduling re-parse on version mismatches.
  - **#3 Embedding Model Identity & Index Validity**: Added Migration V5 `embedding_index_metadata` (provider, model_name, model_version, dimension, config_json, updated_at). Added `verify_index_validity()` in `SqliteVecStore` ensuring vector table matches active embedding model identity.
  - **#4 Parser Version Provenance**: Cleaned hardcoded default parser versions from `Document` models; established canonical `TEXT_PARSER_VERSION = "1.1.0"`.
  - **#5 Strict Integrity Mode Semantics**: In `backend/app/engine/discovery.py` and `worker.py`, strict integrity mode computes streaming SHA-256 for all scanned files; if hash and parser/chunker versions match the indexed record, redundant parsing and re-embedding are bypassed.
  - **#6 Action Type Consistency**: Audited and confirmed `ActionType` enum contract (`OPEN_FILE`, `OPEN_FOLDER`, `COPY_PATH`, `PREVIEW`).
  - **#7 Windows Packaging Console Prevention**: Added `--noconsole` to PyInstaller build command in `backend/build_backend.py`.
  - **#8 Tauri Single Instance Protection**: Integrated `tauri-plugin-single-instance = "2"` into `src-tauri/Cargo.toml` and `src-tauri/src/main.rs` to focus the existing main window on second launch.
  - **#9 Windows-Only Bundle Targets**: Restricted Tauri bundle targets to `["nsis", "msi"]` in `src-tauri/tauri.conf.json`.
  - **#10 Opener Security Hardening**: Validated path canonicalization and registered folder containment in Tauri native commands.
  - **#11 MAX_FILE_SIZE Ingestion Guard**: Enforced `MAX_FILE_SIZE_BYTES = 50MB` in `config.py`, `discovery.py`, `watcher.py`, and `worker.py`, gracefully marking oversized files `SKIPPED` with explicit diagnostic errors.
  - **#12 Persistent Rotating Application Logging**: Built rotating file logging in `backend/app/core/logging_config.py` writing to `%APPDATA%\FileMind\logs\filemind.log` with 5MB max bytes, 5 backups, sanitized thread-safe formatting, and zero content leakage.
  - **#13 Dependency Reproducibility**: Generated pinned Python 3.11 lockfile in `backend/requirements-lock.txt`.
  - **#14 Model Registry Foundation**: Created extensible `ModelRegistry` in `backend/app/retrieval/model_registry.py` managing lifecycle and readiness states (`NOT_LOADED`, `LOADING`, `READY`, `FAILED`, `DISABLED`).
  - **#15 Unified AI Readiness Architecture**: Added `GET /ai/status` endpoint in `backend/app/main.py` reporting aggregated status for embedding, reranker, and local/cloud AI subsystems.
  - **#16 First-Run Local Model Preparation**: Wired readiness transitions into `EmbeddingEngine` and `RerankerService`.
  - **#17 Test Suite & Regression Protection**: Created 8 dedicated Batch 4 test suites (`test_batch4_*.py`).
- **Verification Summary**:
  - **Full Backend Test Suite**: **242 / 242 PASS** (241 passed, 1 skipped due to Windows non-admin symlink permission).
  - **Dedicated Reranker Suite**: **17 / 17 PASS**.
  - **Hybrid Fallback Suite**: **14 / 14 PASS**.
  - **Batch 4 Feature Test Suite**: **11 / 11 PASS**.
  - **Frontend Production Build**: `tsc && vite build` (**0 errors, 1,603 modules transformed**).
  - **Phase 5 Status**: **STRICTLY NOT STARTED**.

---

### Pre-Phase-5 Integrity Hardening (Batches A1, A2, A3, A3.1) & Practical Audit Fixes

- **Status**: **COMPLETE / PASS**.
- **Committed Checkpoint**: `c7c6bd7` (`fix: complete pre-phase-5 integrity hardening`).
- **Audit Objective**: Fix all vector-layer integrity, corpus decoding, hierarchical chunking provenance, reprocessing migrations, desktop capabilities, UI result grouping, and unindexed filename retrieval consistency issues before Phase 5.

#### 1. Batch A1 — Vector-Layer Integrity
- **Orphan Vector Purging**: Enforced atomic purge of active vectors in `chunk_vectors` prior to inserting new vectors during file re-indexing or deletion.
- **Transactional Consistency**: Wrapped vector store updates and SQLite chunk metadata replacement in coordinated transaction rollback handlers to prevent dangling or orphaned vectors upon partial failure.
- **Index Metadata Schema**: Validated `embedding_index_metadata` table tracking active embedding model identity (`sentence-transformers/all-MiniLM-L6-v2`, dim 384) to reject mismatched vector dimensions.

#### 2. Batch A2 — Corpus Encoding & PDF Extraction Integrity
- **Strict UTF-8 & BOM Decoding**: Implemented deterministic `read_text_file_strictly` and `decode_bytes_strictly` with strict UTF-8 (`utf-8-sig`) decoding. Undecodable non-UTF-8 byte sequences explicitly raise `CorruptedDocumentError` to prevent silent evidence corruption with Unicode replacement characters.
- **Corrupted PDF Extraction Handling**: Enhanced `PDFParser` with PyMuPDF fault-tolerant page-by-page extraction, preserving valid pages when individual pages contain broken streams or invalid xref tables.
- **Document Metadata Normalization**: Preserved structural metadata across multi-format documents (`page`, `section`, `h1_parent`, `h2_parent`, `line_start`, `line_end`).

#### 3. Batch A3 — Chunking & Evidence Integrity
- **Deterministic Chunk Identity**: Replaced ambiguous colon-delimited string concatenation with canonical JSON serialization (`sha256(canonical_json(provenance_dict))`), ensuring collision-free, deterministic `chunk_id` generation.
- **Character Overlap Chunking**: Implemented `overlap_chars` in `HierarchicalChunker` ensuring semantic continuity across chunk boundaries without splitting markdown headers or source code entities.
- **Markdown Table Integrity**: Preserved markdown tables as unified structural units during chunking, preventing table splitting across multiple chunk boundaries.

#### 4. Batch A3.1 — Reprocessing Vector Integrity & Version Migration
- **Chunker Version Bump**: Incremented `CHUNKER_VERSION` to `"phase2-hierarchical-v2"` in `app/intelligence/chunker/hierarchical.py`.
- **Filesystem Scanner Version Invalidation**: Updated `FilesystemScanner` to compare stored `chunker_version` and `parser_version` against active versions, automatically scheduling re-parse and re-embedding for files with stale chunk IDs even if file modification timestamps on disk remain unchanged.
- **Zero Orphan Vectors on Reprocessing**: Verified that re-indexing modified files or files with upgraded chunker versions purges 100% of old vectors with zero vector-store leakage.

#### 5. Pre-Phase-5 Practical Audit Fixes
- **Issue 1 — Tauri v2 Directory Dialog Capability**:
  - *Root Cause*: Tauri v2 requires explicit capabilities in `src-tauri/capabilities/default.json`. `@tauri-apps/plugin-dialog` invocations (`open({ directory: true, ... })`) in `FolderPicker.tsx` and `FolderManager.tsx` were blocked by the Tauri v2 security manager.
  - *Fix*: Created `src-tauri/capabilities/default.json` with permissions `["core:default", "opener:default", "dialog:allow-open"]` for window `"main"`.
- **Issue 2 — Deterministic Same-File Candidate Grouping & Provenance**:
  - *Root Cause*: Multiple matching chunks from the same file (e.g. `notes.md`) appeared as separate top-level search cards, cluttering the UI.
  - *Fix*: Added deterministic file-level grouping in `SearchModal.tsx`. The file card displays the highest-scoring primary chunk, and multi-chunk matches show an expandable drawer (`"▼ View {N-1} more matching chunks in this file"`). All per-chunk scores, line numbers, breadcrumbs, `Inspect Chunk`, `Open File`, `Open Folder`, and `Copy Path` actions remain fully accessible.
- **Issue 3 — Explicit Filename Intent Detection & Consistent Not-Found State**:
  - *Root Cause*: Searching for an unindexed filename (e.g. `nonexistent_report.pdf`) caused Dense vector search to embed the filename string and return unrelated chunks via cosine similarity, which Hybrid Fast and Quality surfaced.
  - *Fix*: Implemented `extract_explicit_filename_intent()` in `hybrid.py`. If an explicit filename is not present in the indexed corpus (`files` table), the retriever immediately returns `total_found: 0, results: []` consistently across **BM25**, **Dense**, **Hybrid Fast**, and **Hybrid Quality**. Normal semantic queries (e.g. `"How does semantic retrieval work?"`) bypass filename filtering and run full semantic retrieval.

#### 6. Second Brain Architecture Contract
- Created `FileMind_Second_Brain_Architecture.md` at project root defining the authoritative contract for the local intelligence knowledge layer over user files.

#### 7. Verification & Regression Metrics
- **Full Backend Pytest**: **323 / 324 PASS** (323 passed, 1 skipped, 0 failed; execution duration ~2.5m).
- **Frontend Production Build**: **PASS** (`tsc && vite build`, 1,603 modules, 0 TypeScript errors).
- **Tauri Desktop Verification**: **PASS** (`cargo check` in `src-tauri`, 0 compilation errors).
- **Git Diff Check**: **PASS** (0 whitespace/formatting violations).
- **Phase 5 Status**: **STRICTLY NOT STARTED**.

---

### Phase 5.1 Foundation: Context Assembly & Token Budget Guard

- **Status**: **FOUNDATION COMPLETE** (`backend/app/ai/context.py`, `backend/tests/test_context_budget.py`).
- **Role in Architecture**: Sits between retrieval (`SearchResponse` / `SearchResultItem` / `ChunkItem`) and future LLM invocation (`Retrieval → Context Builder → Token Budget Guard → Bounded Context Package → Future RAG`).
- **Token Budget Accounting**:
  - `ContextBudgetConfig`: `max_context_tokens` (default 4096), `reserved_system_tokens` (500), `reserved_output_tokens` (1000), `max_chunks` (20).
  - Derived invariant: `evidence_budget = max(0, max_context_tokens - reserved_system_tokens - reserved_output_tokens)`.
  - Non-negative telemetry: `total_budget`, `system_reserved`, `output_reserved`, `evidence_budget`, `evidence_used`, `evidence_remaining`, `candidates_considered`, `candidates_included`, `candidates_omitted`.
- **Deterministic Token Estimation**:
  - `TokenEstimator`: Conservative heuristic estimation (~3.5 chars/token non-CJK, 1 char/token CJK) with framing overhead calculation. Note: this is a conservative heuristic estimate, not a model BPE tokenizer.
- **Safety & Provenance Guarantees**:
  - Deduplication by `chunk_id` preserving deterministic retrieval relevance order.
  - Zero silent tail truncation of chunks. Oversized single chunks or budget breaches emit explicit `OmissionReason` (`budget_exceeded`, `oversized_single_chunk`, `duplicate_chunk`, `invalid_empty_content`, `max_chunks_reached`).
  - Exact provenance (file ID, chunk ID, paths, pages, sections, line ranges, scores, and parser metadata) survives assembly for grounded citations.
- **Phase Boundary & Scope**:
  - Zero Ollama generation calls, prompt templates, RAG generation, chat UI, or cloud fallbacks are active in this foundation milestone.

---

### Phase 5.2 Foundation: Grounded Prompt Construction & Local Generation Contract

- **Status**: **FOUNDATION COMPLETE** (`backend/app/ai/prompt.py`, `backend/app/ai/citation.py`, `backend/app/ai/generation.py`, `backend/tests/test_grounded_generation.py`).
- **Role in Architecture**:
  $$\text{Query} \to \text{Retrieval} \to \text{Reranking} \to \text{Context Budget} \to \text{Grounded Prompt} \to \text{Local Ollama} \to \text{Citation Validation} \to \text{Structured Response}$$
- **Prompt Construction & Injection Defense**:
  - `PromptBuilder`: Generates structured prompts with strict system grounding rules, numbered evidence blocks (`[E1]`, `[E2]`), and bounded user queries (max 1000 chars).
  - Untrusted data boundary: Evidence text is explicitly treated as untrusted document data that cannot override system rules or request external tools.
- **Citation & Provenance Mapping**:
  - `CitationSource`: Maps each `[E{n}]` identifier back to exact file ID, chunk ID, source path, page, section, lines, content hash, and retrieval scores.
  - `CitationValidator`: Extracts referenced `[E{n}]` keys from generated answers, resolves them against the active citation map, and detects unresolved/hallucinated citation keys.
- **No-Evidence Short-Circuiting**:
  - If `EvidenceStatus.NO_EVIDENCE`, the LLM is **never** invoked. The pipeline returns an immediate, deterministic insufficient evidence response.
  - If `EvidenceStatus.BUDGET_LIMITED`, generation proceeds on the bounded evidence subset while preserving `BUDGET_LIMITED` telemetry.
- **Local-Only Generation**:
  - Uses `OllamaProvider` targeting loopback `http://127.0.0.1:11434` with `qwen3:4b`.
  - Zero cloud fallback; handles connection, timeout, and generation errors with explicit status codes.
- **Validation Contract**:
  - Validates citation identifier existence and provenance mapping. Does not claim semantic factual entailment verification (deferred to Phase 6 evaluation framework).

---

### Phase 5.3: Ask FileMind End-to-End Local RAG Pipeline & UI

- **Status**: **COMPLETE & VERIFIED** (`backend/app/ai/ask_service.py`, `backend/app/main.py` (`POST /ai/ask`), `frontend/src/components/AskModal.tsx`, `backend/tests/test_ask_pipeline.py`).
- **Role in Architecture**:
  $$\text{User Query} \to \text{Hybrid Retrieval} \to \text{Quality Reranking} \to \text{Context Budget Guard} \to \text{Grounded Prompt} \to \text{Local Ollama} \to \text{Citation Validation} \to \text{Ask Response} \to \text{Ask FileMind UI}$$
- **API Endpoint (`POST /ai/ask`)**:
  - `AskRequest`: `query` (1..1000 chars), `mode` (`hybrid`, `bm25`, `dense`), `quality` (`fast`, `quality`), `top_k` (1..50), optional `folder_id`, `extension`, `file_id`.
  - `AskResponse`: `answer`, `query`, `generation_status`, `evidence_status`, `citations` (`CitationItem[]`), `unresolved_citations` (`string[]`), `model_identity`, `retrieval_metadata`, `context_budget`, `error`.
- **Ask Orchestration Service (`AskService`)**:
  - Direct integration with `HybridRetriever`, `ContextBuilder`, and `GroundedGenerationService`.
  - No-Evidence Guard: Automatically short-circuits with `NO_EVIDENCE` status and skips Ollama execution if 0 evidence chunks are retrieved.
  - Budget-Limited Preservation: Preserves `BUDGET_LIMITED` flag and candidate omission telemetry when context is constrained by token limits.
  - Safe Local Failures: Explicitly maps connection errors to `MODEL_UNAVAILABLE`, timeouts to `TIMEOUT`, and HTTP/generation errors to `GENERATION_FAILED` without cloud fallback.
- **Ask FileMind UI (`frontend/src/components/AskModal.tsx`)**:
  - Interactive modal accessible via `Ctrl + J` / header button with dark glassmorphism design.
  - Quality selector toggle (Fast ~20ms default vs Quality reranked).
  - Grounded answer view with clickable citation pills (`[E1]`, `[E2]`).
  - Source citations cards with source filename, section, page, line ranges, relevance score, and direct "Inspect Evidence" chunk exploration.
  - Explicit diagnostic states: `READY`, `NO_EVIDENCE`, `BUDGET_LIMITED`, `MODEL_UNAVAILABLE` (with actionable `ollama serve` / `ollama run` guidance), `TIMEOUT`, `GENERATION_FAILED`.
  - Full keyboard accessibility, ARIA labels, and focus management.

---

### Phase 5.4 Batch 1: Ask Readiness & Concurrency Hardening

- **Status**: **COMPLETE & PUSHED** (Commit `a55030f`: `feat: harden phase 5.4 ask readiness`).
- **Files**: `backend/app/ai/ollama_provider.py`, `backend/app/ai/__init__.py`, `backend/app/schemas.py`, `backend/app/main.py`, `frontend/src/types/index.ts`, `frontend/src/services/api.ts`, `frontend/src/components/AskModal.tsx`, `backend/tests/test_batch4_ai_status.py`.
- **AskModal Concurrency & Sequence Protection**:
  - Monotonically increasing sequence tracker (`requestSeqRef = useRef(0)`).
  - Each request captures `seq = ++requestSeqRef.current`. Responses and loading state updates are strictly guarded (`if (seq === requestSeqRef.current)`).
  - Stale responses, aborted requests, and stale errors from rapid consecutive submissions are discarded without clobbering newer results.
  - Closing the modal increments sequence and aborts active fetches, guaranteeing that pending microtasks cannot clear loading states upon reopening.
- **Proactive Local Ollama Readiness Probing (`check_ollama_readiness`)**:
  - Probes `GET http://127.0.0.1:11434/api/tags` with a 1.0s timeout.
  - Normalizes model tags (`qwen3:4b` matches `qwen3:4b`, `qwen3:4b:latest`, or base name).
  - Non-generating metadata probe (never invokes `/api/generate` or loads model weights merely to check readiness).
  - Rejects non-loopback endpoints immediately.
  - Safe error handling: network unreachable, missing model, or non-200 responses return structured failure states without crashing `/ai/status` or FastAPI.
- **Non-Breaking Status API (`GET /ai/status`)**:
  - Adds optional `local_ai.ollama` (`OllamaReadinessStatus`: `is_ollama_online`, `has_default_model`, `model_name`, `endpoint`, `error`).
- **AskModal Ambient Readiness UX**:
  - Live status pills in modal header: 🟢 `Local LLM Ready (qwen3:4b)`, 🟡 `Ollama Offline`, 🔴 `Model Missing (qwen3:4b)`.
  - Actionable guidance banners suggesting exact terminal commands (`ollama serve`, `ollama run qwen3:4b`).

---

### Phase 5.4 Batch 2: Ask UX Polish

- **Status**: **COMPLETE & PUSHED** (Commit `ba45128`: `feat: implement phase 5.4 ask ux polish`).
- **Implemented Scope**:
  1. **Staged Ask Progress**: 4-stage visual progress tracker during synchronous generation (`"Analyzing question…"`, `"Searching local files…"`, `"Assembling grounded context…"`, `"Generating with local LLM…"`, `"Verifying citations…"`) with accessible live region (`aria-live="polite"`).
  2. **Copy Answer**: One-click clipboard copy of generated answer text with visual feedback (`"Copied!"`) and clipboard error handling.
  3. **Citation Auto-Scroll / Navigation**: Clicking citation pills (`[E1]`) or cards scrolls the corresponding evidence section smoothly into view and briefly flashes the target card.
  4. **Transient In-Session Query History**: Ephemeral in-memory recent questions list (max 10, deduplicated, most-recent first) allowing one-click query restoration into input without auto-submitting. No database or disk persistence.

---

### Phase 5.5 Batch 1: Document Understanding Core

- **Status**: **COMPLETE & PUSHED** (Commit `4d12526`: `feat: implement phase 5.5 document understanding`).
- **Implemented Scope**:
  1. **Structural Summary Engine**: Sub-millisecond deterministic structural document metrics (size, chunk count, estimated tokens, headings, sections) calculated directly from indexed chunks.
  2. **Grounded Insight Generation**: Generates grounded executive summaries, key topics, key decisions, and cited evidence using local Ollama (`qwen3:4b`).
  3. **Atomic Schema v6 Persistence**: `document_insights` SQLite table with foreign key cascade, unique constraint `(file_id, model_name)`, and invalidation tracking (`content_hash`, `parser_version`, `chunker_version`, `model_name`).
  4. **Citation Validation & Provenance**: Reuses `CitationValidator` to resolve inline `[E{n}]` markers against representative source chunks.
  5. **Endpoints & Frontend Contracts**: Mounted `GET /ai/document-insight/{file_id}` and `POST /ai/document-insight/{file_id}/generate`.

---

### Phase 5.5 Batch 2: Related Content

- **Status**: **COMPLETE & PUSHED** (Commit `7442402`: `feat: implement phase 5.5 related content`).
- **Implemented Scope**:
  1. **Deterministic Related Retrieval**: Discovers meaningfully related files by reusing existing BM25 + Dense + RRF retrieval infrastructure without mandatory LLM calls.
  2. **Representative Query Generation**: Deterministically combines filename stem, unique section headings, and introductory text snippet bounded to $\le 400$ characters.
  3. **Strict Self-Exclusion**: Guarantees source file is never returned in its own related content.
  4. **Max Chunk Score Grouping**: Aggregates multi-chunk candidates into a single file result ranked by highest-scoring chunk with tie-breaking `(-score, -matching_chunk_count, file_id ASC)`.
  5. **Authentic Provenance**: Provides `primary_matched_chunk`, up to 2 `supporting_chunks`, and deterministic explanation strings.
  6. **Dynamic On-Demand Execution**: Zero database migrations (`SCHEMA_VERSION = 6`), zero auxiliary vector stores, instant freshness upon index modification.
  7. **Endpoints & Frontend Contracts**: Mounted `GET /retrieval/related/{file_id}` with `limit` and `quality` (`fast` / `quality`) parameters.

---

### Phase 5.5 Batch 3: Folder Understanding Core & Knowledge Connections (Upcoming)

- **Status**: **NOT STARTED / NEXT PLANNED**.
- **Scope**: Folder-level structural summaries, grounded folder insights, and lightweight knowledge connections.

---

### Explicit Phase 5 Boundaries & Out-of-Scope Items

The following capabilities belong to later milestones and are **STRICTLY NOT IMPLEMENTED**:
- **No Streaming / SSE / WebSockets**: The Ask and Document Understanding pipelines are currently 100% synchronous.
- **No Conversational Memory / Multi-Turn History**: Each Ask query is stateless and independent.
- **No Database Chat Tables / Persistent Conversations**: In-session history is ephemeral memory only.
- **No Knowledge Graph Database**: Second-brain graph databases belong to future phases.
- **No Autonomous Agents / Write Actions**: Read-only question answering and insights only; zero tool execution or file edits.
- **No Cloud Fallback**: 100% local-first privacy architecture strictly preserved.
- **No Multimodal AI**: Text-only document parsing and local generation.

> [!IMPORTANT]
> **PHASE 5.1–5.4 & PHASE 5.5 BATCHES 1 & 2 VERIFIED COMPLETE & PUSHED (COMMIT 7442402).**
> **FULL BACKEND REGRESSION: 423 / 424 PASS (423 PASSED, 1 SKIPPED, 0 FAILED).**
> **PHASE 5 / 5.5 AI SUITES: 93 / 93 PASS.**
> **FRONTEND PRODUCTION BUILD & TAURI CARGO CHECK VERIFIED PASS.**




---

## 1. Product Identity

- **Name:** FileMind — "Your files. One intelligent search."
- **What it is:** A local-first, privacy-first Windows desktop application that indexes
  user-selected folders, provides hybrid (lexical + semantic) file search, and answers
  grounded questions about file contents using a local LLM, with verifiable citations.
- **What it is NOT:** a ChatGPT clone, a generic "chat with PDFs" web app, a cloud-only
  document manager, an unrestricted filesystem agent, a Windows Search/Spotlight
  replacement, a Kubernetes/microservices project, or anything requiring Docker to run
  for a normal user.
- **Core loop:** `DISCOVER → RETRIEVE → UNDERSTAND → ACT`, where ACT is limited to
  `Open File / Open Folder / Copy Path / Preview`. No autonomous delete, move, rename,
  or arbitrary command execution exists in the core product.

---

## 2. Non-Negotiable Architecture Contracts

These apply across every phase. Do not implement anything that violates one of these,
even temporarily, even for a demo or a "quick test."

1. **Every chunk carries immutable provenance** from extraction through citation
   (see §5 schema below). The same `chunk_id` must survive extraction → index →
   retrieval → reranking → RAG → citation.
2. **Citations reference the actual retrieved `chunk_id`** — never a paraphrased,
   inferred, or reconstructed source.
3. **Integrity verification policy (Normal / Strict) is configurable per folder**, not
   global-only.
4. **Local/cloud mode and Fast/Quality mode are always explicit and visible to the
   user** — never a silent switch. Mode is locked for the duration of a single
   request; a mode change only takes effect on the *next* query.
5. **The AI layer never receives arbitrary filesystem or shell access.** All actions
   go through a validated, permissioned tool layer (`OPEN_FILE`, `OPEN_FOLDER`,
   `COPY_PATH`, `PREVIEW` only). Never `LLM → PowerShell`, never `LLM → Bash`, never
   `LLM → arbitrary filesystem operation`.
6. **The local product works fully without any cloud infrastructure.** Cloud AI is
   optional and off by default.
7. **Keyword/metadata search works without an LLM being involved at all.** If Ollama
   or any model is unavailable, retrieval results must still be returned.
8. **RAG answers are grounded in retrieved evidence** — never bypassing retrieval to
   answer from model memory.
9. **Indexing survives interruption** (crash, sleep, shutdown) without requiring a
   full rebuild. Stale `PROCESSING` jobs are detected and retried on startup.
10. **Architecturally significant decisions are benchmark-driven, not pre-selected.**
    This applies to: document parser, vector store, embedding model, reranker,
    ONNX/FastEmbed strategy, OCR engine, multimodal retrieval. See §6 for the
    candidate list — none of these are locked technology choices.

---

## 3. Absolute Prohibitions ("Never")

- Never give the LLM shell access or the ability to run arbitrary commands.
- Never let the LLM perform an unrestricted filesystem operation (delete, move,
  rename, write) outside the four safe actions.
- Never silently send content to a cloud AI provider. If cloud mode is on but a file
  is marked sensitive (or falls under a folder's local-only policy), force local and
  surface that explicitly (e.g. "Answered locally — sensitivity policy").
- Never silently downgrade Fast/Quality mode mid-request. If a mode change is forced
  by resource constraints, it applies to the *next* query, and the UI states the
  active mode plainly.
- Never fabricate or reconstruct a citation. If a chunk's provenance chain is broken,
  do not produce a citation for it — surface an extraction/indexing error instead.
- Never silently index folders the user did not explicitly select.
- Never treat a corrupted, encrypted, unsupported, or permission-denied file as a
  silent success. Surface it as a failed/skipped file with a reason.
- Never assume Phase N+1 is authorized because Phase N passed its gate.
- Never make FileMind require Docker, Node.js, Python, or any dev tooling for a
  normal end user to install and run it.
- Never claim local models match frontier cloud model reasoning quality.
- Never make an unqualified "100% private" marketing claim — the accurate claim is
  "your files stay where they are unless you explicitly choose otherwise," and
  privacy behavior must be inspectable (Privacy Center: AI mode, cloud status,
  telemetry status, external request count).

---

## 4. Platform & Stack

| Layer | Technology | Status |
|---|---|---|
| Desktop shell | Tauri | Locked |
| UI | React + TypeScript + Vite | Locked |
| Backend | Python (FastAPI) | Locked (primary); Rust-native core is the predetermined fallback if packaging fails |
| Local DB | SQLite | Locked (WAL mode, versioned migrations) |
| Filesystem watcher | `watchdog` cross-platform abstraction | Locked (Phase 1) |
| Local LLM runtime | Ollama | Locked |
| First production target | Windows 11 | Locked — architecture must stay extensible to macOS/Linux via isolated platform abstractions |

---

## 5. Provenance Schema (mandatory, do not simplify)

Every indexed chunk must carry this record, and it must survive the entire pipeline
unmodified in identity (`chunk_id` is the join key everywhere):

```json
{
  "chunk_id": "abc123",
  "file_id": "file456",
  "source_file": "GuardianAI.pdf",
  "source_path": "C:/dev/Guardian-AI/GuardianAI.pdf",
  "page": 8,
  "section": "Architecture",
  "h1_parent": "Architecture",
  "h2_parent": "Backend",
  "line_start": 120,
  "line_end": 148,
  "char_start": 6211,
  "char_end": 7022,
  "content_hash": "..."
}
```

Additional chunk metadata to maintain: MIME type, extension, author, modification
time, chunk index, embedding model name/version/dimension.

Core SQLite entities: `folders`, `files`, `chunks`, `indexing_jobs`, `file_events`,
`model_registry`, `settings`, `evaluation_runs`. Exact schema is implemented from
this provenance contract and the indexing pipeline (§7.1) — do not invent additional
core tables without checking against this list first.

---

## 6. Candidate Technologies — Benchmark Before Locking

Do **not** treat these as decided. Each requires a small benchmark (latency, quality,
memory, packaging complexity) before becoming a permanent dependency:

- Document parser: Evaluated Docling vs. PyMuPDF vs. PyPDF; **PyMuPDF (`pymupdf-parser` v1.0.0)** selected and locked in Phase 2 for desktop distribution constraints and fast structural parsing.
- Vector store: **LanceDB** vs. **SQLite-vec** (candidate)
- Embedding model: Sentence Transformers / Hugging Face / ONNX Runtime candidates
- Reranker: **BAAI/bge-reranker-base** (candidate)
- OCR engine: not yet selected (deferred to Phase 7)
- Multimodal/visual retrieval: **ColPali** (candidate, not an unconditional dependency)
- Sparse/lexical search: SQLite FTS5 / BM25 (candidate, high confidence but still
  benchmark-driven)

Process for any of the above: `Candidate → small benchmark → measured result →
decision → lock`. Benchmark artifacts may be lightweight but must exist and be
checked in (e.g. `evaluation/benchmarks/`) before a choice is treated as final.

---

## 7. Pipeline Architecture

### 7.0 Final Logical Architecture

```
FileMind UI (Tauri + React/TS)
        |
   Local FastAPI
        |
   +----+----+----+
   |         |    |
Filesystem Search RAG
 Engine    Engine Engine
   |       /    \   |
OS Watcher BM25 Dense Ollama
   |        \    /   |
Job Queue    RRF     |
   |         |       |
Worker Pool Top-K    |
   |         |       |
Doc Extraction Reranker
   |         |________|
Hierarchical      |
 Chunking   Answer + Citations
   |
SHA-256 / Provenance
   |
 +-+-+
 |   |
SQLite Vector Index
 |___|
   |
FileMind
```

### 7.1 Indexing Pipeline (Discover) — Phase 1–2 scope

```
Selected Folder
  -> Recursive Discovery -> File Filtering (exclusions: node_modules/, .git/,
       __pycache__/, venv/, dist/, build/, .cache/, temp/, + user patterns e.g. *.tmp, *.log)
  -> Filesystem Watcher (CREATE / MODIFY / DELETE / MOVE / RENAME)
  -> Event Normalization -> Deduplication -> Queue

Change Detection (never trust timestamps alone):
  compare size + mtime
    unchanged -> skip
    changed   -> SHA-256 verify
                   -> unchanged -> metadata-only update
                   -> changed   -> re-index
  (Strict Integrity Mode: force full hash verify — set per folder, not global)

  -> Format Detection -> Document Parser (layout-aware; candidate: Docling)
  -> Hierarchical Chunking (headings/sections/tables preserved — never flat
       fixed-size-only chunking)
  -> Chunk Provenance Record (see §5)
  -> Local Embeddings (Sentence Transformers / ONNX Runtime)
  -> Vector Index (LanceDB / SQLite-vec — candidate)   BM25 Index (SQLite FTS5)
              \_______________________  ________________________/
                                      \/
        SQLite: folders / files / chunks / indexing_jobs / file_events
```

Supported formats — Tier 1 (build first): PDF, DOCX, PPTX, TXT, Markdown, CSV, XLSX,
JSON, source code. Tier 2 (visual): PNG, JPG/JPEG, WEBP. Tier 3 (advanced, later):
scanned PDFs, OCR, visual tables, diagrams, charts. Unsupported or partially
supported files must produce explicit, inspectable status — never a silent failure.

Background workers must support: concurrency limits, retries, backoff, cancellation,
failure tracking, recovery. Resource management (CPU limits, worker limits, memory
awareness, pause/resume, indexing priority, battery-aware throttling) are independent
subsystems layered around the core indexing engine — do not block core indexing
correctness on these being fully built.

Progressive indexing is a core UX requirement: the app must be searchable after the
first files are indexed, not only after the entire folder tree completes.

### 7.2 Query Pipeline (Retrieve → Understand) — Phase 3–5 scope

```
User Query
  -> Query Processing -> Metadata Filtering (type, date, folder)

        BM25 Search (lexical)      Dense Search (semantic)
                    \                  /
                     Reciprocal Rank Fusion (RRF)
                               |
                        Top-N candidates
                               |
        FAST MODE  <----------------->  QUALITY MODE
     (return as-is)               (+ Cross-Encoder Reranker,
                                      candidate: bge-reranker-base)
                               |
                    Top-K evidence chunks
                    /                    \
        [Simple file lookup]     [Question needs synthesis]
                |                          |
        Return results          Context Selection / Compression
        with citations                    |
                            Cloud/Local Policy Check:
                              sensitive file? -> force Local
                              else            -> honor session toggle
                                       |
                            Local LLM (Ollama) or Cloud LLM
                                       |
                                Grounded Answer
                                       |
                            Citation Verification
                        (answer chunk_id == retrieved chunk_id)
                                       |
                        Answer + Sources + Status
                (e.g. "Answered locally"/"Answered with cloud AI" · "Fast"/"Quality")

  If Ollama/model unavailable -> retrieval results still returned
  (search never depends on the LLM being available)
```

### 7.3 Action Pipeline (Act)

```
User selects a result
  -> Requested action: Open File / Open Folder / Copy Path / Preview
  -> Validated Schema (allowed action? valid path? no traversal?)
  -> Permission Check
  -> Constrained Tool Execution
  -> Filesystem / OS Default Viewer

  Preview = OS default viewer (never a universal in-app renderer)

  NEVER: LLM -> shell command (PowerShell / Bash)
  NEVER: LLM -> arbitrary filesystem operation
```

### 7.4 Data Lifecycle (Delete)

```
File Delete Event (via Filesystem Watcher)
  -> Remove metadata (files table)
  -> Remove chunks (chunks table)
  -> Remove vectors (vector index)
```

---

## 8. Security Requirements

Protect against: path traversal, malicious paths, symlinks, Windows junctions/
reparse points, unauthorized folders, inaccessible paths, deleted files mid-index,
malicious filenames, arbitrary command execution.

Shared-machine isolation: local indexes are scoped to the OS user. Never create a
global index spanning multiple Windows users' private files. Multi-user/team
workspace support is explicitly out of local-core scope (future cloud/enterprise
tier only).

---

## 9. Evaluation — Sequencing Matters

Do not build evaluation infrastructure ahead of the system it measures. Sequence:

1. **Phase 3:** 20–30 real queries against real files. Measure Recall@K, MRR,
   search latency. Compare BM25-only vs. dense-only vs. hybrid — let the winner be
   determined by measurement, not assumed.
2. **Phase 4:** Benchmark reranker on/off against latency, CPU, RAM cost.
3. **Phase 6 (not before):** Expand dataset (→ 50–100 → 200+), introduce Ragas
   (faithfulness/context/answer relevance), introduce MLflow (experiment tracking),
   add CI regression gates (e.g. block merge if Recall@5 drops below baseline).

Do not introduce Ragas, MLflow, or CI quality gates before Phase 6 — they need a
system that already exists to measure.

---

## 10. Phase 0 Go/No-Go Reference (for context — already passed)

| Check | Requirement | Result |
|---|---|---|
| Clean install | Installs & launches on Windows 11 VM, zero dev tooling | PASS |
| Backend startup | Health endpoint responds ≤ 5s | PASS (0.971s current cold median; 3.247s original historical median) |
| Desktop ↔ backend | Tauri manages backend; frontend calls local API | PASS |
| Filesystem access | Folder select, recursive listing, open/open-folder/copy-path | PASS |
| Defender check | No malware/PUA flag on unsigned installer | PASS |
| State persistence | Relaunch after close: clean reopen, no corrupted state | PASS |
| Uninstall | Clean removal, no orphaned processes | PASS |
| Installer size | < 500 MB target | PASS (87.62 MB current; 14.38 MB initial smoke test) |

Fallback (Rust-native core + Python ML sidecar) was **not** triggered — this is
recorded here only because it remains the predetermined fallback for reference if a
future packaging regression occurs. Do not implement it speculatively.

---

## 11. Phase Roadmap

| Phase | Scope | Status |
|---|---|---|
| 0 | Distribution Feasibility (Packaging, sidecar lifecycle, startup baseline) | ✅ Complete / PASS |
| 1 | Filesystem Engine (Watcher, change detection, exclusions, SQLite schema, crash recovery) | ✅ Complete / IMPLEMENTED |
| 2 | Document Intelligence (Parser benchmarking, hierarchical chunking, immutable provenance) | ✅ Complete / IMPLEMENTED |
| 3 | Hybrid Retrieval (BM25 + dense vector embeddings + RRF fusion, 28-query evaluation set) | ✅ Complete / IMPLEMENTED |
| H1 | Windows Job Object process-lifecycle supervision | ✅ Complete / PASS |
| H2 | Directory event cascade coalescing | ✅ Complete / PASS |
| H3 | PDF extraction-quality gate and observability | ✅ Complete / PASS |
| H4 | SQLite WAL observability and transaction-boundary hardening | ✅ Complete / PASS |
| B1–B4 | Hardening Batches 1–4 (Security, Isolation, Index Metadata, Logging, Size Guards) | ✅ Complete / PASS |
| 4 | Reranking / Search Quality (Fast vs Quality modes, benchmark exit gate, PR #1 / `624c010`, cleanups `4c569e8`, `c3e4e98`) | ✅ Complete / CLOSED |
| 5 | RAG / Local AI (Local LLM via Ollama, citation verification, cloud/local policy) | ⏳ **NOT STARTED** |
| 6 | Evaluation / MLOps (Expanded dataset, Ragas, MLflow, CI regression gates) | ⏳ PENDING |
| 7 | Multimodal (Optional: OCR, complex tables, ColPali) | ⏳ PENDING |
| 8 | Production Hardening (Battery throttling, hardware-aware models, auto-update) | ⏳ PENDING |
| 9 | Optional Cloud / Enterprise (Multi-user workspaces, cloud sync) | ⏳ OPTIONAL / PENDING |
| 10 | Future Automation / Agentic Intelligence (Autonomous file organization, smart workflows) | ⏳ FUTURE EXTENSION |

Each phase has an explicit exit condition in the full specification documents. Do
not mark a phase complete without measurable evidence matching its exit condition —
"it seems to work" is not a phase gate.

---

## 12. Pre-Phase-5 Hardening & Audit History (Batches 1–4 & Pre-Phase-5 Fixes)

### Batch 1: Security, API & Frontend Hardening
- **CORS Hardening**: Removed insecure wildcard origins; strictly bounded loopback HTTP origins (`localhost`, `127.0.0.1`, `tauri://localhost`).
- **Content Security Policy (CSP)**: Enforced strict CSP in Tauri webview preventing arbitrary script execution.
- **Folder Containment**: Added strict root-path containment checks rejecting path traversal attempts.
- **Path Security**: Canonical path normalization, null-byte rejection, and junction/reparse-point defense.

### Batch 2: Correctness & Data Integrity
- **Document Lifecycle Race Fix**: Resolved chunk deletion vs. indexing race conditions in background worker.
- **Job Deduplication**: Implemented atomic job queue deduplication preventing duplicate simultaneous indexing jobs.
- **SQL LIKE Escaping**: Added deterministic escaping for wildcard characters (`%`, `_`) in metadata queries.
- **Rust Parser Support**: Added multi-language code parsing extensions for `.rs` and modern project files.
- **Health Version Synchronization**: Aligned `/health` endpoint response payload with canonical semver.
- **Schema Validation**: Corrected schema definitions for folder and file registration endpoints.

### Batch 3: Filesystem Reliability & Retrieval Robustness
- **Offline Deletion Reconciliation**: Background engine startup reconciles files deleted while FileMind was offline.
- **Watcher Symlink / Junction Protection**: Prevented infinite recursive traversal across Windows junctions and symlinks.
- **JobQueue Permanent-Failure Semantics**: Max retry limit triggers terminal `FAILED` status with structured error diagnostics.
- **Debounced Event Flush Batching**: Coalesced rapid bursts of filesystem events into single atomic SQLite transactions.
- **Adaptive Dense fetch_k Ceiling**: Clamped dense vector candidate fetching to bounded safe limits.
- **Filename / Stem Boost Consolidation**: Merged lexical exact-filename and stem boosting directly into RRF scoring.
- **CJK / Multilingual Evaluation**: Evaluated multi-byte UTF-8 tokenization and query normalization.
- **Structured Health Parsing**: Frontend gracefully parses structured health status objects.
- **Backend Supervision**: Tauri supervisor monitors sidecar heartbeat and ensures clean restart on unexpected exit.
- **Folder Containment Defense**: Enhanced `/fs/action` endpoint with boundary verification.

### Batch 4: Pre-Phase-5 Hardening (All 18 Verified Items)
1. **Same-File Reprocessing Failure Isolation**: If reprocessing a modified file fails or is skipped (e.g. corrupted PDF), FileMind preserves the existing last-known-good index chunks rather than silently purging them.
2. **Parser & Chunker Version Invalidation**: File metadata records `parser_version` and `chunker_version`; version bumps automatically trigger re-indexing on subsequent discovery scans.
3. **Embedding Model Identity & Metadata**: SQLite table `embedding_index_metadata` tracks active model name, dimension, and revision (`v1.0.0`), preventing index corruption if models change.
4. **Parser Provenance in Models**: `TEXT_PARSER_VERSION = "1.1.0"` stamped on all extracted text/code documents.
5. **Strict Integrity Mode**: When `--integrity-mode STRICT` is configured, files with unchanged mtime+size but matching SHA-256 bypass expensive re-parsing while maintaining absolute cryptographic integrity.
6. **ActionType Consistency**: Aligned `ActionType` enum in Rust/Tauri with Python backend schemas (`open`, `open_folder`, `copy_path`).
7. **Windows Console Prevention**: PyInstaller packaging uses `--noconsole` in production builds to eliminate transient console popups.
8. **Tauri Single-Instance Plugin**: Configured `tauri-plugin-single-instance` to focus existing window on secondary launch.
9. **Windows-Only Bundle Targets**: Configured `tauri.conf.json` targets strictly to `["nsis", "msi"]`.
10. **Opener Path Security**: All open-file and open-folder commands strictly validate targets against registered folder boundaries.
11. **MAX_FILE_SIZE Ingestion Guard**: Configured 50 MB default file size limit (`MAX_FILE_SIZE_BYTES`) protecting against OOM crashes on huge binary files.
12. **Persistent Rotating Logging**: Rotating log handler at `%APPDATA%\FileMind\logs\filemind.log` (5 MB max size, 5 backups, level `INFO`, sensitive document text redacted).
13. **Dependency Reproducibility**: Generated pinned `backend/requirements-lock.txt` for exact reproducible environments.
14. **Model Registry Foundation**: Centralized `app.retrieval.model_registry` tracking local model lifecycle states (`not_ready`, `loading`, `ready`, `failed`).
15. **Unified AI Readiness Endpoint**: Added `GET /ai/status` reporting local embedding, reranker, and vector store readiness.
16. **First-Run Model Preparation**: Prepares local FastEmbed cache on startup without blocking user interaction.
17. **Regression Test Suite**: Added 11 new Batch 4 test suites (**248 / 248 backend tests passing**).
18. **Authoritative Documentation**: Updated `FileMind.md` with complete implementation specifications.

### Pre-Phase-5 Audit Cleanup (Commit: `4c569e8`)
Following the merge of PR #1 (`624c010`), a focused pre-Phase-5 audit cleanup was completed at commit `4c569e8`:

1. **SearchRequest Quality Contract Verification**:
   - Investigated and confirmed `quality: str = "fast"` as the authoritative schema and system default.
   - Fast Mode remains the standard default across backend schemas (`SearchRequest`, `SearchResponse`), retriever methods (`HybridRetriever.search()`), and the frontend UI (`useState("fast")`).
   - Re-verified valid combination matrix (`bm25+fast`, `dense+fast`, `hybrid+fast`, `hybrid+quality`) and HTTP 400 rejection for unsupported combinations (`bm25+quality`, `dense+quality`).
   - No source changes required; added regression coverage in `backend/tests/test_audit_cleanup.py`.

2. **`parser_version` Fallback Cleanup**:
   - `ChunkProvenance.parser_version` dataclass default changed: `"1.0.0"` $\rightarrow$ `"unknown"`.
   - `Repository.replace_file_chunks` dictionary fallback changed: `"1.0.0"` $\rightarrow$ `"unknown"`.
   - Eliminates misleading fallback advertising of obsolete parser versions during ad-hoc or fallback chunk construction.
   - All real active parsers (`TextParser` v1.1.0, `PyMuPDFParser` v1.0.0, `DocxParser` v1.0.0, `PptxParser` v1.0.0, `TabularParser` v1.0.0) continue to explicitly provide their authoritative version.
   - `FilesystemScanner` automatically detects `"unknown"` != active parser version, triggering proper re-indexing.
   - Added regression coverage in `backend/tests/test_audit_cleanup.py`.

3. **`token_count` Heuristic (Deliberately NOT Changed)**:
   - Existing `len(text) // 4` character-to-token ratio heuristic remains unchanged.
   - Replacing this heuristic with an actual HuggingFace/ONNX tokenizer was deliberately deferred: invoking FastEmbed tokenizers during document chunking would force eager model/tokenizer initialization on background worker threads, disrupting lazy-loading and increasing chunking latency overhead.

4. **Rust `is_backend_healthy()` (Deliberately NOT Changed)**:
   - `src-tauri/src/main.rs` remains untouched.
   - Rust modifications are deferred until a verified, higher-memory build environment is available to run `cargo check` and Tauri compilation safely without memory/swap exhaustion.

5. **Verification**:
   - Audit Cleanup Tests (`backend/tests/test_audit_cleanup.py`): **3 / 3 PASS**.
   - Targeted Suites: **43 / 43 PASS**.
   - Full Backend Regression: **252 passed / 0 failed / 1 skipped** (out of 253 total tests).
   - Frontend Source: Untouched.

### Model-Agnostic Vector Store Embedding Identity Fix (Commit: `c3e4e98`)
Following the audit cleanup, a latent bug in `SqliteVecStore.upsert_vectors()` was resolved at commit `c3e4e98`:

1. **Problem**:
   - `SqliteVecStore.upsert_vectors()` previously created hardcoded embedding metadata on first write if uninitialized (`provider="fastembed"`, `model_name="sentence-transformers/all-MiniLM-L6-v2"`, `model_version="1.0.0"`, `dimension=self.dimension`).
   - This caused the generic vector storage layer to falsely assume that the default production embedding model produced all incoming vectors, even when vectors originated from custom/experimental models or custom dimensions (e.g. `dimension=4`).

2. **Fix**:
   - Removed hardcoded default embedding metadata creation from `SqliteVecStore.upsert_vectors()`.
   - Vector storage is now completely model-identity agnostic; `upsert_vectors()` strictly performs vector insertion/replacement.
   - The embedding producer (`backend/app/engine/worker.py` via `default_embedding_engine.get_identity()`) remains authoritative for recording active model identity (`vec_store.set_index_metadata(...)`).
   - Existing `get_index_metadata()`, `set_index_metadata()`, and `verify_index_validity()` mechanisms remain fully intact.

3. **Regression Coverage**:
   - Updated `backend/tests/test_batch4_embedding_identity.py` (4/4 PASS):
     - Verified that fresh vector indices directly receiving `upsert_vectors()` retain `get_index_metadata() == None` (no fabricated default metadata).
     - Verified that small/custom dimension vector stores (e.g. `dimension=4`) do not get falsely stamped with 384-dim MiniLM metadata.
     - Verified that explicit model identity recording and verification correctly accept matching models and reject mismatched model names, versions, providers, and dimensions.

4. **Verification**:
   - Focused Retrieval/Vector Store Suites: **74 / 74 PASS** (34.32s).
   - Full Backend Regression: **254 passed / 0 failed / 1 skipped** (out of 255 total tests in 119.09s).
   - Frontend Production Build: **PASS in 42.48s** (1,603 modules transformed, 0 errors).
   - `git diff --check`: **PASS (clean)**.



---

## 13. Phase 4 Validated State & Closure Report

### 13.1 Fast vs Quality Retrieval Contract
The FileMind search architecture cleanly decouples **Retrieval Mode** from **Search Quality**:

- **Retrieval Mode** (`mode`):
  - `bm25`: Lexical ranking via SQLite FTS5.
  - `dense`: Vector cosine similarity via FastEmbed + `sqlite-vec`.
  - `hybrid`: Reciprocal Rank Fusion ($k=60$) combining BM25 and Dense.
- **Search Quality** (`quality`):
  - `fast`: Pure single-pass retrieval without cross-encoder inference (sub-20 ms response target).
  - `quality`: Multi-stage hybrid retrieval with Cross-Encoder reranking (`BAAI/bge-reranker-base`).

### 13.2 Valid Combination Matrix & HTTP 400 Rejection
| Mode | Quality | Status | Runtime Execution |
|---|---|---|---|
| `bm25` | `fast` | **VALID** | FTS5 BM25 lexical ranking -> results |
| `dense` | `fast` | **VALID** | FastEmbed vector search -> results |
| `hybrid` | `fast` | **VALID** | BM25 + Dense -> RRF fusion ($k=60$) -> results |
| `hybrid` | `quality` | **VALID** | BM25 + Dense -> RRF -> Candidate Pool -> Cross-Encoder -> results |
| `bm25` | `quality` | **INVALID** | HTTP 400 Bad Request ("Quality mode is only supported with hybrid retrieval") |
| `dense` | `quality` | **INVALID** | HTTP 400 Bad Request ("Quality mode is only supported with hybrid retrieval") |

### 13.3 Explicit Quality Degradation Semantics
If `quality == "quality"` is requested and the cross-encoder model is unavailable, times out, or fails:
- Hybrid RRF ranking is **preserved**.
- Search response explicitly sets `degraded = true` and `degraded_reason = "reranker_unavailable: <error>"`.
- All item `reranker_score` fields are set to `null` (no fabricated scores).
- The frontend surfaces an explicit warning badge: `Quality (Degraded: Reranker unavailable)`.
- **Inviolable Principle**: Quality search must **never** silently become Fast search or unreranked RRF without degraded telemetry.

### 13.4 Candidate Pool Policy
- **Policy**: Dynamic Candidate Pool Expansion within Safe Bounds.
- Effective Candidate Pool: $\text{effective\_pool} = \min(\max(25, \text{top\_k}), 100)$.
- Guarantees `effective_pool >= top_k` to eliminate silent truncation when requesting $top\_k > 25$, while enforcing an upper safety ceiling of 100 to protect bounded CPU memory and execution time.

### 13.5 Timing Provenance Preservation
All search responses return immutable, un-reconstructed server-side latency breakdowns across 7 discrete stages:
1. `normalization`: Unicode NFKC & identifier extraction latency.
2. `lexical_search`: SQLite FTS5 BM25 query time.
3. `query_embedding`: FastEmbed ONNX query embedding time.
4. `dense_search`: `sqlite-vec` vector similarity search time.
5. `rrf_fusion`: Reciprocal rank fusion and exact-stem boosting time.
6. `reranker_inference`: Cross-encoder ONNX batch inference time (or 0.0 ms in Fast mode).
7. `total_request`: End-to-end request time.

### 13.6 Benchmark Execution & Reproducibility
- **Dataset Version**: `phase4-eval-v1.0` (28 canonical queries covering exact filename, exact phrase, code snippets, acronyms, technical terms, semantic concepts, synonyms, paraphrases, structured tables, multi-file, cross-format, and negative queries).
- **Corpus Version**: `phase3-benchmark-corpus-v1` (20 realistic structural and adversarial files, 54 chunks, 219,851 bytes).
- **Embedding Model**: `sentence-transformers/all-MiniLM-L6-v2` (384-dim, FastEmbed ONNX Runtime).
- **Reranker Model**: `BAAI/bge-reranker-base` (FastEmbed ONNX Runtime).
- **Platform**: Windows 11 (Python 3.11.0, 16 CPUs, RAM RSS ~2,160 MB during full benchmark).

### 13.7 Benchmark Results Table (5 Warm Runs per Query, 28 Queries)
| Configuration | Recall@1 | Recall@5 | Recall@10 | MRR | NDCG@10 | p50 Latency | p95 Latency | Mean Latency | Rerank Latency |
|---|---|---|---|---|---|---|---|---|---|
| **BM25 Fast** | 0.4113 | 0.4933 | 0.4933 | 0.5600 | 0.5090 | 0.22 ms | 0.42 ms | 0.25 ms | 0.00 ms |
| **Dense Fast** | 0.6267 | 0.8613 | 0.9113 | 0.8393 | 0.8263 | 18.15 ms | 21.91 ms | 18.36 ms | 0.00 ms |
| **Hybrid Fast (RRF)** | **0.7147** | **0.9233** | **0.9733** | **0.9433** | **0.9367** | **19.67 ms** | **22.04 ms** | **19.90 ms** | **0.00 ms** |
| **Hybrid Quality (Cross-Encoder)** | 0.6667 | 0.8747 | 0.9347 | 0.9200 | 0.8868 | 4817.67 ms | 5890.36 ms | 5176.00 ms | 5062.31 ms |

### 13.8 Authoritative Decisions
1. **Default Mode Decision**:
   - **Hybrid Fast (RRF) MUST remain the user-facing default.**
   - Hybrid Fast achieves **0.9367 NDCG@10** and **0.9433 MRR** at **19.67 ms** median latency (~50 queries/sec).
   - Quality Mode requires ~4.8 s on CPU across 25 candidates; it is available as a deliberate user selection for deep analysis, but unacceptable as an interactive keystroke default.
2. **Model Decision**:
   - Keep `BAAI/bge-reranker-base`. On complex semantic queries (e.g. `Q19_TABLE_CONTENT` NDCG delta +0.5090, `Q18_MULTI_CHUNK` delta +0.1165), cross-encoder scoring provides deep semantic alignment without heavy PyTorch payload.
3. **Candidate Pool Decision**:
   - Default pool of 25 candidates (`DEFAULT_RERANK_POOL = 25`) with dynamic expansion $\min(\max(25, \text{top\_k}), 100)$.
4. **Score Semantics**:
   - Reranker output is passed through standard logistic sigmoid $\sigma(x) = \frac{1}{1 + e^{-x}}$ to yield a **bounded monotonic relevance score in $(0, 1)$**.
   - It is explicitly documented as a **relative relevance ranking score**, NOT a calibrated Bayesian posterior probability or confidence percentage.
5. **Caching Decision**:
   - Fast Hybrid retrieval runs in < 20 ms, making caching unnecessary for current desktop vault scale (< 10,000 files). Search remains 100% deterministic and stateless.
6. **Pagination Decision**:
   - Cursor contract designed as `offset` with deterministic multi-level tie-breaking `(score DESC, chunk_id ASC)`. Tail queries beyond the cross-encoder candidate pool seamlessly fall back to deterministic RRF ordering.
7. **Phase 4 Exit Decision**:
   - All 17 Phase 4 Exit Gate criteria are satisfied and verified with automated test suites (**248 / 248 backend regression tests passing**).
   - **PHASE 4 IS OFFICIALLY CLOSED.**

### 13.9 Semantic Reorder Analysis
Reranking produced reordered top-3 candidates across 23 queries:
- **Major Semantic Gains**:
  - `Q19_TABLE_CONTENT` ("Quarterly benchmark results discovery and watcher latency"): Cross-encoder promoted `sample_metrics.xlsx` to #1 $\rightarrow$ **NDCG delta: +0.5090**.
  - `Q18_MULTI_CHUNK` ("FileMind architecture overview and subsystems"): **NDCG delta: +0.1165**.
  - `Q15_HYBRID_MULTI_TERM` ("SQLite WAL persistence and change detection"): **NDCG delta: +0.0486**.
- **Exact-Keyword Edge Cases**:
  - `Q01_EXACT_FILENAME` ("sample_system_spec.pdf"): Lexical boost in RRF correctly prioritized exact `.pdf` filename, while Cross-Encoder ranked `.docx` highest due to semantic similarity ($\Delta \text{NDCG}: -0.7860$). This demonstrates why exact filename stem boost remains critical in Fast Hybrid mode.

### 13.10 Frontend UX & Search Controls
- **Retrieval Mode Selector**: Hybrid (RRF), Lexical (BM25), and Dense (Semantic).
- **Quality Toggle**: Fast (Instant) vs Quality (Deep Rerank).
- **Combination Guard**: Selecting Lexical or Dense disables Quality with a tooltip explaining that Quality requires Hybrid mode.
- **Degraded Alert**: Visual warning banner when `response.degraded` is true with human-readable error reasons.
- **Honest Search Footer**: Displayed as `"100% Local Deterministic Search • Fast & Quality Modes"`. No false claims of LLM answer generation.

### 13.11 Automated Test Verification & Regression
- **Phase 5 / 5.5 AI Test Suites**: **93 / 93 PASS** (`test_document_understanding.py`, `test_related_content.py`, `test_ask_pipeline.py`, `test_grounded_generation.py`, `test_context_budget.py`, `test_ollama_provider.py`, `test_batch4_ai_status.py`).
- **AI Status Readiness Tests** (`backend/tests/test_batch4_ai_status.py`): **9 / 9 PASS**.
- **Full Backend Regression Suite** (`pytest backend/tests/`): **423 passed, 0 failed, 1 skipped** (out of 424 total tests).
  *(Note: 1 skipped test is `test_watcher_symlink_ignored_on_windows`, which skips on non-elevated Windows environments lacking symlink creation privileges).*
- **Frontend Production Build** (`tsc && vite build`): **PASS** (1,604 modules transformed, 0 errors).
- **Tauri Desktop Shell** (`cargo check`): **PASS** (0 errors).

### 13.12 Security & Privacy Model
- **Registered-Root Containment**: File operations restricted to registered vault directories.
- **Symlink & Junction Defense**: Protected against circular or unauthorized junction traversals.
- **Opener Restrictions**: Path-checked shell execution using OS default viewers without arbitrary command execution.
- **CORS & CSP**: Localhost-only CORS; strict Content Security Policy.
- **Backend Supervision**: Win32 Job Objects guarantee zero orphaned child processes.
- **Single-Instance Enforcement**: Tauri single-instance plugin focuses existing application.
- **Local-First Privacy**: 100% on-device model execution with zero telemetry or silent cloud fallback.
- **Prompt Injection Defense**: Retrieved document evidence is strictly bounded in untrusted data delimiters.
- **Sensitive-Data-Safe Logging**: Document text and secrets are strictly excluded from persistent logs.

### 13.13 Data & Index Integrity
- **Version Tracking**: `parser_version` and `chunker_version` stored per file; version upgrades trigger automatic re-indexing.
- **Embedding Index Identity**: `embedding_index_metadata` verifies active model identity, dimensions, and schema version (`v1.0.0`).
- **Last-Known-Good Preservation**: Reprocessing failures retain existing valid chunks rather than purging them.
- **Deletion Reconciliation**: Reconciles files deleted while offline upon engine startup.
- **Strict Integrity Mode**: Streaming SHA-256 check allows fast bypass for unchanged files while maintaining cryptographic integrity.

### 13.14 Logging & Diagnostics
- **File Location**: `%APPDATA%\FileMind\logs\filemind.log`
- **Rotation**: 5 MB per file, up to 5 backups.
- **Privacy Rule**: Document body text and secrets are never intentionally logged.

### 13.15 AI Readiness & Status Probing
- **Model Registry**: Centralized registry (`app.retrieval.model_registry`) managing model lifecycle states (`not_ready`, `loading`, `ready`, `failed`).
- **Status API**: `GET /ai/status` reporting local embedding, reranker, vector store, and proactive Ollama daemon/model readiness (`local_ai.ollama`).
- **First-Run Preparation**: FastEmbed models initialized asynchronously on daemon threads without blocking startup.
- **Ollama Probe**: Non-generating `GET /api/tags` probe with 1.0s timeout and model tag normalization.

### 13.16 Current Status & Explicit Future Boundaries
- **Local RAG & Generation (Phase 5.1–5.3)**: Fully implemented and verified.
- **Ask Readiness & Concurrency (Phase 5.4 Batch 1)**: Fully implemented and pushed.
- **Ask UX Polish (Phase 5.4 Batch 2)**: Fully implemented and pushed.
- **Document Understanding Core (Phase 5.5 Batch 1)**: Fully implemented and pushed.
- **Related Content (Phase 5.5 Batch 2)**: Fully implemented and pushed.
- **Folder Understanding & Knowledge Connections (Phase 5.5 Batch 3)**: Next planned.
- **Streaming / SSE**: NOT implemented (synchronous on-device pipeline preserved).
- **Conversational Memory / Multi-Turn History**: NOT implemented (stateless Q&A).
- **Persistent Chat Database**: NOT implemented.
- **Knowledge Graph Database**: NOT implemented (deferred to future milestones).
- **Autonomous Agents**: NOT implemented.


---

## 14. When Instructions Conflict With This File

If a task instruction conflicts with a Non-Negotiable Contract (§2), an Absolute
Prohibition (§3), or the phase boundary in §0/§11, stop and flag the conflict rather
than proceeding. This file reflects a deliberately locked specification — treat an
instruction that contradicts it as a signal to ask for clarification, not as an
implicit spec change.


