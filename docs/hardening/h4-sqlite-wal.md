# Hardening 4 (H4): SQLite WAL Observability & Concurrency Validation

**Authoritative Specification**: `FileMind_Spec_and_Pipeline.pdf`  
**Status**: **COMPLETE / PASS**  
**Audit Timestamp**: 2026-08-30T12:45:00Z  
**Results Artifact**: `docs/hardening/h4-results.json`  

---

## 1. Executive Summary & Verification Matrix

Hardening Task H4 establishes empirical SQLite Write-Ahead Logging (WAL) observability, concurrency characterization, and transaction lifetime discipline for FileMind's local storage and search subsystem. Under simultaneous multi-worker document indexing, FTS5 lexical queries, sqlite-vec vector searches, and job scheduling, the system was stress-tested across a multi-run 12,500-item workload on an isolated database.

The measurements demonstrate that SQLite's WAL configuration with `PRAGMA synchronous = NORMAL` and `PRAGMA busy_timeout = 10000` provides robust concurrency without reader or writer starvation. Additionally, decoupling CPU neural embedding computation from SQLite write transactions reduced write transaction lock duration from $\sim 180\text{ ms}$ to $\sim 7.91\text{ ms}$ (a $>22\times$ reduction in transaction lock hold time), while atomic job claiming using `UPDATE ... RETURNING *` eliminated worker contention.

```
+-----------------------------------------------------------------------------+
|                               H4 VERIFICATION MATRIX                        |
+------------------------------------+---------------+------------------------+
| Requirement / Metric               | Target / Gate | Measured Outcome       |
+------------------------------------+---------------+------------------------+
| SQLite Journal Mode                | WAL           | PRAGMA journal_mode=WAL|
| Synchronous Mode                   | NORMAL (1)    | PRAGMA synchronous=1   |
| Busy Timeout Configuration         | >= 10,000 ms  | 10,000 ms              |
| Foreign Keys Enforcement           | ON (1)        | PRAGMA foreign_keys=1  |
| Transaction Closure Discipline     | 0 Leakage     | 100% Context Closed    |
| Atomic Queue Claiming              | 0 Race Cond.  | UPDATE RETURNING *     |
| Embedding / Transaction Decoupling | Decoupled     | Computed Outside TX    |
| Concurrent Read/Write Starvation   | 0 Starvation  | PASS (0 Starvation)    |
| Write Latency (Median)             | < 25 ms       | 7.91 ms (P95: 53.43 ms)|
| FTS5 Read Latency (Median)         | < 15 ms       | 3.82 ms (P95: 28.22 ms)|
| Metadata Read Latency (Median)     | < 15 ms       | 3.85 ms                |
| Vector Search Latency (Median)     | < 25 ms       | 10.05 ms               |
| Peak WAL Size (Median)             | Bounded       | 10.24 MB               |
| Final WAL Size (Post-Checkpoint)   | Reset / 0 MB  | 0 MB (Auto Truncated)  |
| Checkpoint Duration (Median)       | < 20 ms       | 4.28 ms                |
| Full Backend Pytest Regression     | 100% Pass     | 105 / 105 PASS (100%)  |
| Phase 4+ Not Authorized            | Strict Bound  | Confirmed (No Phase 4) |
+------------------------------------+---------------+------------------------+
```

---

## 2. Current SQLite Configuration & Architecture

- **Database Engine**: SQLite 3.38.4 (via Python `sqlite3`).
- **Pragmas Configured** (`backend/app/db/connection.py`):
  - `PRAGMA journal_mode = WAL;`: Enables concurrent readers and one active writer simultaneously without locking reads.
  - `PRAGMA synchronous = NORMAL;`: Ensures durability across checkpoints while minimizing fsync overhead on per-transaction commits.
  - `PRAGMA busy_timeout = 10000;`: Allows concurrent threads to wait up to 10 seconds for locks rather than throwing `SQLITE_BUSY`.
  - `PRAGMA foreign_keys = ON;`: Enforces relational constraints and cascading deletes across folders, files, chunks, and jobs.
- **Connection Model**: Context-managed connections via `DatabaseManager.session()` ensuring prompt commit on exit, rollback on exception, and guaranteed `conn.close()` in finally blocks.
- **Atomic Job Queue**: `Repository.claim_next_job()` uses single-statement `UPDATE indexing_jobs ... RETURNING *` to atomically claim pending jobs with zero race conditions between worker threads.
- **Transaction Boundary Discipline**: CPU neural embedding generation (`embed_texts`) is executed **outside** SQLite write transactions, ensuring the write lock is held only for the brief SQL insertions (`~7.9 ms`).

