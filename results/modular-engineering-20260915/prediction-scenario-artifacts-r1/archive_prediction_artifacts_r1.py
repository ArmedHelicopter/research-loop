"""Archive frozen prediction fixture records without rerunning producers."""
import hashlib
import json
from pathlib import Path
import sys
import zipfile

BASE = Path('E:/_ryanDev/AI/research-loop-modular')
ROOT = BASE / 'artifact-evidence-provenance'
PREFIX = BASE / 'work/prediction-artifacts-root-r3'
OUT = ROOT / 'results/modular-engineering-20260915/prediction-scenario-artifacts-r1'
closed = json.loads(Path(str(PREFIX) + '-closed.json').read_bytes())

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def sources_unchanged():
    for name, expected in closed['source_after'].items():
        assert sha((ROOT / name).read_bytes()) == expected, name

sources_unchanged()
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from research_loop.modular.prediction_scenario_artifacts import verify_prediction_scenario_artifacts
from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask
from research_loop.ontology import ContractError
from tests.test_modular_prediction_scenarios import public_task, controls

assert closed['source_unchanged'] and closed['exit_code'] == 0
assert closed['junit'] == {'tests': 66, 'failures': 0, 'errors': 0, 'skipped': 0}
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
    with target.open('xb') as stream:
        stream.write(path.read_bytes())
    register(target)

for prefix in (BASE / 'work/prediction-artifacts-final', BASE / 'work/prediction-artifacts-root-r2', PREFIX):
    metadata = json.loads(Path(str(prefix) + '-source-members.json').read_bytes())
    source_zip = Path(str(prefix) + '-sources.zip')
    assert sha(source_zip.read_bytes()) == metadata['archive_sha256']
    with zipfile.ZipFile(source_zip) as archive:
        assert archive.testzip() is None
        for row in metadata['members']:
            raw = archive.read(row['path'])
            assert len(raw) == row['bytes'] and sha(raw) == row['sha256']
    for suffix in ('-source-members.json', '-sources.zip', '-before.json', '-closed.json', '.xml'):
        original(Path(str(prefix) + suffix))
for name in ('review.py', 'report.json'):
    original(BASE / 'work/prediction-artifact-independent-781e5c7c' / name, 'independent-v1-' + name)
original(Path(__file__))

def tree(root):
    result = {}
    for path in root.rglob('*'):
        assert not path.is_symlink() and not path.is_junction(), path
        if path.is_file():
            result[path.relative_to(root).as_posix()] = (path.read_bytes(), path.stat().st_mtime_ns)
    return result

