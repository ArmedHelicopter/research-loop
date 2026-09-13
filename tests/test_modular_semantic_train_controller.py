"""Actual custody/controller/model-port seam for the fixed P0 semantic grid."""
import pytest

from evaluation.modular.train_io import TrainPacketExporter
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.panel_plan import executable_arms, obligation_grids
from research_loop.modular.runtime import AuditVerifier
from research_loop.modular.train_controller import FrozenTrainControllerConfig, run_train_panel
from research_loop.ontology import ContractError
from test_modular_semantic_panel_drivers import _bundle, _model, _semantic_response
from test_modular_train_controller import FINAL, config, model_port, snapshot_and_custody


def _closed_shape(value):
    if isinstance(value, dict):
        return {"type": "object", "properties": {key: _closed_shape(item) for key, item in value.items()},
                "required": list(value), "additionalProperties": False}
    if isinstance(value, list):
        return {"type": "array", "items": _closed_shape(value[0]) if value else {"type": "string"}}
    return {"type": "boolean" if isinstance(value, bool) else "string"}


@pytest.mark.parametrize("coverage,expected_cells,slots", [
    ("Q2.2", 10, ("semantic_judgement", "alternative_analysis", "final")),
    ("Q6.4", 6, ("first_semantic_judgement", "first_alternative_analysis", "second_semantic_judgement", "second_alternative_analysis", "final")),
])
def test_semantic_driver_runs_all_cells_with_compiled_p0_control(tmp_path, monkeypatch, coverage, expected_cells, slots):
    snapshot, custody = snapshot_and_custody(tmp_path)
    base = config(custody, snapshot, tmp_path).data()
    packets = TrainPacketExporter(custody, snapshot, tmp_path / "material-export").export(base["item_ids"])
    grids = obligation_grids((coverage,), baseline_digest=base["baseline_digest"], p0_control=FrozenRecord.from_dict(base["p0_control"]))
    package = next(iter(base["packages_by_arm"].values()))
    semantic = _closed_shape(_semantic_response("The programme is complete."))
    alternative = _closed_shape({"scientific_acceptability": "unknown", "rationale": "synthetic assessment"})
    schemas = {slot: FINAL if slot == "final" else alternative if slot.endswith("alternative_analysis") else semantic for slot in slots}
    frozen = FrozenTrainControllerConfig(FrozenRecord.from_dict({**base, "schema": "train-panel-controller-v1",
        "engineering_scope": "train_only_panel_engineering", "stage": "synthetic-semantic-controller", "scope_ids": [coverage],
        "evidence_by_task": {packet.task.content_hash: _bundle(packet.task, grids[coverage]).data() for packet in packets},
        "packages_by_arm": {arm.content_hash: package for arm in executable_arms(grids[coverage]).values()},
        "budget": {"model_calls": len(slots), "execution_limit": 0}, "max_calls": expected_cells * len(slots), "schemas": schemas}))
    drifted = frozen.data(); drifted["p0_control"] = {"p0": "different trusted control"}
    with pytest.raises(ContractError, match="controller's frozen P0"):
        FrozenTrainControllerConfig(FrozenRecord.from_dict(drifted))
    seen = []
    port = model_port(tmp_path, monkeypatch, max_calls=expected_cells * len(slots), schemas=schemas, response_factory=_model(seen))
    result = run_train_panel(frozen, custody=custody, snapshot_root=snapshot, export_root=tmp_path / "export",
        run_root=tmp_path / "run", model=port, audit_verifier=AuditVerifier({"a": b"a" * 32, "b": b"b" * 32}))
    assert len(result.runtimes) == expected_cells and all(row.status == "succeeded" for row in result.runtimes)
    assert len(port.ledger["calls"]) == len(seen) == expected_cells * len(slots)
    assert all(request["module_context"]["p0_control_digest"] == result.compiled.control.content_hash for request in seen)
    assert result.receipt.data()["execution_status"] == "engineering_complete" and result.verdict.scientific_verified is False
