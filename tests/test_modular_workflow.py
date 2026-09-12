import subprocess
from pathlib import Path
import pytest
from research_loop.modular.benchmarks import BladeAdapter
from research_loop.modular.benchmarks.execution import DockerExecutionBroker
from research_loop.modular.combinations import default_compatibility
from research_loop.modular.contracts import DataIdentity,FrozenRecord
from research_loop.modular.modules.admission import AuditItem,ScientificState
from research_loop.modular.modules.retrieval import SourceDocument,FrozenSourceBundle,FrozenRetrievalPolicy,RetrievalBudget,RetrievalSignals
from research_loop.modular.modules.exploration import ExplorationPlan,ResourceClosure,FeasibilityObservation,ExplorationBudget
from research_loop.modular.modules.scheduling import FifoScheduler
from research_loop.modular.runtime import RunSession,AuditAuthority,AuditVerifier
from research_loop.modular.workflow import ModularWorkflow

KEYS={"a":b"a"*32,"b":b"b"*32}
def make(tmp, enabled, slots):
 i=DataIdentity("blade","fixture","source","v1","split","train")
 t=BladeAdapter().prepare(i,{"task_id":"fixture","dataset_id":"d","research_question":"q","data_schema":[{"name":"x"}]})
 s=RunSession(t,package_digest="pkg",arm=default_compatibility("base").arm(enabled),objective=FrozenRecord.from_dict({"question":"q","primary":"p"}),slots=slots,execution_limit=2,sidecar=tmp,verifier=AuditVerifier(KEYS),required_audit=("measurement",))
 data=tmp/"p.csv";data.write_text("x\\n1\\n")
 b=DockerExecutionBroker([tmp],runner=lambda *a,**k:subprocess.CompletedProcess(a[0],0,b"ok",b""))
 return s,b,{"data":data}
def audit(s,e):
 return [AuditAuthority(n,k).issue(identity=s.task.identity,objective_digest=s.objective.content_hash,execution_digest=e.content_hash,state=ScientificState("valid","supported","unknown","explore"),outcome="positive",audit=[AuditItem("measurement",True,True)]) for n,k in KEYS.items()]
class Provider:
 def __init__(self,docs):self.docs=docs;self.calls=[]
 def search(self,**kw):self.calls.append(kw["lane"]);return [x for x in self.docs if x.lane==kw["lane"]]
def branches():
 return [{"hypothesis_id":"h1","mechanism_key":"m1","mechanism":"one","intervention":"i","elimination_condition":"f","predictions":[{"prediction_id":"p1","discriminator_id":"d","observable":"o","direction":"up","value_range":None,"failure_condition":"down"}]},{"hypothesis_id":"h2","mechanism_key":"m2","mechanism":"two","intervention":"i","elimination_condition":"f","predictions":[{"prediction_id":"p2","discriminator_id":"d","observable":"o","direction":None,"value_range":[0,1],"failure_condition":"out"}]}]
def review(kind):return {"assessment":kind,"evidence_refs":["root"],"counterexamples":[],"uncertainty":"u"}

def test_public_adapter_driver_calls_m4_to_m8_and_final_gate(tmp_path):
 slots=("m4","r1","r2","m6","final");s,b,inputs=make(tmp_path/"run",["M1","M2","M3","M4","M5","M6","M7","M8"],slots); w=ModularWorkflow(s); seen=[]
 e=s.execute("print(1)",broker=b,image="x@sha256:"+"a"*64,inputs=inputs);s.admit(e.content_hash,audit(s,e))
 def model(req):
  row=req.data();seen.append(row);slot=row["slot"]
  if slot=="m4":return FrozenRecord.from_dict({"question":"q","branches":branches(),"budget_units":2})
  if slot in {"r1","r2"}:return FrozenRecord.from_dict(review("accept"))
  if slot=="final":return FrozenRecord.from_dict({"objective_digest":s.objective.content_hash,"outcome":"positive","evidence_ids":[e.content_hash],"conclusion":"ok","programme_complete":False})
  return FrozenRecord.from_dict({"next":"uses sources"})
 assert w.propose("m4",model,instruction="propose").status=="executed"
 assert w.independent_review([("r1","mechanism","why?","a1"),("r2","measurement","bias?","a2")],model,evidence_snapshot=s.evidence.version).status=="executed"
 docs=tuple(SourceDocument(x,"root-"+x,l,FrozenRecord.from_dict({"text":x})) for x,l in (("s","support"),("c","counter"),("m","method")))
 p=Provider(docs);w.retrieve_then_invoke("m6",model,instruction="research",provider=p,query=FrozenRecord.from_dict({"q":"q"}),source_bundle=FrozenSourceBundle("bundle",docs),policy=FrozenRetrievalPolicy("p",("new_mechanism",),RetrievalBudget(1,1)),signals=RetrievalSignals(new_mechanism=True))
 assert p.calls==['support','counter','method']
 assert all(row['objective'] == s.objective.data() for row in seen)
 assert "submissions" not in seen[2]["module_context"] and "independent_review" in seen[3]["module_context"]
 plan=ExplorationPlan("x",s.task.identity,FrozenRecord.from_dict({"x":1}),ResourceClosure("v","a","n",1,1))
 assert w.explore(plan,{"data":FeasibilityObservation("data","passed","d")},ExplorationBudget(1,1),code="print(2)",broker=b,image="x@sha256:"+"a"*64,inputs=inputs).status=="executed"
 panel=w.run_panel(FifoScheduler(tmp_path/"panel.sqlite",max_concurrency=1,total_budget=2),experiment_id="panel",jobs=[{"task_id":"a","dependencies":[],"resources":[],"cost_units":1},{"task_id":"b","dependencies":[],"resources":[],"cost_units":1}],worker_id="w",execute=lambda lease:FrozenRecord.from_dict({"run":lease.run_id}))
 assert panel.status=="executed"
 candidate=s.invoke("final",model,instruction="final");assert s.finish(candidate).data()["decision"]=="proceed"

def test_disabled_and_unpermitted_paths_are_blocked(tmp_path):
 s,b,inputs=make(tmp_path/"off",["M1","M2","M3"],("final",));w=ModularWorkflow(s)
 assert w.propose("final",lambda _:FrozenRecord.from_dict({}),instruction="x").status=="blocked"
 assert w.m9_policy(None).status=="blocked"



def test_m7_no_permit_does_not_execute(tmp_path):
 s,b,inputs=make(tmp_path/"m7",["M1","M2","M3","M7"],("final",));w=ModularWorkflow(s)
 plan=ExplorationPlan("x",s.task.identity,FrozenRecord.from_dict({"x":1}),ResourceClosure("v","a","n",1,1))
 result=w.explore(plan,{},ExplorationBudget(1,1),code="print(1)",broker=b,image="x@sha256:"+"a"*64,inputs=inputs)
 assert result.status=="blocked" and s._attempts==0
