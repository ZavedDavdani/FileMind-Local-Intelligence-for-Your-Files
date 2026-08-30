# FileMind Phase 1 — Validation Report

**Status**: **PASS**  
**Phase**: 1 — Filesystem Engine  
**Authoritative References**: `FileMind_Spec_and_Pipeline.pdf` & `FileMind.md`  
**Evaluation Date**: 2026-08-30  
**Scope Status**: STRICT BOUNDARY ADHERENCE (Zero Phase 2+ functionality present)

---

## 1. Environment

- **Operating System**: Windows 11 Pro / Enterprise x64 (`Windows-10-10.0.26200-SP0`)
- **Host CPU**: Intel64 Family 6 Model 154 Stepping 3, GenuineIntel
- **RAM**: 16.0 GB System Memory
- **Python Runtime**: Python 3.11.0 (64-bit) in `backend/.venv`
- **Database Engine**: SQLite 3.39+ (WAL mode, busy timeout 10,000ms, Foreign Keys ON)
- **Filesystem Engine Store**: `%APPDATA%\FileMind\filemind.db`
- **Node / Frontend Tooling**: Node.js v20+, Vite 6.4.3, React 18, TypeScript 5

---

## 2. Build / Commit

- **Repository**: `C:\dev\FileMind`
- **Git Branch**: `master`
- **Phase 0 Baseline**: Verified PASS (Standalone bundled binary `src-tauri/binaries/filemind-backend.exe`, NSIS installer `dist/FileMind_0.1.0_x64-setup.exe`)
- **Phase 1 Backend Status**: Fast-path & Strict SQLite Engine (`backend/app/`)
- **Frontend Status**: Production build verified (`dist/` built in 4.11s with 0 TypeScript diagnostics)

---

## 3. Test Fixtures

- **Synthetic Directory Tree (Primary Benchmark)**:
  - Total Files: 1,150 files across 8 directory hierarchies
  - Clean Files: 1,000 text documents distributed over 5 nested directory levels (`docs/`, `src/components/`, `src/utils/`, `assets/images/`, `reports/2026/q1/`)
  - Excluded Trees: 150 files in high-noise structures (`node_modules/package_a/`, `.git/objects/`, `venv/Lib/`)
  - File Sizes: ~800 bytes per clean file (average); 50 MB synthetic binary block for streaming cryptographic hashing
- **Realistic Directory Tree (Supplementary Workload Benchmark)**:
  - Total Files: 575 files across 6 directory hierarchies (depth 4)
  - Clean Files: 500 mixed documents (`.txt`, `.md`, `.py`, `.json`, `.csv`, `.log`) with realistic size distribution: 70% small (1-5 KB), 25% medium (20-80 KB), 5% large (200-500 KB), total ~15 MB dataset
  - Excluded Trees: 75 files in `node_modules/library/dist`, `.git/objects/pack`, `venv/Lib/site-packages`
- **Temporary Resources**: All test databases and filesystem trees allocated under `tempfile.gettempdir()` and cleaned up on completion.

---

## 4. Benchmark Methodology

- **Discovery Throughput**:
  - Boundary: Timer starts immediately prior to `scanner.scan_folder()` execution and stops upon returning after all discovered files are upserted into SQLite `files` table and jobs are enqueued in `indexing_jobs`.
  - Condition: Real disk scan over 1,000 clean files across 5 nested directories + 150 excluded files.
- **Streaming SHA-256 Cryptographic Hashing (Single-File Ceiling)**:
  - Boundary: Timer starts before opening 50 MB binary file and stops when `compute_file_sha256()` completes hashing via 64 KB buffers.
  - Condition: Real disk I/O, single-threaded streaming computation.
- **Worker Queue Processing**:
  - Boundary: Timer starts upon `WorkerPool.start()` and stops when SQLite `files` table records 1,000 `INDEXED` files.
  - Condition: Real SQLite transactions, 4 worker threads, streaming hashing and atomic updates.
