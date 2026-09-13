"""Synthetic public end-to-end checks for linked mechanism and solver cells."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import subprocess

import pytest

from research_loop.modular import benchmark_cell
from research_loop.modular.benchmark_cell import run_benchmark_cell, verify_linked_benchmark_cell, verified_mechanism_provenance
from research_loop.modular.benchmark_solver import run_benchmark_solve
from research_loop.modular.benchmarks import BladeAdapter, DiscoveryBenchAdapter, DockerExecutionBroker
from research_loop.modular.combinations import default_compatibility
from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask
from research_loop.modular.experiments import ControllerInputs, registry, scenario
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
from research_loop.modular.panel_receipts import PanelCell
from research_loop.modular.runtime import AuditVerifier
from research_loop.ontology import ContractError


IMAGE = "research-benchmark-python@sha256:1433f0d223b0773b0d8c3184fa4ff6ab0a3891113442f1592d8d7e883d21a349"
SCORER = "f" * 64


def _task(benchmark: str) -> PublicTask:
    identity = DataIdentity(benchmark, "linked-synthetic", benchmark + ":linked", "v1", "split", "train")
    if benchmark == "blade":
        return BladeAdapter().prepare(identity, {"task_id": identity.task_id, "dataset_id": "public",
            "research_question": "What is the synthetic mean?", "data_schema": [{"name": "x", "dtype": "float"}]})
    return DiscoveryBenchAdapter().prepare(identity, {"task_id": identity.task_id, "question": "What is the synthetic mean?",
        "source_kind": "synthetic", "dataset": [{"name": "public.csv", "columns": [{"name": "x"}]}]})


def _material(benchmark: str, mechanism: str):
    task = _task(benchmark)
    spec = registry()[mechanism]
    variant = spec.variants[0]
    evidence = (FrozenRecord.from_dict({"schema": "q15-review-material-v1", "identity": task.identity.data(),
        "public_evidence": {"measurement": "public"}, "historical_summary": "synthetic public history"})
        if mechanism == "Q1.5" else FrozenRecord.from_dict({"evidence": "public"}))
    controlled = scenario(spec, variant, inputs=ControllerInputs(FrozenRecord.from_dict(task.data()), evidence,
        FrozenRecord.from_dict({"budget": "fixed"})))
    package = CandidatePackage.create(parent_digest=None,
        manifest=TrainingManifest.freeze([task.identity]), changes={"prompt": {"instructions": "linked synthetic train package"}}, search_cost=0)
    cell = PanelCell(mechanism, task.identity, "r1", variant, "base", default_compatibility("base").arm([]),
        task.content_hash, controlled.content_hash, package.digest, SCORER)
    return task, controlled, package, cell


def _audit() -> AuditVerifier:
    return AuditVerifier({"audit-a": b"a" * 32, "audit-b": b"b" * 32})


def _model(seen: list[dict]):
    def callback(request: FrozenRecord) -> FrozenRecord:
        row = request.data(); seen.append(row); slot = row["slot"]
        if slot == "analysis_program":
            provenance = row["module_context"]["mechanism_provenance"]
            assert provenance["responses"] and provenance["mechanism_stages"]
            return FrozenRecord.from_dict({"analysis": "calculate the public x mean", "program":
                "import csv\nwith open('/input/public_csv', newline='') as f:\n rows=list(csv.DictReader(f))\nprint(sum(float(r['x']) for r in rows)/len(rows))"})
        if slot == "final_answer":
            assert row["execution_feedback"][0]["stdout"].strip() == "2.0"
            return FrozenRecord.from_dict({"objective_digest": row["module_context"]["required_objective_digest"], "outcome": "unknown",
                "evidence_ids": [], "conclusion": "The synthetic mean is 2.0.", "programme_complete": False})
        if slot == "scenario":
            return FrozenRecord.from_dict({"question": "public mechanism", "budget_units": 3, "branches": [
                {"hypothesis_id": "h" + str(n), "mechanism_key": "m" + str(n), "mechanism": "mechanism", "intervention": "public",
                 "elimination_condition": "shared observation", "predictions": [{"prediction_id": "p" + str(n), "discriminator_id": "d",
                 "observable": "x", "direction": "decrease" if n == 1 else "increase", "value_range": None, "failure_condition": "not increase"}]} for n in range(3)]})
        if slot != "final":
            return FrozenRecord.from_dict({"assessment": "public concern", "evidence_refs": ["public"], "counterexamples": [], "uncertainty": "synthetic"})
        return FrozenRecord.from_dict({"objective_digest": row["module_context"]["required_objective_digest"], "outcome": "unknown",
            "evidence_ids": [], "conclusion": "mechanism candidate", "programme_complete": False})
    return callback


@pytest.mark.parametrize("benchmark", ["discoverybench", "blade"])
@pytest.mark.parametrize("mechanism", ["Q1.5", "Q3.1", "Q4.3"])
def test_linked_cell_uses_verified_mechanism_in_both_solver_calls_and_live_docker(tmp_path: Path, benchmark: str, mechanism: str) -> None:
    task, controlled, package, cell = _material(benchmark, mechanism)
    public = tmp_path / "public"; public.mkdir(); (public / "public.csv").write_text("x\n1\n3\n", encoding="utf-8")
    mechanism_dir, solver_dir = tmp_path / "mechanism", tmp_path / "solver"; mechanism_dir.mkdir(); solver_dir.mkdir()
    seen: list[dict] = []
    result = run_benchmark_cell(cell=cell, task=task, scenario=controlled, package=package,
        objective=FrozenRecord.from_dict({"question": "synthetic mean"}), mechanism_sidecar=mechanism_dir,
        solver_sidecar=solver_dir, public_inputs={"public_csv": public / "public.csv"}, image=IMAGE,
        broker=DockerExecutionBroker([public, solver_dir]), model=_model(seen), audit_verifier=_audit())
    assert result.status == "linked_succeeded" and result.solver is not None
    assert result.solver.execution is not None and result.solver.execution.status == "succeeded"
    assert result.solver.answer is not None and result.solver.answer.data()["conclusion"] == "The synthetic mean is 2.0."
    solver_requests = [row for row in seen if row["slot"] in {"analysis_program", "final_answer"}]
    assert len(solver_requests) == 2
    assert all(row["module_context"]["mechanism_provenance"] == result.provenance.data() for row in solver_requests)
    assert verify_linked_benchmark_cell(result, task=task, scenario=controlled, package=package).data()["engineering_verified"] is True


def test_linked_cell_keeps_mechanism_and_solver_failures_as_rows(tmp_path: Path) -> None:
    task, controlled, package, cell = _material("discoverybench", "Q3.1")
    public = tmp_path / "public"; public.mkdir(); (public / "public.csv").write_text("x\n1\n3\n", encoding="utf-8")
    def fail_mechanism(request: FrozenRecord) -> FrozenRecord:
        if request.data()["slot"] == "final": return FrozenRecord.from_dict({"bad": "candidate"})
        return _model([])(request)
    first = run_benchmark_cell(cell=cell, task=task, scenario=controlled, package=package, objective=FrozenRecord.from_dict({"q": "x"}),
        mechanism_sidecar=tmp_path / "m1", solver_sidecar=tmp_path / "s1", public_inputs={"public_csv": public / "public.csv"}, image=IMAGE,
        broker=DockerExecutionBroker([public, tmp_path]), model=fail_mechanism, audit_verifier=_audit())
    assert first.status == "mechanism_blocked" and first.solver is None
    assert verify_linked_benchmark_cell(first, task=task, scenario=controlled, package=package).data()["engineering_verified"] is True
    def fail_solver(request: FrozenRecord) -> FrozenRecord:
        if request.data()["slot"] == "analysis_program": raise RuntimeError("synthetic solver failure")
        return _model([])(request)
    second = run_benchmark_cell(cell=cell, task=task, scenario=controlled, package=package, objective=FrozenRecord.from_dict({"q": "x"}),
        mechanism_sidecar=tmp_path / "m2", solver_sidecar=tmp_path / "s2", public_inputs={"public_csv": public / "public.csv"}, image=IMAGE,
        broker=DockerExecutionBroker([public, tmp_path]), model=fail_solver, audit_verifier=_audit())
    assert second.status == "solver_analysis_model_failed" and second.solver is not None
    solver_calls = second.receipt.data()["solver_calls"]
    assert len(solver_calls) == 1 and solver_calls[0]["slot"] == "analysis_program"
    assert solver_calls[0]["status"] == "failed" and solver_calls[0]["error_type"] == "RuntimeError"
    assert verify_linked_benchmark_cell(second, task=task, scenario=controlled, package=package).data()["engineering_verified"] is True
    crashed = run_benchmark_cell(cell=cell, task=task, scenario=controlled, package=package, objective=FrozenRecord.from_dict({"q": "x"}),
        mechanism_sidecar=tmp_path / "m3", solver_sidecar=tmp_path / "s3", public_inputs={"public_csv": public / "public.csv"}, image=IMAGE,
        broker=DockerExecutionBroker([public, tmp_path]), model=lambda _: (_ for _ in ()).throw(RuntimeError("mechanism port failed")), audit_verifier=_audit())
    assert crashed.status == "mechanism_failed" and crashed.receipt.data()["mechanism_calls"][0]["status"] == "failed"


def test_verified_provenance_rejects_foreign_task_arm_package_and_tampering(tmp_path: Path) -> None:
    task, controlled, package, cell = _material("discoverybench", "Q3.1")
    public = tmp_path / "public"; public.mkdir(); (public / "public.csv").write_text("x\n1\n3\n", encoding="utf-8")
    result = run_benchmark_cell(cell=cell, task=task, scenario=controlled, package=package, objective=FrozenRecord.from_dict({"q": "x"}),
        mechanism_sidecar=tmp_path / "m", solver_sidecar=tmp_path / "s", public_inputs={"public_csv": public / "public.csv"}, image=IMAGE,
        broker=DockerExecutionBroker([public, tmp_path]), model=_model([]), audit_verifier=_audit())
    with pytest.raises(ContractError):
        verified_mechanism_provenance(cell=cell, task=_task("blade"), scenario=controlled, package=package, mechanism=result.mechanism)
    foreign_arm = PanelCell(cell.coverage_id, cell.identity, cell.replicate, cell.variant, "foreign", default_compatibility("base").arm(["M4"]), cell.task_digest, cell.scenario_digest, cell.package_digest, cell.scorer_digest)
    with pytest.raises(ContractError):
        verified_mechanism_provenance(cell=foreign_arm, task=task, scenario=controlled, package=package, mechanism=result.mechanism)
    other = CandidatePackage.create(parent_digest=None, manifest=TrainingManifest.freeze([task.identity]), changes={"memory": {"lesson": "other"}}, search_cost=0)
    with pytest.raises(ContractError):
        verified_mechanism_provenance(cell=cell, task=task, scenario=controlled, package=other, mechanism=result.mechanism)
    lines = result.mechanism.runtime.trace_path.read_text(encoding="utf-8").splitlines(); changed = FrozenRecord(lines[-1]).data(); changed["data"]["candidate_digest"] = "0" * 64
    result.mechanism.runtime.trace_path.write_text("\n".join([*lines[:-1], FrozenRecord.from_dict(changed).encoded]) + "\n", encoding="utf-8")
    with pytest.raises(ContractError):
        verified_mechanism_provenance(cell=cell, task=task, scenario=controlled, package=package, mechanism=result.mechanism)


def test_verifier_rejects_a_hash_consistent_solver_with_foreign_arm_and_objective(tmp_path: Path) -> None:
    task, controlled, package, cell = _material("discoverybench", "Q3.1")
    public = tmp_path / "public"; public.mkdir(); data = public / "public.csv"; data.write_text("x\n1\n3\n", encoding="utf-8")
    result = run_benchmark_cell(cell=cell, task=task, scenario=controlled, package=package, objective=FrozenRecord.from_dict({"q": "original"}),
        mechanism_sidecar=tmp_path / "mechanism", solver_sidecar=tmp_path / "solver", public_inputs={"public_csv": data}, image=IMAGE,
        broker=DockerExecutionBroker([public, tmp_path]), model=_model([]), audit_verifier=_audit())
    foreign_dir = tmp_path / "foreign"; foreign_dir.mkdir()
    foreign = run_benchmark_solve(task=task, public_inputs={"public_csv": data}, image=IMAGE, package_digest=package.digest,
        arm=default_compatibility("base").arm(["M4"]), objective=FrozenRecord.from_dict({"q": "foreign objective"}), sidecar=foreign_dir,
        broker=DockerExecutionBroker([public, foreign_dir], runner=lambda argv, **_: subprocess.CompletedProcess(argv, 0, b"2.0\n", b"")),
        model=_model([]), audit_verifier=_audit(), predecessor_context=result.provenance,
        panel_cell_binding=benchmark_cell._binding(cell), mechanism_provenance=result.provenance)
    forged = replace(result, solver=foreign, status="linked_succeeded")
    forged = replace(forged, receipt=benchmark_cell._receipt(cell, result.mechanism, foreign, result.provenance, forged.status))
    with pytest.raises(ContractError, match="solver lock"):
        verify_linked_benchmark_cell(forged, task=task, scenario=controlled, package=package)
