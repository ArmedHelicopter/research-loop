"""Preflight all closed inputs, then archive raw bytes without private payloads."""
import hashlib
import io
import json
import shutil
import subprocess
import tarfile
import zipfile
from pathlib import Path
import xml.etree.ElementTree as ET

B=Path('E:/_ryanDev/AI/research-loop-modular'); W=B/'work'; R=B/'integration'
A=R/'results/modular-engineering-20260912'; D=A/'reference-combinations-linked-20260913'
def read(path): return json.loads(Path(path).read_bytes())
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8',newline='\n') as stream:
        json.dump(value,stream,indent=2,ensure_ascii=False);stream.write('\n')
def git(tree,*args): return subprocess.check_output(['git',*args],cwd=tree)

source=git(R,'rev-parse','HEAD').decode().strip()
root_closed=read(W/'pred-lineage-integrated-closed-freeze-verification-r1.json')
assert source==root_closed['source_commit'] and not git(R,'status','--porcelain').strip()
assert not D.exists()
old=read(A/'SHA256.json');assert len(old)==1680
assert all(sha(A/name)==expected for name,expected in old.items())
copies={};grids={};sources=set();report_counts={}
def plan(path,name,expected=None):
    path=Path(path)
    assert path.is_file() and not path.is_symlink() and not path.is_junction(),str(path)
    value=sha(path);assert expected is None or value==expected,str(path)
    row={'source':str(path),'sha256':value,'bytes':path.stat().st_size}
    assert name not in copies or copies[name]==row,name
    copies[name]=row
def report(path,name,expected=None):
    plan(path,name,expected)
    suite=ET.parse(path).getroot().find('testsuite')
    assert suite is not None
    report_counts[name]=dict(suite.attrib)
def grid(name,root,paths):
    assert name not in grids
    root=Path(root);files={}
    for path in sorted(set(paths)):
        assert path.is_relative_to(root) and path.is_file() and not path.is_symlink() and not path.is_junction(),str(path)
        files[path.relative_to(root).as_posix()]={'sha256':sha(path),'bytes':path.stat().st_size}
    assert files,name
    grids[name]=(root,files)
def safe_runtime_grid(name,root):
    # Explicit synthetic runtime paths; exclude reference stores, keys, configs,
    # public task/CSV copies and raw evaluator requests.
    root=Path(root);assert (root/'run').is_dir(),str(root)
    paths=[p for p in (root/'run').rglob('*') if p.is_file()]
    for relative in ('port/ledger.json','solver/ledger.json','independent-fixture-authority.json',
                     'signed-fixture-primary-scores.json'):
        path=root/relative
        if path.is_file(): paths.append(path)
    for worker in root.glob('worker[0-9]'):
        for relative in ('client.jsonl','server.jsonl','evaluator/ledger.json'):
            path=worker/relative
            if path.is_file(): paths.append(path)
    grid(name,root,paths)
def original_archive(tree,folder,head,count):
    tree=B/tree;prefix='results/modular-engineering-20260913/'+folder;root=tree/prefix
    assert git(tree,'rev-parse','HEAD').decode().strip()==head
    assert not git(tree,'status','--porcelain').strip()
    final=read(root/'FINAL-VERIFICATION.json');manifest=read(root/'ARTIFACT-MANIFEST.json')
    assert final['artifact_manifest_sha256']==sha(root/'ARTIFACT-MANIFEST.json')
    for name,expected in manifest['files'].items():assert sha(root/name)==expected,name
    paths={p.relative_to(tree).as_posix():sha(p) for p in root.rglob('*') if p.is_file()}
    assert len(paths)==count
    with tarfile.open(fileobj=io.BytesIO(git(tree,'archive',head,prefix))) as tar:
        blobs={m.name:hashlib.sha256(tar.extractfile(m).read()).hexdigest() for m in tar if m.isfile()}
    assert blobs==paths
    grid(folder,root,[root/name[len(prefix)+1:] for name in paths])
    for path in root.iterdir():
        if path.is_file():plan(path,folder+'/'+path.name)
    for path in (root/'reports').glob('*.xml'):report(path,folder+'/reports/'+path.name)
    return final

# Previously reviewed independent scoring implementation and its retained failures.
lps=read(W/'lps-verification.json')
plan(W/'lps-verification.json','lineage-process/verification.json','be8106d1a0c8dd2c23d98b466389826bb2f53a297c7b68fc87f9da41b4189e78')
for name,expected in lps['source_hashes'].items():
    plan(B/'lineage-process-scoring'/name,'lineage-process/frozen-source/'+name,expected);sources.add(name)
for row in lps['reports']:report(row['file'],'lineage-process/reports/'+Path(row['file']).name,row['sha256'])
for index,row in enumerate(lps['runs']):safe_runtime_grid('lineage-process-run-'+str(index),row['run'])

