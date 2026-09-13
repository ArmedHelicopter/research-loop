from pathlib import Path
from research_loop.modular import panel_runner
from research_loop.modular.benchmarks import BladeAdapter,DiscoveryBenchAdapter
from research_loop.modular.contracts import DataIdentity,FrozenRecord
from research_loop.modular.modules.improvement import CandidatePackage,TrainingManifest
from research_loop.modular.panel_plan import compile_train_panel,executable_arms
from research_loop.modular.panel_receipts import PanelReceiptVerifier
from research_loop.modular.runtime import AuditVerifier
from research_loop.modular.prediction_panel_drivers import freeze_prediction_bundle,Q32JointSeparateDriver,Q53DedupDriver

def branch(i,key,d): return {'hypothesis_id':i,'mechanism_key':key,'mechanism':'public '+key,'intervention':'public intervention','elimination_condition':'public failure','predictions':[{'prediction_id':i+'p','discriminator_id':'public-disc','observable':'public x','direction':d,'value_range':None,'failure_condition':'not '+d}]}
def task(name):
 i=DataIdentity(name,'pred-'+name,name+':pred','v1','8'*64,'train'); return DiscoveryBenchAdapter().prepare(i,{'task_id':i.task_id,'question':'PUBLIC '+name,'source_kind':'synthetic','dataset':[{'name':'x','columns':[{'name':'x'}]}]}) if name=='discoverybench' else BladeAdapter().prepare(i,{'task_id':i.task_id,'dataset_id':'p','research_question':'PUBLIC '+name,'data_schema':[{'name':'x','dtype':'float'}]})
def material(t):
 a,b,c=branch('a','one','positive'),branch('b','two','negative'),branch('c','three','null'); plan=lambda bs,n,s:{'branches':bs,'budget_units':n,'support_records':[{'record':'SUPPORT-'+s}]}
 q32={'joint':{'plans':[plan([a,b,c],3,'J')]},'separate':{'plans':[plan([a,b],1,'1'),plan([a,c],1,'2'),plan([b,c],1,'3')]}}
 proposals=lambda x:[{'proposal_id':'a','mechanism_key':'shared' if x!='title' else 'one','prediction_signature':'d:positive','title':'same' if x=='title' else 'first'},{'proposal_id':'b','mechanism_key':'shared' if x!='title' else 'two','prediction_signature':'d:negative' if x=='opposite_prediction' else 'd:positive' if x=='same_mechanism' else 'd:null','title':'same' if x=='title' else 'second'}]
 q53={x:{'proposals':proposals(x),'plan':{'branches':[a,b],'budget_units':2}} for x in ('same_mechanism','opposite_prediction','title')}
 return freeze_prediction_bundle(t,public_evidence={'evidence':'PUBLIC'},q32=q32,q53=q53)
def model(r):
 b=r.data(); return FrozenRecord.from_dict({'objective_digest':b['module_context']['required_objective_digest'],'outcome':'unknown','evidence_ids':[],'conclusion':'bounded','programme_complete':False}) if b['slot']=='final' else FrozenRecord.from_dict({'assessment':'public','evidence_refs':['public'],'counterexamples':[],'uncertainty':'bounded'})
def test_full_prediction_grid(tmp_path,monkeypatch):
 tasks={x:task(x) for x in ('discoverybench','blade')}; package=CandidatePackage.create(parent_digest=None,manifest=TrainingManifest.freeze([x.identity for x in tasks.values()]),changes={'prompt':{'instructions':'p'}},search_cost=0)
 from research_loop.modular.panel_plan import obligation_grids
 grids=obligation_grids(('Q3.2','Q5.3'),baseline_digest='base',p0_control=FrozenRecord.from_dict({'p':'0'})); packages={a.content_hash:package for g in grids.values() for a in executable_arms(g).values()}
 compiled=compile_train_panel(stage='p',scope_ids=('Q3.2','Q5.3'),tasks=tuple(tasks.values()),evidence_by_task={x.content_hash:material(x) for x in tasks.values()},budget=FrozenRecord.from_dict({'calls':4}),baseline_digest='base',p0_control=FrozenRecord.from_dict({'p':'0'}),packages_by_arm=packages,scorer=FrozenRecord.from_dict({'s':'none'}),acceptance_criteria=FrozenRecord.from_dict({'a':'engineering'}))
 monkeypatch.setitem(panel_runner.DRIVERS,'Q3.2',Q32JointSeparateDriver()); monkeypatch.setitem(panel_runner.DRIVERS,'Q5.3',Q53DedupDriver()); runs=[]
 for n,c in enumerate(compiled.panel.cells):
  r=panel_runner.run_train_cell(c,task=tasks[c.identity.benchmark],scenario=compiled.scenarios[c.key],package=compiled.packages[c.runtime_arm.content_hash],objective=FrozenRecord.from_dict({'o':'x'}),sidecar=tmp_path/str(n),model=model,audit_verifier=AuditVerifier({'a':b'a'*32,'b':b'b'*32})); assert r.runtime.status=='succeeded'; runs.append(r.runtime)
 assert PanelReceiptVerifier().verify(compiled.panel,tuple(runs)).decision=='engineering_verified'

