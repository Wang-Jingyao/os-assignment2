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
    const SYS_SPAWN: usize = 300;
    const MAX_FILENAME_LENGTH: usize = 256;

    if syscall_number != SYS_SPAWN {
        return Err(Error::new(Errno::ENOSYS));
    }

    let path = args[0] as Vaddr;
    if path == 0 {
        return Err(Error::new(Errno::EFAULT));
    }

    let mut buffer = [0u8; MAX_FILENAME_LENGTH];
    let vm_space = current_process.memory_space().vm_space();

    for i in 0..MAX_FILENAME_LENGTH {
        let addr = path.checked_add(i).ok_or(Error::new(Errno::EFAULT))?;
        vm_space.reader(addr, 1).map_err(|_| Error::new(Errno::EFAULT))?.read_fallible(&mut VmWriter::from(&mut buffer[i..i + 1])).map_err(|_| Error::new(Errno::EFAULT))?;
        if buffer[i] == 0 {
            break;
        }
    }

    let program_name = CStr::from_bytes_until_nul(&buffer)
        .map_err(|_| Error::new(Errno::ENAMETOOLONG))?
        .to_str()
        .map_err(|_| Error::new(Errno::EINVAL))?;

    let binary = crate::progs::lookup_progs(program_name)?;
    let child = do_spawn(binary, current_process).ok_or(Error::new(Errno::ENOMEM))?;
    let pid = child.pid();
    child.run();
    Ok(SyscallReturn(pid as isize))
}

pub fn do_spawn(program: &[u8], current_process: &Arc<Process>) -> Option<Arc<Process>> {
    let child = Process::new(program);
    child.setup_parent(current_process);
    Some(child)
}
