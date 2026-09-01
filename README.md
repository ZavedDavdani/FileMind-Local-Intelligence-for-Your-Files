# FileMind

> Local Intelligence for Your Files. Privacy-first, deterministic desktop search.

FileMind is a local-first, privacy-first Windows desktop application that indexes user-selected folders and provides multi-stage hybrid evidence retrieval: SQLite FTS5 BM25 lexical matching, local dense vector embeddings, Reciprocal Rank Fusion (RRF), and optional neural cross-encoder reranking. FileMind locates exact evidence from local files with immutable structural provenance (page numbers, heading hierarchy, line offsets, and character boundaries).

---

## Current Status & Phase Roadmap

| Phase | Scope | Status |
|---|---|---|
| **Phase 0** | Distribution Feasibility (Tauri 2 + PyInstaller `--onedir` sidecar packaging) | ✅ Complete / PASS |
| **Phase 1** | Filesystem Engine (Watcher, change detection, exclusions, SQLite WAL, crash recovery) | ✅ Complete / IMPLEMENTED |
| **Phase 2** | Document Intelligence (Multi-format parsers, hierarchical chunking, provenance tracking) | ✅ Complete / IMPLEMENTED |
| **Phase 3** | Hybrid Retrieval (SQLite FTS5 BM25 + dense vectors with Reciprocal Rank Fusion) | ✅ Complete / IMPLEMENTED |
| **Batches 1–4** | Pre-Phase-5 Hardening (Security, crash isolation, index metadata, logging, size guards) | ✅ Complete / PASS |
| **Phase 4** | Reranking / Search Quality (Fast vs Quality modes, benchmark-driven exit gate) | ✅ Complete / CLOSED |
| **Phase 5** | RAG / Local AI (Local LLM via Ollama, citation verification, cloud/local policy) | ⏳ **NOT STARTED** |
| **Phase 6** | Evaluation / MLOps (Expanded dataset, Ragas, MLflow, CI regression gates) | ⏳ PENDING |
| **Phase 7** | Multimodal (Optional: OCR, complex tables, ColPali) | ⏳ PENDING |
| **Phase 8** | Production Hardening (Battery throttling, hardware-aware models, auto-update) | ⏳ PENDING |
| **Phase 9** | Optional Cloud / Enterprise (Multi-user workspaces, cloud sync) | ⏳ OPTIONAL / PENDING |
| **Phase 10** | Future Automation / Agentic Intelligence (Smart file organization, automated workflows) | ⏳ FUTURE EXTENSION |

> **Current Boundary & Explicit Limitation**: Phase 5 (Local RAG / Ollama / LLM generation) has **NOT started**. FileMind currently operates strictly as a 100% deterministic local evidence retrieval engine. Answer synthesis, citations, and autonomous agents are not yet implemented.

---

## Core Architecture

```
User Query
  │
  ▼
[ Query Normalizer (Unicode NFKC, Quoted Phrases, Identifier Preservation) ]
  │
  ├──────────────────────────────────┐
  ▼                                  ▼
[ SQLite FTS5 Lexical Search ]     [ FastEmbed Dense Vector Search ]
  │ (BM25 + Stem Boost)              │ (`sqlite-vec` Cosine Similarity)
  └─────────────────┬────────────────┘
                    ▼
  [ Reciprocal Rank Fusion (RRF k=60) ]
                    │
                    ▼
          Search Quality Selection
         /                        \
  [ FAST MODE ]             [ QUALITY MODE ]
  (Direct RRF Ranking)      (Candidate Pool: min(max(25, top_k), 100))
  ~19.7 ms p50              (Cross-Encoder: BAAI/bge-reranker-base)
                            ~4.8 s CPU inference
         \                        /
          └─────────┬────────────┘
                    ▼
  [ Final Search Results with Provenance & Latency Breakdown ]
```

