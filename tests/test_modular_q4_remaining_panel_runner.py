"""Two-benchmark production wiring checks for Q4.1, Q4.2, Q4.4 and Q4.5."""
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


SPLIT, SCORER = "1" * 64, "2" * 64
SCOPE = ("Q4.1", "Q4.2", "Q4.4", "Q4.5")


def _task(benchmark):
    identity = DataIdentity(benchmark, "q4-" + benchmark, benchmark + ":q4", "synthetic-v1", SPLIT, "train")
    sentinel = "PUBLIC-Q4-EVIDENCE-" + benchmark.upper()
    if benchmark == "discoverybench":
        return DiscoveryBenchAdapter().prepare(identity, {"task_id": identity.task_id, "question": sentinel,
            "source_kind": "synthetic", "dataset": [{"name": "public.csv", "columns": [{"name": "x"}]}]})
    return BladeAdapter().prepare(identity, {"task_id": identity.task_id, "dataset_id": "public", "research_question": sentinel,
        "data_schema": [{"name": "outcome", "dtype": "float"}], "task_instructions": "Use only supplied public data."})


def _obligations():
    modules = tuple(f"M{number}" for number in range(1, 10))
    return CombinationObligations(tuple(combinations(modules, 2)),
        (("M2", "M3", "M5"), ("M4", "M5", "M6"), ("M1", "M4", "M7"), ("M3", "M6", "M9"), ("M7", "M8", "M9")), modules, modules)


def _panel():
    tasks = {name: _task(name) for name in ("discoverybench", "blade")}
    package = CandidatePackage.create(parent_digest=None, manifest=TrainingManifest.freeze([task.identity for task in tasks.values()]),
        changes={"prompt": {"instructions": "synthetic public Q4 package"}}, search_cost=0)
    cells, scenarios, grids = [], {}, {}
    for coverage in SCOPE:
        modules = registry()[coverage].modules
        grid = default_compatibility("base").conditional_factorial(modules)
        grids[coverage] = grid
        arms = {row["id"]: FrozenRecord.from_dict(row["arm"]) for row in grid.data()["cells"] if row["status"] == "executable"}
        for benchmark, task in tasks.items():
            for variant in registry()[coverage].variants:
                material = scenario(registry()[coverage], variant, inputs=ControllerInputs(FrozenRecord.from_dict(task.data()),
                    FrozenRecord.from_dict({"public_evidence": task.payload.data()}), FrozenRecord.from_dict({"budget": "fixed"})))
                for arm_id, arm in arms.items():
                    cell = PanelCell(coverage, task.identity, "r1", variant, arm_id, arm, task.content_hash, material.content_hash, package.digest, SCORER)
                    cells.append(cell); scenarios[cell.key] = material
    return FrozenPanel("train-q4-remaining", "train", SPLIT, package.digest, SCOPE, grids,
        FrozenRecord.from_dict({"criterion": "engineering runner wiring only"}), tuple(cells), _obligations()), scenarios, tasks, package


def _branch(number):
    return {"hypothesis_id": "h" + str(number), "mechanism_key": "m" + str(number), "mechanism": "synthetic mechanism " + str(number),
        "intervention": "same public intervention", "predictions": [{"prediction_id": "p" + str(number), "discriminator_id": "shared",
            "observable": "public outcome", "direction": "up" if number % 2 else "down", "value_range": None,
            "failure_condition": "public observation differs"}], "elimination_condition": "shared observation differs"}


class _Transport:
    def __init__(self):
        self.calls = 0
        self.heterogeneous_reviewers = {
            "reviewer_one": {"provider": "synthetic-provider-a", "model_id": "synthetic-a", "callback": self._reviewer("a")},
            "reviewer_two": {"provider": "synthetic-provider-b", "model_id": "synthetic-b", "callback": self._reviewer("b")},
        }

    def _reviewer(self, suffix):
        def callback(request):
            return self(request)
        return callback

    def __call__(self, request):
        body = request.data()
        if body["slot"] == "final":
            return FrozenRecord.from_dict({"objective_digest": body["module_context"]["required_objective_digest"], "outcome": "unknown",
                "evidence_ids": [], "conclusion": "synthetic Q4 candidate", "programme_complete": False})
        review = {"assessment": "concern", "evidence_refs": ["public-observation"], "counterexamples": ["public alternative"], "uncertainty": "synthetic transport"}
        if body["module_context"].get("m4_enabled"):
            self.calls += 2
            return FrozenRecord.from_dict({"review": review, "prediction_candidates": [_branch(self.calls - 1), _branch(self.calls)]})
        return FrozenRecord.from_dict(review)