- **Watchdog Event-to-State Latency**:
  - Boundary: Timer starts when OS `open().write()` is executed and stops when the event debouncer normalizes and logs the record in SQLite `file_events`.
  - Condition: Real Windows filesystem notifications supervised by `watchdog.observers.Observer`. Includes the configured 500 ms debouncing window.
- **Crash Recovery Latency**:
  - Boundary: Timer starts when `repo.recover_stale_processing_jobs()` is invoked and stops upon commit of all resets (`PROCESSING` $\rightarrow$ `PENDING`).
  - Condition: 50 stale jobs recovered in SQLite.

---

## 5. Audited Benchmark Results (5-Run Multi-Run Baseline)

All primary metrics were evaluated across 5 consecutive, independent test runs:

| Metric | Target | Run 1 | Run 2 | Run 3 | Run 4 | Run 5 | **Median** | **Range (Min - Max)** | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Discovery Throughput** | $> 200\text{ files/s}$ | 761.56 | 878.33 | 715.84 | 767.54 | 748.38 | **761.56 files/s** | 715.84 – 878.33 | **PASS** |
| **SHA-256 Throughput** | $> 200\text{ MB/s}$ | 656.04 | 656.73 | 554.88 | 517.88 | 606.74 | **606.74 MB/s** | 517.88 – 656.73 | **PASS** |
| **Queue Throughput** | $> 100\text{ jobs/s}$ | 205.85 | 219.51 | 210.47 | 237.19 | 216.76 | **216.76 jobs/s** | 205.85 – 237.19 | **PASS** |
| **Watcher Latency** | $< 1000\text{ ms}$ | 558.50 | 554.80 | 555.97 | 557.59 | 556.51 | **556.51 ms** | 554.80 – 558.50 | **PASS** |
| **Crash Recovery Latency** | $< 1000\text{ ms}$ | 10.68 | 13.04 | 8.02 | 10.41 | 11.87 | **10.68 ms** | 8.02 – 13.04 | **PASS** |
| **Idle Process Memory (RSS)** | $< 100\text{ MB}$ | — | — | — | — | — | **27.62 MB** | — | **PASS** |
| **Idle CPU Utilization** | $< 2.0\%$ | — | — | — | — | — | **0.0%** | — | **PASS** |

### Supplementary Realistic Filesystem Workload Benchmark (5 Runs)
*Evaluates three distinct independent timers on 500 mixed-size files (1 KB to 500 KB) in a nested directory tree:*

| Workload Metric | Timer Boundary | Run 1 | Run 2 | Run 3 | Run 4 | Run 5 | **Median** | **Range** | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Workload Discovery** | `scanner.scan_folder()` entry $\rightarrow$ return after persisting 500 rows | 661.81 | 766.90 | 533.88 | 323.62 | 738.78 | **661.81 files/s** | 323.62 – 766.90 | **PASS** |
| **Realistic Hashing-Only** | `hash timer start` $\rightarrow$ sequential streaming of 500 files via 64 KB buffers $\rightarrow$ `hash complete` (excludes all worker/SQLite overhead) | 88.23 | 82.63 | 34.23 | 31.87 | 74.15 | **74.15 MB/s** | 31.87 – 88.23 | **PASS** |
| **End-to-End Worker Rate** | `worker pool start` $\rightarrow$ all 500 files reach `INDEXED` in SQLite (includes queue, hashing, and SQLite updates) | 208.35 | 204.95 | 166.39 | 157.42 | 210.26 | **204.95 jobs/s** | 157.42 – 210.26 | **PASS** |

*Note on Realistic Hashing-Only: The 74.15 MB/s throughput (median 2,460.33 files/sec) measures pure streaming SHA-256 across hundreds of small/medium discrete files, reflecting real per-file operating system open/read/close overhead, whereas the 606.74 MB/s ceiling measures single-file continuous streaming throughput.*

---

## 6. Historical Measurements

The original single-run measurements from the initial Phase 1 implementation report are preserved below for full historical audit transparency:

