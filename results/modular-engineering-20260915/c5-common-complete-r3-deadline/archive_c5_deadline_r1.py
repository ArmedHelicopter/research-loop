"""Preserve the stopped C5 engineering attempt; never resume or reinterpret it."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import zipfile

BASE = Path('E:/_ryanDev/AI/research-loop-modular')
SOURCE = BASE / 'integration'
PREFIX = BASE / 'work/c5-common-complete-r3'
ROOT = BASE / 'artifact-evidence-provenance'
OUT = ROOT / 'results/modular-engineering-20260915/c5-common-complete-r3-deadline'
CONFIG = BASE / 'work/c5-common-complete-r3-watchdog-extension-r1-config.json'
JOURNAL = BASE / 'work/c5-common-complete-r3-watchdog-extension-r1.jsonl'
config = json.loads(CONFIG.read_text(encoding='utf-8-sig'))
events = [json.loads(line) for line in JOURNAL.read_text(encoding='utf-8-sig').splitlines()]
assert events[-1]['event'] == 'deadline_cleanup_recorded'
assert events[-1]['remaining_observed_owned_processes'] == []
assert all(row['absent_after_cleanup'] for row in events[-1]['observed_owned_docker_cleanup'])
inventory_event = next(row for row in events if row['event'] == 'deadline_inventory')
owned = inventory_event['processes']
query = ' OR '.join('ProcessId = ' + str(row['pid']) for row in owned)
cmd = "Get-CimInstance Win32_Process -Filter '" + query + "' | Select-Object ProcessId,@{Name='creation_utc_ticks';Expression={$_.CreationDate.ToUniversalTime().Ticks}} | ConvertTo-Json -Compress"
observed = subprocess.check_output(['powershell.exe', '-NoProfile', '-Command', cmd], text=True).strip()
live = json.loads(observed) if observed else []
if isinstance(live, dict): live = [live]
assert not any(row['ProcessId'] == prior['pid'] and row['creation_utc_ticks'] == prior['creation_utc_ticks']
               for row in live for prior in owned), 'an observed owned process remains'

def sha(raw): return hashlib.sha256(raw).hexdigest()
def file_hash(path):
    with path.open('rb') as stream: return hashlib.file_digest(stream, 'sha256').hexdigest()
def write(path, value):
    with path.open('xb') as stream: stream.write((json.dumps(value, indent=2) + '\n').encode())

before = json.loads(Path(str(PREFIX) + '-before.json').read_bytes())
sources = json.loads(Path(str(PREFIX) + '-source-members.json').read_bytes())
assert before['commit'] == sources['commit']
assert before['source_before'] == {row['path']: row['sha256'] for row in sources['members']}
assert all(file_hash(SOURCE/name) == digest for name, digest in before['source_before'].items())
assert not Path(str(PREFIX) + '-closed.json').exists()
assert not Path(str(PREFIX) + '.xml').exists()
assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=SOURCE).strip()

OUT.mkdir(parents=True, exist_ok=False)
(OUT / '.gitattributes').write_bytes(b'* -text\n')
originals = []
def register(path):
    originals.append({'file': path.name, 'bytes': path.stat().st_size, 'sha256': file_hash(path)})
def copy(path):
    dest = OUT/path.name
    with path.open('rb') as source, dest.open('xb') as target:
        while raw := source.read(1024*1024): target.write(raw)
    assert file_hash(path) == file_hash(dest)
    register(dest)

for path in [CONFIG, JOURNAL, Path(__file__), BASE / 'work/watch_native_phase_deadline_r1.ps1',
             Path(str(PREFIX)+'-before.json'), Path(str(PREFIX)+'-source-members.json'), Path(str(PREFIX)+'-sources.zip')]:
    copy(path)
source_zip = OUT / (PREFIX.name + '-sources.zip')
assert file_hash(source_zip) == sources['archive_sha256']
with zipfile.ZipFile(source_zip) as archive:
    assert archive.testzip() is None
    for row in sources['members']:
        raw = archive.read(row['path'])
        assert sha(raw) == row['sha256'] and len(raw) == row['bytes']

def listing():
    files, links, directories = {}, {}, []
    for directory, dirs, names in os.walk(PREFIX, followlinks=False):
        root = Path(directory)
        directories.append(root.relative_to(PREFIX).as_posix())
        for name in list(dirs):
            path = root/name
            if path.is_symlink() or path.is_junction():
                links[path.relative_to(PREFIX).as_posix()] = os.readlink(path)
                dirs.remove(name)
        for name in names:
            path = root/name
            if path.is_symlink() or path.is_junction():
                links[path.relative_to(PREFIX).as_posix()] = os.readlink(path)
            else:
                stat = path.stat()
                files[path.relative_to(PREFIX).as_posix()] = (stat.st_size, stat.st_mtime_ns)
    return dict(sorted(files.items())), dict(sorted(links.items())), sorted(directories)

files, links, directories = listing()
members, groups, group, size = [], [], [], 0
for name, metadata in files.items():
    if group and size + metadata[0] > 24 * 1024 * 1024:
        groups.append(group); group, size = [], 0
    group.append(name); size += metadata[0]
if group: groups.append(group)
for index, group in enumerate(groups):
    path = OUT / f'runtime-{index:03d}.zip'
    with zipfile.ZipFile(path, 'x', zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
        for name in group:
            source = PREFIX/name
            raw = source.read_bytes()
            stat = source.stat()
            assert (len(raw), stat.st_mtime_ns) == files[name]
            archive.writestr(name, raw)
            members.append({'path': name, 'bytes': len(raw), 'sha256': sha(raw),
                            'mtime_ns': stat.st_mtime_ns, 'archive': path.name})
    register(path)
assert listing() == (files, links, directories)
for row in members:
    assert file_hash(PREFIX/row['path']) == row['sha256']
for path in OUT.glob('runtime-*.zip'):
    expected = [row for row in members if row['archive'] == path.name]
    with zipfile.ZipFile(path) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist()) == {row['path'] for row in expected}
        for row in expected:
            raw = archive.read(row['path'])
            assert len(raw) == row['bytes'] and sha(raw) == row['sha256']
assert listing() == (files, links, directories)
checkpoint = json.loads((PREFIX/'test_complete_common_train_con0/common-run/checkpoint.json').read_bytes())
counts = {}
for row in checkpoint['rows']:
    key = row['stage'] + ':' + row['status']
    counts[key] = counts.get(key, 0) + 1
assert sum(row['stage'] == 'target' for row in checkpoint['rows']) == 118
assert sum(row['stage'] == 'history_build' for row in checkpoint['rows']) == 46
result = {'status': 'deadline_interrupted_incomplete', 'source_commit': before['commit'],
    'originals': originals, 'specimens': [], 'runtime_members': members, 'runtime_links_not_followed': links,
    'runtime_directories': directories, 'checkpoint_counts': counts, 'expected_history_builds': 46,
    'expected_target_cells': 118, 'expected_synthetic_main_calls': 930, 'expected_docker_attempts': 442,
    'expected_scorer_opportunities': 118, 'actual_synthetic_main_calls': None, 'actual_docker_attempts': None,
    'actual_scorer_invocations': None, 'new_paid_calls': 0, 'scientific_validated': False,
    'completed_junit_or_frozen_closure': False, 'observed_owned_processes_absent': True,
    'unobserved_resource_absence_proven': False, 'runtime_bytes_and_mtime_unchanged_during_archive': True,
    'source_unchanged_from_original_frozen_start': True,
    'limitations': ['checkpoint succeeded rows are not a completed test or scientific acceptance',
                   'retained sources and bytes do not establish complete historical semantic replay',
                   'no retry, extension, optimizer or VAL operation performed by this archive']}
write(OUT/'manifest.json', result)
write(OUT/'verification.json', {'status': 'original_bytes_verified', 'files': len(files),
    'bytes': sum(row[0] for row in files.values()), 'runtime_archives': len(groups),
    'checkpoint_counts': counts, 'originals': len(originals), 'scientific_validated': False})
print(json.dumps({'archive': str(OUT), 'runtime_files': len(files), 'runtime_bytes': sum(row[0] for row in files.values()),
                  'archives': len(groups), 'originals': len(originals), 'counts': counts}), flush=True)
