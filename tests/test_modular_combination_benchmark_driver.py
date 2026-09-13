"""Synthetic public integration checks for the shared-session M4/M5 pair."""
from __future__ import annotations

import runpy
from dataclasses import replace
from pathlib import Path

import pytest

from research_loop.modular.benchmarks import DockerExecutionBroker
from research_loop.modular.combination_benchmark_driver import (
    run_m4_m5_combination_benchmark_cell, verify_m4_m5_combination_benchmark_cell,
)
from research_loop.modular.combination_panels import CombinationPanelVerifier
from research_loop.modular.combination_contrasts import estimate_grouped_contrast
from research_loop.modular.panel_receipts import PanelReceiptVerifier
from research_loop.modular.panel_receipts import ScientificScorerReceipt
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.modules.predictions import PredictionRegistry
from research_loop.modular.modules.review import ReviewEngine
from research_loop.modular.runtime import AuditVerifier
from research_loop.ontology import ContractError


IMAGE = "research-benchmark-python@sha256:1433f0d223b0773b0d8c3184fa4ff6ab0a3891113442f1592d8d7e883d21a349"


def _catalogue():
    return runpy.run_path("tests/test_modular_combination_panels.py")["_catalogue"]()


def _audit():
    return AuditVerifier({"audit-a": b"a" * 32, "audit-b": b"b" * 32})


def _plan():
    return {"question": "Which public mechanism explains x?", "budget_units": 3, "branches": [
        {"hypothesis_id": "h1", "mechanism_key": "m1", "mechanism": "public mechanism one", "intervention": "public",
         "elimination_condition": "x does not increase", "predictions": [{"prediction_id": "p1", "discriminator_id": "d",
            "observable": "x", "direction": "increase", "value_range": None, "failure_condition": "not increase"}]},
        {"hypothesis_id": "h2", "mechanism_key": "m2", "mechanism": "public mechanism two", "intervention": "public",
         "elimination_condition": "x does increase", "predictions": [{"prediction_id": "p2", "discriminator_id": "d",
            "observable": "x", "direction": "decrease", "value_range": None, "failure_condition": "not decrease"}]},
        {"hypothesis_id": "h3", "mechanism_key": "m3", "mechanism": "public mechanism three", "intervention": "public",
         "elimination_condition": "x is unchanged", "predictions": [{"prediction_id": "p3", "discriminator_id": "d",
            "observable": "x", "direction": "unchanged", "value_range": None, "failure_condition": "not unchanged"}]},
    ]}


def _model(seen: list[dict], *, malformed_plan: bool = False, fail_solver: bool = False):
    def call(request: FrozenRecord) -> FrozenRecord:
        body = request.data(); seen.append(body)
        encoded = request.encoded
        assert all(marker not in encoded for marker in ('"arm_id"', '"enabled"', '"control"', '"truth"', '"contrast"', '"candidate_package"'))
        slot = body["slot"]
        if slot == "m4_plan":
            return FrozenRecord.from_dict({"invalid": True}) if malformed_plan else FrozenRecord.from_dict(_plan())
        if slot in {"m5_mechanism", "m5_measurement"}:
            return FrozenRecord.from_dict({"assessment": "concern", "evidence_refs": [], "counterexamples": [], "uncertainty": "unknown"})
        if slot == "analysis_program":
            if fail_solver:
                raise RuntimeError("synthetic solver transport failure")
            artifacts = body["module_context"]["public_artifacts"]
            assert artifacts == [{"artifact": artifacts[0]["artifact"], "container_path": "/input/public_csv"}]
            return FrozenRecord.from_dict({"analysis": "mean public x", "program":
                "import csv\nwith open('/input/public_csv', newline='') as f:\n rows=list(csv.DictReader(f))\nprint(sum(float(r['x']) for r in rows)/len(rows))"})
        assert slot == "final_answer"
        assert body["execution_feedback"][0]["stdout"].strip() == "2.0"
        return FrozenRecord.from_dict({"objective_digest": body["module_context"]["required_objective_digest"],
            "outcome": "unknown", "evidence_ids": [], "conclusion": "The public mean is 2.0.", "programme_complete": False})
    return call


