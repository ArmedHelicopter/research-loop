"""Synthetic full-grid checks for Q1.3/Q1.4 caller-owned support materials."""
from __future__ import annotations
from pathlib import Path
import pytest
from research_loop.modular import panel_runner
from research_loop.modular.benchmarks import BladeAdapter, DiscoveryBenchAdapter
from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
from research_loop.modular.panel_plan import compile_train_panel, executable_arms, obligation_grids
from research_loop.modular.panel_receipts import PanelReceiptVerifier
from research_loop.modular.runtime import AuditVerifier
from research_loop.modular.support_panel_drivers import freeze_support_bundle, install_drivers
from research_loop.ontology import canonical

SPLIT = "f" * 64; AUDIT = AuditVerifier({"a": b"a" * 32, "b": b"b" * 32})

def _task(name):
    identity = DataIdentity(name, "support-" + name, name + ":support", "synthetic-v1", SPLIT, "train")
    if name == "blade": return BladeAdapter().prepare(identity, {"task_id": identity.task_id, "dataset_id": "public", "research_question": "Public support?", "data_schema": [{"name": "x", "dtype": "float"}]})
    return DiscoveryBenchAdapter().prepare(identity, {"task_id": identity.task_id, "question": "Public support?", "source_kind": "synthetic", "dataset": [{"name":"p", "columns":[{"name":"x"}]}]})

def _source(root, evidence): return {"root_material": root, "public_evidence": evidence}
def _bundle(task):
    common = _source({"source_id": "shared-" + task.identity.benchmark}, {"observation": "Q13-SAME-SOURCE", "value": 1})
    a = _source({"source_id": "a-" + task.identity.benchmark}, {"observation": "Q14-A", "value": 1})
    b = _source({"source_id": "b-" + task.identity.benchmark}, {"observation": "Q14-B", "value": 2})
    copy = _source({"source_id": "copy-shared-" + task.identity.benchmark}, {"observation": "Q14-COPY", "value": 3})
    q13 = {v: {"source": common, "representation": r, "claim_statement": "Caller supplied representation claim."} for v,r in {"log":"raw","report":"report","summary":"summary","memory":"summary"}.items()}
    q14 = {"one_withdrawn": {"sources":{"a":a,"b":b}, "withdraw_actions":[{"source_key":"a","reason":"caller withdrawal a"}], "claim_statement":"Caller supplied paired support claim."},
           "all_withdrawn": {"sources":{"a":a,"b":b}, "withdraw_actions":[{"source_key":"a","reason":"caller withdrawal a"},{"source_key":"b","reason":"caller withdrawal b"}], "claim_statement":"Caller supplied all support claim."},
           "copies": {"sources":{"primary":copy,"copy":copy}, "withdraw_actions":[], "claim_statement":"Caller supplied copied support claim."}}
    return freeze_support_bundle(task, q13=q13, q14=q14)

def _admit(_task, record): return {"record_digest":record.content_hash,"trusted_validator":"synthetic-controlled-port","validator_verified":True,"admitted":True}
def _model(rows):
    def call(request):
        row=request.data(); rows.append(row)
        if row["slot"] == "final": return FrozenRecord.from_dict({"objective_digest":row["module_context"]["required_objective_digest"],"outcome":"unknown","evidence_ids":[],"conclusion":"synthetic","programme_complete":False})
        return FrozenRecord.from_dict({"assessment":"synthetic","evidence_refs":[],"counterexamples":[],"uncertainty":"unknown"})
    return call

@pytest.mark.parametrize("coverage", ["Q1.3","Q1.4"])
def test_shared_bundle_full_grid_exercises_actual_support_state(tmp_path: Path, monkeypatch, coverage):
    tasks={key:_task(key) for key in ("blade","discoverybench")}; bundles={task.content_hash:_bundle(task) for task in tasks.values()}
    package=CandidatePackage.create(parent_digest=None, manifest=TrainingManifest.freeze([task.identity for task in tasks.values()]), changes={"prompt":{"instructions":"support"}}, search_cost=0)
    control=FrozenRecord.from_dict({"source":"synthetic","always_enabled":True}); grids=obligation_grids((coverage,),baseline_digest="b"*64,p0_control=control); packages={arm.content_hash:package for grid in grids.values() for arm in executable_arms(grid).values()}
    compiled=compile_train_panel(stage="support",scope_ids=(coverage,),tasks=tuple(tasks.values()),evidence_by_task=bundles,budget=FrozenRecord.from_dict({"calls":3}),baseline_digest="b"*64,p0_control=control,packages_by_arm=packages,scorer=FrozenRecord.from_dict({"identity":"none"}),acceptance_criteria=FrozenRecord.from_dict({"scope":"engineering"}),replicates=("r1",))
    local=dict(panel_runner.DRIVERS); install_drivers(local, material_resolver=lambda task,_:bundles[task.content_hash],admission_port=_admit); monkeypatch.setattr(panel_runner,"DRIVERS",local)
    rows=[]; runtime=[]
    for n,cell in enumerate(compiled.panel.cells):
        result=panel_runner.run_train_cell(cell,task=tasks[cell.identity.benchmark],scenario=compiled.scenarios[cell.key],package=compiled.packages[cell.runtime_arm.content_hash],objective=FrozenRecord.from_dict({"q":coverage}),sidecar=tmp_path/str(n),model=_model(rows),audit_verifier=AUDIT)
        assert result.runtime.status=="succeeded" and result.call_plan.data()["model_calls"]==3; runtime.append(result.runtime)
    assert PanelReceiptVerifier().verify(compiled.panel,tuple(runtime)).decision=="engineering_verified"
    assert all(set(row["module_context"]["panel_cell"])=={"schema","cell_digest"} for row in rows)
    if coverage=="Q1.3":
        initial=[row for row in rows if row["slot"]=="representation_initial"]
        assert all("Q13-SAME-SOURCE" in canonical(row["module_context"]["public_support_state"]) for row in initial)
        on=[row for row in initial if row["module_context"]["ledger_mode"]=="deduplicated"]
        assert all(len(row["module_context"]["public_support_state"]["root_ids"])==2 and len(set(row["module_context"]["public_support_state"]["root_ids"]))==1 for row in on)
        assert all(row["module_context"]["context_material"]["mode"]=="candidate" for row in on)
    else:
        initial=[row for row in rows if row["slot"]=="support_initial"]; after=[row for row in rows if row["slot"]=="support_rechecked"]
        assert all("withdraw_actions" not in row["module_context"]["public_support_state"] for row in initial)
        one=next(row for row in after if row["module_context"]["m2"]=="enabled" and len(row["module_context"]["public_support_state"]["sources"])==1 and row["module_context"]["public_support_state"]["withdraw_actions"])
        assert any(entry["kind"]=="claim" and entry["support_roots"] for entry in next(row for row in initial if row["module_context"]["panel_cell"]==one["module_context"]["panel_cell"])["module_context"]["context_material"]["entries"]["entries"])
        assert any(entry["kind"]=="claim" and entry["needs_review"] for entry in one["module_context"]["reconstructed_context"]["entries"]["entries"])
