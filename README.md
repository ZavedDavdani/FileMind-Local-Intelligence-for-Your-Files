# FileMind

> Local Intelligence for Your Files. One intelligent search.

FileMind is a local-first, privacy-first Windows desktop application that indexes user-selected folders, provides multi-stage hybrid evidence retrieval (lexical BM25 + dense semantic vectors + neural cross-encoder reranking), and is designed to locate exact evidence from local documents with verifiable source citations.

---

## Current Phase Status

- **Phase 0 — VERIFIED** (Distribution Feasibility: Tauri 2 + PyInstaller `--onedir` backend sidecar)
- **Phase 1 — VERIFIED** (Filesystem Engine: SQLite WAL, change detection, directory event debouncing, job queue)
- **Phase 2 — VERIFIED** (Document Intelligence: Multi-format parsers, hierarchical structure-first chunking, provenance tracking)
- **Phase 3 — VERIFIED** (Hybrid Retrieval: SQLite FTS5 BM25 + dense vector embeddings with Reciprocal Rank Fusion)
- **Phase 4 — VERIFIED** (Cross-Encoder Reranking: Local `BAAI/bge-reranker-base` joint relevance scoring)
- **Phase 5 — NOT STARTED** (Local & Cloud RAG Pipeline)

---

## Core Architecture

```
FileMind
  ↓
Filesystem / Document Intelligence
  ↓
BM25 + Dense Retrieval
  ↓
RRF Fusion
  ↓
Cross-Encoder Reranking
  ↓
Final Search Results
```

### Retrieval Pipeline Breakdown

1. **Filesystem & Document Intelligence**:
   - Watches registered directories with debounced event coalescing.
   - Parses diverse document formats (PDF, DOCX, PPTX, XLSX, CSV, Markdown, Code, Plaintext).
   - Generates hierarchical chunks preserving structural headings (`H1 > H2`), section context, table layout, and exact provenance (page numbers, line ranges, character spans).
2. **First-Stage Hybrid Retrieval**:
   - **Lexical Search**: SQLite FTS5 BM25 full-text matching with technical identifier protection.
   - **Dense Retrieval**: `sqlite-vec` / LanceDB vector search using local ONNX embeddings (`sentence-transformers/all-MiniLM-L6-v2` / `BAAI/bge-small-en-v1.5`).
3. **Reciprocal Rank Fusion (RRF)**:
   - Merges lexical and dense candidate lists using standard RRF ($k=60$).
4. **Phase 4 Cross-Encoder Reranking**:
   - Evaluates query-document pairs jointly using local `BAAI/bge-reranker-base` via FastEmbed ONNX Runtime.
   - Operates over a bounded candidate pool of top 25 candidates (`RERANK_CANDIDATE_POOL_SIZE = 25`).
   - Reorders initial candidates based on joint query-document semantic relevance.
5. **Final Presentation**:
   - Returns top results with complete provenance metadata, source snippets, and score breakdowns.

---

## Phase 4 Cross-Encoder Details

- **Model**: `BAAI/bge-reranker-base` executed locally via FastEmbed ONNX Runtime (CPU inference with zero external dependencies).
- **Candidate Pool**: 25 candidates sliced from the RRF fusion stage.
- **Search Mode Scope**:
  - `hybrid`: Invokes first-stage RRF fusion followed by cross-encoder reranking over the top 25 candidates.
  - `bm25` (direct lexical mode): Bypasses reranker (`reranker_score = None`).
  - `dense` (direct semantic mode): Bypasses reranker (`reranker_score = None`).
- **Graceful Fallback**: If the reranker model fails to load, encounters an inference error, or times out, search automatically degrades to standard RRF ranking with `degraded = True`, `degraded_reason = "reranker_unavailable: ..."`, and `reranker_score = None`.
- **Latency Measurement**: Dedicated `reranker_inference` stage measured independently in `latency_breakdown_ms` (~1.05 s – 1.18 s CPU duration for 25 candidates).

---

## Score Semantics

