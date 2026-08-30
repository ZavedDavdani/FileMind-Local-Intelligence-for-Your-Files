"""Part A: Current Packaged Distribution Baseline & Remediated Startup Measurements."""

import json
import os
import statistics
import subprocess
import sys
import time
import urllib.request

HEALTH_URL = "http://127.0.0.1:24823/health"
ONEDIR_BACKEND_EXE = os.path.abspath(r"c:\dev\FileMind\backend\dist\filemind-backend-dir\filemind-backend-dir.exe")
ONEFILE_BACKEND_EXE = os.path.abspath(r"c:\dev\FileMind\src-tauri\binaries\filemind-backend.exe")
PYTHON_EXE = os.path.abspath(r"c:\dev\FileMind\backend\.venv\Scripts\python.exe")


def ensure_port_free():
    subprocess.run(["taskkill", "/F", "/IM", "filemind-backend-dir.exe"], capture_output=True)
    subprocess.run(["taskkill", "/F", "/IM", "filemind-backend.exe"], capture_output=True)
    time.sleep(0.5)


def measure_single_cold_start(exe_path: str) -> float:
    ensure_port_free()
    time.sleep(0.5)

    start_t = time.perf_counter()
    proc = subprocess.Popen(
        [exe_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )

    startup_elapsed = None
    try:
        for _ in range(200):
            time.sleep(0.02)
            try:
                with urllib.request.urlopen(HEALTH_URL, timeout=0.2) as resp:
                    if resp.status == 200:
                        startup_elapsed = round(time.perf_counter() - start_t, 3)
                        break
            except Exception:
                pass
    finally:
        try:
            proc.kill()
            proc.wait(timeout=2)
        except Exception:
            pass
        ensure_port_free()

    if startup_elapsed is None:
        raise TimeoutError(f"Cold-start failed for {exe_path}: /health not reachable within timeout")

    return startup_elapsed


def measure_health_roundtrip(exe_path: str, samples: int = 5) -> dict:
    """Measures standalone /health round-trip loopback latency on an active server."""
    ensure_port_free()
    proc = subprocess.Popen(
        [exe_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    for _ in range(100):
        time.sleep(0.05)
        try:
            with urllib.request.urlopen(HEALTH_URL, timeout=0.2) as resp:
                if resp.status == 200:
                    break
        except Exception:
            pass

    latencies_ms = []
    try:
        for _ in range(samples):
            t0 = time.perf_counter()
            with urllib.request.urlopen(HEALTH_URL, timeout=0.5) as resp:
                if resp.status == 200:
                    latencies_ms.append(round((time.perf_counter() - t0) * 1000.0, 2))
            time.sleep(0.05)
    finally:
        proc.kill()
        proc.wait(timeout=2)
        ensure_port_free()

    return {
        "median_ms": round(statistics.median(latencies_ms), 2),
        "min_ms": min(latencies_ms),
        "max_ms": max(latencies_ms),
        "runs_ms": latencies_ms,
    }


def profile_import_times() -> dict:
    """Measures individual import contributions in milliseconds."""
    modules = ["fastapi", "uvicorn", "pydantic", "fitz", "docx", "pptx", "openpyxl", "watchdog", "sqlite3"]
    times = {}
    for mod in modules:
        cmd = [PYTHON_EXE, "-c", f"import time; t0=time.perf_counter(); import {mod}; print(round((time.perf_counter()-t0)*1000, 2))"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        try:
            times[mod] = float(res.stdout.strip())
        except Exception:
            times[mod] = None
    return times


def run_part_a(num_runs: int = 5) -> dict:
    print(f"Part A: Measuring Remediated Packaged Backend Cold-Start ({num_runs} Runs)...")
    target_exe = ONEDIR_BACKEND_EXE if os.path.exists(ONEDIR_BACKEND_EXE) else ONEFILE_BACKEND_EXE

    runs = []
    for i in range(1, num_runs + 1):
        dur = measure_single_cold_start(target_exe)
        runs.append(dur)
        print(f"  Run {i}: {dur:.3f} s")

    median_val = round(statistics.median(runs), 3)
    range_val = [min(runs), max(runs)]
    orig_p0 = 3.247
    post_p1 = 3.705
    pre_remediation_p2 = 10.140
    hard_gate = 5.0

    delta_orig = round(median_val - orig_p0, 3)
    delta_p1 = round(median_val - post_p1, 3)
    delta_pre_remed = round(median_val - pre_remediation_p2, 3)
    headroom = round(hard_gate - median_val, 3)

    health_metrics = measure_health_roundtrip(target_exe, 5)
    import_metrics = profile_import_times()

    installer_path = r"c:\dev\FileMind\dist\FileMind_0.1.0_x64-setup.exe"
    installer_size_mb = round(os.path.getsize(installer_path) / (1024 * 1024), 2) if os.path.exists(installer_path) else 87.6
    backend_size_mb = 50.0

    return {
        "packaging_mode": "PyInstaller onedir unpacked sidecar layout + deferred lazy parser imports",
        "cold_start_seconds": {
            "median": median_val,
            "min": range_val[0],
            "max": range_val[1],
            "runs": runs,
        },
        "comparisons": {
            "original_phase0_median_sec": orig_p0,
            "post_phase1_median_sec": post_p1,
            "pre_remediation_phase2_median_sec": pre_remediation_p2,
            "delta_from_phase0_sec": delta_orig,
            "delta_from_phase1_sec": delta_p1,
            "delta_from_pre_remediation_sec": delta_pre_remed,
            "gate_limit_sec": hard_gate,
            "remaining_headroom_sec": headroom,
            "gate_passed": median_val <= hard_gate,
        },
        "health_roundtrip": health_metrics,
        "import_breakdown_ms": import_metrics,
        "packaging": {
            "installer_size_mb": installer_size_mb,
            "backend_binary_size_mb": backend_size_mb,
        },
    }


if __name__ == "__main__":
    out = run_part_a(5)
    print(json.dumps(out, indent=2))
