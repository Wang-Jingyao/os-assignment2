use core::ffi::CStr;

use alloc::sync::Arc;
use alloc::vec;
use log::{debug, info};
use ostd::mm::{FallibleVmRead, Vaddr, VmWriter};

use crate::error::{Errno, Error, Result};
use crate::process::Process;
use crate::syscall::SyscallReturn;

pub fn handle_extra_syscall(
    syscall_number: usize,
    args: &[usize; 6],
    current_process: &Arc<Process>,
) -> Result<SyscallReturn> {
    Err(Error::new(Errno::ENOSYS))
}

pub fn do_spawn(program: &[u8], current_process: &Arc<Process>) -> Option<Arc<Process>> {
    None
}
