import hashlib
import json
import pytest

from research_loop.modular.benchmarks import BladeAdapter, DiscoveryBenchAdapter, DockerExecutionBroker
from research_loop.modular.combinations import default_compatibility
from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
from research_loop.modular.panel_receipts import PanelCell
from research_loop.modular.q54_causal_driver import Q54CausalDriver, _receipt, freeze_q54_causal_bundle, q54_causal_injection
from research_loop.modular.runtime import AuditVerifier, RunSession
from research_loop.modular.workflow import ModularWorkflow
from research_loop.ontology import ContractError

IMAGE='research-benchmark-python@sha256:1433f0d223b0773b0d8c3184fa4ff6ab0a3891113442f1592d8d7e883d21a349'

def task(benchmark):
 identity=DataIdentity(benchmark,'q54','g','v','9'*64,'train')
 if benchmark=='blade': return BladeAdapter().prepare(identity,{'task_id':'q54','dataset_id':'synthetic','research_question':'q','data_schema':[{'name':'x','dtype':'float'}]})
 return DiscoveryBenchAdapter().prepare(identity,{'task_id':'q54','question':'q','source_kind':'synthetic','dataset':[{'name':'p','columns':[{'name':'x'}]}]})
def branch(name,direction):
 return {'hypothesis_id':'h-'+name,'mechanism_key':'m-'+name,'mechanism':'public '+name,'intervention':'one diagnostic','elimination_condition':'authority outcome','predictions':[{'prediction_id':'p-'+name,'discriminator_id':'disc','observable':'public result','direction':direction,'value_range':None,'failure_condition':'authority outcome'}]}
def material(t,csv):
 authority={'contract_id':'c','source_id':t.identity.group_id,'authorities':[{'authority_id':'a','source_group':'one'},{'authority_id':'b','source_group':'two'}]}
 branches=[branch('a','increase'),branch('b','decrease')]
 rows=[]
 for name,cost,u in [('a',2,1),('b',1,9)]:
  control='0.0' if name=='a' else 'value'
  program=f"import csv\nwith open('/input/data') as handle:\n value=sum(float(row['x']) for row in csv.DictReader(handle))\nnegative_control={control}\nmeasurement=value\nprint('measurement='+str(measurement))\nprint('negative_control='+str(negative_control))"
  rows.append({'diagnostic_id':name,'branch_ids':['h-a','h-b'],'program':program,'program_sha256':hashlib.sha256(program.encode()).hexdigest(),'image':IMAGE,'inputs':{'data':{'sha256':hashlib.sha256(csv).hexdigest(),'byte_count':len(csv)}},'cost':cost,'preregistered_uncertainty':u,'negative_control_id':'zero'})
 item={'diagnostics':rows,'prediction_branches':branches,'measurement_contract':{'source_id':t.identity.group_id,'contract_id':'measure','discriminator_id':'disc','observable':'public result','negative_control_id':'zero'},'authority_contract':authority}
 return freeze_q54_causal_bundle(t,variants={'subjective':item,'preregistered_cost':item})
class Authority:
 def verify_diagnostic(self,subject):
  body=subject.data(); c=body['authority_contract']; receipt=body['execution_receipt']
  csv_bytes=bytes.fromhex(body['public_input_bytes']['data']); expected=sum(float(row.split(',')[0]) for row in csv_bytes.decode().splitlines()[1:]); stdout=receipt['record']['stdout']
  assert receipt['status']=='succeeded' and ('measurement='+str(expected)) in stdout and 'negative_control=' in stdout
  assert csv_bytes==b'x\n1\n'
  assert hashlib.sha256(bytes.fromhex(body['public_program_bytes'])).hexdigest()==receipt['artifact']['sha256']
  assert body['measurement_contract']['observable']=='public result'
  control=float(next(line.split('=',1)[1] for line in stdout.splitlines() if line.startswith('negative_control=')))
  classifications={}
  qualified=control==0.0
  for branch_row in body['prediction_branches']:
   direction=branch_row['predictions'][0]['direction']
   classifications[branch_row['hypothesis_id']]=('consistent' if direction=='increase' and expected>control else 'failed' if direction=='decrease' and expected>control else 'unknown') if qualified else 'unknown'
  status='passed' if qualified else 'failed'
  return FrozenRecord.from_dict({'schema':'q54-causal-authority-receipt-v1','subject_digest':subject.content_hash,'status':status,'observations':[{'authority_id':x['authority_id'],'source_group':x['source_group'],'contract_id':c['contract_id'],'subject_digest':subject.content_hash,'observation_digest':str(i+1)*64,'status':status,'signature_verified':True} for i,x in enumerate(c['authorities'])],'cost':{'unit':'verifier_units','units':1},'classifications':classifications})

