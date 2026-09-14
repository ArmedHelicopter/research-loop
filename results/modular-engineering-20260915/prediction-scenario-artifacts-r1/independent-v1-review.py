import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys
from unittest.mock import patch

SOURCE = Path('E:/_ryanDev/AI/research-loop-modular/prediction-scenario-artifacts')
BASE = Path(__file__).parent
sys.path.insert(0, str(SOURCE))
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.artifact_catalogue import source_snapshot
from research_loop.modular.prediction_scenario_artifacts import verify_prediction_scenario_artifacts
from research_loop.modular.scenarios_predictions import run_prediction_scenario, _VARIANTS
from research_loop.ontology import ContractError, digest
from tests.test_modular_prediction_scenarios import controls, public_task

J='prediction-scenario-artifacts.jsonl'
T='prediction-scenario-terminal.json'
C='prediction-scenario-closure.json'
report={'commit':'781e5c7c533f1d393b8d1b866c6f94173217bc04','scope':'offline fixtures only; no provider/model/API/Docker/scoring', 'baselines':[], 'attacks':[], 'failure_checks':[]}

def inventory(root):
    return {p.name:(hashlib.sha256(p.read_bytes()).hexdigest(),p.stat().st_mtime_ns,p.stat().st_size) for p in root.iterdir()}

def check(root, task, exp, variant, complete=True):
    before=inventory(root)
    try:
        return verify_prediction_scenario_artifacts(root,task=task,controls=controls(task),experiment_id=exp,variant=variant,complete=complete).data()
    finally:
        assert inventory(root)==before, 'reader mutated artifacts'

def write(root, rows, terminal):
    prev=None
    for i,row in enumerate(rows):
        row['sequence']=i
        row['previous']=prev
        prev=digest(row)
    (root/J).write_bytes((''.join(FrozenRecord.from_dict(r).encoded+'\n' for r in rows)).encode())
    terminal['entry_count']=len(rows)
    (root/T).write_bytes((FrozenRecord.from_dict(terminal).encoded+'\n').encode())
    files={n:{'sha256':hashlib.sha256((root/n).read_bytes()).hexdigest(),'bytes':len((root/n).read_bytes())} for n in (J,T)}
    closure={'schema':'prediction-scenario-closure-v1','inputs':rows[1]['data'],'terminal':terminal,'files':files,'fixture_only':True,'scientific_validated':False}
    (root/C).write_bytes((FrozenRecord.from_dict(closure).encoded+'\n').encode())

for adapter in ('blade','discovery'):
    task=public_task(adapter)
    for exp,variants in _VARIANTS.items():
        for variant in sorted(variants):
            root=BASE/'baseline'/adapter/(exp+'-'+variant)
            seen=[]
            result=run_prediction_scenario(exp,variant,task=task,frozen_controls=controls(task),artifact_root=root,plan_callback=lambda p:seen.append(p) or {'ordinary':'not scientific'})
            verified=check(root,task,exp,variant)
            assert len(seen)==(3 if exp=='Q3.2' else 1)
            assert result.callback_payloads==tuple(seen)
            report['baselines'].append({'adapter':adapter,'experiment':exp,'variant':variant,'callbacks':len(seen),'verified':verified['storage_integrity_verified']})

task=public_task('blade')
baseline=BASE/'baseline'/'blade'/'Q3.2-separate'

def attack(name, mutate):
    root=BASE/'attacks'/name
    shutil.copytree(baseline,root)
    assert check(root,task,'Q3.2','separate')['storage_integrity_verified']
    rows=[json.loads(line) for line in (root/J).read_text().splitlines()]
    terminal=json.loads((root/T).read_text())
    mutate(root,rows,terminal)
    write(root,rows,terminal)
    try:
        outcome=check(root,task,'Q3.2','separate')
        report['attacks'].append({'name':name,'intact_copy_verified_first':True,'coherently_resealed':True,'accepted':True,'check':outcome})
    except Exception as e:
        report['attacks'].append({'name':name,'intact_copy_verified_first':True,'coherently_resealed':True,'accepted':False,'error':str(e)})

def subject(root,rows,terminal):
    for r in rows:
        if r['kind'] in ('frozen_plan','callback_request'):
            r['data']['task']['identity']['task_id']='unrelated-subject'
    result=next(r['data'] for r in rows if r['kind']=='outcome')
    result['callback_payload_digests']=[digest(r['data']) for r in rows if r['kind']=='callback_request']
    terminal['result']=result
    terminal['result_digest']=digest(result)
