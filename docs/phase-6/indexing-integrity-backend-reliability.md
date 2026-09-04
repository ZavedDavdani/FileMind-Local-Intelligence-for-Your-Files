# Pre-Phase-7 Architecture Hardening: Indexing Integrity, Backend Reliability & Performance

## Overview

As part of the final backend architecture-hardening pass prior to Phase 7, FileMind implemented **Batch 2: Indexing Integrity, Backend Reliability, and Performance**. This pass resolved remaining architectural debt, eliminated transaction-boundary coupling in the indexing engine, hardened AI generation concurrency handling, optimized retrieval and knowledge connection performance, and established production-grade runtime observability.

---

## Key Architectural Enhancements

### 1. Indexing Engine Decomposition & Atomic Transaction Isolation

- **`IndexingPipeline` Extraction (`backend/app/engine/pipeline.py`)**:
  - Encapsulated CPU- and I/O-intensive indexing tasks—file hashing, parser discovery, quality assessment (OCR gates, encrypted/corrupted document handling), hierarchical chunking, and embedding generation—into a standalone, database-decoupled pipeline.
  - Generates an immutable `IndexingPipelineResult` object outside of any SQLite transaction, eliminating lock contention and ensuring workers hold zero open write transactions during embedding inference.
  - Implemented strict unchanged hash and parser/chunker version bypass checking.

- **Atomic Index Persistence (`_persist_pipeline_outcome` in `backend/app/engine/worker.py`)**:
  - Consolidated index purging, chunk insertion, vector upsert, embedding model identity validation, file status update, and job completion into a single atomic SQLite write transaction.
  - Guaranteed the invariant: `chunk_vectors` virtual table entries are always purged before relational chunk pointers are destroyed.
  - Automatic rollback on any failure ensures that existing indexed files are never left in a corrupted or partially deleted state.

### 2. Event-Driven Worker Pool Coordination

- **`threading.Event` Worker Wake-Up (`backend/app/engine/worker.py`, `backend/app/engine/coordinator.py`)**:
  - Replaced fixed polling loops with event-driven worker notification (`self._wake_event`).
  - `WorkerPool.notify_job_available()` is triggered immediately upon folder scan discovery, file modification events, or new job enqueuing, reducing job claiming latency to near zero while eliminating CPU spinning during idle periods.

### 3. Retrieval & Browsing Performance Optimizations

- **Lexical Candidate Pool Expansion (`backend/app/retrieval/lexical.py`)**:
  - Expanded candidate fetch pool (`fetch_limit = max(top_k * 3, 100)`) so exact and partial filename boosts are evaluated across all candidate matches before slicing to `top_k`.
  - Preserves proper lexical scoring and prevents premature truncation of relevant documents.

- **Elimination of N+1 Queries in Related Content (`backend/app/retrieval/related.py`, `backend/app/db/repositories/files.py`)**:
  - Introduced `FileRepository.get_files_by_ids(file_ids, chunk_size=500)` for batched file lookups.
  - Replaced per-chunk sequential DB lookups with a single batched query, improving related content resolution performance significantly on large libraries.

- **Token Estimator ASCII Fast-Path (`backend/app/ai/context.py`)**:
  - Optimized `TokenEstimator.estimate()` with `isascii()` fast-path character-to-token heuristic (`len(text) // 4`), bypassing expensive regex iterations for standard Latin-script documents.

- **Knowledge Connections Optimization (`backend/app/ai/knowledge_connections.py`)**:
  - Scoped shared-topic lookups strictly to files with cached insights for the active model.
  - Bounded candidate target allocations to prevent memory bloat on large repositories.

- **PDF Column & Caption Spatial Filter (`backend/app/intelligence/parsers/pdf_parser.py`)**:
  - Replaced simple bounding box overlap checks with proportional area overlap ratio threshold (`>= 0.5`), protecting figure captions and grazing margins from inadvertent exclusion.

### 4. Generation Concurrency & Citation Resilience

- **Local Generation Concurrency (`backend/app/ai/generation.py`, `backend/app/routers/ai.py`)**:
  - Handled `LocalGenerationBusyError` in `GroundedGenerationService.generate_answer` with user-friendly error details and `GENERATION_FAILED` status.
  - Explicitly mapped `LocalGenerationBusyError` and `RuntimeError` in `/ai/ask` to HTTP 409 Conflict with informative error payloads.

- **Citation Regex Normalization (`backend/app/ai/citation.py`)**:
  - Upgraded citation parsing pattern to `re.compile(r"\[[Ee]\s*(\d+)\]")` supporting case insensitivity (`[e1]`), leading zeroes (`[E01]`, `[E001]`), and optional whitespace (`[E 1]`).

### 5. Observability & Degradation Tracking

- **Observability Infrastructure (`backend/app/core/observability.py`)**:
  - Added lightweight `LatencyTracker` context manager for tracking retrieval, reranking, and generation durations.
  - Added `build_degraded_metadata` helper for structured diagnostic reporting when retrieval operates in fallback mode.

---

## Verification & Quality Baseline

- **Full Backend Test Suite**: 540+ tests passing, 0 failures, 1 skipped.
- **Frontend Production Build**: `tsc && vite build` completed with zero errors.
- **Tauri Verification**: `cargo check --manifest-path src-tauri/Cargo.toml` passed cleanly.
- **API Contract Compatibility**: 100% backward-compatible across all existing endpoints.