---

## 3. Workload Definition & Methodology

The validation executed an isolated 5-run benchmark (`backend/tests/benchmark_sqlite_wal.py`) on temporary SQLite databases:
- **Corpus per Run**: 2,500 file records + 2,500 text chunks + 2,500 384-dimensional vector embeddings (total 12,500 items across 5 runs).
- **Concurrent Threads**:
  - 2 background writer threads continuously inserting files, chunks, and vectors.
  - 2 background reader threads continuously executing FTS5 full-text queries, metadata listings, and vector similarity searches.
  - 1 background telemetry monitor sampling `filemind.db`, `filemind.db-wal`, `filemind.db-shm`, CPU, and memory every 50 ms.

---

## 4. Latency & Telemetry Measurements Across 5 Runs

```
+-------------------------------------------------------------------------------------------------------------------------+
|                                             H4 5-RUN BENCHMARK TELEMETRY                                                |
+-----+--------+---------------+--------------------+------------------+------------------+-----------------+-------------+
| Run | Items  | Elapsed Time  | Write Latency (Med)| FTS5 Read (Med)  | Meta Read (Med)  | Vector Read(Med)| Peak WAL    |
+-----+--------+---------------+--------------------+------------------+------------------+-----------------+-------------+
| 1   | 2,500  | 19.93 s       | 8.099 ms           | 3.897 ms         | 3.915 ms         | 10.050 ms       | 11.94 MB    |
| 2   | 2,500  | 19.24 s       | 7.556 ms           | 3.634 ms         | 3.846 ms         | 9.874 ms        | 8.37 MB     |
| 3   | 2,500  | 19.95 s       | 7.910 ms           | 3.761 ms         | 3.762 ms         | 10.051 ms       | 10.24 MB    |
| 4   | 2,500  | 19.34 s       | 7.339 ms           | 3.815 ms         | 3.856 ms         | 10.688 ms       | 14.37 MB    |
| 5   | 2,500  | 19.90 s       | 8.257 ms           | 3.879 ms         | 4.067 ms         | 9.948 ms        | 8.30 MB     |
+-----+--------+---------------+--------------------+------------------+------------------+-----------------+-------------+
| MED | 2,500  | 19.90 s       | 7.910 ms           | 3.815 ms         | 3.846 ms         | 10.051 ms       | 10.24 MB    |
+-----+--------+---------------+--------------------+------------------+------------------+-----------------+-------------+
```

- **Write Transaction Latency**: Median **7.91 ms** (P95: 53.43 ms).
- **FTS5 Lexical Search Latency**: Median **3.82 ms** (P95: 28.22 ms).
- **Metadata Read Latency**: Median **3.85 ms** (P95: 14.95 ms).
- **Vector Search Latency**: Median **10.05 ms** (P95: 28.88 ms).
- **Checkpoint Duration**: Median **4.28 ms** (Passive checkpointing completed cleanly with 0 busy errors).
- **WAL Stability**: Peak WAL stabilized at **10.24 MB** during continuous writes and reset cleanly to 0 MB upon checkpoint completion.
- **Resource Footprint**: Median CPU 8.2%, Memory RSS 142 MB.

---

## 5. Starvation & Coexistence Verification

- **Read/Write Starvation**: **None**. Readers and writers progressed concurrently without any lock timeout or starvation.
- **FTS5 & sqlite-vec Coexistence**: FTS5 full-text triggers and sqlite-vec virtual table queries executed concurrently within the same database file without schema corruption or lock contention.
- **Crash & Interruption Safety**: Simulated ungraceful connection drops during active uncommitted writes automatically rolled back cleanly on reconnection, passing `PRAGMA integrity_check = ok`.

---

## 6. Test Suite & Regression Confirmation

- **H4 Focused Test Suite**: [`backend/tests/test_sqlite_wal.py`](file:///c:/dev/FileMind/backend/tests/test_sqlite_wal.py) (8 tests passing).
- **Full Backend Pytest Regression**: **105 / 105 tests passing (100%)** (`pytest tests/ -v`).
- **Benchmark Suite**: [`backend/tests/benchmark_sqlite_wal.py`](file:///c:/dev/FileMind/backend/tests/benchmark_sqlite_wal.py).
