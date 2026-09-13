"""Read-only byte verifier. Run from repository: python <script> <archive> [revision]."""
import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path

root = Path(sys.argv[1]).resolve()
repo = Path(subprocess.check_output(['git', 'rev-parse', '--show-toplevel'], text=True).strip()).resolve()
relative = root.relative_to(repo).as_posix()
revision = sys.argv[2] if len(sys.argv) > 2 else None
entries = json.loads((root / 'payload-sha256.json').read_text())
expected_payload = {entry['path'] for entry in entries}
expected_all = expected_payload | {'payload-sha256.json', 'evidence.zip'}
actual_all = {path.relative_to(root).as_posix() for path in root.rglob('*') if path.is_file()}
assert expected_all == actual_all
with zipfile.ZipFile(root / 'evidence.zip') as archive:
    assert len(archive.namelist()) == len(expected_payload)
    assert set(archive.namelist()) == expected_payload
    assert archive.testzip() is None
    for entry in entries:
        data = (root / entry['path']).read_bytes()
        assert len(data) == entry['size']
        assert hashlib.sha256(data).hexdigest() == entry['sha256']
        assert archive.read(entry['path']) == data
tracked = subprocess.check_output(['git', 'ls-files', '-z', '--', relative]).decode().split('\0')
assert {x[len(relative)+1:] for x in tracked if x} == expected_all
rows = []
for name in sorted(expected_all):
    data = (root / name).read_bytes()
    path = relative + '/' + name
    assert subprocess.check_output(['git', 'show', ':' + path]) == data
    if revision:
        assert subprocess.check_output(['git', 'show', revision + ':' + path]) == data
    rows.append({'path': name, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
if revision:
    committed = subprocess.check_output(['git', 'ls-tree', '-r', '--name-only', '-z', revision, '--', relative]).decode().split('\0')
    assert {x[len(relative)+1:] for x in committed if x} == expected_all
print(json.dumps({'schema': 'grok-native-acp-archive-byte-verification-v1',
    'archive': str(root), 'revision': revision, 'payload_zip_entries': len(entries),
    'archive_files': len(rows), 'disk_manifest_zip_equal': True, 'all_index_bytes_equal': True,
    'all_commit_bytes_equal': bool(revision), 'private_files_included': False, 'files': rows}, indent=2))
