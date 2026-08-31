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

TARGET_NAMES = [
    "filemind-backend-x86_64-pc-windows-msvc.exe",
    "filemind-backend-x86_64-pc-windows-gnu.exe",
    "filemind-backend.exe",
]


def build():
    print("=" * 60)
    print("Building FileMind Standalone FastAPI Backend with PyInstaller")
    print("=" * 60)

    os.makedirs(BINARIES_DIR, exist_ok=True)

    pyinstaller_cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--noconfirm",
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

    # Copy onedir into src-tauri/binaries/
    tauri_bin_dir = os.path.join(BINARIES_DIR, "filemind-backend-dir")
    if os.path.exists(tauri_bin_dir):
        shutil.rmtree(tauri_bin_dir)
    shutil.copytree(built_dir, tauri_bin_dir)
    print(f"Synced onedir bundle to: {tauri_bin_dir}")

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
