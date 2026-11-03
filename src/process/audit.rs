//! Private runtime evidence. Nothing in the answer module can write these records.
use super::{Process, PROCESS_TABLE, elf};
use alloc::{sync::Arc, vec::Vec};
use ostd::{arch::cpu::context::UserContext, sync::Mutex, user::UserContextApi};

struct Audit { valid: bool, starts: Vec<usize>, exits: Vec<usize>, spawns: Vec<usize>, waits: Vec<usize> }
static AUDIT: Mutex<Audit> = Mutex::new(Audit {
    valid: true, starts: Vec::new(), exits: Vec::new(), spawns: Vec::new(), waits: Vec::new(),
});

pub(super) fn on_start(process: &Arc<Process>, context: &UserContext) {
    if process.pid() == 1 { return; }
    let parent = process.parent_process();
    let valid_parent = parent.as_ref().is_some_and(|p| p.pid() == 1);
    let (expected, expected_context) = elf::create_user_space(crate::progs::lookup_progs("spawn_test").unwrap());
    let valid = valid_parent
        && context.instruction_pointer() == expected_context.instruction_pointer()
        && context.stack_pointer() == expected_context.stack_pointer()
        && process.memory_space().snapshot() == expected.snapshot()
        && !Arc::ptr_eq(process.memory_space().vm_space(), parent.as_ref().unwrap().memory_space().vm_space())
        && PROCESS_TABLE.lock().get(&process.pid()).is_some_and(|p| Arc::ptr_eq(p, process));
    expected.clear();
    let mut audit = AUDIT.lock();
    if !valid || audit.starts.contains(&process.pid()) { audit.valid = false; }
    audit.starts.push(process.pid());
}

pub(super) fn before_syscall(process: &Arc<Process>, context: &UserContext) {
    if !matches!(context.a7(), 93 | 94) { return; }
    if process.pid() != 1 {
        let mut audit = AUDIT.lock();
        if context.a0() != 100 || !audit.starts.contains(&process.pid()) || audit.exits.contains(&process.pid()) {
            audit.valid = false;
        }
        audit.exits.push(process.pid());
        return;
    }
    if context.a0() != 0 { return; }
    let audit = AUDIT.lock();
    let expected: Vec<_> = (2..=11).collect();
    let mut starts = audit.starts.clone(); starts.sort();
    let mut exits = audit.exits.clone(); exits.sort();
    if audit.valid && starts == expected && exits == expected && audit.spawns == expected && audit.waits == expected
        && process.children.lock().is_empty() && PROCESS_TABLE.lock().len() == 1 {
        proof_correctness(&[audit.spawns.len() as u64, starts.len() as u64, exits.len() as u64, audit.waits.len() as u64]);
    }
}

pub(super) fn after_syscall(process: &Arc<Process>, number: usize, context: &UserContext) {
    if process.pid() != 1 || !matches!(number, 300 | 260) { return; }
    let pid = context.a0();
    if number == 300 {
        let child = process.children.lock().get(&pid).cloned();
        let registered = child.as_ref().is_some_and(|c|
            c.parent_process().is_some_and(|p| Arc::ptr_eq(&p, process))
            && PROCESS_TABLE.lock().get(&pid).is_some_and(|p| Arc::ptr_eq(p, c)));
        let mut audit = AUDIT.lock();
        if !registered || pid != 2 + audit.spawns.len() { audit.valid = false; }
        audit.spawns.push(pid);
    } else {
        let gone = !process.children.lock().contains_key(&pid) && !PROCESS_TABLE.lock().contains_key(&pid);
        let mut audit = AUDIT.lock();
        if !gone || !audit.exits.contains(&pid) || pid != 2 + audit.waits.len() { audit.valid = false; }
        audit.waits.push(pid);
    }
}

// Not exported and not callable from syscall::spawn. The host observes the PC and reads a0.
#[inline(never)]
fn proof_correctness(values: &[u64; 4]) { core::hint::black_box(values); }
