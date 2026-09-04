# FileMind — Phase 7 Planning & Product Readiness Audit Report

**Status**: 📋 **AUDITED & PLANNED**  
**Authoritative Baseline**: Phase 5 Frozen at \c6e4a4\, Phase 6 Verified at d09eb\  
**Test Baseline**: **522 passed, 1 skipped (0 failed)** across full backend regression suite  
**Frontend Build**: **1,606 modules transformed, 0 errors**  
**Tauri Desktop Shell**: **\cargo check\ passed (0 errors)**  

---

## 1. Executive Summary

FileMind has completed Phase 6 (Modular Backend Architecture, Domain Repository Decomposition, Error/Security Boundaries, and Retrieval/Search Performance Optimizations). The system operates as a **Feature-Complete MVP (Beta-Ready)** desktop application for local-first search, grounded RAG question answering, and Second Brain document understanding.

This audit evaluates the current codebase to establish the authoritative Phase 7 product and engineering roadmap, focusing on core local-first differentiators rather than generic cloud SaaS features.

---

## 2. Current Architecture & Capability Map

\┌─────────────────────────────────────────────────────────────────────────────┐
│                             TAURI DESKTOP (Rust)                            │
│  • App Lifecycle Supervisor          • Win32 Job Object RAII Guard          │
│  • Native Directory Picker Dialog   • Edge WebView2 Container               │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │ HTTP Loopback (127.0.0.1:24823)
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          REACT 18 / TYPESCRIPT UI                           │
│  • Spotlight Search (Ctrl+K)         • Ask FileMind Modal (Ctrl+J)          │
│  • Second Brain Knowledge Sheet      • File List & Folder Manager           │
│  • Event Audit Log & Chunk Inspector • Memoized Polling-Resistant State     │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │ HTTP REST (CORS restricted to localhost)
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            FASTAPI WEB SERVICE                              │
│  • Lifespan Coordinator             • Centralized Error Mapping             │
│  • Rotating Application Logging      • Request-Scoped Dependency Injection  │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
            ┌──────────────────────────┴──────────────────────────┐
            ▼                                                     ▼
┌───────────────────────────────┐             ┌───────────────────────────────┐
│          API ROUTERS          │             │     SERVICES & ENGINES        │
├───────────────────────────────┤             ├───────────────────────────────┤
│ • folders_router              │             │ • FilesystemCoordinator       │
│ • files_router                │             │ • FilesystemScanner           │
│ • indexing_router             │             │ • WatcherService (Watchdog)   │
│ • events_router               │             │ • WorkerPool (4 Threads)      │
│ • jobs_router                 │             │ • HybridRetriever             │
│ • fs_actions_router (Security)│             │ • AskService & PromptBuilder  │
│ • search_router               │             │ • LocalGenerationCoordinator  │
│ • ai_router                   │             │ • KnowledgeConnectionService  │
└───────────────────────────────┘             └───────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          DOMAIN REPOSITORIES & FAÇADE                       │
│  • FolderRepository    • FileRepository       • JobRepository               │
│  • EventRepository     • ChunkRepository      • InsightRepository           │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                       SQLITE PERSISTENCE LAYER                              │
│  • filemind.db (WAL mode, busy_timeout=30000ms, foreign_keys=ON)            │
│  • Tables: folders, files, chunks, file_events, indexing_jobs, insights     │
│  • FTS5: chunks_fts (unicode61 BM25), files_fts (trigram file search)       │
│  • Vector Store: chunk_vectors (sqlite-vec vec0 cosine index)               │
└─────────────────────────────────────────────────────────────────────────────┘
\
### Verified Subsystem Capabilities:
1. **Ingestion & Processing**: Watchdog debouncing (500ms sliding window), recursive directory event coalescing (H2), crash recovery resetting stale jobs, structure-first parsers (PyMuPDF, python-docx, python-pptx, openpyxl, text/code for 25+ extensions), hierarchical chunking (~1500 chars) with parent headings, and 12-signal PDF extraction quality gate (H3).
2. **Multi-Stage Hybrid Retrieval**: SQLite FTS5 lexical BM25 (\chunks_fts\) + FastEmbed ONNX dense vectors (\sentence-transformers/all-MiniLM-L6-v2\) + Reciprocal Rank Fusion (k=60) + local BGE cross-encoder reranking (\BAAI/bge-reranker-base\) in Quality mode.
3. **File Browsing Acceleration**: Trigram FTS5 index (\iles_fts\, migration V9) providing sub-millisecond substring matching on filename, relative path, and SHA-256.
4. **Local AI & Second Brain**: On-device Ollama integration with single-concurrency admission control, grounded prompt construction, 4096-token budget enforcement, deterministic citation validation, document structural summaries, folder summaries, and cross-document topic graphs.
5. **Desktop Stability**: Win32 Job Object kernel guard terminating the Python sidecar on window close; sub-second port release; memoized polling-resistant frontend components.

