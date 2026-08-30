# FileMind

> Local Intelligence for Your Files. One intelligent search.

FileMind is a local-first, privacy-first Windows desktop application that indexes user-selected folders, provides hybrid (lexical BM25 + dense semantic) evidence retrieval, and is designed to answer grounded questions about file contents using local AI with verifiable source citations.

---

## Current Project Status

- **Phase 0 — Distribution Feasibility**: **COMPLETE / PASS** (Tauri + React/Vite + bundled Python/FastAPI backend sidecar)
- **Phase 1 — Filesystem Engine**: **COMPLETE / PASS** (SQLite WAL persistence, change detection, directory event cascade debouncing, atomic job queue)
- **Phase 2 — Document Intelligence**: **COMPLETE / PASS** (Multi-format parsers for PDF, DOCX, PPTX, XLSX, CSV, Markdown, Code; hierarchical chunking; exact provenance tracking)
- **Phase 3 — Retrieval Subsystem**: **COMPLETE / PASS** (Deterministic SQLite FTS5 BM25 + dense vector embeddings with Reciprocal Rank Fusion RRF)
- **Hardening 1 (H1) — Windows Job Object Lifecycle**: **COMPLETE / PASS** (`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` orphan prevention)
- **Hardening 2 (H2) — Directory Event Cascade Coalescing**: **COMPLETE / PASS** (Subpath prefix matching, burst coalescing)
- **Hardening 3 (H3) — PDF Extraction-Quality Gate**: **COMPLETE / PASS** (OCR detection, corrupted font filtering, vector poisoning prevention)
- **Hardening 4 (H4) — SQLite WAL Observability**: **COMPLETE / PASS** (Passive checkpointing, concurrent read/write isolation, transaction boundaries)
- **Pre-RAG Integrity Audit**: **COMPLETE / PASS** (Provenance exactness audit, BM25 mechanism verification, hybrid vector fallback contract)
- **Phase 4 — Reranking & Cross-Encoders**: **NOT STARTED / NOT AUTHORIZED**
- **Phase 5 — Local & Cloud RAG Pipeline**: **NOT STARTED / NOT AUTHORIZED**

---

## Core Architecture

```
Desktop App (Tauri 2 + Rust Supervisor + Windows Job Object)
  │
  ├── Frontend (React 18 + TypeScript + Vite + Tailwind CSS)
  │     └── Evidence search UI, folder management, status monitoring
  │
  └── Backend Sidecar (FastAPI + SQLite WAL + FTS5 + ONNX Embeddings)
        ├── Filesystem Watcher & Event Coalescer
        ├── Transactional Job Queue & Worker Pool
        ├── Multi-Format Parser Registry (PDF, Office, Code, Tables)
        ├── Hierarchical Structure-First Chunker
        ├── SQLite FTS5 BM25 Lexical Engine
        ├── Native sqlite-vec / Dense Vector Store
        └── Hybrid Reciprocal Rank Fusion (RRF k=60) Retriever with Fallback
```

---

## Implemented Capabilities

1. **Local-First Privacy & Zero Telemetry**: All parsing, indexing, embedding, and retrieval occur 100% locally on the user's workstation.
2. **Robust Multi-Format Parsing**:
   - PDF (PyMuPDF / fitz with extraction quality gate)
   - Microsoft Word (`.docx`), PowerPoint (`.pptx`), Excel (`.xlsx`, `.csv`)
   - Markdown (`.md`), Plaintext (`.txt`), and Source Code (Python, Rust, JS/TS, Go, C/C++, JSON, YAML)
3. **Structure-First Hierarchical Chunking**: Preserves document headings (`H1 > H2`), section context, table integrity, and exact source location metadata (page numbers, line ranges, character spans).
4. **Hybrid Retrieval with Graceful Degradation**: Combines BM25 full-text search with dense vector embeddings (`all-MiniLM-L6-v2`) via RRF, with automated fallback to BM25 if neural hardware acceleration or vector stores are temporarily offline.
5. **Rock-Solid Windows Process Lifecycle**: Windows Job Object (`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`) guarantees zero orphaned background processes upon application exit.
6. **SQLite WAL Concurrency**: Readers never block writers and writers never block readers.

---

## Project Structure

```
FileMind/
├── backend/                       # Python FastAPI backend & intelligence engine
│   ├── app/
│   │   ├── core/                  # Configuration & constants
│   │   ├── db/                    # SQLite connection, migrations, repository
│   │   ├── engine/                # Watcher, job queue, worker pool
│   │   ├── intelligence/          # Parsers, hierarchical chunker, quality gate
│   │   ├── retrieval/             # Normalizer, BM25, embeddings, vector store, hybrid RRF
│   │   └── main.py                # FastAPI endpoints & schemas
│   └── tests/                     # 114 unit, integration, and concurrency tests
│
├── frontend/                      # React TypeScript desktop frontend
│   ├── src/
│   │   ├── components/            # Search UI, folder picker, file browser
│   │   ├── hooks/                 # Backend health & query hooks
│   │   └── services/              # API client
│   └── package.json
│
├── src-tauri/                     # Tauri desktop shell & Windows Job Object
│   ├── src/
│   │   ├── main.rs                # App supervisor & process lifecycle
│   │   └── job_object.rs          # Win32 Job Object binding
│   └── Cargo.toml
│
├── installer/                     # NSIS installer definition
│   └── FileMind_Installer.nsi
│
├── docs/                          # Validation reports, hardening dossiers, benchmarks
│   ├── phase-0/                   # Distribution feasibility report & metrics
│   ├── phase-1/                   # Filesystem engine report & measurements
│   ├── phase-2/                   # Document intelligence report & parser benchmark
│   ├── phase-3/                   # Hybrid retrieval evaluation dataset & metrics
│   └── hardening/                 # H1, H2, H3, H4 dossiers & audited results
│
├── FileMind.md                    # Persistent canonical implementation context
└── FileMind_Spec_and_Pipeline.pdf # Immutable specification reference
```

---

## Development & Testing Setup

### Prerequisites
- Windows 10/11 x64
- Python 3.11+
- Node.js 18+
- Rust toolchain & Cargo

### 1. Backend Setup & Testing
```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Run full backend regression suite (114 tests)
python -m pytest tests/ -v
```

### 2. Frontend Setup & Build
```powershell
cd frontend
npm install
npm run build
```

### 3. Tauri Desktop Shell
```powershell
cd src-tauri
cargo check
```

---

## Phase Boundary

- **Phase 0–3**: **COMPLETE**
- **Hardening H1–H4**: **COMPLETE**
- **Pre-RAG Integrity Pass**: **COMPLETE**
- **Phase 4 (Reranking & Cross-Encoders)**: **NOT STARTED / NOT AUTHORIZED**
- **Phase 5 (Local & Cloud RAG Pipeline)**: **NOT STARTED / NOT AUTHORIZED**
