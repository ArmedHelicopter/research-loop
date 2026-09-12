from research_loop.modular.benchmarks import BladeAdapter, DiscoveryBenchAdapter
from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.modular.experiments import registry
from research_loop.modular.scenarios_core import run_core_scenario

def task(kind):
 i=DataIdentity("blade" if kind=="blade" else "discoverybench",kind+"-core","g","v","s","train")
 return BladeAdapter().prepare(i,{"task_id":i.task_id,"dataset_id":"x","research_question":"public?","data_schema":[]}) if kind=="blade" else DiscoveryBenchAdapter().prepare(i,{"task_id":i.task_id,"question":"public?","difficulty":"x","source_kind":"synthetic","dataset":[{"name":"x","description":"x","columns":[]}]})
def controls(t): return FrozenRecord.from_dict({"task_digest":t.content_hash,"budget_digest":"frozen","fixture_only":True})
def cb(p):
 review={"assessment":"unknown","evidence_refs":["fixture-public-evidence" if p.data()["schema"]=="q11-history-input-v1" else p.data()["case_material"]["evidence_id"]],"counterexamples":[],"uncertainty":"fixture"}
 return review if p.data()["schema"]=="q11-history-input-v1" else {"review":review,"candidate":{"validity":"invalid","support":"undetermined","outcome":"negative"}}
def test_registry_q11_and_q21_variants_execute_both_public_adapters():
 for adapter in ("blade","discovery"):
  for experiment in ("Q1.1","Q2.1"):
   for variant in registry()[experiment].variants:
    r=run_core_scenario(experiment,variant,task=task(adapter),frozen_controls=controls(task(adapter)),callback=cb)
    assert len(r.payloads)==len(r.responses)==(3 if experiment=="Q1.1" else 4)
def test_q11_same_evidence_and_q21_all_four_actual_gates():
 t=task("blade"); h=run_core_scenario("Q1.1","wrong",task=t,frozen_controls=controls(t),callback=cb); q=run_core_scenario("Q2.1","positive",task=t,frozen_controls=controls(t),callback=cb)
 assert {p.data()["new_public_evidence"]["id"] for p in h.payloads}=={"fixture-new-public-table"}
 assert len(q.record.data()["m1_gates"])==4 and q.record.data()["m1_gates"][2]["admitted"] is False

def test_q21_callback_candidate_changes_gate_and_always_positive_is_not_oracle_correct():
 t=task("blade")
 def always(p):
  e=p.data()["case_material"]["evidence_id"]
  return {"review":{"assessment":"accept","evidence_refs":[e],"counterexamples":[],"uncertainty":"x"},"candidate":{"validity":"valid","support":"supported","outcome":"positive"}}
 r=run_core_scenario("Q2.1","neutral",task=t,frozen_controls=controls(t),callback=always).record.data()
 assert r["m1_gates"][0]["admitted"] is True
 assert r["m1_gates"][1]["fixture_oracle_match"] is False and r["m1_gates"][2]["fixture_oracle_match"] is False
 assert r["m1_gates"][1]["false_admission_observed"] is True


def test_q11_manipulates_actual_history_material_and_rebuilds_from_identical_roots():
 t=task("blade")
 runs={v:run_core_scenario("Q1.1",v,task=t,frozen_controls=controls(t),callback=cb) for v in registry()["Q1.1"].variants}
 for strategy_index in (0,1):
  # Exclude strategy/variant identifiers: actual history content must differ.
  contexts=[FrozenRecord.from_dict(r.payloads[strategy_index].data()["history_context"]).content_hash for r in runs.values()]
  assert len(set(contexts))==3
 for r in runs.values():
  bodies=[p.data() for p in r.payloads]
  assert bodies[0]["history_context"] != bodies[1]["history_context"]
  assert bodies[2]["history_context"]["mode"] == "candidate"
  entries=bodies[2]["history_context"]["entries"]["entries"]
  assert any(e["kind"] == "evidence" and e["payload"]["content"].get("treated_mean")==10.2 for e in entries)
  assert all(b["new_public_evidence"] == bodies[0]["new_public_evidence"] for b in bodies)
 assert len({FrozenRecord.from_dict(r.payloads[2].data()["history_context"]).content_hash for r in runs.values()})==1


def test_q21_unknown_and_invalid_are_not_conflated_by_fixture_oracle():
 t=task("blade")
 r=run_core_scenario("Q2.1","neutral",task=t,frozen_controls=controls(t),callback=cb)
 gates=r.record.data()["m1_gates"]
 assert gates[2]["fixture_oracle_match"] is True
 assert gates[3]["fixture_oracle_match"] is False
