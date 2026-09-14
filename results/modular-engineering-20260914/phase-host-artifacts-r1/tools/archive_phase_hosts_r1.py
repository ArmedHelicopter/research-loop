"""Preserve exact phase-host checks and all selected public runtime witnesses."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import xml.etree.ElementTree as ET
import zipfile

WORK=Path(__file__).resolve().parent
TREE=WORK.parent/'artifact-evidence-provenance'
STAGE=WORK/'phase-host-artifacts-staging-r1'
DEST=TREE/'results/modular-engineering-20260914/phase-host-artifacts-r1'
PREFIXES=('phase-host-seams-r1','phase-host-seams-r2')
sys.path.insert(0,str(TREE))
from research_loop.modular.contracts import FrozenRecord as R
assert not STAGE.exists() and not DEST.exists()
assert all((WORK/(prefix+'-closed.json')).is_file() for prefix in PREFIXES)
STAGE.mkdir();items=[];checks=[];witnesses=[]
sha=lambda raw:hashlib.sha256(raw).hexdigest()
read=lambda path:json.loads(path.read_bytes())
def copy(path,relative):
    raw=path.read_bytes();target=STAGE/relative;target.parent.mkdir(parents=True,exist_ok=True)
    with target.open('xb') as stream:stream.write(raw)
    items.append({'path':relative,'bytes':len(raw),'sha256':sha(raw),'original':str(path)})

for prefix in PREFIXES:
    at=lambda suffix:WORK/(prefix+suffix)
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
        def sources(value):
            if isinstance(value,dict):
                if set(value)=={'path','sha256','bytes'}:
                    name=Path(value['path']).relative_to(TREE).as_posix();raw=archive.read(name)
                    assert len(raw)==value['bytes'] and sha(raw)==value['sha256']
                else:
                    for child in value.values():sources(child)
            elif isinstance(value,list):
                for child in value:sources(child)
        if prefix=='phase-host-seams-r1':
            selected=[WORK/prefix/'test_actual_phase_before_any_m2/actual-host']
        else:
            selected=[case/'actual-host' for case in sorted((WORK/prefix).iterdir())
                if re.fullmatch(r'test_actual_(?:composite_host_and|phase_before_any_m)\d+',case.name)]
            assert len(selected)==18
            targets=sorted((WORK/prefix/'execution-improvement0/run/targets').iterdir())
            assert len(targets)==32
            selected+=targets
        for root in selected:
            rel=root.relative_to(WORK/prefix).as_posix()
            files=sorted(path for path in root.rglob('*') if path.is_file())
            for path in files:
                name=path.relative_to(root).as_posix()
                assert re.fullmatch(r'(source-verification\.json|'
                    r'phase/(?:[0-9a-f]{64}\.(?:py|json)|allocation\.json|events\.jsonl|queue\.sqlite|receipt\.json)|'
                    r'phase-artifacts/blobs/[0-9a-f]{64}|'
                    r'runtime/(?:analysis-1\.py|artifacts\.jsonl(?:\.seal\.json)?|trace\.jsonl|evidence\.jsonl|'
                    r'claims\.jsonl|predictions\.jsonl|reviews\.jsonl))',name),name
                assert not path.is_symlink()
                if name.startswith('phase-artifacts/blobs/'):assert path.name==sha(path.read_bytes())
                copy(path,'runtime/'+prefix+'/'+rel+'/'+name)
            entries=[R(line.decode()) for line in (root/'runtime/artifacts.jsonl').read_bytes().splitlines()]
            previous=None;seen=set();traces=[];kinds={}
            for index,entry in enumerate(entries):
                row=entry.data();descriptor=R.from_dict(row['descriptor']);body=descriptor.data()
                assert row['sequence']==index and row['previous']==previous and row['descriptor_digest']==descriptor.content_hash
                assert descriptor.content_hash not in seen and set(body['parents'])<=seen
                sources(body);kinds[body['kind']]=kinds.get(body['kind'],0)+1
                if body['kind']=='trace_event':traces.append(body['payload']['canonical'])
                seen.add(descriptor.content_hash);previous=entry.content_hash
            assert traces==[json.loads(line) for line in (root/'runtime/trace.jsonl').read_bytes().splitlines()]
            assert kinds['execution_phase_inputs']==kinds['phase_allocation']==kinds['phase_receipt']==1
            assert kinds['phase_program']==kinds['phase_return']==2
            closed_trace=[event for event in traces if event['stage']=='audited_phase_closed']
            assert len(closed_trace)==1
            anchor=closed_trace[0]['data'];count=anchor['catalogue_prefix_count']
            assert entries[count-1].content_hash==anchor['catalogue_prefix_head']
            assert anchor['phase_digest']==R.from_dict(read(root/'phase/receipt.json')).content_hash
            witness={'prefix':prefix,'runtime':rel,'descriptors':len(entries),'trace_gap':0,
                'phase_status':read(root/'phase/receipt.json')['status'],'kinds':kinds,
                'trace_prefix_anchor_verified':True,'archived_source_bytes_verified':True,'file_count':len(files)}
            witnesses.append(witness)
    checks.append({'prefix':prefix,'commit':before['commit'],'junit':junit,'source_files':len(members),
        'source_archive_sha256':manifest['archive_sha256'],'report_sha256':closed['report_sha256'],
        'wall_seconds':closed['wall_seconds'],'new_paid_calls':closed['new_paid_calls']})
    for suffix in ('-before.json','-closed.json','-source-members.json','-sources.zip','.xml','-watchdog-config.json','-watchdog.json'):
        if at(suffix).is_file():copy(at(suffix),'checks/'+prefix+suffix)
copy(Path(__file__),'tools/'+Path(__file__).name)
copy(WORK/'standalone-builder-artifact-design-r1.md','reviews/standalone-builder-artifact-design-r1.md')
scope={'schema':'phase-host-artifact-archive-v1','checks':checks,'runtime_witnesses':witnesses,'items':items,
    'scope':'Actual Docker, synthetic public TRAIN engineering; six sampled host seams and full 32-target execution-improvement grid',
    'failure':'r1 rejected a correctly task-bound opaque early failure; r2 repairs the reader without accepting foreign cell digests',
    'semantic_replay_in_historical_environment':False,'private_credentials_or_provider_streams_included':False,
    'scientific_effectiveness_proven':False,'validation_acceptance':False,'all_module_output_coverage_complete':False}
(STAGE/'SCOPE.json').write_bytes((json.dumps(scope,indent=2)+'\n').encode())
(STAGE/'.gitattributes').write_bytes(b'* -text\n')
shutil.copytree(STAGE,DEST)
assert all(path.read_bytes()==(DEST/path.relative_to(STAGE)).read_bytes() for path in STAGE.rglob('*') if path.is_file())
print(json.dumps({'archive':str(DEST),'files':len(items)+2,'runtime_witnesses':len(witnesses),
    'descriptors':sum(row['descriptors'] for row in witnesses)}))