@pytest.mark.parametrize('variant,expected',[('subjective','a'),('preregistered_cost','b')])
@pytest.mark.parametrize('enabled',[(),('M4',),('M7',),('M4','M7')])
@pytest.mark.parametrize('benchmark',['blade','discoverybench'])
def test_q54_uses_model_ranking_updates_m4_and_executes_every_arm(tmp_path,variant,expected,enabled,benchmark):
 t=task(benchmark); csv=b'x\n1\n'; input_dir=tmp_path/'inputs'; input_dir.mkdir(); path=input_dir/'data.csv'; path.write_bytes(csv); bundle=material(t,csv)
 controller=q54_causal_injection(variant,task=FrozenRecord.from_dict(t.data()),evidence=bundle)
 scenario=FrozenRecord.from_dict({'experiment_id':'Q5.4','variant':variant,'controller_input':controller,'base':{'task':t.content_hash,'evidence':bundle.content_hash,'budget':'a'*64},'controls':{'same_task':True,'same_evidence':True,'same_budget':True}})
 package=CandidatePackage.create(parent_digest=None,manifest=TrainingManifest.freeze([t.identity]),changes={'prompt':{'instructions':'x'}},search_cost=0); arm=default_compatibility('b'*64).arm(enabled); cell=PanelCell('Q5.4',t.identity,'r',variant,'a',arm,t.content_hash,scenario.content_hash,package.digest,'a'*64)
 run_dir=tmp_path/'run'; session=RunSession(t,package_digest=package.digest,arm=arm,objective=FrozenRecord.from_dict({'o':'x'}),slots=('ranking','diagnostic','final'),execution_limit=1,sidecar=run_dir,verifier=AuditVerifier({'a':b'a'*32,'b':b'b'*32}),required_audit=('measurement',)); calls=[]
 def model(request):
  body=request.data(); calls.append(body); context=body['module_context']
  if 'diagnostics' in context: return FrozenRecord.from_dict({'ranking':['a','b'],'rationale':'public ordering'})
  if 'required_objective_digest' not in context:
   assert ('M4' in enabled)==(context['observation']['competition'] is not None)
   return FrozenRecord.from_dict({'decision':context['observation']['gate']['disposition'] if 'M7' in enabled else 'continue','rationale':'observed public output'})
  return FrozenRecord.from_dict({'objective_digest':context['required_objective_digest'],'outcome':'unknown','evidence_ids':[],'conclusion':'x','programme_complete':False})
 driver=Q54CausalDriver(DockerExecutionBroker([tmp_path]),lambda _task,_bundle:{'data':path},Authority())
 _,candidate,_=driver.run(ModularWorkflow(session),cell=cell,scenario=scenario,model=model,package=package); session.finish(candidate)
 events=[FrozenRecord(line).data() for line in (run_dir/'trace.jsonl').read_text().splitlines()]
 assert sum(event['stage']=='execution_request' for event in events)==1
 assert any(event['stage']=='modular_workflow' and event['data'].get('selection',{}).get('diagnostic_id')==expected for event in events)
 assert ('M4' in enabled)==any(event['stage']=='modular_workflow' and event['data'].get('m4_outcome') is not None for event in events)
 assert all(token not in json.dumps(calls) for token in ('M4','M7','authority_contract','bundle_digest','container_path','argv'))

def test_authority_receipt_rejects_bad_aggregate_and_failed_execution_classification():
 contract={'contract_id':'c','source_id':'g','authorities':[{'authority_id':'a','source_group':'one'},{'authority_id':'b','source_group':'two'}]}
 branches=[branch('a','increase'),branch('b','decrease')]
 subject=FrozenRecord.from_dict({'authority_contract':contract,'prediction_branches':branches,'execution_receipt':{'status':'succeeded'}})
 observations=[{'authority_id':x,'source_group':g,'contract_id':'c','subject_digest':subject.content_hash,'observation_digest':str(i+1)*64,'status':'failed','signature_verified':True} for i,(x,g) in enumerate((('a','one'),('b','two')))]
 malformed={'schema':'q54-causal-authority-receipt-v1','subject_digest':subject.content_hash,'status':'passed','observations':observations,'cost':{'unit':'verifier_units','units':1},'classifications':{'h-a':'failed','h-b':'consistent'}}
 with pytest.raises(ContractError): _receipt(FrozenRecord.from_dict(malformed),subject)
 failed_subject=FrozenRecord.from_dict({**subject.data(),'execution_receipt':{'status':'failed'}})
 observations=[{**item,'subject_digest':failed_subject.content_hash,'status':'passed'} for item in observations]
 malformed={**malformed,'subject_digest':failed_subject.content_hash,'status':'passed','observations':observations}
 with pytest.raises(ContractError): _receipt(FrozenRecord.from_dict(malformed),failed_subject)

