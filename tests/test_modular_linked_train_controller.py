"""Focused controller coverage for trace-bound benchmark solves.

The model transport is a no-cost subprocess fixture.  The successful path uses
the pinned local Docker image; failure rows use the same broker with a bounded
synthetic Docker process outcome.
"""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import subprocess
import pytest

from research_loop.modular import benchmark_cell, train_controller
from research_loop.modular.benchmark_cell import verify_linked_benchmark_cell
from research_loop.modular.benchmarks.execution import DockerExecutionBroker
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.panel_plan import executable_arms, obligation_grids
from research_loop.modular.runtime import AuditVerifier
from research_loop.modular.train_controller import FrozenTrainControllerConfig, _driver_plan, run_train_panel
from research_loop.ontology import ContractError
from test_modular_train_controller import FINAL, REVIEW, SCENARIO, config, model_port, snapshot_and_custody


IMAGE = "research-benchmark-python@sha256:1433f0d223b0773b0d8c3184fa4ff6ab0a3891113442f1592d8d7e883d21a349"
ANALYSIS = {"type": "object", "properties": {"analysis": {"type": "string"}, "program": {"type": "string"}},
            "required": ["analysis", "program"], "additionalProperties": False}
AUDIT = {"a": b"a" * 32, "b": b"b" * 32}


def _schemas(scope: str, *, linked: bool) -> dict:
    driver = train_controller.DRIVERS[scope]
    result = {slot: REVIEW for slot in driver.slots}
    result["final"] = FINAL
    if scope == "Q3.1":
        result["scenario"] = SCENARIO
    if linked:
        result |= {"analysis_program": ANALYSIS, "final_answer": FINAL}
    return result


def _linked_config(custody, snapshot: Path, root: Path, *, scope: str = "Q3.1",
                   max_calls: int | None = None, linked: bool = True) -> FrozenTrainControllerConfig:
    base = config(custody, snapshot, root).data()
    package = next(iter(base["packages_by_arm"].values()))
    control = FrozenRecord.from_dict(base["p0_control"])
    grids = obligation_grids((scope,), baseline_digest=base["baseline_digest"], p0_control=control)
    packages = {arm.content_hash: package for grid in grids.values() for arm in executable_arms(grid).values()}
    cells, calls = _driver_plan((scope,), baseline_digest=base["baseline_digest"], p0_control=control,
                                item_count=len(base["item_ids"]), replicates=("r1",), linked=linked)
    return FrozenTrainControllerConfig(FrozenRecord.from_dict({**base,
        "schema": "train-panel-controller-v1", "engineering_scope": "train_only_panel_engineering",
        "stage": "synthetic-linked-" + scope, "scope_ids": [scope], "packages_by_arm": packages,
        "max_calls": calls if max_calls is None else max_calls, "max_tokens": 200,
        "schemas": _schemas(scope, linked=linked),
        **({"execution_mode": "linked_benchmark_solve"} if linked else {})
    }))


@pytest.mark.parametrize("scope", ["Q1.5", "Q3.1", "Q4.3"])
def test_linked_config_has_exact_driver_and_solver_slots_and_two_extra_calls(tmp_path: Path, scope: str) -> None:
    snapshot, custody = snapshot_and_custody(tmp_path)
    base = _linked_config(custody, snapshot, tmp_path / scope, scope=scope, linked=False)
    linked = _linked_config(custody, snapshot, tmp_path / (scope + "-linked"), scope=scope)
    base_cells, base_calls = _driver_plan((scope,), baseline_digest=base.data()["baseline_digest"],
        p0_control=FrozenRecord.from_dict(base.data()["p0_control"]), item_count=2, replicates=("r1",), linked=False)
    linked_cells, linked_calls = _driver_plan((scope,), baseline_digest=linked.data()["baseline_digest"],
        p0_control=FrozenRecord.from_dict(linked.data()["p0_control"]), item_count=2, replicates=("r1",), linked=True)
    assert base_cells == linked_cells
    assert linked_calls == base_calls + 2 * linked_cells
    assert set(base.data()["schemas"]) == set(train_controller.DRIVERS[scope].slots)
    assert set(linked.data()["schemas"]) == set(train_controller.DRIVERS[scope].slots) | {"analysis_program", "final_answer"}
    invalid = linked.data(); invalid["schemas"].pop("analysis_program")
    with pytest.raises(ContractError, match="exact production-driver"):
        FrozenTrainControllerConfig(FrozenRecord.from_dict(invalid))


