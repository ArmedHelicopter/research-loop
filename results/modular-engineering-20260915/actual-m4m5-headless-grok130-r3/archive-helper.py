"""Archive the closed eight-cell TRAIN attempt, retaining failure and raw custody."""
import hashlib
import importlib.util
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
import zipfile

BASE = Path('E:/_ryanDev/AI/research-loop-modular')
WORK = BASE / 'work'
RUN = WORK / 'actual-m4m5-headless-grok130-run-r3'
PREP = WORK / 'actual-m4m5-headless-grok130-preparation-r3'
RAW_PRIVATE = BASE / 'custody-private/actual-m4m5-headless-grok130-r3'
DEST = BASE / 'artifact-evidence-provenance/results/modular-engineering-20260915/actual-m4m5-headless-grok130-r3'
RETAINED = BASE / 'retained-private-evidence/actual-m4m5-headless-grok130-r3'
HELPER = WORK / 'prepare_headless_lineage_full4_archive_r1.py'
SOURCE_COMMIT = '62695576080b974d3ebae7a265039f6d761a5aef'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def write(path, value):
    with path.open('xb') as stream:
        stream.write((json.dumps(value, indent=2, ensure_ascii=False) + '\n').encode())


def stamp(path):
    raw = path.read_bytes()
    return {'sha256': sha(raw), 'bytes': len(raw), 'mtime_ns': path.stat().st_mtime_ns}


def diagnostics(role, ledger_path):
    ledger = read(ledger_path)
    rows = []
    for index, call in enumerate(ledger['calls'], 1):
        native = Path(call['private_directory'])
        assert native.is_relative_to(BASE)
        observer_path = native.parent / 'observer-receipt.private.json'
        observer = read(observer_path)
        pre = observer.get('account_preflight')
        span = None if not pre else (datetime.fromisoformat(pre['observed_at']) -
                                    datetime.fromisoformat(pre['oldest_observed_at'])).total_seconds()
        rows.append({'role': role, 'reservation_index': index, 'slot': call.get('slot'),
                     'ledger_status': call['status'], 'observer_sha256': sha(observer_path.read_bytes()),
                     'prompt_process_launched': observer['prompt_process_launched'],
                     'accepted': observer['accepted'], 'faults': observer['faults'],
                     'account_observation_span_seconds': span,
                     'frozen_account_prelaunch_max_age_seconds': 35,
                     'known_main_usage': call.get('known_headless_main_usage')})
    return {'role': role, 'ledger_sha256': sha(ledger_path.read_bytes()),
            'reservations': len(rows), 'statuses': dict(Counter(r['ledger_status'] for r in rows)),
            'prompt_processes_launched': sum(r['prompt_process_launched'] is True for r in rows),
            'known_main_tokens': ledger['known_main_tokens'],
            'usage_incomplete': ledger['usage_incomplete'], 'calls': rows}


