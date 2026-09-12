"""Production Q4.3 panel runner integration with synthetic model transport."""
from itertools import combinations
from pathlib import Path

import pytest

from research_loop.modular.benchmarks import BladeAdapter, DiscoveryBenchAdapter
from research_loop.modular.combinations import default_compatibility
from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask
from research_loop.modular.experiments import ControllerInputs, registry, scenario
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
from research_loop.modular.panel_receipts import CombinationObligations, FrozenPanel, PanelCell, PanelReceiptVerifier
from research_loop.modular.panel_runner import run_train_cell
from research_loop.modular.runtime import AuditVerifier
from research_loop.ontology import ContractError


SCORER, SPLIT = "d" * 64, "e" * 64


def _obligations() -> CombinationObligations:
    modules = tuple(f"M{number}" for number in range(1, 10))
    return CombinationObligations(tuple(combinations(modules, 2)),
        (("M2", "M3", "M5"), ("M4", "M5", "M6"), ("M1", "M4", "M7"), ("M3", "M6", "M9"), ("M7", "M8", "M9")), modules, modules)


def _task(benchmark: str) -> PublicTask:
    identity = DataIdentity(benchmark, f"q43-{benchmark}", f"{benchmark}:q43", "synthetic-v1", SPLIT, "train")
    if benchmark == "discoverybench":
        return DiscoveryBenchAdapter().prepare(identity, {"task_id": identity.task_id, "question": "Which public mechanism is plausible?", "source_kind": "synthetic", "dataset": [{"name": "public.csv", "columns": [{"name": "x"}]}]})
    return BladeAdapter().prepare(identity, {"task_id": identity.task_id, "dataset_id": "public", "research_question": "Estimate a public association.", "data_schema": [{"name": "outcome", "dtype": "float"}], "task_instructions": "Use only supplied public data."})


def _panel():
    spec = registry()["Q4.3"]
    design = default_compatibility("base").conditional_factorial(("M5",))
    arms = {row["id"]: FrozenRecord.from_dict(row["arm"]) for row in design.data()["cells"] if row["status"] == "executable"}
    tasks = {benchmark: _task(benchmark) for benchmark in ("discoverybench", "blade")}
    manifest = TrainingManifest(FrozenRecord.from_dict({"domain": "train", "identities": [task.identity.data() for task in tasks.values()]}))
    package = CandidatePackage.create(parent_digest=None, manifest=manifest, changes={"prompt": {"instructions": "synthetic q43 package"}}, search_cost=0)
    cells, scenarios = [], {}
    for benchmark, task in tasks.items():
        for variant in spec.variants:
            material = scenario(spec, variant, inputs=ControllerInputs(FrozenRecord.from_dict(task.data()), FrozenRecord.from_dict({"evidence": "public"}), FrozenRecord.from_dict({"budget": "fixed"})))
            for arm_id, arm in arms.items():
                cell = PanelCell("Q4.3", task.identity, "r1", variant, arm_id, arm, task.content_hash, material.content_hash, package.digest, SCORER)
                cells.append(cell); scenarios[(benchmark, variant, arm_id)] = material
    return FrozenPanel("train-q43", "train", SPLIT, package.digest, ("Q4.3",), {"Q4.3": design}, FrozenRecord.from_dict({"criterion": "synthetic runner wiring only"}), tuple(cells), _obligations()), scenarios, tasks, package


def _audit() -> AuditVerifier:
    return AuditVerifier({"audit-a": b"a" * 32, "audit-b": b"b" * 32})


def _model(request: FrozenRecord) -> FrozenRecord:
    body = request.data()
    if body["slot"] != "final":
        role = body["module_context"]["review_role"]
        return FrozenRecord.from_dict({"assessment": "concern", "evidence_refs": [f"public-{role}"], "counterexamples": [], "uncertainty": "synthetic transport response"})
    return FrozenRecord.from_dict({"objective_digest": body["module_context"]["required_objective_digest"], "outcome": "unknown", "evidence_ids": [], "conclusion": "synthetic q43 candidate", "programme_complete": False})


def _requests(run):
    return [event["data"]["request"] for event in [FrozenRecord(line).data() for line in run.runtime.trace_path.read_text(encoding="utf-8").splitlines()] if event["stage"] == "model_request"]


