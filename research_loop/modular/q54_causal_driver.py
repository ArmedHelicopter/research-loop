"""Causal Q5.4 driver: ranked selection, M4 outcome update, matched execution.

This is deliberately separate from the earlier diagnostic driver while its
causal defects remain under review.
"""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
from typing import Any, Mapping, Protocol

from research_loop.modular.benchmarks.execution import DockerExecutionBroker
from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask, required_text, strict_bool
from research_loop.modular.modules.exploration import ExplorationPlan, ResourceClosure, select_claimed_diagnostic
from research_loop.modular.modules.improvement import TrainingManifest
from research_loop.modular.panel_receipts import opaque_panel_cell_binding
from research_loop.ontology import ContractError

_VARIANTS=("subjective","preregistered_cost")

class PublicInputResolver(Protocol):
 def __call__(self, task:PublicTask, bundle:FrozenRecord)->Mapping[str,Path]: ...
class DiagnosticAuthority(Protocol):
 def verify_diagnostic(self, subject:FrozenRecord)->FrozenRecord: ...

def _map(x,n):
 if not isinstance(x,Mapping): raise ContractError(f'{n} must be mapping')
 return dict(x)
def _text(x,n): return required_text(x,n)
def _hex(x,n):
 x=_text(x,n)
 if len(x)!=64 or any(c not in '0123456789abcdef' for c in x): raise ContractError(f'{n} must be sha256')
 return x
def _inputs(x):
 x=_map(x,'input declarations')
 if not x: raise ContractError('at least one input declaration required')
 out={}
 for key,row in x.items():
  row=_map(row,'input declaration')
  if set(row)!={'sha256','byte_count'} or type(row['byte_count']) is not int or row['byte_count']<0: raise ContractError('input declaration invalid')
  out[_text(key,'input id')]={'sha256':_hex(row['sha256'],'input hash'),'byte_count':row['byte_count']}
 return out
def _authorities(x,identity):
 x=_map(x,'authority contract')
 if set(x)!={'contract_id','source_id','authorities'} or x['source_id']!=identity.group_id: raise ContractError('authority contract source drift')
 _text(x['contract_id'],'contract id')
 if not isinstance(x['authorities'],list) or len(x['authorities'])!=2: raise ContractError('exactly two authorities required')
 seen=set()
 for row in x['authorities']:
  if not isinstance(row,Mapping) or set(row)!={'authority_id','source_group'}: raise ContractError('authority fields invalid')
  aid=_text(row['authority_id'],'authority id'); _text(row['source_group'],'authority source')
  if aid in seen: raise ContractError('authority identities must differ')
  seen.add(aid)
 return x
def _program(x,sha):
 x=_text(x,'program')
 if '\r' in x or hashlib.sha256(x.encode('utf-8')).hexdigest()!=_hex(sha,'canonical program hash'): raise ContractError('program must be canonical LF and hash-bound')
 host=x.encode('utf-8').replace(b'\n',os.linesep.encode('ascii'))
 return {'text':x,'canonical_program_sha256':sha,'host_program_sha256':hashlib.sha256(host).hexdigest(),'host_program_byte_count':len(host)}
def _measurement(x,identity):
 x=_map(x,'measurement contract')
 if set(x)!={'source_id','contract_id','discriminator_id','observable','negative_control_id'} or x['source_id']!=identity.group_id: raise ContractError('measurement contract binding drift')
 for val in x.values(): _text(val,'measurement field')
 return x
