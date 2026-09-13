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
from research_loop.ontology import canonical, ContractError

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
    q14 = {"one_withdrawn": {"sources":{"a":a,"a_copy":a,"b":b}, "withdraw_actions":[{"source_key":"a","reason":"caller withdrawal a"}], "claim_statement":"Caller supplied paired support claim."},
           "all_withdrawn": {"sources":{"a":a,"a_copy":a,"b":b,"b_copy":b}, "withdraw_actions":[{"source_key":"a","reason":"caller withdrawal a"},{"source_key":"b","reason":"caller withdrawal b"}], "claim_statement":"Caller supplied all support claim."},
           "copies": {"sources":{"primary":copy,"copy":copy}, "withdraw_actions":[], "claim_statement":"Caller supplied copied support claim."}}
    return freeze_support_bundle(task, q13=q13, q14=q14)

def _admit(_task, record): return {"record_digest":record.content_hash,"trusted_validator":"synthetic-controlled-port","validator_verified":True,"admitted":True}
def _model(rows):
    def call(request):
        row=request.data(); rows.append(row)
        if row["slot"] == "final": return FrozenRecord.from_dict({"objective_digest":row["module_context"]["required_objective_digest"],"outcome":"unknown","evidence_ids":[],"conclusion":"synthetic","programme_complete":False})
        return FrozenRecord.from_dict({"assessment":"synthetic","evidence_refs":[],"counterexamples":[],"uncertainty":"unknown"})
    return call

def _q13_cell():
    tasks={key:_task(key) for key in ("blade","discoverybench")}; bundles={task.content_hash:_bundle(task) for task in tasks.values()}
    package=CandidatePackage.create(parent_digest=None, manifest=TrainingManifest.freeze([task.identity for task in tasks.values()]), changes={"prompt":{"instructions":"support"}}, search_cost=0)
    control=FrozenRecord.from_dict({"source":"synthetic","always_enabled":True})
    grids=obligation_grids(("Q1.3",),baseline_digest="b"*64,p0_control=control)
    packages={arm.content_hash:package for grid in grids.values() for arm in executable_arms(grid).values()}
    compiled=compile_train_panel(stage="support",scope_ids=("Q1.3",),tasks=tuple(tasks.values()),evidence_by_task=bundles,budget=FrozenRecord.from_dict({"calls":3}),baseline_digest="b"*64,p0_control=control,packages_by_arm=packages,scorer=FrozenRecord.from_dict({"identity":"none"}),acceptance_criteria=FrozenRecord.from_dict({"scope":"engineering"}),replicates=("r1",))
    cell=next(item for item in compiled.panel.cells if item.identity.benchmark=="blade" and "M2" in item.runtime_arm.data()["enabled"])
    return tasks["blade"], bundles[tasks["blade"].content_hash], compiled, cell, package

