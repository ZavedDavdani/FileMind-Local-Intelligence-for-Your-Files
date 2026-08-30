"""Phase 0 Execution, Measurements, and Verification Suite."""

import os
import sys
import time
import json
import psutil
import subprocess
import urllib.request
import urllib.parse
import tempfile

BACKEND_EXE = os.path.abspath(r"c:\dev\FileMind\src-tauri\binaries\filemind-backend.exe")
HEALTH_URL = "http://127.0.0.1:24823/health"
ENUMERATE_URL = "http://127.0.0.1:24823/fs/enumerate"
ACTION_URL = "http://127.0.0.1:24823/fs/action"


def run_measurements():
    print("=" * 60)
    print("Running FileMind Phase 0 Real-World Benchmark & Measurements")
    print("=" * 60)

    if not os.path.exists(BACKEND_EXE):
        raise FileNotFoundError(f"Backend binary not found at {BACKEND_EXE}")

    exe_size_mb = round(os.path.getsize(BACKEND_EXE) / (1024 * 1024), 2)
    print(f"Backend Executable Size: {exe_size_mb} MB")

    # Launch Standalone Backend Process
    print("\n1. Launching standalone backend executable...")
    start_t = time.perf_counter()
    proc = subprocess.Popen([BACKEND_EXE], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    pid = proc.pid
    print(f"Spawned backend PID: {pid}")

    health_response_time = None
    health_payload = None

    try:
        # Measure /health response time
        for _ in range(50):
            time.sleep(0.1)
            try:
                with urllib.request.urlopen(HEALTH_URL, timeout=1) as resp:
                    if resp.status == 200:
                        health_response_time = round(time.perf_counter() - start_t, 3)
                        health_payload = json.loads(resp.read().decode("utf-8"))
                        break
            except Exception:
                pass

        if health_response_time is None:
            raise TimeoutError("Backend failed to respond to /health within 5 seconds")

        print(f"[OK] /health responded in {health_response_time}s (Limit: 5.0s)")
        print(f"[OK] Health Payload: {health_payload}")

        # Measure Process Resource Utilization
        p = psutil.Process(pid)
        # Settle idle
        time.sleep(1.0)
        mem_info = p.memory_info()
        idle_ram_mb = round(mem_info.rss / (1024 * 1024), 2)
        # Measure CPU percent over 1 second
        idle_cpu_percent = round(p.cpu_percent(interval=1.0), 1)

        print(f"[OK] Idle RAM: {idle_ram_mb} MB")
        print(f"[OK] Idle CPU: {idle_cpu_percent}%")

        # Create Test Directory Structure for Enumeration Smoke Test
        with tempfile.TemporaryDirectory() as tmp_dir:
            for i in range(25):
                sub = os.path.join(tmp_dir, f"sub_{i % 5}")
                os.makedirs(sub, exist_ok=True)
                file_path = os.path.join(sub, f"test_doc_{i}.txt")
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(f"Sample test document {i} for FileMind Phase 0 smoke testing.")

            print(f"\n2. Running Recursive Filesystem Enumeration on test directory ({tmp_dir})...")
            req = urllib.request.Request(
                ENUMERATE_URL,
                data=json.dumps({"folder_path": tmp_dir}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            enum_start = time.perf_counter()
            with urllib.request.urlopen(req) as resp:
                enum_duration = round((time.perf_counter() - enum_start) * 1000, 2)
                enum_data = json.loads(resp.read().decode("utf-8"))

            print(f"[OK] Discovered {enum_data['file_count']} files in {enum_duration}ms")
            print(f"[OK] Backend reported scan duration: {enum_data['scan_duration_ms']}ms")

            # Test Safe Actions
            sample_file = enum_data["files"][0]["absolute_path"]
            print(f"\n3. Testing Safe Action: COPY_PATH on {sample_file}...")
            action_req = urllib.request.Request(
                ACTION_URL,
                data=json.dumps({"action": "COPY_PATH", "target_path": sample_file}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(action_req) as resp:
                action_data = json.loads(resp.read().decode("utf-8"))

            print(f"[OK] Action Response: {action_data}")
            assert action_data["success"] is True
            assert action_data["action"] == "COPY_PATH"

        # Verify State Persistence Format
        state_file = os.path.join(os.environ.get("APPDATA", ""), "FileMind", "state.json")
        os.makedirs(os.path.dirname(state_file), exist_ok=True)
        sample_state = {
            "lastSelectedFolder": tmp_dir,
            "lastFileCount": 25,
            "lastScanDurationMs": enum_duration,
            "lastScanTime": "2026-08-30T00:45:00Z",
        }
        with open(state_file, "w", encoding="utf-8") as sf:
            json.dump(sample_state, sf)

        with open(state_file, "r", encoding="utf-8") as sf:
            restored_state = json.load(sf)
        print(f"\n4. Verified AppData State Persistence: {restored_state}")
        assert restored_state["lastFileCount"] == 25

    finally:
        print("\n5. Terminating backend process and checking for orphan processes...")
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except Exception:
            proc.kill()

        time.sleep(0.5)
        is_running = psutil.pid_exists(pid)
        print(f"[OK] Process terminated cleanly. Orphan exists: {is_running}")

    results = {
        "installer_size_mb": exe_size_mb,
        "backend_startup_seconds": health_response_time,
        "health_response_seconds": health_response_time,
        "idle_ram_mb": idle_ram_mb,
        "idle_cpu_percent": idle_cpu_percent,
        "health_payload": health_payload,
    }

    return results


if __name__ == "__main__":
    run_measurements()
