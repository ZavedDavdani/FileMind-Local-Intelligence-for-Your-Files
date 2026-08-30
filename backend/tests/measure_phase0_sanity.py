"""Current Phase 0 Cold-Start Sanity Check."""

import json
import os
import statistics
import subprocess
import sys
import time
import urllib.request

HEALTH_URL = "http://127.0.0.1:24823/health"
BACKEND_EXE = os.path.abspath(r"c:\dev\FileMind\src-tauri\binaries\filemind-backend.exe")
PYTHON_EXE = os.path.abspath(r"c:\dev\FileMind\backend\.venv\Scripts\python.exe")


def ensure_port_free():
    subprocess.run(["taskkill", "/F", "/IM", "filemind-backend.exe"], capture_output=True)
    time.sleep(0.5)


def measure_single_cold_start() -> float:
    ensure_port_free()
    time.sleep(1.0)

    start_t = time.perf_counter()
    if os.path.exists(BACKEND_EXE):
        proc = subprocess.Popen(
            [BACKEND_EXE],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
    else:
        proc = subprocess.Popen(
            [PYTHON_EXE, "-m", "uvicorn", "app.main:app", "--port", "24823", "--host", "127.0.0.1"],
            cwd=r"c:\dev\FileMind\backend",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    startup_elapsed = None
    try:
        for _ in range(250):
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
        raise TimeoutError("Cold-start sanity check failed: /health not reachable in 5 seconds")

    return startup_elapsed


def run_sanity_check():
    print("=" * 60)
    print("CURRENT BUILD: Phase 0 Cold-Start Sanity Check (3 Runs)")
    print("=" * 60)

    runs = []
    for i in range(1, 4):
        print(f"Executing Cold-Start Run {i}/3...")
        dur = measure_single_cold_start()
        runs.append(dur)
        print(f"  Run {i}: {dur:.3f} s")

    median_val = round(statistics.median(runs), 3)
    range_val = [min(runs), max(runs)]

    print("\n" + "=" * 60)
    print(f"Run 1: {runs[0]} s")
    print(f"Run 2: {runs[1]} s")
    print(f"Run 3: {runs[2]} s")
    print(f"Current Cold-Start Median: {median_val} s (Range: {range_val[0]} s - {range_val[1]} s)")
    print(f"Original Phase 0 Median:  3.247 s")
    diff = round(median_val - 3.247, 3)
    print(f"Delta: {diff:+.3f} s")
    print("=" * 60)

    return {"runs": runs, "median": median_val, "range": range_val, "original_phase0_median": 3.247}


if __name__ == "__main__":
    run_sanity_check()
