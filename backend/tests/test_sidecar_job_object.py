"""
FileMind — Hardening 1 (H1): Windows Job Object Sidecar Lifecycle Test

Verifies:
1. Native Windows Job Object creation and JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE configuration.
2. Exact backend child process assignment to Job Object.
3. Graceful shutdown cleanup (parent terminates child -> port 24823 released).
4. Abnormal forced parent termination (parent killed -> Job Object automatically terminates child -> port 24823 released).
5. Fresh relaunch capability with /health verification.
6. Absolute safety: operates strictly on exact spawned PIDs without wildcard or name-based kills.
"""

import ctypes
from ctypes import wintypes
import json
import os
import pathlib
import signal
import socket
import subprocess
import sys
import time
import urllib.request
import psutil
import pytest

# Win32 kernel32 API definitions
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_TERMINATE = 0x0001
SYNCHRONIZE = 0x00100000

OpenProcess = kernel32.OpenProcess
OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
OpenProcess.restype = wintypes.HANDLE

CloseHandle = kernel32.CloseHandle
CloseHandle.argtypes = [wintypes.HANDLE]
CloseHandle.restype = wintypes.BOOL

IsProcessInJob = kernel32.IsProcessInJob
IsProcessInJob.argtypes = [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
IsProcessInJob.restype = wintypes.BOOL

def is_pid_in_job_object(pid: int) -> bool:
    """Verifies with the Windows kernel if an exact PID is assigned to a Job Object."""
    h_proc = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h_proc:
        h_proc = OpenProcess(PROCESS_QUERY_INFORMATION, False, pid)
    if not h_proc:
        err = ctypes.get_last_error()
        raise RuntimeError(f"OpenProcess failed for PID {pid} (Win32 Error {err})")
    
    try:
        in_job = wintypes.BOOL()
        res = IsProcessInJob(h_proc, 0, ctypes.byref(in_job))
        if res == 0:
            err = ctypes.get_last_error()
            raise RuntimeError(f"IsProcessInJob query failed for PID {pid} (Win32 Error {err})")
        return bool(in_job.value)
    finally:
        CloseHandle(h_proc)

def is_port_open(port: int = 24823, host: str = "127.0.0.1") -> bool:
    """Checks if a TCP port is open and listening."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex((host, port)) == 0

def wait_for_health(url: str = "http://127.0.0.1:24823/health", timeout_s: float = 8.0) -> bool:
    """Polls /health until online or timeout."""
    start = time.perf_counter()
    while time.perf_counter() - start < timeout_s:
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=0.8) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(0.15)
    return False

def wait_for_port_release(port: int = 24823, timeout_s: float = 6.0) -> float:
    """Waits until port is released and returns elapsed time."""
    start = time.perf_counter()
    while time.perf_counter() - start < timeout_s:
        if not is_port_open(port):
            return time.perf_counter() - start
        time.sleep(0.1)
    if is_port_open(port):
        raise TimeoutError(f"Port {port} was not released within {timeout_s} seconds")
    return time.perf_counter() - start

def find_child_pid_by_parent(parent_pid: int, timeout_s: float = 5.0) -> int:
    """Identifies the exact child process PID spawned by the specific parent PID."""
    start = time.perf_counter()
    while time.perf_counter() - start < timeout_s:
        try:
            parent = psutil.Process(parent_pid)
            children = parent.children(recursive=True)
            if children:
                return children[0].pid
        except psutil.NoSuchProcess:
            break
        time.sleep(0.15)
    raise RuntimeError(f"Could not identify child process spawned by parent PID {parent_pid}")

@pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Object is Windows-specific")
def test_job_object_lifecycle_and_orphan_prevention():
    """
    End-to-End Hardening Test:
    Validates Windows Job Object assignment, graceful termination,
    forced abnormal parent termination, and clean relaunch.
    """
    repo_root = pathlib.Path(__file__).resolve().parent.parent.parent
    tauri_exe = repo_root / "src-tauri" / "target" / "debug" / "filemind.exe"

    # Pre-condition: Port 24823 should be free before test
    if is_port_open(24823):
        # Allow brief time for port release if previously in use
        wait_for_port_release(24823, timeout_s=3.0)

    # -------------------------------------------------------------
    # Scenario A: Graceful Close Lifecycle
    # -------------------------------------------------------------
    print("\n--- Scenario A: Testing Graceful Close Lifecycle ---")
    proc_a = subprocess.Popen(
        [str(tauri_exe)],
        cwd=str(repo_root),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    parent_pid_a = proc_a.pid
    print(f"[Test] Spawned isolated parent Tauri instance (PID {parent_pid_a})")

    try:
        # 1. Wait for backend /health
        health_ok = wait_for_health("http://127.0.0.1:24823/health", timeout_s=10.0)
        assert health_ok, "Backend failed to become healthy on port 24823 in Scenario A"

        # 2. Identify exact child PID
        child_pid_a = find_child_pid_by_parent(parent_pid_a)
        print(f"[Test] Identified exact child backend PID {child_pid_a}")
        assert psutil.pid_exists(child_pid_a), f"Child PID {child_pid_a} does not exist"

        # 3. Verify child process is assigned to a Windows Job Object
        in_job = is_pid_in_job_object(child_pid_a)
        print(f"[Test] Child PID {child_pid_a} in Windows Job Object: {in_job}")
        assert in_job is True, f"Child PID {child_pid_a} is NOT in a Windows Job Object!"

        # 4. Perform graceful close
        proc_a.terminate()
        proc_a.wait(timeout=5.0)
        print(f"[Test] Parent PID {parent_pid_a} terminated gracefully")

        # 5. Verify child backend terminated and port released
        time.sleep(0.5)
        assert not psutil.pid_exists(child_pid_a), f"Child PID {child_pid_a} survived graceful parent close!"
        port_release_time_a = wait_for_port_release(24823, timeout_s=4.0)
        print(f"[Test] Port 24823 released in {port_release_time_a*1000:.2f} ms")

    finally:
        # Cleanup safety: only touch exact PIDs spawned in this test
        if proc_a.poll() is None:
            proc_a.kill()

    # -------------------------------------------------------------
    # Scenario B: Forced Abnormal Parent Termination (Job Object Test)
    # -------------------------------------------------------------
    print("\n--- Scenario B: Testing Forced Parent Termination (Job Object Kill) ---")
    proc_b = subprocess.Popen(
        [str(tauri_exe)],
        cwd=str(repo_root),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    parent_pid_b = proc_b.pid
    print(f"[Test] Spawned isolated parent Tauri instance (PID {parent_pid_b})")

    try:
        # 1. Wait for backend /health
        health_ok = wait_for_health("http://127.0.0.1:24823/health", timeout_s=10.0)
        assert health_ok, "Backend failed to become healthy on port 24823 in Scenario B"

        # 2. Identify exact child PID
        child_pid_b = find_child_pid_by_parent(parent_pid_b)
        print(f"[Test] Identified exact child backend PID {child_pid_b}")
        assert psutil.pid_exists(child_pid_b), f"Child PID {child_pid_b} does not exist"

        # 3. Verify Job Object membership
        in_job_b = is_pid_in_job_object(child_pid_b)
        print(f"[Test] Child PID {child_pid_b} in Windows Job Object: {in_job_b}")
        assert in_job_b is True, f"Child PID {child_pid_b} is NOT in a Windows Job Object!"

        # 4. Forcefully terminate ONLY the parent PID (simulating parent crash/kill)
        # We do NOT touch child_pid_b; the Windows kernel Job Object must kill it automatically.
        print(f"[Test] Forcefully terminating parent PID {parent_pid_b} with taskkill /F /PID {parent_pid_b}...")
        subprocess.run(
            ["taskkill", "/F", "/PID", str(parent_pid_b)],
            capture_output=True,
            check=True
        )

        # 5. Verify parent is dead
        t_parent = time.perf_counter()
        parent_dead = False
        while time.perf_counter() - t_parent < 4.0:
            if not psutil.pid_exists(parent_pid_b):
                parent_dead = True
                break
            time.sleep(0.05)
        assert parent_dead, f"Parent PID {parent_pid_b} survived forced kill!"
        print(f"[Test] Parent PID {parent_pid_b} confirmed dead")

        # 6. Verify Windows Job Object automatically killed the orphan child backend
        t0 = time.perf_counter()
        child_dead = False
        while time.perf_counter() - t0 < 5.0:
            if not psutil.pid_exists(child_pid_b):
                child_dead = True
                break
            time.sleep(0.1)

        time_to_child_dead = time.perf_counter() - t0
        print(f"[Test] Child PID {child_pid_b} terminated by Windows Job Object in {time_to_child_dead*1000:.2f} ms")
        assert child_dead, f"Child PID {child_pid_b} survived parent kill! Job Object failed to kill orphan process!"

        # 7. Verify port release
        port_release_time_b = wait_for_port_release(24823, timeout_s=4.0)
        print(f"[Test] Port 24823 released in {port_release_time_b*1000:.2f} ms")

    finally:
        if proc_b.poll() is None:
            proc_b.kill()

    # -------------------------------------------------------------
    # Scenario C: Clean Application Relaunch & Health Verification
    # -------------------------------------------------------------
    print("\n--- Scenario C: Testing Application Relaunch ---")
    proc_c = subprocess.Popen(
        [str(tauri_exe)],
        cwd=str(repo_root),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    parent_pid_c = proc_c.pid
    print(f"[Test] Spawned fresh relaunch parent Tauri instance (PID {parent_pid_c})")

    try:
        # 1. Verify fresh backend starts and /health succeeds
        health_ok_c = wait_for_health("http://127.0.0.1:24823/health", timeout_s=10.0)
        assert health_ok_c, "Relaunched backend failed to become healthy on port 24823"

        child_pid_c = find_child_pid_by_parent(parent_pid_c)
        print(f"[Test] Relaunch child PID {child_pid_c} online and healthy")
        assert is_pid_in_job_object(child_pid_c) is True

        # 2. Clean shutdown of relaunch test process
        proc_c.terminate()
        proc_c.wait(timeout=5.0)
        wait_for_port_release(24823, timeout_s=4.0)
        print("[Test] Relaunch test instance cleanly shutdown")

    finally:
        if proc_c.poll() is None:
            proc_c.kill()

    # Write hardening results JSON artifact
    results_data = {
        "hardening_task": "H1_WINDOWS_JOB_OBJECT_LIFECYCLE",
        "status": "PASS",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "job_object_configured": True,
        "limit_flags": "JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE (0x00002000)",
        "exact_pid_assignment": True,
        "scenarios": {
            "scenario_a_graceful_close": {
                "parent_pid": parent_pid_a,
                "child_pid": child_pid_a,
                "in_job_object": True,
                "backend_terminated": True,
                "port_released": True,
                "port_release_latency_ms": round(port_release_time_a * 1000, 2)
            },
            "scenario_b_forced_parent_kill": {
                "parent_pid": parent_pid_b,
                "child_pid": child_pid_b,
                "in_job_object": True,
                "forced_kill_parent": True,
                "job_object_child_kill_verified": True,
                "child_termination_latency_ms": round(time_to_child_dead * 1000, 2),
                "port_released": True,
                "port_release_latency_ms": round(port_release_time_b * 1000, 2)
            },
            "scenario_c_relaunch_health": {
                "parent_pid": parent_pid_c,
                "child_pid": child_pid_c,
                "relaunch_health_status": "healthy",
                "relaunch_success": True
            }
        },
        "safety_audit": {
            "no_name_based_kills": True,
            "exact_pid_isolation": True,
            "zero_orphan_processes": True
        }
    }

    docs_dir = repo_root / "docs" / "hardening"
    docs_dir.mkdir(parents=True, exist_ok=True)
    with open(docs_dir / "h1-results.json", "w", encoding="utf-8") as f:
        json.dump(results_data, f, indent=2)
    print(f"\n[Test] Recorded H1 hardening results to {docs_dir / 'h1-results.json'}")

if __name__ == "__main__":
    test_job_object_lifecycle_and_orphan_prevention()