def _run(panel, cell, catalogue, root: Path, model):
    public = root / "public"; public.mkdir(parents=True, exist_ok=True)
    source = public / "public.csv"; source.write_text("x\n1\n3\n", encoding="utf-8")
    sidecar = root / cell.identity.benchmark / cell.arm_id; sidecar.mkdir(parents=True)
    result = run_m4_m5_combination_benchmark_cell(panel=panel, cell=cell, task=catalogue.tasks[cell.task_digest],
        scenario=catalogue.scenarios[cell.key], package=catalogue.packages[cell.runtime_arm.content_hash],
        objective=FrozenRecord.from_dict({"objective": "synthetic M4 M5 combination"}), sidecar=sidecar,
        public_inputs={"public_csv": source}, image=IMAGE, broker=DockerExecutionBroker([public, sidecar]),
        model=model, audit_verifier=_audit())
    return result


def _rewrite_trace(path: Path, change) -> str:
    """Apply an adversarial trace edit while retaining a valid hash chain."""
    events = [FrozenRecord(line).data() for line in path.read_text(encoding="utf-8").splitlines()]
    change(events)
    previous, encoded = None, []
    for sequence, event in enumerate(events):
        event["sequence"], event["previous"] = sequence, previous
        frozen = FrozenRecord.from_dict(event)
        encoded.append(frozen.encoded)
        previous = frozen.content_hash
    path.write_text("\n".join(encoded) + "\n", encoding="utf-8")
    return previous


def _alternate_plan():
    plan = _plan()
    plan["question"] = "Which other public mechanism explains x?"
    return plan


def _replace_joint_in_trace(path: Path, joint: FrozenRecord) -> str:
    def change(events):
        event = next(item for item in events if item["stage"] == "combination_mechanism")
        event["data"]["joint"], event["data"]["joint_digest"] = joint.data(), joint.content_hash
    return _rewrite_trace(path, change)


def test_full_two_benchmark_four_arm_grid_uses_one_session_real_modules_and_docker(tmp_path: Path):
    catalogue = _catalogue(); panel = catalogue.panels["pair:M4+M5"]
    rows, results = [], []
    for cell in panel.cells:
        seen: list[dict] = []
        result = _run(panel, cell, catalogue, tmp_path / cell.identity.benchmark / cell.arm_id, _model(seen))
        assert result.runtime.status == "succeeded" and result.solver is not None
        assert result.solver.session.sidecar == result.runtime.trace_path.parent
        assert [row["slot"] for row in seen] == ["m4_plan", "m5_mechanism", "m5_measurement", "analysis_program", "final_answer"]
        assert result.solver.execution is not None and result.solver.execution.status == "succeeded"
        argv = result.solver.execution.record.data()["argv"]
        assert any(value.endswith(":/input/public_csv:ro") for value in argv)
        log_bytes = {name: (result.runtime.trace_path.parent / name).read_bytes()
                     for name in ("predictions.jsonl", "reviews.jsonl")}
        verified = verify_m4_m5_combination_benchmark_cell(result, panel=panel, task=catalogue.tasks[cell.task_digest],
            scenario=catalogue.scenarios[cell.key], package=catalogue.packages[cell.runtime_arm.content_hash])
        assert verified.data()["engineering_verified"] is True
        assert log_bytes == {name: (result.runtime.trace_path.parent / name).read_bytes()
                             for name in ("predictions.jsonl", "reviews.jsonl")}
        joint = result.joint_mechanism.data()
        enabled = set(cell.runtime_arm.data()["enabled"])
        assert (joint["prediction_plan"] is not None) is ("M4" in enabled)
        assert (joint["revealed_review"] is not None) is ("M5" in enabled)
        m4 = seen[0]["module_context"]
        assert set(m4) == {"panel_cell", "public_task", "mechanism_phase"}
        assert m4["public_task"] == catalogue.tasks[cell.task_digest].data()
        assert all("review_id" not in request["module_context"] for request in seen[1:3])
        rows.append(result.runtime); results.append(result)
    assert len(results) == 8
    assert CombinationPanelVerifier().verify(panel, rows).engineering_verified is True
    values = {"00": 0.0, "10": 0.0, "01": 0.0, "11": 2.0}
    scored = [ScientificScorerReceipt(row.cell_key, FrozenRecord.from_dict({"schema": "independent-scored-cell-v1",
        "runtime_trace_digest": row.trace_digest, "scorer_digest": next(cell.scorer_digest for cell in panel.cells if cell.key == row.cell_key),
        "metric": {"value": values[row.cell_key[-1]], "direction": "higher_better", "value_range": [0.0, 2.0], "scale": "unit"}})) for row in rows]
    contrast = estimate_grouped_contrast(panel, runtime=rows, scorer_receipts=scored,
        verifier=CombinationPanelVerifier(scorer_verifier=lambda *_: None)).data()
    assert all(item["mean"] == 2.0 for item in contrast["benchmark_estimates"].values())
    with pytest.raises(ContractError, match="coverage mismatch"):
        CombinationPanelVerifier().verify(panel, rows[:-1])


