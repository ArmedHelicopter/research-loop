from pathlib import Path
from itertools import combinations
import pytest
from research_loop.modular import panel_runner
from research_loop.modular.benchmarks import BladeAdapter, DiscoveryBenchAdapter
from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
from research_loop.modular.panel_plan import compile_train_panel, executable_arms
from research_loop.modular.panel_receipts import PanelReceiptVerifier
from research_loop.modular.runtime import AuditVerifier
from research_loop.modular.withdrawal_panel_drivers import freeze_withdrawal_bundle,Q16WithdrawalDriver,Q17TimeInformationDriver

SPLIT='9'*64; AUDIT=AuditVerifier({'a':b'a'*32,'b':b'b'*32})
def task(name):
 i=DataIdentity(name,'withdraw-'+name,name+':withdraw','synthetic-v1',SPLIT,'train')
 return DiscoveryBenchAdapter().prepare(i,{'task_id':i.task_id,'question':'PUBLIC-WITHDRAW-'+name,'source_kind':'synthetic','dataset':[{'name':'x.csv','columns':[{'name':'x'}]}]}) if name=='discoverybench' else BladeAdapter().prepare(i,{'task_id':i.task_id,'dataset_id':'public','research_question':'PUBLIC-WITHDRAW-'+name,'data_schema':[{'name':'x','dtype':'float'}]})
def bundle(t):
 action={'execution_success':True,'outcome':'negative','state':{'validity':'invalid','support':'refuted','novelty':'unknown','investment':'repair'},'audit':[{'name':'measurement','executed':True,'passed':True}],'reason':'caller recorded source defect'}
 common=lambda n:{'initial_answer':'INITIAL-Q16-'+str(n),'historical_summary':'HISTORY-Q16-'+str(n),'old_evidence':{'observation':'OLD-Q16-'+str(n)},'old_claim':'OLD-CLAIM-Q16-'+str(n),'invalidation_evidence':{'observation':'INVALID-Q16-'+str(n)},'invalidation_action':action}
 q16={'replacement':common(1)|{'alternative_material':{'proposal':'ALTERNATIVE-Q16-1'}},'none':common(2),'high_score':common(3)|{'historical_score':{'score':9,'source':'caller-score-log','recorded_at':'2026-01-01T00:00:00Z'}}}
 def timed(n,before,current,sufficient=True): return {'initial_answer':'INITIAL-Q17-'+str(n),'historical_summary':'HISTORY-Q17-'+str(n),'before_evidence':{'observation':before[0],'time_order':before[1],'narrative':before[2],'evidence_sufficient':True},'current_evidence':{'observation':current[0],'time_order':current[1],'narrative':current[2],'evidence_sufficient':sufficient}}
 q17={'irrelevant':timed(1,('OBS-A','t1-before-t2','narrative one'),('OBS-A','t1-before-t2','narrative two')),'causal':timed(2,('OBS-B','cause-before-effect','narrative one'),('OBS-C','effect-before-cause','narrative one')),'unknown':timed(3,('OBS-D','t1-before-t2','narrative one'),('OBS-D','t1-before-t2','narrative two'),False)}
 return freeze_withdrawal_bundle(t,public_evidence={'observation':'PUBLIC-EVIDENCE-'+t.identity.benchmark},q16=q16,q17=q17)

def admission(_task,record): return {'record_digest':record.content_hash,'trusted_validator':'synthetic-caller','validator_verified':True,'admitted':True}
def model(request):
 b=request.data()
 if b['slot']=='final': return FrozenRecord.from_dict({'objective_digest':b['module_context']['required_objective_digest'],'outcome':'unknown','evidence_ids':[],'conclusion':'synthetic bounded','programme_complete':False})
 return FrozenRecord.from_dict({'assessment':'synthetic','evidence_refs':['public'],'counterexamples':[],'uncertainty':'bounded'})
def setup():
 tasks={x:task(x) for x in ('discoverybench','blade')}; package=CandidatePackage.create(parent_digest=None,manifest=TrainingManifest.freeze([t.identity for t in tasks.values()]),changes={'prompt':{'instructions':'package'}},search_cost=0)
 from research_loop.modular.panel_plan import obligation_grids
 grids=obligation_grids(('Q1.6','Q1.7'),baseline_digest='base',p0_control=FrozenRecord.from_dict({'control':'fixed'})); packages={a.content_hash:package for g in grids.values() for a in executable_arms(g).values()}
 return compile_train_panel(stage='withdrawal-grid',scope_ids=('Q1.6','Q1.7'),tasks=tuple(tasks.values()),evidence_by_task={t.content_hash:bundle(t) for t in tasks.values()},budget=FrozenRecord.from_dict({'calls':3}),baseline_digest='base',p0_control=FrozenRecord.from_dict({'control':'fixed'}),packages_by_arm=packages,scorer=FrozenRecord.from_dict({'scorer':'none'}),acceptance_criteria=FrozenRecord.from_dict({'criterion':'engineering'})),tasks
