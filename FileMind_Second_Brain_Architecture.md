# FileMind — Second Brain Architecture

> **Document Status**: Authoritative Architecture Direction Document
> **Phase Context**: Phase 5.1–5.3 Complete & Verified, Phase 5.4 Batch 1 Complete & Pushed (Commit `a55030f`), Phase 5.4 Batch 2 Next
> **Target Audience**: Core Engineering & Product Architecture

---

## 1. Product Evolution

FileMind is evolving along a deliberate, incremental trajectory:

- **CURRENT**: *Local Intelligence for Your Files & Grounded Local RAG* (High-performance structural parsing, lexical/dense hybrid retrieval, cross-encoder reranking, local vector storage, context/token budgeting, and grounded local Q&A via Ollama with citation validation).
- **TARGET**: *Private Local Second Brain* (A private local knowledge layer that searches, understands, connects, reviews, and remembers information across user files).

```
┌─────────────────────────────────────────────────────────────────────────┐
│ CURRENT BASELINE (Phases 1–5.3 & Phase 5.4 Batch 1 · Commit a55030f)   │
│ Local Intelligence for Your Files & Grounded Local RAG                  │
│ • Deep structural document parsing (PDF, Office, Code, Data)            │
│ • Strict UTF-8 & integrity-first decoding (No U+FFFD corruption)        │
│ • Deterministic hierarchical chunking & immutable provenance records   │
│ • Fast & Quality hybrid retrieval (FTS5 BM25 + sqlite-vec Dense + RRF)   │
│ • BGE cross-encoder neural reranking with graceful fallback             │
│ • Context assembly, token budget guard, and prompt injection defense    │
│ • Grounded local LLM generation (Ollama qwen3:4b) & citation validation │
│ • Ask FileMind Q&A with proactive Ollama readiness & concurrency guards │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ TARGET VISION (Second Brain Layer & Beyond)                             │
│ Private Local Second Brain                                              │
│ • SEARCH: Sub-100ms multi-format lexical, semantic & reranked discovery │
│ • UNDERSTAND: Evidence-grounded document & folder summaries / decisions │
│ • CONNECT: Lightweight cross-document associations and shared concepts  │
│ • REVIEW: Temporal change summaries and proactive activity intelligence │
│ • REMEMBER: Persistent, provenance-linked knowledge cards and insights │
└─────────────────────────────────────────────────────────────────────────┘
```

This evolution is an extension of the existing product rather than a rewrite or replacement. FileMind does not require users to migrate their knowledge into a new proprietary workspace; it derives intelligence directly from the files they already own and maintain.

---

## 2. Core Principle

> ### **FileMind is a local knowledge layer over the user's existing files.**
> ### **The user's files remain the SINGLE SOURCE OF TRUTH.**

This principle is a permanent, non-negotiable architectural constraint:

- **Filesystem Primacy**: The user's files on disk are the primary, authoritative data source. FileMind never replaces, modifies, or silos the user's files.
- **Derived Knowledge vs. Source Information**: FileMind derives intelligence, summaries, associations, and answers from existing files, but derived knowledge is strictly secondary and traceable.
- **No Inversion of Authority**: FileMind must never silently turn AI-generated interpretations into authoritative source material.

---

## 3. What FileMind Is

FileMind is defined as:

- **A local-first file intelligence system**: Indexes and understands heterogeneous local file collections completely offline.
- **A private knowledge layer**: Organizes, indexes, and surfaces insights across local files without remote telemetry or cloud dependencies.
- **A high-performance retrieval system**: Combines BM25 lexical search, dense vector embeddings, reciprocal rank fusion (RRF), and cross-encoder reranking.
- **A grounded understanding system**: Synthesizes multi-document answers and structured summaries backed strictly by local evidence.
- **A system for discovering relationships across files**: Identifies connections, shared themes, and project references across distinct documents.
- **A provenance-aware AI interface over local evidence**: Exposes exact source file paths, section headings, page numbers, and chunk references for every insight.

---

## 4. What FileMind Is Not

To maintain architectural focus and prevent product drift, FileMind is explicitly defined as:

- **NOT a note-taking application**: FileMind does not provide note authoring, rich-text canvases, or daily journal interfaces.
- **NOT a document editor**: FileMind does not edit or save Word documents, PDFs, or code files.
- **NOT a replacement filesystem**: FileMind does not manage disk storage or force proprietary folder structures.
- **NOT an Obsidian clone**: FileMind does not require or construct a user-managed markdown vault.
- **NOT a Notion clone**: FileMind does not build relational databases, kanban boards, or collaborative workspaces.
- **NOT a cloud-first knowledge platform**: FileMind does not require cloud accounts, hosted backends, or SaaS subscriptions.
- **NOT an autonomous agent platform**: FileMind does not execute autonomous external actions (e.g., sending emails, executing shell commands).
- **NOT an ungrounded chatbot**: FileMind does not offer general-purpose conversational chat disconnected from local files.
- **NOT a parallel source-of-truth database**: FileMind does not maintain an independent repository of user-authored knowledge.

---

## 5. Existing Architectural Foundation

The Second Brain layer is built directly upon the existing, verified foundation without duplicating or replacing core subsystems:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     LOCAL FILESYSTEM ON DISK                            │
│                  (Single Source of Truth)                               │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
┌────────────────────────────────────▼────────────────────────────────────┐
│                    INGESTION & PARSING (Phase 2)                        │
│   PDF (PyMuPDF/PyPDF) · Office (DOCX/PPTX/XLSX) · Text · Code · Data    │
│            (Strict UTF-8 / BOM Decoding Policy — A2)                    │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
┌────────────────────────────────────▼────────────────────────────────────┐
│              HIERARCHICAL CHUNKING & PROVENANCE (Phase 2)               │
│   Structure-First Elements · Token Estimation · Bounded Overlap (A3)    │
│         Deterministic JSON Chunk ID · Frozen ChunkProvenance            │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
┌────────────────────────────────────▼────────────────────────────────────┐
│                   HYBRID RETRIEVAL LAYER (Phase 3 & 4)                  │
│       FTS5 BM25 Lexical  +  sqlite-vec Dense  +  RRF Fusion (k=60)      │
│                     (Foundational & Permanent)                          │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
┌────────────────────────────────────▼────────────────────────────────────┐
│                       CROSS-ENCODER RERANKING (Phase 4)                 │
│              FlashRank ms-marco-MiniLM-L-6-v2 Reranker                  │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
┌────────────────────────────────────▼────────────────────────────────────┐
│                      LOCAL AI / RAG ENGINE (Phase 5)                    │
│   Context Assembly · Local LLM Runtime · Grounded Generation · Citations│
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
┌────────────────────────────────────▼────────────────────────────────────┐
│                     SECOND BRAIN CAPABILITIES (Phase 5.x)               │
│        Ask FileMind · Understand · Connect · Review · Cards             │
└─────────────────────────────────────────────────────────────────────────┘
```

The hybrid retrieval foundation (`BM25 + Dense + RRF`) is permanently preserved as the unified retrieval core.

---

## 6. Knowledge Model

FileMind maintains a strict conceptual and data-level distinction between **Source Knowledge** and **Derived Knowledge**:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           SOURCE KNOWLEDGE                              │
│  • Immutable raw bytes and files on disk (user-authored / user-owned)  │
│  • Extracted structural elements (Headings, Paragraphs, Code, Tables)   │
│  • 100% Ground Truth — The single source of truth                       │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │ (Ingestion / Parsing / Chunking)
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                          EVIDENCE CHUNKS                                │
│  • Hierarchical chunks with deterministic IDs (identity.py)             │
│  • Immutable provenance records (provenance.py)                         │
│  • Dense vector embeddings (sqlite-vec) & FTS5 tokens                   │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │ (Retrieval / Context Assembly)
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                          DERIVED KNOWLEDGE                              │
│  • Grounded answers to natural language questions                       │
│  • Multi-granularity document & folder summaries                        │
│  • Extracted decisions, risks, and unresolved action items              │
│  • Lightweight associative links & shared topics                        │
│  • Temporal review summaries                                            │
│  • Saved Knowledge Cards                                                │
└─────────────────────────────────────────────────────────────────────────┘
```

### Traceability Invariant
Every unit of Derived Knowledge must retain an unbroken link back to the supporting Evidence Chunks and Source Files. Derived knowledge must be reconstructable during a corpus re-index. Graph databases are not introduced at this stage.

