"""Archive the closed source-frozen TRAIN provider gate and selected synthetic originals."""
from pathlib import Path
import hashlib
import json
import shutil
import zipfile

BASE = Path('E:/_ryanDev/AI/research-loop-modular')
WORK = BASE / 'work'
PREFIX = WORK / 'headless-train-provider-root-r1'
STAGE = WORK / 'headless-train-provider-archive-stage-r1'

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def read(path):
    return json.loads(path.read_bytes())

def write(path, body):
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(body, stream, indent=2)
        stream.write('\n')

closed = read(Path(str(PREFIX) + '-closed.json'))
before = read(Path(str(PREFIX) + '-before.json'))
members = read(Path(str(PREFIX) + '-source-members.json'))
assert closed['exit_code'] == 0 and closed['source_unchanged']
assert not any(closed['junit'][k] for k in ('errors', 'failures', 'skipped'))
assert before['commit'] == closed['commit'] == members['commit'] == '4c096f4fa65be10beb3b1dc95fefc64c0f5410ff'
assert before['source_before'] == closed['source_after']
STAGE.mkdir(exist_ok=False)
copies = []
for suffix, name in (('-before.json', 'before.json'), ('-closed.json', 'closed.json'),
                     ('-source-members.json', 'source-members.json'), ('-sources.zip', 'sources.zip'),
                     ('.xml', 'checks.xml')):
    source = Path(str(PREFIX) + suffix)
    shutil.copyfile(source, STAGE / name)
    assert sha(source.read_bytes()) == sha((STAGE / name).read_bytes())
    copies.append({'source': str(source), 'path': name, 'sha256': sha(source.read_bytes())})

# Full roots include both successful and rejected/tampered synthetic operations.
# Ignore pytest's "current" links, never follow arbitrary linked directories.
selected_names = (
    'test_complete_headless_factori0', 'test_complete_headless_factori1',
    'test_headless_synthetic_os_htt0', 'test_postflight_failure_retain0',
    'test_postflight_rejection_is_r0', 'test_unknown_main_usage_keeps_0',
    'test_malformed_original_keeps_0', 'test_malformed_original_keeps_1',
)
rows = []
for name in selected_names:
    directory = PREFIX / name
    assert directory.is_dir() and not directory.is_symlink(), name
    for path in sorted(directory.rglob('*')):
        assert not path.is_symlink(), path
        if path.is_file():
            stat = path.stat()
            rows.append({'path': path.relative_to(PREFIX).as_posix(), 'source': str(path),
                         'sha256': sha(path.read_bytes()), 'bytes': stat.st_size,
                         'mtime_ns': stat.st_mtime_ns})

archive = STAGE / 'selected-synthetic-originals.zip'
with zipfile.ZipFile(archive, 'x', zipfile.ZIP_DEFLATED) as output:
    for row in rows:
        output.writestr(row['path'], Path(row['source']).read_bytes())
with zipfile.ZipFile(archive) as saved:
    assert saved.namelist() == [r['path'] for r in rows]
    for row in rows:
        path = Path(row['source'])
        raw = saved.read(row['path'])
        assert len(raw) == row['bytes'] and sha(raw) == row['sha256'] == sha(path.read_bytes())
        assert path.stat().st_mtime_ns == row['mtime_ns']
write(STAGE / 'selected-originals.json', {
    'schema': 'headless-train-selected-synthetic-originals-v1', 'selected_roots': list(selected_names),
    'file_count': len(rows), 'originals_byte_and_mtime_unchanged': True,
    'zip_sha256': sha(archive.read_bytes()), 'files': rows,
    'scope': 'Synthetic local OS/HTTP peers and actual restricted Docker/RPC. Fixture credentials are synthetic. No real model or VAL data.',
})
shutil.copyfile(__file__, STAGE / Path(__file__).name)
for name in ('run_frozen_checks_with_source.py', 'run_frozen_useful_checks.py'):
    shutil.copyfile(WORK / name, STAGE / name)
write(STAGE / 'archive-summary.json', {
    'schema': 'headless-train-provider-engineering-archive-v1', 'source_commit': closed['commit'],
    'junit': closed['junit'], 'wall_seconds': closed['wall_seconds'],
    'source_files_unchanged': closed['source_count'], 'source_archive_sha256': members['archive_sha256'],
    'copied_gate_originals': copies, 'selected_synthetic_roots': len(selected_names),
    'selected_original_files': len(rows), 'new_paid_calls': 0, 'actual_model_calls': 0,
    'validation_opened': False, 'scientific_effectiveness_measured': False,
    'limits': ['Full headless C4 and C5 grids were not run in this gate.',
               'Synthetic observations do not authenticate an actual model or establish benchmark effects.',
               'Prior preliminary checks are separate and are not added to this frozen denominator.'],
})
print(json.dumps({'stage': str(STAGE), 'junit': closed['junit'], 'selected_files': len(rows)}))
