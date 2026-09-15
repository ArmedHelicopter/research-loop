"""Verify the committed controller archive, source snapshot and retained originals."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys
import zipfile

BASE = Path('E:/_ryanDev/AI/research-loop-modular')
ROOT = BASE / 'artifact-evidence-provenance'
REL = 'results/modular-engineering-20260915/headless-evaluator-controller-r1'
TARGET = ROOT / REL
def sha(raw): return hashlib.sha256(raw).hexdigest()
def read(path): return json.loads(path.read_bytes())
if '--create-manifest' in sys.argv or '--repair-manifest' in sys.argv:
    repair = '--repair-manifest' in sys.argv
    if repair:
        previous = read(TARGET / 'manifest.json')
        assert any(row['path'] == 'manifest.json' and row['bytes'] == 0
                   and row['sha256'] == sha(b'') for row in previous['files'])
        with (TARGET / 'manifest.initial-invalid.json').open('xb') as saved:
            saved.write((TARGET / 'manifest.json').read_bytes())
    body = {'schema': 'headless-evaluator-controller-archive-v1', 'manifest_self_excluded': True,
            'files': [{'path': path.name, 'bytes': path.stat().st_size, 'sha256': sha(path.read_bytes())}
                      for path in sorted(TARGET.iterdir()) if path.is_file() and path.name != 'manifest.json']}
    with (TARGET / 'manifest.json').open('w' if repair else 'x', encoding='utf-8') as stream:
        json.dump(body, stream, indent=2)
    sys.exit(0)
manifest = read(TARGET / 'manifest.json')
names = list(filter(None, subprocess.check_output(['git', 'ls-files', '-z', '--', REL], cwd=ROOT).decode().split('\0')))
assert {Path(name).name for name in names} == {row['path'] for row in manifest['files']} | {'manifest.json'}
for name in names:
    assert subprocess.check_output(['git', 'show', 'HEAD:' + name], cwd=ROOT) == (ROOT / name).read_bytes()
for row in manifest['files']:
    raw = (TARGET / row['path']).read_bytes()
    assert len(raw) == row['bytes'] and sha(raw) == row['sha256']
before, closed, sources = [read(TARGET / name) for name in ('before.json', 'closed.json', 'source-members.json')]
assert before['source_before'] == closed['source_after'] and closed['source_unchanged'] and closed['exit_code'] == 0
originals = read(TARGET / 'selected-originals.json')
for archive, rows, check_original in [('sources.zip', sources['members'], False),
                                     ('selected-synthetic-originals.zip', originals['files'], True)]:
    with zipfile.ZipFile(TARGET / archive) as saved:
        assert saved.namelist() == [row['path'] for row in rows]
        for row in rows:
            raw = saved.read(row['path'])
            assert len(raw) == row['bytes'] and sha(raw) == row['sha256']
            if check_original:
                path = Path(row['source'])
                assert sha(path.read_bytes()) == row['sha256'] and path.stat().st_mtime_ns == row['mtime_ns']
            else:
                assert before['source_before'][row['path']] == row['sha256']
result = {'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
          'git_disk_bytes_match': True, 'archive_file_count': len(names), 'junit': closed['junit'],
          'source_files': len(sources['members']), 'original_files': len(originals['files']),
          'original_bytes_mtime_unchanged': True, 'manifest_sha256': sha((TARGET / 'manifest.json').read_bytes())}
with (BASE / 'work/headless-evaluator-controller-committed-verification-r1.json').open('x', encoding='utf-8') as stream:
    json.dump(result, stream, indent=2)
print(json.dumps(result))
