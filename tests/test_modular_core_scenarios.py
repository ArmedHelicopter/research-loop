from research_loop.modular.benchmarks import BladeAdapter, DiscoveryBenchAdapter
from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.modular.experiments import registry
from research_loop.modular.scenarios_core import run_core_scenario

def task(kind):
 i=DataIdentity("blade" if kind=="blade" else "discoverybench",kind+"-core","g","v","s","train")
 return BladeAdapter().prepare(i,{"task_id":i.task_id,"dataset_id":"x","research_question":"public?","data_schema":[]}) if kind=="blade" else DiscoveryBenchAdapter().prepare(i,{"task_id":i.task_id,"question":"public?","difficulty":"x","source_kind":"synthetic","dataset":[{"name":"x","description":"x","columns":[]}]})
def controls(t): return FrozenRecord.from_dict({"task_digest":t.content_hash,"budget_digest":"frozen","fixture_only":True})
def cb(p): return {"assessment":"unknown","evidence_refs":["fixture-public-evidence"],"counterexamples":[],"uncertainty":"fixture"}
def test_registry_q11_and_q21_variants_execute_both_public_adapters():
 for adapter in ("blade","discovery"):
  for experiment in ("Q1.1","Q2.1"):
   for variant in registry()[experiment].variants:
    r=run_core_scenario(experiment,variant,task=task(adapter),frozen_controls=controls(task(adapter)),callback=cb)
    assert len(r.payloads)==len(r.responses)==(3 if experiment=="Q1.1" else 4)
def test_q11_same_evidence_and_q21_all_four_actual_gates():
 t=task("blade"); h=run_core_scenario("Q1.1","wrong",task=t,frozen_controls=controls(t),callback=cb); q=run_core_scenario("Q2.1","positive",task=t,frozen_controls=controls(t),callback=cb)
 assert {p.data()["new_public_evidence"]["id"] for p in h.payloads}=={"fixture-public-evidence"}
 assert len(q.record.data()["m1_gates"])==4 and q.record.data()["m1_gates"][2]["admitted"] is False
