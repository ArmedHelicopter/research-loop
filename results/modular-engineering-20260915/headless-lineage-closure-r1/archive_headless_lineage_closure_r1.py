"""Retain the closed lineage factory and worker gate and exact selected synthetic originals."""
from pathlib import Path
import hashlib
import json
import shutil
import zipfile

BASE = Path('E:/_ryanDev/AI/research-loop-modular')
WORK = BASE / 'work'
PREFIX = WORK / 'headless-lineage-closure-root-r1'
TARGET = BASE / 'artifact-evidence-provenance/results/modular-engineering-20260915/headless-lineage-closure-r1'

def sha(raw): return hashlib.sha256(raw).hexdigest()
def read(path): return json.loads(path.read_bytes())
def write(path, value):
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, indent=2); stream.write('\n')

closed = read(Path(str(PREFIX) + '-closed.json'))
before = read(Path(str(PREFIX) + '-before.json'))
assert closed['commit'] == '67d38e1148a9342fdb447c65c4a3eceee4fc33bb'
assert closed['exit_code'] == 0 and closed['source_unchanged']
assert before['source_before'] == closed['source_after']
assert not any(closed['junit'][key] for key in ('failures', 'errors', 'skipped'))
TARGET.mkdir(parents=True, exist_ok=False)
for suffix, name in (('-closed.json', 'closed.json'), ('-before.json', 'before.json'),
                     ('-source-members.json', 'source-members.json'), ('-sources.zip', 'sources.zip'), ('.xml', 'checks.xml')):
    original = Path(str(PREFIX) + suffix)
    shutil.copyfile(original, TARGET / name)
    assert original.read_bytes() == (TARGET / name).read_bytes()
selected = sorted(path for path in PREFIX.iterdir() if path.is_dir() and not path.is_symlink() and not path.is_junction()
                  and path.name.startswith(('test_headless_lineage', 'test_native_lineage',
                                           'test_lineage_closure', 'test_unknown_native')))
assert len(selected) == 11
rows = []
for root in selected:
    for path in sorted(root.rglob('*')):
        assert not path.is_symlink() and not path.is_junction(), path
        if path.is_file():
            stat = path.stat()
            rows.append({'source': str(path), 'path': path.relative_to(PREFIX).as_posix(),
                         'sha256': sha(path.read_bytes()), 'bytes': stat.st_size, 'mtime_ns': stat.st_mtime_ns})
archive = TARGET / 'selected-synthetic-originals.zip'
with zipfile.ZipFile(archive, 'x', zipfile.ZIP_DEFLATED) as saved:
    for row in rows: saved.writestr(row['path'], Path(row['source']).read_bytes())
with zipfile.ZipFile(archive) as saved:
    assert saved.namelist() == [row['path'] for row in rows]
    for row in rows:
        original = Path(row['source'])
        raw = saved.read(row['path'])
        assert sha(raw) == row['sha256'] == sha(original.read_bytes()) and len(raw) == row['bytes']
        assert original.stat().st_mtime_ns == row['mtime_ns']
write(TARGET / 'selected-originals.json', {
    'scope': 'Synthetic OS/HTTP responses and actual restricted Docker; no actual Grok, paid API or VAL calls.',
    'selected_roots': [root.name for root in selected], 'files': rows,
    'zip_sha256': sha(archive.read_bytes()), 'original_bytes_and_mtime_unchanged': True})
for name in ('run_frozen_checks_with_source.py', 'run_frozen_useful_checks.py', Path(__file__).name):
    shutil.copyfile(WORK / name, TARGET / name)
(TARGET / '.gitattributes').write_bytes(b'* -text\n')
write(TARGET / 'summary.json', {
    'source_commit': closed['commit'], 'junit': closed['junit'], 'wall_seconds': closed['wall_seconds'],
    'source_files_unchanged': closed['source_count'], 'selected_original_files': len(rows),
    'selected_original_roots': len(selected),
    'limits': ['No actual Grok, paid API or VAL calls.', 'Lineage factory/worker and individual scored-cell closure only.',
               'The outer lineage controller and full four-panel stdio lifecycle are not covered.',
               'Engineering checks do not establish benchmark effects or formal calibration.'],
    'preliminary_checks': 'Agent focused native/worker checks preceded this freeze and are not added to its denominator.'})
print(json.dumps({'archive': str(TARGET), 'junit': closed['junit'], 'original_files': len(rows), 'roots': len(selected)}))
