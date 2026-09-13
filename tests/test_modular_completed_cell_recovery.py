"""Read-only recovery from real journals; no paid model transport."""
from dataclasses import replace
import hashlib
from pathlib import Path
import subprocess

import pytest

from research_loop.modular.benchmark_cell import restore_completed_benchmark_cell, run_benchmark_cell
from research_loop.modular.benchmark_solver import CompletedSolverSession
from research_loop.modular.benchmarks.execution import DockerExecutionBroker
from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.runtime import RunSession
from research_loop.ontology import ContractError
from test_modular_benchmark_cell import IMAGE, _audit, _material, _model


def _snapshot(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("outcome", ["succeeded", "failed", "mechanism_failed"])
def test_recovery_replays_original_success_and_failures_without_writing_or_execution(tmp_path, monkeypatch, outcome):
    task, scenario, package, cell = _material("discoverybench", "Q3.1")
    public = tmp_path / "public.csv"; public.write_text("x\n1\n3\n", encoding="utf-8")
    mechanism, solver = tmp_path / "mechanism", tmp_path / "solver"
    mechanism.mkdir(); solver.mkdir()
    calls = []
    model = _model(calls)
    if outcome == "mechanism_failed":
        def model(_):
            raise ContractError("synthetic model failure")
    broker = DockerExecutionBroker([tmp_path])
    if outcome == "failed":
        broker = DockerExecutionBroker([tmp_path], runner=lambda argv, **kwargs:
            subprocess.CompletedProcess(argv, 7, b"", b"synthetic failure"))
        original_model = model
        def model(request):
            if request.data()["slot"] == "final_answer":
                return FrozenRecord.from_dict({"objective_digest": request.data()["module_context"]["required_objective_digest"],
                    "outcome": "unknown", "evidence_ids": [], "conclusion": "Execution failed.", "programme_complete": False})
            return original_model(request)
    result = run_benchmark_cell(cell=cell, task=task, scenario=scenario, package=package,
        objective=FrozenRecord.from_dict({"question": "mean"}), mechanism_sidecar=mechanism, solver_sidecar=solver,
        public_inputs={"public_csv": public}, image=IMAGE, broker=broker, model=model, audit_verifier=_audit())
    before = _snapshot(tmp_path)
    def forbidden(*args, **kwargs):
        pytest.fail("recovery attempted to construct or execute a live session")
    monkeypatch.setattr(RunSession, "__init__", forbidden)
    monkeypatch.setattr(DockerExecutionBroker, "__init__", forbidden)
    kwargs = dict(cell=cell, task=task, scenario=scenario, package=package, runtime=result.mechanism.runtime,
        linked_receipt=result.receipt, solver_sidecar=solver if result.solver else None,
        public_inputs={"public_csv": public})
    recovered = restore_completed_benchmark_cell(**kwargs)
    assert recovered.receipt == result.receipt and recovered.status == result.status
    assert recovered.mechanism.call_plan.data()["original_call_plan"] == "not_persisted"
    assert _snapshot(tmp_path) == before
    if recovered.solver:
        assert isinstance(recovered.solver.session, CompletedSolverSession)
        assert recovered.solver.record == result.solver.record
        assert not hasattr(recovered.solver.session, "finish")
    assert recovered.status == {"succeeded": "linked_succeeded", "failed": "solver_execution_failed",
                                "mechanism_failed": "mechanism_failed"}[outcome]

    # Each mutation is restored exactly before testing the next one. Failures
    # are required before returning a signable scoring candidate.
    if outcome == "succeeded":
        for path in (public, solver / "analysis-1.py", solver / "trace.jsonl", mechanism / "trace.jsonl"):
            original = path.read_bytes()
            path.write_bytes(original + b"drift")
            with pytest.raises((ContractError, ValueError)):
                restore_completed_benchmark_cell(**kwargs)
            path.write_bytes(original)
        bad = result.receipt.data(); bad["status"] = "solver_execution_failed"
        with pytest.raises(ContractError):
            restore_completed_benchmark_cell(**{**kwargs, "linked_receipt": FrozenRecord.from_dict(bad)})
        with pytest.raises(ContractError):
            restore_completed_benchmark_cell(**{**kwargs, "runtime": replace(result.mechanism.runtime, output_digest="0" * 64)})
        assert _snapshot(tmp_path) == before