def _diagnostics(x,branches,negative_control_id):
 if not isinstance(x,list) or len(x)<2: raise ContractError('two diagnostics required')
 branch_ids={b['hypothesis_id'] for b in branches}; out=[]; seen=set()
 for row in x:
  row=_map(row,'diagnostic')
  raw_fields={'diagnostic_id','branch_ids','program','program_sha256','image','inputs','cost','preregistered_uncertainty','negative_control_id'}
  frozen_fields={'diagnostic_id','branch_ids','program','canonical_program_sha256','host_program_sha256','host_program_byte_count','image','inputs','cost','preregistered_uncertainty','negative_control_id'}
  if set(row) not in (raw_fields,frozen_fields): raise ContractError('diagnostic fields incomplete')
  did=_text(row['diagnostic_id'],'diagnostic id')
  if _text(row['negative_control_id'],'negative control id')!=negative_control_id: raise ContractError('diagnostic negative-control binding drift')
  if did in seen or not isinstance(row['branch_ids'],list) or set(row['branch_ids'])!=branch_ids or len(row['branch_ids'])!=len(branch_ids): raise ContractError('diagnostic identity or common branch binding drift')
  seen.add(did)
  if type(row['cost']) not in (int,float) or row['cost']<=0 or type(row['preregistered_uncertainty']) not in (int,float) or row['preregistered_uncertainty']<0: raise ContractError('diagnostic cost or uncertainty invalid')
  program=_program(row['program'],row.get('program_sha256',row.get('canonical_program_sha256')))
  if set(row)==frozen_fields and (row['host_program_sha256']!=program['host_program_sha256'] or row['host_program_byte_count']!=program['host_program_byte_count']): raise ContractError('frozen host program bytes drift')
  out.append({'diagnostic_id':did,'branch_ids':sorted(_text(item,'branch id') for item in row['branch_ids']),'program':program['text'],'canonical_program_sha256':program['canonical_program_sha256'],'host_program_sha256':program['host_program_sha256'],'host_program_byte_count':program['host_program_byte_count'],'image':_text(row['image'],'image'),'inputs':_inputs(row['inputs']),'cost':row['cost'],'preregistered_uncertainty':row['preregistered_uncertainty'],'negative_control_id':negative_control_id})
 return out
def _item(raw,identity):
 raw=_map(raw,'Q5.4 material')
 if set(raw)!={'diagnostics','prediction_branches','measurement_contract','authority_contract'}: raise ContractError('Q5.4 material fields incomplete')
 branches=raw['prediction_branches']
 # The registry validates real competing predictions, including the shared
 # discriminator and non-identical predictions, before they can be frozen.
 from research_loop.modular.modules.predictions import PredictionRegistry
 if not isinstance(branches,list): raise ContractError('prediction branches must be list')
 PredictionRegistry(identity).freeze('caller-frozen diagnostic competition',branches,budget_units=1)
 measurement=_measurement(raw['measurement_contract'],identity)
 if any(not any(p['discriminator_id']==measurement['discriminator_id'] and p['observable']==measurement['observable'] for p in b['predictions']) for b in branches): raise ContractError('measurement discriminator and observable pair does not bind all branches')
 return {'diagnostics':_diagnostics(raw['diagnostics'],branches,measurement['negative_control_id']),'prediction_branches':branches,'measurement_contract':measurement,'authority_contract':_authorities(raw['authority_contract'],identity)}

def freeze_q54_causal_bundle(task:PublicTask,*,variants:Mapping[str,Mapping[str,Any]])->FrozenRecord:
 if not isinstance(task,PublicTask) or set(variants)!=set(_VARIANTS): raise ContractError('Q5.4 bundle variant coverage mismatch')
 task.identity.require_train()
 return FrozenRecord.from_dict({'schema':'q54-causal-bundle-v1','identity':task.identity.data(),'payload_digest':task.payload.content_hash,'variants':{k:_item(v,task.identity) for k,v in variants.items()}})

def q54_causal_injection(variant:str,*,task:FrozenRecord,evidence:FrozenRecord)->Mapping[str,Any]:
 public=PublicTask(DataIdentity.parse(task.data()['identity']),FrozenRecord.from_dict(task.data()['payload']))
 raw=evidence.data(); rebuilt=freeze_q54_causal_bundle(public,variants=raw.get('variants',{}))
 if raw.get('schema')!='q54-causal-bundle-v1' or rebuilt.content_hash!=evidence.content_hash or variant not in _VARIANTS: raise ContractError('Q5.4 causal bundle binding drift')
 return {'schema':'q54-causal-controller-v1','bundle':rebuilt.data()}

