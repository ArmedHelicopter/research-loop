"""Append closed M4/M5 training and source-qualified engineering evidence."""
import hashlib
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

BASE=Path('E:/_ryanDev/AI/research-loop-modular');ROOT=BASE/'integration'
ARCHIVE=ROOT/'results/modular-engineering-20260912';DEST=ARCHIVE/'combination-exploration-20260913'
TRIAL=BASE/'work/m4m5-train-process-20260913-01'
PRIVATE=BASE/'custody-private/m4m5-scorer-process-20260913-01'
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,value):
    with p.open('x',encoding='utf-8',newline='\n') as f:json.dump(value,f,ensure_ascii=False,indent=2);f.write('\n')
old=read(ARCHIVE/'SHA256.json');assert len(old)==1194 and not DEST.exists()
assert all(sha(ARCHIVE/name)==h for name,h in old.items())
payloads={};origins={};reports={}
def add(source,name,note):
    p=Path(source);assert p.is_file() and not p.is_symlink() and name not in payloads
    payloads[name]=p.read_bytes();origins[name]={'source':str(p),'sha256':sha(p),'qualification':note}
    if p.suffix=='.xml':
        s=ET.fromstring(payloads[name]).find('testsuite');reports[name]={k:s.attrib[k] for k in ('tests','failures','errors','skipped','time')}
for name,note in (
    ('meta-root-integrated-r1.xml','c725086: 77 root checks; separate Q6.3 phase and rejected successor/history preservation'),
    ('extended-exploration-root-r1.xml','c03e2eb: 69 root checks; complete 88-cell actual controller seam'),
    ('combination-process-r1.xml','60cc333: 55 process and controller checks, including actual eight-cell synthetic Docker grid'),
    ('q55-controller-verifier-committed.xml','a0beade: 52 independent committed-source checks; actual 32-cell Q5.5 controller'),
    ('resource-combo-root-r1.xml','64568e0: 94 pass and one stale Q5.5 fixture-classification failure; no all-green claim'),
    ('resource-combo-root-classification-r2.xml','9e2d942: 43 pass; only test-classification changed after the preceding report'),
    ('combination-failed-terminal-red-r1.xml','9e2d942 plus new test: actual failed Docker followed by valid unknown answer was incorrectly rejected'),
    ('combination-failed-terminal-green-r1.xml','intermediate working source: one counterexample passes; final committed report follows'),
    ('combination-failed-terminal-frozen-r2.xml','cf571b0: frozen failed-terminal repair checks, actual failed/successful Docker and forged binding refusals')):
    add(BASE/'work'/name,'reports/'+name,note)
for pattern in ('meta-*.xml','meta-*.json','q55-*.xml'):
    for p in sorted((BASE/'work').glob(pattern)):
        name='history/'+p.name
        if name not in payloads:add(p,name,'Retained agent/intermediate evidence; overlapping reports are not independent replications')
for name in ('exploration_extended_verification.json','exploration_extended_controller_verification.json','exploration_extended_cost_review.json'):
    add(ROOT/'docs'/name,'exploration/'+name,'Source-qualified synthetic verification manifest; no efficacy claim')
extended=read(ROOT/'docs/exploration_extended_controller_verification.json')
for field in ('preflight','frozen_suite'):
    entry=extended[field];assert sha(Path(entry['path']))==entry['sha256']
    add(entry['path'],'exploration/'+Path(entry['path']).name,'Preserved formal controller report')
for row in extended['main_traces']:
    assert sha(Path(row['trace_path']))==row['sha256']
    add(row['trace_path'],f"exploration/traces/{row['index']:03d}.jsonl",'Actual frozen synthetic controller trace, not a paid benchmark score')
for directory in ('export','run'):
    for p in sorted((TRIAL/directory).rglob('*')):
        if p.is_file():add(p,'trial/'+p.relative_to(TRIAL).as_posix(),'Closed original training run; all failure cells retained')
for name in ('controller.json','preflight.json','startup.json','summary.json','scorer-client.jsonl','model/ledger.json'):
    add(TRIAL/name,'trial/'+name,'Closed frozen training controls, cost metadata or authenticated scorer journal')
add(PRIVATE/'server.jsonl','trial/scorer-worker-journal.jsonl','Closed scorer reservations and signed numeric results; no reference text')
for name in ('run_m4m5_train_20260913.py','diagnose_m4m5_closed_20260913.py','m4m5-closed-diagnosis-20260913-01.json'):
    add(BASE/'work'/name,name,'Frozen trial or separate read-only diagnosis; original files unchanged')
add(Path(__file__),Path(__file__).name,'Append-only publisher')
summary=read(TRIAL/'summary.json')
assert summary['cells']==8 and summary['scored_cells']==5 and summary['failed_cells']==3
assert summary['solver_calls']==40 and summary['solver_tokens']==364228
assert summary['evaluator_calls']==5 and summary['evaluator_tokens']==112562
assert summary['status']=='inconclusive' and not summary['usage_incomplete']
evaluation=read(PRIVATE/'evaluator-model/ledger.json')
cost={'schema':'combination-evaluator-cost-metadata-v1','source_path':str(PRIVATE/'evaluator-model/ledger.json'),
    'source_sha256':sha(PRIVATE/'evaluator-model/ledger.json'),'calls':len(evaluation['calls']),
    'tokens':evaluation['tokens'],'usage_incomplete':evaluation['usage_incomplete'],
    'reservations':[{k:r.get(k) for k in ('id','slot','status','request_hash','output_hash','usage','error_type')} for r in evaluation['calls']]}
all_trial_hashes={p.relative_to(TRIAL).as_posix():sha(p) for p in sorted(TRIAL.rglob('*')) if p.is_file()}
DEST.mkdir()
for name,raw in payloads.items():
    p=DEST/name;p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('xb') as f:f.write(raw)
write(DEST/'origins.json',origins);write(DEST/'evaluator-cost-metadata.json',cost)
write(DEST/'original-trial-file-hashes.json',all_trial_hashes)
write(DEST/'checkpoint.json',{'schema':'combination-exploration-checkpoint-v1',
    'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
    'production_question_drivers':36,'separate_meta_phase':'Q6.3','reports':reports,'training':summary,
    'combined_calls':45,'combined_tokens':476790,'failure_details':{'empty_conclusion':2,'program_syntax_error':1},
    'source_verifier_issue':'Failed program plus valid unknown final answer rejected by original generic verifier; original trial remains unchanged',
    'paid_reruns':0,'validation_used':0,'scientific_efficacy':False,'calibration':False,'current_head_full_suite':False,
    'pruned_combinations':[],'all_48_scientific_obligations_and_required_combinations_remain_open':True})
index={p.relative_to(ARCHIVE).as_posix():sha(p) for p in sorted(ARCHIVE.rglob('*')) if p.is_file() and p.name!='SHA256.json'}
assert all(index[name]==h for name,h in old.items())
(ARCHIVE/'SHA256.json').write_text(json.dumps(index,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
print(json.dumps({'preserved':len(old),'added':len(index)-len(old),'total':len(index),'reports':reports}))