@pytest.mark.parametrize("coverage", ["Q1.3","Q1.4"])
def test_shared_bundle_full_grid_exercises_actual_support_state(tmp_path: Path, monkeypatch, coverage):
    tasks={key:_task(key) for key in ("blade","discoverybench")}; bundles={task.content_hash:_bundle(task) for task in tasks.values()}
    package=CandidatePackage.create(parent_digest=None, manifest=TrainingManifest.freeze([task.identity for task in tasks.values()]), changes={"prompt":{"instructions":"support"}}, search_cost=0)
    control=FrozenRecord.from_dict({"source":"synthetic","always_enabled":True}); grids=obligation_grids((coverage,),baseline_digest="b"*64,p0_control=control); packages={arm.content_hash:package for grid in grids.values() for arm in executable_arms(grid).values()}
    compiled=compile_train_panel(stage="support",scope_ids=(coverage,),tasks=tuple(tasks.values()),evidence_by_task=bundles,budget=FrozenRecord.from_dict({"calls":3}),baseline_digest="b"*64,p0_control=control,packages_by_arm=packages,scorer=FrozenRecord.from_dict({"identity":"none"}),acceptance_criteria=FrozenRecord.from_dict({"scope":"engineering"}),replicates=("r1",))
    rows=[]; runtime=[]
    for n,cell in enumerate(compiled.panel.cells):
        result=panel_runner.run_train_cell(cell,task=tasks[cell.identity.benchmark],scenario=compiled.scenarios[cell.key],package=compiled.packages[cell.runtime_arm.content_hash],objective=FrozenRecord.from_dict({"q":coverage}),sidecar=tmp_path/str(n),model=_model(rows),audit_verifier=AUDIT,history_admission_port=_admit)
        assert result.runtime.status=="succeeded" and result.call_plan.data()["model_calls"]==3; runtime.append(result.runtime)
    assert PanelReceiptVerifier().verify(compiled.panel,tuple(runtime)).decision=="engineering_verified"
    assert all(set(row["module_context"]["panel_cell"])=={"schema","cell_digest"} for row in rows)
    if coverage=="Q1.3":
        initial=[row for row in rows if row["slot"]=="representation_initial"]
        later=[row for row in rows if row["slot"]=="representation_next"]
        assert all("Q13-SAME-SOURCE" in canonical(row["module_context"]["public_support_state"]) and len(row["module_context"]["public_support_state"]["records"])==1 for row in initial)
        assert all({record["representation"] for record in row["module_context"]["public_support_state"]["records"]}=={"raw"} for row in initial)
        assert all(len(row["module_context"]["public_support_state"]["records"])==2 for row in later)
        on=[row for row in initial if row["module_context"]["ledger_mode"]=="deduplicated"]
        assert all(row["module_context"]["context_material"]["mode"]=="candidate" for row in on)
        assert all(len([entry for entry in row["module_context"]["context_material"]["entries"]["entries"] if entry["kind"]=="evidence"])==1 for row in on)
        paired={}
        for row in later:
            key=(row["task"]["identity"]["task_id"], row["module_context"]["public_support_state"]["records"][1]["representation"])
            paired.setdefault(key,{})[row["module_context"]["ledger_mode"]]=row["module_context"]["public_support_state"]["records"]
        assert all(pair["deduplicated"]==pair["frozen_non_deduplicated_control"] for pair in paired.values())
    else:
        initial=[row for row in rows if row["slot"]=="support_initial"]; after=[row for row in rows if row["slot"]=="support_rechecked"]
        assert all("withdraw_actions" not in row["module_context"]["public_support_state"] for row in initial)
        one_rows=[row for row in after if len(row["module_context"]["public_support_state"]["sources"])==1 and row["module_context"]["public_support_state"]["withdraw_actions"]]
        assert {row["module_context"]["m2"] for row in one_rows}=={"enabled","frozen_control"}
        assert all(set(row["module_context"]["public_support_state"]["sources"])=={"b"} for row in one_rows)
        one=next(row for row in one_rows if row["module_context"]["m2"]=="enabled")
        assert set(one["module_context"]["public_support_state"]["sources"])=={"b"}
        assert "Q14-A" not in canonical(one["module_context"]["public_support_state"])
        assert any(entry["kind"]=="claim" and entry["support_roots"] for entry in next(row for row in initial if row["module_context"]["panel_cell"]==one["module_context"]["panel_cell"])["module_context"]["context_material"]["entries"]["entries"])
        one_entries=one["module_context"]["reconstructed_context"]["entries"]["entries"]
        assert any(entry["kind"]=="evidence" and "Q14-B" in canonical(entry) for entry in one_entries)
        assert any(entry["kind"]=="claim" and entry["needs_review"] and len(entry["support_roots"])==1 for entry in one_entries)
        copied=next(row for row in initial if row["module_context"]["m2"]=="enabled" and len(row["module_context"]["public_support_state"]["sources"])==2 and "Q14-COPY" in canonical(row["module_context"]["public_support_state"]))
        assert len([entry for entry in copied["module_context"]["context_material"]["entries"]["entries"] if entry["kind"]=="evidence"])==1
        all_withdrawn=next(row for row in after if row["module_context"]["m2"]=="enabled" and not row["module_context"]["public_support_state"]["sources"])
        assert {action["source_key"] for action in all_withdrawn["module_context"]["public_support_state"]["withdraw_actions"]}=={"a","b"}
        assert any(entry["kind"]=="claim" and entry["needs_review"] and not entry["support_roots"] for entry in all_withdrawn["module_context"]["reconstructed_context"]["entries"]["entries"])
        paired={}
        for row in after:
            paired.setdefault(canonical(row["module_context"]["public_support_state"]),set()).add(row["module_context"]["m2"])
        assert all(modes=={"enabled","frozen_control"} for modes in paired.values())

def test_rejects_unbound_receipts_before_model_calls(tmp_path: Path, monkeypatch):
    task, bundle, compiled, cell, package=_q13_cell()
    invalid=[
        lambda _task, record: {"record_digest":"0"*64,"trusted_validator":"synthetic","validator_verified":True,"admitted":True},
        lambda _task, record: {"record_digest":record.content_hash,"trusted_validator":"synthetic","validator_verified":False,"admitted":True},
        lambda _task, record: {"record_digest":record.content_hash,"trusted_validator":"synthetic","validator_verified":True,"admitted":True,"extra":"forbidden"},
    ]
    for index, port in enumerate(invalid):
        local=dict(panel_runner.DRIVERS); install_drivers(local,material_resolver=lambda _task,_:bundle,admission_port=port); monkeypatch.setattr(panel_runner,"DRIVERS",local)
        calls=[]
        result=panel_runner.run_train_cell(cell,task=task,scenario=compiled.scenarios[cell.key],package=package,objective=FrozenRecord.from_dict({"q":"Q1.3"}),sidecar=tmp_path/str(index),model=_model(calls),audit_verifier=AUDIT)
        assert result.runtime.status=="failed" and result.call_plan.data()["model_calls"]==0 and calls==[]

def test_rejects_invalid_q14_topology():
    task=_task("blade"); bundle=_bundle(task); body=bundle.data()
    bad=dict(body["q14"]); bad["all_withdrawn"]=dict(bad["all_withdrawn"], withdraw_actions=[])
    with pytest.raises(ContractError): freeze_support_bundle(task,q13=body["q13"],q14=bad)
    bad=dict(body["q14"]); bad["copies"]=dict(bad["copies"], sources={"a":bad["copies"]["sources"]["primary"],"b":_source({"source_id":"different"},{"observation":"different"})})
    with pytest.raises(ContractError): freeze_support_bundle(task,q13=body["q13"],q14=bad)
