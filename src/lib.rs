#![no_std]
#![forbid(unsafe_code)]
#![feature(fn_traits)]
#![feature(ascii_char)]

pub mod console;
mod error;
mod logger;
mod mm;
#[cfg(ktest)]
pub mod spawn_analysis;
pub mod process;
pub mod progs;
pub mod syscall;

extern crate alloc;

#[ostd::main]
pub fn main() {
    logger::init();
    progs::init();
    let process = process::Process::new(progs::lookup_progs("spawn").unwrap());
    process.run();
}

#[cfg(ktest)]
mod test {
    use ostd::prelude::ktest;
    use ostd::{arch::cpu::context::UserContext, early_println};

    // Private symbol observed by QEMU outside the guest; serial output is not proof.
    #[inline(never)]
    fn proof_performance(values: &[u64; 2]) { core::hint::black_box(values); }

    #[ktest]
    pub fn spawn_performance_compare2_fork_exec() {
        use crate::process::Process;
        use alloc::sync::Arc;

        // Prepare...
        crate::progs::init();
        let process = Process::new(crate::progs::lookup_progs("spawn").unwrap());
        let hello_world = crate::progs::lookup_progs("hello_world").unwrap();
        let user_context = UserContext::default();

        let mut created = alloc::vec::Vec::new();
        // Call spawn multiple times
        let current_time = ostd::timer::Jiffies::elapsed().as_duration();
        for _ in 0..10 {
            let raw_spawn_process = crate::syscall::spawn::do_spawn(hello_world, &process);
            assert!(raw_spawn_process.is_some());
            let spawn_process = raw_spawn_process.unwrap();
            assert!(spawn_process.parent_process().is_some());
            created.push(spawn_process.clone());
            assert!(Arc::ptr_eq(
                &spawn_process.parent_process().unwrap(),
                &process
            ));
        }
        let spawn_time = ostd::timer::Jiffies::elapsed().as_duration() - current_time;

        // Call fork + exec multiple times
        let current_time = ostd::timer::Jiffies::elapsed().as_duration();
        for _ in 0..10 {
            let child = process.fork(&user_context);
            child.exec(hello_world);
            created.push(child);
        }
        let fork_exec_time = ostd::timer::Jiffies::elapsed().as_duration() - current_time;

        for child in created { child.dispose_experiment(); }
        process.dispose_experiment();
        assert!(fork_exec_time.as_micros() as f64 > spawn_time.as_micros() as f64 * 1.8);
        assert!(spawn_time.as_micros() as f64 * 8.0 > fork_exec_time.as_micros() as f64);
        proof_performance(&[spawn_time.as_micros() as u64, fork_exec_time.as_micros() as u64]);
        early_println!(
            "[KTEST] spawn time: {:?}, fork+exec time: {:?}",
            spawn_time,
            fork_exec_time
        );
    }
}
