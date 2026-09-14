"""Undo the three known later assertions while preserving original line endings."""
import hashlib
import json
import zipfile
from pathlib import Path

base = Path(r'C:\Users\Administrator\.codex\tmp\modular-checks')
red = base / 'm4m5-final-provenance-red-r1'
green = base / 'm4m5-final-provenance-green-r1'
output = Path(str(red) + '-recovered-test-source.zip')
manifest = Path(str(red) + '-recovered-test-source.json')
assert not output.exists() and not manifest.exists()
name = 'tests/test_grok_train_solver.py'
before = json.loads(Path(str(red) + '-before.json').read_bytes())
source_manifest = json.loads(Path(str(green) + '-source-members.json').read_bytes())
source_zip = Path(str(green) + '-sources.zip')
sha = lambda b: hashlib.sha256(b).hexdigest()
assert sha(source_zip.read_bytes()) == source_manifest['archive_sha256']
with zipfile.ZipFile(source_zip) as archive:
    raw = archive.read(name)
assert sha(raw) == next(row['sha256'] for row in source_manifest['members'] if row['path'] == name)
removed = [
    b"    assert result.receipt.data()['eligible_scored_cells'] == 8",
    b"    assert result.receipt.data()['native_final_verification']['score_eligible'] is True",
    b"    assert result.receipt.data()['native_final_verification']['current_originals_verified'] is True",
]
for line in removed:
    matches = [value for value in (line + b'\n', line + b'\r\n') if value in raw]
    assert len(matches) == 1 and raw.count(matches[0]) == 1
    raw = raw.replace(matches[0], b'', 1)
assert sha(raw) == before['source_before'][name], 'no inferred source equality'
with zipfile.ZipFile(output, 'x', zipfile.ZIP_DEFLATED) as archive:
    archive.writestr(name, raw)
report = {'commit': before['commit'], 'source_archive_sha256': sha(source_zip.read_bytes()),
          'archive_sha256': sha(output.read_bytes()), 'path': name, 'bytes': len(raw), 'sha256': sha(raw),
          'method': 'reverse only the three acde220 added assertions from captured exact green-r1 bytes',
          'matches_existing_frozen_source_before': True}
manifest.write_bytes((json.dumps(report, indent=2) + '\n').encode())
print(json.dumps(report))
