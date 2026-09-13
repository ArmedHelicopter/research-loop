"""Production Q3.2 and Q5.3 M4 prediction drivers."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Mapping
from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask
from research_loop.modular.modules.predictions import PredictionRegistry, freeze_shared_experiment, deduplicate_mechanism_predictions, deduplicate_titles
from research_loop.modular.panel_receipts import PanelCell, opaque_panel_cell_binding
from research_loop.ontology import ContractError

def _branch(value: Any) -> dict[str,Any]:
 if not isinstance(value,Mapping) or set(value)!={'hypothesis_id','mechanism_key','mechanism','intervention','elimination_condition','predictions'}: raise ContractError('prediction material needs complete operational branches')
 return dict(value)
def _bundle(task:PublicTask, body:Mapping[str,Any]):
 if not isinstance(body,Mapping) or body.get('schema')!='typed-prediction-panel-bundle-v1' or body.get('identity')!=task.identity.data() or not isinstance(body.get('public_evidence'),Mapping): raise ContractError('prediction driver requires typed caller bundle')
 return body
def freeze_prediction_bundle(task:PublicTask, *, public_evidence:Mapping[str,Any], q32:Mapping[str,Any], q53:Mapping[str,Any])->FrozenRecord:
 body={'schema':'typed-prediction-panel-bundle-v1','identity':task.identity.data(),'public_evidence':dict(public_evidence),'q32':{k:dict(v) for k,v in q32.items()},'q53':{k:dict(v) for k,v in q53.items()}}
 if set(body['q32'])!={'joint','separate'} or set(body['q53'])!={'same_mechanism','opposite_prediction','title'}: raise ContractError('prediction bundle lacks frozen variants')
 for key,item in body['q32'].items():
  plans=item.get('plans');
  if not isinstance(plans,list) or (len(plans)!=1 if key=='joint' else len(plans)!=3): raise ContractError('Q3.2 needs its declared plan layout')
  if sum(int(plan.get('budget_units',0)) for plan in plans)!=3: raise ContractError('Q3.2 variants need matched three-unit budget')
  for plan in plans:
   if set(plan)!={'branches','budget_units','support_records'} or not isinstance(plan['branches'],list) or not plan['branches'] or not isinstance(plan['support_records'],list) or not plan['support_records']: raise ContractError('Q3.2 plan material is incomplete')
   [_branch(x) for x in plan['branches']]
  supports=[r for plan in plans for r in plan['support_records']]
  if key=='joint' and len({FrozenRecord.from_dict(r).content_hash for r in supports})!=1: raise ContractError('joint plan requires one common support record')
  if key=='separate' and len({FrozenRecord.from_dict(r).content_hash for r in supports})!=3: raise ContractError('separate plan requires three distinct support records')
 for item in body['q53'].values():
  if set(item)!={'proposals','plan'} or not isinstance(item['proposals'],list) or len(item['proposals'])<2 or not isinstance(item['plan'],Mapping): raise ContractError('Q5.3 requires typed proposals and plan')
  for proposal in item['proposals']:
   if not isinstance(proposal,Mapping) or set(proposal)!={'proposal_id','mechanism_key','prediction_signature','title'}: raise ContractError('Q5.3 proposal malformed')
  plan=item['plan'];
  if set(plan)!={'branches','budget_units'} or not isinstance(plan['branches'],list): raise ContractError('Q5.3 plan malformed')
  [_branch(x) for x in plan['branches']]
 return FrozenRecord.from_dict(body)
def prediction_panel_injection(experiment_id,variant,*,task,evidence):
 raw=task.data(); public=PublicTask(DataIdentity.parse(raw['identity']),FrozenRecord.from_dict(raw['payload']))
 body=_bundle(public,evidence.data())
 key='q32' if experiment_id=='Q3.2' else 'q53'
 if experiment_id not in {'Q3.2','Q5.3'} or variant not in body[key]: raise ContractError('prediction bundle lacks selected variant')
 return {'schema':'prediction-panel-controller-v1','material_bundle':body}
def _material(task,scenario,experiment,variant):
 ctrl=scenario.data().get('controller_input',{}); body=_bundle(task,ctrl.get('material_bundle',{}))
 if scenario.data().get('base',{}).get('evidence')!=FrozenRecord.from_dict(body).content_hash: raise ContractError('prediction bundle does not bind scenario evidence')
 return body['public_evidence'], body['q32' if experiment=='Q3.2' else 'q53'][variant]
def _final(workflow,cell,model,package,material):
 return workflow.invoke_model('final',model,instruction='Return bounded train-only candidate. Copy required_objective_digest exactly.',module_context=FrozenRecord.from_dict({'panel_cell':opaque_panel_cell_binding(cell),'required_objective_digest':workflow.session.objective.content_hash,'prediction_artifacts':material}))
@dataclass(frozen=True)
class Q32JointSeparateDriver:
 experiment_id:str='Q3.2'; slots:tuple[str,...]=('plan_1','plan_2','plan_3','final'); execution_limit:int=0; docker_execution:str='not_requested_by_driver'
 def slots_for(self,cell): return self.slots
 def run(self,workflow,*,cell,scenario,model,package):
  evidence,data=_material(workflow.session.task,scenario,'Q3.2',cell.variant); plans=data['plans']; responses=[]; artifacts=[]
  frozen_joint=None
  for n in range(3):
   plan=plans[0] if len(plans)==1 else plans[n]; response=workflow.invoke_model(f'plan_{n+1}',model,instruction='Assess the supplied public operational prediction plan and support records.',module_context=FrozenRecord.from_dict({'panel_cell':opaque_panel_cell_binding(cell),'public_evidence':evidence,'plan_material':plan})); responses.append(response)
   if 'M4' in workflow.enabled:
    frozen=frozen_joint if frozen_joint is not None else freeze_shared_experiment(workflow.predictions,'public joint-or-separate prediction question',plan['branches'],budget_units=plan['budget_units']); frozen_joint=frozen; artifacts.append({'plan':frozen.payload.data(),'support_records':plan['support_records'],'response':response.data()})
   else: artifacts.append({'plan':None,'support_records':plan['support_records'],'response':response.data()})
  stage=workflow._trace('stage_1' if 'M4' in workflow.enabled else 'operation_m4_control','executed',artifact_count=len(artifacts))
  final=_final(workflow,cell,model,package,{'joint_or_separate':artifacts});
  if final.data().get('objective_digest')!=workflow.session.objective.content_hash: raise ContractError('Q3.2 final objective mismatch')
  return stage,final,tuple(responses+[final])
@dataclass(frozen=True)
class Q53DedupDriver:
 experiment_id:str='Q5.3'; slots:tuple[str,...]=('dedup','final'); execution_limit:int=0; docker_execution:str='not_requested_by_driver'
 def slots_for(self,cell): return self.slots
 def run(self,workflow,*,cell,scenario,model,package):
  evidence,data=_material(workflow.session.task,scenario,'Q5.3',cell.variant); response=workflow.invoke_model('dedup',model,instruction='Assess supplied public operational proposals before a possible mechanism-prediction deduplication.',module_context=FrozenRecord.from_dict({'panel_cell':opaque_panel_cell_binding(cell),'public_evidence':evidence,'proposals':data['proposals'],'plan_material':data['plan']}))
  if 'M4' in workflow.enabled:
   kept,removed=deduplicate_mechanism_predictions(data['proposals']); title_kept,title_removed=deduplicate_titles(data['proposals']); frozen=freeze_shared_experiment(workflow.predictions,'public dedup prediction question',data['plan']['branches'],budget_units=data['plan']['budget_units']); artifact={'kept':list(kept),'removed':list(removed),'title_baseline':{'kept':list(title_kept),'removed':list(title_removed)},'plan':frozen.payload.data(),'response':response.data()}
  else: artifact={'kept':None,'removed':None,'title_baseline':None,'plan':None,'response':response.data()}
  stage=workflow._trace('stage_1' if 'M4' in workflow.enabled else 'operation_m4_control','executed',dedup_applied='M4' in workflow.enabled)
  final=_final(workflow,cell,model,package,{'deduplication':artifact});
  if final.data().get('objective_digest')!=workflow.session.objective.content_hash: raise ContractError('Q5.3 final objective mismatch')
  return stage,final,(response,final)
