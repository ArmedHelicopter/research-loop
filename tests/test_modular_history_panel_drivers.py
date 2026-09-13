"""Synthetic public grid checks for the unregistered Q1.1/Q1.2 panel drivers."""
from __future__ import annotations

from itertools import combinations
from pathlib import Path

import pytest

from research_loop.modular import panel_runner
from research_loop.modular.benchmarks import BladeAdapter, DiscoveryBenchAdapter
from research_loop.modular.combinations import default_compatibility
from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.modular.experiments import registry
from research_loop.modular.history_panel_drivers import freeze_history_bundle, install_drivers
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
from research_loop.modular.panel_plan import compile_train_panel, executable_arms, obligation_grids
from research_loop.modular.panel_receipts import PanelReceiptVerifier
from research_loop.modular.runtime import AuditVerifier


SPLIT, SCORER = "f" * 64, "a" * 64
AUDIT = AuditVerifier({"a": b"a" * 32, "b": b"b" * 32})


def _task(benchmark: str):
    identity = DataIdentity(benchmark, "history-" + benchmark, benchmark + ":history", "synthetic-v1", SPLIT, "train")
    if benchmark == "blade":
        return BladeAdapter().prepare(identity, {"task_id": identity.task_id, "dataset_id": "public", "research_question": "What does public evidence show?", "data_schema": [{"name": "x", "dtype": "float"}]})
    return DiscoveryBenchAdapter().prepare(identity, {"task_id": identity.task_id, "question": "What does public evidence show?", "source_kind": "synthetic", "dataset": [{"name": "public.csv", "columns": [{"name": "x"}]}]})


def _rows(coverage: str):
    spec = registry()[coverage]
    tasks = {name: _task(name) for name in ("discoverybench", "blade")}
    package = CandidatePackage.create(parent_digest=None, manifest=TrainingManifest.freeze([task.identity for task in tasks.values()]), changes={"prompt": {"instructions": "public history package"}}, search_cost=0)
    bundles = {task.content_hash: _bundle(task, None) for task in tasks.values()}
    control = FrozenRecord.from_dict({"source": "synthetic", "always_enabled": True})
    grids = obligation_grids((coverage,), baseline_digest="b" * 64, p0_control=control)
    packages = {arm.content_hash: package for grid in grids.values() for arm in executable_arms(grid).values()}
    compiled = compile_train_panel(stage="history-" + coverage, scope_ids=(coverage,), tasks=tuple(tasks.values()), evidence_by_task=bundles,
        budget=FrozenRecord.from_dict({"calls": 3}), baseline_digest="b" * 64, p0_control=control,
        packages_by_arm=packages, scorer=FrozenRecord.from_dict({"identity": "not-configured"}),
        acceptance_criteria=FrozenRecord.from_dict({"scope": "engineering-only"}), replicates=("r1",))
    return compiled, tasks, bundles


def _model(seen):
    def call(request: FrozenRecord):
        row = request.data(); seen.append(row)
        if row["slot"] == "final":
            return FrozenRecord.from_dict({"objective_digest": row["module_context"]["required_objective_digest"], "outcome": "unknown", "evidence_ids": [], "conclusion": "synthetic history candidate", "programme_complete": False})
        return FrozenRecord.from_dict({"assessment": "concern", "evidence_refs": ["public"], "counterexamples": [], "uncertainty": "synthetic"})
    return call


def _bundle(task, _scenario):
    return freeze_history_bundle(task, public_evidence={"measurement_id": "public-" + task.identity.benchmark, "observation": "Public grouped measurement changed.", "value": 1.5},
        q11={"correct": {"historical_summary": "Earlier report says treatment exceeded control.", "withdrawal": False, "dependency": False},
             "wrong": {"historical_summary": "Earlier report says treatment was below control.", "withdrawal": False, "dependency": False},
             "neutral": {"historical_summary": "Earlier report has no interpretation.", "withdrawal": False, "dependency": False}},
        q12={"summary_only": {"historical_summary": "Historical summary lacks a registered source dependency.", "withdrawal": False, "dependency": False},
             "registered": {"historical_summary": "Historical upstream revision is registered.", "withdrawal": False, "dependency": True},
             "withdraw": {"historical_summary": "Historical upstream source is withdrawn.", "withdrawal": True, "dependency": True}})


