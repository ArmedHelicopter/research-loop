"""Archive original frozen review records, without rerunning their producers."""
import hashlib
import json
import sys
import zipfile
from pathlib import Path

BASE = Path('E:/_ryanDev/AI/research-loop-modular')
ROOT = BASE / 'artifact-evidence-provenance'
PREFIX = BASE / 'work/review-artifacts-root-r2'
OUT = ROOT / 'results/modular-engineering-20260915/review-scenario-artifacts-r1'
closed = json.loads(Path(str(PREFIX) + '-closed.json').read_bytes())

def sha(raw): return hashlib.sha256(raw).hexdigest()
def unchanged():
    for name, expected in closed['source_after'].items():
        assert sha((ROOT / name).read_bytes()) == expected, name

assert closed['exit_code'] == 0 and closed['source_unchanged']
assert closed['junit'] == {'tests': 135, 'failures': 0, 'errors': 0, 'skipped': 0}
unchanged()
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from research_loop.modular.review_scenario_artifacts import verify_review_artifacts
from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask
from research_loop.ontology import ContractError
from test_modular_review_scenarios import task, controls

OUT.mkdir(parents=True, exist_ok=False)
(OUT / '.gitattributes').write_bytes(b'* -text\n')
originals, specimens = [], []

def write(path, body):
    with path.open('xb') as stream:
        stream.write((json.dumps(body, indent=2) + '\n').encode())

def register(path):
    raw = path.read_bytes()
    originals.append({'file': path.name, 'sha256': sha(raw), 'bytes': len(raw)})

def original(path, name=None):
    target = OUT / (name or path.name)
    with target.open('xb') as stream: stream.write(path.read_bytes())
    register(target)

for prefix, finished in ((BASE / 'work/review-scenario-artifacts/final-frozen', True),
                         (BASE / 'work/review-scenario-artifacts/final-label-frozen', True),
                         (BASE / 'work/review-scenario-artifacts/preedit-relevant', True),
                         (BASE / 'work/review-exact-v3-frozen', True),
                         (BASE / 'work/review-exact-parents-v3-frozen', True),
                         (BASE / 'work/review-artifacts-root-r1', False), (PREFIX, True)):
    metadata = json.loads(Path(str(prefix) + '-source-members.json').read_bytes())
    source_zip = Path(str(prefix) + '-sources.zip')
    assert sha(source_zip.read_bytes()) == metadata['archive_sha256']
    with zipfile.ZipFile(source_zip) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist()) == {row['path'] for row in metadata['members']}
        for row in metadata['members']:
            raw = archive.read(row['path'])
            assert len(raw) == row['bytes'] and sha(raw) == row['sha256']
    suffixes = ['-source-members.json', '-sources.zip', '-before.json']
    suffixes += ['-closed.json', '.xml'] if finished else ['-INTERRUPTED.md']
    for suffix in suffixes: original(Path(str(prefix) + suffix))
for name in ('review.py', 'report.json'):
    original(BASE / 'work/review-artifact-independent-f2d5c74b' / name, 'independent-v2-' + name)
original(Path(__file__))

def tree(root):
    result = {}
    for path in root.rglob('*'):
        assert not path.is_symlink() and not path.is_junction(), path
        if path.is_file():
            result[path.relative_to(root).as_posix()] = (path.read_bytes(), path.stat().st_mtime_ns)
    return result

historical = []
old = BASE / 'work/review-artifact-independent-f2d5c74b'
for name in ('source-snapshot', 'baseline', 'attacks', 'failures', 'bad_callback_raw',
             'm4-positive', 'post_callback_failure', 'producer_returns_corrupt_artifact'):
    before = tree(old / name)
    if name == 'source-snapshot':
        before = {key: value for key, value in before.items()
                  if Path(key).suffix in ('.py', '.md') and not key.startswith(('results/', '.git/'))}
    target = OUT / ('independent-v2-' + name + '.zip')
    with zipfile.ZipFile(target, 'x', zipfile.ZIP_DEFLATED) as archive:
        for key, (raw, _) in before.items(): archive.writestr(key, raw)
    after = tree(old / name)
    assert all(after[key] == value for key, value in before.items())
    register(target)
    historical.append({'file': target.name, 'original_root': str(old / name),
        'scope': 'retained historical bytes; not reevaluated with the current reader',
        'members': [{'path': key, 'bytes': len(raw), 'sha256': sha(raw)} for key, (raw, _) in before.items()]})

def inputs(experiment='Q4.3', variant='sequential', *, identities=None, external=None):
    public = task('blade')
    return {'task': public.data(), 'controls': controls(public).data(), 'experiment_id': experiment,
            'variant': variant, 'reviewer_identities': identities, 'review_log_path': str(external) if external else None}

