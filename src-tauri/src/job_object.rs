// Windows Job Object Lifecycle Guard for FileMind Sidecar Supervisor
// Ensures child backend process is bound to parent Tauri process lifetime.

#[cfg(target_os = "windows")]
use std::os::windows::io::AsRawHandle;
#[cfg(target_os = "windows")]
use std::ptr;
#[cfg(target_os = "windows")]
use windows_sys::Win32::Foundation::{CloseHandle, GetLastError, HANDLE, INVALID_HANDLE_VALUE};
#[cfg(target_os = "windows")]
use windows_sys::Win32::System::JobObjects::{
    AssignProcessToJobObject, CreateJobObjectW, SetInformationJobObject,
    JobObjectExtendedLimitInformation, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
};

pub struct JobObjectGuard {
    #[cfg(target_os = "windows")]
    handle: HANDLE,
}

// Safety: Windows HANDLE for JobObject is safe to transfer between threads
// when protected by standard synchronization primitives (Arc/Mutex).
unsafe impl Send for JobObjectGuard {}
unsafe impl Sync for JobObjectGuard {}

impl JobObjectGuard {
    #[cfg(target_os = "windows")]
    pub fn create_with_kill_on_close() -> Result<Self, String> {
        unsafe {
            let job_handle = CreateJobObjectW(ptr::null(), ptr::null());
            if job_handle.is_null() || job_handle == INVALID_HANDLE_VALUE {
                let err = GetLastError();
                return Err(format!(
                    "Failed to create Windows Job Object (Win32 Error {})",
                    err
                ));
            }

            let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
            info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;

            let result = SetInformationJobObject(
                job_handle,
                JobObjectExtendedLimitInformation,
                &info as *const _ as *const std::ffi::c_void,
                std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
            );

            if result == 0 {
                let err = GetLastError();
                CloseHandle(job_handle);
                return Err(format!(
                    "Failed to set JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE on Job Object (Win32 Error {})",
                    err
                ));
            }

            println!("[JobObject] Initialized Windows Job Object with KILL_ON_JOB_CLOSE");
            Ok(Self { handle: job_handle })
        }
    }

    #[cfg(not(target_os = "windows"))]
    pub fn create_with_kill_on_close() -> Result<Self, String> {
        Ok(Self {})
    }

    #[cfg(target_os = "windows")]
    pub fn assign_child(&self, child: &std::process::Child) -> Result<(), String> {
        let raw_handle = child.as_raw_handle() as HANDLE;
        let pid = child.id();
        unsafe {
            let result = AssignProcessToJobObject(self.handle, raw_handle);
            if result == 0 {
                let err = GetLastError();
                return Err(format!(
                    "Failed to assign child process (PID {}) to Job Object (Win32 Error {})",
                    pid, err
                ));
            }
            println!(
                "[JobObject] Successfully assigned backend child process (PID {}) to Job Object",
                pid
            );
            Ok(())
        }
    }

    #[cfg(not(target_os = "windows"))]
    pub fn assign_child(&self, _child: &std::process::Child) -> Result<(), String> {
        Ok(())
    }

    #[cfg(target_os = "windows")]
    #[allow(dead_code)]
    pub fn raw_handle(&self) -> HANDLE {
        self.handle
    }
}

impl Drop for JobObjectGuard {
    fn drop(&mut self) {
        #[cfg(target_os = "windows")]
        unsafe {
            if !self.handle.is_null() && self.handle != INVALID_HANDLE_VALUE {
                println!("[JobObject] Closing Job Object handle");
                CloseHandle(self.handle);
                self.handle = ptr::null_mut();
            }
        }
    }
}
