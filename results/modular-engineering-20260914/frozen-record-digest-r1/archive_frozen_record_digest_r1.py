"""Preserve frozen digest checks and selected actual public C5 stage originals."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import xml.etree.ElementTree as ET
import zipfile

work = Path(__file__).resolve().parent
tree = work.parent / 'artifact-evidence-provenance'
prefix = 'frozen-record-digest-r1'
stage = work / 'frozen-record-digest-staging-r1'
dest = tree / 'results/modular-engineering-20260914/frozen-record-digest-r1'
assert not stage.exists() and not dest.exists()
sys.path.insert(0, str(tree))
from research_loop.modular.artifact_catalogue import ArtifactCatalogue
from research_loop.modular.artifact_source_archive import ArchivedSourceResolver
from research_loop.modular.contracts import DataIdentity, FrozenRecord

sha = lambda raw: hashlib.sha256(raw).hexdigest()
read = lambda path: json.loads(path.read_bytes())
at = lambda suffix: work / (prefix + suffix)
before, closed, manifest = [read(at(s)) for s in ('-before.json', '-closed.json', '-source-members.json')]
assert before['commit'] == closed['commit'] == manifest['commit']
assert before['source_before'] == closed['source_after'] and closed['source_unchanged']
assert closed['exit_code'] == 0
suites = list(ET.parse(at('.xml')).getroot().iter('testsuite'))
junit = {key: sum(int(s.get(key, 0)) for s in suites) for key in ('tests', 'failures', 'errors', 'skipped')}
assert junit == closed['junit'] and junit['tests'] >= 140
assert not (junit['failures'] or junit['errors'] or junit['skipped'])
assert sha(at('.xml').read_bytes()) == closed['report_sha256']
assert sha(at('-sources.zip').read_bytes()) == manifest['archive_sha256']
with zipfile.ZipFile(at('-sources.zip')) as archive:
    members = {row['path']: row for row in manifest['members']}
    assert len(archive.namelist()) == len(set(archive.namelist())) == len(members)
    assert set(archive.namelist()) == set(members) == set(before['source_before'])
    for name, row in members.items():
        raw = archive.read(name)
        assert len(raw) == row['bytes'] and sha(raw) == row['sha256'] == before['source_before'][name]

stage.mkdir()
files = []
def copy(path, relative):
    assert path.is_file() and not path.is_symlink()
    assert not getattr(path.stat(), 'st_file_attributes', 0) & 0x400
    raw = path.read_bytes()
    target = stage / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('xb') as stream:
        stream.write(raw)
    files.append({'path': relative, 'original': str(path), 'bytes': len(raw), 'sha256': sha(raw)})

for suffix in ('-before.json', '-closed.json', '-source-members.json', '-sources.zip', '.xml', '-watchdog-config.json', '-watchdog.jsonl'):
    if at(suffix).is_file():
        copy(at(suffix), 'checks/' + prefix + suffix)
for name in ('canonical-hash-cost-observation-r1.json', 'probe_canonical_hash_cost_r1.py', 'bounded-record-digest-microtiming-r1.json'):
    copy(work / name, 'microtiming/' + name)
copy(Path(__file__), 'archive_frozen_record_digest_r1.py')

resolver = ArchivedSourceResolver(at('-sources.zip'), manifest['archive_sha256'], tree)
cases = ['test_actual_history_target_pip0', 'test_actual_ordinary_control_p0',
         'test_unknown_main_keeps_comple0', 'test_artifact_writer_failure_r0']
catalogues = []
stages = []
for case in cases:
    source = work / prefix / case / 'common-run/stages'
    for node in sorted(source.iterdir()):
        assert node.is_dir() and not node.is_symlink()
        receipt = read(node / 'receipt.json')
        relative = 'stages/' + case + '/' + node.name
        selected = sorted(p for p in node.rglob('*') if p.is_file())
        for path in selected:
            assert path.suffix in ('.json', '.jsonl', '.py', '.sqlite', '')
            assert not any(part in ('data/labels', '.env') or part.endswith('.key') for part in path.relative_to(node).parts)
            copy(path, relative + '/' + path.relative_to(node).as_posix())
        journal = node / 'runtime/artifacts.jsonl'
        first = json.loads(journal.read_bytes().splitlines()[0])['descriptor']
        reader = ArtifactCatalogue(journal, identity=DataIdentity(**first['identity']), **first['binding'],
                                   producer_source=first['producer_source'], source_resolver=resolver)
        records = reader.records()
        seal = FrozenRecord.from_dict(read(reader.seal_path))
        reader.verify(seal)
        assert receipt['artifact_catalogue_seal'] == seal.data()
        catalogues.append({'path': relative + '/runtime/artifacts.jsonl', 'descriptors': len(records),
                           'seal_digest': seal.content_hash, 'stage_status': receipt['status']})
        stages.append({'case': case, 'path': relative, 'files': len(selected), 'status': receipt['status']})
assert len(stages) == 6 and len(catalogues) == 6
assert sum(row['status'] == 'succeeded' for row in stages) == 4
scope = {'schema': 'frozen-record-digest-engineering-archive-v1',
         'checks': {k: v for k, v in closed.items() if k != 'source_after'},
         'source_archive_sha256': manifest['archive_sha256'], 'original_tree': str(tree),
         'files': files, 'stages': stages, 'catalogues': catalogues,
         'scope': 'Selected four successful and two failed public synthetic C5 stage directories. The complete C5 controller is a separate run. Raw source and all check outcomes preserved. Microtiming does not estimate total runtime speedup.',
         'exclusions': 'Private scorer stores, keys, source snapshot roots, full split or VAL indexes, provider streams; other test case originals remain in work.',
         'historical_stage_semantic_replay_executed': False,
         'scientific_effectiveness_proven': False, 'validation_acceptance': False, 'new_paid_calls': 0}
(stage / 'SCOPE.json').write_bytes((json.dumps(scope, indent=2) + '\n').encode())
(stage / '.gitattributes').write_bytes(b'* -text\n')
shutil.copytree(stage, dest)
for path in stage.rglob('*'):
    if path.is_file():
        assert path.read_bytes() == (dest / path.relative_to(stage)).read_bytes()
print(json.dumps({'files': len(files) + 2, 'stages': len(stages), 'catalogues': len(catalogues),
                  'descriptors': sum(row['descriptors'] for row in catalogues), 'junit': junit, 'destination': str(dest)}))