def specimen(root, data, *, name, input_path=None, attack=False, expected=None):
    task = PublicTask(DataIdentity.parse(data['task']['identity']), FrozenRecord.from_dict(data['task']['payload']))
    frozen = FrozenRecord.from_dict(data['controls'])
    before = tree(root)
    try:
        check = verify_prediction_scenario_artifacts(root, task=task, controls=frozen,
            experiment_id=data['experiment_id'], variant=data['variant'], complete=False).data()
        status = 'verified_completed_fixture' if check['status'] == 'succeeded' else 'verified_failed_prefix'
    except ContractError:
        check, status = None, 'nonaccepted_retained_bytes'
    if attack:
        assert status == 'nonaccepted_retained_bytes', name
    if expected:
        assert status == expected, (name, status)
    assert tree(root) == before
    target = OUT / (name + '.zip')
    with zipfile.ZipFile(target, 'x', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('independent-inputs.json', (FrozenRecord.from_dict(data).encoded + '\n').encode())
        if input_path is not None:
            archive.writestr('original-control/' + input_path.name, input_path.read_bytes())
        for relative, (raw, _) in before.items():
            archive.writestr('runtime/' + relative, raw)
    register(target)
    specimens.append({'file': target.name, 'original_root': str(root), 'status': status, 'attack': attack,
        'verification': check, 'original_control': str(input_path) if input_path else 'caller definition in frozen tests',
        'experiment_id': data['experiment_id'], 'variant': data['variant'], 'benchmark': task.identity.benchmark,
        'original_files': len(before), 'original_sha256': {name: sha(raw) for name, (raw, _) in before.items()},
        'bytes_and_mtime_unchanged_after_read': True})

cases = sorted(p for p in PREFIX.iterdir() if p.is_dir() and not p.is_symlink() and not p.is_junction())
for case in cases:
    for input_path in sorted(case.glob('*-independent-inputs.json')):
        root = case / input_path.name.removesuffix('-independent-inputs.json')
        if root.is_dir():
            specimen(root, json.loads(input_path.read_bytes()), name=case.name + '-' + root.name,
                     input_path=input_path, expected='verified_completed_fixture')
    input_path = case / 'independent-inputs.json'
    if input_path.is_file():
        data = json.loads(input_path.read_bytes())
        for child in ('original', 'attack'):
            root = case / child
            if root.is_dir():
                specimen(root, data, name=case.name + '-' + child, input_path=input_path,
                         attack=child == 'attack', expected='verified_completed_fixture' if child == 'original' else None)
    for prefix, child, adapter, experiment, variant, status in (
        ('test_callback_failure_is_durab', 'failed', 'discovery', 'Q3.1', 'mechanism', 'verified_failed_prefix'),
        ('test_invalid_callback_value_su', 'invalid', 'discovery', 'Q3.1', 'mechanism', 'verified_failed_prefix'),
        ('test_post_callback_mechanism_f', 'late-failure', 'blade', 'Q3.2', 'separate', 'verified_failed_prefix'),
        ('test_partial_write_is_retaine', 'partial', 'blade', 'Q3.2', 'separate', 'nonaccepted_retained_bytes')):
        if case.name.startswith(prefix) and (case / child).is_dir():
            task = public_task(adapter)
            data = {'task': task.data(), 'controls': controls(task).data(), 'experiment_id': experiment, 'variant': variant}
            specimen(case / child, data, name=case.name + '-' + child, expected=status)

counts = {s: sum(x['status'] == s for x in specimens) for s in
          ('verified_completed_fixture', 'verified_failed_prefix', 'nonaccepted_retained_bytes')}
matrix = {(s['experiment_id'], s['variant'], s['benchmark']) for s in specimens if
          s['status'] == 'verified_completed_fixture' and s['file'].startswith('test_registered_variants_')}
assert len(matrix) == 24, len(matrix)
assert sum(s['attack'] for s in specimens) == 15
assert counts['verified_failed_prefix'] == 5
assert counts['nonaccepted_retained_bytes'] == 16
for row in originals:
    raw = (OUT / row['file']).read_bytes()
    assert sha(raw) == row['sha256'] and len(raw) == row['bytes']
    if row['file'].endswith('.zip'):
        with zipfile.ZipFile(OUT / row['file']) as archive:
            assert archive.testzip() is None
sources_unchanged()
write(OUT / 'manifest.json', {'schema': 'prediction-fixture-artifact-archive-v1', 'source_commit': closed['commit'],
    'originals': originals, 'specimens': specimens, 'counts': counts, 'matrix_cells': len(matrix),
    'new_model_or_docker_calls': 0, 'validation_access': False, 'scientific_validated': False,
    'limitations': ['original source paths required', 'failed prefixes prove stored mechanism history, not external failure cause',
                    'no external model response attestation or complete historical environment replay']})
write(OUT / 'verification.json', {'status': 'verified', 'specimens': len(specimens), 'counts': counts,
    'originals': len(originals), 'complete_matrix_cells': len(matrix), 'bytes_and_mtime_unchanged': True,
    'user_callbacks_invoked': 0, 'scientific_validated': False})
print(json.dumps({'archive': str(OUT), 'specimens': len(specimens), 'counts': counts, 'originals': len(originals)}))
