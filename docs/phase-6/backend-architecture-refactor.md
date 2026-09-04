# Phase 6 Backend Architecture & Performance Refactor Report

**Status**: ✅ **COMPLETE / VERIFIED**  
**Starting Baseline**: Phase 5 Frozen at `fc6e4a4` (`chore: finalize phase 5 hardening and freeze`, 476 passed, 1 skipped)  
**Refactor Commit**: Clean Phase 6 architectural modularization  
**Contract Verification**: 100% behavior preservation, 0 API schema/route/status code changes, 0 frontend alterations.

---

## 1. Executive Summary

Phase 6 addresses structural debt concentrated in the backend layer (`main.py`, `Repository` God Object, unbatched `KnowledgeConnectionService` queries) without altering API schemas, HTTP semantics, database tables, or desktop contracts.

### Major Achievements:
1. **Knowledge Connections Optimization**: Eliminated $O(\text{chunks} \times \text{files})$ DB roundtrips by introducing batched document insight/chunk/citation lookups and precomputed reference candidate indexes.
2. **Repository Decomposition**: Decomposed the monolithic ~50-method `Repository` into 6 focused domain repositories (`FolderRepository`, `FileRepository`, `JobRepository`, `EventRepository`, `ChunkRepository`, `InsightRepository`) composed under a unified `Repository` compatibility façade.
3. **FastAPI Dependencies & Error Handling**: Replaced repetitive session context managers with request-scoped `get_repo` and dynamic `get_db` providers, and centralized AI service error mapping via `@map_service_errors`.
4. **Security Boundary Extraction**: Extracted `/fs/action` path verification into `resolve_and_authorize` in `app/core/security.py`, maintaining strict containment, normalization, symlink/junction, and traversal protections.
5. **Modular Routers**: Replaced the ~900-line monolithic `main.py` with 8 modular `APIRouter` modules under `app/routers/`.

---

## 2. Architecture Comparison

### Before (Monolithic God Object Architecture):
```
Tauri Desktop Supervisor / React Frontend
   │ (REST JSON)
   ▼
FastAPI backend/app/main.py (~900 lines, 25+ routes, inline DB wiring, repeated try/except blocks)
   │ (14x with db_manager.session(): repo = Repository(conn))
   ▼
backend/app/db/repository.py (50+ method God Object owning folders, files, jobs, events, chunks, vectors, insights)
   │
   ▼
SQLite Database (WAL mode)
```

### After (Modular Domain Architecture):
```
Tauri Desktop Supervisor / React Frontend
   │ (REST JSON - 100% Identical Contracts)
   ▼
FastAPI backend/app/main.py (Application composition, lifespan, CORS, health)
   │
   ├── app/routers/
   │     ├── folders.py       (Folder CRUD & watcher sync)
   │     ├── files.py         (Tracked files & chunk inspection)
   │     ├── indexing.py      (Coordinator state & indexing controls)
   │     ├── events.py        (Filesystem audit trail)
   │     ├── jobs.py          (Worker jobs lifecycle)
   │     ├── fs_actions.py    (Safe desktop actions via security boundary)
   │     ├── search.py        (Hybrid retrieval & related content)
   │     └── ai.py            (Ask FileMind, Document/Folder understanding, Knowledge connections)
   │
   ├── app/core/
   │     ├── deps.py          (Request-scoped get_repo, dynamic get_db)
   │     ├── errors.py        (Centralized @map_service_errors decorator)
   │     └── security.py      (resolve_and_authorize security boundary)
   │
   ├── app/db/
   │     ├── repository.py    (Unified Repository compatibility façade)
   │     └── repositories/
   │           ├── folders.py     (FolderRepository)
   │           ├── files.py       (FileRepository)
   │           ├── jobs.py        (JobRepository)
   │           ├── events.py      (EventRepository)
   │           ├── chunks.py      (ChunkRepository)
   │           └── insights.py    (InsightRepository)
   │
   ▼
SQLite Database (WAL mode)
```

