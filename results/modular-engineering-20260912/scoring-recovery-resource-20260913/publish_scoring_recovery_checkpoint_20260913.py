"""Append closed scoring recovery and Q54 engineering evidence; preserve old bytes."""
import hashlib
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

BASE=Path('E:/_ryanDev/AI/research-loop-modular')
ROOT=BASE/'integration'; ARCHIVE=ROOT/'results/modular-engineering-20260912'
DEST=ARCHIVE/'scoring-recovery-resource-20260913'
OLD=BASE/'work/linked-train-scored-20260913-02'
REC=BASE/'work/linked-train-scoring-recovery-20260913-01'
PRIV=BASE/'custody-private/linked-scorer-recovery-20260913-01'
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,value):
    with p.open('x',encoding='utf-8',newline='\n') as f: f.write(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
old=read(ARCHIVE/'SHA256.json'); assert len(old)==999 and not DEST.exists()
for name,value in old.items():assert sha(ARCHIVE/name)==value,name
payloads={};origins={};reports={}
def add(source,name,note):
    source=Path(source);assert source.is_file() and not source.is_symlink() and name not in payloads
    payloads[name]=source.read_bytes();origins[name]={'source':str(source),'sha256':sha(source),'qualification':note}
    if name.endswith('.xml'):
        s=ET.fromstring(payloads[name]).find('testsuite');reports[name]={k:s.attrib[k] for k in ('tests','failures','errors','skipped','time')}
for name, note in (
    ('q54-root-seam-r1.xml','f41982d root: 97 checks; formal 16-cell custody/export/Codex fixture/Docker/authority seam and failed-cost retention'),
    ('public-execution-root-r1.xml','07bdc04 root: 68 checks; unchanged public execution helpers used by feasibility and exploration controllers'),
    ('scorer-utf8-red-r1.xml','07bdc04 plus new synthetic real-stdio test: retained GBK worker decoding counterexample'),
    ('scorer-utf8-green-r1.xml','3349b68: 18 passing checks; explicit UTF-8 process streams, including label isolation'),
    ('completed-cell-recovery-r1.xml','7441cfd: 21 passing checks; original successes/failures, no repeated execution, artifact/trace drift refusals and label isolation')):
    add(BASE/'work'/name,name,note)
for p in sorted((BASE/'work').glob('q54-causal-*')):
    if p.is_file():add(p,'q54-history/'+p.name,'Retained overlapping agent revision report; not an independent replication or current-source full-suite claim')
for directory in ('controls','export','run'):
    for p in sorted((OLD/directory).rglob('*')):
        if p.is_file():add(p,'original-02/'+p.relative_to(OLD).as_posix(),'Closed original train-only execution; never overwritten or resumed')
for name in ('model/ledger.json','scorer-client.jsonl','run-failure.json'):
    add(OLD/name,'original-02/'+name,'Closed original provider cost or pre-reservation scoring failure evidence')
for p in sorted(REC.rglob('*')):
    if p.is_file():add(p,'recovery/'+p.relative_to(REC).as_posix(),'Separate scorer-only recovery; original 12-cell denominator and frozen scoring rule preserved')
add(PRIV/'server.jsonl','recovery/scorer-worker-journal.jsonl','Independent scorer process closed reservations and opaque signed score receipts; no protected reference text')
# Evaluator cost evidence is metadata only. The private model ledger remains in
# custody; no reference store, keys, evaluator prompts or protected outputs enter
# the execution-side archive.
evaluation=read(PRIV/'evaluator-model/ledger.json')
cost={'schema':'scorer-recovery-cost-metadata-v1','source_sha256':sha(PRIV/'evaluator-model/ledger.json'),
    'source_path':str(PRIV/'evaluator-model/ledger.json'),'calls':len(evaluation['calls']),
    'tokens':evaluation['tokens'],'usage_incomplete':evaluation['usage_incomplete'],
    'reservations':[{k:r.get(k) for k in ('id','slot','status','request_hash','output_hash','usage','error_type')} for r in evaluation['calls']]}
summary=read(REC/'summary.json'); assert summary['scored']==11 and summary['cells']==12 and summary['new_solver_calls']==0
assert summary['original_solver_calls']==48 and summary['original_solver_tokens']==454992
assert summary['evaluator_calls']==11 and summary['evaluator_tokens']==231721 and summary['selection']=='inconclusive'
assert summary['original_files_unchanged'] and not summary['usage_incomplete']
add(BASE/'work/recover_scoring_20260913.py','recover_scoring_20260913.py','Frozen scorer-only runner; exact source byte hash is in recovery preflight')
add(Path(__file__),Path(__file__).name,'Append-only publisher')
assert sha(BASE/'work/recover_scoring_20260913.py')==read(REC/'preflight.json')['runner_sha256']
for p,h in read(REC/'preflight.json')['original_file_sha256'].items():assert sha(Path(p))==h,p
DEST.mkdir()
for name,raw in payloads.items():
    p=DEST/name;p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('xb') as f:f.write(raw)
write(DEST/'evaluator-cost-metadata.json',cost);write(DEST/'origins.json',origins)
write(DEST/'checkpoint.json',{'schema':'scoring-recovery-resource-checkpoint-v1',
    'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
    'production_question_drivers':31,'reports':reports,'training':summary,
    'combined_provider_calls':59,'combined_tokens':686713,'original_execution_failures':1,
    'failure_summary':'Generated analysis formatted an undefined correlation as a float; original TypeError remains in denominator',
    'new_solver_calls':0,'current_head_full_suite_pass':False,'scientific_effectiveness_proven':False,
    'validation_eligible_records':0,'validation_opened':False,'pruned_combinations':[],
    'all_48_scientific_obligations_and_required_combinations_remain_open':True})
index={p.relative_to(ARCHIVE).as_posix():sha(p) for p in sorted(ARCHIVE.rglob('*')) if p.is_file() and p.name!='SHA256.json'}
assert all(index[name]==value for name,value in old.items())
(ARCHIVE/'SHA256.json').write_text(json.dumps(index,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
print(json.dumps({'old_files_preserved':len(old),'new_files':len(index)-len(old),'total_files':len(index),'reports':reports}))
