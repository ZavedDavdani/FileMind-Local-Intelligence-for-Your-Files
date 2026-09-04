# Phase 6 Pre-Phase-7 Architecture Hardening: AppContext & Dependency Injection

**Status**: ✅ **COMPLETE / VERIFIED**  
**Starting Baseline**: Phase 6 Frozen Baseline (`1c9f8de`)  
**Hardening Scope**: Batch 1 — Explicit `AppContext` and Hierarchical Dependency Injection  
**Contract Verification**: 100% behavior preservation, 0 API schema/route/status code changes, 0 frontend alterations, singleton model lifecycle preservation.

---

## 1. Executive Summary

As part of pre-Phase-7 architectural hardening, FileMind introduced an explicit application-scoped dependency container (`AppContext`) to eliminate implicit cross-module singleton references and provide a clean, testable dependency injection architecture across the FastAPI application layer and domain services.

### Key Outcomes:
1. **Application Scope Ownership**: `AppContext` encapsulates and manages core runtime dependencies:
   - `DatabaseManager` (`db_manager`)
   - `EmbeddingEngine` (`embedding_engine`)
   - `CrossEncoderReranker` (`reranker`)
   - `ModelRegistry` (`model_registry`)
   - `GenerationCoordinator` (`generation_coordinator`)
   - `EngineCoordinator` (`engine_coordinator`)
2. **Hierarchical FastAPI Dependencies**:
   - `get_app_context` resolves the active context from `request.app.state.context` (or `default_app_context` fallback).
   - `get_db` consumes `AppContext` to yield managed database sessions.
   - `get_repo` consumes the session to yield the domain `Repository` façade.
3. **Explicit Service Wiring**: Domain services (`AskService`, `DocumentUnderstandingService`, `FolderUnderstandingService`, `RelatedContentService`, `GroundedGenerationService`, `HybridRetriever`) now receive their runtime engines and coordinators explicitly rather than importing module-level singletons.
4. **Isolated Testing & Test Overrides**: Tests can cleanly override dependencies at the top level via `app.dependency_overrides[get_app_context]` without monkey-patching global module internals.

---

## 2. Architecture & Design

### Container Architecture

```
                    ┌─────────────────────────┐
                    │      FastAPI App        │
                    │ (app.state.context=ctx) │
                    └───────────┬─────────────┘
                                │
                    ┌───────────▼─────────────┐
                    │       AppContext        │
                    │  (app/core/context.py)  │
                    └──────┬───────────┬──────┘
                           │           │
          ┌────────────────▼───┐   ┌───▼────────────────────┐
          │   Data Layer       │   │   AI & Engine Layer    │
          │  - db_manager      │   │  - embedding_engine    │
          │                    │   │  - reranker            │
          │                    │   │  - model_registry      │
          │                    │   │  - generation_coord    │
          │                    │   │  - engine_coordinator  │
          └────────────────────┘   └────────────────────────┘
```

### Dependency Resolution Chain

```
HTTP Request
     │
     ▼
[get_app_context] ──► Extracts ctx from request.app.state.context (or default_app_context)
     │
     ├──────────────► Injected directly into routers for engine/coordinator controls
     │
     ▼
  [get_db] ──────────► Uses ctx.db_manager.session() to manage connection lifecycle
     │
     ▼
 [get_repo] ─────────► Instantiates Repository(conn) with domain sub-repositories
     │
     ▼
Route Handler / Domain Services
```

---

## 3. Backward Compatibility & Test Isolation

To ensure 100% backward compatibility with existing tests that patch module-level globals (such as `app.main.db_manager`), `AppContext` implements dynamic fallback properties:

```python
class AppContext:
    def __init__(self, db_manager=None, embedding_engine=None, ...):
        self._db_manager = db_manager
        ...

    @property
    def db_manager(self) -> DatabaseManager:
        if self._db_manager is not None:
            return self._db_manager
        import app.main as _main
        return _main.db_manager
```

This guarantees:
- **Zero Regression**: Legacy tests with direct monkeypatches continue to work seamlessly.
- **Modern DI Capability**: New tests can construct an isolated `AppContext` and register it with `app.dependency_overrides[get_app_context]`.

---

## 4. Verification & Release Gate Results

| Test Suite | Command / Verification | Result | Details |
|---|---|---|---|
| **Backend Unit & Integration Tests** | `pytest backend/tests` | ✅ **PASS** | 528 passed, 1 skipped (0 failures) |
| **AppContext Dedicated Tests** | `pytest backend/tests/test_core_app_context.py` | ✅ **PASS** | 3 passed (context isolation & route override) |
| **Frontend Production Build** | `npm run build` (frontend) | ✅ **PASS** | Vite production bundle compiled cleanly |
| **Tauri Desktop Verification** | `cargo check --manifest-path src-tauri/Cargo.toml` | ✅ **PASS** | 0 compile errors |
| **API Contract Invariants** | 26 API routes & schemas | ✅ **PRESERVED** | 100% schema & status code compatibility |
| **Singleton Lifecycle** | Memory & model load verification | ✅ **VERIFIED** | 0 duplicate heavy model allocations |
