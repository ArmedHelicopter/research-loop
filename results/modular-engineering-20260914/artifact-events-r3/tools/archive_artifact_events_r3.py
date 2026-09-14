"""Verify and preserve M7-M9 checks, including the reproduced acceptance failure."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import xml.etree.ElementTree as ET
import zipfile

WORK = Path(__file__).resolve().parent
TREE = WORK.parent/'artifact-evidence-provenance'
STAGE = WORK/'artifact-events-archive-staging-r3'
DEST = TREE/'results/modular-engineering-20260914/artifact-events-r3'
sys.path.insert(0, str(TREE))
from research_loop.modular.contracts import FrozenRecord as R

PREFIXES = ('m7-m8-phase-artifact-r1', 'm7-m8-phase-artifact-r2',
    'm9-builder-frozen-r1', 'm9-builder-frozen-r2', 'm9-builder-frozen-r3',
    'artifact-m1-m9-stage-r1', 'artifact-m9-stage-repro-r2', 'artifact-m9-stage-fixed-r3')
assert not STAGE.exists() and not DEST.exists()
assert all((WORK/(name+'-closed.json')).is_file() for name in PREFIXES)
STAGE.mkdir()
items, checks, witnesses = [], [], []
def sha(raw): return hashlib.sha256(raw).hexdigest()
def read(path): return json.loads(path.read_bytes())
def copy(path, relative):
    raw = path.read_bytes(); target = STAGE/relative
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('xb') as stream: stream.write(raw)
    assert target.read_bytes() == raw
    items.append({'path': relative, 'bytes': len(raw), 'sha256': sha(raw), 'original': str(path)})

for name in PREFIXES:
    def at(suffix): return WORK/(name+suffix)
    before, closed, manifest = [read(at(s)) for s in ('-before.json', '-closed.json', '-source-members.json')]
    assert before['commit'] == closed['commit'] == manifest['commit']
    assert before['source_before'] == closed['source_after'] and closed['source_unchanged']
    assert sha(at('.xml').read_bytes()) == closed['report_sha256']
    suites = list(ET.parse(at('.xml')).getroot().iter('testsuite'))
    junit = {key: sum(int(s.get(key, 0)) for s in suites) for key in ('tests', 'failures', 'errors', 'skipped')}
    assert junit == closed['junit']
    assert sha(at('-sources.zip').read_bytes()) == manifest['archive_sha256']
    with zipfile.ZipFile(at('-sources.zip')) as archive:
        members = {row['path']: row for row in manifest['members']}
        assert len(archive.namelist()) == len(set(archive.namelist())) == len(members)
        assert set(archive.namelist()) == set(members) == set(before['source_before'])
        for member, row in members.items():
            raw = archive.read(member)
            assert len(raw) == row['bytes'] and sha(raw) == row['sha256'] == before['source_before'][member]
    checks.append({'prefix': name, 'commit': before['commit'], 'junit': junit, 'source_files': len(members),
        'source_archive_sha256': manifest['archive_sha256'], 'wall_seconds': closed['wall_seconds'],
        'actual_paid_provider_calls': 0, 'scientific_effectiveness_proven': False})
    for suffix in ('-before.json', '-closed.json', '-source-members.json', '-sources.zip', '.xml'):
        copy(at(suffix), 'checks/'+name+suffix)
    for suffix in ('-watchdog-config.json', '-watchdog.json'):
        if at(suffix).is_file(): copy(at(suffix), 'checks/'+name+suffix)

for prefix, cases in (
    ('artifact-m1-m9-stage-r1', ('test_actual_history_target_pip0', 'test_actual_ordinary_control_p0')),
    ('artifact-m9-stage-repro-r2', ('test_actual_history_target_pip0',)),
    ('artifact-m9-stage-fixed-r3', ('test_actual_history_target_pip0', 'test_actual_ordinary_control_p0')),
):
    with zipfile.ZipFile(WORK/(prefix+'-sources.zip')) as archive:
        def sources(value):
            if isinstance(value, dict):
                if set(value) == {'path', 'sha256', 'bytes'}:
                    relative = Path(value['path']).relative_to(TREE).as_posix()
                    raw = archive.read(relative)
                    assert sha(raw) == value['sha256'] and len(raw) == value['bytes']
                else:
                    for child in value.values(): sources(child)
            elif isinstance(value, list):
                for child in value: sources(child)
        for case in cases:
            stages = sorted((WORK/prefix/case/'common-run/stages').iterdir())
            assert len(stages) == 2
            for stage in stages:
                receipt = read(stage/'receipt.json')
                files = sorted(path for path in stage.rglob('*') if path.is_file())
                observed_files = {}
                for path in files:
                    relative = path.relative_to(stage).as_posix()
                    assert re.fullmatch(r'(receipt\.json|builder(?:-receipt)?\.json|candidate\.json|'
                        r'm9-(?:builder-return|build-terminal)\.json|(?:source|corpus)/source\.json|'
                        r'phase/(?:[0-9a-f]{64}\.(?:py|json)|allocation\.json|events\.jsonl|queue\.sqlite|receipt\.json)|'
                        r'phase-artifacts/blobs/[0-9a-f]{64}|'
                        r'runtime/(?:artifacts\.jsonl(?:\.seal\.json)?|trace\.jsonl|evidence\.jsonl|claims\.jsonl|'
                        r'predictions\.jsonl|reviews\.jsonl|analysis-1\.py))', relative), relative
                    if relative.startswith('phase-artifacts/blobs/'): assert sha(path.read_bytes()) == path.name
                    if path.name != 'receipt.json': observed_files[relative] = sha(path.read_bytes())
                    copy(path, 'runtime/'+prefix+'/'+case+'/'+stage.name+'/'+relative)
                assert observed_files == receipt['files']
                entries = [R(line.decode()) for line in (stage/'runtime/artifacts.jsonl').read_bytes().splitlines()]
                previous, seen, traced, kinds, modules = None, set(), [], {}, set()
                for index, entry in enumerate(entries):
                    row = entry.data(); descriptor = R.from_dict(row['descriptor']); body = descriptor.data()
                    assert row['sequence'] == index and row['previous'] == previous and row['descriptor_digest'] == descriptor.content_hash
                    assert descriptor.content_hash not in seen and set(body['parents']) <= seen
                    sources(body)
                    if body['kind'] == 'trace_event': traced.append(body['payload']['canonical'])
                    kinds[body['kind']] = kinds.get(body['kind'], 0)+1
                    if body['coverage'] == 'covered': modules.add(body['module'])
                    seen.add(descriptor.content_hash); previous = entry.content_hash
                seal = read(stage/'runtime/artifacts.jsonl.seal.json')
                assert seal == receipt['artifact_catalogue_seal'] and seal['count'] == len(entries) and seal['head'] == previous
                assert traced == [json.loads(line) for line in (stage/'runtime/trace.jsonl').read_bytes().splitlines()]
                assert kinds['phase_program'] == kinds['phase_return'] == 2
                assert kinds['phase_allocation'] == kinds['phase_receipt'] == 1
                assert kinds['phase_scheduler_event'] == len((stage/'phase/events.jsonl').read_bytes().splitlines())
                terminal = read(stage/'m9-build-terminal.json') if (stage/'m9-build-terminal.json').exists() else None
                witnesses.append({'prefix': prefix, 'case': case, 'stage': stage.name,
                    'status': receipt['status'], 'descriptors': len(entries), 'trace_gap': 0,
                    'kinds': kinds, 'modules_with_descriptors': sorted(modules),
                    'builder_terminal_status': terminal['status'] if terminal else None,
                    'restored_original_after_tamper_test': prefix != 'artifact-m1-m9-stage-r1',
                    'archived_producer_sources_verified': True, 'stage_file_count': len(files)})
for name in ('artifact-host-coverage-audit-r1.md', 'artifact-host-call-sites-r1.json'):
    copy(WORK/name, 'reviews/'+name)
copy(WORK/'inventory_artifact_hosts_r1.py', 'tools/inventory_artifact_hosts_r1.py')
copy(Path(__file__), 'tools/'+Path(__file__).name)
scope = {'schema': 'artifact-event-evidence-scope-v3', 'checks': checks, 'runtime_witnesses': witnesses,
    'scope': 'Synthetic public engineering; real Docker and synthetic model processes in actual stage checks',
    'negative_evidence': 'repro-r2 demonstrates old success reader accepted coherently sealed failed M9 terminal; fixed-r3 rejects it',
    'historical_source_verification': 'Exact archive bytes and producer references; not full historical environment replay',
    'cost_scope': 'M9 units are restricted-builder attempt/search units; resource and monetary totals are separate and not inferred',
    'watcher_note': 'root stage-r1 prospective expected_cases was 38; collected and closed actual denominator is 39',
    'private_keys_auth_and_streams_included': False, 'full_artifact_coverage_complete': False,
    'scientific_effectiveness_proven': False, 'validation_acceptance': False, 'items': items}
(STAGE/'SCOPE.json').write_bytes((json.dumps(scope, indent=2)+'\n').encode())
(STAGE/'.gitattributes').write_bytes(b'* -text\n')
DEST.parent.mkdir(parents=True, exist_ok=True)
shutil.copytree(STAGE, DEST)
for path in STAGE.rglob('*'):
    if path.is_file(): assert path.read_bytes() == (DEST/path.relative_to(STAGE)).read_bytes()
print(json.dumps({'archive': str(DEST), 'total_files': len(items)+2, 'checks': len(checks),
    'runtime_stages': len(witnesses), 'descriptors': sum(row['descriptors'] for row in witnesses)}))
