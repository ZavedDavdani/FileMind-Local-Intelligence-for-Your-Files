# Pre-Phase-5 Hardening & Practical Audit Verification Report

**Status**: COMPLETE / VERIFIED PASS
**Committed Hardening Checkpoint**: `c7c6bd7` (`fix: complete pre-phase-5 integrity hardening`)
**Phase 4**: CLOSED
**Phase 5**: STRICTLY NOT STARTED

---

## 1. Executive Summary

Prior to initiating Phase 5 (Local RAG / LLM Integration), FileMind underwent a two-stage integrity hardening and real-world practical audit pass:
1. **Pre-Phase-5 Integrity Hardening (Batches A1, A2, A3, A3.1)**: Addressed vector-layer atomicity, multi-format text encoding fallback, corrupted PDF page recovery, deterministic canonical JSON chunk identity hashes, character overlap (`overlap_chars`), markdown table preservation, and scanner version invalidation.
2. **Pre-Phase-5 Practical Audit Fixes (Issues 1, 2, 3)**: Fixed Tauri v2 desktop dialog capability permissions, implemented deterministic same-file candidate grouping with expandable multi-chunk evidence drawers, and established deterministic explicit filename intent detection with consistent not-found state across all retrieval modes.
3. **Second Brain Architecture Document**: Established the authoritative 16-section product architecture specification in `FileMind_Second_Brain_Architecture.md`.

---

## 2. Hardening Batches & Implementations

### Batch A1 — Vector-Layer Integrity
- **Orphan Vector Purge**: Enforced atomic deletion in `chunk_vectors` prior to upserting new vectors on file re-indexing or deletion.
- **Rollback Safety**: Transactional rollback handlers wrap vector store updates and SQLite chunk metadata replacement to prevent orphan vector leakage during partial failure.
- **Index Metadata**: Validated `embedding_index_metadata` schema ensuring vector store dimensions and embedding models (`sentence-transformers/all-MiniLM-L6-v2`, 384-dim) match at runtime.

### Batch A2 — Corpus Decoding & PDF Integrity
- **Strict UTF-8 & BOM Decoding**: Implemented deterministic `read_text_file_strictly` and `decode_bytes_strictly` with strict UTF-8 (`utf-8-sig`) decoding. Undecodable non-UTF-8 byte sequences explicitly raise `CorruptedDocumentError` to prevent silent evidence corruption with Unicode replacement characters.
- **Fault-Tolerant PDF Extraction**: Implemented page-by-page PyMuPDF extraction, ensuring valid pages are preserved and indexed even when individual PDF pages contain damaged streams or broken xrefs.
- **Document Metadata**: Normalized structural metadata across all supported document types.

### Batch A3 — Chunking & Evidence Integrity
- **Deterministic Chunk Identity**: Replaced ambiguous colon-delimited chunk ID hashing with canonical JSON serialization (`sha256(canonical_json(provenance_dict))`).
- **Character Overlap Chunking**: Implemented `overlap_chars` in `HierarchicalChunker` to ensure continuity across chunk boundaries without header splitting.
- **Markdown Table Preservation**: Kept markdown tables unified within chunks to maintain tabular integrity for subsequent retrieval and LLM context assembly.

### Batch A3.1 — Reprocessing Vector Integrity & Version Migration
- **Chunker Version Migration**: Incremented `CHUNKER_VERSION` to `"phase2-hierarchical-v2"` in `app/intelligence/chunker/hierarchical.py`.
- **Scanner Invalidation**: Updated `FilesystemScanner` to detect version mismatches between indexed chunks and active parser/chunker versions, automatically scheduling re-parsing even for unchanged files on disk.
- **Zero Orphan Guarantee**: Proven that re-indexing purges 100% of old vectors with zero vector-store leakage.

---

## 3. Practical Audit Fixes