---

## 7. Second Brain Capability Roadmap

The capability roadmap follows a locked engineering priority sequence:

```
  ┌────────────────────────────────────────────────────────────────┐
  │ 7.1 Ask FileMind (Multi-Document Evidence-Grounded Q&A)        │
  └───────────────────────────────┬────────────────────────────────┘
                                  │
  ┌───────────────────────────────▼────────────────────────────────┐
  │ 7.2 Document / Folder Understanding (Summaries & Decisions)    │
  └───────────────────────────────┬────────────────────────────────┘
                                  │
  ┌───────────────────────────────▼────────────────────────────────┐
  │ 7.3 Related Content (Similarity & Topic Discovery)             │
  └───────────────────────────────┬────────────────────────────────┘
                                  │
  ┌───────────────────────────────▼────────────────────────────────┐
  │ 7.4 Knowledge Connections (Lightweight Cross-File Links)       │
  └───────────────────────────────┬────────────────────────────────┘
                                  │
  ┌───────────────────────────────▼────────────────────────────────┐
  │ 7.5 Review (Activity, Change Digests & Recurrent Themes)       │
  └───────────────────────────────┬────────────────────────────────┘
                                  │
  ┌───────────────────────────────▼────────────────────────────────┐
  │ 7.6 Knowledge Cards (Saved Traceable Derived Insights)         │
  └────────────────────────────────────────────────────────────────┘
```

### 7.1 Ask FileMind (Priority: HIGHEST)
- **Purpose**: Allows users to ask natural language questions across their indexed files and receive accurate, synthesized answers grounded in verifiable evidence.
- **Architectural Requirements**:
  - Multi-file evidence retrieval via Fast (BM25 + Dense + RRF) or Quality (Cross-Encoder) retrieval modes.
  - Strict context assembly respecting token budgets with explicit file, heading, and page provenance.
  - Grounded answer synthesis with inline citation markers mapped directly to retrieved chunks.
  - **Explicit Insufficient-Evidence State**: If retrieved chunks lack sufficient evidence, FileMind explicitly reports that evidence was not found rather than speculating.
  - Zero unsupported claims presented as facts.

### 7.2 Document / Folder Understanding
- **Purpose**: Generates structured overviews, executive summaries, decision logs, risk registries, and theme analyses for single documents or entire directories.
- **Architectural Requirements**:
  - Hierarchical map-reduce summarization for documents exceeding single-turn context limits.
  - Multi-file directory digest synthesis combining filesystem metadata with structural chunk samples.
  - Explicit visual and data tagging demarcating generated summaries as derived interpretations.

### 7.3 Related Content
- **Purpose**: Discovers related documents, chunks, topics, and concepts based on semantic and lexical similarity.
- **Architectural Requirements**:
  - Direct reuse of existing hybrid retrieval and vector embedding infrastructure (e.g., query-by-chunk-vector).
  - Explainable relevance signals (matching keywords, vector cosine proximity, shared structural tags).
  - Zero duplicate search index infrastructure.

### 7.4 Knowledge Connections
- **Purpose**: Establishes lightweight associative links across documents, recurring concepts, project entities, and decisions.
- **Architectural Requirements**:
  - Relational mapping of derived connections (`document` $\leftrightarrow$ `concept`, `document` $\leftrightarrow$ `topic`, `document` $\leftrightarrow$ `project`, `document` $\leftrightarrow$ `related_document`).
  - Derived dynamically or stored in relational tables reconstructable from source files.
  - A graph database is NOT a prerequisite; the architecture remains extensible toward graph engines in later phases.

### 7.5 Review
- **Purpose**: Provides temporal and change-aware synthesis answering *"What changed this week?"*, *"What decisions were documented recently?"*, and *"What unresolved issues need attention?"*.
- **Architectural Requirements**:
  - Synthesizes filesystem timestamps (`modified_at`, `indexed_at`), newly parsed chunks, and recent derived insights.
  - Grounded strictly in local filesystem and index data.

### 7.6 Knowledge Cards
- **Purpose**: Provides persistent, bookmarkable units of derived knowledge (key decisions, core facts, project references, unresolved questions).
- **Architectural Requirements**:
  - Stored with immutable provenance links: `source_file_id`, `chunk_ids`, `provenance_snapshot`, `created_at`, `model_identity`.
  - Tagged explicitly with `is_ai_derived = true`.
  - Invalidation hooks: If a source file is modified or deleted, associated cards flag a stale/orphaned state rather than acting as a disconnected source of truth.

