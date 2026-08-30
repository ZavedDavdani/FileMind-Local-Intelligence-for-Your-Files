"""Rigorous Phase 0 Timing and Resource Measurement Suite.

Performs independent multi-run measurements for:
1. Cold Start -> /health OK (Process spawn to HTTP 200 on cold launch)
2. Warm Start -> /health OK (Process spawn to HTTP 200 on warm cache)
3. /health Round-Trip Only (HTTP latency on already running process)
4. Idle RAM and Idle CPU (sampled over 30 seconds)
5. Filesystem scan latency
"""

import os
import sys
import time
import json
import psutil
import subprocess
import urllib.request
import tempfile
import statistics

BACKEND_EXE = os.path.abspath(r"c:\dev\FileMind\src-tauri\binaries\filemind-backend.exe")
INSTALLER_EXE = os.path.abspath(r"c:\dev\FileMind\dist\FileMind_0.1.0_x64-setup.exe")
HEALTH_URL = "http://127.0.0.1:24823/health"
ENUMERATE_URL = "http://127.0.0.1:24823/fs/enumerate"
ACTION_URL = "http://127.0.0.1:24823/fs/action"


def ensure_port_free():
    """Kills any running filemind-backend instances and ensures port 24823 is free."""
    subprocess.run(["taskkill", "/F", "/IM", "filemind-backend.exe"], capture_output=True)
    time.sleep(0.5)
    for _ in range(20):
        try:
            with urllib.request.urlopen(HEALTH_URL, timeout=0.2) as resp:
                time.sleep(0.2)
        except Exception:
            return True
    return False


