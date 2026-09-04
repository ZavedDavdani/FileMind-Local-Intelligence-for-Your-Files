# FileMind — Chunk 2 Remediation & Architectural Contracts

This document establishes the verified architectural invariants and lifecycle contracts implemented and validated during **Remediation Chunk 2**.

---

## 1. Job Lifecycle & Ownership State Machine

```
[Discovery / Watcher]
        |
        v
    [PENDING] -------- (Disabled folder) --------> [SKIPPED on Claim]
        |
        +-- (claim_next_job with attempts + 1)
        v
   [PROCESSING]
        |
        +-- (Successful Pipeline) --------> [INDEXED]
        +-- (Corrupted / Permanent Error) -> [FAILED]
        +-- (Transient / Timeout Error) ----> [PENDING with retry_at]
        +-- (Superseded by Newer Job) -----> [Discarded / Stale Write Skipped]
        +-- (Directory/File Deleted) ------> [MISSING reconciles terminal]
```

### Invariants:
1. **Ownership (`is_current_processing_job`)**:
   - A job owns the write for its file if and only if it is in `PROCESSING` or `PENDING` state and no newer job has been enqueued (`created_at` or `started_at` superseding).
   - Stale workers whose jobs have been superseded are prevented from writing chunks/vectors or transitioning the file state.
2. **Attempt Accounting (Bug 119)**:
   - Worker crashes and engine restarts invoke `recover_stale_processing_jobs()`, which adjusts `attempts = MAX(0, attempts - 1)` when resetting `PROCESSING` jobs to `PENDING`.
   - Reclaiming a recovered job increments `attempts` by 1, correctly attributing only genuine executions against the retry budget without burning attempts on crash recovery.
3. **Disabled Folders (Bug 118)**:
   - `claim_next_job()` joins `folders` and checks `(folders.indexing_enabled = 1 OR job_type = 'DELETE_CLEANUP')`.
   - Indexing work for disabled folders remains queued in `PENDING` state without being claimed, while `DELETE_CLEANUP` jobs proceed to completion.

---

## 2. Vector Deletion and Cascade Invariants (Bugs 27, 28, 115)

`chunk_vectors` is a SQLite `vec0` virtual table. Because SQLite virtual tables do not support native foreign key triggers across table types:
1. **Two-Phase Atomic Deletion**:
   - Deletion of files or folders always purges the virtual `chunk_vectors` table **first** before removing relational rows from `chunks`, `files`, or `folders`.
   - In `Repository.purge_file_index(file_id)`:
     ```sql
     DELETE FROM chunk_vectors WHERE chunk_id IN (SELECT chunk_id FROM chunks WHERE file_id = ?);
     DELETE FROM chunks WHERE file_id = ?;
     ```
   - In `FolderRepository.delete_folder(folder_id)`:
     ```sql
     DELETE FROM chunk_vectors WHERE chunk_id IN (
         SELECT c.chunk_id FROM chunks c
         JOIN files f ON c.file_id = f.file_id
         WHERE f.folder_id = ?
     );
     DELETE FROM folders WHERE folder_id = ?;
     ```
2. **Deletion Cleanup (`DELETE_CLEANUP`, Bugs 37 & 88)**:
   - Claiming a `DELETE_CLEANUP` job does **not** set `files.index_status = 'PROCESSING'`.
   - Completing a `DELETE_CLEANUP` job explicitly passes `final_status="MISSING"`, preserving missing/deleted file lifecycle semantics.

---

## 3. Embedding Dimensions & Model Diagnostics (Bugs 33 & 34)

1. **Explicit Dimension Validation (Bug 33)**:
   - `EmbeddingEngine` requires explicit model dimension registration via `MODEL_DIMENSIONS` or `ModelRegistry`.
   - Instantiating an unknown or unregistered model raises a diagnostic `ValueError` rather than silently defaulting to 384 dimensions.
2. **Nomic Prefix Symmetry (Bug 34)**:
   - Nomic models (`nomic-ai/nomic-embed-text-v1.5`) require asymmetric search prefixes:
     - Document / chunk embedding (`embed_texts`): `search_document: <text>`
     - Query embedding (`embed_query`): `search_query: <text>`
   - Both `embed_texts` and `embed_query` apply the respective prefix symmetrically for Nomic models, while leaving standard embedding models un-prefixed.

---

## 4. Index Validity & Retrieval Invariants (Bugs 32 & 35)

1. **Adaptive Vector Search Recall (Bug 32)**:
   - When metadata filters (folder ID, extension, file ID) restrict the candidate space, `SqliteVecStore.search()` adaptively expands candidate fetch (`fetch_k = max(fetch_k * 4, fetch_k + top_k * 10)`) across up to 10 iterations.
   - Prevents premature search termination and guarantees candidate recall across large indices.
2. **Index Metadata Verification (Bug 35)**:
   - `SqliteVecStore.verify_index_validity()` strictly rejects non-empty vector indices lacking recorded metadata or having mismatched provider, model name, or dimension.
   - An uninitialized / empty vector store with no metadata is considered valid.

---

## 5. File Lifecycle Protection (Bug 29 & 31)

1. **Lifecycle Preservation on Rediscovery (Bug 29)**:
   - `FileRepository.upsert_file()` uses conditional SQL `CASE` expressions on conflict:
     - Preserves `INDEXED`, `PROCESSING`, `FAILED`, and `SKIPPED` when file modification time and size are unchanged.
     - Transitions to `QUEUED` only when mtime/size changes, the file was previously `MISSING`, or explicit reprocess is requested.
2. **Race Protection (Bug 31)**:
   - If a directory or file is marked `MISSING` while a background worker is `PROCESSING`, `_persist_pipeline_outcome` and `complete_job()` check the file's current state and abort writing stale chunks.

---

## 6. Worker & Concurrency Invariants (Bugs 25, 26, 30, 39, 40, 95)

1. **Constructor & Notification Contract (Bugs 25 & 26)**:
   - `EngineCoordinator` and `WorkerPool` constructors accept optional `embedding_engine` dependencies.
   - File discovery and watcher flush invoke `self.worker_pool.notify_job_available()`, triggering `_wake_event.set()` for immediate event-driven worker execution without busy polling (Bug 40).
2. **Aggregate Status (Bug 30)**:
   - `get_aggregate_status()` queries `file_counts["QUEUED"]` and `file_counts["PROCESSING"]` directly from `files` status, avoiding double-counting with `indexing_jobs`.
3. **Session Lifetime (Bug 39)**:
   - `EngineCoordinator.scan_all_enabled_folders()` scopes each folder scan to an independent, short-lived SQLite write session, preventing long lock holding across multi-folder scans.
4. **Connection Lifecycle (Bug 95)**:
   - `DatabaseManager.session()` configures WAL mode, 10s busy timeout, normal synchronous, and foreign keys per connection. Connection pooling is deferred to the dedicated performance optimization pass.
