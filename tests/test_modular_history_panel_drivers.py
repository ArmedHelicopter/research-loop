"""Synthetic public grid checks for the unregistered Q1.1/Q1.2 panel drivers."""
from __future__ import annotations

from itertools import combinations
from pathlib import Path

import pytest

from research_loop.modular import panel_runner
from research_loop.modular.benchmarks import BladeAdapter, DiscoveryBenchAdapter
from research_loop.modular.combinations import default_compatibility
from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.modular.experiments import ControllerInputs, registry, scenario
from research_loop.modular.history_panel_drivers import freeze_history_bundle, install_drivers
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
from research_loop.modular.panel_receipts import CombinationObligations, FrozenPanel, PanelCell, PanelReceiptVerifier
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
    factors = tuple(module for module in spec.modules if module != "P0")
    design = default_compatibility("base").conditional_factorial(factors)
    arms = {row["id"]: FrozenRecord.from_dict(row["arm"]) for row in design.data()["cells"] if row["status"] == "executable"}
    tasks = {name: _task(name) for name in ("discoverybench", "blade")}
    package = CandidatePackage.create(parent_digest=None, manifest=TrainingManifest.freeze([task.identity for task in tasks.values()]), changes={"prompt": {"instructions": "public history package"}}, search_cost=0)
    rows, scenarios = [], {}
    for name, task in tasks.items():
        for variant in spec.variants:
            controlled = scenario(spec, variant, inputs=ControllerInputs(FrozenRecord.from_dict(task.data()), FrozenRecord.from_dict({"public": "evidence"}), FrozenRecord.from_dict({"budget": "fixed"})))
            for arm_id, arm in arms.items():
                cell = PanelCell(coverage, task.identity, "r1", variant, arm_id, arm, task.content_hash, controlled.content_hash, package.digest, SCORER)
                rows.append(cell); scenarios[cell.key] = controlled
    modules = tuple(f"M{n}" for n in range(1, 10))
    obligations = CombinationObligations(tuple(combinations(modules, 2)), (("M2", "M3", "M5"), ("M4", "M5", "M6"), ("M1", "M4", "M7"), ("M3", "M6", "M9"), ("M7", "M8", "M9")), modules, modules)
    return FrozenPanel("history-" + coverage, "train", SPLIT, package.digest, (coverage,), {coverage: design}, FrozenRecord.from_dict({"criterion": "engineering only"}), tuple(rows), obligations), tasks, scenarios, package


def _model(seen):
    def call(request: FrozenRecord):
        row = request.data(); seen.append(row)
        if row["slot"] == "final":
            return FrozenRecord.from_dict({"objective_digest": row["module_context"]["required_objective_digest"], "outcome": "unknown", "evidence_ids": [], "conclusion": "synthetic history candidate", "programme_complete": False})
        return FrozenRecord.from_dict({"assessment": "concern", "evidence_refs": ["public"], "counterexamples": [], "uncertainty": "synthetic"})
    return call


def _bundle(task, _scenario):
    return freeze_history_bundle(task, public_evidence={"measurement_id": "public-" + task.identity.benchmark, "observation": "Public grouped measurement changed.", "value": 1.5},
        q11={"correct": {"historical_summary": "Earlier report says treatment exceeded control.", "withdrawal": False},
             "wrong": {"historical_summary": "Earlier report says treatment was below control.", "withdrawal": False},
             "neutral": {"historical_summary": "Earlier report has no interpretation.", "withdrawal": False}},
        q12={"summary_only": {"historical_summary": "Historical summary lacks a registered source dependency.", "withdrawal": False},
             "registered": {"historical_summary": "Historical upstream revision is registered.", "withdrawal": False},
             "withdraw": {"historical_summary": "Historical upstream source is withdrawn.", "withdrawal": True}})


@pytest.mark.parametrize("coverage", ["Q1.1", "Q1.2"])
def test_full_public_grid_records_real_m2_m3_material_and_final_payload(tmp_path: Path, monkeypatch, coverage: str):
    local = dict(panel_runner.DRIVERS); install_drivers(local, material_resolver=_bundle); monkeypatch.setattr(panel_runner, "DRIVERS", local)
    frozen, tasks, scenarios, package = _rows(coverage); runtimes = []; requests = []
    for number, cell in enumerate(frozen.cells):
        run = panel_runner.run_train_cell(cell, task=tasks[cell.identity.benchmark], scenario=scenarios[cell.key], package=package,
            objective=FrozenRecord.from_dict({"objective": coverage}), sidecar=tmp_path / str(number), model=_model(requests), audit_verifier=AUDIT)
        runtimes.append(run.runtime)
        assert run.runtime.status == "succeeded" and run.call_plan.data()["model_calls"] == 3
    assert PanelReceiptVerifier().verify(frozen, tuple(runtimes)).decision == "engineering_verified"
    assert all(row["task"]["identity"]["benchmark"] in {"blade", "discoverybench"} for row in requests)
    assert all(row["slot"] != "final" or row["module_context"]["reconstructed_context"]["entries"] is not None for row in requests)
    if coverage == "Q1.1":
        q11 = [row for row in requests if row["slot"] != "final"]
        assert all("truth" not in row["module_context"]["history_material"] and "label" not in row["module_context"]["history_material"] for row in q11)
        assert len({FrozenRecord.from_dict(row["module_context"]["history_material"]).content_hash for row in q11}) == 6
    else:
        after = [row for row in requests if row["slot"] == "downstream_after_withdrawal"]
        assert any(row["module_context"]["withdrawal_applied"] for row in after)
        assert any(row["module_context"]["m2"] == "frozen_control" and row["module_context"]["m3"] == "frozen_control" for row in after)
        withdrawn = next(row for row in after if row["module_context"]["withdrawal_applied"])
        assert withdrawn["module_context"]["reconstructed_context"]["entries"]["entries"] != []
    trace = (tmp_path / "0" / "trace.jsonl").read_text(encoding="utf-8")
    assert "operation_m3_" in trace
