"""Synthetic public integration checks for planning-only prediction drivers."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from research_loop.modular import panel_runner
from research_loop.modular.benchmarks import BladeAdapter, DiscoveryBenchAdapter
from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
from research_loop.modular.panel_plan import compile_train_panel, executable_arms, obligation_grids
from research_loop.modular.panel_receipts import PanelReceiptVerifier
from research_loop.modular.prediction_panel_drivers import (
    Q32JointSeparateDriver,
    Q53DedupDriver,
    _prediction_signature,
    freeze_prediction_bundle,
    prediction_panel_injection,
)
from research_loop.modular.runtime import AuditVerifier
from research_loop.ontology import ContractError


def branch(identifier: str, mechanism: str, direction: str) -> dict:
    return {"hypothesis_id": identifier, "mechanism_key": mechanism, "mechanism": "public " + mechanism,
            "intervention": "public intervention", "elimination_condition": "public failure",
            "predictions": [{"prediction_id": identifier + "-prediction", "discriminator_id": "public-disc",
                             "observable": "public x", "direction": direction, "value_range": None,
                             "failure_condition": "not " + direction}]}


def task(name: str):
    identity = DataIdentity(name, "pred-" + name, name + ":pred", "v1", "8" * 64, "train")
    if name == "discoverybench":
        return DiscoveryBenchAdapter().prepare(identity, {"task_id": identity.task_id, "question": "PUBLIC " + name,
            "source_kind": "synthetic", "dataset": [{"name": "x", "columns": [{"name": "x"}]}]})
    return BladeAdapter().prepare(identity, {"task_id": identity.task_id, "dataset_id": "p",
        "research_question": "PUBLIC " + name, "data_schema": [{"name": "x", "dtype": "float"}]})


def support(t, suffix: str, branches: list[dict]) -> dict:
    source_id, observation_id = "public-source-" + suffix, "public-observation-" + suffix
    return {"schema": "prediction-support-record-v1", "task_digest": t.content_hash, "source_id": source_id,
            "observation_id": observation_id, "public_observation": "public observation " + suffix,
            "branch_ids": [item["hypothesis_id"] for item in branches], "caller_admission_receipt": {
                "schema": "caller-observation-admission-v1", "task_digest": t.content_hash,
                "source_id": source_id, "observation_id": observation_id, "authority_id": "caller-authority",
                "receipt_digest": "receipt-" + suffix}}


def q32_plan(t, question: str, branches: list[dict], budget: int, suffix: str) -> dict:
    return {"question": question, "branches": branches, "budget_units": budget,
            "support_records": [support(t, suffix, branches)]}


def proposal(branch_value: dict, root_id: str, title: str) -> dict:
    return {"proposal_id": branch_value["hypothesis_id"], "root_id": root_id,
            "mechanism_key": branch_value["mechanism_key"],
            "prediction_signature": _prediction_signature(branch_value), "title": title}


def material(t):
    a, b, c = branch("a", "mechanism-a", "positive"), branch("b", "mechanism-b", "negative"), branch("c", "mechanism-c", "null")
    q32 = {"joint": {"plans": [q32_plan(t, "public joint question", [a, b, c], 3, "joint")]},
           "separate": {"plans": [q32_plan(t, "public separate one", [a, b], 1, "one"),
                                  q32_plan(t, "public separate two", [a, c], 1, "two"),
                                  q32_plan(t, "public separate three", [b, c], 1, "three")]}}
    same_a, same_b = branch("same-a", "shared-mechanism", "positive"), branch("same-b", "shared-mechanism", "positive")
    opposite_a, opposite_b = branch("opposite-a", "shared-mechanism", "positive"), branch("opposite-b", "shared-mechanism", "negative")
    title_a, title_b = branch("title-a", "candidate-a", "positive"), branch("title-b", "candidate-b", "null")
    q53 = {
        "same_mechanism": {"proposals": [proposal(same_a, "shared-root", "first"), proposal(same_b, "shared-root", "second")],
                           "plan": {"question": "public same mechanism", "branches": [same_a, same_b], "budget_units": 2}},
        "opposite_prediction": {"proposals": [proposal(opposite_a, "shared-root", "first"), proposal(opposite_b, "shared-root", "second")],
                                "plan": {"question": "public opposite prediction", "branches": [opposite_a, opposite_b], "budget_units": 2}},
        "title": {"proposals": [proposal(title_a, "root-a", "same title"), proposal(title_b, "root-b", "same title")],
                  "plan": {"question": "public title baseline", "branches": [title_a, title_b], "budget_units": 2}},
    }
    return freeze_prediction_bundle(t, public_evidence={"schema": "prediction-public-evidence-v1", "task_digest": t.content_hash,
        "source_id": "public-source", "observation_id": "public-observation", "public_summary": "PUBLIC observation"},
        controller_truth={"schema": "prediction-controller-truth-v1", "marker": "same_wrong"}, q32=q32, q53=q53)


def model(seen: list[dict], *, fail_dedup: bool = False):
    def callback(request: FrozenRecord) -> FrozenRecord:
        row = request.data(); seen.append(row); slot = row["slot"]
        if slot.startswith("plan_"):
            plan = row["module_context"]["plan_material"]
            return FrozenRecord.from_dict({name: plan[name] for name in ("question", "branches", "budget_units")})
        if slot == "dedup":
            kept = row["module_context"]["retained_proposal_ids"]
            return FrozenRecord.from_dict({"kept_proposal_ids": ["wrong"] if fail_dedup else kept})
        if slot == "final":
            return FrozenRecord.from_dict({"objective_digest": row["module_context"]["required_objective_digest"],
                "outcome": "unknown", "evidence_ids": [], "conclusion": "planning-only", "programme_complete": False})
        raise AssertionError("unexpected model slot")
    return callback


def _compiled(tmp_path: Path):
    tasks = {name: task(name) for name in ("discoverybench", "blade")}
    package = CandidatePackage.create(parent_digest=None, manifest=TrainingManifest.freeze([item.identity for item in tasks.values()]),
        changes={"prompt": {"instructions": "planning only"}}, search_cost=0)
    grids = obligation_grids(("Q3.2", "Q5.3"), baseline_digest="base", p0_control=FrozenRecord.from_dict({"p": "0"}))
    packages = {arm.content_hash: package for grid in grids.values() for arm in executable_arms(grid).values()}
    return compile_train_panel(stage="prediction", scope_ids=("Q3.2", "Q5.3"), tasks=tuple(tasks.values()),
        evidence_by_task={item.content_hash: material(item) for item in tasks.values()}, budget=FrozenRecord.from_dict({"calls": 4}),
        baseline_digest="base", p0_control=FrozenRecord.from_dict({"p": "0"}), packages_by_arm=packages,
        scorer=FrozenRecord.from_dict({"s": "none"}), acceptance_criteria=FrozenRecord.from_dict({"a": "engineering"})), tasks


def _events(path: Path) -> list[dict]:
    return [FrozenRecord(line).data() for line in path.read_text(encoding="utf-8").splitlines()]


def _artifact(events: list[dict]) -> dict:
    return next(row["data"]["artifacts"] for row in events if row["stage"] == "modular_workflow"
                and row["data"]["stage"] == "prediction_artifacts")


def test_full_prediction_grid_has_actual_planning_artifacts_and_matched_calls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    compiled, tasks = _compiled(tmp_path)
    monkeypatch.setitem(panel_runner.DRIVERS, "Q3.2", Q32JointSeparateDriver())
    monkeypatch.setitem(panel_runner.DRIVERS, "Q5.3", Q53DedupDriver())
    runs = []
    assert len(compiled.panel.cells) == 20
    for index, cell in enumerate(compiled.panel.cells):
        seen: list[dict] = []
        run = panel_runner.run_train_cell(cell, task=tasks[cell.identity.benchmark], scenario=compiled.scenarios[cell.key],
            package=compiled.packages[cell.runtime_arm.content_hash], objective=FrozenRecord.from_dict({"o": "x"}),
            sidecar=tmp_path / str(index), model=model(seen), audit_verifier=AuditVerifier({"a": b"a" * 32, "b": b"b" * 32}))
        assert run.runtime.status == "succeeded" and run.call_plan.data()["model_calls"] == (4 if cell.coverage_id == "Q3.2" else 2)
        assert all("same_wrong" not in FrozenRecord.from_dict(request).encoded for request in seen)
        for request in seen:
            encoded = FrozenRecord.from_dict(request).encoded
            assert all(key not in encoded for key in ('"planning_status"', '"not_applied"', '"controller_truth"',
                '"caller_admission_receipt"', '"candidate_package"', '"arm_id"', '"variant"'))
        events = _events(run.runtime.trace_path); artifact = _artifact(events)
        records = (run.runtime.trace_path.parent / "predictions.jsonl").read_text(encoding="utf-8").splitlines()
        if "M4" not in cell.runtime_arm.data()["enabled"]:
            assert not records and next(row["data"] for row in events if row["stage"] == "modular_workflow")["stage"] == "operation_m4_control"
            if cell.coverage_id == "Q5.3":
                result = artifact["deduplication"]
                assert result["kept"] == (["title-a"] if cell.variant == "title" else
                    ["same-a", "same-b"] if cell.variant == "same_mechanism" else ["opposite-a", "opposite-b"])
        elif cell.coverage_id == "Q3.2":
            plans = artifact["joint_or_separate"]
            budgets = [item["plan"]["budget_units"] for item in plans]
            assert all(item["planning_status"] == "planning_only" and item["execution_status"] == "not_measured" for item in plans)
            if cell.variant == "joint":
                assert len(records) == 1 and budgets == [3, 3, 3] and len({FrozenRecord.from_dict(item["plan"]).content_hash for item in plans}) == 1
            else:
                assert len(records) == 3 and budgets == [1, 1, 1] and len({FrozenRecord.from_dict(item["plan"]).content_hash for item in plans}) == 3
        else:
            result = artifact["deduplication"]
            if cell.variant == "same_mechanism":
                assert not records and result["kept"] == ["same-a"] and result["removed"] == ["same-b"]
                assert result["plan"] is None and result["planning_status"] == "not_distinguishable_after_dedup"
            else:
                assert len(records) == 1 and result["removed"] == [] and len(result["plan"]["branches"]) == 2
                if cell.variant == "title":
                    assert result["title_baseline"]["removed"] == ["title-b"] and result["kept"] == ["title-a", "title-b"]
                else:
                    assert result["kept"] == ["opposite-a", "opposite-b"]
        runs.append(run.runtime)
    assert PanelReceiptVerifier().verify(compiled.panel, tuple(runs)).decision == "engineering_verified"


def test_dedup_uses_mechanism_not_source_and_preserves_opposite_forecasts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setitem(panel_runner.DRIVERS, "Q5.3", Q53DedupDriver())
    compiled, tasks = _compiled(tmp_path)
    for variant in ("same_mechanism", "opposite_prediction"):
        cell = next(item for item in compiled.panel.cells if item.coverage_id == "Q5.3" and item.variant == variant
                    and "M4" in item.runtime_arm.data()["enabled"])
        public = tasks[cell.identity.benchmark]; raw = material(public).data()
        row = raw["q53"][variant]
        if variant == "same_mechanism":
            row["proposals"][1]["root_id"] = "independent-source-with-same-declared-mechanism"
        else:
            extra = branch("other", "different-mechanism", "positive")
            row["plan"]["branches"].append(extra)
            row["proposals"].append(proposal(extra, "shared-root", "other title"))
        bundle = freeze_prediction_bundle(public, **{name: raw[name] for name in ("public_evidence", "controller_truth", "q32", "q53")})
        body = compiled.scenarios[cell.key].data()
        body["controller_input"] = dict(prediction_panel_injection("Q5.3", variant, task=FrozenRecord.from_dict(public.data()), evidence=bundle))
        body["base"]["evidence"] = bundle.content_hash
        scenario = FrozenRecord.from_dict(body); selected = replace(cell, scenario_digest=scenario.content_hash)
        run = panel_runner.run_train_cell(selected, task=public, scenario=scenario,
            package=compiled.packages[cell.runtime_arm.content_hash], objective=FrozenRecord.from_dict({"o": "semantics"}),
            sidecar=tmp_path / variant, model=model([]), audit_verifier=AuditVerifier({"a": b"a"*32, "b": b"b"*32}))
        assert run.runtime.status == "succeeded"
        artifact = _artifact(_events(run.runtime.trace_path))["deduplication"]
        assert artifact["kept"] == (["same-a"] if variant == "same_mechanism" else ["opposite-a", "opposite-b", "other"])


@pytest.mark.parametrize("bad", [True, "3"])
def test_bundle_rejects_noninteger_budget_and_deep_bad_plan_before_any_model_call(bad: object) -> None:
    public = task("discoverybench")
    raw = material(public).data(); raw["q32"]["joint"]["plans"][0]["budget_units"] = bad
    with pytest.raises(ContractError, match="budget"):
        prediction_panel_injection("Q3.2", "joint", task=FrozenRecord.from_dict(public.data()), evidence=FrozenRecord.from_dict(raw))
    raw = material(public).data(); raw["q32"]["joint"]["plans"][0]["branches"][0]["predictions"][0]["direction"] = None
    with pytest.raises(ContractError, match="exactly one"):
        prediction_panel_injection("Q3.2", "joint", task=FrozenRecord.from_dict(public.data()), evidence=FrozenRecord.from_dict(raw))


def test_invalid_runtime_bundle_fails_before_model_slot_and_remains_a_panel_row(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    compiled, tasks = _compiled(tmp_path)
    monkeypatch.setitem(panel_runner.DRIVERS, "Q3.2", Q32JointSeparateDriver())
    cell = next(item for item in compiled.panel.cells if item.coverage_id == "Q3.2" and item.variant == "joint")
    bad = material(tasks[cell.identity.benchmark]).data(); bad["q32"]["joint"]["plans"][0]["budget_units"] = True
    body = compiled.scenarios[cell.key].data(); body["controller_input"]["material_bundle"] = bad; body["base"]["evidence"] = FrozenRecord.from_dict(bad).content_hash
    scenario = FrozenRecord.from_dict(body); failed_cell = replace(cell, scenario_digest=scenario.content_hash)
    seen: list[dict] = []
    run = panel_runner.run_train_cell(failed_cell, task=tasks[cell.identity.benchmark], scenario=scenario,
        package=compiled.packages[cell.runtime_arm.content_hash], objective=FrozenRecord.from_dict({"o": "bad"}), sidecar=tmp_path / "bad",
        model=model(seen), audit_verifier=AuditVerifier({"a": b"a" * 32, "b": b"b" * 32}))
    assert run.runtime.status == "failed" and not seen
    assert not [row for row in _events(run.runtime.trace_path) if row["stage"] == "model_request"]


def test_bad_dedup_response_is_a_failed_denominator_row(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    compiled, tasks = _compiled(tmp_path)
    monkeypatch.setitem(panel_runner.DRIVERS, "Q5.3", Q53DedupDriver())
    cell = next(item for item in compiled.panel.cells if item.coverage_id == "Q5.3" and item.variant == "opposite_prediction" and "M4" in item.runtime_arm.data()["enabled"])
    run = panel_runner.run_train_cell(cell, task=tasks[cell.identity.benchmark], scenario=compiled.scenarios[cell.key],
        package=compiled.packages[cell.runtime_arm.content_hash], objective=FrozenRecord.from_dict({"o": "bad dedup"}), sidecar=tmp_path / "failed",
        model=model([], fail_dedup=True), audit_verifier=AuditVerifier({"a": b"a" * 32, "b": b"b" * 32}))
    assert run.runtime.status == "failed" and run.call_plan.data()["model_calls"] == 1


def test_failed_cell_stays_in_the_complete_twenty_cell_denominator(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    compiled, tasks = _compiled(tmp_path)
    monkeypatch.setitem(panel_runner.DRIVERS, "Q3.2", Q32JointSeparateDriver())
    monkeypatch.setitem(panel_runner.DRIVERS, "Q5.3", Q53DedupDriver())
    failing = next(item.key for item in compiled.panel.cells if item.coverage_id == "Q5.3"
                   and item.variant == "opposite_prediction" and "M4" in item.runtime_arm.data()["enabled"])
    runs = []
    for index, cell in enumerate(compiled.panel.cells):
        run = panel_runner.run_train_cell(cell, task=tasks[cell.identity.benchmark], scenario=compiled.scenarios[cell.key],
            package=compiled.packages[cell.runtime_arm.content_hash], objective=FrozenRecord.from_dict({"o": "denominator"}),
            sidecar=tmp_path / str(index), model=model([], fail_dedup=cell.key == failing),
            audit_verifier=AuditVerifier({"a": b"a" * 32, "b": b"b" * 32}))
        runs.append(run.runtime)
    verdict = PanelReceiptVerifier().verify(compiled.panel, tuple(runs))
    assert verdict.observed_cells == 20 and verdict.failures == 1 and verdict.decision == "engineering_verified"
