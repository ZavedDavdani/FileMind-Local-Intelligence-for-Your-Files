"""PyInstaller build script to produce standalone backend binaries for Tauri."""

import os
import sys
import shutil
import subprocess
import time
import urllib.request
import json

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.abspath(os.path.join(ROOT_DIR, ".."))
BINARIES_DIR = os.path.join(PROJECT_DIR, "src-tauri", "binaries")
DIST_DIR = os.path.join(ROOT_DIR, "dist")
BUILD_DIR = os.path.join(ROOT_DIR, "build")
RUNNER_SCRIPT = os.path.join(ROOT_DIR, "run_server.py")
LOCK_FILE = os.path.join(ROOT_DIR, "requirements-lock.txt")

TARGET_NAMES = [
    "filemind-backend-x86_64-pc-windows-msvc.exe",
    "filemind-backend-x86_64-pc-windows-gnu.exe",
    "filemind-backend.exe",
]


def _parse_pinned_versions(lock_path: str) -> dict:
    """Parses a `name==version` pinned requirements file into a dict."""
    pinned = {}
    if not os.path.exists(lock_path):
        return pinned
    with open(lock_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "==" not in line:
                continue
            name, _, version = line.partition("==")
            pinned[name.strip().lower()] = version.strip()
    return pinned


def verify_lockfile_parity():
    """Warns (does not fail the build) if the active environment's installed
    package versions drift from requirements-lock.txt.

    requirements-lock.txt exists specifically so that a rebuild months from
    now reproduces the same dependency versions used to generate the frozen
    Phase 4 evaluation/benchmark numbers (docs/phase-4/benchmark_results.json).
    Previously this file was generated but never consulted by anything —
    this check is what actually gives it teeth: a visible warning at build
    time if the environment has drifted, instead of silent divergence.
    """
    pinned = _parse_pinned_versions(LOCK_FILE)
    if not pinned:
        print(f"[Lockfile Check] WARNING: {LOCK_FILE} not found or empty; skipping parity check.")
        return

    try:
        from importlib import metadata as importlib_metadata
    except ImportError:  # pragma: no cover - py<3.8 fallback, unsupported anyway
        print("[Lockfile Check] WARNING: importlib.metadata unavailable; skipping parity check.")
        return

    mismatches = []
    missing = []
    for name, expected_version in pinned.items():
        try:
            installed_version = importlib_metadata.version(name)
        except importlib_metadata.PackageNotFoundError:
            missing.append(name)
            continue
        if installed_version != expected_version:
            mismatches.append((name, expected_version, installed_version))

    if not mismatches and not missing:
        print(f"[Lockfile Check] OK: environment matches requirements-lock.txt ({len(pinned)} packages checked).")
        return

    print("[Lockfile Check] WARNING: build environment differs from requirements-lock.txt.")
    print("  This can silently change parser/embedding/reranker behavior and invalidate")
    print("  previously recorded Phase 4 benchmark numbers. Re-run benchmarks after any")
    print("  intentional dependency upgrade, or reinstall from requirements-lock.txt to")
    print("  reproduce the exact frozen environment.")
    for name in missing:
        print(f"    - {name}: pinned in lockfile but NOT INSTALLED in this environment")
    for name, expected_version, installed_version in mismatches:
        print(f"    - {name}: lockfile={expected_version} installed={installed_version}")


def build():
    print("=" * 60)
    print("Building FileMind Standalone FastAPI Backend with PyInstaller")
    print("=" * 60)

    verify_lockfile_parity()

    os.makedirs(BINARIES_DIR, exist_ok=True)

    pyinstaller_cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--noconfirm",
        "--noconsole",
        "--onedir",
        "--name", "filemind-backend-dir",

        "--hidden-import", "uvicorn.logging",
        "--hidden-import", "uvicorn.loops",
        "--hidden-import", "uvicorn.loops.auto",
        "--hidden-import", "uvicorn.protocols",
        "--hidden-import", "uvicorn.protocols.http",
        "--hidden-import", "uvicorn.protocols.http.auto",
        "--hidden-import", "uvicorn.protocols.http.h11_impl",
        "--hidden-import", "uvicorn.protocols.http.httptools_impl",
        "--hidden-import", "uvicorn.protocols.websockets",
        "--hidden-import", "uvicorn.protocols.websockets.auto",
        "--hidden-import", "uvicorn.lifespans",
        "--hidden-import", "uvicorn.lifespans.on",
        "--hidden-import", "uvicorn.lifespans.off",
        "--collect-all", "fastapi",
        "--collect-all", "uvicorn",
        "--collect-all", "pydantic",
        "--collect-all", "pymupdf",
        "--collect-all", "fitz",
        "--collect-all", "docx",
        "--collect-all", "pptx",
        "--collect-all", "openpyxl",
        "--collect-all", "fastembed",
        "--collect-all", "sqlite_vec",
        "--distpath", DIST_DIR,
        "--workpath", BUILD_DIR,
        "--specpath", ROOT_DIR,
        RUNNER_SCRIPT,
    ]

    print(f"Executing: {' '.join(pyinstaller_cmd)}")
    subprocess.check_call(pyinstaller_cmd)

    built_dir = os.path.join(DIST_DIR, "filemind-backend-dir")
    built_exe = os.path.join(built_dir, "filemind-backend-dir.exe")
    if not os.path.exists(built_exe):
        raise RuntimeError(f"Build failed: {built_exe} not found")

    # Ensure alias executable filemind-backend.exe exists in onedir
    shutil.copyfile(built_exe, os.path.join(built_dir, "filemind-backend.exe"))

    # Copy onedir into src-tauri/binaries/filemind-backend-dir/
    tauri_bin_dir = os.path.join(BINARIES_DIR, "filemind-backend-dir")
    if os.path.exists(tauri_bin_dir):
        shutil.rmtree(tauri_bin_dir)
    shutil.copytree(built_dir, tauri_bin_dir)
    print(f"Synced onedir bundle to: {tauri_bin_dir}")

    # Verify ONEDIR bundle integrity
    tauri_exe = os.path.join(tauri_bin_dir, "filemind-backend-dir.exe")
    if not os.path.exists(tauri_exe):
        raise RuntimeError(f"PyInstaller bundle is incomplete: {tauri_exe} not found")
    print(f"Verified ONEDIR executable: {tauri_exe}")

    internal_python = os.path.join(tauri_bin_dir, "_internal", "python311.dll")
    if not os.path.exists(internal_python):
        raise RuntimeError(f"PyInstaller bundle is incomplete: {internal_python} not found")
    print(f"Verified ONEDIR Python runtime: {internal_python}")

    # Copy top-level alias executables for Tauri lookup
    for name in TARGET_NAMES:
        dest = os.path.join(BINARIES_DIR, name)
        shutil.copyfile(built_exe, dest)
        print(f"Copied binary stub to: {dest}")

    # Self-test the onedir executable
    print("\nVerifying onedir executable execution & /health check...")
    proc = subprocess.Popen([built_exe], cwd=built_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    healthy = False
    start_t = time.perf_counter()
    health_latency = None

    try:
        for _ in range(50):  # Poll up to 5 seconds
            time.sleep(0.1)
            try:
                with urllib.request.urlopen("http://127.0.0.1:24823/health", timeout=1) as resp:
                    if resp.status == 200:
                        data = json.loads(resp.read().decode("utf-8"))
                        if data.get("status") == "healthy" and data.get("port") == 24823:
                            health_latency = round((time.perf_counter() - start_t) * 1000, 2)
                            healthy = True
                            print(f"VERIFIED: Standalone backend is healthy! Latency: {health_latency}ms")
                            print(f"Health Response: {data}")
                            break
            except Exception:
                pass
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except Exception:
            proc.kill()

    if not healthy:
        raise RuntimeError("Standalone backend self-test FAILED to respond to /health within 5 seconds")

    print("\nBackend Packaging SUCCESS!")


if __name__ == "__main__":
    build()