def test_malformed_module_solver_failure_and_other_obligations_fail_closed(tmp_path: Path):
    catalogue = _catalogue(); panel = catalogue.panels["pair:M4+M5"]
    m4_on = next(cell for cell in panel.cells if cell.arm_id == "10")
    malformed = _run(panel, m4_on, catalogue, tmp_path / "malformed", _model([], malformed_plan=True))
    assert malformed.runtime.status == "failed" and malformed.solver is None
    PanelReceiptVerifier()._verify_runtime(malformed.runtime, m4_on)
    assert verify_m4_m5_combination_benchmark_cell(malformed, panel=panel, task=catalogue.tasks[m4_on.task_digest],
        scenario=catalogue.scenarios[m4_on.key], package=catalogue.packages[m4_on.runtime_arm.content_hash]).data()["engineering_verified"] is True
    with pytest.raises(ContractError):
        verify_m4_m5_combination_benchmark_cell(
            replace(malformed, runtime=replace(malformed.runtime, status="succeeded", failure_reason=None)),
            panel=panel, task=catalogue.tasks[m4_on.task_digest], scenario=catalogue.scenarios[m4_on.key],
            package=catalogue.packages[m4_on.runtime_arm.content_hash])
    calls: list[dict] = []
    two_branch = _plan(); two_branch["branches"] = two_branch["branches"][:2]
    failed_after_one = _run(panel, m4_on, catalogue, tmp_path / "two-branches", lambda request: (
        calls.append(request.data()) or FrozenRecord.from_dict(two_branch)))
    assert failed_after_one.runtime.status == "failed" and failed_after_one.solver is None
    assert [call["slot"] for call in calls] == ["m4_plan"]
    m5_on = next(cell for cell in panel.cells if cell.arm_id == "01")
    solver_failed = _run(panel, m5_on, catalogue, tmp_path / "solver-failed", _model([], fail_solver=True))
    assert solver_failed.runtime.status == "failed" and solver_failed.solver is not None
    PanelReceiptVerifier()._verify_runtime(solver_failed.runtime, m5_on)
    with pytest.raises(ContractError, match="absent mechanism"):
        verify_m4_m5_combination_benchmark_cell(
            replace(solver_failed, joint_mechanism=None, solver=None), panel=panel,
            task=catalogue.tasks[m5_on.task_digest], scenario=catalogue.scenarios[m5_on.key],
            package=catalogue.packages[m5_on.runtime_arm.content_hash])
    unsupported_panel = catalogue.panels["pair:M1+M4"]; unsupported = unsupported_panel.cells[0]; calls = []
    with pytest.raises(ContractError, match="no actual combination executor"):
        _run(unsupported_panel, unsupported, catalogue, tmp_path / "unsupported", _model(calls))
    assert not calls


def test_verifier_rejects_forged_runtime_and_joint_bindings(tmp_path: Path):
    catalogue = _catalogue(); panel = catalogue.panels["pair:M4+M5"]; cell = next(c for c in panel.cells if c.arm_id == "11")
    result = _run(panel, cell, catalogue, tmp_path, _model([])); task=catalogue.tasks[cell.task_digest]; package=catalogue.packages[cell.runtime_arm.content_hash]; scenario=catalogue.scenarios[cell.key]
    for forged in (replace(result, runtime=replace(result.runtime, status="failed", failure_reason="forged")),
                   replace(result, runtime=replace(result.runtime, cell_key=("forged", *result.cell.key[1:]))),
                   replace(result, runtime=replace(result.runtime, output_digest="0" * 64)),
                   replace(result, joint_mechanism=None),
                   replace(result, joint_mechanism=None, runtime=replace(result.runtime, status="failed", failure_reason="forged"))):
        with pytest.raises(ContractError): verify_m4_m5_combination_benchmark_cell(forged,panel=panel,task=task,scenario=scenario,package=package)
    joint=result.joint_mechanism.data(); joint["module_response_digests"][0]="0"*64
    with pytest.raises(ContractError): verify_m4_m5_combination_benchmark_cell(replace(result,joint_mechanism=FrozenRecord.from_dict(joint)),panel=panel,task=task,scenario=scenario,package=package)
    assert result.solver is not None and result.solver.execution is not None and result.solver.answer is not None
    for forged_solver in (
        replace(result.solver, execution=replace(result.solver.execution, status="failed")),
        replace(result.solver, answer=FrozenRecord.from_dict({"other": "answer"})),
        replace(result.solver, status="execution_failed"),
    ):
        with pytest.raises(ContractError): verify_m4_m5_combination_benchmark_cell(replace(result, solver=forged_solver),panel=panel,task=task,scenario=scenario,package=package)


