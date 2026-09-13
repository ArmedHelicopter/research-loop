"""Archive closed engineering evidence after preflighting every source path."""
import hashlib, json, shutil, subprocess, zipfile
from pathlib import Path
import xml.etree.ElementTree as ET

B=Path('E:/_ryanDev/AI/research-loop-modular'); R=B/'integration'; W=B/'work'
A=R/'results/modular-engineering-20260912'; D=A/'all48-export-linked-20260913'
def read(p): return json.loads(p.read_bytes())
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p, value):
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open('x', encoding='utf-8', newline='\n') as f:
        json.dump(value, f, ensure_ascii=False, indent=2); f.write('\n')

head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip()
assert head=='b9f7ff46030f16ddfe321c616bf863b92fc9a08c'
assert not subprocess.check_output(['git','status','--porcelain'],cwd=R,text=True).strip()
assert not D.exists()
old=read(A/'SHA256.json'); assert len(old)==1595
assert all(sha(A/p)==v for p,v in old.items())
copies={}
def plan(path, name, expected=None):
    p=Path(path)
    assert p.is_file() and not p.is_symlink() and not p.is_junction(), str(p)
    value=sha(p); assert expected is None or expected==value, str(p)
    assert name not in copies, name
    copies[name]={'source':str(p),'sha256':value,'bytes':p.stat().st_size}

primary=read(R/'docs/primary-prospective-export-verification.json')
plan(R/'docs/primary-prospective-export-verification.json','primary/fixture-verification.json')
for row in primary['junit']: plan(row['path'],'primary/fixture-'+Path(row['path']).name,row['sha256'])
for row in primary['source_files']:
    plan(B/'primary-prospective-export'/row['path'],'primary/frozen-source/'+row['path'],row['sha256'])
    plan(R/row['path'],'integrated-source/'+row['path'])
live=W/'primary-prospective-export-live-r1'
delivery=read(live/'delivery-manifest-r1.json')
plan(live/'delivery-manifest-r1.json','primary/live/delivery-manifest-r1.json',
     '8f30d619bec9227d1064bf597d580b3a54426a76e3e683205dab50e3f17416d3')
excluded=[]
for row in delivery['artifacts']:
    p=Path(row['path']); assert sha(p)==row['sha256']
    if p.is_relative_to(live):
        if p.name in {'data.csv','public.json'}:
            excluded.append(row); continue
        plan(p,'primary/live/'+p.relative_to(live).as_posix(),row['sha256'])
    elif p.name=='source-freeze-r1.json':
        plan(p,'primary/fixture-source-freeze-r1.json',row['sha256'])
assert len(excluded)==8
for name in ('verify_primary_live_root_20260913.py','primary-live-root-metadata-verification-r1.json',
             'all48-export-linked-root-r1.xml','primary-lineage-archive-index-verification.json'):
    plan(W/name,name)
suite=ET.parse(W/'all48-export-linked-root-r1.xml').getroot().find('testsuite')
assert suite.attrib['tests']=='121'
assert all(suite.attrib[k]=='0' for k in ('failures','errors','skipped'))

m6=R/'results/modular-engineering-20260913/q85-q86-q87-production'
paths=sorted(p for p in m6.rglob('*') if p.is_file()); assert len(paths)==26
for p in paths:
    relative=p.relative_to(R).as_posix()
    committed=subprocess.check_output(['git','show',head+':'+relative],cwd=R)
    assert hashlib.sha256(committed).hexdigest()==sha(p), relative
    plan(p,'m6/'+p.relative_to(m6).as_posix())
m6report=read(m6/'FINAL-VERIFICATION.json')
assert m6report['final_grid_denominator']==92 and m6report['paid_calls']==0

retrieval=read(W/'retrieval-linked-verification-r1.json')
plan(W/'retrieval-linked-verification-r1.json','retrieval/verification-r1.json',
     '798ff2506751b4abe229109067279215bcc58cd24c91b66be525cd9f8dc14800')
for row in retrieval['reports'].values(): plan(row['path'],'retrieval/'+Path(row['path']).name,row['sha256'])
for relative, row in retrieval['source_bindings'].items():
    plan(B/'retrieval-linked-benchmark'/relative,'retrieval/frozen-source/'+relative,row['worktree_sha256'])
    if 'integrated-source/'+relative not in copies: plan(R/relative,'integrated-source/'+relative)