Search responses surface granular evidence from every retrieval stage:

| Field | Description | Range / Format |
|---|---|---|
| `lexical_score` | BM25 lexical relevance score from SQLite FTS5 | Float (or `null` if absent from lexical pool / dense-only mode) |
| `dense_score` | Cosine similarity score from vector retrieval | Float $\in [-1, 1]$ (or `null` if absent from dense pool / BM25-only mode) |
| `rrf_score` | Reciprocal Rank Fusion score | Float $\in (0, 1)$ |
| `reranker_score` | Normalized bounded cross-encoder relevance score | Float $\in (0, 1)$ via sigmoid $\sigma(z)$ (or `null` in BM25/Dense modes or degraded fallback) |
| `score` | Final sorting score matching active search mode | Matches `reranker_score` (in hybrid), `lexical_score` (in BM25), or `dense_score` (in Dense) |

> **Score Formulation Note**: Sigmoid normalization $\sigma(z) = \frac{1}{1 + e^{-z}}$ maps raw unbounded cross-encoder logits into a normalized bounded relevance score in $(0, 1)$ for stable presentation and thresholding. This normalization bounds the score range, but does not constitute a calibrated probability.

---

## Reliability & System Invariants

- **100% Local-First Inference**: Zero data ever leaves the local workstation. Embeddings, vector indexing, FTS5 lexical matching, and cross-encoder reranking run entirely on-device.
- **Single Model Instance & Reuse**: Embedding and cross-encoder models load once on background daemon threads and are reused across all queries.
- **Bounded Initialization & Non-Blocking Callers**: If model initialization exceeds configured timeouts, hybrid search immediately falls back to RRF without blocking the UI or crashing the backend.
- **Explicit Degraded State Telemetry**: If any retrieval arm is unavailable, FileMind returns clean partial results with `degraded = True` and explicit machine-readable reasons.
- **Complete Provenance Preservation**: Every chunk retains exact source file, absolute path, heading hierarchy, line offsets, and character boundaries.
- **Windows Job Object Lifecycle**: Tauri supervisor uses native Win32 Job Objects (`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`) to guarantee zero orphaned Python processes upon application close or abnormal termination.
- **Filesystem Action Scoping**: File open, folder open, and path copy operations are strictly scoped and validated against registered folder boundaries.

---

## Verification & Release Gate Status

Phase 4 implementation and fresh packaged release verification are complete:

- **Phase 4 Acceptance Requirements**: **20 / 20 verified**
- **Dedicated Reranker Tests**: **17 / 17 PASS** (`backend/tests/test_reranker.py`)
- **Hybrid Fallback Tests**: **14 / 14 PASS** (`backend/tests/test_hybrid_fallback.py`)
- **Full Backend Regression Suite**: **192 / 192 PASS** (`pytest backend/tests/ -v`)
- **Frontend Production Build**: **PASS** (1,603 modules transformed, 0 TypeScript errors)
- **Packaged Windows Release**: Verified fresh build of WiX MSI (`FileMind_0.1.0_x64_en-US.msi`) and NSIS setup installer (`FileMind_0.1.0_x64-setup.exe`) with bundled PyInstaller `--onedir` backend sidecar.
- **Installed Release Practical Tests**: Verified live search and semantic reordering across test queries on `C:\FileMind-Practical-Test`.

---

## Development & Testing

### Prerequisites
- Windows 10/11 x64
- Python 3.11+
- Node.js 18+
- Rust toolchain & Cargo

### 1. Backend Setup & Test Suite
```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Run dedicated Phase 4 reranker test suite (17 tests)
python -m pytest tests/test_reranker.py -v

# Run full backend regression suite (192 tests)
python -m pytest tests/ -v
```

### 2. Frontend Setup & Build
```powershell
cd frontend
npm install
npm run build
```

### 3. Tauri Desktop Shell & Packaging
```powershell
cd src-tauri
cargo check

# Package Windows release installers (MSI + NSIS)
cargo tauri build
```