def _audit(): return AuditVerifier({"a": b"a" * 32, "b": b"b" * 32})


def _requests(run):
    return [FrozenRecord(line).data()["data"]["request"] for line in run.runtime.trace_path.read_text(encoding="utf-8").splitlines()
            if FrozenRecord(line).data()["stage"] == "model_request"]


def test_remaining_q4_full_grid_binds_public_material_blindness_revisions_and_m5_controls(tmp_path: Path):
    frozen, scenarios, tasks, package = _panel(); runs = []; seen_counts = {}
    for number, cell in enumerate(frozen.cells):
        run = run_train_cell(cell, task=tasks[cell.identity.benchmark], scenario=scenarios[cell.key], package=package,
            objective=FrozenRecord.from_dict({"objective": "q4 remaining"}), sidecar=tmp_path / str(number), model=_Transport(), audit_verifier=_audit())
        assert run.runtime.status == "succeeded"
        requests = _requests(run); runs.append(run)
        initial = [request for request in requests if request["module_context"].get("review_phase") == "initial_blind"]
        sentinel = "PUBLIC-Q4-EVIDENCE-" + cell.identity.benchmark.upper()
        assert initial and all(sentinel in FrozenRecord.from_dict(request["module_context"]).encoded for request in initial)
        assert all("scenario_controller_input" not in request["module_context"] and "reviewer_id" not in request["module_context"]
                   and "provider" not in request["module_context"] and "initial_answers" not in request["module_context"]
                   for request in initial)
        if cell.coverage_id == "Q4.5":
            final_context = requests[-1]["module_context"]["review_record"]
            assert final_context["initial_answers"] and final_context["post_reveal_revisions"]
        key = (cell.coverage_id, cell.variant, tuple(module for module in cell.runtime_arm.data()["enabled"] if module != "M5"))
        seen_counts.setdefault(key, set()).add(run.call_plan.data()["model_calls"])
    assert all(len(counts) == 1 for counts in seen_counts.values())
    verdict = PanelReceiptVerifier().verify(frozen, tuple(run.runtime for run in runs))
    assert verdict.decision == "engineering_verified" and verdict.failures == 0 and verdict.observed_cells == len(frozen.cells)


def test_q45_heterogeneous_without_configured_provider_fails_closed_and_stays_in_denominator(tmp_path: Path):
    frozen, scenarios, tasks, package = _panel()
    cell = next(item for item in frozen.cells if item.coverage_id == "Q4.5" and item.variant == "heterogeneous")
    def plain_model(request): return _Transport()(request)
    runs = []
    for number, current in enumerate(frozen.cells):
        callback = plain_model if current.key == cell.key else _Transport()
        runs.append(run_train_cell(current, task=tasks[current.identity.benchmark], scenario=scenarios[current.key], package=package,
            objective=FrozenRecord.from_dict({"objective": "q45 provider"}), sidecar=tmp_path / str(number), model=callback, audit_verifier=_audit()).runtime)
    result = next(row for row in runs if row.cell_key == cell.key)
    assert result.status == "failed"
    assert FrozenRecord(result.trace_path.read_text(encoding="utf-8").splitlines()[-1]).data()["stage"] == "controller_failure"
    verdict = PanelReceiptVerifier().verify(frozen, tuple(runs))
    assert verdict.engineering_verified and verdict.observed_cells == len(frozen.cells) and verdict.failures == 1
    with pytest.raises(ContractError, match="training cells only"):
        validation = PanelCell(cell.coverage_id, DataIdentity(cell.identity.benchmark, cell.identity.task_id, cell.identity.group_id,
            cell.identity.dataset_version, cell.identity.split_id, "validation"), cell.replicate, cell.variant, cell.arm_id,
            cell.runtime_arm, cell.task_digest, cell.scenario_digest, cell.package_digest, cell.scorer_digest)
        run_train_cell(validation, task=tasks[cell.identity.benchmark], scenario=scenarios[cell.key], package=package,
            objective=FrozenRecord.from_dict({"objective": "q45 provider"}), sidecar=tmp_path / "validation", model=plain_model, audit_verifier=_audit())