---

## 8. Grounding Principle

> ### **Every generated answer must be grounded in retrieved FileMind evidence and expose verifiable provenance.**

### Formal Invariants:
1. **Evidence Precedence**: The system must never prefer a plausible generated answer over trustworthy evidence.
2. **Explicit Insufficient Evidence**: If retrieval confidence is below threshold or retrieved chunks do not contain the answer, FileMind must explicitly report that sufficient evidence was not found.
3. **Categorical Separation**:
   - **Source Evidence**: Immutable text extracted directly from user files.
   - **Retrieved Evidence**: Ranked subset of chunks selected by hybrid search.
   - **Model Interpretation**: Synthesized prose produced by the LLM, which must cite retrieved evidence.

---

## 9. Provenance Principle

FileMind preserves an unbroken provenance chain across all transformations:

$$\text{Source File} \longrightarrow \text{Parser} \longrightarrow \text{Chunk} \longrightarrow \text{Retrieval} \longrightarrow \text{Evidence Selection} \longrightarrow \text{Generated Answer / Card}$$

- **Metadata Propagation**: Chunk ID, file ID, file path, section, page, heading hierarchy, line range, and character offset flow through context assembly into final answers and cards.
- **Version Tracking**: `parser_version` and `chunker_version` (`phase2-hierarchical-v2`) remain attached to all chunks and derived knowledge to detect stale representations.

---

## 10. Local-First Privacy

FileMind enforces a strict local-first privacy boundary:

- **100% Local Execution**: Indexing, parsing, vector embedding generation, cross-encoder reranking, and LLM generation execute on the user's local hardware by default.
- **Zero Silent Fallback**: The system never silently falls back to external cloud APIs or remote services upon local failure.
- **Zero Telemetry / Zero Uploads**: No user document contents, queries, chunk hashes, metadata, or generated insights are transmitted over the network.
- **Opt-In Cloud Boundary**: Any future cloud or enterprise integrations must be strictly optional, explicitly configured, fully disclosed, and architecturally separated from the local engine.

---

## 11. Phase Roadmap

The complete strategic engineering roadmap is defined as follows:

| Phase / Milestone | Focus Area | Status |
| :--- | :--- | :--- |
| **A1–A3.1** | Vector, Corpus Encoding, Chunker & Reprocessing Hardening | **COMPLETE** |
| **Phase 4** | Fast / Quality Retrieval, Cross-Encoder Reranker, Exit Gate | **CLOSED** |
| **Phase 5.1–5.3** | **Local AI / RAG Foundation & Ask FileMind** (Context, Prompts, Citations, Ask UI) | **COMPLETE** |
| **Phase 5.4 Batch 1** | **Ask Readiness & Concurrency Hardening** (`/ai/status`, tag probe, request sequencing) | **COMPLETE** |
| **Phase 5.4 Batch 2** | **Ask UX Polish** (Staged progress, Copy Answer, Citation navigation, In-session history) | **NEXT PLANNED** |
| **Phase 5.x** | **Higher-Level Second Brain Capabilities** (Document/Folder Summaries, Connections, Cards) | **AFTER PHASE 5.4** |
| **Phase 6** | Evaluation, MLOps, Automated Regression Benchmarks | **PLANNED** |
| **Phase 7** | Multimodal Intelligence (Images, Scans, OCR Integration) | **PLANNED** |
| **Phase 8** | Desktop Packaging, Performance Optimization & Production Hardening | **PLANNED** |
| **Later** | Knowledge Graph Topologies, Expanded Review, Spaced Repetition, Voice, Agentic Intelligence | **FUTURE** |

---

## 12. Phase 5 Boundary

