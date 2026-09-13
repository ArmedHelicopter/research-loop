"""Append source-qualified train export, retrieval and eligibility-hold evidence."""
import hashlib,json,shutil,subprocess
from pathlib import Path
import xml.etree.ElementTree as ET
BASE=Path('E:/_ryanDev/AI/research-loop-modular'); ROOT=BASE/'integration'; WORK=BASE/'work'
ARC=ROOT/'results/modular-engineering-20260912'; DEST=ARC/'train-export-retrieval-20260913'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_bytes())
def write(p,value):
    with p.open('x',encoding='utf-8',newline='\n') as f:json.dump(value,f,ensure_ascii=False,indent=2); f.write('\n')
assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()=='8aff4f13d986adbe285a06d26bdce3d7ca68b637'
assert not subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip()
old=read(ARC/'SHA256.json'); assert len(old)==1459
assert all(sha(ARC/p)==v for p,v in old.items())
DEST.mkdir(); origins={}
def add(p,name,expected=None):
    value=sha(p); assert expected is None or value==expected,str(p)
    target=DEST/name; target.parent.mkdir(parents=True,exist_ok=True); assert not target.exists()
    shutil.copyfile(p,target); assert sha(target)==value
    origins[name]={'source':str(p),'sha256':value}
manifest=read(ROOT/'docs/prospective-train-export-verification.json')
add(ROOT/'docs/prospective-train-export-verification.json','export/verification.json')
for group in ('artifacts','checks'):
    for name,row in manifest[group].items():
        # Manifest entries are metadata/receipts and synthetic reports only.
        add(Path(row['path']),'export/'+name+('.xml' if group=='checks' else ''),row['sha256'])
for row in manifest['public_task_artifacts']:
    assert sha(Path(row['path']))==row['sha256']  # Bind, but do not copy task contents.
for name in ('prospective-export-root-r1.xml','prospective-export-root-actual-verification-r1.json','q81-q84-root-integrated-r1.xml'):
    add(WORK/name,name)
for p in sorted((ROOT/'results/modular-engineering-20260913/q81-q84-production').iterdir()):
    if p.is_file():add(p,'q81-q84-production/'+p.name)
checks=WORK/'primary-process-qualification-checks'
add(checks/'sab-eligibility-hold-r1.json','sab-history/eligibility-hold.json','e590e020602c960779b1ecfe5b738eda612992824b230a767c53bafe550ac82e')
add(checks/'history-result-r1.json','sab-history/history-result.json','9557b2090b6b5797c6472a158e0f3d86f95f30d49ff267da1c11f931c394f00e')
hold=read(checks/'sab-eligibility-hold-r1.json')
assert hold['held_record_count']==18 and hold['validation_lease_allowed'] is False
for relative in ('evaluation/modular/prospective_train_exporter.py','evaluation/modular/extended_ingestion.py',
    'research_loop/modular/benchmarks/scicode.py','research_loop/modular/benchmarks/scienceagentbench.py',
    'research_loop/modular/retrieval_stage_panel_drivers.py','research_loop/modular/train_controller.py',
    'research_loop/modular/panel_runner.py','tests/test_prospective_train_exporter.py','tests/test_modular_extended_adapters.py',
    'tests/test_modular_q81_q84_train_controller.py'):
    add(ROOT/relative,'source/'+relative)
reports={}
for name,commit in [('prospective-export-root-r1','20743525d2fdaafb4325fa986734f42cda22013e'),
                    ('q81-q84-root-integrated-r1','8aff4f13d986adbe285a06d26bdce3d7ca68b637')]:
    suite=ET.parse(WORK/(name+'.xml')).getroot().find('testsuite')
    reports[name]={'source_commit':commit,**{k:suite.attrib[k] for k in ('tests','failures','errors','skipped','time')}}
write(DEST/'checkpoint.json',{'schema':'train-export-retrieval-checkpoint-v1','source_commit':'8aff4f13d986adbe285a06d26bdce3d7ca68b637',
    'registered_question_drivers':40,'separate_train_phases':['Q6.1','Q6.2','Q6.3','Q6.5','Q6.6'],
    'remaining_question_drivers':['Q8.5','Q8.6','Q8.7'],'root_reports':reports,'actual_fixed_train_tasks_exported':4,
    'original_export_failure_preserved':True,'original_extended_partition':{'train':164,'sealed_validation':18},
    'validation_eligibility_status':'all_18_SAB_records_on_hold_pending_revision_bound_earlier_history_overlap_audit',
    'validation_lease_allowed':False,'validation_opened':False,'earlier_SAB_scope':{'selected':12,'observed_successful_calls':3,'known_tokens':75272},
    'earlier_calls_are_historical_not_new_usage':True,'primary_seal':'under_bounded_audit',
    'q84_M6_given_M2':'mechanistically_redundant_expected_null_contrast_retained','scientific_effectiveness':'not_established',
    'new_paid_model_calls':0,'pruned_combinations':[]})
add(Path(__file__),Path(__file__).name); write(DEST/'ORIGINS.json',origins)
current=dict(old)
for p in DEST.rglob('*'):
    if p.is_file():
        relative=p.relative_to(ARC).as_posix(); assert relative not in current; current[relative]=sha(p)
assert all(sha(ARC/p)==v for p,v in old.items())
(ARC/'SHA256.json').write_text(json.dumps(dict(sorted(current.items())),indent=2)+'\n',encoding='utf-8',newline='\n')
print(json.dumps({'old_files_unchanged':len(old),'new_files':len(current)-len(old),'indexed_files':len(current),'reports':reports}))
