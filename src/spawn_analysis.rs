//! Public measurement framework. No spawn answer is provided here.
use alloc::{sync::Arc, vec::Vec};
use ostd::{arch::cpu::context::UserContext, mm::{PageFlags, PAGE_SIZE}, sync::SpinLock};
use crate::{mm::VmMapping, process::Process};

pub const SAMPLE_PAGES: &[usize] = &[1, 5, 13];
const EXTRA_BASE: usize = 0x20_0000_0000;

#[derive(Debug, PartialEq, Eq)]
pub struct SpawnAnalysis {
    pub fork_copy_bytes_per_added_page: u64,
    pub spawn_copy_bytes_per_added_page: u64,
    pub discarded_parent_copy_bytes: alloc::vec::Vec<u64>,
}
#[derive(Default)]
struct Trace { copies: Vec<(usize, u64)>, discards: Vec<(usize, usize, u64)> }
static TRACE: SpinLock<Trace> = SpinLock::new(Trace { copies: Vec::new(), discards: Vec::new() });
pub(crate) fn record_copy(source: usize, bytes: u64) { TRACE.lock().copies.push((source, bytes)); }
pub(crate) fn record_discard(space: usize, source: usize, bytes: u64) { TRACE.lock().discards.push((space, source, bytes)); }
fn reset() { *TRACE.lock() = Trace::default(); }
fn copies_of(source: usize) -> Result<u64, &'static str> {
    let trace = TRACE.lock();
    if trace.copies.iter().any(|(id, _)| *id != source) { return Err("unexpected copy source"); }
    Ok(trace.copies.iter().map(|(_, bytes)| *bytes).sum())
}
fn slope(pages: &[usize], bytes: &[u64]) -> Result<u64, &'static str> {
    if pages.len() < 3 || pages.len() != bytes.len() { return Err("at least three samples required"); }
    let mut result = None;
    for i in 1..pages.len() {
        let dp = pages[i].checked_sub(pages[i-1]).filter(|d| *d > 0).ok_or("pages must strictly increase")? as u64;
        let db = bytes[i].checked_sub(bytes[i-1]).ok_or("negative delta")?;
        if db % dp != 0 { return Err("non-integral byte slope"); }
        let value = db / dp;
        if result.is_some_and(|v| v != value) { return Err("inconsistent adjacent slopes"); }
        result = Some(value);
    }
    Ok(result.unwrap())
}

pub fn analyze_spawn(pages: &[usize]) -> Result<SpawnAnalysis, &'static str> {
    // Reject invalid input before creating processes or mapping pages.
    if pages != SAMPLE_PAGES { return Err("use public fixed samples [1,5,13]"); }
    crate::progs::init();
    let initial_count = Process::experiment_process_count();
    let parent_elf = crate::progs::lookup_progs("spawn").unwrap();
    let target_elf = crate::progs::lookup_progs("hello_world").unwrap();
    let mut fork_bytes = Vec::new();
    let mut spawn_bytes = Vec::new();
    let mut discarded = Vec::new();
    for &extra_pages in pages {
        let parent = Process::new(parent_elf);
        parent.memory_space().map(VmMapping::new(EXTRA_BASE, extra_pages, PageFlags::RW));
        let original = parent.memory_space().snapshot();
        let expected = Process::new(target_elf);
        let target = expected.memory_space().snapshot();
        expected.dispose_experiment();
        drop(expected);
        let mut fork_child = None;
        let mut spawn_child = None;
        let result = (|| {
            let source = parent.memory_space().identity();
            reset();
            let child = parent.fork(&UserContext::default());
            fork_child = Some(child.clone());
            let copied = copies_of(source)?;
            if copied != parent.memory_space().mapped_bytes() || copied == 0
                || child.memory_space().snapshot() != original || !parent.checked_child(&child) {
                return Err("fork did not duplicate the measured parent");
            }
            child.exec(target_elf);
            if child.memory_space().snapshot() != target || parent.memory_space().snapshot() != original {
                return Err("exec target or parent memory mismatch");
            }
            // Only a clear of this exact duplicated address space counts as discarded parent data.
            if TRACE.lock().discards.as_slice() != [(child.memory_space().identity(), source, copied)] {
                return Err("exec discard provenance mismatch");
            }
            if copies_of(source)? != copied { return Err("exec unexpectedly copied parent data"); }
            fork_bytes.push(copied);
            discarded.push(TRACE.lock().discards[0].2);
            child.dispose_experiment();
            fork_child = None;
            drop(child);
            reset();
            let child = crate::syscall::spawn::do_spawn(target_elf, &parent).ok_or("spawn returned None")?;
            spawn_child = Some(child.clone());
            if !parent.checked_child(&child) || Arc::ptr_eq(parent.memory_space().vm_space(), child.memory_space().vm_space())
                || child.memory_space().snapshot() != target || parent.memory_space().snapshot() != original {
                return Err("spawn child, process tree, target ELF, mappings or parent state invalid");
            }
            spawn_bytes.push(copies_of(source)?);
            Ok(())
        })();
        if let Some(child) = fork_child { child.dispose_experiment(); }
        if let Some(child) = spawn_child { if !Arc::ptr_eq(&child, &parent) { child.dispose_experiment(); } }
        parent.dispose_experiment();
        drop(parent);
        reset();
        if Process::experiment_process_count() != initial_count { return Err("experiment leaked processes"); }
        result?;
    }
    let result = SpawnAnalysis {
        fork_copy_bytes_per_added_page: slope(pages, &fork_bytes)?,
        spawn_copy_bytes_per_added_page: slope(pages, &spawn_bytes)?,
        discarded_parent_copy_bytes: discarded,
    };
    proof_analysis(&[
        result.fork_copy_bytes_per_added_page, result.spawn_copy_bytes_per_added_page,
        result.discarded_parent_copy_bytes[0], result.discarded_parent_copy_bytes[1], result.discarded_parent_copy_bytes[2],
        fork_bytes[0], fork_bytes[1], fork_bytes[2], spawn_bytes[0], spawn_bytes[1], spawn_bytes[2],
    ]);
    ostd::early_println!("A2_EVIDENCE {{\"pages\":{:?},\"fork\":{:?},\"spawn\":{:?}}}", pages, fork_bytes, spawn_bytes);
    Ok(result)
}

#[ostd::prelude::ktest]
fn analysis_measurements() {
    ostd::early_println!("");
    assert!(analyze_spawn(&[]).is_err());
    assert!(analyze_spawn(&[1,1,3]).is_err());
    assert!(slope(&[1,2,4], &[0,1,2]).is_err());
    let a = analyze_spawn(SAMPLE_PAGES).expect("incomplete or invalid experiment");
    ostd::early_println!("A2_ANALYSIS {{\"fork_copy_bytes_per_added_page\":{},\"spawn_copy_bytes_per_added_page\":{},\"discarded_parent_copy_bytes\":{:?}}}",
        a.fork_copy_bytes_per_added_page, a.spawn_copy_bytes_per_added_page, a.discarded_parent_copy_bytes);
    ostd::early_println!("A2_ANALYSIS_COMPLETE");
}

// Only the completed trusted measurement path can call this private checkpoint.
#[inline(never)]
fn proof_analysis(values: &[u64; 11]) { core::hint::black_box(values); }
