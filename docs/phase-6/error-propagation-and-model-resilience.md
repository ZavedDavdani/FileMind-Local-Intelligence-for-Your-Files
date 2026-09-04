# Phase 6 Bug Fix Pass 1: Error Propagation & Model Resilience Report

**Status**: ✅ **COMPLETE / VERIFIED**  
**Phase Baseline**: Phase 5 Frozen at `fc6e4a4` (`chore: finalize phase 5 hardening and freeze`)  
**Phase 6 Refactor**: `668ecf7` (`docs(phase-6): add backend architecture refactor documentation and update roadmap`)  
**Test Suite Verification**: 505 passed, 0 failed, 1 skipped (100% passing across 84 test suites)  
**Contract Verification**: 100% existing API schemas, response shapes, and HTTP status codes preserved.

---

## 1. Executive Summary

This bug-fix pass resolved three confirmed production error propagation and model resilience defects, ensuring that detected errors are persisted, auditable, and surfaced to UI callers rather than dropped or silently treated as unblemished successes:

1. **Bug 1 (P1 - Data Integrity / Visibility)**: Replaced fake `system-scan` job failures during discovery scanning with a dedicated `record_scan_error()` method, Schema Migration V8 (`SCAN_ERROR` check constraint in `file_events`), and atomic file status updates (`FAILED`, `indexing_error`).
2. **Bug 2 (P2 - Model Resilience / CPU Exhaustion)**: Replaced 0.0s retry cooldown in `EmbeddingEngine` and `Reranker` with configurable `EMBEDDING_RETRY_COOLDOWN_SECONDS` and `RERANKER_RETRY_COOLDOWN_SECONDS` (defaults: 30.0s, env overrides: `FILEMIND_EMBED_RETRY_COOLDOWN_SEC`, `FILEMIND_RERANK_RETRY_COOLDOWN_SEC`), preventing continuous thread re-spawning during persistent model failure.
3. **Bug 3 (P1 - Vector Mismatch Visibility)**: Ensured vector-write skips on model mismatch and embedding generation warnings populate `indexing_error` on the file record while preserving `INDEXED` status for FTS5/BM25 keyword search access.

---

## 2. Detailed Bug Fixes

### Bug 1: Discovery Scan Errors & Phantom Jobs

- **Root Cause**: When `FilesystemScanner` encountered a `PermissionError` or `OSError` on an existing file during scanning, it called `self.repo.fail_job(job_id="system-scan", ...)` which failed silently because no row with `job_id="system-scan"` exists in `indexing_jobs`. The file remained in its prior state with no error visibility.
- **Solution**:
  - Added `record_scan_error(file_id: str, error_message: str) -> bool` to `FileRepository` and `Repository`.
  - Added `MIGRATION_V8_SQL` and bumped `SCHEMA_VERSION = 8` to support `SCAN_ERROR` event type in `file_events`.
  - If a scanned file encounters an OS/permission error, `record_scan_error` marks the file `index_status = 'FAILED'`, persists `indexing_error`, and logs a `SCAN_ERROR` audit event in `file_events`. Missing files (`index_status == 'MISSING'`) are ignored.
  - Scanner continues scanning remaining files without crashing or fabricating fake jobs.

### Bug 2: Embedding & Reranker Retry Cooldown

- **Root Cause**: `RETRY_COOLDOWN_SECONDS` was hardcoded to `0.0` in `embeddings.py` and `reranker.py`, causing `_ensure_loaded()` to immediately spawn a new background daemon thread on every single request when a model download/load was failing, exhausting threads and CPU.
- **Solution**:
  - Added `EMBEDDING_RETRY_COOLDOWN_SECONDS` (env: `FILEMIND_EMBED_RETRY_COOLDOWN_SEC`, default: 30.0s) and `RERANKER_RETRY_COOLDOWN_SECONDS` (env: `FILEMIND_RERANK_RETRY_COOLDOWN_SEC`, default: 30.0s) to `app/core/config.py`.
  - Connected `EmbeddingEngine` and `Reranker` to these configurable constants.
  - Calls within the cooldown window fail-fast immediately with the cached `_init_error` without starting new threads or re-attempting expensive operations.
  - After cooldown expiration, retry is cleanly permitted.

### Bug 3: Vector Mismatch & Embedding Warning Visibility

- **Root Cause**: In `worker.py`, when `vec_store.verify_index_validity(identity)` detected a model mismatch (or embedding generation threw a warning), the worker logged the warning and called `complete_job` with `indexing_error=None`. As a result, the file was marked `INDEXED` with no indication that dense vector embeddings were skipped.
- **Solution**:
  - Tracked `vector_write_skipped_reason` throughout `_process_job`.
  - On model identity mismatch or embedding exception, `vector_write_skipped_reason` is set with detailed context.
  - In `complete_job`, `final_status="INDEXED"` is preserved (allowing BM25 keyword search), and `indexing_error` is populated with `vector_write_skipped_reason` (or combined with `parse_warning_msg` via `" | "` if both occur).

---

## 3. Comprehensive Error Propagation Audit