### Key Subsystems
- **Frontend**: Tauri 2 + React + TypeScript + Tailwind CSS. Spotlight modal (`Ctrl+K`) with instant debounced search, breadcrumbs, format filters, and safe file actions.
- **Backend Sidecar**: FastAPI + Python 3.11 running as an isolated local background process under native Win32 Job Object supervision (`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`).
- **Filesystem Engine**: Cross-platform `watchdog` with sliding event debouncing, recursive folder discovery, exclusion filters (`node_modules`, `.git`, `venv`, user globs), and persistent SQLite WAL metadata storage.
- **Document Intelligence**: Structure-first parsers for PDF (PyMuPDF), DOCX, PPTX, XLSX, CSV, Markdown, Code, and Plaintext generating hierarchical chunks with exact parent headings (`H1 > H2`) and location spans.
- **Retrieval Engine**:
  - **Lexical**: SQLite FTS5 full-text index with `unicode61` tokenizer and trigger-based synchronization.
  - **Dense**: `sqlite-vec` vector database populated by `sentence-transformers/all-MiniLM-L6-v2` via FastEmbed ONNX Runtime.
  - **Fusion**: Reciprocal Rank Fusion ($k=60$) with deterministic tie-breaking.
  - **Reranker**: `BAAI/bge-reranker-base` local cross-encoder for deep semantic reordering in Quality mode.

---

## Fast vs Quality Search Modes

The API and UI cleanly separate **Retrieval Mode** (`hybrid`, `bm25`, `dense`) from **Search Quality** (`fast`, `quality`):

| Mode + Quality Combination | Status | Execution Pipeline | Target Latency |
|---|---|---|---|
| **Hybrid + Fast** *(Default)* | **VALID** | BM25 + Dense $\rightarrow$ RRF Fusion $\rightarrow$ Results | **~19.7 ms** |
| **Dense + Fast** | **VALID** | FastEmbed Vector Search $\rightarrow$ Results | **~18.2 ms** |
| **BM25 + Fast** | **VALID** | SQLite FTS5 BM25 Search $\rightarrow$ Results | **~0.2 ms** |
| **Hybrid + Quality** | **VALID** | BM25 + Dense $\rightarrow$ RRF $\rightarrow$ Cross-Encoder $\rightarrow$ Results | **~4.8 s** |
| **BM25 + Quality** | **INVALID** | HTTP 400 Bad Request (Quality requires Hybrid) | N/A |
| **Dense + Quality** | **INVALID** | HTTP 400 Bad Request (Quality requires Hybrid) | N/A |

### Graceful Quality Degradation
If Quality mode is requested and the cross-encoder model is unavailable, times out, or encounters an error:
- RRF ranking is **preserved**.
- Response sets `degraded = true` and `degraded_reason = "reranker_unavailable: <error>"`.
- `reranker_score` is set to `null` (never fabricated).
- The frontend UI displays an explicit warning alert with the reason.

---

## Phase 4 Benchmark Evidence

Evaluated on `phase4-eval-v1.0` (28 canonical benchmark queries) against `phase3-benchmark-corpus-v1` (20 files, 54 chunks, 219,851 bytes) on Windows 11 (Python 3.11, 16 CPU cores, 5 warm runs per query):

| Configuration | Recall@1 | Recall@5 | Recall@10 | MRR | NDCG@10 | p50 Latency | p95 Latency | Mean Latency | Rerank Latency |
|---|---|---|---|---|---|---|---|---|---|
| **BM25 Fast** | 0.4113 | 0.4933 | 0.4933 | 0.5600 | 0.5090 | 0.22 ms | 0.42 ms | 0.25 ms | 0.00 ms |
| **Dense Fast** | 0.6267 | 0.8613 | 0.9113 | 0.8393 | 0.8263 | 18.15 ms | 21.91 ms | 18.36 ms | 0.00 ms |
| **Hybrid Fast (RRF)** | **0.7147** | **0.9233** | **0.9733** | **0.9433** | **0.9367** | **19.67 ms** | **22.04 ms** | **19.90 ms** | **0.00 ms** |
| **Hybrid Quality (Cross-Encoder)** | 0.6667 | 0.8747 | 0.9347 | 0.9200 | 0.8868 | 4817.67 ms | 5890.36 ms | 5176.00 ms | 5062.31 ms |

