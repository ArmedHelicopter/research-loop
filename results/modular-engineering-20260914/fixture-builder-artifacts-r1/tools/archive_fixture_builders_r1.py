"""Archive frozen Q6.3 fixture checks and selected original public directories."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import xml.etree.ElementTree as ET
import zipfile

work=Path(__file__).resolve().parent
tree=work.parent/'artifact-evidence-provenance'
stage=work/'fixture-builder-artifacts-staging-r1'
dest=tree/'results/modular-engineering-20260914/fixture-builder-artifacts-r1'
prefixes={'fixture-builder-artifacts-r1':(84,9),'fixture-builder-artifacts-r2':(86,10)}
assert not stage.exists() and not dest.exists()
assert all((work/(p+'-closed.json')).is_file() for p in prefixes)
sys.path.insert(0,str(tree))
from research_loop.modular.artifact_catalogue import ArtifactCatalogue
from research_loop.modular.artifact_source_archive import ArchivedSourceResolver
from research_loop.modular.contracts import DataIdentity, FrozenRecord

sha=lambda raw:hashlib.sha256(raw).hexdigest()
read=lambda path:json.loads(path.read_bytes())
stage.mkdir();items=[];checks=[];witnesses=[]
def copy(path,relative):
    raw=path.read_bytes();target=stage/relative;target.parent.mkdir(parents=True,exist_ok=True)
    with target.open('xb') as stream:stream.write(raw)
    items.append({'path':relative,'bytes':len(raw),'sha256':sha(raw),'original':str(path)})

for prefix,(expected_tests,expected_roots) in prefixes.items():
    at=lambda suffix:work/(prefix+suffix)
    before,closed,manifest=[read(at(s)) for s in ('-before.json','-closed.json','-source-members.json')]
    assert before['commit']==closed['commit']==manifest['commit']
    assert before['source_before']==closed['source_after'] and closed['source_unchanged'] and closed['exit_code']==0
    assert sha(at('.xml').read_bytes())==closed['report_sha256']
    suites=list(ET.parse(at('.xml')).getroot().iter('testsuite'))
    junit={key:sum(int(s.get(key,0)) for s in suites) for key in ('tests','failures','errors','skipped')}
    assert junit==closed['junit']=={'tests':expected_tests,'failures':0,'errors':0,'skipped':0}
    assert sha(at('-sources.zip').read_bytes())==manifest['archive_sha256']
    with zipfile.ZipFile(at('-sources.zip')) as archive:
        members={row['path']:row for row in manifest['members']}
        assert len(archive.namelist())==len(set(archive.namelist()))==len(members)
        assert set(archive.namelist())==set(members)==set(before['source_before'])
        for name,row in members.items():
            raw=archive.read(name)
            assert len(raw)==row['bytes'] and sha(raw)==row['sha256']==before['source_before'][name]
    checks.append({'prefix':prefix,'commit':closed['commit'],'junit':junit,'source_files':len(members),
        'source_archive_sha256':manifest['archive_sha256'],'report_sha256':closed['report_sha256'],
        'wall_seconds':closed['wall_seconds'],'new_paid_calls':closed['new_paid_calls']})
    for suffix in ('-before.json','-closed.json','-source-members.json','-sources.zip','.xml','-watchdog-config.json','-watchdog.json'):
        if at(suffix).is_file():copy(at(suffix),'checks/'+prefix+suffix)
    roots=[case/'run' for case in sorted((work/prefix).iterdir()) if not case.is_symlink()
        and case.name.startswith(('test_actual_fixture_','test_invalid_original_',
                                 'test_actual_failed_fixture_','test_failure_after_registry_'))]
    assert len(roots)==expected_roots
    resolver=ArchivedSourceResolver(at('-sources.zip'),manifest['archive_sha256'],tree)
    def sources(value):
        if isinstance(value,dict):
            if set(value)=={'path','sha256','bytes'}:
                name=Path(value['path']).relative_to(tree).as_posix()
                assert members[name]['sha256']==value['sha256'] and members[name]['bytes']==value['bytes']
            else:
                for child in value.values():sources(child)
        elif isinstance(value,list):
            for child in value:sources(child)
    for root in roots:
        path=root/'fixture-artifacts.jsonl';original=path.read_bytes();first=json.loads(original.splitlines()[0])['descriptor']
        catalogue=ArtifactCatalogue(path,identity=DataIdentity(**first['identity']),**first['binding'],
            producer_source=first['producer_source'],source_resolver=resolver)
        records=catalogue.records()
        for record in records:sources(record.data())
        terminal=read(root/'fixture-terminal.json');seal=FrozenRecord.from_dict(read(root/'fixture-artifacts.jsonl.seal.json'))
        catalogue.verify(seal)
        raw_terminal=(root/'fixture-terminal.json').read_bytes()
        assert read(root/'fixture-closure.json')=={'schema':'q63-fixture-closure-v1','catalogue_seal':seal.data(),
            'terminal':{'file':'fixture-terminal.json','sha256':sha(raw_terminal),'bytes':len(raw_terminal),'canonical':terminal}}
        last=records[-1].data()
        assert last['kind']=='fixture_terminal' and last['payload']['canonical']['canonical']==terminal
        all_files=sorted(p for p in root.rglob('*') if p.is_file())
        actual_files={}
        for source in all_files:
            name=source.relative_to(root).as_posix();assert not source.is_symlink()
            assert re.fullmatch(r'(builder\.json|builder-receipt\.json|builders\.sqlite|candidate\.json|'
                r'm9-build-terminal\.json|m9-builder-return\.json|fixture-(?:closure|result|terminal)\.json|'
                r'fixture-artifacts\.jsonl(?:\.seal\.json)?|fixture-blobs/[0-9a-f]{64})',name),name
            raw=source.read_bytes()
            if name.startswith('fixture-blobs/'):assert source.name==sha(raw)
            if name not in {'fixture-artifacts.jsonl','fixture-artifacts.jsonl.seal.json','fixture-terminal.json','fixture-closure.json'}:
                actual_files[name]={'sha256':sha(raw),'bytes':len(raw)}
            copy(source,'runtime/'+prefix+'/'+root.relative_to(work/prefix).as_posix()+'/'+name)
        assert actual_files==terminal['files'] and path.read_bytes()==original
        witnesses.append({'prefix':prefix,'runtime':root.relative_to(work/prefix).as_posix(),
            'variant':first['payload']['canonical']['injection']['variant'],'status':terminal['status'],
            'stage':terminal['stage'],'descriptors':len(records),'files':len(all_files),
            'archived_catalogue_integrity_verified':True,'historical_semantic_replay_executed':False})
copy(Path(__file__),'tools/'+Path(__file__).name)
scope={'schema':'fixture-builder-public-archive-v1','checks':checks,'runtime_witnesses':witnesses,'items':items,
    'scope':'Complete selected Q6.3 fixture directories, including actual failed calls and post-commit registry failure',
    'fixture_only':True,'new_paid_calls':0,'scientific_effectiveness_proven':False,
    'validation_acceptance':False,'failure_reader_scope':'Storage integrity, not stage semantic acceptance',
    'all_module_output_coverage_complete':False}
(stage/'SCOPE.json').write_bytes((json.dumps(scope,indent=2)+'\n').encode())
(stage/'.gitattributes').write_bytes(b'* -text\n')
shutil.copytree(stage,dest)
assert all(p.read_bytes()==(dest/p.relative_to(stage)).read_bytes() for p in stage.rglob('*') if p.is_file())
print(json.dumps({'archive':str(dest),'files':len(items)+2,'runtime_witnesses':len(witnesses),
    'descriptors':sum(w['descriptors'] for w in witnesses)}))
