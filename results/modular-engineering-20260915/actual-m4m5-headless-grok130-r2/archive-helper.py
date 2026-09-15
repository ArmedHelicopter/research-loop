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
RUN = WORK / 'actual-m4m5-headless-grok130-run-r2'
PREP = WORK / 'actual-m4m5-headless-grok130-preparation-r2'
RAW_PRIVATE = BASE / 'custody-private/actual-m4m5-headless-grok130-r2'
DEST = BASE / 'artifact-evidence-provenance/results/modular-engineering-20260915/actual-m4m5-headless-grok130-r2'
RETAINED = BASE / 'retained-private-evidence/actual-m4m5-headless-grok130-r2'
HELPER = WORK / 'prepare_headless_lineage_full4_archive_r1.py'
SOURCE_COMMIT = '6ec1a7205680e8f21a0da1e826ea696aff0f1333'


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
                     'snapshot_already_older_than_frozen_5s_guard': span is not None and span > 5,
                     'known_main_usage': call.get('known_headless_main_usage')})
    return {'role': role, 'ledger_sha256': sha(ledger_path.read_bytes()),
            'reservations': len(rows), 'statuses': dict(Counter(r['ledger_status'] for r in rows)),
            'prompt_processes_launched': sum(r['prompt_process_launched'] is True for r in rows),
            'known_main_tokens': ledger['known_main_tokens'],
            'usage_incomplete': ledger['usage_incomplete'], 'calls': rows}


def main():
    assert not DEST.exists() and not RETAINED.exists()
    start = WORK / 'actual-m4m5-headless-grok130-run-r2-native-start.json'
    join = WORK / 'actual-m4m5-headless-grok130-run-r2-native-join.json'
    assert read(start)['session_id'] == read(join)['native_session_id'] == 90559
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
    assert summary['scored_cells'] == 1 and summary['eligible_scored_cells'] == 0
    assert (receipt['successful_cells'], receipt['failed_cells'], receipt['blocked_cells']) == (1, 3, 4)
    assert summary['validation_opened'] is False and receipt['pruned_cells'] == []
    assert prep['additional_paid_api_budget'] == 0
    assert all(sha(Path(path).read_bytes()) == digest for path, digest in
               {**prep['source_pins'], **prep['input_pins']}.items())
    roles = [diagnostics('solver', RUN / 'solver-model/ledger.json'),
             diagnostics('evaluator', RAW_PRIVATE / 'evaluator-model/ledger.json')]
    assert [r['reservations'] for r in roles] == [17, 2]
    assert [r['prompt_processes_launched'] for r in roles] == [16, 1]
    assert [r['known_main_tokens'] for r in roles] == [107041, 5081]
    failed = [c for r in roles for c in r['calls'] if not c['accepted']]
    assert len(failed) == 2 and all(c['faults'] == ['prelaunch_guard_failed'] and
        c['prompt_process_launched'] is False and c['snapshot_already_older_than_frozen_5s_guard'] for c in failed)
    cells = [{'benchmark': row['cell']['identity']['benchmark'], 'arm': row['cell']['arm_id'],
              'task_digest': row['cell']['task_digest'], 'status': row['status'],
              'phase': row.get('phase'), 'reason': row.get('reason'),
              'error_type': row.get('error_type'), 'scorer_calls': row['scorer_calls']}
             for row in attempts['cells']]
    assessment = {'schema': 'closed-m4m5-train-diagnostic-v1', 'source_commit': SOURCE_COMMIT,
        'panel_digest': receipt['panel_digest'], 'cells': cells, 'roles': roles,
        'cause': 'Two retained account observations already exceed the frozen 5-second oldest-observation guard before prompt launch.',
        'evidence_limits': [
            'This is execution diagnosis from retained metadata, not module-effect estimation.',
            'The frozen controller conservatively marks usage incomplete and final evidence ineligible.',
            'A third scorer submission did not create a third evaluator reservation.',
            'No failed or blocked cell is removed from the eight-cell denominator.',
            'No retry, regrade, data change or validation access is performed by this archive.',
            'MAIN usage is known only as recorded; title/all-opportunity billing settlement remains unknown.'],
        'scientific_effectiveness_proven': False, 'validation_opened': False}
    spec = importlib.util.spec_from_file_location('m4m5_retention_r2', HELPER)
    retention = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(retention)
    originals = []
    for root, label in ((RUN, 'run'), (PREP, 'preparation'), (RAW_PRIVATE, 'private')):
        originals += [(label + '/' + p.relative_to(root).as_posix(), p)
                      for p in sorted(retention.regular_files(root))]
    public = {'summary.json': RUN / 'summary.json', 'controller-receipt.json': RUN / 'controller/controller-receipt.json',
              'parent-closure.json': RUN / 'parent-closure.json', 'preparation.json': PREP / 'preparation.json',
              'native-start.json': start, 'native-join.json': join,
              'driver.log': WORK / 'actual-m4m5-headless-grok130-run-r2-driver.log',
              'runner-source.py': WORK / 'run_actual_m4m5_headless_grok130_r2.py',
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
    (DEST / 'README.md').write_bytes('''# M4/M5 Grok 1.0.30 TRAIN attempt r2

Native session 90559 and its owned child tree closed with exit 0; the research
result is inconclusive. Of eight frozen cells, one scored, three failed, and
four were blocked by incomplete usage state. Final eligible scored cells: zero.
Both primary benchmarks remain in the denominator; VAL was not opened.

There were 17 solver reservations (16 MAIN launches) and two evaluator reservations
(one MAIN launch). Known MAIN usage: 107,041 solver and 5,081 evaluator tokens.
The unlaunched failed reservations retain their original conservative incomplete
ledger states. Title/all-opportunity settlement is unknown; paid API budget is zero.

The retained evaluator and solver failures both occurred before model launch:
three sequential account GET observations took longer than the frozen five-second
freshness guard permits. Source/input pins remained unchanged. The original batch
is not repaired or regraded; any runtime repair applies only to a new frozen run.

Raw prompts, responses, account observations, all intermediate artefacts and
controller attempts are retained privately, with credentials excluded. The public
manifest exposes metadata and hashes. The exact runtime source is also retained in
the adjacent grok130-evaluator-and-root-checks-r1 engineering archive. No module
benefit, interaction effect, formal calibration, or validation acceptance is claimed.
'''.encode())
    assert before == {str(p): stamp(p) for p in inputs}
    files = [{'path': p.name, 'sha256': sha(p.read_bytes()), 'bytes': p.stat().st_size}
             for p in sorted(DEST.iterdir())]
    write(DEST / 'published-manifest.json', {'schema': 'actual-m4m5-grok130-public-v1', 'files': files})
    print(json.dumps({'archive': str(DEST), 'public_files': len(files) + 1,
        'private_originals': len(members), 'manifest_sha256': sha((DEST / 'published-manifest.json').read_bytes())}))


if __name__ == '__main__':
    main()