| Location | Error Condition | Handling Strategy | Persisted State / Destination | Visible to UI / Caller |
|:---|:---|:---|:---|:---|
| `discovery.py` | Top-level folder `scandir` error | Append to `DiscoveryResult.errors` | Returned in scan response | Yes (via scan API response) |
| `discovery.py` | `PermissionError` / `OSError` on file | `repo.record_scan_error(file_id, msg)` | `files.index_status = 'FAILED'`, `files.indexing_error`, `file_events (SCAN_ERROR)` | Yes (Files table & Events list) |
| `discovery.py` | Oversized file (`> MAX_FILE_SIZE_BYTES`) | Early skip in upsert | `files.index_status = 'SKIPPED'`, `files.indexing_error` | Yes (Files list & status badge) |
| `discovery.py` | Offline deleted file | `repo.mark_file_missing`, cancel jobs, enqueue `DELETE_CLEANUP` | `files.index_status = 'MISSING'`, cleanup job enqueued | Yes (Files list marked missing) |
| `worker.py` | File deleted before processing | Permanent job failure | `indexing_jobs.status = 'FAILED'`, `files.index_status = 'FAILED'` | Yes (Jobs & Files view) |
| `worker.py` | Oversized file guard | Skip parsing & hashing | `files.index_status = 'SKIPPED'`, `files.indexing_error` | Yes (Files list) |
| `worker.py` | SHA-256 hashing error | Job failure with retry/backoff | `indexing_jobs.status = 'FAILED'`, `files.indexing_error` | Yes (Jobs retry queue) |
| `worker.py` | Unsupported format / No parser | Complete job as SKIPPED | `files.index_status = 'SKIPPED'`, `files.indexing_error` | Yes (File details) |
| `worker.py` | `REQUIRES_OCR` quality gate | Complete job as SKIPPED, purge stale vectors/chunks | `files.index_status = 'SKIPPED'`, `files.indexing_error = qa.to_json()` | Yes (File details & QA badge) |
| `worker.py` | `PARSE_WARNING` quality gate | Complete job as INDEXED, persist warning | `files.index_status = 'INDEXED'`, `files.indexing_error = qa.to_json()` | Yes (File details) |
| `worker.py` | Embedding generation warning / timeout | Record skipped reason, persist chunks, complete INDEXED | `files.index_status = 'INDEXED'`, `files.indexing_error` | Yes (File details & diagnostics) |
| `worker.py` | Vector model identity mismatch | Refuse vector write, record reason, complete INDEXED | `files.index_status = 'INDEXED'`, `files.indexing_error = mismatch_reason` | Yes (File details & re-index prompt) |
| `worker.py` | `EncryptedDocumentError` | Complete job as SKIPPED | `files.index_status = 'SKIPPED'`, `files.indexing_error = "Encrypted/Password Protected: ..."` | Yes (File details) |
| `worker.py` | `CorruptedDocumentError` | Fail job permanently | `indexing_jobs.status = 'FAILED'`, `files.index_status = 'FAILED'` | Yes (Jobs & Files view) |
| `worker.py` | Unhandled parser exception | Fail job permanently | `indexing_jobs.status = 'FAILED'`, `files.index_status = 'FAILED'` | Yes (Jobs & Files view) |
| `embeddings.py` | Model init failure within cooldown | Fail-fast with cached exception without spawning threads | Propagated `RuntimeError` | Yes (Retrieval falls back to BM25) |
| `reranker.py` | Model init failure within cooldown | Fail-fast with cached exception without spawning threads | Propagated `RuntimeError` | Yes (Retrieval falls back to RRF) |

---

## 4. Verification & Test Coverage

### Dedicated Test Suites Added:
1. `backend/tests/test_scan_error_propagation.py` (5 tests)
   - `test_repository_record_scan_error_success`
   - `test_repository_record_scan_error_ignores_missing_files`
   - `test_repository_record_scan_error_nonexistent_file`
   - `test_discovery_scanner_permission_error_propagation`
   - `test_discovery_scanner_oserror_propagation`
2. `backend/tests/test_model_retry_cooldown.py` (6 tests)
   - `test_embedding_retry_cooldown_defaults`
   - `test_config_env_var_overrides`
   - `test_embedding_fail_fast_within_cooldown`
   - `test_embedding_retry_allowed_after_cooldown`
   - `test_reranker_fail_fast_within_cooldown`
   - `test_reranker_retry_allowed_after_cooldown`
3. `backend/tests/test_vector_mismatch_visibility.py` (4 tests)
   - `test_vector_mismatch_populates_indexing_error_and_keeps_indexed`
   - `test_matching_identity_clears_indexing_error`
   - `test_parse_warning_and_vector_mismatch_combination`
   - `test_embedding_generation_failure_preserves_indexed_with_warning`

### Full Suite Run:
- **Pytest**: 505 passed, 0 failed, 1 skipped (0:02:38).
- **Frontend**: `npm run build` completed cleanly (0 errors).
- **Desktop**: `cargo check` in `src-tauri/` passed (0 errors).
- **Git Diff**: `git diff --check` clean (0 whitespace/formatting issues).