def _admit(_task, _material):
    return {"trusted_validator": "synthetic-independent-admission", "validator_verified": True, "admitted": True}


@pytest.mark.parametrize("coverage", ["Q1.1", "Q1.2"])
def test_full_public_grid_records_real_m2_m3_material_and_final_payload(tmp_path: Path, monkeypatch, coverage: str):
    compiled, tasks, bundles = _rows(coverage)
    local = dict(panel_runner.DRIVERS); install_drivers(local, material_resolver=lambda task, _scenario: bundles[task.content_hash], admission_port=_admit); monkeypatch.setattr(panel_runner, "DRIVERS", local)
    runtimes = []; requests = []
    for number, cell in enumerate(compiled.panel.cells):
        run = panel_runner.run_train_cell(cell, task=tasks[cell.identity.benchmark], scenario=compiled.scenarios[cell.key], package=compiled.packages[cell.runtime_arm.content_hash],
            objective=FrozenRecord.from_dict({"objective": coverage}), sidecar=tmp_path / str(number), model=_model(requests), audit_verifier=AUDIT)
        runtimes.append(run.runtime)
        assert run.runtime.status == "succeeded" and run.call_plan.data()["model_calls"] == 3
    assert PanelReceiptVerifier().verify(compiled.panel, tuple(runtimes)).decision == "engineering_verified"
    assert all(row["task"]["identity"]["benchmark"] in {"blade", "discoverybench"} for row in requests)
    assert all(row["slot"] != "final" or row["module_context"]["reconstructed_context"]["entries"] is not None for row in requests)
    if coverage == "Q1.1":
        q11 = [row for row in requests if row["slot"] != "final"]
        assert all("correct" not in FrozenRecord.from_dict(row).encoded and "wrong" not in FrozenRecord.from_dict(row).encoded and "neutral" not in FrozenRecord.from_dict(row).encoded for row in q11)
        assert len({FrozenRecord.from_dict(row["module_context"]["history_material"]).content_hash for row in q11}) == 6
    else:
        after = [row for row in requests if row["slot"] == "downstream_after_withdrawal"]
        assert any(row["module_context"]["withdrawal_applied"] for row in after)
        assert any(row["module_context"]["m2"] == "frozen_control" and row["module_context"]["m3"] == "frozen_control" for row in after)
        withdrawn = next(row for row in after if row["module_context"]["withdrawal_applied"])
        assert withdrawn["module_context"]["reconstructed_context"]["entries"]["entries"] != []
    trace = (tmp_path / "0" / "trace.jsonl").read_text(encoding="utf-8")
    assert "operation_m3_" in trace


def test_rejects_unbound_resolver_bundle_before_any_model_call(tmp_path: Path, monkeypatch):
    compiled, tasks, bundles = _rows("Q1.2")
    foreign = next(iter(bundles.values()))
    local = dict(panel_runner.DRIVERS); install_drivers(local, material_resolver=lambda _task, _scenario: foreign, admission_port=_admit); monkeypatch.setattr(panel_runner, "DRIVERS", local)
    cell = next(item for item in compiled.panel.cells if item.identity.benchmark == "blade")
    called = []
    result = panel_runner.run_train_cell(cell, task=tasks["blade"], scenario=compiled.scenarios[cell.key], package=compiled.packages[cell.runtime_arm.content_hash],
        objective=FrozenRecord.from_dict({"objective": "guard"}), sidecar=tmp_path / "guard", model=lambda request: called.append(request), audit_verifier=AUDIT)
    assert result.runtime.status == "failed"
    assert called == []