### Issue 1 — Browse / Select Folder Does Nothing
- **Root Cause**: In Tauri v2, `tauri-plugin-dialog` requires capability permissions defined under `src-tauri/capabilities/`. Without a capability file, IPC invocations (`open({ directory: true, ... })`) were rejected.
- **Remediation**: Created `src-tauri/capabilities/default.json` with `["core:default", "opener:default", "dialog:allow-open"]` for window `"main"`.
- **Verification**: Verified via `cargo check` and regression test `test_tauri_dialog_capability_configured`.

### Issue 2 — Multiple Chunks From Same File Appear As Separate Search Results
- **Root Cause**: The search presentation layer mapped individual chunks 1-to-1 to top-level search cards, cluttering the UI when multiple chunks in a single document matched.
- **Remediation**: Implemented deterministic file-level grouping in `frontend/src/components/SearchModal.tsx`.
  - The top-ranked chunk represents the file card.
  - Multi-chunk matches display a badge (`"{N} relevant chunks found"`) with an expandable evidence drawer (`"▼ View {N-1} more matching chunks in this file"`).
  - All per-chunk scores, line numbers, breadcrumbs, `Inspect Chunk`, `Open File`, `Open Folder`, and `Copy Path` actions are preserved.
- **Verification**: Verified via `npm run build` and regression test `test_same_file_grouping_helper_invariants`.

### Issue 3 — Unindexed Filename Search Is Inconsistent
- **Root Cause**: When searching for an explicit unindexed filename (e.g. `nonexistent_report.pdf`), BM25 returned 0 results, but Dense vector search embedded the filename string and matched unrelated chunks by cosine similarity, which Hybrid Fast and Quality surfaced.
- **Remediation**: Added `extract_explicit_filename_intent()` in `backend/app/retrieval/hybrid.py`.
  - If an explicit filename is not present in `files` (with `index_status != 'MISSING'`), the retriever immediately returns `total_found: 0, results: []` consistently across **BM25**, **Dense**, **Hybrid Fast**, and **Hybrid Quality**.
  - Normal content and semantic queries (e.g. `"How does semantic retrieval work?"`, `"What is inside report.pdf?"`) bypass filename filtering and execute standard full-corpus semantic retrieval.
  - The UI presents a clear `"File not found or not indexed"` state.
- **Verification**: Verified with 3 dedicated regression tests in `test_audit_practical_fixes.py`.

---

## 4. Test & Quality Verification Results

| Suite | Tests Run | Passed | Skipped | Failed | Result |
|---|---|---|---|---|---|
| **Practical Audit Regressions** (`test_audit_practical_fixes.py`) | 6 | 6 | 0 | 0 | **PASS** |
| **Reprocessing Integrity** (`test_batch_a3_1_reprocessing_integrity.py`) | 6 | 6 | 0 | 0 | **PASS** |
| **Hierarchical Chunker** (`test_hierarchical_chunker.py`) | 12 | 12 | 0 | 0 | **PASS** |
| **Document Parsers** (`test_parsers.py`) | 15 | 15 | 0 | 0 | **PASS** |
| **Reranker Suite** (`test_reranker.py`) | 24 | 24 | 0 | 0 | **PASS** |
| **Hybrid Fallback** (`test_hybrid_fallback.py`) | 14 | 14 | 0 | 0 | **PASS** |
| **Full Backend Regression Suite** | **324** | **323** | **1** | **0** | **PASS** |
| **Frontend Production Build** (`tsc && vite build`) | 1,603 modules | 1,603 | 0 | 0 | **PASS** |
| **Tauri Desktop Verification** (`cargo check`) | — | — | — | 0 | **PASS** |
| **Git Whitespace Quality** (`git diff --check`) | — | — | — | 0 | **PASS** |

---

## 5. Phase 5 Boundary Lock

FileMind strictly maintains the following boundary:
- **Phase 5 is NOT STARTED.**
- **No LLM / Ollama client code has been added.**
- **No generative RAG or answer synthesis has been introduced.**
- **FileMind operates strictly as a 100% deterministic local evidence retrieval engine.**