def test_bundle_rejects_crlf_program_and_measurement_observable_drift():
 t=task('blade'); raw=material(t,b'x\n1\n').data()['variants']
 raw['subjective']['diagnostics'][0]['program']="print('a')\r\nprint('bad')"
 with pytest.raises(ContractError): freeze_q54_causal_bundle(t,variants=raw)

def test_bundle_rejects_split_discriminator_observable_pair():
 t=task('blade'); raw=material(t,b'x\n1\n').data()['variants']; predictions=raw['subjective']['prediction_branches'][0]['predictions']
 predictions[0]['observable']='wrong observable'
 predictions.append({'prediction_id':'extra','discriminator_id':'other','observable':'public result','direction':'increase','value_range':None,'failure_condition':'authority outcome'})
 with pytest.raises(ContractError,match='pair'): freeze_q54_causal_bundle(t,variants=raw)

def test_post_execution_input_mutation_is_refused(tmp_path):
 t=task('blade'); csv=b'x\n1\n'; inputs=tmp_path/'inputs'; inputs.mkdir(); path=inputs/'data.csv'; path.write_bytes(csv); bundle=material(t,csv); variant='subjective'
 scenario=FrozenRecord.from_dict({'experiment_id':'Q5.4','variant':variant,'controller_input':q54_causal_injection(variant,task=FrozenRecord.from_dict(t.data()),evidence=bundle),'base':{'task':t.content_hash,'evidence':bundle.content_hash,'budget':'a'*64},'controls':{'same_task':True,'same_evidence':True,'same_budget':True}}); package=CandidatePackage.create(parent_digest=None,manifest=TrainingManifest.freeze([t.identity]),changes={'prompt':{'instructions':'x'}},search_cost=0); arm=default_compatibility('b'*64).arm(('M7',)); cell=PanelCell('Q5.4',t.identity,'r',variant,'a',arm,t.content_hash,scenario.content_hash,package.digest,'a'*64)
 class MutatingBroker(DockerExecutionBroker):
  def execute(self,request):
   receipt=super().execute(request); path.write_bytes(b'x\n99\n'); return receipt
 session=RunSession(t,package_digest=package.digest,arm=arm,objective=FrozenRecord.from_dict({'o':'x'}),slots=('ranking','diagnostic','final'),execution_limit=1,sidecar=tmp_path/'run',verifier=AuditVerifier({'a':b'a'*32,'b':b'b'*32}),required_audit=('measurement',))
 def model(request):
  context=request.data()['module_context']
  if 'diagnostics' in context: return FrozenRecord.from_dict({'ranking':['a','b'],'rationale':'x'})
  return FrozenRecord.from_dict({'decision':'continue','rationale':'x'}) if 'required_objective_digest' not in context else FrozenRecord.from_dict({'objective_digest':context['required_objective_digest'],'outcome':'unknown','evidence_ids':[],'conclusion':'x','programme_complete':False})
 with pytest.raises(ContractError,match='public input changed after execution'):
  Q54CausalDriver(MutatingBroker([tmp_path]),lambda _task,_bundle:{'data':path},Authority()).run(ModularWorkflow(session),cell=cell,scenario=scenario,model=model,package=package)
 raw=material(t,b'x\n1\n').data()['variants']
 raw['subjective']['measurement_contract']['observable']='different observable'
 with pytest.raises(ContractError): freeze_q54_causal_bundle(t,variants=raw)

