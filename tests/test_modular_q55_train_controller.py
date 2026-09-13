"""Actual custody/controller entry coverage for Q5.5."""
import hashlib
import json

import pytest
from evaluation.modular.train_io import TrainPacketExporter
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.panel_plan import obligation_grids, executable_arms
from research_loop.modular.q55_causal_driver import freeze_q55_causal_bundle
from research_loop.modular.runtime import AuditVerifier
from research_loop.modular.train_controller import FrozenTrainControllerConfig, run_train_panel
from research_loop.ontology import ContractError
from test_modular_q55_causal_driver import source_rows, PublicAuthority, AUTHORITY_KEYS, PublicProvider
from test_modular_q54_train_controller import _closed_shape
from test_modular_train_controller import config, snapshot_and_custody, model_port, FINAL

IMAGE='research-benchmark-python@sha256:1433f0d223b0773b0d8c3184fa4ff6ab0a3891113442f1592d8d7e883d21a349'
V=('missing_data','missing_method','missing_budget','missing_control')

def evidence(task,csv):
 p="from pathlib import Path\nprint(sum(int(x) for x in Path('/input/data_csv').read_text().split()[1:]))\n"; contract={'contract_id':'q55-controller','source_id':task.identity.group_id,'authorities':[{'authority_id':'authority-a','source_group':'external-a'},{'authority_id':'authority-b','source_group':'external-b'}]}
 rows={}
 for v in V:
  missing=v.removeprefix('missing_'); rows[v]={'availability':{x:x!=missing for x in ('data','method','budget','control')},'program':p,'program_sha256':hashlib.sha256(p.encode()).hexdigest(),'image':IMAGE,'inputs':{'data_csv':{'sha256':hashlib.sha256(csv).hexdigest(),'byte_count':len(csv)}},'authority_contract':contract,'closure_source_id':{'data':'c01','method':'c02','budget':'c03','control':'c04'}[missing],'ordinary_source_id':{'data':'o01','method':'o02','budget':'o03','control':'o04'}[missing]}
 return freeze_q55_causal_bundle(task,items=rows,sources=source_rows())

def _config(tmp):
 snap,custody=snapshot_and_custody(tmp); base=config(custody,snap,tmp).data(); packets=TrainPacketExporter(custody,snap,tmp/'material').export(base['item_ids']); grid=obligation_grids(('Q5.5',),baseline_digest=base['baseline_digest'],p0_control=FrozenRecord.from_dict(base['p0_control']))['Q5.5']; package=next(iter(base['packages_by_arm'].values()))
 schemas={'diagnostic':_closed_shape({'assessment':'public','evidence_refs':['public'],'counterexamples':['public'],'uncertainty':'public'}),'final':FINAL}
 return snap,custody,FrozenTrainControllerConfig(FrozenRecord.from_dict({**base,'schema':'train-panel-controller-v1','engineering_scope':'train_only_panel_engineering','stage':'q55-custody-controller','scope_ids':['Q5.5'],'schemas':schemas,'max_calls':64,'budget':{'model_calls':2,'execution_opportunities':1,'retrieval_calls':3,'verification_calls':1},'evidence_by_task':{p.task.content_hash:evidence(p.task,p.csv_path.read_bytes()).data() for p in packets},'packages_by_arm':{a.content_hash:package for a in executable_arms(grid).values()}}))

def test_q55_full_32_cells_custody_model_docker_authority(tmp_path,monkeypatch):
 snap,custody,frozen=_config(tmp_path); seen=[]
 def response(request):
  row=request.data(); seen.append(row)
  if row['slot']=='diagnostic': return FrozenRecord.from_dict({'assessment':'public','evidence_refs':['public'],'counterexamples':['public'],'uncertainty':'public'})
  return FrozenRecord.from_dict({'objective_digest':FrozenRecord.from_dict(row['objective']).content_hash,'outcome':'unknown','evidence_ids':[],'conclusion':'bounded closure','programme_complete':False})
 port=model_port(tmp_path,monkeypatch,max_calls=64,schemas=frozen.data()['schemas'],response_factory=response)
 provider,authority=PublicProvider(),PublicAuthority()
 result=run_train_panel(frozen,custody=custody,snapshot_root=snap,export_root=tmp_path/'export',run_root=tmp_path/'run',model=port,audit_verifier=AuditVerifier({'a':b'a'*32,'b':b'b'*32}),q55_authority=authority,q55_authority_keys=AUTHORITY_KEYS,q55_provider=provider)
 assert len(result.runtimes)==32 and len(port.ledger['calls'])==64 and all(x.status=='succeeded' for x in result.runtimes)
 assert len(seen)==64 and len(provider.calls)==96 and len(authority.calls)==32
 assert {call['lane'] for call in provider.calls}=={'support','counter','method'}
 assert all(call['call_limit']==1 and call['source_limit']==8 for call in provider.calls)
 for runtime in result.runtimes:
  trace=[json.loads(line) for line in runtime.trace_path.read_text(encoding='utf-8').splitlines()]
  requests=[event for event in trace if event['stage']=='model_request']
  retrieval=[event for event in trace if event['stage']=='q55_retrieval_request']
  authority_requests=[event for event in trace if event['stage']=='q55_authority_request']
  authority_raw=[event for event in trace if event['stage']=='q55_authority_raw_response']
  assert [event['data']['request']['slot'] for event in requests]==['diagnostic','final']
  assert [event['data']['lane'] for event in retrieval]==['support','counter','method']
  assert len(authority_requests)==len(authority_raw)==1
  assert len(authority_raw[0]['data']['response']['observations'])==2
  assert sum(event['stage']=='execution_request' for event in trace)==(1 if runtime.cell_key[-1] in {'10','11'} else 0)
 assert sum('execution_result' in runtime.trace_path.read_text(encoding='utf-8') for runtime in result.runtimes)==16

def test_q55_foreign_csv_rejected_before_provider_model_authority(tmp_path,monkeypatch):
 snap,custody,frozen=_config(tmp_path); data=frozen.data(); next(iter(data['evidence_by_task'].values()))['items']['missing_data']['inputs']['data_csv']['sha256']='0'*64; frozen=FrozenTrainControllerConfig(FrozenRecord.from_dict(data)); port=model_port(tmp_path,monkeypatch,max_calls=64,schemas=data['schemas']); provider=PublicProvider()
 class Never:
  def verify_closure(self,subject): pytest.fail('authority called')
 with pytest.raises(ContractError,match='differs from exported train CSV bytes'):
  run_train_panel(frozen,custody=custody,snapshot_root=snap,export_root=tmp_path/'export',run_root=tmp_path/'run',model=port,audit_verifier=AuditVerifier({'a':b'a'*32,'b':b'b'*32}),q55_authority=Never(),q55_authority_keys=AUTHORITY_KEYS,q55_provider=provider)
 assert port.ledger['calls']==[] and provider.calls==[]