attack('cross_subject_plans_requests_resealed',subject)

def source(root,rows,terminal):
    unrelated=BASE/'attacker-source.txt'
    unrelated.write_text('this is not either producer module')
    for key in ('scenario_source','artifact_source'):
        rows[1]['data'][key]=source_snapshot(unrelated)
    rows[0]['data']['input_digest']=digest(rows[1]['data'])
attack('unrelated_source_resealed',source)

def attempt(root,rows,terminal):
    rows[0]['data'].update(run_id='unrelated-attempt',task_digest='unrelated-task',identity={'domain':'validation'},experiment_id='Q5.4',variant='subjective')
attack('attempt_binding_resealed',attempt)

def truncate(root,rows,terminal):
    rows[:]=[r for r in rows if r['kind'] in ('attempt','inputs','outcome')]
    result=rows[-1]['data']
    result.update(plan_ids=[],callback_payload_digests=[],callback_response_digests=[])
    terminal['result']=result
    terminal['result_digest']=digest(result)
attack('erase_all_callbacks_plans_trace_resealed',truncate)

def raw_return(root,rows,terminal):
    for r in rows:
        if r['kind']=='callback_return': r['data']['raw']={'ordinary':'different raw value'}
attack('raw_typed_disagree_resealed',raw_return)

def trace(root,rows,terminal):
    for r in rows:
        if r['kind']=='mechanism_trace':r['data']={'events':[{'event':'forged','scientific_validated':True,'classifications':{'mechanism':'supported'}}]}
attack('scientific_trace_forgery_resealed',trace)

def outcome(root,rows,terminal):
    result=next(r['data'] for r in rows if r['kind']=='outcome')
    result.update(task_digest='wrong',experiment_id='Q5.4',variant='subjective',budget_digest='wrong',fixture_only=False)
    terminal['result']=result
    terminal['result_digest']=digest(result)
attack('wrong_outcome_subject_variant_budget_resealed',outcome)
attack('wrong_result_digest_resealed',lambda root,rows,terminal:terminal.update(result_digest='incorrect-digest'))

for exp,variants in _VARIANTS.items():
    for variant in sorted(variants):
        for fail_at in range(1,(3 if exp=='Q3.2' else 1)+1):
            root=BASE/'failures'/(exp+'-'+variant+'-'+str(fail_at))
            seen=[]
            def fail(p):
                seen.append(p)
                if len(seen)==fail_at: raise RuntimeError('injected callback failure')
                return {'ordinary':'ok'}
            try:run_prediction_scenario(exp,variant,task=task,frozen_controls=controls(task),artifact_root=root,plan_callback=fail)
            except RuntimeError:pass
            else:raise AssertionError('callback did not fail')
            assert check(root,task,exp,variant,False)['status']=='failed'
            try:check(root,task,exp,variant)
            except ContractError:pass
            else:raise AssertionError('failed accepted as complete')
            report['failure_checks'].append({'experiment':exp,'variant':variant,'fail_at':fail_at,'retained':True})

root=BASE/'post_callback_failure'
seen=[]
with patch('research_loop.modular.scenarios_predictions._record_unknown_outcomes', side_effect=RuntimeError('injected mechanism failure')):
    try:run_prediction_scenario('Q3.1','mechanism',task=task,frozen_controls=controls(task),artifact_root=root,plan_callback=lambda p:seen.append(p) or None)
    except RuntimeError:pass
try:check(root,task,'Q3.1','mechanism',False)
except ContractError as e: report['post_callback_failure']={'callbacks':len(seen),'files':sorted(p.name for p in root.iterdir()),'failed_attempt_readable':False,'error':str(e)}

validation=public_task('blade','validation')
root=BASE/'preflight-validation'
try:run_prediction_scenario('Q3.1','mechanism',task=validation,frozen_controls=controls(validation),artifact_root=root,plan_callback=lambda p:(_ for _ in ()).throw(AssertionError('callback ran')))
except ContractError:report['train_preflight']={'rejected':True,'directory_created':root.exists()}

(BASE/'report.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'baselines':len(report['baselines']),'failure_checks':len(report['failure_checks']),'attacks':report['attacks'],'post_callback_failure':report['post_callback_failure'],'train_preflight':report['train_preflight']},indent=2))