def _receipt(receipt,subject):
 if not isinstance(receipt,FrozenRecord): raise ContractError('authority must return frozen receipt')
 row=receipt.data(); contract=subject.data()['authority_contract']
 if set(row)!={'schema','subject_digest','status','observations','cost','classifications'} or row['schema']!='q54-causal-authority-receipt-v1' or row['subject_digest']!=subject.content_hash or row['status'] not in ('passed','failed','unknown'): raise ContractError('authority receipt binding drift')
 expected={a['authority_id']:a['source_group'] for a in contract['authorities']}; seen=set(); statuses=[]
 for obs in row['observations'] if isinstance(row['observations'],list) else ():
  if not isinstance(obs,Mapping) or set(obs)!={'authority_id','source_group','contract_id','subject_digest','observation_digest','status','signature_verified'} or obs['authority_id'] not in expected or obs['authority_id'] in seen or obs['source_group']!=expected[obs['authority_id']] or obs['contract_id']!=contract['contract_id'] or obs['subject_digest']!=subject.content_hash or obs['status'] not in ('passed','failed','unknown') or strict_bool(obs['signature_verified'],'signature') is not True: raise ContractError('authority observation binding drift')
  _hex(obs['observation_digest'],'observation hash'); seen.add(obs['authority_id']); statuses.append(obs['status'])
 if seen!=set(expected): raise ContractError('authority observation pair incomplete')
 aggregate='failed' if 'failed' in statuses else 'unknown' if 'unknown' in statuses else 'passed'
 if row['status']!=aggregate: raise ContractError('authority status must aggregate both observations')
 if not isinstance(row['cost'],Mapping) or set(row['cost'])!={'unit','units'} or row['cost']['unit']!='verifier_units' or (row['cost']['units'] is not None and (type(row['cost']['units']) is not int or row['cost']['units']<0)): raise ContractError('authority cost invalid')
 ids={b['hypothesis_id'] for b in subject.data()['prediction_branches']}
 if not isinstance(row['classifications'],Mapping) or set(row['classifications'])!=ids or any(v not in ('consistent','failed','unknown') for v in row['classifications'].values()): raise ContractError('authority classifications do not bind plan')
 # A failed or unknown authority result cannot be promoted into an M7 gate.
 if (row['status']!='passed' or subject.data()['execution_receipt']['status']!='succeeded') and any(v!='unknown' for v in row['classifications'].values()): raise ContractError('unqualified or failed execution outcome must remain unknown')
 return row

