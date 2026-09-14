"""Coherent Q8.6 consumer mutation regressions.

The helpers rebuild every ordinary journal digest after each mutation.  The
consumer must reject for the independent panel/scenario expectation, not for a
stale checksum or broken catalogue chain.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.artifact_catalogue import ArtifactCatalogue, source_snapshot
from research_loop.modular.research_versions import verify_research_version_artifacts
from research_loop.ontology import ContractError
from research_loop.modular.panel_plan import obligation_grids, executable_arms
from research_loop.modular.runtime import AuditVerifier
from research_loop.modular.train_controller import FrozenTrainControllerConfig, run_train_panel
from test_modular_train_controller import snapshot_and_custody, config, model_port, FINAL
from test_modular_q85_q86_q87_train_controller import GOAL_REVIEW, REVIEW, FRONTIER, bundle, Provider, Authority, response
from test_modular_retrieval_panel_drivers import admission


def _consumer(sidecar, cell, scenario, lock, expected_run_id):
    events = tuple(FrozenRecord(line).data() for line in (sidecar / "trace.jsonl").read_text(encoding="utf-8").splitlines())
    return verify_research_version_artifacts(sidecar, cell=cell, scenario=scenario, identity=cell.identity,
        task_digest=cell.task_digest, lock=lock, events=events, expected_run_id=expected_run_id)


@pytest.fixture(scope="module")
def q86_actual_cases(tmp_path_factory):
    """Build once with the production Q8.6 driver, then isolate each sidecar."""
    tmp_path = tmp_path_factory.mktemp("q86-consumer-mutations")
    snapshot, custody = snapshot_and_custody(tmp_path)
    base = config(custody, snapshot, tmp_path).data()
    from evaluation.modular.train_io import TrainPacketExporter
    packets = TrainPacketExporter(custody, snapshot, tmp_path / "material").export(base["item_ids"])
    evidence = {packet.task.content_hash: bundle(packet).data() for packet in packets}
    grid = obligation_grids(("Q8.6",), baseline_digest=base["baseline_digest"],
                            p0_control=FrozenRecord.from_dict(base["p0_control"]))["Q8.6"]
    package = next(iter(base["packages_by_arm"].values()))
    schemas = {"final": FINAL, "review": GOAL_REVIEW, "frontier_review_a": REVIEW,
               "frontier_review_b": REVIEW, "frontier": FRONTIER}
    frozen = FrozenTrainControllerConfig(FrozenRecord.from_dict({**base, "schema":"train-panel-controller-v1",
        "engineering_scope":"train_only_panel_engineering", "stage":"q86-consumer-mutation-fixture",
        "scope_ids":["Q8.6"], "evidence_by_task":evidence,
        "packages_by_arm":{arm.content_hash:package for arm in executable_arms(grid).values()},
        "budget":{"model_calls":2,"retrieval_calls":3,"execution_limit":0}, "max_calls":48, "max_tokens":512,
        "schemas":schemas}))
    with pytest.MonkeyPatch.context() as patches:
        port = model_port(tmp_path, patches, max_calls=48, max_tokens=512, schemas=schemas, response_factory=response)
        result = run_train_panel(frozen, custody=custody, snapshot_root=snapshot, export_root=tmp_path / "export",
            run_root=tmp_path / "run", model=port, audit_verifier=AuditVerifier({"a":b"a"*32,"b":b"b"*32}),
            retrieval_provider=Provider(), retrieval_admission_port=admission, retrieval_final_authority=Authority())
    cells = {cell.key: cell for cell in result.compiled.panel.cells}
    selected = {}
    for variant in ("pause_new_version", "conflict", "malicious_override"):
        runtime = next(row for row in result.runtimes if cells[row.cell_key].variant == variant and "M1" in cells[row.cell_key].runtime_arm.data()["enabled"] and "M6" in cells[row.cell_key].runtime_arm.data()["enabled"])
        cell = cells[runtime.cell_key]; original = runtime.trace_path.parent
        copied = tmp_path / "copies" / variant; shutil.copytree(original, copied)
        lock = FrozenRecord((copied / "trace.jsonl").read_text(encoding="utf-8").splitlines()[0]).data()["data"]
        catalogue = json.loads((copied / "artifacts.jsonl").read_text(encoding="utf-8").splitlines()[0])["descriptor"]["binding"]
        selected["paused" if variant == "pause_new_version" else "override" if variant == "malicious_override" else "conflict"] = (
            copied, cell, result.compiled.scenarios[cell.key], lock, catalogue["run_id"])
    return selected


@pytest.mark.parametrize("case,fault", [
    ("paused", "child_schema"), ("paused", "child_state"),
    ("conflict", "transition_from"), ("conflict", "transition_reason"),
    ("paused", "source_bundle"), ("paused", "visible_sources"),
    ("paused", "receipt_scientific"), ("paused", "producer_source"),
    ("override", "run_id"),
])
def test_q86_consumer_rejects_coherently_rehashed_mutations(q86_actual_cases, tmp_path, case, fault):
    original, cell, scenario, lock, expected_run_id = q86_actual_cases[case]
    sidecar = tmp_path / "sidecar"; shutil.copytree(original, sidecar)
    from q86_coherent_copy import rewrite
    _consumer(sidecar, cell, scenario, lock, expected_run_id)
    rewrite(sidecar, fault=fault, identity=cell.identity)
    with pytest.raises(ContractError):
        _consumer(sidecar, cell, scenario, lock, expected_run_id)
