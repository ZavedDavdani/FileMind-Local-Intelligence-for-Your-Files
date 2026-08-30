# Hardening 1 (H1): Windows Job Object Sidecar Lifecycle Dossier

**Authoritative Specification**: `FileMind_Spec_and_Pipeline.pdf`  
**Status**: **COMPLETE / PASS**  
**Audit Timestamp**: 2026-08-30T11:55:00Z  
**Results Artifact**: `docs/hardening/h1-results.json`  

---

## 1. Executive Summary & Verification Matrix

Hardening Task H1 mitigates the risk of orphaned Python sidecar processes on abnormal parent process termination (e.g. `taskkill /F`, process crash, Task Manager "End Task", or power loss). By encapsulating the backend process in a Windows Job Object with the `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` flag, the Windows kernel guarantees atomic process termination when the parent process handle closes.

```
+-----------------------------------------------------------------------------+
|                               H1 VERIFICATION MATRIX                        |
+------------------------------------+---------------+------------------------+
| Requirement / Gate                 | Target / Gate | Measured Outcome       |
+------------------------------------+---------------+------------------------+
| Native Job Object Creation         | Win32 Success | VERIFIED (CreateJob)   |
| Kill-On-Job-Close Flag Configured  | 0x00002000    | VERIFIED (SetInfoJob)  |
| Exact Backend Process Assignment   | Exact PID     | VERIFIED (AssignProc)  |
| IsProcessInJob Kernel Verification | 100% True     | VERIFIED (Win32 API)   |
| Graceful Shutdown Child Teardown   | Clean Exit    | PASS (304.29 ms port)  |
| Abnormal Forced Parent Termination | 100% Killed   | PASS (201.25 ms child) |
| Port 24823 Availability on Relaunch| Port Free     | PASS (309.65 ms port)  |
| Fresh Instance /health Online      | 200 OK        | PASS (Relaunch 200 OK) |
| PID Safety (Zero Wildcard Kills)   | Exact PIDs    | VERIFIED               |
| Full Backend Pytest Regression     | 100% Pass     | 77 / 77 PASS (100%)    |
+------------------------------------+---------------+------------------------+
```

---

## 2. Vulnerability Analysis & Root Cause

### A. The Orphan Process Hazard
On Windows desktop applications with sidecar architectures:
- Under **graceful shutdown**, Tauri's `WindowEvent::CloseRequested` or `RunEvent::Exit` sends termination signals to the child process (`child.kill()`, `child.wait()`).
- Under **abnormal shutdown** (application crash, forced parent-process termination via `taskkill /F /PID <exact-parent-pid>`, Task Manager kill, or power loss), event loop exit handlers in the parent process NEVER execute.
- Without kernel-level lifecycle binding, the child process survives detached in the background, continuously occupying TCP port `24823` and consuming RAM.
- Upon subsequent application launch, the new Tauri supervisor fails to bind port `24823` or interacts with a stale backend instance.

### B. Windows Kernel Solution
Windows Job Objects provide operating-system-level process grouping. By calling `SetInformationJobObject` with `JobObjectExtendedLimitInformation` and setting:

`LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE (0x00002000)`

the Windows kernel registers an immutable contract: when all open handles to the Job Object are closed (which the OS kernel performs automatically upon parent process termination for any reason), all processes assigned to that Job Object are immediately and unconditionally terminated by the kernel.

---

## 3. Implementation Details

### A. Rust Implementation Location
- **Job Object Module**: [`src-tauri/src/job_object.rs`](file:///c:/dev/FileMind/src-tauri/src/job_object.rs)
- **Sidecar Supervisor**: [`src-tauri/src/main.rs`](file:///c:/dev/FileMind/src-tauri/src/main.rs)

### B. RAII Guard Structure (`JobObjectGuard`)
The `JobObjectGuard` struct wraps the raw `HANDLE` to the Win32 Job Object:
1. **Creation**: Calls `CreateJobObjectW(ptr::null(), ptr::null())`.
2. **Configuration**: Configures `JOBOBJECT_EXTENDED_LIMIT_INFORMATION` with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`.
3. **Assignment**: Extracts `child.as_raw_handle()` and invokes `AssignProcessToJobObject(self.handle, raw_handle)`.
4. **Lifecycle Ownership**: Stored inside `BackendState` protected by `Arc<Mutex<BackendState>>`.
5. **Drop Implementation**: Calls `CloseHandle(self.handle)` upon graceful exit.

---

## 4. Test Methodology & Evidence

The integration test suite is located in [`backend/tests/test_sidecar_job_object.py`](file:///c:/dev/FileMind/backend/tests/test_sidecar_job_object.py) and executes 3 sequential lifecycle scenarios:

1. **Scenario A (Graceful Close)**:
   - Spawns isolated parent Tauri instance (PID 7484).
   - Verifies exact child backend PID (19676) is assigned to Job Object via Win32 `IsProcessInJob`.
   - Sends graceful `terminate()` to parent.
   - Verifies backend child terminated and port 24823 released in **304.29 ms**.
2. **Scenario B (Forced Abnormal Parent Termination)**:
   - Spawns second isolated parent Tauri instance (PID 10112).
   - Verifies exact child backend PID (12608) is assigned to Job Object.
   - Issues forced termination `taskkill /F /PID 10112` strictly on parent PID.
   - Confirms parent is dead.
   - Verifies Windows kernel Job Object terminates child PID 12608 in **201.25 ms**.
   - Verifies port 24823 released in **309.65 ms**.
3. **Scenario C (Relaunch & Health)**:
   - Spawns third fresh instance (PID 8892, child PID 14448).
   - Verifies `/health` returns HTTP 200 OK with `status: "healthy"`.
   - Cleanly shuts down test instance.

---

## 5. Explicit Limitations & Boundaries

1. **Process Lifecycle vs SQLite Integrity**:
   - Job Objects guarantee **process-lifecycle ownership and orphan prevention**.
   - They do **NOT** replace or validate SQLite transaction semantics or crash recovery.
   - SQLite ACID/WAL crash consistency is handled separately by FileMind's database connection and job queue recovery architecture.
2. **Safety Invariant**:
   - Tests and runtime never use wildcard or process-name based kills (`taskkill /IM` is strictly forbidden). Only exact tracked PIDs are managed.
3. **Scope Boundary**:
   - Hardening H1 is strictly bounded. Hardening tasks H2, H3, H4, and Phase 4 remain NOT STARTED / NOT AUTHORIZED.