@dataclass(frozen=True)
class Q54CausalDriver:
 broker:DockerExecutionBroker
 input_resolver:PublicInputResolver
 authority:DiagnosticAuthority
 experiment_id:str='Q5.4'
 slots:tuple[str,...]=('ranking','diagnostic','final')
 execution_limit:int=1
 docker_execution:str='one literal selected public diagnostic in every arm'
 def slots_for(self,cell): return self.slots
 def run(self,workflow,*,cell,scenario,model,package):
  if not isinstance(self.broker,DockerExecutionBroker) or not callable(self.input_resolver) or not callable(getattr(self.authority,'verify_diagnostic',None)): raise ContractError('broker, resolver and authority port required before model calls')
  body=scenario.data(); task=workflow.session.task
  if set(body)!={'experiment_id','variant','controller_input','base','controls'} or body['experiment_id']!='Q5.4' or body['variant']!=cell.variant or cell.coverage_id!='Q5.4' or cell.task_digest!=task.content_hash or cell.scenario_digest!=scenario.content_hash or package.digest!=cell.package_digest: raise ContractError('Q5.4 scenario or cell drift')
  ctrl=_map(body['controller_input'],'controller'); bundle=FrozenRecord.from_dict(_map(ctrl.get('bundle'),'bundle'))
  rebuilt=freeze_q54_causal_bundle(task,variants=bundle.data().get('variants',{})); base=_map(body['base'],'base'); controls=_map(body['controls'],'controls')
  if set(ctrl)!={'schema','bundle'} or ctrl['schema']!='q54-causal-controller-v1' or bundle.content_hash!=rebuilt.content_hash or set(base)!={'task','evidence','budget'} or base['task']!=task.content_hash or base['evidence']!=bundle.content_hash or set(controls)!={'same_task','same_evidence','same_budget'} or any(strict_bool(v,k) is not True for k,v in controls.items()): raise ContractError('Q5.4 controller binding drift')
  _hex(base['budget'],'budget digest')
  if task.identity not in TrainingManifest(FrozenRecord.from_dict(package.record.data()['training_manifest'])).identities(): raise ContractError('package omits task')
  item=bundle.data()['variants'][cell.variant]
  from research_loop.modular.benchmarks.execution import ExecutionRequest
  for diagnostic in item['diagnostics']:
   ExecutionRequest(task.identity,diagnostic['image'],Path('unresolved.py'),{key:Path('unresolved.csv') for key in diagnostic['inputs']})
  all_inputs={}
  for diagnostic in item['diagnostics']:
   for artifact_id,declaration in diagnostic['inputs'].items():
    if artifact_id in all_inputs and all_inputs[artifact_id]!=declaration: raise ContractError('shared input id has conflicting frozen declarations')
    all_inputs[artifact_id]=declaration
  paths=self.input_resolver(task,bundle)
  if not isinstance(paths,Mapping) or set(paths)!=set(all_inputs): raise ContractError('resolver input set mismatch')
  artifacts=self.broker.validate_inputs(task.identity,paths)
  actual={a.artifact_id:a.record.data() for a in artifacts}; declared={k:{'artifact_id':k,**v} for k,v in all_inputs.items()}
  if actual!=declared: raise ContractError('literal input artifact declarations drift')
  ranking=workflow.invoke_model('ranking',model,instruction='Rank every public diagnostic ID for the claimed task before execution. Return ranking and rationale.',evidence_only=True,module_context=FrozenRecord.from_dict({'panel_cell':opaque_panel_cell_binding(cell),'diagnostics':[{'diagnostic_id':d['diagnostic_id'],'program':d['program'],'cost':d['cost']} for d in item['diagnostics']]}))
  rank=ranking.data()
  if set(rank)!={'ranking','rationale'} or not isinstance(rank['ranking'],list) or set(rank['ranking'])!={d['diagnostic_id'] for d in item['diagnostics']} or len(rank['ranking'])!=len(item['diagnostics']): raise ContractError('ranking must cover every caller-frozen diagnostic exactly once')
  _text(rank['rationale'],'ranking rationale')
  runtime_plan=None
  if 'M4' in workflow.enabled:
   runtime_plan=workflow.predictions.freeze('caller-frozen diagnostic competition',item['prediction_branches'],budget_units=1)
  scores={did:len(rank['ranking'])-index for index,did in enumerate(rank['ranking'])}
  candidates=[]
  for d in item['diagnostics']:
   score=scores[d['diagnostic_id']] if cell.variant=='subjective' else d['preregistered_uncertainty']/d['cost']
   candidates.append(FrozenRecord.from_dict({'diagnostic_id':d['diagnostic_id'],'subjective_score':score,'uncertainty_reduction':d['preregistered_uncertainty'],'cost':d['cost']}))
  plan=ExplorationPlan('q54-'+bundle.content_hash,task.identity,bundle,ResourceClosure('caller',item['diagnostics'][0]['canonical_program_sha256'],item['measurement_contract']['negative_control_id'],1,0))
  chosen_decision=select_claimed_diagnostic(plan,FrozenRecord.from_dict({'policy_version':'q54-'+cell.variant,'identity':task.identity.data(),'criterion':'subjective' if cell.variant=='subjective' else 'uncertainty_per_cost','frozen_before_validation':True}),tuple(candidates))
  chosen=next(d for d in item['diagnostics'] if d['diagnostic_id']==chosen_decision.data()['diagnostic_id'])
  workflow.session._record('q54_execution_reservation',{'limit':1,'selected_diagnostic_id':chosen['diagnostic_id'],'m7_enabled':'M7' in workflow.enabled})
  execution=workflow.session.execute(chosen['program'],broker=self.broker,image=chosen['image'],inputs={k:paths[k] for k in chosen['inputs']})
  actual_program=Path(execution.artifact.path).read_bytes() if execution.artifact is not None else b''
  if (execution.artifact is None or execution.artifact.sha256!=chosen['host_program_sha256'] or execution.artifact.byte_count!=chosen['host_program_byte_count'] or hashlib.sha256(actual_program).hexdigest()!=chosen['host_program_sha256'] or len(actual_program)!=chosen['host_program_byte_count'] or execution.record.data().get('input_artifacts')!={k:{'artifact_id':k,**v} for k,v in chosen['inputs'].items()}): raise ContractError('execution receipt literal host-byte binding drift')
  # Re-read once after Docker.  This catches a resolver path changed between
  # broker validation/execution and authority review; the authority receives
  # exactly these verified bytes, never a second unchecked read.
  verified_input_bytes={}
  for artifact_id,declaration in chosen['inputs'].items():
   raw_input=paths[artifact_id].read_bytes()
   if len(raw_input)!=declaration['byte_count'] or hashlib.sha256(raw_input).hexdigest()!=declaration['sha256']: raise ContractError('public input changed after execution')
   verified_input_bytes[artifact_id]=raw_input.hex()
  # Authority gets the complete receipt and read-only public bytes; model never does.
  subject=FrozenRecord.from_dict({'schema':'q54-causal-authority-subject-v1','identity':task.identity.data(),'task_digest':task.content_hash,'bundle_digest':bundle.content_hash,'cell_binding':opaque_panel_cell_binding(cell),'authority_contract':item['authority_contract'],'prediction_branches':item['prediction_branches'],'measurement_contract':item['measurement_contract'],'selection':chosen,'ranking':rank,'execution_receipt':execution.data(),'public_program_bytes':actual_program.hex(),'public_input_bytes':verified_input_bytes})
  workflow.session._record('q54_authority_request',{'subject':subject.data(),'subject_digest':subject.content_hash,'cost':{'unit':'verifier_units','units':None}})
  raw=None
  try:
   raw=self.authority.verify_diagnostic(subject)
   workflow.session._record('q54_authority_response_raw',{'subject_digest':subject.content_hash,'receipt':raw.data() if isinstance(raw,FrozenRecord) else None,'reported_cost':raw.data().get('cost') if isinstance(raw,FrozenRecord) else None})
   receipt=_receipt(raw,subject)
  except Exception as exc:
   partial=getattr(exc,'partial_response',None)
   partial_valid=isinstance(partial,FrozenRecord)
   if partial_valid:
    workflow.session._record('q54_authority_partial_response',{'subject_digest':subject.content_hash,'partial_response':partial.data(),'reported_cost':partial.data().get('cost')})
   exception_cost=getattr(exc,'cost',None)
   if isinstance(exception_cost,FrozenRecord): exception_cost=exception_cost.data()
   cost_valid=isinstance(exception_cost,Mapping) and set(exception_cost)=={'unit','units'} and exception_cost['unit']=='verifier_units' and (exception_cost['units'] is None or (type(exception_cost['units']) is int and exception_cost['units']>=0))
   reported=raw.data().get('cost') if isinstance(raw,FrozenRecord) else partial.data().get('cost') if partial_valid else None
   workflow.session._record('q54_authority_failure',{'subject_digest':subject.content_hash,'error_type':type(exc).__name__,
    'reported_cost':reported,'exception_reported_cost':dict(exception_cost) if cost_valid else None,
    'exception_cost_invalid':exception_cost is not None and not cost_valid,
    'partial_response_invalid':partial is not None and not partial_valid,
    'verified_cost':{'unit':'verifier_units','units':None}}); raise
  receipt_record=FrozenRecord.from_dict(receipt)
  update=None
  if runtime_plan is not None:
   update=workflow.predictions.record_outcome(runtime_plan.plan_id,item['measurement_contract']['discriminator_id'],receipt_record.content_hash,receipt['classifications'],{'trusted_evaluator':'+'.join(a['authority_id'] for a in item['authority_contract']['authorities']),'verified':True})
  public_execution={'binding':execution.content_hash,'status':execution.status,'program_sha256':chosen['canonical_program_sha256'],'host_program_sha256':chosen['host_program_sha256'],'input_artifacts':execution.record.data()['input_artifacts'],'exit_code':execution.record.data().get('exit_code'),'stdout':execution.record.data().get('stdout','')}
  competition=None if update is None else {'plan_binding':runtime_plan.payload.content_hash,'eliminated':sorted(k for k,v in receipt['classifications'].items() if v=='failed'),'retained':sorted(k for k,v in receipt['classifications'].items() if v=='consistent'),'unknown':sorted(k for k,v in receipt['classifications'].items() if v=='unknown')}
  disposition='stop' if execution.status!='succeeded' else ('continue' if receipt['status']=='passed' else 'defer')
  gate={'disposition':disposition,'receipt_binding':receipt_record.content_hash} if 'M7' in workflow.enabled else {'disposition':'unapplied','receipt_binding':receipt_record.content_hash}
  public={'execution':public_execution,'selection':{'diagnostic_id':chosen['diagnostic_id'],'cost':chosen['cost']},'competition':competition,'gate':gate}
  diagnostic=workflow.invoke_model('diagnostic',model,instruction='Make a bounded diagnostic decision from this public execution observation. Return decision (continue, stop, or defer) and rationale.',evidence_only=True,module_context=FrozenRecord.from_dict({'panel_cell':opaque_panel_cell_binding(cell),'observation':public}))
  d=diagnostic.data()
  if set(d)!={'decision','rationale'} or d['decision'] not in ('continue','stop','defer') or ('M7' in workflow.enabled and d['decision']!=disposition): raise ContractError('diagnostic decision invalid or overrides applied M7 gate')
  _text(d['rationale'],'diagnostic rationale')
  final=workflow.invoke_model('final',model,instruction='Return the standard P0 candidate using this public diagnostic observation.',evidence_only=True,module_context=FrozenRecord.from_dict({'panel_cell':opaque_panel_cell_binding(cell),'required_objective_digest':workflow.session.objective.content_hash,'observation':public,'diagnostic':d}))
  stage=workflow._trace('q54_m7_gate' if 'M7' in workflow.enabled else 'q54_m7_baseline','executed',selection=chosen_decision.data(),execution_binding=execution.content_hash,authority_binding=receipt_record.content_hash,m4_outcome=None if update is None else update.data(),gate=gate)
  return stage,final,(ranking,diagnostic,final)
