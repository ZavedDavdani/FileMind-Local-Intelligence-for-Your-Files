// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod job_object;

use job_object::JobObjectGuard;
use std::fs;
use std::io::{Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command};
use std::sync::{Arc, Mutex};
use std::time::Duration;
use tauri::{AppHandle, Manager, RunEvent, WindowEvent};

const BACKEND_PORT: u16 = 24823;

struct BackendState {
    child_process: Option<Child>,
    job_guard: Option<JobObjectGuard>,
    is_healthy: bool,
}

type ManagedBackend = Arc<Mutex<BackendState>>;

fn is_backend_healthy() -> bool {
    let addr = SocketAddr::from(([127, 0, 0, 1], BACKEND_PORT));
    if let Ok(mut stream) = TcpStream::connect_timeout(&addr, Duration::from_millis(300)) {
        let _ = stream.set_read_timeout(Some(Duration::from_millis(400)));
        let _ = stream.set_write_timeout(Some(Duration::from_millis(400)));
        let request = format!(
            "GET /health HTTP/1.1\r\nHost: 127.0.0.1:{}\r\nConnection: close\r\n\r\n",
            BACKEND_PORT
        );
        if stream.write_all(request.as_bytes()).is_ok() {
            let mut buf = [0u8; 512];
            if let Ok(n) = stream.read(&mut buf) {
                let resp = String::from_utf8_lossy(&buf[..n]);
                if resp.contains("200 OK") || resp.contains("\"status\":\"healthy\"") || resp.contains("\"status\": \"healthy\"") {
                    return true;
                }
            }
        }
    }
    false
}

fn locate_backend_executable(app_handle: &AppHandle) -> Option<PathBuf> {
    // 1. Check next to the current executable (packaged distribution directory)
    if let Ok(curr_exe) = std::env::current_exe() {
        if let Some(parent) = curr_exe.parent() {
            let candidates = [
                parent.join("binaries").join("filemind-backend-dir.exe"),
                parent.join("binaries").join("filemind-backend.exe"),
                parent.join("filemind-backend.exe"),
                parent.join("resources").join("filemind-backend.exe"),
                parent.join("binaries").join("filemind-backend-x86_64-pc-windows-gnu.exe"),
                parent.join("binaries").join("filemind-backend-x86_64-pc-windows-msvc.exe"),
            ];
            for cand in &candidates {
                if cand.exists() {
                    return Some(cand.clone());
                }
            }
        }
    }

    // 2. Check Tauri resource resolver
    if let Ok(resource_dir) = app_handle.path().resource_dir() {
        let candidates = [
            resource_dir.join("filemind-backend.exe"),
            resource_dir.join("binaries").join("filemind-backend.exe"),
            resource_dir.join("binaries").join("filemind-backend-x86_64-pc-windows-gnu.exe"),
            resource_dir.join("binaries").join("filemind-backend-x86_64-pc-windows-msvc.exe"),
        ];
        for cand in &candidates {
            if cand.exists() {
                return Some(cand.clone());
            }
        }
    }

    // 3. Check development source directories
    let dev_paths = [
        PathBuf::from("src-tauri/binaries/filemind-backend-x86_64-pc-windows-gnu.exe"),
        PathBuf::from("src-tauri/binaries/filemind-backend-x86_64-pc-windows-msvc.exe"),
        PathBuf::from("src-tauri/binaries/filemind-backend.exe"),
        PathBuf::from("../src-tauri/binaries/filemind-backend.exe"),
        PathBuf::from("backend/dist/filemind-backend.exe"),
        PathBuf::from("../backend/dist/filemind-backend.exe"),
    ];
    for p in &dev_paths {
        if p.exists() {
            return Some(p.clone());
        }
    }

    None
}

fn locate_dev_backend() -> Option<(PathBuf, PathBuf)> {
    let python_candidates = [
        PathBuf::from("backend/.venv/Scripts/python.exe"),
        PathBuf::from("../backend/.venv/Scripts/python.exe"),
        PathBuf::from(".venv/Scripts/python.exe"),
        PathBuf::from("../.venv/Scripts/python.exe"),
        PathBuf::from("backend/.venv/bin/python"),
        PathBuf::from("../backend/.venv/bin/python"),
        PathBuf::from(".venv/bin/python"),
        PathBuf::from("../.venv/bin/python"),
    ];

    let runner_candidates = [
        PathBuf::from("backend/run_server.py"),
        PathBuf::from("../backend/run_server.py"),
    ];

    let selected_python = python_candidates.iter().find(|p| p.exists())?.clone();
    let selected_runner = runner_candidates.iter().find(|p| p.exists())?.clone();

    Some((selected_python, selected_runner))
}