def test_verifier_rejects_rehashed_joint_reordering_and_artifact_substitution(tmp_path: Path):
    catalogue = _catalogue(); panel = catalogue.panels["pair:M4+M5"]
    cell = next(c for c in panel.cells if c.arm_id == "11")
    task, package, scenario = catalogue.tasks[cell.task_digest], catalogue.packages[cell.runtime_arm.content_hash], catalogue.scenarios[cell.key]
    result = _run(panel, cell, catalogue, tmp_path / "order", _model([]))
    path = result.runtime.trace_path
    def move_joint_early(events):
        joint_index = next(index for index, event in enumerate(events) if event["stage"] == "combination_mechanism")
        joint = events.pop(joint_index)
        third_request = [index for index, event in enumerate(events) if event["stage"] == "model_request"][2]
        events.insert(third_request, joint)
    digest = _rewrite_trace(path, move_joint_early)
    with pytest.raises(ContractError, match="not ordered"):
        verify_m4_m5_combination_benchmark_cell(replace(result, runtime=replace(result.runtime, trace_digest=digest)),panel=panel,task=task,scenario=scenario,package=package)

    result = _run(panel, cell, catalogue, tmp_path / "plan", _model([])); sidecar = result.runtime.trace_path.parent
    registry = PredictionRegistry(task.identity, storage_path=sidecar / "predictions.jsonl")
    (sidecar / "predictions.jsonl").unlink(); registry = PredictionRegistry(task.identity, storage_path=sidecar / "predictions.jsonl")
    alternative = registry.freeze(_alternate_plan()["question"], _alternate_plan()["branches"], budget_units=3)
    joint = result.joint_mechanism.data(); joint.update({"prediction_plan": alternative.payload.data(), "prediction_plan_id": alternative.plan_id, "prediction_plan_digest": alternative.payload.content_hash})
    forged_joint = FrozenRecord.from_dict(joint); digest = _replace_joint_in_trace(result.runtime.trace_path, forged_joint)
    with pytest.raises(ContractError, match="actual M4 model response"):
        verify_m4_m5_combination_benchmark_cell(replace(result, joint_mechanism=forged_joint, runtime=replace(result.runtime, trace_digest=digest)),panel=panel,task=task,scenario=scenario,package=package)

    result = _run(panel, cell, catalogue, tmp_path / "review", _model([])); sidecar = result.runtime.trace_path.parent
    (sidecar / "reviews.jsonl").unlink(); reviews = ReviewEngine(task.identity, storage_path=sidecar / "reviews.jsonl")
    review = reviews.open(task_binding=task.content_hash, evidence_snapshot=scenario.content_hash, roles=[
        {"role_id": "mechanism", "question": "Identify a plausible public mechanism and an observation that could falsify it."},
        {"role_id": "measurement", "question": "Identify a public measurement risk and an observation that could distinguish it."},
    ], budget_units=2)
    altered = {"assessment": "accept", "evidence_refs": [], "counterexamples": [], "uncertainty": "alternate"}
    for role in ("mechanism", "measurement"):
        reviews.submit(review.review_id, role_id=role, reviewer_id="m4m5-" + role, response=altered, cost_units=1)
    revealed = FrozenRecord.from_dict({"review_id": review.review_id, "submissions": [item.data() for item in reviews.reveal(review.review_id)]})
    joint = result.joint_mechanism.data(); joint.update({"review_id": review.review_id, "revealed_review": revealed.data(), "review_digest": revealed.content_hash})
    forged_joint = FrozenRecord.from_dict(joint); digest = _replace_joint_in_trace(result.runtime.trace_path, forged_joint)
    with pytest.raises(ContractError, match="actual sealed model responses"):
        verify_m4_m5_combination_benchmark_cell(replace(result, joint_mechanism=forged_joint, runtime=replace(result.runtime, trace_digest=digest)),panel=panel,task=task,scenario=scenario,package=package)