- **Original Discovery Throughput**: `731.03 files/sec`
- **Original SHA-256 Throughput**: `1,007.14 MB/sec`
- **Original Worker Queue Throughput**: `240.98 jobs/sec`
- **Original Watcher Event Latency**: `556.45 ms`
- **Original Crash Recovery Latency**: `9.33 ms`
- **Original Memory (RSS)**: `25.97 MB`
- **Original CPU**: `0.0%`
- *Historical Note*: The original figures were single-run measurements. The 5-run audited statistics in Section 5 supersede them as the permanent Phase 1 performance baseline.

---

## 7. Integration Test Evidence

- **Test File**: `backend/tests/test_engine_integration.py`
- **Demonstrated Behaviors & Assertions**:
  1. **Initial Discovery** (`test_full_filesystem_engine_lifecycle`):
     - Asserts all initial files are registered in SQLite with exact paths, sizes, extensions, and valid initial SHA-256 hashes.
  2. **Dynamic Creation** (`test_full_filesystem_engine_lifecycle`):
     - Creates `created_later.txt` post-indexing; asserts scanner detects new file, worker computes SHA-256, and state reaches `INDEXED`.
  3. **File Modification** (`test_full_filesystem_engine_lifecycle`):
     - Modifies content of `doc1.txt`; verifies scanner detects `mtime` change, re-queues file, preserves `file_id` identity, and persists newly computed cryptographic hash.
  4. **Delete Handling** (`test_delete_handling_isolated`):
     ```python
     # Assert SQLite delete handling contract
     marked = repo.mark_file_missing(file_path)
     assert marked is True
     cancelled_count = repo.cancel_pending_jobs_for_file(file_id)
     assert cancelled_count >= 1
     f_state = repo.get_file_by_id(file_id)
     assert f_state["index_status"] == "MISSING"
     cursor = conn.execute("SELECT COUNT(*) FROM indexing_jobs WHERE file_id = ? AND status IN ('PENDING', 'PROCESSING');", (file_id,))
     assert cursor.fetchone()[0] == 0
     ```
  5. **Rename Handling** (`test_rename_handling_isolated`):
     ```python
     # Assert file rename preserves file_id identity and updates SQLite path
     renamed = repo.rename_file_path(old_path=src_path, new_path=dst_path, new_rel_path="new_name.txt", new_filename="new_name.txt", new_ext=".txt")
     assert renamed is True
     assert repo.get_file_by_path(src_path) is None
     new_rec = repo.get_file_by_path(dst_path)
     assert new_rec["file_id"] == original_file_id
     assert new_rec["filename"] == "new_name.txt"
     ```
  6. **Move Handling** (`test_move_handling_isolated`):
     ```python
     # Assert file moved to subfolder updates relative_path and preserves folder_id and file_id
     moved = repo.rename_file_path(old_path=src_path, new_path=dst_path, new_rel_path="subfolder/moved_doc.txt", new_filename="moved_doc.txt", new_ext=".txt")
     assert moved is True
     assert repo.get_file_by_path(src_path) is None
     moved_rec = repo.get_file_by_path(dst_path)
     assert moved_rec["file_id"] == original_file_id
     assert moved_rec["folder_id"] == folder_id
     assert moved_rec["relative_path"] == "subfolder/moved_doc.txt"
     ```

---

## 8. Watcher Evidence

- **Test File**: `backend/tests/test_watcher.py`
- **Test Functions**:
  - `test_event_debouncer_coalesces_rapid_modifications`: Verifies 5 rapid `MODIFY` events on the same file within debounce window coalesce into 1 single event.
  - `test_event_debouncer_create_then_modify`: Verifies immediate `CREATE + MODIFY` sequence normalizes to single `CREATE`.
  - `test_watcher_service_detects_live_file_events`: **Real OS temp-directory integration test**. Performs real OS disk writes and validates that `watchdog` captures and normalizes live `CREATE`, `MODIFY`, `RENAME`, and `DELETE` events, logging them into SQLite `file_events`.
- **Latency Debounce Disclosure**: The measured end-to-end watcher path was 556.51 ms and includes the configured 500 ms sliding debounce window. The remaining ~56.51 ms must not be interpreted as pure OS watcher notification latency because it also includes other processing and scheduling overhead.

---

## 9. Crash Recovery Evidence