---

## 3. Product Gap & Friction Analysis

| Area | Current Strength | Critical Gap | User Impact |
| :--- | :--- | :--- | :--- |
| **Ask / RAG** | Strict grounding, verified citations, context budgeting | Non-streaming blocking POST; single-turn volatile context | 3–8s waiting delay; cannot ask follow-up questions |
| **Onboarding** | Proactive Ollama tag probe (\/ai/status\) | No in-app model installer or setup wizard | User must know to open PowerShell and run \ollama pull\ |
| **Scanned Files** | Scanned PDFs detected & vector poisoning prevented | Scanned PDFs/images marked \SKIPPED\ without OCR | Paper contracts, receipts, and invoices are unsearchable |
| **Knowledge Graph** | Cross-document connections & topics computed | Rendered as text list in a slide-out panel | Cannot explore or visualize cross-file concept networks |
| **Search UI** | Sub-20ms hybrid search, exact trigram matching | No search query history or saved searches | Repetitive manual query typing |

---

## 4. Scale & Reliability Analysis

* **1,000 to 10,000 Files**: Verified in benchmark runs. Discovery < 2.0s, total ingestion < 10s, memory RSS < 100MB, search latency < 20ms.
* **100,000 Files**: Inferred low risk. SQLite WAL and FTS5 scale easily. Full-table vector scans estimated at ~150–250ms.
* **500,000+ Files**: Bottleneck boundary. Vector scans without approximate index (HNSW/IVF) will exceed 1.0s. Cold-start hashing will require multi-hour batching.
* **Reliability Assessment**: Worker crashes are handled via startup crash recovery; scanned PDFs are prevented from corrupting vectors; SQLite write lock contention is prevented via single-connection transactions and event coalescing.

---

## 5. Phase 7 Roadmap & Execution Plan

\┌─────────────────────────────────────────────────────────────────────────────┐
│                           PHASE 7 EXECUTION ROADMAP                         │
├─────────────────────────────────────────────────────────────────────────────┤
│ WORKSTREAM 1: Conversational Intelligence & Streaming RAG (P0)              │
│ • SSE endpoint: POST /ai/ask/stream with token-by-token streaming          │
│ • Persistent SQLite schema: chat_threads & chat_messages (Migration V10)    │
│ • Multi-turn conversational context builder with citation preservation      │
│ • Interactive Chat Sidebar & Thread Management UI in AskModal               │
├─────────────────────────────────────────────────────────────────────────────┤
│ WORKSTREAM 2: Desktop Onboarding & Local Model Hub (P0)                     │
│ • In-app Ollama detection & one-click model pull (POST /ai/models/pull)     │
│ • First-run Welcome Wizard (Ollama probe → Model select → Folder select)    │
│ • Privacy & Local-First Verification Badge in Header                        │
├─────────────────────────────────────────────────────────────────────────────┤
│ WORKSTREAM 3: Deep Document Intelligence & Local OCR (P1)                   │
│ • Windows Media OCR / Tesseract local OCR engine integration                │
│ • Ingestion pipeline upgrade: process REQUIRES_OCR PDFs and image formats   │
│ • OCR text layer extraction with bounding box & page provenance             │
├─────────────────────────────────────────────────────────────────────────────┤
│ WORKSTREAM 4: Visual Knowledge Graph & Search Polish (P1/P2)                │
│ • Interactive Canvas/SVG Knowledge Graph explorer for cross-file links      │
│ • Search Query History & Saved Searches dropdown in Spotlight (Ctrl+K)      │
│ • File filter chips (Date modified range, File size range) in search modal  │
└─────────────────────────────────────────────────────────────────────────────┘
\
---

## 6. What NOT to Build

* **Cloud LLM APIs (OpenAI / Anthropic / Gemini)**: Destroys the 100% local, zero-leakage privacy guarantee.
* **Cloud Sync / Multi-User Collaboration**: Premature complexity that detracts from single-user desktop speed and simplicity.
* **External Graph Database Servers (Neo4j)**: Unnecessary resource footprint; SQLite relational graph queries perform in < 2ms.
* **Autonomous File-Modifying Agents**: Violates read-only safety invariant and risks user data loss.
* **WYSIWYG Note Editor**: FileMind is an intelligence layer over existing user files, not a text editor.

---

## 7. Release Readiness Decision

* **Current Maturity Level**: **Feature-Complete MVP (Beta-Ready)**
* **Architecture Decision**: **NO ARCHITECTURAL REFACTOR REQUIRED**. Phase 6 established modular, request-scoped, domain-separated architecture. Phase 7 will cleanly implement features atop this foundation.
* **Success Criteria for Production**:
  1. Time-to-first-token in Ask modal < 400ms via SSE streaming.
  2. Persistent multi-turn chat threads in SQLite.
  3. Local OCR for scanned documents without cloud dependencies.
  4. Zero-terminal first-run onboarding experience.