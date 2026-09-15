"""Preserve the interrupted full4 specimen; never infer a successful join."""
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
sys.dont_write_bytecode = True

WORK = Path(__file__).parent
SPEC = importlib.util.spec_from_file_location('archive_helpers', WORK/'prepare_headless_lineage_full4_archive_r1.py')
helpers = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helpers)
STAGE = WORK/'headless-lineage-controller-full4-incomplete-archive-r1'
PRIVATE = WORK.parent/'retained-private-evidence/headless-lineage-controller-full4-incomplete-r1'


def stamp(path):
    raw = path.read_bytes()
    return {'sha256': hashlib.sha256(raw).hexdigest(), 'byte_count': len(raw), 'mtime_ns': path.stat().st_mtime_ns}


def absent_original_process():
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000, False, helpers.PID)
    if handle:
        kernel.CloseHandle(handle)
        raise RuntimeError('full4 PID is present; inspect identity before archival')
    error = ctypes.get_last_error()
    if error != 87:
        raise OSError(error, 'cannot prove original PID absent')
    return {'pid': helpers.PID, 'observed_at': datetime.now(timezone.utc).isoformat(),
            'open_process_error': error, 'process_present': False,
            'exit_code': None, 'termination_reason': 'unknown'}


def main():
    audit = WORK/'headless-lineage-controller-full4-interruption-audit-r1.json'
    if not audit.is_file():
        raise RuntimeError('independent read-only interruption audit required')
    process_before = absent_original_process()
    if STAGE.exists() or PRIVATE.exists():
        raise FileExistsError('incomplete archive outputs must be fresh')
    STAGE.mkdir(); PRIVATE.mkdir(parents=True)
    source_paths = [helpers.REPO/name for name in subprocess.check_output(
        ['git', '-C', str(helpers.REPO), 'ls-files', '*.py', '*.md'], text=True).splitlines()
        if not name.startswith(('results/', 'data/')) and (helpers.REPO/name).is_file()]
    paths = list(helpers.regular_files(helpers.ROOT))
    external = [audit, WORK/'join_lineage_full4_r1.py', WORK/'join_lineage_full4_r2.py', Path(__file__)]
    for stem in ('full', 'full2', 'full3', 'full4'):
        external += [WORK/f'headless-lineage-controller-{stem}{ext}' for ext in ('.log', '.xml')]
    external += [WORK/f'headless-lineage-controller-full4-root-join-r{index}.json' for index in (1, 2)]
    external = [path for path in external if path.is_file()]
    before = {str(path): stamp(path) for path in [*paths, *external, *source_paths]}
    public, private = [], []
    for path in paths:
        row = ('full4/'+path.relative_to(helpers.ROOT).as_posix(), path.read_bytes(), str(path))
        (public if path.name in helpers.PUBLIC_NAMES or path.suffix == '.xml' else private).append(row)
    for path in external:
        row = ('external/'+path.name, path.read_bytes(), str(path))
        (private if path.suffix == '.log' else public).append(row)
    source = [('source/'+p.relative_to(helpers.REPO).as_posix(), p.read_bytes(), str(p)) for p in source_paths]
    source_members = helpers.add_zip(STAGE/'source-exact.zip', source)
    public_members = helpers.add_zip(STAGE/'public-metadata.zip', public)
    private_members = helpers.add_zip(PRIVATE/'retained-private.zip', private)
    after = {str(path): stamp(path) for path in [*paths, *external, *source_paths]}
    if before != after:
        raise RuntimeError('original/source bytes or mtimes changed during preservation')
    process_after = absent_original_process()
    attempt = json.loads((helpers.ROOT/'run/controller-attempt.json').read_text(encoding='utf-8'))
    counts = {}
    for row in attempt['cells']:
        counts[row['status']] = counts.get(row['status'], 0) + 1
    manifest = {'schema': 'headless-lineage-full4-incomplete-archive-v1',
        'status': 'incomplete_no_terminal_receipt', 'scientific_effectiveness_proven': False,
        'recorded_source_commit': helpers.COMMIT,
        'current_source_commit': subprocess.check_output(['git','-C',str(helpers.REPO),'rev-parse','HEAD'],text=True).strip(),
        'source_snapshot': 'post_interruption_disk_bytes', 'pre_run_source_manifest': 'absent_not_claimed',
        'source_status': subprocess.check_output(['git','-C',str(helpers.REPO),'status','--porcelain'],text=True),
        'process_before': process_before, 'process_after': process_after,
        'attempt_snapshot': {'status': attempt['status'], 'cells': len(attempt['cells']),
            'cell_counts': counts, 'actual_scorer_calls': attempt['actual_scorer_calls'],
            'final_gate_present': isinstance(attempt.get('lineage_evaluator_final_gate'), dict)},
        'missing_terminal_evidence': [str(p) for p in (WORK/'headless-lineage-controller-full4.xml',
            WORK/'headless-lineage-controller-full4-root-join-r2.json') if not p.exists()],
        'test_restarted': False, 'test_terminated_by_archiver': False,
        'excluded_credentials': helpers.EXCLUSIONS, 'pruned_reparse_paths': sorted(helpers.PRUNED_LINKS),
        'original_files_before': before, 'original_files_after': after,
        'source_members': source_members, 'public_members': public_members, 'retained_private_members': private_members,
        'archives': {str(p): stamp(p) for p in (STAGE/'source-exact.zip', STAGE/'public-metadata.zip', PRIVATE/'retained-private.zip')}}
    with (STAGE/'manifest.json').open('x', encoding='utf-8') as output:
        json.dump(manifest, output, ensure_ascii=False, sort_keys=True, indent=2)
    print(json.dumps({'stage':str(STAGE), 'manifest':stamp(STAGE/'manifest.json'),
        'source_files':len(source_members),'public_files':len(public_members),'private_files':len(private_members),
        'attempt_snapshot':manifest['attempt_snapshot']}), flush=True)


if __name__ == '__main__':
    main()
