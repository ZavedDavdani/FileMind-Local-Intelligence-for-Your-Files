// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod job_object;

use job_object::JobObjectGuard;
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
    intentional_shutdown: bool,
}

type ManagedBackend = Arc<Mutex<BackendState>>;

fn is_backend_healthy() -> bool {
    let addr = SocketAddr::from(([127, 0, 0, 1], BACKEND_PORT));
    let mut stream = match TcpStream::connect_timeout(&addr, Duration::from_millis(300)) {
        Ok(s) => s,
        Err(_) => return false,
    };
    let _ = stream.set_read_timeout(Some(Duration::from_millis(600)));
    let _ = stream.set_write_timeout(Some(Duration::from_millis(400)));

    let request = format!(
        "GET /health HTTP/1.1\r\nHost: 127.0.0.1:{}\r\nConnection: close\r\n\r\n",
        BACKEND_PORT
    );
    if stream.write_all(request.as_bytes()).is_err() {
        return false;
    }

    let mut buf = Vec::new();
    let _ = stream.read_to_end(&mut buf);
    if buf.is_empty() {
        return false;
    }

    let resp = match std::str::from_utf8(&buf) {
        Ok(s) => s,
        Err(_) => return false,
    };

    let status_line = resp.lines().next().unwrap_or("");
    if !status_line.contains("200") {
        return false;
    }

    let body = if let Some(idx) = resp.find("\r\n\r\n") {
        &resp[idx + 4..]
    } else if let Some(idx) = resp.find("\n\n") {
        &resp[idx + 2..]
    } else {
        return false;
    };

    if let Ok(val) = serde_json::from_str::<serde_json::Value>(body.trim()) {
        let is_healthy = val.get("status").and_then(|s| s.as_str()) == Some("healthy");
        let is_filemind = val.get("service").and_then(|s| s.as_str()) == Some("FileMind Backend");
        return is_healthy && is_filemind;
    }
    false
}


fn describe_backend_bundle(exe_path: &Path) {
    println!(
        "[Tauri Supervisor] Selected backend: {:?}",
        exe_path
    );

    if let Some(parent) = exe_path.parent() {
        println!(
            "[Tauri Supervisor] Backend directory: {:?}",
            parent
        );

        println!(
            "[Tauri Supervisor] Executable exists: {}",
            exe_path.exists()
        );

        println!(
            "[Tauri Supervisor] _internal exists: {}",
            parent.join("_internal").exists()
        );

        println!(
            "[Tauri Supervisor] python311.dll exists: {}",
            parent.join("_internal").join("python311.dll").exists()
        );
    }
}