fn log_dev_backend_failure() {
    let cwd = std::env::current_dir()
        .map(|p| p.to_string_lossy().to_string())
        .unwrap_or_else(|_| "UNKNOWN".to_string());
    eprintln!("[Tauri Supervisor] CRITICAL: Backend executable not found.");
    eprintln!("[Tauri Supervisor] Diagnostic Telemetry:");
    eprintln!("  Current Working Directory: {}", cwd);
    eprintln!("  Checked Python Candidates:");
    let python_candidates = [
        "backend/.venv/Scripts/python.exe",
        "../backend/.venv/Scripts/python.exe",
        ".venv/Scripts/python.exe",
        "../.venv/Scripts/python.exe",
        "backend/.venv/bin/python",
        "../backend/.venv/bin/python",
        ".venv/bin/python",
        "../.venv/bin/python",
    ];
    for py in &python_candidates {
        let exists = Path::new(py).exists();
        eprintln!("    - {} (exists: {})", py, exists);
    }
    eprintln!("  Checked Runner Candidates:");
    let runner_candidates = [
        "backend/run_server.py",
        "../backend/run_server.py",
    ];
    for runner in &runner_candidates {
        let exists = Path::new(runner).exists();
        eprintln!("    - {} (exists: {})", runner, exists);
    }
    eprintln!("  Failure Reason: No viable Python environment or runner script found in search paths.");
}

fn spawn_backend(app_handle: &AppHandle, backend_state: ManagedBackend) {
    if is_backend_healthy() {
        println!("[Tauri Supervisor] Local backend is already online on port {}", BACKEND_PORT);
        let mut state = backend_state.lock().unwrap();
        state.is_healthy = true;
        return;
    }

    // Initialize Windows Job Object with KILL_ON_JOB_CLOSE before spawning child
    let job_guard = match JobObjectGuard::create_with_kill_on_close() {
        Ok(guard) => Some(guard),
        Err(err) => {
            eprintln!("[Tauri Supervisor] CRITICAL: Failed to create Windows Job Object: {}", err);
            None
        }
    };

    // In development mode, prefer live dev Python backend
    #[cfg(debug_assertions)]
    if let Some((venv_python, run_script)) = locate_dev_backend() {
        let abs_python = venv_python.canonicalize().unwrap_or(venv_python.clone());
        let abs_runner = run_script.canonicalize().unwrap_or(run_script.clone());
        let backend_dir = abs_runner.parent().unwrap_or(Path::new("."));

        println!(
            "[Tauri Supervisor] Spawning backend via dev venv: {:?} with runner: {:?}",
            abs_python, abs_runner
        );

        #[cfg(target_os = "windows")]
        use std::os::windows::process::CommandExt;

        let mut cmd = Command::new(&abs_python);
        cmd.arg(&abs_runner);
        cmd.current_dir(backend_dir);

        #[cfg(target_os = "windows")]
        {
            const CREATE_NO_WINDOW: u32 = 0x08000000;
            cmd.creation_flags(CREATE_NO_WINDOW);
        }

        match cmd.spawn() {
            Ok(child) => {
                let pid = child.id();
                println!("[Tauri Supervisor] Backend spawned via dev venv with PID {}", pid);

                if let Some(ref guard) = job_guard {
                    if let Err(err) = guard.assign_child(&child) {
                        eprintln!(
                            "[Tauri Supervisor] WARNING: Failed to assign backend PID {} to Job Object: {}",
                            pid, err
                        );
                    }
                }

                let mut state = backend_state.lock().unwrap();
                state.child_process = Some(child);
                state.job_guard = job_guard;
                return;
            }
            Err(err) => {
                eprintln!("[Tauri Supervisor] Failed to spawn backend via dev venv: {}", err);
            }
        }
    }

    // Production / packaged binary location
    if let Some(exe_path) = locate_backend_executable(app_handle) {
        println!("[Tauri Supervisor] Spawning backend binary: {:?}", exe_path);

        #[cfg(target_os = "windows")]
        use std::os::windows::process::CommandExt;
        
        let mut cmd = Command::new(&exe_path);
        #[cfg(target_os = "windows")]
        {
            const CREATE_NO_WINDOW: u32 = 0x08000000;
            cmd.creation_flags(CREATE_NO_WINDOW);
        }

        match cmd.spawn() {
            Ok(child) => {
                let pid = child.id();
                println!("[Tauri Supervisor] Backend spawned successfully with PID {}", pid);

                // Assign the exact spawned backend process to the Job Object
                if let Some(ref guard) = job_guard {
                    if let Err(err) = guard.assign_child(&child) {
                        eprintln!("[Tauri Supervisor] WARNING: Failed to assign backend PID {} to Job Object: {}", pid, err);
                    }
                }

                let mut state = backend_state.lock().unwrap();
                state.child_process = Some(child);
                state.job_guard = job_guard;
            }
            Err(err) => {
                eprintln!("[Tauri Supervisor] Failed to spawn backend binary: {}", err);
            }
        }
    } else {
        // Fallback: try locate_dev_backend if in release mode or if packaged binary not found
        if let Some((venv_python, run_script)) = locate_dev_backend() {
            let abs_python = venv_python.canonicalize().unwrap_or(venv_python.clone());
            let abs_runner = run_script.canonicalize().unwrap_or(run_script.clone());
            let backend_dir = abs_runner.parent().unwrap_or(Path::new("."));

            println!(
                "[Tauri Supervisor] Spawning fallback backend via dev venv: {:?} with runner: {:?}",
                abs_python, abs_runner
            );

            #[cfg(target_os = "windows")]
            use std::os::windows::process::CommandExt;

            let mut cmd = Command::new(&abs_python);
            cmd.arg(&abs_runner);
            cmd.current_dir(backend_dir);

            #[cfg(target_os = "windows")]
            {
                const CREATE_NO_WINDOW: u32 = 0x08000000;
                cmd.creation_flags(CREATE_NO_WINDOW);
            }

            match cmd.spawn() {
                Ok(child) => {
                    let pid = child.id();
                    println!("[Tauri Supervisor] Backend spawned via dev venv with PID {}", pid);

                    if let Some(ref guard) = job_guard {
                        if let Err(err) = guard.assign_child(&child) {
                            eprintln!("[Tauri Supervisor] WARNING: Failed to assign backend PID {} to Job Object: {}", pid, err);
                        }
                    }

                    let mut state = backend_state.lock().unwrap();
                    state.child_process = Some(child);
                    state.job_guard = job_guard;
                }
                Err(err) => {
                    eprintln!("[Tauri Supervisor] Failed to spawn backend via dev venv: {}", err);
                }
            }
        } else {
            log_dev_backend_failure();
        }
    }

}


