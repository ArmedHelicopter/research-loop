"""Synthetic custody-to-model production coverage for every M8 panel cell."""
import json

import pytest

from evaluation.modular.train_io import TrainPacketExporter
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.modules.improvement import CandidatePackage
from research_loop.modular.panel_plan import executable_arms, obligation_grids
from research_loop.modular.runtime import AuditVerifier
from research_loop.modular.scheduler_panel_drivers import freeze_scheduler_bundle, freeze_scheduler_source
from research_loop.modular.train_controller import FrozenTrainControllerConfig, run_train_panel
from test_modular_scheduler_panel_drivers import _schedules
from test_modular_train_controller import FINAL, config, model_port, snapshot_and_custody


@pytest.mark.parametrize("coverage,expected_cells", [("Q3.3", 8), ("Q3.4", 8), ("Q3.5", 20)])
def test_scheduler_cells_execute_after_custody_export_and_frozen_model_policy(tmp_path, monkeypatch, coverage, expected_cells):
    snapshot, custody = snapshot_and_custody(tmp_path)
    base = config(custody, snapshot, tmp_path).data()
    packets = TrainPacketExporter(custody, snapshot, tmp_path / "material-export").export(base["item_ids"])
    package_record = next(iter(base["packages_by_arm"].values()))
    package = CandidatePackage(FrozenRecord.from_dict(package_record))
    evidence = {packet.task.content_hash: freeze_scheduler_bundle(packet.task,
        source=freeze_scheduler_source(packet.task, values=[2, -3, 4]),
        package_digest=package.digest, schedules=_schedules()).data() for packet in packets}
    grids = obligation_grids((coverage,), baseline_digest=base["baseline_digest"], p0_control=FrozenRecord.from_dict(base["p0_control"]))
    schemas = {"final": FINAL}
    frozen = FrozenTrainControllerConfig(FrozenRecord.from_dict({**base, "schema": "train-panel-controller-v1",
        "engineering_scope": "train_only_panel_engineering", "stage": "synthetic-scheduler-controller", "scope_ids": [coverage],
        "evidence_by_task": evidence,
        "packages_by_arm": {arm.content_hash: package_record for arm in executable_arms(grids[coverage]).values()},
        "budget": {"model_calls": 1, "execution_limit": 0}, "max_calls": expected_cells, "schemas": schemas}))
    seen = []
    def respond(request):
        body = request.data(); seen.append(body)
        context = body["module_context"]
        assert set(context["scheduler_observation"]) == {
            "schema", "input_binding", "outputs", "visibility", "missing_output_bindings"}
        assert set(context) == {"panel_cell", "public_task", "scheduler_observation", "required_objective_digest"}
        return FrozenRecord.from_dict({"objective_digest": context["required_objective_digest"], "outcome": "unknown",
            "evidence_ids": [], "conclusion": "synthetic scheduling observation", "programme_complete": False})
    port = model_port(tmp_path, monkeypatch, max_calls=expected_cells, schemas=schemas, response_factory=respond)
    result = run_train_panel(frozen, custody=custody, snapshot_root=snapshot,
        export_root=tmp_path / "export", run_root=tmp_path / "run", model=port,
        audit_verifier=AuditVerifier({"a": b"a" * 32, "b": b"b" * 32}))
    assert len(result.runtimes) == len(port.ledger["calls"]) == len(seen) == expected_cells
    assert result.receipt.data()["execution_status"] == "engineering_complete"
    assert result.verdict.scientific_verified is False
    cells = {cell.key: cell for cell in result.compiled.panel.cells}
    for runtime in result.runtimes:
        assert runtime.status == "succeeded"
        cell = cells[runtime.cell_key]
        observed = json.loads((runtime.trace_path.parent / "m8-controller-observation.json").read_text(encoding="utf-8"))
        assert observed["engine"] == ("durable_fifo" if "M8" in cell.runtime_arm.data()["enabled"] else "memory_fifo_baseline")
        assert observed["actual_spent_cost_units"] >= 5
        assert observed["remaining_leases"] == observed["unknown_runs"] == []
        assert all(attempt["output"] is None or attempt["output"]["task_digest"] == cell.task_digest
                   for attempt in observed["attempts"])