def requests(runtime): return [FrozenRecord(line).data()['data']['request'] for line in runtime.trace_path.read_text(encoding='utf-8').splitlines() if FrozenRecord(line).data()['stage']=='model_request']
def events(runtime): return [FrozenRecord(line).data() for line in runtime.trace_path.read_text(encoding='utf-8').splitlines()]
def test_q16_q17_full_compiled_grid_uses_actual_material_without_blind_leaks(tmp_path,monkeypatch):
 compiled,tasks=setup(); monkeypatch.setitem(panel_runner.DRIVERS,'Q1.6',Q16WithdrawalDriver(admission_port=admission)); monkeypatch.setitem(panel_runner.DRIVERS,'Q1.7',Q17TimeInformationDriver(admission_port=admission)); runtimes=[]; seen=[]; traced=[]
 for n,cell in enumerate(compiled.panel.cells):
  result=panel_runner.run_train_cell(cell,task=tasks[cell.identity.benchmark],scenario=compiled.scenarios[cell.key],package=compiled.packages[cell.runtime_arm.content_hash],objective=FrozenRecord.from_dict({'objective':'withdrawal'}),sidecar=tmp_path/str(n),model=model,audit_verifier=AUDIT); assert result.runtime.status=='succeeded'; assert result.call_plan.data()['model_calls']==3; runtimes.append(result.runtime); seen += requests(result.runtime); traced.append((cell,events(result.runtime)))
 assert PanelReceiptVerifier().verify(compiled.panel,tuple(runtimes)).decision=='engineering_verified'
 assert all(r['module_context']['panel_cell'].keys()=={'schema','cell_digest'} for r in seen)
 for cell,rows in traced:
  workflow=[row['data'] for row in rows if row['stage']=='modular_workflow']
  stages=[row['stage'] for row in workflow]
  if cell.coverage_id=='Q1.6':
   assert 'operation_m2_withdrawal_propagation' in stages or 'operation_m2_control' in stages
   if 'M1' in cell.runtime_arm.data()['enabled']:
    gate=next(row for row in workflow if row['stage']=='operation_m1_evidence_gate'); assert gate['disposition']['admitted'] is False
    if 'M2' in cell.runtime_arm.data()['enabled']:
     assert any(row['stage']=='operation_m2_withdrawal_propagation' and row['withdrawn_root'] for row in workflow)
  else:
   row=next(row for row in workflow if row['stage'] in {'stage_9','operation_m3_control'}); assert row['before_root'] and row['current_root']

 encoded='\n'.join(FrozenRecord.from_dict(r).encoded for r in seen)
 assert all(label not in encoded for label in ('replacement','high_score','irrelevant','causal'))
 for r in seen:
  if r['slot']=='initial':
   text=FrozenRecord.from_dict(r).encoded; assert 'INVALID-Q16-' not in text and 'CURRENT-Q17-' not in text
  if r['slot']=='final':
   context=r['module_context']; assert ('withdrawal_processing' in context) ^ ('time_reconstruction' in context)
   assert any(key in FrozenRecord.from_dict(context).encoded for key in ('INVALID-Q16-','OBS-'))
def test_bundle_and_caller_receipt_fail_closed(tmp_path,monkeypatch):
 compiled,tasks=setup(); cell=next(c for c in compiled.panel.cells if c.coverage_id=='Q1.6'); monkeypatch.setitem(panel_runner.DRIVERS,'Q1.6',Q16WithdrawalDriver(admission_port=lambda *_:{'record_digest':'0'*64,'trusted_validator':'x','validator_verified':False,'admitted':True}))
 result=panel_runner.run_train_cell(cell,task=tasks[cell.identity.benchmark],scenario=compiled.scenarios[cell.key],package=compiled.packages[cell.runtime_arm.content_hash],objective=FrozenRecord.from_dict({'objective':'bad'}),sidecar=tmp_path/'bad',model=model,audit_verifier=AUDIT); assert result.runtime.status=='failed'