def specimen(root, data, *, name, expected, control=None, modification=False):
    public = PublicTask(DataIdentity.parse(data['task']['identity']), FrozenRecord.from_dict(data['task']['payload']))
    before = tree(root)
    try:
        check = verify_review_artifacts(root, task=public, controls=FrozenRecord.from_dict(data['controls']),
            experiment_id=data['experiment_id'], variant=data['variant'],
            reviewer_identities=data['reviewer_identities'], review_log_path=data['review_log_path']).data()
        status = 'verified_completed_fixture' if check['status'] == 'succeeded' else 'verified_failed_prefix'
    except ContractError:
        check, status = None, 'nonaccepted_retained_bytes'
    assert status == expected, (name, status, expected)
    assert tree(root) == before, name
    target = OUT / (name + '.zip')
    with zipfile.ZipFile(target, 'x', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('independent-inputs.json', (FrozenRecord.from_dict(data).encoded + '\n').encode())
        if control is not None: archive.writestr('original-control/' + control.name, control.read_bytes())
        for relative, (raw, _) in before.items(): archive.writestr('runtime/' + relative, raw)
    register(target)
    specimens.append({'file': target.name, 'original_root': str(root), 'status': status,
        'verification': check, 'coherent_modification': modification,
        'original_control': str(control) if control else 'independent caller definition in frozen tests',
        'experiment_id': data['experiment_id'], 'variant': data['variant'], 'benchmark': public.identity.benchmark,
        'original_files': len(before), 'original_sha256': {key: sha(raw) for key, (raw, _) in before.items()},
        'bytes_and_mtime_unchanged_after_read': True})
    print(json.dumps({'specimen': name, 'status': status}), flush=True)

OK = 'verified_completed_fixture'
FAIL = 'verified_failed_prefix'
NO = 'nonaccepted_retained_bytes'
cases = sorted(p for p in PREFIX.iterdir() if p.is_dir() and not p.is_symlink() and not p.is_junction())
for case in cases:
    control = case / 'independent-inputs.json'
    if control.is_file():
        data = json.loads(control.read_bytes())
        for child in ('review', 'original', 'copied'):
            if (case / child).is_dir():
                specimen(case / child, data, name=case.name + '-' + child,
                    expected=NO if child == 'copied' else OK, control=control, modification=child == 'copied')
        continue
    if case.name.startswith('test_actual_m4_freeze_payload_') or case.name.startswith('test_m4_event_and_actual_froze'):
        for child in ('original', 'copied'):
            specimen(case / child, inputs('Q4.1', 'roles'), name=case.name + '-' + child,
                expected=OK if child == 'original' else NO, modification=child == 'copied')
    elif case.name.startswith('test_raw_values_survive_failed'):
        specimen(case / 'failed', inputs('Q4.1', 'single'), name=case.name, expected=FAIL)
    elif case.name.startswith('test_late_oracle_failure_has_c'):
        specimen(case / 'failed', inputs(), name=case.name, expected=FAIL)
    elif case.name.startswith('test_consumer_only_reads_archi'):
        for child in ('original', 'copy'):
            specimen(case / child, inputs(external=case / 'external.jsonl'), name=case.name + '-' + child, expected=OK)
    elif case.name.startswith('test_partial_output_write_is_p'):
        specimen(case / 'partial', inputs('Q4.1', 'single'), name=case.name, expected=NO)
    elif case.name.startswith('test_partial_journal_append_is'):
        specimen(case / 'partial-journal', inputs('Q4.1', 'single'), name=case.name, expected=NO)
    elif case.name.startswith('test_actual_runner_requires_co'):
        specimen(case / 'rejected', inputs('Q4.1', 'single'), name=case.name, expected=NO)
    elif case.name.startswith('test_consumed_record_parents_a'):
        specimen(case / 'original', inputs(), name=case.name + '-original', expected=OK)
        for number in range(7):
            specimen(case / f'copy-{number}', inputs(), name=case.name + f'-copy-{number}', expected=NO, modification=True)
    elif case.name.startswith('test_reveal_revision_and_m4_re'):
        specimen(case / 'sequential', inputs(), name=case.name + '-sequential', expected=OK)
        specimen(case / 'prediction', inputs('Q4.1', 'roles'), name=case.name + '-prediction', expected=OK)
        for number in range(3):
            specimen(case / f'prediction-copy-{number}', inputs('Q4.1', 'roles'),
                name=case.name + f'-prediction-copy-{number}', expected=NO, modification=True)

counts = {status: sum(row['status'] == status for row in specimens) for status in (OK, FAIL, NO)}
matrix = {(row['experiment_id'], row['variant'], row['benchmark']) for row in specimens
          if row['file'].startswith('test_every_registered_variant_') and row['status'] == OK}
assert len(matrix) == 30
assert sum(row['coherent_modification'] for row in specimens) == 30
assert counts[FAIL] == 5 and counts[NO] == 33
for row in originals:
    raw = (OUT / row['file']).read_bytes()
    assert len(raw) == row['bytes'] and sha(raw) == row['sha256']
    if row['file'].endswith('.zip'):
        with zipfile.ZipFile(OUT / row['file']) as archive: assert archive.testzip() is None
unchanged()
write(OUT / 'manifest.json', {'schema': 'review-fixture-artifact-archive-v1', 'source_commit': closed['commit'],
    'originals': originals, 'specimens': specimens, 'historical': historical, 'counts': counts, 'matrix_cells': len(matrix),
    'new_model_or_docker_calls': 0, 'validation_access': False, 'scientific_validated': False,
    'limitations': ['same original source paths and bytes required', 'repeated fixture directories are not independent scientific samples',
                   'failed prefixes do not attest external exception cause', 'no external model authorship or complete historical environment attestation']})
write(OUT / 'verification.json', {'status': 'verified', 'originals': len(originals), 'specimens': len(specimens),
    'counts': counts, 'matrix_cells': len(matrix), 'coherent_modified_copies': 30,
    'user_callbacks_invoked': 0, 'bytes_and_mtime_unchanged': True, 'scientific_validated': False})
print(json.dumps({'archive': str(OUT), 'originals': len(originals), 'specimens': len(specimens), 'counts': counts}))