---

## 3. Knowledge Connections Performance Optimization

### The Problem:
Previously, `KnowledgeConnectionService.get_connections(file_id)` performed:
- Up to 100,000 files loaded sequentially.
- Per-file `get_document_insight()` query ($N$ DB roundtrips).
- Per-file `get_chunks_by_file()` query ($N$ DB roundtrips).
- Per-citation `get_chunk_by_id()` query ($M$ DB roundtrips).
- Nested chunk $\times$ file regex scans on every request.

### The Solution:
1. **Batched Database Retrieval**:
   - `repo.get_document_insights_by_files(file_ids, model_name)`
   - `repo.get_chunks_by_files(file_ids)`
   - `repo.get_chunks_by_ids(chunk_ids)`
2. **SQLite Parameter Limit Safety**:
   - Queries partition parameter lists into safe slices of $\le 500$ parameters (well below SQLite variable limits).
3. **Precomputed Candidate Indexing**:
   - Filename uniqueness map and `(relative_path, unique_filename, target_file)` reference candidate list constructed once per request.
   - Single pass over source chunks matching against the candidate index with stable priority ranking (relative path > unique basename).
4. **Complexity**:
   - Reduced database roundtrips from $O(N + M)$ to $O(\lceil N / 500 \rceil)$.
   - Algorithmic complexity reduced from $O(\text{chunks} \times \text{files})$ to $O(\text{chunks} + \text{files})$.

---

## 4. Verification Results

| Test Suite / Check | Command | Baseline (Phase 5 Freeze) | Phase 6 Refactor Result | Status |
|---|---|---|---|---|
| **Backend Test Suite** | `pytest -q backend/tests/` | 476 passed, 1 skipped | **490 passed, 1 skipped** (0 failed) | ✅ PASS |
| **Frontend Production Build** | `npm run build` (`frontend/`) | 1,606 modules transformed | **1,606 modules transformed, 0 errors** | ✅ PASS |
| **Tauri Desktop Check** | `cargo check` (`src-tauri/`) | 0 warnings/errors | **Finished in 17.07s, 0 errors** | ✅ PASS |
| **Git Diff Formatting** | `git diff --check` | Clean | **Clean (0 whitespace errors)** | ✅ PASS |
| **Circular Import Audit** | Dynamic Python module import test | Clean | **Clean (0 circular imports)** | ✅ PASS |

---

## 5. File Inventory

### Created Files:
- `backend/app/core/deps.py`
- `backend/app/core/errors.py`
- `backend/app/routers/__init__.py`
- `backend/app/routers/folders.py`
- `backend/app/routers/files.py`
- `backend/app/routers/indexing.py`
- `backend/app/routers/events.py`
- `backend/app/routers/jobs.py`
- `backend/app/routers/fs_actions.py`
- `backend/app/routers/search.py`
- `backend/app/routers/ai.py`
- `backend/app/db/repositories/__init__.py`
- `backend/app/db/repositories/folders.py`
- `backend/app/db/repositories/files.py`
- `backend/app/db/repositories/jobs.py`
- `backend/app/db/repositories/events.py`
- `backend/app/db/repositories/chunks.py`
- `backend/app/db/repositories/insights.py`
- `backend/tests/test_core_deps_and_errors.py`
- `backend/tests/test_core_security.py`
- `backend/tests/test_domain_repositories.py`
- `docs/phase-6/backend-architecture-refactor.md`

### Modified Files:
- `backend/app/main.py` (reduced from 888 lines to 105 lines)
- `backend/app/db/repository.py` (reduced from 1,214 lines to 44 lines)
- `backend/app/ai/knowledge_connections.py` (batched queries & precomputed indexing)
- `backend/app/core/security.py` (extracted `resolve_and_authorize`)
- `backend/tests/test_knowledge_connections.py` (extended test cases)
- `README.md` & `FileMind.md` (updated architectural status)
