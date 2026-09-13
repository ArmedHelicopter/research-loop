"""Q1.5 production driver integration over paired public benchmark cells."""
from itertools import combinations
from pathlib import Path

import pytest

from research_loop.modular.benchmarks import BladeAdapter, DiscoveryBenchAdapter
from research_loop.modular.combinations import default_compatibility
from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.modular.experiments import ControllerInputs, registry, scenario
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
from research_loop.modular.panel_receipts import CombinationObligations, FrozenPanel, PanelCell, PanelReceiptVerifier
from research_loop.modular.panel_runner import run_train_cell
from research_loop.modular.runtime import AuditVerifier
from research_loop.ontology import ContractError


SPLIT, SCORER = "f" * 64, "a" * 64


def _task(benchmark):
    identity = DataIdentity(benchmark, "q15-" + benchmark, benchmark + ":q15", "synthetic-v1", SPLIT, "train")
    if benchmark == "discoverybench":
        return DiscoveryBenchAdapter().prepare(identity, {"task_id": identity.task_id, "question": "Public Q1.5 question", "source_kind": "synthetic", "dataset": [{"name": "public.csv", "columns": [{"name": "x"}]}]})
    return BladeAdapter().prepare(identity, {"task_id": identity.task_id, "dataset_id": "public", "research_question": "Public Q1.5 question", "data_schema": [{"name": "outcome", "dtype": "float"}], "task_instructions": "Use public data."})


def _panel():
    spec, design = registry()["Q1.5"], default_compatibility("base").conditional_factorial(("M5",))
    arms = {row["id"]: FrozenRecord.from_dict(row["arm"]) for row in design.data()["cells"] if row["status"] == "executable"}
    tasks = {name: _task(name) for name in ("discoverybench", "blade")}
    package = CandidatePackage.create(parent_digest=None, manifest=TrainingManifest.freeze([task.identity for task in tasks.values()]), changes={"prompt": {"instructions": "public q15 package"}}, search_cost=0)
    cells, scenarios = [], {}
    for name, task in tasks.items():
        review_material = FrozenRecord.from_dict({"schema": "q15-review-material-v1", "identity": task.identity.data(),
            "public_evidence": {"measurement_id": "public-measurement-" + name,
                "observation": "Raw public measurement changed after the intervention.", "value": 1.5},
            "historical_summary": ("Incorrect historical summary: no change was measured." if name == "discoverybench"
                                   else "Correct historical summary: the public measurement changed.")})
        for variant in spec.variants:
            material = scenario(spec, variant, inputs=ControllerInputs(FrozenRecord.from_dict(task.data()), review_material, FrozenRecord.from_dict({"budget": "fixed"})))
            for arm_id, arm in arms.items():
                cell = PanelCell("Q1.5", task.identity, "r1", variant, arm_id, arm, task.content_hash, material.content_hash, package.digest, SCORER)
                cells.append(cell); scenarios[(name, variant, arm_id)] = material
    modules = tuple(f"M{number}" for number in range(1, 10))
    obligations = CombinationObligations(tuple(combinations(modules, 2)), (("M2", "M3", "M5"), ("M4", "M5", "M6"), ("M1", "M4", "M7"), ("M3", "M6", "M9"), ("M7", "M8", "M9")), modules, modules)
    return FrozenPanel("train-q15", "train", SPLIT, package.digest, ("Q1.5",), {"Q1.5": design}, FrozenRecord.from_dict({"criterion": "engineering only"}), tuple(cells), obligations), scenarios, tasks, package


def _audit(): return AuditVerifier({"a": b"a" * 32, "b": b"b" * 32})


def _model(request):
    body = request.data()
    if body["slot"] == "final":
        return FrozenRecord.from_dict({"objective_digest": body["module_context"]["required_objective_digest"], "outcome": "unknown", "evidence_ids": [], "conclusion": "synthetic q15 candidate", "programme_complete": False})
    return FrozenRecord.from_dict({"assessment": "concern", "evidence_refs": ["public-q15-evidence"], "counterexamples": [], "uncertainty": "synthetic review"})


