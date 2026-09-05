import os
import sys
import subprocess
from pathlib import Path

def build_backend_sidecar():
    project_root = Path(__file__).resolve().parent.parent
    backend_dir = project_root / 'backend'
    output_target_dir = project_root / 'src-tauri' / 'binaries' / 'filemind-backend-dir'
    print('=== FileMind Backend Sidecar Build ===')
    output_target_dir.parent.mkdir(parents=True, exist_ok=True)
    pyinstaller_args = [
        sys.executable, '-m', 'PyInstaller',
        '--noconfirm', '--onedir', '--windowed',
        '--name', 'filemind-backend-dir',
        '--distpath', str(project_root / 'src-tauri' / 'binaries'),
        '--workpath', str(backend_dir / 'build'),
        '--specpath', str(backend_dir),
        '--hidden-import', 'sqlite_vec',
        '--hidden-import', 'uvicorn',
        '--hidden-import', 'uvicorn.logging',
        '--hidden-import', 'uvicorn.loops',
        '--hidden-import', 'uvicorn.loops.auto',
        '--hidden-import', 'uvicorn.protocols',
        '--hidden-import', 'uvicorn.protocols.http',
        '--hidden-import', 'uvicorn.protocols.http.auto',
        '--hidden-import', 'uvicorn.lifespans',
        '--hidden-import', 'uvicorn.lifespans.on',
        '--hidden-import', 'app.main',
        str(backend_dir / 'run_server.py')
    ]
    try:
        subprocess.run(pyinstaller_args, check=True, cwd=str(backend_dir))
        print('PyInstaller build completed successfully.')
    except Exception as e:
        print(f'PyInstaller step note: {e}')

if __name__ == '__main__':
    build_backend_sidecar()