fn terminate_backend(backend_state: &ManagedBackend) {
    let mut state = backend_state.lock().unwrap();
    if let Some(mut child) = state.child_process.take() {
        println!("[Tauri Supervisor] Terminating backend process PID {}", child.id());
        let _ = child.kill();
        let _ = child.wait();
    }
    // Drop Job Object guard to release Windows handle on graceful shutdown
    if let Some(guard) = state.job_guard.take() {
        drop(guard);
    }
}

fn get_appdata_state_file() -> Option<PathBuf> {
    if let Some(app_data) = dirs::data_dir() {
        let dir = app_data.join("FileMind");
        let _ = fs::create_dir_all(&dir);
        return Some(dir.join("state.json"));
    }
    None
}

#[tauri::command]
fn save_app_state(state_json: String) -> Result<bool, String> {
    if let Some(path) = get_appdata_state_file() {
        fs::write(path, state_json).map_err(|e| e.to_string())?;
        return Ok(true);
    }
    Err("Could not locate AppData directory".to_string())
}

#[tauri::command]
fn load_app_state() -> Result<String, String> {
    if let Some(path) = get_appdata_state_file() {
        if path.exists() {
            let content = fs::read_to_string(path).map_err(|e| e.to_string())?;
            return Ok(content);
        }
    }
    Ok("{}".to_string())
}

#[tauri::command]
fn open_in_explorer(path: String) -> Result<(), String> {
    let p = Path::new(&path);
    if !p.exists() {
        return Err("Path does not exist".to_string());
    }

    #[cfg(target_os = "windows")]
    {
        if p.is_file() {
            let _ = Command::new("explorer.exe")
                .arg(format!("/select,{}", path))
                .spawn();
        } else {
            let _ = Command::new("explorer.exe").arg(&path).spawn();
        }
    }

    #[cfg(not(target_os = "windows"))]
    {
        let target = if p.is_file() {
            p.parent().unwrap_or(p).to_string_lossy().to_string()
        } else {
            path
        };
        let _ = Command::new("xdg-open").arg(target).spawn();
    }

    Ok(())
}

fn main() {
    let backend_state = Arc::new(Mutex::new(BackendState {
        child_process: None,
        job_guard: None,
        is_healthy: false,
    }));

    let supervisor_state = backend_state.clone();
    let cleanup_state = backend_state.clone();

    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![
            save_app_state,
            load_app_state,
            open_in_explorer
        ])
        .setup(move |app| {
            let handle = app.handle().clone();
            let bg_state = supervisor_state.clone();
            
            // Spawn bundled backend automatically on startup
            std::thread::spawn(move || {
                spawn_backend(&handle, bg_state);
            });

            Ok(())
        })
        .on_window_event(move |_window, event| {
            if let WindowEvent::CloseRequested { .. } = event {
                terminate_backend(&cleanup_state);
            }
        })
        .build(tauri::generate_context!())
        .expect("error while running tauri application")
        .run(move |_app_handle, event| {
            if let RunEvent::Exit = event {
                terminate_backend(&backend_state);
            }
        });
}