def measure_startup_once():
    """Ensures clean slate, spawns backend process, and measures time to first HTTP 200."""
    ensure_port_free()
    time.sleep(0.3)

    start_t = time.perf_counter()
    proc = subprocess.Popen(
        [BACKEND_EXE],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    pid = proc.pid
    startup_elapsed = None
    payload = None

    try:
        # Poll /health every 20ms
        for _ in range(250):
            time.sleep(0.02)
            try:
                with urllib.request.urlopen(HEALTH_URL, timeout=0.2) as resp:
                    if resp.status == 200:
                        startup_elapsed = round(time.perf_counter() - start_t, 3)
                        payload = json.loads(resp.read().decode("utf-8"))
                        break
            except Exception:
                pass
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except Exception:
            proc.kill()
        ensure_port_free()

    if startup_elapsed is None:
        raise TimeoutError("Backend failed to respond to /health within 5 seconds")

    return startup_elapsed, payload


def measure_health_roundtrip_warm(count=5):
    """Measures pure HTTP round-trip latency on an already running, warm backend instance."""
    ensure_port_free()
    time.sleep(0.2)

    proc = subprocess.Popen(
        [BACKEND_EXE],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    pid = proc.pid

    # Wait for backend readiness
    ready = False
    for _ in range(100):
        time.sleep(0.05)
        try:
            with urllib.request.urlopen(HEALTH_URL, timeout=0.2) as resp:
                if resp.status == 200:
                    ready = True
                    break
        except Exception:
            pass

    if not ready:
        try:
            proc.kill()
        except Exception:
            pass
        raise RuntimeError("Backend failed to start for roundtrip testing")

    # Warmup request
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=1.0) as resp:
            resp.read()
    except Exception:
        pass

    latencies = []
    for _ in range(count):
        time.sleep(0.1)
        t0 = time.perf_counter()
        with urllib.request.urlopen(HEALTH_URL, timeout=1.0) as resp:
            data = resp.read()
            assert resp.status == 200
        t1 = time.perf_counter()
        elapsed_sec = round(t1 - t0, 5)
        latencies.append(elapsed_sec)

    # Measure Resource Utilization on this running process
    p = psutil.Process(pid)
    time.sleep(0.5)
    idle_ram_mb = round(p.memory_info().rss / (1024 * 1024), 2)

    # Sample CPU over 30 seconds (sample every 1s across 30 iterations)
    print("  Sampling Idle CPU over 30.0-second window...")
    cpu_samples = []
    p.cpu_percent(interval=None)  # initialize
    for i in range(30):
        time.sleep(1.0)
        cpu_samples.append(p.cpu_percent(interval=None))
    idle_cpu_percent = round(statistics.mean(cpu_samples), 2)

    # Measure Filesystem Scan Latency
    with tempfile.TemporaryDirectory() as tmp_dir:
        test_file_count = 50
        for i in range(test_file_count):
            sub = os.path.join(tmp_dir, f"folder_{i % 5}")
            os.makedirs(sub, exist_ok=True)
            file_path = os.path.join(sub, f"document_{i}.txt")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(f"Sample test document {i} for Phase 0 scan latency benchmarking.")

        req = urllib.request.Request(
            ENUMERATE_URL,
            data=json.dumps({"folder_path": tmp_dir}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        scan_t0 = time.perf_counter()
        with urllib.request.urlopen(req) as resp:
            scan_data = json.loads(resp.read().decode("utf-8"))
        scan_t1 = time.perf_counter()

        total_scan_latency_ms = round((scan_t1 - scan_t0) * 1000, 2)
        backend_internal_scan_ms = scan_data.get("scan_duration_ms")
        discovered_count = scan_data.get("file_count")

    # Cleanup
    try:
        proc.terminate()
        proc.wait(timeout=2)
    except Exception:
        proc.kill()
    ensure_port_free()

    return {
        "latencies": latencies,
        "idle_ram_mb": idle_ram_mb,
        "idle_cpu_percent": idle_cpu_percent,
        "scan_latency_ms": total_scan_latency_ms,
        "scan_file_count": discovered_count,
        "backend_internal_scan_ms": backend_internal_scan_ms,
    }


def run_comprehensive_audit():
    print("=" * 70)
    print("FILEMIND PHASE 0 RIGOROUS BENCHMARK & AUDIT SUITE")
    print("=" * 70)

    if not os.path.exists(BACKEND_EXE):
        raise FileNotFoundError(f"Backend binary not found at {BACKEND_EXE}")

    backend_size_mb = round(os.path.getsize(BACKEND_EXE) / (1024 * 1024), 2)
    installer_size_mb = (
        round(os.path.getsize(INSTALLER_EXE) / (1024 * 1024), 2)
        if os.path.exists(INSTALLER_EXE)
        else None
    )

    print(f"Backend Binary Size: {backend_size_mb} MB")
    print(f"Installer Size: {installer_size_mb} MB")

    # 1. Measure Cold Start (5 runs, first launch after cold wait)
    print("\n--- 1. Measuring Cold Start -> /health OK (5 runs) ---")
    cold_runs = []
    for run_idx in range(5):
        time.sleep(2.0)  # Inter-run cool down
        dur, payload = measure_startup_once()
        cold_runs.append(dur)
        print(f"  Cold Run {run_idx + 1}: {dur:.3f} s")

    cold_median = round(statistics.median(cold_runs), 3)
    cold_min = min(cold_runs)
    cold_max = max(cold_runs)
    cold_range = f"{cold_min:.3f} s - {cold_max:.3f} s"
    print(f"  -> Cold Median: {cold_median} s | Range: {cold_range}")

    # 2. Measure Warm Start (5 runs, sequential launches on warm OS cache)
    print("\n--- 2. Measuring Warm Start -> /health OK (5 runs) ---")
    warm_runs = []
    for run_idx in range(5):
        time.sleep(0.3)  # Immediate relaunch
        dur, _ = measure_startup_once()
        warm_runs.append(dur)
        print(f"  Warm Run {run_idx + 1}: {dur:.3f} s")

    warm_median = round(statistics.median(warm_runs), 3)
    warm_min = min(warm_runs)
    warm_max = max(warm_runs)
    warm_range = f"{warm_min:.3f} s - {warm_max:.3f} s"
    print(f"  -> Warm Median: {warm_median} s | Range: {warm_range}")

    # 3. Measure /health Round-Trip Only & Resources on Warm Process
    print("\n--- 3. Measuring /health Round-Trip Latency & Resources (5 runs) ---")
    metrics = measure_health_roundtrip_warm(count=5)
    rt_runs = metrics["latencies"]
    for idx, val in enumerate(rt_runs):
        print(f"  Roundtrip Run {idx + 1}: {val * 1000:.2f} ms ({val:.5f} s)")

    rt_median = round(statistics.median(rt_runs), 5)
    rt_min = min(rt_runs)
    rt_max = max(rt_runs)
    rt_range = f"{rt_min * 1000:.2f} ms - {rt_max * 1000:.2f} ms ({rt_min:.5f} s - {rt_max:.5f} s)"
    print(f"  -> Roundtrip Median: {rt_median * 1000:.2f} ms ({rt_median:.5f} s) | Range: {rt_range}")

    print("\n--- 4. Resource Utilization ---")
    print(f"  Idle RAM: {metrics['idle_ram_mb']} MB (Target: < 100 MB)")
    print(f"  Idle CPU (30s sample): {metrics['idle_cpu_percent']}% (Target: < 2.0%)")

    print("\n--- 5. Filesystem Scan Latency ---")
    print(f"  Files: {metrics['scan_file_count']} | Scan Round-trip Latency: {metrics['scan_latency_ms']} ms (Target: < 1000 ms)")

    results = {
        "cold_runs": cold_runs,
        "cold_median": cold_median,
        "cold_range": cold_range,
        "warm_runs": warm_runs,
        "warm_median": warm_median,
        "warm_range": warm_range,
        "rt_runs": rt_runs,
        "rt_median": rt_median,
        "rt_range": rt_range,
        "idle_ram_mb": metrics["idle_ram_mb"],
        "idle_cpu_percent": metrics["idle_cpu_percent"],
        "scan_latency_ms": metrics["scan_latency_ms"],
        "scan_file_count": metrics["scan_file_count"],
        "backend_size_mb": backend_size_mb,
        "installer_size_mb": installer_size_mb,
    }

    with open("docs/phase-0/audit_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print("\n[OK] Comprehensive Audit Measurements Complete!")
    return results


if __name__ == "__main__":
    run_comprehensive_audit()