- **Test File**: `backend/tests/test_crash_recovery.py`
- **Test Functions**:
  - `test_stale_processing_job_recovery_after_simulated_crash`: Validates SQLite transaction resetting stranded `PROCESSING` jobs to `PENDING`.
  - `test_real_subprocess_termination_and_recovery`: **Real Child Process Interruption Test**.
    1. Spawns dedicated Python worker child process (`subprocess.Popen`).
    2. Captures exact child PID.
    3. Worker claims job into `PROCESSING`.
    4. Test forcibly kills ONLY that exact child PID (`proc.kill()`).
    5. Confirms process termination (`proc.poll() is not None`).
    6. Starts fresh `EngineCoordinator` on the database.
    7. Asserts stale job is detected and recovered to `PENDING`.
    8. Asserts background worker claims and completes the job to `INDEXED` with valid SHA-256 hash without full folder rebuild.

---

## 10. Security Evidence

- **Test File**: `backend/tests/test_path_security.py`
  - Canonical absolute path normalization (`test_normalize_path_basic`).
  - Rejection of null-byte injection `\x00` (`test_normalize_path_rejects_null_bytes`).
  - Rejection of empty/whitespace paths (`test_normalize_path_rejects_empty`).
  - Verification of safe subpath containment (`test_is_path_within_root_valid_children`).
  - Blocking of relative `..` traversals and root escapes (`test_is_path_within_root_traversal_attempts`, `test_validate_subpath_safety_raises_on_escape`).
- **Test File**: `backend/tests/test_exclusions.py`
  - In-place skipping of default noise directories (`node_modules`, `.git`, `__pycache__`, `venv`, `dist`, `build`, `.cache`, `temp`).
  - In-place skipping of noise files (`*.tmp`, `*.log`, `~$*`, `desktop.ini`, `thumbs.db`, `.ds_store`).
  - Custom user-configured exclusion glob patterns.

---

## 11. Scope Boundary Audit

A comprehensive codebase audit was conducted across `backend/` and `frontend/` searching for Phase 2+ terminology and imports (`docling`, `pdfplumber`, `pypdf`, `fitz`, `docx`, `pptx`, `chunk`, `embedding`, `vector`, `bm25`, `rerank`, `rag`, `ollama`, `mlflow`, `ragas`, `sentence_transformer`, `torch`).

### Audit Findings:
- **Phase 2+ functional code present**: **NO**
- **Statement**: *"Repository audit found no functional Phase 2+ implementation."*
- **Speculative hooks/stubs**: None. `worker.py` and `coordinator.py` implement only metadata discovery, streaming SHA-256 hashing, deletion cleanup, and recovery.

---

## 12. Failures & Resolutions

1. **SQLite Timestamp Converter Incompatibility**:
   - *Issue*: Python 3.11 `sqlite3.PARSE_DECLTYPES` raised `ValueError` on ISO-8601 timestamps containing `'T'`.
   - *Resolution*: Updated schema definitions to explicit `TEXT` columns and removed `PARSE_DECLTYPES`, preserving strict ISO-8601 formatting.
2. **SQLite In-Memory Database Isolation in Tests**:
   - *Issue*: Separate connection sessions to `:memory:` produced distinct isolated databases in tests.
   - *Resolution*: Switched integration test fixtures to isolated temporary `.db` files under `tempfile.gettempdir()`.
3. **Windows File Locking during Cleanup**:
   - *Issue*: Open SQLite handles prevented immediate `shutil.rmtree` cleanup on Windows.
   - *Resolution*: Ensured `coordinator.shutdown()` explicitly stops all worker and watcher threads and closes SQLite sessions before fixture teardown.

---

## 13. Current Phase 0 Cold-Start Sanity Check

To confirm that the newly integrated Phase 1 backend components (SQLite, watchdog, worker pool) have not degraded Phase 0 cold-start characteristics:

- **Launch Path**: `backend/.venv/Scripts/python.exe` / packaged binary $\rightarrow$ `/health` 200 OK
- **Measured Runs**:
  - Run 1: **3.710 s**
  - Run 2: **3.705 s**
  - Run 3: **3.475 s**
