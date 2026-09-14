"""Preserve repaired module checks and complete public synthetic stage files."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import xml.etree.ElementTree as ET
import zipfile

WORK = Path(__file__).resolve().parent
TREE = WORK.parent / 'artifact-evidence-provenance'
sys.path.insert(0, str(TREE))
from research_loop.modular.contracts import FrozenRecord as R

STAGE = WORK/'artifact-events-archive-staging-r2'
DEST = TREE/'results/modular-engineering-20260914/artifact-events-r2'
assert not STAGE.exists() and not DEST.exists()
prefixes = [Path(row['prefix']) for row in json.loads((WORK/'artifact-event-deliveries-root-verification-r2.json').read_bytes())['checks']]
prefixes += [WORK/name for name in ('m4-m5-stage-fix-r1', 'artifact-m1-m6-unit-r1',
                                   'artifact-m1-m6-native-r1', 'artifact-m1-m6-order-r2')]
assert all(Path(str(prefix)+'-closed.json').is_file() for prefix in prefixes)
STAGE.mkdir()
items, checks, witnesses = [], [], []


def sha(raw): return hashlib.sha256(raw).hexdigest()
def read(path): return json.loads(path.read_bytes())
def at(prefix, suffix): return Path(str(prefix) + suffix)
def copy(path, relative):
    raw = path.read_bytes()
    target = STAGE/relative
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('xb') as stream: stream.write(raw)
    assert target.read_bytes() == raw
    items.append({'path': relative, 'bytes': len(raw), 'sha256': sha(raw), 'original': str(path)})


for prefix in prefixes:
    before, closed, manifest = [read(at(prefix, suffix)) for suffix in ('-before.json', '-closed.json', '-source-members.json')]
    assert before['commit'] == closed['commit'] == manifest['commit']
    assert before['source_before'] == closed['source_after'] and closed['source_unchanged']
    assert sha(at(prefix, '.xml').read_bytes()) == closed['report_sha256']
    suites = list(ET.parse(at(prefix, '.xml')).getroot().iter('testsuite'))
    junit = {key: sum(int(s.get(key, 0)) for s in suites) for key in ('tests', 'failures', 'errors', 'skipped')}
    assert junit == closed['junit']
    assert sha(at(prefix, '-sources.zip').read_bytes()) == manifest['archive_sha256']
    with zipfile.ZipFile(at(prefix, '-sources.zip')) as archive:
        members = {row['path']: row for row in manifest['members']}
        assert len(archive.namelist()) == len(set(archive.namelist())) == len(members)
        assert set(archive.namelist()) == set(members) == set(before['source_before'])
        for name, row in members.items():
            raw = archive.read(name)
            assert len(raw) == row['bytes'] and sha(raw) == row['sha256'] == before['source_before'][name]
    checks.append({'prefix': prefix.name, 'commit': before['commit'], 'junit': junit,
        'source_files': len(members), 'source_archive_sha256': manifest['archive_sha256'],
        'wall_seconds': closed['wall_seconds']})
    for suffix in ('-before.json', '-closed.json', '-source-members.json', '-sources.zip', '.xml'):
        copy(at(prefix, suffix), 'checks/'+prefix.name+suffix)


for prefix_name, cases in (
    ('artifact-m1-m6-native-r1', ('test_actual_history_target_pip0', 'test_artifact_writer_failure_r0')),
    ('artifact-m1-m6-order-r2', ('test_actual_history_target_pip0',)),
):
    source_zip = WORK/(prefix_name+'-sources.zip')
    with zipfile.ZipFile(source_zip) as archive:
        def sources(value):
            if isinstance(value, dict):
                if set(value) == {'path', 'sha256', 'bytes'}:
                    relative = Path(value['path']).relative_to(TREE).as_posix()
                    raw = archive.read(relative)
                    assert sha(raw) == value['sha256'] and len(raw) == value['bytes']
                else:
                    for item in value.values(): sources(item)
            elif isinstance(value, list):
                for item in value: sources(item)
        for case in cases:
            for stage in sorted((WORK/prefix_name/case/'common-run/stages').iterdir()):
                receipt = read(stage/'receipt.json')
                files = sorted(path for path in stage.rglob('*') if path.is_file())
                for path in files:
                    relative = path.relative_to(stage).as_posix()
                    assert re.fullmatch(r'(receipt\.json|builder(?:-receipt)?\.json|candidate\.json|(?:source|corpus)/source\.json|'
                        r'phase/(?:[0-9a-f]{64}\.(?:py|json)|allocation\.json|events\.jsonl|queue\.sqlite|receipt\.json)|'
                        r'runtime/(?:artifacts\.jsonl(?:\.seal\.json)?|trace\.jsonl|evidence\.jsonl|claims\.jsonl|'
                        r'predictions\.jsonl|reviews\.jsonl|audit-failure\.json|analysis-1\.py))', relative), relative
                    if path.name != 'receipt.json': assert sha(path.read_bytes()) == receipt['files'][relative]
                    copy(path, 'runtime/'+prefix_name+'/'+case+'/'+stage.name+'/'+relative)
                entries = [R(line.decode()) for line in (stage/'runtime/artifacts.jsonl').read_bytes().splitlines()]
                previous, seen, traced = None, set(), []
                for index, entry in enumerate(entries):
                    row = entry.data(); descriptor = R.from_dict(row['descriptor']); body = descriptor.data()
                    assert row['sequence'] == index and row['previous'] == previous and row['descriptor_digest'] == descriptor.content_hash
                    assert descriptor.content_hash not in seen and set(body['parents']) <= seen
                    sources(body)
                    if body['kind'] == 'trace_event': traced.append(body['payload']['canonical'])
                    seen.add(descriptor.content_hash); previous = entry.content_hash
                seal = read(stage/'runtime/artifacts.jsonl.seal.json')
                assert seal == receipt['artifact_catalogue_seal'] and seal['count'] == len(entries) and seal['head'] == previous
                traces = [json.loads(line) for line in (stage/'runtime/trace.jsonl').read_bytes().splitlines()]
                failed = (stage/'runtime/audit-failure.json').exists()
                assert traced == (traces[:-1] if failed else traces)
                witnesses.append({'prefix': prefix_name, 'case': case, 'stage': stage.name,
                    'status': receipt['status'], 'descriptors': len(entries), 'trace_gap': len(traces)-len(traced),
                    'archived_producer_sources_verified': True, 'stage_file_count': len(files)})

for name in ('artifact-event-deliveries-root-verification-r2.json', 'historical-catalogues-root-verification-r1.json',
             'integrated-artifact-review-r1.md', 'm4-m5-stage-review-r1.md', 'm3-native-stale-watchdogs-closed-r1.json'):
    copy(WORK/name, 'reviews/'+name)
for name in ('verify_artifact_event_deliveries_r2.py', 'verify_historical_catalogues_r1.py', 'archive_artifact_events_r2.py'):
    copy(WORK/name, 'tools/'+name)
scope = {'schema': 'artifact-event-evidence-scope-v2', 'checks': checks, 'runtime_witnesses': witnesses,
    'scope': 'Synthetic public engineering; complete stage files for selected runs, not real efficacy or VAL acceptance',
    'reviews': 'Earlier passing checks retain later-discovered gaps; repairs and checks are separate source versions',
    'historical_reader_scope': 'Archived source and catalogue integrity only; no historical semantic replay or environment equivalence',
    'watcher_limit': 'Two completed M3 checks left PID-only watchers; exact-identity cleanup preserved separately',
    'private_keys_auth_and_streams_included': False, 'full_artifact_coverage_complete': False,
    'scientific_effectiveness_proven': False, 'items': items}
(STAGE/'SCOPE.json').write_bytes((json.dumps(scope, indent=2)+'\n').encode())
(STAGE/'.gitattributes').write_bytes(b'* -text\n')
DEST.parent.mkdir(parents=True, exist_ok=True)
shutil.copytree(STAGE, DEST)
for path in STAGE.rglob('*'):
    if path.is_file(): assert path.read_bytes() == (DEST/path.relative_to(STAGE)).read_bytes()
print(json.dumps({'archive': str(DEST), 'total_files': len(items)+2, 'checks': len(checks), 'witnesses': witnesses}))
