import builtins
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import shutil
import sys
from unittest.mock import patch

SOURCE=Path('E:/_ryanDev/AI/research-loop-modular/work/review-artifact-independent-f2d5c74b/source-snapshot')
BASE=Path(__file__).parent
sys.path[:0]=[str(SOURCE),str(SOURCE/'tests')]
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.review_scenario_artifacts import verify_review_artifacts, ReviewArtifactSession, inventory
from research_loop.modular.scenarios_review import run_review_scenario, _VARIANTS
from research_loop.ontology import ContractError, digest
from test_modular_review_scenarios import task, controls, responder, prediction_responder

A='review-attempts.jsonl'; O='review-outputs.json'; T='review-terminal.json'; I='review-inputs.json'
report={'commit':'f2d5c74b5f93e30f73cee86e034bbfbf2a2349bf','scope':'offline fixtures; no providers/models/API/Docker/VAL experiment','baselines':[],'attacks':[],'failures':[]}
identities={'reviewer_one':{'reviewer_id':'a','model_id':'m1','provider':'p1','provenance':'fixture A'},'reviewer_two':{'reviewer_id':'b','model_id':'m2','provider':'p2','provenance':'fixture B'}}
results={}
def state(root):
    return {p.name:(hashlib.sha256(p.read_bytes()).hexdigest(),p.stat().st_mtime_ns,p.stat().st_size) for p in root.iterdir()}
def check(root,public,exp,variant,result=None):
    before=state(root)
    original_open=Path.open
    def guarded_open(path,mode='r',*args,**kwargs):
        if any(x in mode for x in 'wax+'):raise AssertionError('reader tried file write: '+str(path))
        return original_open(path,mode,*args,**kwargs)
    try:
        with ExitStack() as stack:
            stack.enter_context(patch.object(Path,'open',guarded_open))
            for method in ('mkdir','touch','unlink','rmdir','rename','replace'):
                stack.enter_context(patch.object(Path,method,side_effect=AssertionError('reader tried mutation '+method)))
            return verify_review_artifacts(root,task=public,controls=controls(public),experiment_id=exp,variant=variant,result=result).data()
    finally:assert state(root)==before,'reader changed filesystem'
def reseal(root,rows,outputs,terminal):
    for n,row in enumerate(rows):
        row['sequence']=n
        for body,key in [('payload','payload_digest'),('raw_response','raw_digest'),('typed_response','typed_digest'),('review_event','review_event_digest')]:
            if body in row:row[key]=digest(row[body])
    (root/A).write_bytes((''.join(FrozenRecord.from_dict(r).encoded+'\n' for r in rows)).encode())
    if outputs is not None:(root/O).write_bytes((FrozenRecord.from_dict(outputs).encoded+'\n').encode())
    terminal['files']=inventory(root,include_terminal=False)
    (root/T).write_bytes((FrozenRecord.from_dict(terminal).encoded+'\n').encode())
def sync_payloads(rows,outputs):
    outputs['callback_payloads']=[r['payload'] for r in rows if r['event']=='callback_payload']
    outputs['result']['callback_payload_digests']=[digest(p) for p in outputs['callback_payloads']]
def attack(name,fn,exp='Q4.3',variant='sequential',consumer_result=False):
    original=BASE/'baseline'/'blade'/(exp+'-'+variant)
    root=BASE/'attacks'/name
    shutil.copytree(original,root)
    public=task('blade'); result=results[('blade',exp,variant)] if consumer_result else None
    assert check(root,public,exp,variant,result)['status']=='succeeded'
    rows=[json.loads(x) for x in (root/A).read_text().splitlines()]
    outputs=json.loads((root/O).read_text()); terminal=json.loads((root/T).read_text())
    fn(root,rows,outputs,terminal)
    reseal(root,rows,outputs if (root/O).exists() else None,terminal)
    try:outcome=check(root,public,exp,variant,result); accepted=True; error=None
    except Exception as exc:outcome=None; accepted=False; error=str(exc)
    report['attacks'].append({'name':name,'intact_complete_copy_verified':True,'fully_resealed':True,'original_producer_result_supplied':consumer_result,'accepted':accepted,'check':outcome,'error':error})

for adapter in ('blade','discovery'):
    public=task(adapter)
    for exp,variants in _VARIANTS.items():
        for variant in sorted(variants):
            root=BASE/'baseline'/adapter/(exp+'-'+variant)
            result=run_review_scenario(exp,variant,task=public,frozen_controls=controls(public),artifact_root=root,review_callback=responder,reviewer_identities=identities if variant=='heterogeneous' else None)
            check(root,public,exp,variant,result)
            check(root,public,exp,variant)
            results[(adapter,exp,variant)]=result
            report['baselines'].append({'adapter':adapter,'experiment':exp,'variant':variant,'callbacks':len(result.callback_payloads)})

def raw(root,rows,outputs,terminal):
    for row in rows:
        if row['event']=='callback_response':row['raw_response']={'assessment':'unknown','evidence_refs':[],'counterexamples':[],'uncertainty':'forged raw'}
attack('raw_typed_disagreement_original_result',raw,consumer_result=True)

def reservation(root,rows,outputs,terminal):
    for row in rows:
        if row['event']=='callback_reserved':row['allocation']['fixture_units']=-999;row['allocation']['role_id']='unrelated-'+row['allocation']['role_id']
attack('negative_wrong_role_allocation_original_result',reservation,consumer_result=True)

def remove_revision(root,rows,outputs,terminal):
    target=next(r for r in rows if r['event']=='review_engine_event' and r['review_event']['event']=='revise')
    rows.remove(target)
attack('missing_one_m5_revision_original_result',remove_revision,consumer_result=True)

