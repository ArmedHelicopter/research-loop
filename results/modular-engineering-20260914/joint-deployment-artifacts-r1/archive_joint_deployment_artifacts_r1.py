"""Preserve checks and selected public synthetic deployment databases and caller pins."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import xml.etree.ElementTree as ET
import zipfile

work = Path(__file__).resolve().parent
tree = work.parent/'artifact-evidence-provenance'
stage = work/'joint-deployment-artifacts-staging-r1'
dest = tree/'results/modular-engineering-20260914/joint-deployment-artifacts-r1'
assert not stage.exists() and not dest.exists()
sys.path[:0] = [str(tree), str(tree/'tests')]
from research_loop.modular.artifact_source_archive import ArchivedSourceResolver
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.joint_deployment_artifacts import verify_joint_deployment_artifacts
from test_joint_deployment import KEYS, ROLLBACK

sha = lambda raw: hashlib.sha256(raw).hexdigest()
read = lambda path: json.loads(path.read_bytes())
stage.mkdir()
files = []; checks = []; databases = []

def copy(path, relative):
    assert path.is_file() and not path.is_symlink()
    assert not getattr(path.stat(), 'st_file_attributes', 0) & 0x400
    raw = path.read_bytes(); target = stage/relative
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('xb') as stream: stream.write(raw)
    files.append({'path': relative, 'original': str(path), 'bytes': len(raw), 'sha256': sha(raw)})

for prefix, expected_tests in [('joint-deployment-artifacts-r1', 74), ('joint-deployment-artifacts-r2', 78), ('joint-deployment-artifacts-r3', 78)]:
    at = lambda suffix: work/(prefix+suffix)
    before, closed, manifest = [read(at(s)) for s in ('-before.json', '-closed.json', '-source-members.json')]
    assert before['commit'] == closed['commit'] == manifest['commit']
    assert before['source_before'] == closed['source_after'] and closed['source_unchanged'] and closed['exit_code'] == 0
    suites = list(ET.parse(at('.xml')).getroot().iter('testsuite'))
    junit = {key: sum(int(s.get(key, 0)) for s in suites) for key in ('tests', 'failures', 'errors', 'skipped')}
    assert junit == closed['junit'] == {'tests': expected_tests, 'failures': 0, 'errors': 0, 'skipped': 0}
    assert sha(at('.xml').read_bytes()) == closed['report_sha256']
    assert sha(at('-sources.zip').read_bytes()) == manifest['archive_sha256']
    with zipfile.ZipFile(at('-sources.zip')) as archive:
        members = {row['path']: row for row in manifest['members']}
        assert len(archive.namelist()) == len(set(archive.namelist())) == len(members)
        assert set(archive.namelist()) == set(members) == set(before['source_before'])
        for name, row in members.items():
            raw = archive.read(name)
            assert sha(raw) == row['sha256'] == before['source_before'][name] and len(raw) == row['bytes']
    checks.append({'prefix': prefix, **{k:v for k,v in closed.items() if k!='source_after'},
                   'source_archive_sha256': manifest['archive_sha256']})
    for suffix in ('-before.json', '-closed.json', '-source-members.json', '-sources.zip', '.xml', '-watchdog-config.json', '-watchdog.jsonl'):
        if at(suffix).is_file(): copy(at(suffix), 'checks/'+prefix+suffix)

prefix = 'joint-deployment-artifacts-r3'
resolver = ArchivedSourceResolver(work/(prefix+'-sources.zip'), checks[-1]['source_archive_sha256'], tree)
cases = ['test_actual_outputs_use_config0', 'test_partial_component_writes_0',
         'test_audit_failure_cannot_publ0', 'test_audit_failure_cannot_publ1',
         'test_returned_task_output_is_r0', 'test_commit_survives_a_caller_0',
         'test_component_subject_preserv0', 'test_two_process_writers_publi0',
         'test_all_nine_components_reach0', 'test_legacy_store_is_an_observ0']
for case in cases:
    root = work/prefix/case; database = root/'joint.sqlite'
    assert not (root/'joint.sqlite-journal').exists()
    original = database.read_bytes()
    if (root/'joint.caller-checkpoints.jsonl').is_file():
        pins = [json.loads(line) for line in (root/'joint.caller-checkpoints.jsonl').read_bytes().splitlines()]
        assert all(row['domain']=='train' for row in pins)
        checkpoint = FrozenRecord.from_dict(max(pins, key=lambda r:r['checkpoint']['count'])['checkpoint'])
        pin_files = [root/'joint.caller-checkpoints.jsonl']
    else:
        checkpoint = FrozenRecord.from_dict(read(root/'joint.audit-checkpoint.json'))
        pin_files = [root/'joint.audit-checkpoint.json']
    report = verify_joint_deployment_artifacts(database, domain='train', checkpoint=checkpoint,
        acceptance_keys=KEYS, rollback_keys=ROLLBACK,
        component_source_roots={f'M{i}':root/'builds' for i in range(1,10)}, source_resolver=resolver)
    assert database.read_bytes() == original
    assert report.data()['optimizer_visible'] is False and report.data()['component_sources_verified'] is True
    reports = sorted(root.glob('joint.audit-read*.json'))
    assert reports and any(FrozenRecord(p.read_text(encoding='utf-8').strip()) == report for p in reports)
    copy(database, 'stores/'+case+'/joint.sqlite')
    for path in pin_files+reports: copy(path, 'stores/'+case+'/'+path.name)
    sources = sorted((root/'builds').iterdir())
    assert len(sources)==9 and all(path.suffix=='.py' for path in sources)
    for path in sources: copy(path, 'stores/'+case+'/builds/'+path.name)
    rows = report.data()['events']
    assert all(r['payload'].get('identity', {}).get('domain', 'train')=='train'
               for r in rows if r['kind']=='started' and r['payload']['identity'] is not None)
    databases.append({'case': case, 'path':'stores/'+case+'/joint.sqlite', 'checkpoint':checkpoint.data(),
        'events':len(rows), 'started':sum(r['kind']=='started' for r in rows),
        'committed':sum(r['kind']=='committed' for r in rows), 'failed':sum(r['kind']=='failed' for r in rows),
        'pending':len(report.data()['pending_attempts']),
        'history_complete':rows[0]['payload']['history_complete'], 'report_digest':report.content_hash})

copy(Path(__file__), 'archive_joint_deployment_artifacts_r1.py')
scope = {'schema':'joint-deployment-artifact-engineering-archive-v1', 'checks':checks, 'files':files,
         'original_tree':str(tree), 'source_prefix':prefix, 'source_archive_sha256':checks[-1]['source_archive_sha256'],
         'databases':databases, 'scope':'Ten selected actual public synthetic SQLite stores, caller-retained checkpoints, actual readback outputs and all declared component build sources. Includes atomic publication, rollback, failed staging, audit-writer failure, task returns, post-COMMIT delivery failure, process concurrency and explicitly observed legacy history.',
         'exclusions':'No validation store or validation output is copied; private keys, private reference stores and real datasets are excluded. Other counterexample case originals remain in work.',
         'limits':'The three check versions are not independent scientific samples. SQL replay checks recorded transitions and source bytes; it does not execute historical source or establish model efficacy, VAL acceptance or operating-system isolation.',
         'scientific_effectiveness_proven':False, 'validation_acceptance':False, 'new_paid_calls':0}
(stage/'SCOPE.json').write_bytes((json.dumps(scope,indent=2)+'\n').encode())
(stage/'.gitattributes').write_bytes(b'* -text\n')
shutil.copytree(stage,dest)
for path in stage.rglob('*'):
    if path.is_file(): assert path.read_bytes()==(dest/path.relative_to(stage)).read_bytes()
print(json.dumps({'files':len(files)+2,'databases':len(databases),
    'counts':{key:sum(row[key] for row in databases) for key in ('events','started','committed','failed','pending')},
    'legacy_observations':sum(not row['history_complete'] for row in databases),'destination':str(dest)}))
