"""Reconcile delivered original check bytes, including preserved failures."""
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

WORK = Path(__file__).resolve().parent
BASE = WORK.parent
PREFIXES = [
    *[WORK / f'm3-context-artifact-r{i}' for i in (3, 4, 5)],
    *[WORK / f'm3-context-native-r{i}' for i in (1, 2)],
    BASE / 'artifact-review-provenance/work/m4-m5-artifacts-full-r1',
    BASE / 'artifact-review-provenance/work/m4-m5-artifacts-r2-full',
    *[WORK / f'm6-artifact-retrieval-r{i}' for i in (1, 2)],
    BASE / 'artifact-source-archive/work/artifact-source-archive-r1',
    *[WORK / f'artifact-source-archive-r{i}' for i in (2, 3)],
]


def sha(raw): return hashlib.sha256(raw).hexdigest()
def read(path): return json.loads(path.read_bytes())
def at(prefix, suffix): return Path(str(prefix) + suffix)


checks = []
for prefix in PREFIXES:
    before, closed, members = [read(at(prefix, suffix)) for suffix in ('-before.json', '-closed.json', '-source-members.json')]
    archive_raw, report_raw = at(prefix, '-sources.zip').read_bytes(), at(prefix, '.xml').read_bytes()
    assert before['commit'] == closed['commit'] == members['commit'], prefix
    assert closed['source_unchanged'] and closed['source_after'] == before['source_before'], prefix
    assert sha(archive_raw) == members['archive_sha256'], prefix
    assert sha(report_raw) == closed['report_sha256'], prefix
    metadata = {r['path']: r for r in members['members']}
    assert len(metadata) == len(members['members'])
    assert {name: row['sha256'] for name, row in metadata.items()} == before['source_before']
    with zipfile.ZipFile(at(prefix, '-sources.zip')) as archive:
        assert len(archive.namelist()) == len(set(archive.namelist())) == len(metadata)
        assert set(archive.namelist()) == set(metadata)
        for name, row in metadata.items():
            raw = archive.read(name)
            assert sha(raw) == row['sha256'] and len(raw) == row['bytes'], (prefix, name)
    suites = list(ET.fromstring(report_raw).iter('testsuite'))
    junit = {key: sum(int(s.get(key, 0)) for s in suites) for key in ('tests', 'failures', 'errors', 'skipped')}
    assert junit == closed['junit'], prefix
    assert bool(closed['exit_code'] == 0) == bool(junit['failures'] == junit['errors'] == 0), prefix
    checks.append({'prefix': str(prefix), 'commit': before['commit'], 'junit': junit,
        'source_count': len(metadata), 'archive_sha256': members['archive_sha256'],
        'report_sha256': closed['report_sha256'], 'source_unchanged': True,
        'original_bytes_verified': True, 'wall_seconds': closed['wall_seconds']})

result = {'schema': 'artifact-delivery-originals-verification-v2', 'checks': checks,
          'all_original_bytes_consistent': True, 'scientific_validated': False,
          'full_module_artifact_coverage_complete': False}
output = WORK / 'artifact-event-deliveries-root-verification-r2.json'
with output.open('x', encoding='utf-8', newline='\n') as stream:
    stream.write(json.dumps(result, indent=2) + '\n')
print(json.dumps({'output': str(output), 'checks': [{'prefix': Path(c['prefix']).name, 'junit': c['junit'],
    'commit': c['commit'], 'source_count': c['source_count']} for c in checks]}))
