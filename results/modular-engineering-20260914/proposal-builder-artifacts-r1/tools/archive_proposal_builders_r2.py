"""Archive closed proposal-builder attempts and selected public output witnesses."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import xml.etree.ElementTree as ET
import zipfile

work = Path(__file__).resolve().parent
tree = work.parent/'artifact-evidence-provenance'
stage = work/'proposal-builder-artifacts-staging-r2'
dest = tree/'results/modular-engineering-20260914/proposal-builder-artifacts-r1'
prefixes = ('proposal-builder-hosts-r1','proposal-builder-hosts-r2','proposal-builder-hosts-r3','proposal-builder-hosts-r4')
assert not stage.exists() and not dest.exists()
assert all((work/(p+'-closed.json')).is_file() for p in prefixes)
sys.path.insert(0,str(tree))
from research_loop.modular.artifact_catalogue import ArtifactCatalogue
from research_loop.modular.artifact_source_archive import ArchivedSourceResolver
from research_loop.modular.contracts import DataIdentity

sha = lambda raw:hashlib.sha256(raw).hexdigest()
read = lambda path:json.loads(path.read_bytes())
stage.mkdir()
items, checks, witnesses = [], [], []
def copy(path, relative):
    raw=path.read_bytes(); target=stage/relative
    target.parent.mkdir(parents=True,exist_ok=True)
    with target.open('xb') as stream:stream.write(raw)
    items.append({'path':relative,'bytes':len(raw),'sha256':sha(raw),'original':str(path)})

for prefix in prefixes:
    at=lambda suffix:work/(prefix+suffix)
    before,closed,manifest=[read(at(s)) for s in ('-before.json','-closed.json','-source-members.json')]
    assert before['commit']==closed['commit']==manifest['commit']
    assert before['source_before']==closed['source_after'] and closed['source_unchanged']
    assert sha(at('.xml').read_bytes())==closed['report_sha256']
    suites=list(ET.parse(at('.xml')).getroot().iter('testsuite'))
    junit={key:sum(int(s.get(key,0)) for s in suites) for key in ('tests','failures','errors','skipped')}
    assert junit==closed['junit']
    assert sha(at('-sources.zip').read_bytes())==manifest['archive_sha256']
    with zipfile.ZipFile(at('-sources.zip')) as archive:
        members={row['path']:row for row in manifest['members']}
        assert len(archive.namelist())==len(set(archive.namelist()))==len(members)
        assert set(archive.namelist())==set(members)==set(before['source_before'])
        for name,row in members.items():
            raw=archive.read(name)
            assert len(raw)==row['bytes'] and sha(raw)==row['sha256']==before['source_before'][name]
    checks.append({'prefix':prefix,'commit':closed['commit'],'junit':junit,
        'source_archive_sha256':manifest['archive_sha256'],'report_sha256':closed['report_sha256'],
        'source_files':len(members),'wall_seconds':closed['wall_seconds'],'new_paid_calls':closed['new_paid_calls']})
    for suffix in ('-before.json','-closed.json','-source-members.json','-sources.zip','.xml','-watchdog-config.json','-watchdog.json'):
        if at(suffix).is_file():copy(at(suffix),'checks/'+prefix+suffix)
    if prefix not in prefixes[2:]:continue
    expected_tests = 50 if prefix==prefixes[2] else 11
    assert closed['exit_code']==0 and junit=={'tests':expected_tests,'failures':0,'errors':0,'skipped':0}
    roots=[]
    for case in (work/prefix).iterdir():
        if case.is_symlink():continue
        if case.name=='state-improvement0': roots.extend((case/'run/builds').iterdir())
        elif case.name.startswith(('test_actual_q63_grid_', 'test_foreign_builder_',
                                   'test_full_operation_', 'test_q62_')):
            roots.extend((case/'stage/cells').iterdir())
    # Report the actual selector coverage; do not silently claim omitted host families.
    expected_roots = 115 if prefix==prefixes[2] else 16
    assert len(roots)==expected_roots, (len(roots),[p.name for p in (work/prefix).iterdir() if not p.is_symlink()])
    resolver=ArchivedSourceResolver(at('-sources.zip'),manifest['archive_sha256'],tree)
    for root in sorted(roots):
        path=root/'proposal/artifacts.jsonl'
        original=path.read_bytes();first=json.loads(original.splitlines()[0])['descriptor']
        reader=ArtifactCatalogue(path,identity=DataIdentity(**first['identity']),**first['binding'],
            producer_source=first['producer_source'],source_resolver=resolver)
        records=reader.records();m9=[r.data() for r in records if r.data()['kind'].startswith('m9_')]
        def sources(value):
            if isinstance(value,dict):
                if set(value)=={'path','sha256','bytes'}:
                    name=Path(value['path']).relative_to(tree).as_posix()
                    assert members[name]['sha256']==value['sha256'] and members[name]['bytes']==value['bytes']
                else:
                    for child in value.values():sources(child)
            elif isinstance(value,list):
                for child in value:sources(child)
        for record in records:sources(record.data())
        assert len(m9)==7 and path.with_name(path.name+'.seal.json').is_file()
        assert [r.data()['payload']['canonical'] for r in records if r.data()['kind']=='trace_event']==[
            json.loads(line) for line in (root/'proposal/trace.jsonl').read_bytes().splitlines()]
        terminal=read(root/'m9-build-terminal.json')
        rel=root.relative_to(work/prefix).as_posix()
        included=[]
        for name in ('builder.json','m9-builder-return.json','builder-receipt.json','candidate.json',
                     'm9-build-terminal.json','phase.jsonl','build-receipt.json','cell-receipt.json'):
            if (root/name).is_file():included.append(root/name)
        for source in (root/'proposal').rglob('*'):
            if not source.is_file():continue
            name=source.relative_to(root/'proposal').as_posix()
            assert re.fullmatch(r'(trace|evidence|claims|predictions|reviews|artifacts)\.jsonl(?:\.seal\.json)?',name),name
            included.append(source)
        for source in included:
            assert not source.is_symlink()
            copy(source,'runtime/'+prefix+'/'+rel+'/'+source.relative_to(root).as_posix())
        assert path.read_bytes()==original
        witnesses.append({'prefix':prefix,'runtime':rel,'host':m9[0]['payload']['canonical']['host'],
            'status':terminal['status'],'descriptors':len(records),'builder_descriptors':len(m9),
            'files':len(included),'archived_catalogue_integrity_verified':True,
            'historical_host_semantic_replay_executed':False})
copy(work/"archive_proposal_builders_r1.py","tools/archive_proposal_builders_r1.py")
copy(work/"proposal-builder-archive-failure-r1.json","checks/proposal-builder-archive-failure-r1.json")
copy(Path(__file__),'tools/'+Path(__file__).name)
for name in ('proposal-host-activation-review-r1.md','proposal-host-activation-repro-r1.json',
             'fixture-builder-artifact-followup-r1.md'):
    copy(work/name,'reviews/'+name)
scope={'schema':'proposal-builder-public-archive-v1','checks':checks,'runtime_witnesses':witnesses,'items':items,
    'scope':'Selected builder files, proposal catalogues and host receipts; not complete host directories',
    'early_failures':'r1 fixture omitted M9 prerequisites; r2 fixture omitted required instruction; both preserved',
    'r3_known_finding':'All 50 checks passed, but read-only review found eight disabled Q6.5 arms incorrectly marked applied; original descriptors retained',
    'r4_scope':'Disabled-arm metadata repaired; 16 actual Q6.5 cells and label isolation checked; downstream guard artifacts remain a distinct open seam',
    'source_archives_verified':True,'new_paid_calls':0,'scientific_effectiveness_proven':False,
    'validation_acceptance':False,'all_module_output_coverage_complete':False}
(stage/'SCOPE.json').write_bytes((json.dumps(scope,indent=2)+'\n').encode())
(stage/'.gitattributes').write_bytes(b'* -text\n')
shutil.copytree(stage,dest)
assert all(p.read_bytes()==(dest/p.relative_to(stage)).read_bytes() for p in stage.rglob('*') if p.is_file())
print(json.dumps({'archive':str(dest),'files':len(items)+2,'witnesses':len(witnesses),
    'descriptors':sum(w['descriptors'] for w in witnesses)}))