def remove_score(root,rows,outputs,terminal):
    rows[:]=[r for r in rows if r['event']!='review_engine_event' or r['review_event']['event']!='score']
attack('missing_m5_score_original_result',remove_score,consumer_result=True)

def m5_response(root,rows,outputs,terminal):
    before={}
    for row in rows:
        if row['event']!='review_engine_event':continue
        ev=row['review_event']
        if ev['event']=='submit':
            ev['response']['assessment']='unknown';ev['response']['uncertainty']='unrelated persisted M5 result'
            ev['before_hash']=digest({k:ev[k] for k in ('review_id','role_id','reviewer_id','response')})
            before[ev['role_id']]=ev['before_hash']
        if ev['event']=='revise':ev['after_hash']=digest({'before_hash':before[ev['role_id']],'response':ev['response']})
attack('m5_submissions_disagree_with_callbacks_original_result',m5_response,consumer_result=True)

def no_visibility(root,rows,outputs,terminal):
    for row in rows:
        if row['event']=='callback_payload':
            p=row['payload']
            p['prior_visible_submission']=[] if p['invocation']=='revision' else None
    sync_payloads(rows,outputs)
attack('sequential_and_revision_visibility_erased',no_visibility)

def fake_results(root,rows,outputs,terminal):
    outputs['result'].update(task_digest='wrong',controls_digest='wrong',experiment_id='Q4.1',variant='single',fixture_only=False,metrics={'net_correction':999,'denominator':1},budget={'fixture_units':999},m4={'status':'on','outcome':'supported'})
    outputs['mechanism_trace']['events']=[{'event':name,'forged':True} for name in ('sealed_barrier_revealed','independent_fixture_oracle','callback_prediction_extraction')]
attack('forged_subject_budget_metrics_m4_trace',fake_results)

def identities_attack(root,rows,outputs,terminal):
    for row in rows:
        if row['event']=='callback_payload':row['payload']['reviewer_identity']={'reviewer_id':'same','model_id':'same','provider':None,'provenance':'forged'}
    sync_payloads(rows,outputs)
attack('heterogeneous_provenance_collapsed',identities_attack,'Q4.5','heterogeneous')

def failed(root,rows,outputs,terminal):
    rows[:]=rows[:1]
    (root/O).unlink()
    terminal.update(status='failed',failure={'exception_type':'RuntimeError','message':'fabricated failure with no attempt event'})
attack('failed_history_erase_no_failure_event',failed)

def source(root,rows,outputs,terminal):
    body=json.loads((root/I).read_text());body['sources']['scenario']['path']='unrelated-source'
    (root/I).write_bytes((FrozenRecord.from_dict(body).encoded+'\n').encode())
attack('unrelated_source_control',source)

public=task('blade')
for exp,variant in [('Q4.1','roles'),('Q4.3','sequential'),('Q4.5','heterogeneous')]:
    count=len(results[('blade',exp,variant)].callback_payloads)
    for position in range(1,count+1):
        root=BASE/'failures'/(exp+'-'+variant+'-'+str(position));seen=[]
        def callback(payload):
            seen.append(payload)
            if len(seen)==position:raise RuntimeError('bounded callback failure')
            return responder(payload)
        try:run_review_scenario(exp,variant,task=public,frozen_controls=controls(public),artifact_root=root,review_callback=callback,reviewer_identities=identities if variant=='heterogeneous' else None)
        except RuntimeError:pass
        else:raise AssertionError('no failure')
        report['failures'].append({'variant':variant,'position':position,'status':check(root,public,exp,variant)['status']})

root=BASE/'post_callback_failure'
with patch('research_loop.modular.scenarios_review._fixture_oracle',side_effect=RuntimeError('injected fixture oracle failure')):
    try:run_review_scenario('Q4.3','sequential',task=public,frozen_controls=controls(public),artifact_root=root,review_callback=responder)
    except RuntimeError:pass
try:check(root,public,'Q4.3','sequential')
except ContractError as exc:report['post_callback_failure']={'files':sorted(p.name for p in root.iterdir()),'error':str(exc),'readable':False}

root=BASE/'bad_callback_raw'
bad={'review':{'not':'valid'},'prediction_candidate':'invalid-candidate'}
try:run_review_scenario('Q4.1','single',task=public,frozen_controls=controls(public),artifact_root=root,review_callback=lambda p:bad)
except ContractError:pass
report['bad_callback_raw']={'status':check(root,public,'Q4.1','single')['status'],'raw_retained':any('raw_response' in json.loads(r) for r in (root/A).read_text().splitlines())}

root=BASE/'producer_returns_corrupt_artifact'
real_complete=ReviewArtifactSession.complete
def corrupt_complete(self,result):
    real_complete(self,result)
    (self.root/O).write_text('CORRUPT')
with patch.object(ReviewArtifactSession,'complete',corrupt_complete):
    returned=run_review_scenario('Q4.1','single',task=public,frozen_controls=controls(public),artifact_root=root,review_callback=responder)
try:check(root,public,'Q4.1','single',returned)
except ContractError as exc:report['producer_return_without_verification']={'returned':True,'independent_verifier_rejected':True,'error':str(exc)}

root=BASE/'m4-positive'
result=run_review_scenario('Q4.1','roles',task=public,frozen_controls=controls(public),artifact_root=root,review_callback=prediction_responder)
check(root,public,'Q4.1','roles',result)
rows=[json.loads(r) for r in (root/A).read_text().splitlines()]
report['m4_positive']={'status':result.record.data()['m4']['status'],'journal_event_types':sorted({r['event'] for r in rows}),'m4_plan_payload_recorded':any('plan' in r and 'branches' in r.get('plan',{}) for r in rows)}

(BASE/'report.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