def main():
    assert not DEST.exists() and not RETAINED.exists()
    start = WORK / 'actual-m4m5-headless-grok130-run-r3-native-start.json'
    join = WORK / 'actual-m4m5-headless-grok130-run-r3-native-join.json'
    assert read(start)['session_id'] == read(join)['native_session_id'] == 66435
    assert read(join)['result']['exit_code'] == 0 and read(join)['source_commit'] == SOURCE_COMMIT
    closure = read(RUN / 'parent-closure.json')
    assert closure['source_and_inputs_unchanged'] is True
    assert closure['process']['process_exit_code'] == 0 and not closure['process']['timed_out']
    assert closure['process']['owned_tree_closed'] is True
    summary = read(RUN / 'summary.json')
    receipt = read(RUN / 'controller/controller-receipt.json')
    attempts = read(RUN / 'controller/controller-attempt.json')
    prep = read(PREP / 'preparation.json')
    assert prep['source_commit'] == summary['source_commit'] == SOURCE_COMMIT
    assert summary['status'] == receipt['status'] == 'inconclusive'
    assert summary['cells'] == receipt['expected_cells'] == len(attempts['cells']) == 8
    assert summary['scored_cells'] == 0 and summary['eligible_scored_cells'] == 0
    assert (receipt['successful_cells'], receipt['failed_cells'], receipt['blocked_cells']) == (0, 1, 7)
    assert summary['validation_opened'] is False and receipt['pruned_cells'] == []
    assert prep['additional_paid_api_budget'] == 0
    assert all(sha(Path(path).read_bytes()) == digest for path, digest in
               {**prep['source_pins'], **prep['input_pins']}.items())
    roles = [diagnostics('solver', RUN / 'solver-model/ledger.json'),
             diagnostics('evaluator', RAW_PRIVATE / 'evaluator-model/ledger.json')]
    assert [r['reservations'] for r in roles] == [1, 0]
    assert [r['prompt_processes_launched'] for r in roles] == [1, 0]
    assert [r['known_main_tokens'] for r in roles] == [0, 0]
    failed = [c for r in roles for c in r['calls'] if not c['accepted']]
    assert len(failed) == 1 and failed[0]['prompt_process_launched'] is True
    assert 'prompt_process_failed' in failed[0]['faults']
    assert roles[0]['usage_incomplete'] is True
    call = read(RUN / 'solver-model/ledger.json')['calls'][0]
    process_path = Path(call['private_directory']) / 'process.json'
    if not process_path.exists():
        candidates = list(Path(call['private_directory']).glob('*/process.json'))
        candidates = [p for p in candidates if read(p).get('timed_out') is True]
        assert len(candidates) == 1, 'exact timed-out process record required'
        process_path = candidates[0]
    process = read(process_path)
    assert process['timed_out'] is True and process['owned_tree_closed'] is True
    assert process['failure'] == 'process_tree_shutdown_failed'
    process_evidence = {key: process.get(key) for key in (
        'pid', 'started_at', 'finished_at', 'timeout_seconds', 'timed_out',
        'failure', 'process_exit_code', 'owned_tree_closed')}
    process_evidence['original_sha256'] = sha(process_path.read_bytes())
    cells = [{'benchmark': row['cell']['identity']['benchmark'], 'arm': row['cell']['arm_id'],
              'task_digest': row['cell']['task_digest'], 'status': row['status'],
              'phase': row.get('phase'), 'reason': row.get('reason'),
              'error_type': row.get('error_type'), 'scorer_calls': row['scorer_calls']}
             for row in attempts['cells']]
    assessment = {'schema': 'closed-m4m5-train-diagnostic-v1', 'source_commit': SOURCE_COMMIT,
        'panel_digest': receipt['panel_digest'], 'cells': cells, 'roles': roles,
        'cause': 'The first solver MAIN launched after account preflight, timed out with no accepted response, and retained a shutdown-failure record. Seven remaining cells were blocked by incomplete usage.',
        'main_process_evidence': process_evidence,
        'evidence_limits': [
            'This is execution diagnosis from retained metadata, not module-effect estimation.',
            'The frozen controller conservatively marks usage incomplete and final evidence ineligible.',
            'There were no evaluator reservations; zero known solver tokens does not establish zero consumption.',
            'The original child record retains a null exit code despite final owned-tree closure; it is not rewritten by this archive.',
            'No failed or blocked cell is removed from the eight-cell denominator.',
            'No retry, regrade, data change or validation access is performed by this archive.',
            'MAIN usage is known only as recorded; title/all-opportunity billing settlement remains unknown.'],
        'scientific_effectiveness_proven': False, 'validation_opened': False}
    spec = importlib.util.spec_from_file_location('m4m5_retention_r3', HELPER)
    retention = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(retention)
    originals = []
    for root, label in ((RUN, 'run'), (PREP, 'preparation'), (RAW_PRIVATE, 'private')):
        originals += [(label + '/' + p.relative_to(root).as_posix(), p)
                      for p in sorted(retention.regular_files(root))]
    public = {'summary.json': RUN / 'summary.json', 'controller-receipt.json': RUN / 'controller/controller-receipt.json',
              'parent-closure.json': RUN / 'parent-closure.json', 'preparation.json': PREP / 'preparation.json',
              'native-start.json': start, 'native-join.json': join,
              'driver.log': WORK / 'actual-m4m5-headless-grok130-run-r3-driver.log',
              'runner-source.py': WORK / 'run_actual_m4m5_headless_grok130_r3.py',
              'archive-helper.py': Path(__file__), 'retention-helper-source.py': HELPER}
    inputs = sorted(set([p for _, p in originals] + list(public.values())))
    before = {str(p): stamp(p) for p in inputs}
    RETAINED.mkdir(parents=True)
    zip_path = RETAINED / 'original-run-preparation-private-without-credentials.zip'
    members = retention.add_zip(zip_path, ((name, p.read_bytes(), str(p)) for name, p in originals))
    with zipfile.ZipFile(zip_path) as archive:
        assert archive.testzip() is None and archive.namelist() == [r['path'] for r in members]
        for row in members:
            raw = archive.read(row['path'])
            assert sha(raw) == row['sha256'] == before[row['origin']]['sha256']
            assert len(raw) == row['byte_count']
    assert before == {str(p): stamp(p) for p in inputs}
    retained = {'schema': 'actual-m4m5-grok130-retention-v1', 'archive_path': str(zip_path),
        'archive_sha256': sha(zip_path.read_bytes()), 'members': members,
        'excluded_credentials': retention.EXCLUSIONS, 'pruned_reparse_paths': sorted(retention.PRUNED_LINKS),
        'inputs_before': before, 'inputs_after': before}
    write(RETAINED / 'retention-manifest.json', retained)
    public['private-retention-manifest.json'] = RETAINED / 'retention-manifest.json'
    DEST.mkdir(parents=True)
    (DEST / '.gitattributes').write_bytes(b'* -text\n')
    for name, path in public.items():
        (DEST / name).write_bytes(path.read_bytes())
        assert (DEST / name).read_bytes() == path.read_bytes()
    write(DEST / 'execution-diagnosis.json', assessment)
    (DEST / 'README.md').write_bytes('''# M4/M5 Grok 1.0.30 TRAIN attempt r3

Native session 66435 and its parent process closed with exit 0; the research
result is inconclusive. One of eight frozen cells failed and seven were blocked.
No cells were scored or eligible. Both primary benchmarks remain in the
denominator; VAL was not opened, and no combination was pruned.

One solver MAIN was launched after account preflight. It timed out without a
usable completion response. The original child record reports a 60-second limit,
shutdown failure, null exit code and final owned-tree closure; those fields are
retained exactly. There were no evaluator reservations. Known MAIN usage is zero
but solver usage is incomplete, so consumption and full settlement remain unknown.
Added paid API budget remains zero. No retry or regrade is performed here.

Raw prompts, responses, account observations, intermediate artefacts, source/input
pins and controller attempts are retained privately with credentials excluded.
The public manifest contains metadata and hashes. Source/input bytes remained
unchanged. The exact runtime source is retained in the adjacent
account-freshness-runtime-checks-r1 engineering archive.

This is execution evidence, not module or interaction effectiveness, formal
calibration, or validation acceptance. Process capture/shutdown repairs belong
to a new source version and cannot retrospectively alter this result.
'''.encode())
    assert before == {str(p): stamp(p) for p in inputs}
    files = [{'path': p.name, 'sha256': sha(p.read_bytes()), 'bytes': p.stat().st_size}
             for p in sorted(DEST.iterdir())]
    write(DEST / 'published-manifest.json', {'schema': 'actual-m4m5-grok130-public-v1', 'files': files})
    print(json.dumps({'archive': str(DEST), 'public_files': len(files) + 1,
        'private_originals': len(members), 'manifest_sha256': sha((DEST / 'published-manifest.json').read_bytes())}))


if __name__ == '__main__':
    main()
