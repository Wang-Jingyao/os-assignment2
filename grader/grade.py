#!/usr/bin/env python3
"""Public A2 v4 scoring entry. The backend calls this exact file."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import time
import threading
import tempfile
import sys

from qemu_evidence import collect
import uuid

WEIGHTS = {'correctness': 50, 'performance': 30, 'analysis_fork': 5, 'analysis_spawn': 5, 'analysis_discard': 10}
PAGES = [1, 5, 13]
PAGE_BYTES = 4096
TIMEOUT = 300
OUTPUT_LIMIT = 2 * 1024 * 1024
ANSI = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')
FIELDS = {'fork_copy_bytes_per_added_page', 'spawn_copy_bytes_per_added_page', 'discarded_parent_copy_bytes'}

def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result: raise ValueError('duplicate JSON key')
        result[key] = value
    return result

def protocol(log, prefix):
    lines = [line for line in log.splitlines() if prefix + ' ' in line or line == prefix]
    if len(lines) != 1 or not lines[0].startswith(prefix + ' '):
        raise ValueError(prefix + ': missing, duplicate or invalid line')
    line = lines[0][len(prefix)+1:]
    if '\x1b' in line: raise ValueError('ANSI in analysis output')
    return json.loads(line, object_pairs_hook=unique_object)

def uint(value):
    return type(value) is int and 0 <= value <= 2**64-1

def adjacent(values):
    if not isinstance(values, list) or len(values) != len(PAGES) or not all(uint(v) for v in values): raise ValueError('invalid sample count/bytes')
    slopes = []
    for i in range(1, len(PAGES)):
        delta = values[i] - values[i-1]
        step = PAGES[i] - PAGES[i-1]
        if delta < 0 or delta % step: raise ValueError('negative or non-integral delta')
        slopes.append(delta // step)
    if len(set(slopes)) != 1: raise ValueError('inconsistent adjacent slopes')
    return slopes[0]

def completed_test(log):
    plain = ANSI.sub('', log)
    if '[caught panic]' in plain or re.search(r'\b[1-9]\d* failed', plain) or 'panicked at' in plain.lower():
        raise ValueError('kernel panic or test failure')
    if plain.count('[ktest runner] All crates tested.') != 1 or not re.search(r'test result: ok\. 1 passed; 0 failed;', plain):
        raise ValueError('test did not complete exactly one passing test')

def require_evidence(evidence, kind, count):
    if not isinstance(evidence, dict) or evidence.get('kind') != kind:
        raise ValueError('missing trusted QEMU evidence: '+kind)
    values = evidence.get('values')
    if not isinstance(values, list) or len(values) != count or not all(uint(v) for v in values):
        raise ValueError('invalid trusted QEMU evidence')
    return values

def analysis_scores(log, evidence=None):
    values = require_evidence(evidence, 'analysis', 11)
    completed_test(log)
    if log.splitlines().count('A2_ANALYSIS_COMPLETE') != 1: raise ValueError('experiment not completed')
    a = protocol(log, 'A2_ANALYSIS')
    e = protocol(log, 'A2_EVIDENCE')
    if not isinstance(a, dict) or set(a) != FIELDS: raise ValueError('analysis requires exactly three fields')
    if not all(uint(a[k]) for k in FIELDS if k != 'discarded_parent_copy_bytes'): raise ValueError('byte values must be unsigned integers')
    discarded = a['discarded_parent_copy_bytes']
    if not isinstance(discarded, list) or len(discarded) != len(PAGES) or not all(uint(v) for v in discarded): raise ValueError('invalid discard array')
    if not isinstance(e, dict) or set(e) != {'pages','fork','spawn'} or e['pages'] != PAGES or not all(type(v) is int for v in e['pages']): raise ValueError('invalid public samples')
    measured_a = dict(zip(['fork_copy_bytes_per_added_page','spawn_copy_bytes_per_added_page'],values[:2]))
    measured_a['discarded_parent_copy_bytes'] = values[2:5]
    measured_e = {'pages':PAGES,'fork':values[5:8],'spawn':values[8:11]}
    if a != measured_a or e != measured_e:
        raise ValueError('serial JSON disagrees with trusted QEMU measurements')
    f, s = adjacent(measured_e['fork']), adjacent(measured_e['spawn'])
    # Each component is independent after the shared experiment-validity prerequisites.
    return {
      'analysis_fork': (f == a['fork_copy_bytes_per_added_page'] == PAGE_BYTES, 'fork slope must equal measured 4096 bytes/page'),
      'analysis_spawn': (s == a['spawn_copy_bytes_per_added_page'] == 0, 'spawn slope must equal measured 0 bytes/page'),
      'analysis_discard': (discarded == e['fork'] and all(v > 0 for v in discarded), 'discard array must equal each measured fork copy, with verified exec provenance'),
    }

def execute(command, path, deadline, evidence_kind=None):
    if evidence_kind:
        # Keep the QEMU socket path short and independent of the project directory.
        with tempfile.TemporaryDirectory(prefix='a2-evidence-', dir='/tmp') as directory:
            return _execute(command, path, deadline, evidence_kind, Path(directory)/'qemu.sock')
    return _execute(command, path, deadline)

def _execute(command, path, deadline, evidence_kind=None, socket_path=None):
    path.parent.mkdir(exist_ok=True)
    evidence = {}; evidence_error = []; observer = None; execution_error = None
    if evidence_kind:
        command = list(command) + ['--qemu-args=-chardev socket,path='+str(socket_path)+',server=on,wait=off,id=a2proof', '--qemu-args=-gdb chardev:a2proof', '--qemu-args=-S']
    with path.open('wb') as stream:
        proc = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
        if evidence_kind:
            def observe():
                try: evidence.update(collect(evidence_kind, socket_path, proc, deadline))
                except Exception as error: evidence_error.append(str(error))
            observer = threading.Thread(target=observe, daemon=True); observer.start()
        try:
            while proc.poll() is None:
                if evidence_error: raise ValueError('trusted QEMU observation failed: '+evidence_error[0])
                if time.monotonic() > deadline: raise ValueError('timeout (300 seconds per section)')
                if path.stat().st_size > OUTPUT_LIMIT: raise ValueError('output limit (2 MiB)')
                time.sleep(.1)
        except ValueError as error:
            execution_error = error
        finally:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
        if observer: observer.join(timeout=2)
    text = path.read_text(errors='replace')
    print(text, end='', flush=True)
    if path.stat().st_size > OUTPUT_LIMIT: raise ValueError('output limit (2 MiB)')
    if execution_error: raise execution_error
    if proc.returncode: raise ValueError('command failed (exit %s): %s' % (proc.returncode, ' '.join(command)))
    if evidence_kind:
        if evidence_error: raise ValueError('trusted QEMU observation failed: '+evidence_error[0])
        if not evidence: raise ValueError('missing trusted QEMU checkpoint')
        Path('target/'+evidence_kind+'-evidence.json').write_text(json.dumps(evidence,indent=2)+'\n')
        print('A2_HOST_EVIDENCE '+json.dumps(evidence),flush=True)
        return text, evidence
    return text

def section(kind):
    deadline = time.monotonic() + TIMEOUT
    shutil.copyfile('ans.rs', 'src/syscall/spawn.rs')
    Path('src/progs/progs.rs').unlink(missing_ok=True)
    if kind == 'correctness':
        token = str(uuid.uuid4())
        Path('user/spawn.c').write_text(Path('user/spawn_template.c').read_text().replace('#define TOKEN ""', '#define TOKEN "'+token+'"'))
    execute(['make','build_user_programs','generate_progs_rs'], Path('target/'+kind+'-build.log'), deadline)
    if kind == 'correctness':
        log, evidence = execute(['cargo','osdk','run','--target-arch=riscv64'], Path('target/correctness.log'), deadline, 'correctness')
        if require_evidence(evidence, 'correctness', 4) != [10,10,10,10]: raise ValueError('incomplete real child lifecycle')
        if log.splitlines().count('Token: '+token) != 1 or log.splitlines().count('Spawn test passed!') != 1:
            raise ValueError('correctness target did not finish')
        return {'correctness': (True, '')}
    test = 'spawn_performance_compare2_fork_exec' if kind == 'performance' else 'analysis_measurements'
    log, evidence = execute(['cargo','osdk','test','--target-arch=riscv64',test], Path('target/'+kind+'.log'), deadline, kind)
    if kind == 'analysis': return analysis_scores(log, evidence)
    completed_test(log)
    spawn, fork_exec = require_evidence(evidence, 'performance', 2)
    if not (fork_exec > spawn * 1.8 and fork_exec < spawn * 8.0): raise ValueError('measured performance outside original bounds')
    if log.count('[KTEST] spawn time:') != 1: raise ValueError('missing/duplicate timing output')
    return {'performance': (True, '')}

def run_in_safe_directory(project, args):
    # OSDK 0.16.1 also misparses some project paths, independently of QEMU.
    # Build a temporary source copy and return the logs to the student's project.
    candidates = [p for p in project.parents
                  if str(p).isascii() and not any(c.isspace() for c in str(p))
                  and os.access(p, os.W_OK | os.X_OK)]
    parent = candidates[0] if candidates else Path('/tmp')
    result_path = Path(args.result).resolve()
    with tempfile.TemporaryDirectory(prefix='a2-build-', dir=parent) as directory:
        workspace = Path(directory)
        shutil.copytree(project, workspace, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('target', '.git', '__pycache__', 'submission.zip'))
        command = [sys.executable, str(workspace/'grader/grade.py'), '--result', str(result_path)]
        if args.question:
            command += ['--question', args.question]
        print('项目路径含空格或非 ASCII 字符，使用临时目录构建。', flush=True)
        try:
            return subprocess.run(command, cwd=workspace).returncode
        finally:
            target = project/'target'
            target.mkdir(exist_ok=True)
            for pattern in ('*.log', '*.json'):
                for path in (workspace/'target').glob(pattern):
                    shutil.copy2(path, target/path.name)
            if (workspace/'qemu.log').is_file():
                shutil.copy2(workspace/'qemu.log', target/'qemu.log')

def main():
    project = Path(__file__).resolve().parents[1]
    os.chdir(project)
    parser = argparse.ArgumentParser()
    parser.add_argument('--question', choices=list(WEIGHTS))
    parser.add_argument('--result', default='target/grades.json')
    args = parser.parse_args()
    if not str(project).isascii() or any(c.isspace() for c in str(project)):
        return run_in_safe_directory(project, args)
    requested = [args.question] if args.question else list(WEIGHTS)
    scores = {}
    for kind in ('correctness','performance','analysis'):
        keys = [k for k in requested if (k.startswith('analysis_') if kind == 'analysis' else k == kind)]
        if not keys: continue
        try: values = section(kind)
        except (ValueError, OSError, TypeError) as error: values = {k: (False, str(error)) for k in keys}
        for key in keys:
            passed, reason = values[key]
            scores[key] = {'score': WEIGHTS[key] if passed else 0, 'max_score': WEIGHTS[key], 'reason': '' if passed else reason}
    result = {'rubric_version':'a2-v4', 'results': scores, 'total':sum(v['score'] for v in scores.values()), 'max_score':sum(v['max_score'] for v in scores.values())}
    out = Path(args.result); out.parent.mkdir(parents=True, exist_ok=True); out.write_text(json.dumps(result, indent=2)+'\n')
    for k,v in scores.items(): print(f"{k}: {v['score']} / {v['max_score']}" + (' — '+v['reason'] if v['reason'] else ''))
    print(f"total: {result['total']} / {result['max_score']}")
    print('A2_GRADE '+json.dumps(result, separators=(',',':')))
    return 0 if result['total'] == result['max_score'] else 1

if __name__ == '__main__': raise SystemExit(main())