# Reference bridge: include metadata audit journals and explicitly retained invalid
# development result; no actual private reference payload is copied.
ref=read(B/'pr-ref/docs/primary-reference-bridge-verification.json')
plan(B/'pr-ref/docs/primary-reference-bridge-verification.json','reference/fixture-verification.json')
for row in ref['junit']:report(row['path'],'reference/reports/'+Path(row['path']).name,row['sha256'])
for row in ref['artifact_pins']:plan(row['path'],'reference/fixture/'+Path(row['path']).name,row['sha256'])
for group in ref['reference_attempt_denominators']:
    for row in group['journals']:
        path=Path(row['path']);relative=path.relative_to(W/'primary-reference-checks').as_posix()
        plan(path,'reference/fixture-journals/'+relative,row['sha256'])
for row in ref['new_bridge_scorer_process_fixture_calls']:
    plan(row['path'],'reference/fixture-counts/'+row['run']+'.json',row['sha256'])
for name in git(B/'pr-ref','diff','--name-only','b9f7ff4','574bfbf','--','research_loop','evaluation','tests','docs').decode().splitlines():
    plan(B/'pr-ref'/name,'reference/frozen-source/'+name);sources.add(name)
live=W/'primary-prospective-reference-live-r1';delivery=read(live/'delivery-manifest-r1.json')
plan(live/'delivery-manifest-r1.json','reference/live/delivery-manifest-r1.json','1c5b4ad41c2eb834b32d62c2eb85148c9f76f1a6a53996a0029ad92a4717526a')
for row in delivery['metadata_artifacts']:
    path=Path(row['path'])
    if path.is_relative_to(live): name=path.relative_to(live).as_posix()
    else: name='private-metadata/'+path.parent.name+'/'+path.name
    plan(path,'reference/live/'+name,row['sha256'])
private_descriptors=delivery['private_reference_artifacts']
for row in private_descriptors:assert sha(row['path'])==row['sha256']

# Complete bounded combination and prediction-order archives from isolated agents.
mrr=original_archive('retrieval-review-combinations','retrieval-review-combinations',
    '177660c432e5d7904025bf6579b150d48a988c74',406)
prediction=original_archive('pred-order','prediction-linked-order',
    '8f482ba03ea9366561358442d42b1543e15ca2d2',396)
for tree,base,head,label in [('retrieval-review-combinations','0073c9e','0f94d70','retrieval-review-combinations'),
                             ('pred-order','62b1ddb','16d649f','prediction-linked-order'),
                             ('ret-public','0063ca1','edb54f8','retrieval-public-boundary')]:
    for name in git(B/tree,'diff','--name-only',base,head,'--','research_loop','evaluation','tests','docs').decode().splitlines():
        plan(B/tree/name,label+'/frozen-source/'+name);sources.add(name)

lsl=read(W/'lsl-verification.json')
plan(W/'lsl-verification.json','lineage-linked/verification.json','369f1e8701e9a1a2d92affa5e09008bf0de7205a2ee06f1dbb062506a89aa8f5')
assert git(B/'lineage-linked','rev-parse','HEAD').decode().strip()==lsl['commit']
assert not git(B/'lineage-linked','status','--porcelain').strip()
for name,expected in lsl['source_hashes'].items():
    plan(B/'lineage-linked'/name,'lineage-linked/frozen-source/'+name,expected);sources.add(name)
for name,row in lsl['reports'].items():report(W/name,'lineage-linked/reports/'+name,row['sha256'])
for kind in ('normal_groups','source_failure_groups'):
    for index,row in enumerate(lsl[kind]):safe_runtime_grid('lineage-linked-'+kind+'-'+str(index),row['path'])
safe_runtime_grid('retrieval-public-boundary-grid',W/'ret-public-frozen-r1/retrieval-linked-grid0')

# All root reports and contemporaneous source manifests are explicit files.
root_names=['lps-root-integration-verification-r1.json','lps-integrated-root-r1.xml','lps-integrated-root-r2.xml',
 'reference-lineage-root-r1.xml','reference-lineage-root-source-before-r1.json','reference-lineage-root-closed-freeze-verification-r1.json',
 'pred-linked-red-r1.xml','pred-linked-dev-r1.xml','pred-linked-frozen-r1.xml','pred-linked-source-before-r1.json','pred-linked-root-closed-freeze-verification-r1.json',
 'ret-public-red-r1.xml','ret-public-frozen-r1.xml','ret-public-source-before-r1.json','ret-public-root-closed-freeze-verification-r1.json',
 'mrr-lineage-integrated-r1.xml','mrr-lineage-source-before-r1.json','mrr-lineage-root-closed-freeze-verification-r1.json',
 'retrieval-boundary-integrated-r1.xml','retrieval-boundary-integrated-source-before-r1.json','retrieval-boundary-integrated-closed-freeze-verification-r1.json',
 'pred-lineage-integrated-r1.xml','pred-lineage-integrated-source-before-r1.json','pred-lineage-integrated-closed-freeze-verification-r1.json',
 'verify_closed_root_freezes_20260913.py','verify_primary_reference_live_root_20260913.py','primary-reference-live-root-metadata-verification-r1.json',
 'verify_mrr_delivery_root_20260913.py','mrr-delivery-root-verification-r1.json','all48-export-linked-archive-index-verification-r1.json']