grids={}
for name, root in [('review-limited-v1',W/'retrieval-linked-frozen-r1/retrieval-linked-grid0'),
                   ('neutral-identifiers-v2',W/'retrieval-linked-frozen-r2/retrieval-linked-grid0')]:
    assert root.is_dir()
    files={}
    for p in sorted(root.rglob('*')):
        assert not p.is_symlink() and not p.is_junction(),str(p)
        if p.is_file(): files[p.relative_to(root).as_posix()]={'sha256':sha(p),'bytes':p.stat().st_size}
    assert files
    grids[name]=(root,files)
plan(Path(__file__),Path(__file__).name)

# All paths, hashes, reports and closed sources above have passed before mutation.
for name, row in copies.items():
    p=Path(row['source']); assert sha(p)==row['sha256']
    target=D/name;target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(p,target);assert sha(target)==row['sha256']
for name,(root,files) in grids.items():
    target=D/'retrieval'/f'{name}-synthetic-grid.zip'
    with zipfile.ZipFile(target,'x',zipfile.ZIP_DEFLATED) as z:
        for relative,row in files.items():
            assert sha(root/relative)==row['sha256']
            z.write(root/relative,relative)
    with zipfile.ZipFile(target) as z:
        assert set(z.namelist())==set(files)
        assert all(hashlib.sha256(z.read(n)).hexdigest()==row['sha256'] for n,row in files.items())
    write(D/'retrieval'/f'{name}-synthetic-grid-hashes.json',files)
write(D/'primary/live/not-copied-public-task-and-csv-hashes.json',
      {'reason':'Original selected TRAIN outputs remain in the controlled work directory; only hashes are archived here.',
       'artifacts':excluded})
write(D/'checkpoint.json',{'schema':'all48-export-linked-engineering-checkpoint-v1','source_commit':head,
    'root_tests':dict(suite.attrib),'registered_question_drivers':43,'separate_Q6_phases':5,
    'all_question_execution_contracts':48,'all_question_scientific_effects':'open',
    'generic_linked_benchmark_scopes':['Q1.5','Q3.1','Q4.3','Q8.2','Q8.3'],
    'final_three_question_cells':92,'final_three_fixture_model_calls':236,'final_three_real_docker_calls':16,
    'primary_train_public_export':{'discoverybench':2,'blade':2,'root_hash_verified_artifacts':26,'journal_events':7},
    'retrieval_synthetic_cells':24,'retrieval_fixture_model_calls':72,'retrieval_provider_calls':54,
    'retrieval_provider_failure_grid':{'denominator':24,'failed':18,'baseline_succeeded':6},
    'retrieval_v1_qualification':'review_limited_encoded_variant_source_ids',
    'retrieval_v2_qualification':'neutral_ids_actual_precursor_and_solver_request_checks',
    'retrieval_synthetic_zip_members':{name:len(files) for name,(_,files) in grids.items()},
    'existing_pair_controllers':4,'remaining_pair_controllers':32,
    'existing_triple_controllers':1,'remaining_triple_controllers':4,
    'full_loo_and_final_train_selected_bundle':'open','pruned_combinations':[],
    'new_paid_calls':0,'validation_acceptance':'not_run','primary_validation_stays_sealed':95,
    'SAB_validation_records_on_hold':18,'BLADE_validation_groups':1,
    'multiple_disjoint_primary_validation_stages':'insufficient_groups',
    'scientific_effectiveness':'not_established'})
write(D/'ORIGINS.json',copies)
current=dict(old)
for p in D.rglob('*'):
    if p.is_file():
        relative=p.relative_to(A).as_posix();assert relative not in current;current[relative]=sha(p)
assert all(sha(A/p)==v for p,v in old.items())
(A/'SHA256.json').write_text(json.dumps(dict(sorted(current.items())),indent=2)+'\n',encoding='utf-8',newline='\n')
print(json.dumps({'old_files_unchanged':len(old),'indexed_files':len(current),
    'new_files':len(current)-len(old),'root_tests':dict(suite.attrib),
    'zip_members':{name:len(files) for name,(_,files) in grids.items()}}))