> **Authoritative Decision**: Fast Mode (Hybrid RRF) is the user-facing default because it achieves **0.9367 NDCG@10** and **0.9433 MRR** at **19.67 ms** median latency, providing instant 50 queries/sec interactive typing response.

---

## Score Semantics

| Score Field | Source | Range / Interpretation |
|---|---|---|
| `lexical_score` | SQLite FTS5 BM25 | Raw positive float (or `null` if absent from lexical pool) |
| `dense_score` | `sqlite-vec` Cosine Similarity | Float $\in [-1, 1]$ (or `null` if absent from dense pool) |
| `rrf_score` | Reciprocal Rank Fusion ($k=60$) | Float $\in (0, 1)$ combined rank score |
| `reranker_score` | BGE Cross-Encoder via Sigmoid $\sigma(z)$ | Bounded monotonic float $\in (0, 1)$ (or `null` in Fast mode) |
| `score` | Mode-specific primary score | Normalized float matching active search mode |

> **Note on Reranker Score**: The sigmoid value $\sigma(z) = \frac{1}{1 + e^{-z}}$ is a bounded monotonic relevance ranking score. It is **NOT** a calibrated Bayesian confidence percentage (e.g. `0.92` represents higher relative relevance than `0.80`, not "92% probability of correctness").

---

## Security & Privacy Model

- **100% Local Execution**: All tokenization, embeddings, vector indexing, lexical search, and neural reranking execute entirely on-device via FastEmbed ONNX Runtime. Zero telemetry, zero cloud calls.
- **Windows Job Object Supervision**: Tauri desktop process bounds the Python sidecar via Win32 Job Objects (`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`), ensuring child processes terminate cleanly with zero orphans.
- **Registered Vault Containment**: All file read, open, folder open, and path copy actions are strictly validated against registered folder boundaries to prevent path traversal.
- **Localhost-Only API & Strict CSP**: Loopback REST endpoints (`127.0.0.1`) with origin checking and strict Content Security Policy.
- **Sanitized Logging**: Rotating persistent log at `%APPDATA%\FileMind\logs\filemind.log` (5 MB max, 5 backups); document contents and sensitive tokens are strictly redacted.

---

## Verification & Release Gate Status

- **Phase 4 Closure Suite** (`backend/tests/test_phase4_closure.py`): **6 / 6 PASS**
- **Reranker Suite** (`backend/tests/test_reranker.py`): **17 / 17 PASS**
- **Hybrid Fallback Suite** (`backend/tests/test_hybrid_fallback.py`): **14 / 14 PASS**
- **Full Backend Regression Suite**: **247 passed, 0 failed, 1 skipped** *(1 skipped: Windows symlink privilege test)*
- **Frontend Production Build**: **PASS in 4.67s** (1,603 modules transformed, 0 errors)
- **Phase 4 Exit Gate Checklist**: **17 / 17 verified PASS**

---

## Development & Testing

### Prerequisites
- Windows 10/11 x64
- Python 3.11+
- Node.js 18+
- Rust toolchain & Cargo

### 1. Backend Setup & Pytest Regression Suite
```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Run Phase 4 targeted test suites
pytest tests/test_phase4_closure.py tests/test_reranker.py tests/test_hybrid_fallback.py -v

# Run full backend regression suite (248 tests)
pytest tests/ -v
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

# Build packaged Windows release installers (NSIS + MSI)
cargo tauri build
```

---

## Documentation & Benchmark References

- [FileMind Specification (`FileMind.md`)](file:///c:/dev/FileMind/FileMind.md): Authoritative architectural specification and phase contracts.
- [Phase 4 Benchmark Report (`docs/phase-4/reranker-benchmark.md`)](file:///c:/dev/FileMind/docs/phase-4/reranker-benchmark.md): Detailed head-to-head retrieval quality and latency metrics.
- [Phase 4 Evaluation Dataset (`docs/phase-4/evaluation_dataset_v1.json`)](file:///c:/dev/FileMind/docs/phase-4/evaluation_dataset_v1.json): Versioned 28-query ground-truth dataset.