for name in root_names:
    if name.endswith('.xml'): report(W/name,'root/'+name)
    else:plan(W/name,'root/'+name)
audit=W/'primary-scoring-calibration-audit-r1';audit_delivery=read(audit/'delivery-manifest-r1.json')
plan(audit/'delivery-manifest-r1.json','scoring-audit/delivery-manifest-r1.json','a0e91a2d9ac35e933e82850397dd10bb7a09f31a337973db856d831c34aa0f28')
for row in audit_delivery['files']:plan(row['path'],'scoring-audit/'+Path(row['path']).name,row['sha256'])
for name in sources:plan(R/name,'integrated-source/'+name)
plan(Path(__file__),Path(__file__).name)
assert all(sha(R/name)==expected for name,expected in root_closed['source_files_after'].items())

# No destination mutation occurs before all sources above are present and pinned.
for name,row in copies.items():
    path=Path(row['source']);assert sha(path)==row['sha256']
    destination=D/name;destination.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(path,destination);assert sha(destination)==row['sha256']
for name,(root,files) in grids.items():
    path=D/'synthetic-grids'/(name+'.zip');path.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(path,'x',zipfile.ZIP_DEFLATED) as archive:
        for relative,row in files.items():
            assert sha(root/relative)==row['sha256']
            archive.write(root/relative,relative)
    with zipfile.ZipFile(path) as archive:
        assert set(archive.namelist())==set(files)
        assert all(hashlib.sha256(archive.read(n)).hexdigest()==row['sha256'] for n,row in files.items())
    write(D/'synthetic-grids'/(name+'-hashes.json'),files)
write(D/'reference/live/private-reference-hashes-only.json',{'reason':'Private TRAIN reference bodies remain outside the archive.','artifacts':private_descriptors})
write(D/'ORIGINS.json',copies)
write(D/'checkpoint.json',{'schema':'reference-combinations-linked-checkpoint-v1','source_commit':source,
    'registered_question_drivers':43,'separate_Q6_phases':5,'question_execution_contracts':48,
    'generic_linked_benchmark_scopes':['Q1.1','Q1.2','Q1.3','Q1.4','Q1.5','Q3.1','Q3.2','Q4.3','Q5.3','Q8.2','Q8.3'],
    'wired_pair_controllers':6,'remaining_pair_controllers':30,'wired_triple_controllers':2,'remaining_triple_controllers':3,
    'full_loo_and_final_train_selected_bundle':'open','pruned_combinations':[],
    'root_reports':report_counts,'synthetic_zip_members':{name:len(rows) for name,(_,rows) in grids.items()},
    'new_primary_reference_items':4,'primary_reference_attempts':1,'primary_reference_journal_events':8,
    'primary_private_reference_payloads_archived':0,'new_actual_paid_calls':0,
    'retrieval_review_grid':{'cells':32,'model_calls':160,'provider_calls':96,'docker':32,'primary_process_fixture_scores':32},
    'lineage_linked_grid':{'cells':58,'model_calls':290,'docker':58,'primary_process_fixture_scores':58},
    'prediction_linked_grid':prediction['prediction_grid'],'Q3.2_mechanism':'planning_only',
    'earlier_public_input_and_chronology_limitations':'retained_with_original_reports',
    'scientific_mechanism_effects':'not_measured','official_primary_score_equivalence':'not_established',
    'scorer_calibration':'not_measured','validation_acceptance':'not_run','primary_validation_stays_sealed':95,
    'SAB_validation_records_on_hold':18,'BLADE_validation_groups':1})
updated=dict(old)
for path in D.rglob('*'):
    if path.is_file():
        relative=path.relative_to(A).as_posix();assert relative not in updated;updated[relative]=sha(path)
assert all(sha(A/name)==value for name,value in old.items())
(A/'SHA256.json').write_text(json.dumps(dict(sorted(updated.items())),indent=2)+'\n',encoding='utf-8',newline='\n')
print(json.dumps({'source_commit':source,'old_unchanged':len(old),'indexed_files':len(updated),
    'new_files':len(updated)-len(old),'zip_members':{name:len(rows) for name,(_,rows) in grids.items()}}))
