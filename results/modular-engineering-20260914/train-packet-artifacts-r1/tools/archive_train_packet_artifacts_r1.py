"""Archive P0 check history and explicitly selected public export evidence."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import xml.etree.ElementTree as ET
import zipfile

work=Path(__file__).resolve().parent; tree=work.parent/'artifact-evidence-provenance'
stage=work/'train-packet-artifacts-staging-r1'
dest=tree/'results/modular-engineering-20260914/train-packet-artifacts-r1'
assert not stage.exists() and not dest.exists()
sys.path.insert(0,str(tree))
from evaluation.modular.train_packet_artifacts import verify_train_export_artifacts
from research_loop.modular.artifact_catalogue import ArtifactCatalogue
from research_loop.modular.artifact_source_archive import ArchivedSourceResolver
from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask

R=FrozenRecord.from_dict; sha=lambda raw:hashlib.sha256(raw).hexdigest()
read=lambda path:json.loads(path.read_bytes())
prefixes={'train-packet-artifacts-r1':(80,1),'train-packet-combination-r1':(1,0),
    'train-packet-artifacts-r2':(82,1),'train-packet-artifacts-r3':(87,0)}
checks=[]; items=[]; exports=[]; catalogues=[]
stage.mkdir()

def copy(path,relative):
    raw=path.read_bytes(); target=stage/relative; target.parent.mkdir(parents=True,exist_ok=True)
    with target.open('xb') as stream: stream.write(raw)
    items.append({'path':relative,'original':str(path),'bytes':len(raw),'sha256':sha(raw)})

for prefix,(tests,failures) in prefixes.items():
    at=lambda suffix:work/(prefix+suffix)
    before,closed,manifest=[read(at(s)) for s in ('-before.json','-closed.json','-source-members.json')]
    assert before['commit']==closed['commit']==manifest['commit']
    assert before['source_before']==closed['source_after'] and closed['source_unchanged']
    assert closed['exit_code']==int(bool(failures))
    suites=list(ET.parse(at('.xml')).getroot().iter('testsuite'))
    junit={key:sum(int(s.get(key,0)) for s in suites) for key in ('tests','failures','errors','skipped')}
    assert junit==closed['junit']=={'tests':tests,'failures':failures,'errors':0,'skipped':0}
    assert sha(at('.xml').read_bytes())==closed['report_sha256']
    assert sha(at('-sources.zip').read_bytes())==manifest['archive_sha256']
    with zipfile.ZipFile(at('-sources.zip')) as archive:
        members={row['path']:row for row in manifest['members']}
        assert len(archive.namelist())==len(set(archive.namelist()))==len(members)
        assert set(archive.namelist())==set(members)==set(before['source_before'])
        for name,row in members.items():
            raw=archive.read(name)
            assert len(raw)==row['bytes'] and sha(raw)==row['sha256']==before['source_before'][name]
    checks.append({'prefix':prefix,**{k:v for k,v in closed.items() if k!='source_after'},
        'source_archive_sha256':manifest['archive_sha256']})
    for suffix in ('-before.json','-closed.json','-source-members.json','-sources.zip','.xml','-watchdog-config.json','-watchdog.json'):
        if at(suffix).is_file():copy(at(suffix),'checks/'+prefix+suffix)

prefix='train-packet-artifacts-r3'; tested=work/prefix
resolver=ArchivedSourceResolver(work/(prefix+'-sources.zip'),checks[-1]['source_archive_sha256'],tree)
selection=[
    ('test_real_export_files_and_bat0','export','export-audit','completed'),
    ('test_real_export_files_and_bat1','public-train','export-audit','completed'),
    ('test_actual_partial_write_fail0','export-audit/attempt-000001/staging','export-audit','failed'),
    ('test_audit_writer_failure_pres0','export-audit/attempt-000001/staging','export-audit','incomplete'),
    ('test_actual_controller_consume0','controller-export','controller-export-audit','completed'),
    ('test_actual_controller_consume0','fixture/pre-export','fixture/export-audit','completed'),
    ('test_all_three_actual_controll0','export','export-audit','completed'),
    ('test_all_three_actual_controll0','primary/prepared','primary/export-audit','completed'),
]
for case,folder,audit,status in selection:
    root=tested/case/folder; journal=tested/case/audit/'exports.jsonl'
    original=journal.read_bytes(); previous='0'*64; events=[]
    for number,line in enumerate(original.splitlines(),1):
        event=json.loads(line); entry=event.pop('entry_sha256')
        assert entry==R(event).content_hash and event['sequence']==number and event['previous_sha256']==previous
        previous=entry; events.append(event)
    assert events[-1]['event']==('export_completed' if status=='completed' else 'export_failed')
    roots=sorted(p for p in root.iterdir() if p.is_dir()); assert len(roots)==(2 if status=='completed' else 1)
    if status=='completed':
        batch=R(read(root/'export-receipt.json')); tasks=[]
        for anchor in batch.data()['artifact_catalogues']:
            public=read(root/anchor['token']/'public.json')
            task=public['task'] if 'task' in public else public
            tasks.append(PublicTask.create(DataIdentity.parse(task['identity']),task['payload']))
        verify_train_export_artifacts(root,batch,tuple(tasks))
        assert events[-1]['receipt_sha256']==batch.content_hash
    for packet in roots:
        path=packet/'artifacts.jsonl'; first=json.loads(path.read_bytes().splitlines()[0])['descriptor']
        reader=ArtifactCatalogue(path,identity=DataIdentity(**first['identity']),**first['binding'],
            producer_source=first['producer_source'],source_resolver=resolver)
        records=reader.records(); is_sealed=reader.seal_path.is_file()
        assert is_sealed==(status!='incomplete')
        if is_sealed:reader.verify(R(read(reader.seal_path)))
        binding=records[0].data()['payload']['canonical']; reservation=binding['exposure_reservation']
        exposure=events[reservation['sequence']-1]
        assert R(exposure).content_hash==reservation['head'] and exposure['event']=='exposure_reserved'
        assert packet.name in exposure['possibly_exposed_tokens']
        if status=='failed':assert records[-1].data()['status']=='failed'
        if status=='incomplete':assert len(records)==1
        catalogues.append({'path':'public/'+path.relative_to(tested).as_posix(),'descriptors':len(records),
            'sealed':is_sealed,'state':status,'historical_semantic_replay_executed':False})
    for path in sorted(root.rglob('*')):
        if not path.is_file():continue
        assert not path.is_symlink() and path.name in {'public.json','data.csv','receipt.json','artifacts.jsonl',
            'artifacts.jsonl.seal.json','export-receipt.json'}
        copy(path,'public/'+path.relative_to(tested).as_posix())
    copy(journal,'public/'+journal.relative_to(tested).as_posix())
    exports.append({'case':case,'folder':folder,'audit':audit,'status':status,'packets':len(roots),
        'source_event_prefix_verified':True,'private_source_archived':False})

# Keep original public controller outcomes; omit provider streams and all
# synthetic/private scorer stores and credentials.
controller_reads=[]
for case in ('test_actual_controller_consume0','test_all_three_actual_controll0'):
    root=tested/case/'run'; invocations=0; tracefiles=0
    for path in root.rglob('trace.jsonl'):
        tracefiles+=1
        for line in path.read_bytes().splitlines():
            event=json.loads(line)
            if event.get('stage')=='execution_result':
                receipt=event.get('data',{}).get('receipt',{}).get('record',{})
                if receipt.get('argv',[])[:2]==['docker','run']:invocations+=1
    for name in ('controller-attempt.json','controller-receipt.json'):
        if (root/name).is_file():copy(root/name,'controllers/'+case+'/'+name)
    controller_reads.append({'case':case,'tracefiles':tracefiles,'observed_docker_run_receipts':invocations})

copy(Path(__file__),'tools/'+Path(__file__).name)
scope={'schema':'train-packet-artifact-public-archive-v1','checks':checks,'exports':exports,'catalogues':catalogues,
    'controller_observations':controller_reads,'items':items,'source_prefix':'train-packet-artifacts-r3',
    'source_archive_sha256':checks[-1]['source_archive_sha256'],'new_paid_calls':0,
    'scientific_effectiveness_proven':False,'validation_acceptance':False,'all_P0_output_coverage_complete':False,
    'scope':'All frozen check receipts, including failed attempts. Selected final-version complete public TRAIN export directories and redacted export journals, including a sealed failed packet and an unsealed interrupted prefix. Earlier runtime directories and deliberately corrupted counterexamples are not copied. Private source snapshots, split/VAL indexes, scorer stores, provider streams and credentials are excluded. Public packet semantics were checked against live originals before archiving; archived catalogue/source integrity readback is not full historical exporter replay.'}
(stage/'SCOPE.json').write_bytes((json.dumps(scope,indent=2)+'\n').encode())
(stage/'.gitattributes').write_bytes(b'* -text\n')
shutil.copytree(stage,dest)
assert all(p.read_bytes()==(dest/p.relative_to(stage)).read_bytes() for p in stage.rglob('*') if p.is_file())
print(json.dumps({'archive':str(dest),'files':len(items)+2,'exports':len(exports),
    'catalogues':len(catalogues),'descriptors':sum(r['descriptors'] for r in catalogues),
    'controller_observations':controller_reads}))
