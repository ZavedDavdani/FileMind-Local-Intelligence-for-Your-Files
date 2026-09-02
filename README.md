# FileMind

> Local Intelligence for Your Files. Windows-first, privacy-first desktop search & local RAG.

FileMind is a local-first, privacy-first Windows desktop application that indexes user-selected folders and provides multi-stage hybrid evidence retrieval combined with grounded local AI question-answering: SQLite FTS5 BM25 lexical matching, local dense vector embeddings, Reciprocal Rank Fusion (RRF), optional neural cross-encoder reranking, and local-only LLM synthesis via Ollama.

**Core Principle**: *"FileMind is a local knowledge layer over the user's existing files — not a new note-taking app."* The user's files on disk remain the authoritative single source of truth.

---

## Current Status & Phase Roadmap

| Phase | Scope | Status |
|---|---|---|
| **Phase 0** | Distribution Feasibility (Tauri 2 + PyInstaller `--onedir` sidecar packaging) | ✅ Complete / PASS |
| **Phase 1** | Filesystem Engine (Watcher, change detection, exclusions, SQLite WAL, crash recovery) | ✅ Complete / IMPLEMENTED |
| **Phase 2** | Document Intelligence (Multi-format parsers, hierarchical chunking, provenance tracking) | ✅ Complete / IMPLEMENTED |
| **Phase 3** | Hybrid Retrieval (SQLite FTS5 BM25 + dense vectors with Reciprocal Rank Fusion) | ✅ Complete / IMPLEMENTED |
| **Batches 1–4** | Pre-Phase-5 Hardening (Security, crash isolation, index metadata, logging, size guards) | ✅ Complete / PASS |
| **Phase 4** | Reranking / Search Quality (Fast vs Quality modes, benchmark exit gate closed) | ✅ Complete / CLOSED |
| **Phase 5.1** | Context & Token Budgeting (`ContextBudgetConfig`, `TokenEstimator`, `ContextBuilder`) | ✅ Complete / IMPLEMENTED |
| **Phase 5.2** | Grounded Generation Contract (`PromptBuilder`, `CitationValidator`, `OllamaProvider`) | ✅ Complete / IMPLEMENTED |
| **Phase 5.3** | Ask FileMind Local RAG Pipeline & UI (`POST /ai/ask`, `AskService`, `AskModal`) | ✅ Complete / IMPLEMENTED |
| **Phase 5.4 Batch 1** | Ask Readiness & Concurrency Hardening (`GET /ai/status`, tag probe, request sequencing) | ✅ Complete / PUSHED |
| **Phase 5.4 Batch 2** | Ask UX Polish (Staged progress, Copy Answer, Citation navigation, In-session history) | ⏳ **NEXT PLANNED** |
| **Phase 6** | Evaluation / MLOps (Expanded evaluation dataset, Ragas metrics, regression gates) | ⏳ PENDING |
| **Phase 7** | Multimodal Intelligence (Optional: OCR, complex visual tables, ColPali) | ⏳ PENDING |
| **Phase 8** | Production Hardening (Battery throttling, hardware-aware models, auto-update) | ⏳ PENDING |
| **Phase 9** | Optional Cloud / Enterprise (Multi-user workspaces, cloud sync) | ⏳ OPTIONAL / PENDING |
| **Phase 10** | Future Automation / Agentic Intelligence (Smart file organization, automated workflows) | ⏳ FUTURE EXTENSION |

> **Current Boundary & Scope Note**: Phase 5.1–5.3 (Local RAG / Ask FileMind) and Phase 5.4 Batch 1 (Ask Readiness & Concurrency) are **fully implemented and verified**. The pipeline operates synchronously on-device. Streaming, persistent chat history, cloud fallbacks, autonomous tool agents, and knowledge graphs belong to future milestones and are **strictly not implemented**.

---

## Core Architecture

```
User Query (Search Ctrl+K / Ask Ctrl+J)
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
         \                        /
          └─────────┬────────────┘
                    │
      ┌─────────────┴─────────────┐
      ▼                           ▼
[ Search Results UI ]       [ Context Assembly & Token Budget Guard ]
(Spotlight Ctrl+K)          (ContextBudgetConfig: 4096 tokens, system/output reserve)
                                  │
                                  ▼
                            [ Grounded Prompt Builder ]
                            (System grounding rules + [E1], [E2] evidence blocks)
                                  │
                                  ▼
                            [ Local Ollama Provider (qwen3:4b) ]
                            (Strict loopback http://127.0.0.1:11434, zero cloud)
                                  │
                                  ▼
                            [ Citation Validator ]
                            (Resolves inline citations against evidence provenance)
                                  │
                                  ▼
                            [ Ask FileMind UI (Ctrl+J) ]
                            (Grounded answer, verified citation cards, readiness badges)
```