Phase 5 establishes the technical foundation required specifically for **Ask FileMind**:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        PHASE 5 ENGINE BOUNDARY                         │
│                                                                        │
│   ┌───────────────────────────┐      ┌─────────────────────────────┐   │
│   │   Local Model Runtime     │      │   Context Assembly Pipeline │   │
│   │ • Local inference engine  │      │ • Evidence chunk formatting │   │
│   │ • Health & readiness check│      │ • Token budget allocation   │   │
│   │ • Streaming token reader  │      │ • Structural heading context│   │
│   └─────────────┬─────────────┘      └──────────────┬──────────────┘   │
│                 │                                   │                  │
│                 └─────────────────┬─────────────────┘                  │
│                                   ▼                                    │
│   ┌────────────────────────────────────────────────────────────────┐   │
│   │                     Grounded RAG Engine                        │   │
│   │ • Grounding prompt contracts & citation mapping                │   │
│   │ • Deterministic "Insufficient Evidence" handling               │   │
│   │ • Failure semantics, timeouts & cancellation handling          │   │
│   │ • Reproducible evaluation fixtures & ground-truth assertions   │   │
│   └────────────────────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────────────────────┘
```

- **Phase 5 Scope**: Local model abstraction, model readiness probes, retrieval-to-context flow, bounded context assembly, grounded generation, provenance propagation, insufficient-evidence behavior, failure handling, cancellation, and evaluation hooks.
- **Boundary Distinction**: Phase 5 provides the foundational RAG engine. Phase 5.x introduces the higher-level Second Brain capabilities (summaries, connections, review, knowledge cards).

---

## 13. Architectural Constraints

All future development must comply with these 12 hard constraints:

1. **Existing files remain the source of truth**: No feature may create an unbacked, proprietary document store.
2. **BM25 + Dense + RRF remains foundational**: Features must utilize the verified hybrid retrieval pipeline without building duplicate search engines.
3. **Provenance must survive transformations**: Provenance metadata must accompany all derived insights.
4. **No silent local-to-cloud fallback**: All core functionality remains 100% offline and local.
5. **Clear generation tagging**: AI-generated content must always be distinguished from source document text.
6. **Reconstructability**: Derived knowledge must be reconstructable from source files during a full corpus re-index.
7. **Avoid premature graph complexity**: Simple relational mappings must precede graph databases.
8. **No duplicate indexing infrastructure**: Parsing and chunking logic remains centralized in Phase 2 Document Intelligence.
9. **Generated claims require evidence**: Every factual statement must link to an identifiable chunk in the retrieval context.
10. **Insufficient evidence is explicit**: The system must declare lack of evidence rather than generating ungrounded text.
11. **Versioning matters for derived artifacts**: Persistent artifacts must validate `parser_version` and `chunker_version` against active index versions.
12. **Privacy remains local-first**: Zero telemetry and zero unauthorized data egress.

---

## 14. Non-Goals

The following areas are explicitly excluded from FileMind's scope:

- Building a new note-taking application or personal wiki.
- Replacing the filesystem or altering user folder structures.
- Replacing or modifying existing source documents.
- Creating an Obsidian-style markdown vault or graph editor.
- Creating a Notion-style cloud workspace.
- Becoming a cloud-first SaaS knowledge platform.
- Creating an autonomous agent system executing external side-effects.
- Creating an ungrounded general-purpose chatbot.
- Creating a social or collaborative knowledge-sharing network.

---

## 15. Long-Term Extensions

The following capabilities represent future possibilities that may be explored in later phases, without imposing immediate architectural burden:

- **Richer Knowledge Graph**: Dedicated property graphs for deep multi-hop entity traversal and relation queries.
- **Advanced Review System**: Spaced repetition, proactive morning briefs, and automated synthesis of watched directory changes.
- **Spaced Repetition & Memory**: User-configurable flashcard and memory review workflows over extracted knowledge cards.
- **Voice Interaction**: Local speech-to-text (e.g. Whisper) for voice queries and audio transcription.
- **Multimodal Knowledge**: Local vision-language models for charts, diagrams, drawings, and scanned forms (Phase 7).
- **Agentic Workflows**: Multi-step local reasoning agents for complex document cross-referencing.
- **Optional Cloud/Enterprise Capabilities**: Explicit, opt-in enterprise server deployments.

---

## 16. Success Definition

> **FileMind succeeds as a Personal Second Brain when a user can effortlessly ask meaningful questions about their existing files, understand documents and folders at a glance, discover relationships across their work, review important changes over time, and preserve useful derived insights — while maintaining 100% local-first privacy and absolute traceability to the original source evidence.**
