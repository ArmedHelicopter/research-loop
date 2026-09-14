"""Focused producer/reader checks for Q6 scenario sidecar artifacts."""
from pathlib import Path

import pytest

from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.scenarios_improvement import (
    inspect_scenario_artifact_failure, run_improvement_scenario,
    verify_scenario_artifacts,
)
from research_loop.ontology import ContractError
from test_modular_improvement_scenarios import controls, task_for


def _run(root: Path, experiment: str, variant: str, callback=None):
    task = task_for("blade")
    args = dict(task=task, frozen_controls=controls(task), sidecar=root,
                experiment_id=experiment, variant=variant)
    result = run_improvement_scenario(callback=callback, **args)
    return result, args


@pytest.mark.parametrize(("experiment", "variant", "sidecars"), [
    ("Q6.1", "self_activate", {"runtime.sqlite", "active.json"}),
    ("Q6.2", "automatic_train", {"optimizer.sqlite"}),
    ("Q6.5", "unprotected", {"shadow-runtime.sqlite", "shadow-deployment.json"}),
    ("Q6.6", "rollback", {"runtime.sqlite", "deployment.json"}),
])
def test_actual_offline_scenario_outputs_are_sealed_and_read_without_rerun(tmp_path, monkeypatch,
                                                                              experiment, variant, sidecars):
    calls = []
    def callback(request):
        calls.append(request)
        if request.data()["kind"] == "train_candidate_proposal":
            return FrozenRecord.from_dict({"changes": {"memory": {"mode": "automatic", "lesson": "fixture"}}})
        return FrozenRecord.from_dict({"reply": request.data()["kind"]})
    result, args = _run(tmp_path / "run", experiment, variant, callback)
    root = args["sidecar"]
    assert sidecars <= {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    assert result.callback_payloads == tuple(calls)
    terminal = FrozenRecord((root / "scenario-terminal.json").read_text(encoding="utf-8").strip()).data()
    assert terminal["status"] == "succeeded" and terminal["fixture_only"] is True
    assert all(set(v) == {"sha256", "bytes"} for v in terminal["files"].values())
    before = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    monkeypatch.setattr("research_loop.modular.scenarios_improvement.ExecutionRuntime", lambda *a, **k: (_ for _ in ()).throw(AssertionError("reader activated runtime")))
    assert verify_scenario_artifacts(result, **args).data()["status"] == "succeeded"
    assert before == {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_failed_callback_keeps_sealed_prefix_and_is_not_accepted(tmp_path):
    error = ContractError("fixture callback stopped")
    calls = 0
    def callback(_request):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise error
        return FrozenRecord.from_dict({"reply": "first retained callback"})
    with pytest.raises(ContractError) as caught:
        _run(tmp_path / "run", "Q6.5", "sealed_calibrated", callback)
    assert caught.value is error
    task = task_for("blade"); root = tmp_path / "run"
    terminal = FrozenRecord((root / "scenario-terminal.json").read_text(encoding="utf-8").strip()).data()
    assert terminal["status"] == "failed" and terminal["result_digest"] is None
    assert "shadow-runtime.sqlite" in terminal["files"]
    before = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    report = inspect_scenario_artifact_failure(task=task, frozen_controls=controls(task), sidecar=root,
                                               experiment_id="Q6.5", variant="sealed_calibrated").data()
    assert report["storage_integrity_verified"] and not report["acceptance_eligible"]
    assert before == {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("returned", [None, {"not": "frozen"}])
def test_first_callback_opportunity_and_invalid_return_are_retained(tmp_path, returned):
    root = tmp_path / "run"
    with pytest.raises(ContractError):
        _run(root, "Q6.1", "change_rule", lambda _request: returned)
    rows = [FrozenRecord(line).data()["descriptor"] for line in (root / "scenario-artifacts.jsonl").read_text(encoding="utf-8").splitlines()]
    request = next(row for row in rows if row["kind"] == "scenario_callback_request")
    outcome = next(row for row in rows if row["kind"] == "scenario_callback_return")
    assert request["payload"]["canonical"]["kind"] == "privilege_attempt"
    assert outcome["payload"]["canonical"]["returned_type"] == type(returned).__name__
    assert outcome["status"] == "rejected"


def test_throwing_first_callback_keeps_request_and_failure_outcome(tmp_path):
    root = tmp_path / "run"; error = RuntimeError("fixture callback failure")
    with pytest.raises(RuntimeError) as caught:
        _run(root, "Q6.1", "change_rule", lambda _request: (_ for _ in ()).throw(error))
    assert caught.value is error
    rows = [FrozenRecord(line).data()["descriptor"] for line in (root / "scenario-artifacts.jsonl").read_text(encoding="utf-8").splitlines()]
    outcome = next(row for row in rows if row["kind"] == "scenario_callback_return")
    assert outcome["status"] == "failed" and outcome["payload"]["canonical"]["error"] == str(error)
