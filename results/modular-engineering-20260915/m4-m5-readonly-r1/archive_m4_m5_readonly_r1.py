"""Preserve frozen read-only regression evidence and its four original runtimes."""
import hashlib
import json
from pathlib import Path
import sys
import zipfile

BASE = Path('E:/_ryanDev/AI/research-loop-modular')
ROOT = BASE / 'artifact-evidence-provenance'
PREFIX = BASE / 'work/m4-m5-readonly-frozen-r1'
OUT = ROOT / 'results/modular-engineering-20260915/m4-m5-readonly-r1'
closed = json.loads(Path(str(PREFIX) + '-closed.json').read_bytes())
def sha(raw): return hashlib.sha256(raw).hexdigest()
for name, expected in closed['source_after'].items():
    assert sha((ROOT / name).read_bytes()) == expected
assert closed['exit_code'] == 0 and closed['source_unchanged']
assert closed['junit'] == {'tests': 33, 'failures': 0, 'errors': 0, 'skipped': 0}
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from research_loop.modular.runtime import verify_trace
OUT.mkdir(parents=True, exist_ok=False)
(OUT / '.gitattributes').write_bytes(b'* -text\n')
originals, specimens = [], []
def add(path, raw):
    with path.open('xb') as stream: stream.write(raw)
    originals.append({'file': path.name, 'sha256': sha(raw), 'bytes': len(raw)})
for suffix in ('-before.json', '-closed.json', '-source-members.json', '-sources.zip', '.xml'):
    source = Path(str(PREFIX) + suffix)
    add(OUT / source.name, source.read_bytes())
add(OUT / Path(__file__).name, Path(__file__).read_bytes())
cases = sorted(p for p in PREFIX.iterdir() if p.is_dir() and not p.is_symlink() and not p.is_junction()
               and p.name.startswith('test_actual_combination_consum'))
assert len(cases) == 4
for case in cases:
    traces = list(case.glob('*/*/trace.jsonl'))
    assert len(traces) == 1
    runtime = traces[0].parent
    def snapshot():
        return {p.relative_to(runtime).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
                for p in runtime.rglob('*') if p.is_file()}
    before = snapshot()
    verify_trace(traces[0])
    assert snapshot() == before
    target = OUT / (case.name + '.zip')
    with zipfile.ZipFile(target, 'x', zipfile.ZIP_DEFLATED) as archive:
        for name, (raw, _) in before.items(): archive.writestr('runtime/' + name, raw)
    raw = target.read_bytes()
    originals.append({'file': target.name, 'sha256': sha(raw), 'bytes': len(raw)})
    specimens.append({'file': target.name, 'original_root': str(runtime), 'files': len(before),
        'trace_and_artifact_catalogue_reverified': True, 'bytes_and_mtime_unchanged': True,
        'original_sha256': {name: sha(raw) for name, (raw, _) in before.items()}})
for row in originals:
    raw = (OUT / row['file']).read_bytes()
    assert sha(raw) == row['sha256'] and len(raw) == row['bytes']
    if row['file'].endswith('.zip'):
        with zipfile.ZipFile(OUT / row['file']) as archive: assert archive.testzip() is None
members = json.loads((OUT / (PREFIX.name + '-source-members.json')).read_bytes())
assert sha((OUT / (PREFIX.name + '-sources.zip')).read_bytes()) == members['archive_sha256']
with zipfile.ZipFile(OUT / (PREFIX.name + '-sources.zip')) as archive:
    for item in members['members']:
        raw = archive.read(item['path'])
        assert len(raw) == item['bytes'] and sha(raw) == item['sha256']
for name, expected in closed['source_after'].items():
    assert sha((ROOT / name).read_bytes()) == expected
manifest = {'schema': 'm4-m5-readonly-regression-archive-v1', 'source_commit': closed['commit'],
    'originals': originals, 'specimens': specimens, 'scope': 'read-side effects; full joint consumer checked in frozen tests',
    'synthetic_model_callbacks_in_tests': 12, 'docker_execution_calls': 0, 'new_model_service_calls': 0,
    'real_validation_access': False, 'scientific_validated': False}
(OUT / 'manifest.json').write_bytes((json.dumps(manifest, indent=2) + '\n').encode())
(OUT / 'verification.json').write_bytes((json.dumps({'status': 'verified', 'originals': len(originals),
    'specimens': len(specimens), 'callbacks_invoked_during_archive': 0, 'bytes_and_mtime_unchanged': True}) + '\n').encode())
print(json.dumps({'archive': str(OUT), 'files': len(list(OUT.iterdir())), 'specimens': len(specimens)}))