- **Current Median**: **3.705 s** (Range: `3.475 s – 3.710 s`)
- **Original Phase 0 Baseline**: **3.247 s**
- **Delta**: **+0.458 s**
- **Conclusion**: The +0.458s difference accounts for initial database schema verification and worker initialization on launch. The application remains well within the strict $\le 5.0\text{ s}$ cold-start budget.

---

## 14. Evidence-Linked Gate Checklist

| Requirement | Result | Evidence |
| :--- | :--- | :--- |
| **Folder Registration** | PASS | `backend/tests/test_api_folders_files.py::test_folders_api_crud` |
| **Recursive Discovery** | PASS | `backend/tests/test_engine_integration.py::test_full_filesystem_engine_lifecycle` |
| **Exclusion Filtering** | PASS | `backend/tests/test_exclusions.py::test_default_directory_exclusions` |
| **Metadata Persistence** | PASS | `backend/tests/test_engine_integration.py::test_full_filesystem_engine_lifecycle` |
| **Normal Integrity Mode** | PASS | `backend/tests/test_change_detection.py::test_change_detection_normal_vs_strict` |
| **Strict Integrity Mode** | PASS | `backend/tests/test_change_detection.py::test_change_detection_normal_vs_strict` |
| **Watcher Event Capture** | PASS | `backend/tests/test_watcher.py::test_watcher_service_detects_live_file_events` |
| **Event Normalization** | PASS | `backend/tests/test_watcher.py::test_event_debouncer_coalesces_rapid_modifications` |
| **Event Deduplication** | PASS | `backend/tests/test_watcher.py::test_event_debouncer_create_then_modify` |
| **Persistent Job Queue** | PASS | `backend/tests/test_job_queue.py::test_job_queue_state_transitions` |
| **Asynchronous Workers** | PASS | `backend/tests/test_job_queue.py::test_worker_pool_processes_jobs_asynchronously` |
| **Failure Isolation** | PASS | `backend/tests/test_change_detection.py::test_sha256_missing_file_handling` |
| **Retry / Backoff** | PASS | `backend/tests/test_job_queue.py::test_job_retry_exponential_backoff` |
| **Cancellation** | PASS | `backend/tests/test_engine_integration.py::test_full_filesystem_engine_lifecycle` |
| **Delete Handling** | PASS | `backend/tests/test_engine_integration.py::test_delete_handling_isolated` |
| **Rename Handling** | PASS | `backend/tests/test_engine_integration.py::test_rename_handling_isolated` |
| **Move Handling** | PASS | `backend/tests/test_engine_integration.py::test_move_handling_isolated` |
| **Path Security** | PASS | `backend/tests/test_path_security.py::test_validate_subpath_safety_raises_on_escape` |
| **Crash Recovery** | PASS | `backend/tests/test_crash_recovery.py::test_real_subprocess_termination_and_recovery` |
| **Restart Without Full Rebuild** | PASS | `backend/tests/test_crash_recovery.py::test_real_subprocess_termination_and_recovery` |
| **Progressive Indexing State** | PASS | `backend/tests/test_api_folders_files.py::test_indexing_status_and_control` |
| **SQLite Persistence** | PASS | `backend/tests/test_engine_integration.py::test_full_filesystem_engine_lifecycle` |
| **Measurement Consistency** | PASS | `docs/phase-1/verify_measurement_consistency.py` (7/7 matched, 0 mismatched) |
| **Benchmark Record** | PASS | `backend/tests/measure_phase1.py` generating `docs/phase-1/measurements.json` |
| **Scope Boundary Clean** | PASS | Zero Phase 2+ parsing/chunking/vector/RAG dependencies present |

---

## 15. Final Gate Decision & Report Integrity

**Phase 1 Gate Decision**: **APPROVED / PASS**

- Programmatic verification by `docs/phase-1/verify_measurement_consistency.py` confirmed that all median, mean, range, and resource values reported in Section 5 match `docs/phase-1/measurements.json` with 100% precision.
- Resource measurement provenance: Measured dynamically on Python 3.11 with worker threads and watcher active (27.62 MB RSS RAM, 0.0% idle CPU).
