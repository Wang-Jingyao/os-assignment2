use alloc::sync::Arc;
use log::debug;
use ostd::arch::qemu::exit_qemu;

use crate::error::Result;
use crate::process::Process;
use crate::syscall::{SyscallReturn, exit};

pub fn sys_exit(exit_code: u32, current_process: &Arc<Process>) -> Result<SyscallReturn> {
    debug!(
        "[pid: {}] exit with code: {}",
        current_process.pid(),
        exit_code
    );
    if current_process.is_zombie() {
        debug!("[pid: {}] has already exited", current_process.pid());
    } else {
        if current_process.pid() == 1 {
            if exit_code == 0 {
                exit_qemu(ostd::arch::qemu::QemuExitCode::Success);
            } else {
                exit_qemu(ostd::arch::qemu::QemuExitCode::Failed);
            }
        }
        current_process.exit(exit_code);
    }
    Ok(SyscallReturn(0))
}
