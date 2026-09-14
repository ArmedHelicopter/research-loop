"""Archive actual frozen Q3.2 specimens without rerunning any producer/port."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import zipfile

BASE = Path('E:/_ryanDev/AI/research-loop-modular')
ROOT = BASE/'artifact-evidence-provenance'
PREFIX = Path(sys.argv[1])
OUT = ROOT/'results/modular-engineering-20260915/q32-execution-artifacts-r1'
sys.path[:0] = [str(ROOT), str(ROOT/'tests')]
closed = json.loads(Path(str(PREFIX)+'-closed.json').read_bytes())
def checked_reader_sources():
    for name, expected_sha in closed['source_after'].items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest() == expected_sha, name
checked_reader_sources()
from evaluation.modular.q32_execution_verifier import verify_q32_execution
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.q32_artifacts import CLOSURE, inventory, verify_q32_artifacts
from research_loop.ontology import ContractError

R = FrozenRecord.from_dict
def sha(raw): return hashlib.sha256(raw).hexdigest()
def write(path, value):
    with path.open('xb') as stream: stream.write((json.dumps(value, indent=2)+'\n').encode())
def tree(root):
    found = {}
    for path in root.rglob('*'):
        assert not path.is_symlink() and not path.is_junction(), path
        if path.is_file(): found[path.relative_to(root).as_posix()] = path.read_bytes()
    return found

assert closed['exit_code'] == 0 and closed['source_unchanged']
assert closed['junit']['tests'] >= 51
assert all(closed['junit'][key] == 0 for key in ('failures', 'errors', 'skipped'))
OUT.mkdir(parents=True, exist_ok=False)
(OUT/'.gitattributes').write_bytes(b'* -text\n')
originals, specimens = [], []
def original(path, name=None):
    raw = path.read_bytes(); name = name or path.name
    (OUT/name).write_bytes(raw)
    originals.append({'file': name, 'bytes': len(raw), 'sha256': sha(raw)})
for prefix in (BASE/'work/q32-artifacts-frozen-r1', PREFIX):
    metadata = json.loads(Path(str(prefix)+'-source-members.json').read_bytes())
    archive_path = Path(str(prefix)+'-sources.zip')
    assert sha(archive_path.read_bytes()) == metadata['archive_sha256']
    with zipfile.ZipFile(archive_path) as archive:
        assert archive.testzip() is None
        for row in metadata['members']:
            raw = archive.read(row['path'])
            assert len(raw) == row['bytes'] and sha(raw) == row['sha256']
    for suffix in ('-before.json', '-closed.json', '.xml', '-sources.zip', '-source-members.json', '-accounting.json'):
        original(Path(str(prefix)+suffix))
original(Path(__file__))
original(BASE/'work/q32-artifact-independent-review-r1.md')
original(BASE/'work/q32-artifact-local-probe-r1.py')
original(BASE/'work/count_q32_frozen_execution_r1.py')
original(BASE/'work/q32-artifact-local-probe-r1/outcome.json', 'non-frozen-local-probe-outcome.json')

def specimen(root, compiled, cell, *, name, control_path, expected=None, attack=False):
    before = tree(root)
    status = None
    final = None
    try:
        verified = verify_q32_execution(root/'trace.jsonl', compiled, cell=cell).data()
        final = json.loads((root/'result.json').read_bytes())
        status = ('verified_completed_allocation' if final['failure'] is None
            and final['model_attempts'] == 4 and final['execution_attempts'] == 3
            and all(row['status'] != 'blocked' for row in final['rows']) else 'verified_failure_envelope')
    except ContractError:
        verified = None
        try:
            verify_q32_artifacts(root, compiled, cell=cell, complete=False)
            status = 'prefix_only'
        except ContractError:
            status = 'nonaccepted_retained_bytes'
    if attack: assert status not in {'verified_completed_allocation', 'verified_failure_envelope'}, name
    assert tree(root) == before
    archive_path = OUT/(name+'.zip')
    with zipfile.ZipFile(archive_path, 'x', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('independent-input.json', R({'compiled': compiled.data(), 'cell': cell,
            'source': expected or 'compiled.json written by panel before stage production'}).encoded.encode())
        archive.writestr('original-control/'+control_path.name, control_path.read_bytes())
        for relative, raw in sorted(before.items()): archive.writestr('runtime/'+relative, raw)
    original_bytes = archive_path.read_bytes()
    originals.append({'file': archive_path.name, 'bytes': len(original_bytes), 'sha256': sha(original_bytes)})
    specimens.append({'file': archive_path.name, 'original_root': str(root), 'status': status,
        'attack': attack, 'original_files': len(before), 'verification': verified,
        'original_control_path': str(control_path), 'original_control_sha256': sha(control_path.read_bytes()),
        'failure': None if final is None else final['failure'],
        'measurement_statuses': None if final is None else [row['status'] for row in final['rows']],
        'unchanged_after_read': True, 'original_sha256': {name: sha(raw) for name, raw in sorted(before.items())}})

cases = sorted(path for path in PREFIX.iterdir() if path.is_dir() and not path.is_symlink() and not path.is_junction())
for case in cases:
    independent = case/'independent-inputs.json'
    if independent.is_file() and not case.name.startswith('test_linked_original'):
        data = json.loads(independent.read_bytes()); compiled = R(data['compiled']); cell = data['cell']
        for name in ('original', 'attack'):
            if (case/name).is_dir(): specimen(case/name, compiled, cell,
                name=case.name+'-'+name, control_path=independent, expected=data, attack=name=='attack')
    if case.name.startswith(('test_actual_four_cell_grid_', 'test_native_q32_prospective_', 'test_actual_native_artifact_')):
        run = case/'run'
        if not (run/'compiled.json').is_file(): continue
        compiled = R(json.loads((run/'compiled.json').read_bytes()))
        for i, cell in enumerate(compiled.data()['cells']):
            root = run/str(i)/'runtime'
            if not root.is_dir(): root = run/str(i)
            if not (root/'trace.jsonl').is_file(): continue
            specimen(root, compiled, cell, name=case.name+'-cell-'+str(i), control_path=run/'compiled.json')
        for name in ('panel-result.json', 'source-attempt.json'):
            if (run/name).is_file(): original(run/name, case.name+'-'+name)

# Preserve one original failing r1 example as bytes under its own exact source
# archive; current source verification must not rewrite its historical meaning.
old = BASE/'work/q32-artifacts-frozen-r1/test_exact_file_drift_is_rejec0'
with zipfile.ZipFile(OUT/'original-failed-r1-example.zip', 'x', zipfile.ZIP_DEFLATED) as archive:
    for relative, raw in sorted(tree(old/'original').items()): archive.writestr('runtime/'+relative, raw)
    archive.writestr('independent-inputs.json', (old/'independent-inputs.json').read_bytes())
raw = (OUT/'original-failed-r1-example.zip').read_bytes()
originals.append({'file': 'original-failed-r1-example.zip', 'bytes': len(raw), 'sha256': sha(raw)})
counts = {status: sum(row['status'] == status for row in specimens) for status in
          ('verified_completed_allocation', 'verified_failure_envelope', 'prefix_only', 'nonaccepted_retained_bytes')}
assert counts['verified_completed_allocation'] >= 8 and counts['nonaccepted_retained_bytes'] >= 8
for row in originals:
    raw = (OUT/row['file']).read_bytes()
    assert sha(raw) == row['sha256'] and len(raw) == row['bytes']
    if row['file'].endswith('.zip'):
        with zipfile.ZipFile(OUT/row['file']) as archive: assert archive.testzip() is None
write(OUT/'manifest.json', {'schema': 'q32-runtime-artifact-archive-v1', 'source_commit': closed['commit'],
    'originals': originals, 'specimens': specimens, 'counts': counts,
    'scope': 'runtime producer-consumer artifacts only; not full relocated native provider/environment replay',
    'new_model_calls': 0, 'new_docker_calls': 0, 'validation_access': False,
    'prior_failed_run_retained': True})
write(OUT/'verification.json', {'status': 'verified', 'specimens': len(specimens), 'counts': counts,
    'originals': len(originals), 'original_bytes_unchanged_after_read': True,
    'callbacks_replayed': False, 'scientific_validated': False})
checked_reader_sources()
print(json.dumps({'archive': str(OUT), 'originals': len(originals), 'specimens': len(specimens), 'counts': counts}))