def _requests(run):
    return [FrozenRecord(line).data()["data"]["request"] for line in run.runtime.trace_path.read_text(encoding="utf-8").splitlines() if FrozenRecord(line).data()["stage"] == "model_request"]


def test_q15_complete_grid_binds_order_visibility_sealed_content_final_and_m5_control(tmp_path: Path):
    frozen, scenarios, tasks, package = _panel(); runs = []
    for number, cell in enumerate(frozen.cells):
        run = run_train_cell(cell, task=tasks[cell.identity.benchmark], scenario=scenarios[(cell.identity.benchmark, cell.variant, cell.arm_id)], package=package, objective=FrozenRecord.from_dict({"objective": "q15"}), sidecar=tmp_path / str(number), model=_model, audit_verifier=_audit())
        runs.append(run); requests = _requests(run)
        assert len(requests) == 3 == run.call_plan.data()["model_calls"]
        initial, followup, final = requests
        enabled = cell.runtime_arm.data()["enabled"] == ["M5"]
        if cell.variant == "blind_first":
            assert initial["module_context"]["historical_summary"] is None
            assert followup["module_context"]["historical_summary"] is not None
        else:
            assert initial["module_context"]["historical_summary"] is not None
            assert followup["module_context"]["historical_summary"] is None
        assert initial["module_context"]["public_evidence_digest"] == followup["module_context"]["public_evidence_digest"]
        expected_summary = "Incorrect historical summary: no change was measured." if cell.identity.benchmark == "discoverybench" else "Correct historical summary: the public measurement changed."
        visible_summary = followup if cell.variant == "blind_first" else initial
        assert visible_summary["module_context"]["historical_summary"] == expected_summary
        assert initial["context"]["mode"] == "evidence_only"
        if enabled:
            assert initial["module_context"]["sealed"] is True
            assert followup["module_context"]["sealed_submission"]["reviewer_id"] == "q15-evidence-reviewer"
            assert final["module_context"]["q15_review"]["initial_submission"]["response"]["assessment"] == "concern"
            assert final["module_context"]["q15_review"]["post_reveal_revision"]["response"]["assessment"] == "concern"
        else:
            assert initial["module_context"]["control"] == followup["module_context"]["control"] == "M5"
            assert followup["module_context"]["sealed_submission"] is None
            assert final["module_context"]["q15_review"]["initial_submission"] is None
    verdict = PanelReceiptVerifier().verify(frozen, tuple(run.runtime for run in runs))
    assert verdict.decision == "engineering_verified" and verdict.observed_cells == 8


def test_q15_failure_remains_in_denominator_and_validation_is_rejected(tmp_path: Path):
    frozen, scenarios, tasks, package = _panel(); rows = []
    for number, cell in enumerate(frozen.cells):
        callback = (lambda request: FrozenRecord.from_dict({"bad": "review"})) if number == 0 else _model
        rows.append(run_train_cell(cell, task=tasks[cell.identity.benchmark], scenario=scenarios[(cell.identity.benchmark, cell.variant, cell.arm_id)], package=package, objective=FrozenRecord.from_dict({"objective": "q15"}), sidecar=tmp_path / ("r" + str(number)), model=callback, audit_verifier=_audit()).runtime)
    assert PanelReceiptVerifier().verify(frozen, rows).failures == 1
    cell = frozen.cells[0]
    validation = PanelCell(cell.coverage_id, DataIdentity(cell.identity.benchmark, cell.identity.task_id, cell.identity.group_id, cell.identity.dataset_version, cell.identity.split_id, "validation"), cell.replicate, cell.variant, cell.arm_id, cell.runtime_arm, cell.task_digest, cell.scenario_digest, cell.package_digest, cell.scorer_digest)
    with pytest.raises(ContractError, match="training cells only"):
        run_train_cell(validation, task=tasks[cell.identity.benchmark], scenario=scenarios[(cell.identity.benchmark, cell.variant, cell.arm_id)], package=package, objective=FrozenRecord.from_dict({"objective": "q15"}), sidecar=tmp_path / "validation", model=_model, audit_verifier=_audit())