def test_q43_complete_two_benchmark_grid_uses_real_journaled_m5_visibility_and_matched_controls(tmp_path: Path) -> None:
    frozen, scenarios, tasks, package = _panel()
    runs = []
    for index, cell in enumerate(frozen.cells):
        run = run_train_cell(cell, task=tasks[cell.identity.benchmark], scenario=scenarios[(cell.identity.benchmark, cell.variant, cell.arm_id)], package=package, objective=FrozenRecord.from_dict({"objective": "q43 train"}), sidecar=tmp_path / "runs" / str(index), model=_model, audit_verifier=_audit())
        runs.append(run)
        requests = _requests(run)
        assert len(requests) == 5 == run.call_plan.data()["model_calls"]
        assert requests[-1]["module_context"]["required_objective_digest"] == FrozenRecord.from_dict(requests[-1]["objective"]).content_hash
        assert all(request["module_context"]["panel_cell"]["scenario_digest"] == cell.scenario_digest for request in requests)
        enabled = cell.runtime_arm.data()["enabled"] == ["M5"]
        initial = requests[:2]
        if enabled and cell.variant == "sealed_then_exchange":
            assert [request["module_context"]["prior_visible_submission"] for request in initial] == [None, None]
            assert all(request["module_context"]["sealed"] is True for request in initial)
        elif enabled:
            assert initial[0]["module_context"]["prior_visible_submission"] is None
            assert initial[1]["module_context"]["prior_visible_submission"]["evidence_refs"] == ["public-mechanism"]
        else:
            assert all(request["module_context"]["control"] == "M5" and request["module_context"]["prior_visible_submission"] is None for request in initial)
            assert all(not request["module_context"]["revealed_submissions"] for request in requests[2:4])
        if enabled:
            assert all(len(request["module_context"]["revealed_submissions"]) == 2 for request in requests[2:4])
            final_review = requests[-1]["module_context"]["q43_review"]
            assert [item["reviewer_id"] for item in final_review["initial_submissions"]] == ["q43-mechanism-reviewer", "q43-measurement-reviewer"]
            assert [item["reviewer_id"] for item in final_review["post_reveal_revisions"]] == ["q43-mechanism-reviewer", "q43-measurement-reviewer"]
            assert final_review["initial_submissions"][0]["response"]["evidence_refs"] == ["public-mechanism"]
        else:
            assert requests[-1]["module_context"]["q43_review"]["initial_submissions"] == []
    verdict = PanelReceiptVerifier().verify(frozen, tuple(run.runtime for run in runs))
    assert verdict.decision == "engineering_verified" and verdict.observed_cells == 8 and verdict.failures == 0


def test_q43_failure_stays_in_complete_denominator_and_validation_is_refused(tmp_path: Path) -> None:
    frozen, scenarios, tasks, package = _panel()
    rows = []
    failed = False
    for index, cell in enumerate(frozen.cells):
        if not failed and cell.runtime_arm.data()["enabled"] == ["M5"]:
            def callback(request: FrozenRecord) -> FrozenRecord:
                return _model(request) if request.data()["slot"] == "final" else FrozenRecord.from_dict({"invalid": "review"})
            failed = True
        else:
            callback = _model
        rows.append(run_train_cell(cell, task=tasks[cell.identity.benchmark], scenario=scenarios[(cell.identity.benchmark, cell.variant, cell.arm_id)], package=package, objective=FrozenRecord.from_dict({"objective": "q43 train"}), sidecar=tmp_path / str(index), model=callback, audit_verifier=_audit()).runtime)
    verdict = PanelReceiptVerifier().verify(frozen, rows)
    assert verdict.engineering_verified and verdict.failures == 1 and verdict.observed_cells == len(frozen.cells)
    cell = frozen.cells[0]
    validation_identity = DataIdentity(cell.identity.benchmark, cell.identity.task_id, cell.identity.group_id, cell.identity.dataset_version, cell.identity.split_id, "validation")
    validation = PanelCell(cell.coverage_id, validation_identity, cell.replicate, cell.variant, cell.arm_id, cell.runtime_arm, cell.task_digest, cell.scenario_digest, cell.package_digest, cell.scorer_digest)
    with pytest.raises(ContractError, match="training cells only"):
        run_train_cell(validation, task=tasks[cell.identity.benchmark], scenario=scenarios[(cell.identity.benchmark, cell.variant, cell.arm_id)], package=package, objective=FrozenRecord.from_dict({"objective": "q43 train"}), sidecar=tmp_path / "validation", model=_model, audit_verifier=_audit())


def test_q43_rejects_a_final_that_does_not_copy_the_frozen_objective_digest(tmp_path: Path) -> None:
    frozen, scenarios, tasks, package = _panel()
    cell = frozen.cells[0]
    def wrong_final(request: FrozenRecord) -> FrozenRecord:
        if request.data()["slot"] != "final":
            return _model(request)
        return FrozenRecord.from_dict({"objective_digest": "not-the-frozen-digest", "outcome": "unknown", "evidence_ids": [], "conclusion": "wrong objective binding", "programme_complete": False})
    result = run_train_cell(cell, task=tasks[cell.identity.benchmark], scenario=scenarios[(cell.identity.benchmark, cell.variant, cell.arm_id)], package=package, objective=FrozenRecord.from_dict({"objective": "q43 train"}), sidecar=tmp_path / "wrong-final", model=wrong_final, audit_verifier=_audit())
    assert result.runtime.status == "failed"
    assert FrozenRecord(result.runtime.trace_path.read_text(encoding="utf-8").splitlines()[-1]).data()["stage"] == "driver_failure"