def test_unknown_authority_gate_cannot_be_overridden_by_diagnostic_model(tmp_path):
 t=task('blade'); csv=b'x\n1\n'; inputs=tmp_path/'inputs'; inputs.mkdir(); path=inputs/'data.csv'; path.write_bytes(csv); bundle=material(t,csv); variant='subjective'; arm=default_compatibility('b'*64).arm(('M7',)); package=CandidatePackage.create(parent_digest=None,manifest=TrainingManifest.freeze([t.identity]),changes={'prompt':{'instructions':'x'}},search_cost=0)
 scenario=FrozenRecord.from_dict({'experiment_id':'Q5.4','variant':variant,'controller_input':q54_causal_injection(variant,task=FrozenRecord.from_dict(t.data()),evidence=bundle),'base':{'task':t.content_hash,'evidence':bundle.content_hash,'budget':'a'*64},'controls':{'same_task':True,'same_evidence':True,'same_budget':True}}); cell=PanelCell('Q5.4',t.identity,'r',variant,'a',arm,t.content_hash,scenario.content_hash,package.digest,'a'*64); session=RunSession(t,package_digest=package.digest,arm=arm,objective=FrozenRecord.from_dict({'o':'x'}),slots=('ranking','diagnostic','final'),execution_limit=1,sidecar=tmp_path/'run',verifier=AuditVerifier({'a':b'a'*32,'b':b'b'*32}),required_audit=('measurement',))
 class Unknown(Authority):
  def verify_diagnostic(self,subject):
   raw=super().verify_diagnostic(subject).data(); raw['status']='unknown'; raw['classifications']={'h-a':'unknown','h-b':'unknown'}
   for observation in raw['observations']: observation['status']='unknown'
   return FrozenRecord.from_dict(raw)
 def model(request):
  context=request.data()['module_context']
  if 'diagnostics' in context: return FrozenRecord.from_dict({'ranking':['a','b'],'rationale':'x'})
  return FrozenRecord.from_dict({'decision':'continue','rationale':'attempt override'})
 with pytest.raises(ContractError,match='overrides applied M7 gate'):
  Q54CausalDriver(DockerExecutionBroker([tmp_path]),lambda _task,_bundle:{'data':path},Unknown()).run(ModularWorkflow(session),cell=cell,scenario=scenario,model=model,package=package)

@pytest.mark.parametrize('units',[3,None])
def test_authority_partial_response_and_exception_cost_are_journaled_first(tmp_path,units):
 t=task('blade'); csv=b'x\n1\n'; inputs=tmp_path/'inputs'; inputs.mkdir(); path=inputs/'data.csv'; path.write_bytes(csv); bundle=material(t,csv); variant='subjective'; arm=default_compatibility('b'*64).arm(('M7',)); package=CandidatePackage.create(parent_digest=None,manifest=TrainingManifest.freeze([t.identity]),changes={'prompt':{'instructions':'x'}},search_cost=0)
 scenario=FrozenRecord.from_dict({'experiment_id':'Q5.4','variant':variant,'controller_input':q54_causal_injection(variant,task=FrozenRecord.from_dict(t.data()),evidence=bundle),'base':{'task':t.content_hash,'evidence':bundle.content_hash,'budget':'a'*64},'controls':{'same_task':True,'same_evidence':True,'same_budget':True}}); cell=PanelCell('Q5.4',t.identity,'r',variant,'a',arm,t.content_hash,scenario.content_hash,package.digest,'a'*64); run=tmp_path/'run'; session=RunSession(t,package_digest=package.digest,arm=arm,objective=FrozenRecord.from_dict({'o':'x'}),slots=('ranking','diagnostic','final'),execution_limit=1,sidecar=run,verifier=AuditVerifier({'a':b'a'*32,'b':b'b'*32}),required_audit=('measurement',))
 class TransportError(RuntimeError): pass
 class Broken:
  def verify_diagnostic(self,subject):
   error=TransportError('transport'); error.partial_response=FrozenRecord.from_dict({'partial':'typed','cost':{'unit':'verifier_units','units':units}}); error.cost={'unit':'verifier_units','units':units}; raise error
 def model(request): return FrozenRecord.from_dict({'ranking':['a','b'],'rationale':'x'})
 with pytest.raises(TransportError): Q54CausalDriver(DockerExecutionBroker([tmp_path]),lambda _task,_bundle:{'data':path},Broken()).run(ModularWorkflow(session),cell=cell,scenario=scenario,model=model,package=package)
 events=[FrozenRecord(line).data() for line in (run/'trace.jsonl').read_text().splitlines()]; partial=next(i for i,e in enumerate(events) if e['stage']=='q54_authority_partial_response'); failure=next(i for i,e in enumerate(events) if e['stage']=='q54_authority_failure')
 assert partial<failure and events[failure]['data']['exception_reported_cost']=={'unit':'verifier_units','units':units} and events[failure]['data']['verified_cost']=={'unit':'verifier_units','units':None}