fn locate_backend_executable(app_handle: &AppHandle) -> Option<PathBuf> {
    // 1. Check next to the current executable (packaged distribution directory)
    if let Ok(curr_exe) = std::env::current_exe() {
        if let Some(parent) = curr_exe.parent() {
            // Primary ONEDIR candidate: binaries/filemind-backend-dir/filemind-backend-dir.exe
            // This is the correct PyInstaller onedir layout where _internal/ is adjacent to the exe.
            let candidates = [
                parent
                    .join("binaries")
                    .join("filemind-backend-dir")
                    .join("filemind-backend-dir.exe"),
                parent.join("binaries").join("filemind-backend.exe"),
                parent.join("filemind-backend.exe"),
                parent.join("resources").join("filemind-backend.exe"),
                parent
                    .join("binaries")
                    .join("filemind-backend-x86_64-pc-windows-gnu.exe"),
                parent
                    .join("binaries")
                    .join("filemind-backend-x86_64-pc-windows-msvc.exe"),
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
            resource_dir
                .join("binaries")
                .join("filemind-backend-dir")
                .join("filemind-backend-dir.exe"),
            resource_dir.join("filemind-backend.exe"),
            resource_dir.join("binaries").join("filemind-backend.exe"),
            resource_dir
                .join("binaries")
                .join("filemind-backend-x86_64-pc-windows-gnu.exe"),
            resource_dir
                .join("binaries")
                .join("filemind-backend-x86_64-pc-windows-msvc.exe"),
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

fn handle_spawned_child(
    mut child: Child,
    job_guard: Option<JobObjectGuard>,
    backend_state: &ManagedBackend,
) -> bool {
    let pid = child.id();
    #[cfg(target_os = "windows")]
    {
        if let Some(ref guard) = job_guard {
            if let Err(err) = guard.assign_child(&child) {
                eprintln!(
                    "[Tauri Supervisor] CRITICAL: Failed to assign backend PID {} to Job Object: {}. Terminating unmanaged child.",
                    pid, err
                );
                let _ = child.kill();
                return false;
            }
        } else {
            eprintln!(
                "[Tauri Supervisor] CRITICAL: No Job Object available on Windows for backend PID {}. Terminating unmanaged child.",
                pid
            );
            let _ = child.kill();
            return false;
        }
    }

    let mut state = backend_state.lock().unwrap();
    state.child_process = Some(child);
    state.job_guard = job_guard;
    true
}

fn spawn_backend(app_handle: &AppHandle, backend_state: ManagedBackend) {
    if is_backend_healthy() {
        println!("[Tauri Supervisor] Local backend is already online on port {}", BACKEND_PORT);
        let mut state = backend_state.lock().unwrap();
        state.is_healthy = true;
        return;
    }

    // Initialize Windows Job Object with KILL_ON_JOB_CLOSE before spawning child
    let mut job_guard = match JobObjectGuard::create_with_kill_on_close() {
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
                println!("[Tauri Supervisor] Backend spawned via dev venv with PID {}", child.id());
                if handle_spawned_child(child, job_guard.take(), &backend_state) {
                    return;
                }
            }
            Err(err) => {
                eprintln!("[Tauri Supervisor] Failed to spawn backend via dev venv: {}", err);
            }
        }
    }

    // Production / packaged binary location
    if let Some(exe_path) = locate_backend_executable(app_handle) {
        describe_backend_bundle(&exe_path);

        #[cfg(target_os = "windows")]
        use std::os::windows::process::CommandExt;

        let mut cmd = Command::new(&exe_path);
        if let Some(parent) = exe_path.parent() {
            println!(
                "[Tauri Supervisor] Backend executable: {:?}",
                exe_path
            );
            println!(
                "[Tauri Supervisor] Backend working directory: {:?}",
                parent
            );
            println!(
                "[Tauri Supervisor] Backend executable exists: {}",
                exe_path.exists()
            );
            let internal_dir = parent.join("_internal");
            println!(
                "[Tauri Supervisor] Backend _internal exists: {}",
                internal_dir.exists()
            );
            println!(
                "[Tauri Supervisor] Python DLL exists: {}",
                internal_dir.join("python311.dll").exists()
            );
            cmd.current_dir(parent);
        }
        #[cfg(target_os = "windows")]
        {
            const CREATE_NO_WINDOW: u32 = 0x08000000;
            cmd.creation_flags(CREATE_NO_WINDOW);
        }

        match cmd.spawn() {
            Ok(child) => {
                println!("[Tauri Supervisor] Backend spawned successfully with PID {}", child.id());
                handle_spawned_child(child, job_guard.take(), &backend_state);
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
                    println!("[Tauri Supervisor] Backend spawned via dev venv with PID {}", child.id());
                    handle_spawned_child(child, job_guard.take(), &backend_state);
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
    // Signal supervision loop that this is an intentional shutdown, not a crash
    state.intentional_shutdown = true;
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

fn get_registered_folders() -> Vec<PathBuf> {
    let mut folders = Vec::new();
    let addr = SocketAddr::from(([127, 0, 0, 1], BACKEND_PORT));
    if let Ok(mut stream) = TcpStream::connect_timeout(&addr, Duration::from_millis(400)) {
        let _ = stream.set_read_timeout(Some(Duration::from_millis(800)));
        let _ = stream.set_write_timeout(Some(Duration::from_millis(400)));
        let request = format!(
            "GET /folders HTTP/1.1\r\nHost: 127.0.0.1:{}\r\nConnection: close\r\n\r\n",
            BACKEND_PORT
        );
        if stream.write_all(request.as_bytes()).is_ok() {
            let mut buf = Vec::new();
            if stream.read_to_end(&mut buf).is_ok() {
                if let Ok(resp) = std::str::from_utf8(&buf) {
                    let body = if let Some(idx) = resp.find("\r\n\r\n") {
                        &resp[idx + 4..]
                    } else if let Some(idx) = resp.find("\n\n") {
                        &resp[idx + 2..]
                    } else {
                        ""
                    };
                    if let Ok(items) = serde_json::from_str::<Vec<serde_json::Value>>(body.trim()) {
                        for item in items {
                            if let Some(p) = item.get("path").and_then(|v| v.as_str()) {
                                folders.push(PathBuf::from(p));
                            }
                        }
                    }
                }
            }
        }
    }
    folders
}

#[tauri::command]
fn open_in_explorer(path: String) -> Result<(), String> {
    if path.trim().is_empty() {
        return Err("Path cannot be empty".to_string());
    }
    let p = Path::new(&path);
    if !p.exists() {
        return Err("Path does not exist".to_string());
    }

    let canonical_target = p
        .canonicalize()
        .map_err(|e| format!("Failed to canonicalize target path: {}", e))?;

    let registered_folders = get_registered_folders();
    if registered_folders.is_empty() {
        return Err("No registered folders found or backend is offline".to_string());
    }

    let mut is_contained = false;
    for root in &registered_folders {
        if let Ok(canonical_root) = root.canonicalize() {
            // Path::starts_with is path-component-aware (handles separators, case on Windows, and prevents sibling prefix confusion)
            if canonical_target.starts_with(&canonical_root) {
                is_contained = true;
                break;
            }
        }
    }

    if !is_contained {
        return Err(format!(
            "Access denied: path '{}' is outside all registered FileMind folders",
            path
        ));
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
        intentional_shutdown: false,
    }));

    let supervisor_state = backend_state.clone();
    let restart_state = backend_state.clone();
    let cleanup_state = backend_state.clone();

    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(w) = app.get_webview_window("main") {
                let _ = w.show();
                let _ = w.set_focus();
            }
        }))
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![
            open_in_explorer
        ])

        .setup(move |app| {
            let handle = app.handle().clone();
            let bg_state = supervisor_state.clone();

            // Spawn bundled backend on startup
            std::thread::spawn(move || {
                spawn_backend(&handle, bg_state);
            });

            // Backend crash/restart supervision loop (Bug #22)
            // Polls every 5 seconds; if the backend exits unexpectedly (not during an
            // intentional_shutdown), attempts up to MAX_RESTART_ATTEMPTS restarts with
            // exponential backoff (2s, 4s, 8s).
            // This does NOT make Tauri a general process manager — it only supervises
            // the single FileMind backend process it owns.
            let sup_state = restart_state.clone();
            let sup_app = app.handle().clone();
            std::thread::spawn(move || {
                const POLL_INTERVAL_MS: u64 = 5000;
                const MAX_RESTART_ATTEMPTS: u32 = 3;
                const HEALTHY_TICKS_TO_RESET: u32 = 6; // 6 ticks * 5s = 30s stable healthy uptime
                let mut restart_count: u32 = 0;
                let mut healthy_ticks: u32 = 0;

                loop {
                    std::thread::sleep(Duration::from_millis(POLL_INTERVAL_MS));

                    // Check if we're in an intentional shutdown — if so, stop supervising
                    let should_stop = {
                        let state = sup_state.lock().unwrap();
                        state.intentional_shutdown
                    };
                    if should_stop {
                        break;
                    }

                    // Check if the child process has exited unexpectedly
                    let child_exited = {
                        let mut state = sup_state.lock().unwrap();
                        if let Some(ref mut child) = state.child_process {
                            match child.try_wait() {
                                Ok(Some(exit_status)) => {
                                    eprintln!(
                                        "[Tauri Supervisor] Backend process exited unexpectedly with status: {:?}",
                                        exit_status
                                    );
                                    true
                                }
                                Ok(None) => false,   // Still running
                                Err(e) => {
                                    eprintln!("[Tauri Supervisor] WARNING: try_wait error: {}", e);
                                    false
                                }
                            }
                        } else {
                            false // No child registered (e.g. early startup, already using an external backend)
                        }
                    };

                    if child_exited {
                        healthy_ticks = 0;
                        {
                            // Clear the dead child handle
                            let mut state = sup_state.lock().unwrap();
                            state.child_process = None;
                        }

                        if restart_count >= MAX_RESTART_ATTEMPTS {
                            eprintln!(
                                "[Tauri Supervisor] Backend has crashed {} times. Giving up.",
                                MAX_RESTART_ATTEMPTS
                            );
                            break;
                        }

                        restart_count += 1;
                        let backoff_secs = 2u64 << (restart_count - 1); // 2, 4, 8
                        eprintln!(
                            "[Tauri Supervisor] Restarting backend (attempt {}/{}) after {}s backoff...",
                            restart_count, MAX_RESTART_ATTEMPTS, backoff_secs
                        );
                        std::thread::sleep(Duration::from_secs(backoff_secs));

                        // Re-check intentional_shutdown after backoff
                        let should_stop = {
                            let state = sup_state.lock().unwrap();
                            state.intentional_shutdown
                        };
                        if should_stop {
                            break;
                        }

                        spawn_backend(&sup_app, sup_state.clone());
                        println!("[Tauri Supervisor] Backend restart {} triggered.", restart_count);
                    } else {
                        // When the backend is running, track healthy ticks to reset restart_count
                        if is_backend_healthy() {
                            healthy_ticks += 1;
                            if healthy_ticks >= HEALTHY_TICKS_TO_RESET && restart_count > 0 {
                                println!(
                                    "[Tauri Supervisor] Backend has been healthy for {}s. Resetting restart counter from {} to 0.",
                                    healthy_ticks * (POLL_INTERVAL_MS as u32 / 1000),
                                    restart_count
                                );
                                restart_count = 0;
                                healthy_ticks = 0;
                            }
                        } else {
                            healthy_ticks = 0;
                        }
                    }
                }
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