---

## Key Subsystems

### 1. Filesystem Engine & Document Intelligence
- **Watcher**: Cross-platform `watchdog` with sliding event debouncing, recursive folder discovery, exclusion filters (`node_modules`, `.git`, `venv`, user globs), and persistent SQLite WAL metadata storage.
- **Document Parsers**: Structure-first parsers for PDF (PyMuPDF), DOCX, PPTX, XLSX, CSV, Markdown, Code, and Plaintext generating hierarchical chunks with exact parent headings (`H1 > H2`) and location spans.
- **Hierarchical Chunking**: Structure-aware chunking preserving table integrity and heading ancestry with deterministic chunk IDs and immutable provenance snapshots.

### 2. Multi-Stage Hybrid Retrieval
- **Lexical**: SQLite FTS5 full-text index with `unicode61` tokenizer and trigger-based synchronization.
- **Dense**: `sqlite-vec` vector database populated by `sentence-transformers/all-MiniLM-L6-v2` via FastEmbed ONNX Runtime.
- **Fusion**: Reciprocal Rank Fusion ($k=60$) with deterministic tie-breaking.
- **Reranker**: `BAAI/bge-reranker-base` local cross-encoder for deep semantic reordering in Quality mode.

### 3. Grounded Local RAG & Generation (Phase 5.1–5.3)
- **Token Budget Guard (`ContextBudgetConfig`)**: Enforces explicit context boundaries (default 4096 tokens) with reserved system (500 tokens) and output (1000 tokens) allocations. Prevents silent truncation and tracks candidate omissions.
- **Grounded Prompt Builder (`PromptBuilder`)**: Constructs structured prompts with strict system grounding rules, numbered evidence blocks (`[E1]`, `[E2]`), and untrusted document boundary containment for prompt-injection defense.
- **Citation Extraction & Validation (`CitationValidator`)**: Extracts `[E{n}]` markers from model output, validates them against the active citation map, and identifies unresolved citation keys.
- **No-Evidence Short-Circuiting**: If no evidence chunks match the query, the LLM is never invoked; an immediate `NO_EVIDENCE` response is returned.
- **Local Ollama Provider (`OllamaProvider`)**: Executes generation via loopback `http://127.0.0.1:11434` with model `qwen3:4b`. Zero cloud fallback.

### 4. Proactive AI Readiness & Concurrency Protection (Phase 5.4 Batch 1)
- **Ollama Readiness Probe (`check_ollama_readiness`)**: Probes `GET /api/tags` with a 1.0s timeout to verify daemon availability and model presence without loading weights or triggering generation.
- **Status API (`GET /ai/status`)**: Exposes non-breaking `local_ai.ollama` readiness metadata (`is_ollama_online`, `has_default_model`, `model_name`, `endpoint`).
- **AskModal Concurrency Protection**: Monotonically increasing request sequence numbers (`requestSeqRef.current`) suppress stale responses, handle in-flight aborts, and protect loading states across rapid queries or modal close/reopen.
- **Ambient Readiness UI**: AskModal displays live status indicators (🟢 Ready, 🟡 Offline, 🔴 Model Missing) with contextual guidance commands (`ollama serve`, `ollama run qwen3:4b`).

---

## Local AI Setup & Requirements

FileMind uses **Ollama** for on-device generation:

1. **Install Ollama**: Download from [ollama.com](https://ollama.com).
2. **Start Daemon**: Ensure Ollama is running locally:
   ```powershell
   ollama serve
   ```
3. **Pull Default Model**:
   ```powershell
   ollama run qwen3:4b
   ```
4. **Local-Only Guarantee**: FileMind communicates exclusively with `http://127.0.0.1:11434`. Non-loopback endpoints are rejected at the provider layer.

---

## Fast vs Quality Modes

The API and UI separate **Search Mode** (`hybrid`, `bm25`, `dense`) from **Quality Setting** (`fast`, `quality`):

| Pipeline | Mode + Quality | Execution Flow | Target Latency |
|---|---|---|---|
| **Search** | **Hybrid + Fast** *(Default)* | BM25 + Dense $\rightarrow$ RRF Fusion $\rightarrow$ Results | **~19.7 ms** |
| **Search** | **Hybrid + Quality** | BM25 + Dense $\rightarrow$ RRF $\rightarrow$ Cross-Encoder $\rightarrow$ Results | **~4.8 s** |
| **Ask** | **Hybrid + Fast** *(Default)* | Hybrid Search $\rightarrow$ Context Budget $\rightarrow$ Grounded Prompt $\rightarrow$ Ollama $\rightarrow$ Citations | **~1–3 s** |
| **Ask** | **Hybrid + Quality** | Quality Search (Reranked) $\rightarrow$ Context Budget $\rightarrow$ Grounded Prompt $\rightarrow$ Ollama $\rightarrow$ Citations | **~5–8 s** |

### Graceful Degradation & Diagnostic States
- **Model Unavailable**: When Ollama is offline or model is missing, returns `MODEL_UNAVAILABLE` with setup instructions.
- **Timeout**: When generation exceeds timeout threshold, returns `TIMEOUT` without crashing.
- **Insufficient Evidence**: When no relevant chunks match, returns `NO_EVIDENCE` without hallucinating an answer.
- **Budget Limited**: When evidence exceeds token limits, returns `BUDGET_LIMITED` with candidate omission counts.

---

## Security & Privacy Model

- **100% Local Execution**: All tokenization, embeddings, vector indexing, lexical search, neural reranking, and LLM generation execute strictly on-device. Zero telemetry, zero cloud calls.
- **Windows Job Object Supervision**: Tauri desktop process bounds the Python sidecar via Win32 Job Objects (`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`), guaranteeing zero orphan processes on shutdown.
- **Registered Folder Containment**: All file read, open, folder open, and path copy actions are strictly validated against registered folder boundaries to prevent path traversal.
- **Prompt Injection Defense**: Retrieved document text is enclosed within strict untrusted evidence delimiters that cannot override system grounding rules.
- **Localhost-Only API & Strict CSP**: Loopback REST endpoints (`127.0.0.1`) with origin checking and strict Content Security Policy.
- **Sanitized Logging**: Rotating persistent log at `%APPDATA%\FileMind\logs\filemind.log` (5 MB max, 5 backups); document contents and sensitive tokens are strictly redacted.

---

## Verification & Release Gate Status

Previously verified baseline (Commit `a55030f`):

- **AI Status Readiness Tests** (`backend/tests/test_batch4_ai_status.py`): **9 / 9 PASS**
- **Phase 5 AI Test Suites**: **63 / 63 PASS**
  - `test_ask_pipeline.py`: 12 / 12 PASS
  - `test_grounded_generation.py`: 18 / 18 PASS
  - `test_context_budget.py`: 19 / 19 PASS
  - `test_ollama_provider.py`: 5 / 5 PASS
  - `test_batch4_ai_status.py`: 9 / 9 PASS
- **Full Backend Regression Suite**: **393 passed, 1 skipped, 0 failed** *(1 skipped: Windows symlink privilege test)*
- **Frontend Production Build**: **PASS** (1,604 modules transformed, 0 errors)
- **Tauri Desktop Verification**: **PASS** (`cargo check`, 0 errors)
- **Whitespace Check**: **PASS** (0 violations)

---

## Development & Testing

### Prerequisites
- Windows 10/11 x64
- Python 3.11+
- Node.js 18+
- Rust toolchain & Cargo
- Ollama with `qwen3:4b` model

### 1. Backend Setup & Pytest Regression Suite
```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Run Phase 5 AI test suites
pytest tests/test_ask_pipeline.py tests/test_grounded_generation.py tests/test_context_budget.py tests/test_ollama_provider.py tests/test_batch4_ai_status.py -v

# Run full backend regression suite (394 tests)
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

# Build packaged Windows release installer
cargo tauri build
```

---

## Documentation References

- [FileMind Specification (`FileMind.md`)](file:///c:/dev/FileMind/FileMind.md): Authoritative architectural specification and phase contracts.
- [Second Brain Architecture (`FileMind_Second_Brain_Architecture.md`)](file:///c:/dev/FileMind/FileMind_Second_Brain_Architecture.md): Long-term architectural direction and grounding principles.
- [Phase 4 Benchmark Report (`docs/phase-4/reranker-benchmark.md`)](file:///c:/dev/FileMind/docs/phase-4/reranker-benchmark.md): Retrieval quality and latency benchmarks.
- [Pre-Phase-5 Hardening Report (`docs/hardening/pre-phase-5-hardening-report.md`)](file:///c:/dev/FileMind/docs/hardening/pre-phase-5-hardening-report.md): Verification report for foundational hardening.