def test_linked_controller_runs_custody_export_real_port_live_docker_and_replays_receipts(tmp_path: Path, monkeypatch) -> None:
    snapshot, custody = snapshot_and_custody(tmp_path)
    frozen = _linked_config(custody, snapshot, tmp_path)
    seen, captured = [], []
    original_verify, original_run = train_controller.verify_linked_benchmark_cell, train_controller.run_benchmark_cell

    def verified(*args, **kwargs):
        seen.append((args, kwargs))
        return original_verify(*args, **kwargs)

    def capture(**kwargs):
        result = original_run(**kwargs); captured.append(result); return result

    monkeypatch.setattr(train_controller, "verify_linked_benchmark_cell", verified)
    monkeypatch.setattr(train_controller, "run_benchmark_cell", capture)
    result = run_train_panel(frozen, custody=custody, snapshot_root=snapshot, export_root=tmp_path / "export",
        run_root=tmp_path / "run", model=model_port(tmp_path, monkeypatch, max_calls=frozen.data()["max_calls"], schemas=frozen.data()["schemas"]),
        audit_verifier=AuditVerifier(AUDIT))
    assert len(result.packets) == 2 and len(result.runtimes) == len(result.compiled.panel.cells) == 12
    assert len(seen) == len(captured) == 12
    assert result.receipt.data()["execution_status"] == "engineering_complete"
    assert result.receipt.data()["linked_statuses"] == ["linked_succeeded"] * 12
    assert all(item.solver and item.solver.execution and item.solver.execution.status == "succeeded" for item in captured)
    attempt = json.loads((tmp_path / "run" / "controller-attempt.json").read_text(encoding="utf-8"))
    assert len(attempt["linked_receipts"]) == len(attempt["linked_verifications"]) == 12
    forged = replace(captured[0], solver=None, provenance=None, status="mechanism_failed")
    forged = replace(forged, receipt=benchmark_cell._receipt(forged.cell, forged.mechanism, None, None, forged.status))
    with pytest.raises(ContractError, match="mechanism-only"):
        verify_linked_benchmark_cell(forged, task=result.packets[0].task,
                                      scenario=result.compiled.scenarios[captured[0].cell.key],
                                      package=result.compiled.packages[captured[0].cell.runtime_arm.content_hash])


def _docker_outcome(monkeypatch, outcome: str) -> None:
    original = DockerExecutionBroker.__init__

    def runner(argv, **_kwargs):
        if outcome == "timed_out":
            raise subprocess.TimeoutExpired(argv, 1, output=b"", stderr=b"synthetic timeout")
        if outcome == "unavailable":
            return subprocess.CompletedProcess(argv, 1, b"", b"Cannot connect to the Docker daemon")
        return subprocess.CompletedProcess(argv, 7, b"", b"synthetic execution failure")

    def init(self, allowed_roots, *, runner_ignored=None):
        original(self, allowed_roots, runner=runner)

    monkeypatch.setattr(train_controller.DockerExecutionBroker, "__init__", init)


@pytest.mark.parametrize("outcome", ["failed", "timed_out", "unavailable"])
def test_solver_execution_failures_stay_in_denominator_and_do_not_complete(tmp_path: Path, monkeypatch, outcome: str) -> None:
    snapshot, custody = snapshot_and_custody(tmp_path)
    frozen = _linked_config(custody, snapshot, tmp_path)
    _docker_outcome(monkeypatch, outcome)
    result = run_train_panel(frozen, custody=custody, snapshot_root=snapshot, export_root=tmp_path / "export",
        run_root=tmp_path / "run", model=model_port(tmp_path, monkeypatch, max_calls=frozen.data()["max_calls"], schemas=frozen.data()["schemas"]),
        audit_verifier=AuditVerifier(AUDIT))
    assert result.verdict.decision == "engineering_verified"
    assert result.receipt.data()["execution_status"] == "execution_incomplete"
    assert result.receipt.data()["linked_statuses"] == ["solver_execution_" + outcome] * 12


def test_mechanism_failures_remain_denominator_rows(tmp_path: Path, monkeypatch) -> None:
    snapshot, custody = snapshot_and_custody(tmp_path)
    frozen = _linked_config(custody, snapshot, tmp_path)
    def failed_mechanism_port(root: Path):
        port = model_port(root, monkeypatch, max_calls=frozen.data()["max_calls"], schemas=frozen.data()["schemas"])
        original = port.runner
        def fail_final(argv, **kwargs):
            request = json.loads(kwargs["input"].split("\n", 1)[1])
            if request["slot"] == "final":
                raise RuntimeError("synthetic mechanism failure")
            return original(argv, **kwargs)
        port.runner = fail_final
        return port

    mechanism = run_train_panel(frozen, custody=custody, snapshot_root=snapshot, export_root=tmp_path / "mechanism-export",
        run_root=tmp_path / "mechanism-run", model=failed_mechanism_port(tmp_path / "mechanism"), audit_verifier=AuditVerifier(AUDIT))
    assert mechanism.receipt.data()["execution_status"] == "execution_incomplete"
    assert mechanism.receipt.data()["linked_statuses"] == ["mechanism_failed"] * 12


def test_linked_call_budget_rejects_before_any_model_or_export_side_effect(tmp_path: Path, monkeypatch) -> None:
    snapshot, custody = snapshot_and_custody(tmp_path)
    enough = _linked_config(custody, snapshot, tmp_path)
    frozen = _linked_config(custody, snapshot, tmp_path / "short", max_calls=enough.data()["max_calls"] - 1)
    port = model_port(tmp_path / "port", monkeypatch, max_calls=frozen.data()["max_calls"], schemas=frozen.data()["schemas"])
    with pytest.raises(ContractError, match="call capacity"):
        run_train_panel(frozen, custody=custody, snapshot_root=snapshot, export_root=tmp_path / "export",
            run_root=tmp_path / "run", model=port, audit_verifier=AuditVerifier(AUDIT))
    assert port.ledger["calls"] == []
    assert not (tmp_path / "export").exists() and not (tmp_path / "run").exists()
