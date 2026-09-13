"""Trace-bound composition of a real panel mechanism run and benchmark solve.

The wrapper is train-only engineering wiring.  It does not enrol itself in a
panel controller, invoke a scorer, or turn the two traces into scientific
acceptance.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

from research_loop.modular.benchmark_solver import BenchmarkSolveResult, run_benchmark_solve, verify_benchmark_solve_trace
from research_loop.modular.benchmarks.execution import DockerExecutionBroker
from research_loop.modular.contracts import FrozenRecord, PublicTask
from research_loop.modular.modules.improvement import CandidatePackage
from research_loop.modular.panel_receipts import PanelCell, PanelReceiptVerifier
from research_loop.modular.panel_runner import TrainCellResult, run_train_cell
from research_loop.modular.protocol_trace import verify_protocol_trace
from research_loop.modular.runtime import AuditVerifier
from research_loop.ontology import ContractError


ModelPort = Callable[[FrozenRecord], FrozenRecord]
_SUPPORTED_MECHANISMS = frozenset({"Q3.1", "Q4.3"})


@dataclass(frozen=True)
class LinkedBenchmarkCellResult:
    """One denominator row containing the mechanism and solver evidence."""

    cell: PanelCell
    mechanism: TrainCellResult
    solver: BenchmarkSolveResult | None
    provenance: FrozenRecord | None
    receipt: FrozenRecord
    status: str


def run_benchmark_cell(*, cell: PanelCell, task: PublicTask, scenario: FrozenRecord,
                       package: CandidatePackage, objective: FrozenRecord,
                       mechanism_sidecar: Path, solver_sidecar: Path,
                       public_inputs: Mapping[str, Path], image: str,
                       broker: DockerExecutionBroker, model: ModelPort,
                       audit_verifier: AuditVerifier, timeout_seconds: int = 20) -> LinkedBenchmarkCellResult:
    """Run the closed Q3.1/Q4.3 mechanism first, then solve from its trace.

    A failed mechanism remains an explicit row and does not call the solver.
    Solver failures are returned from ``run_benchmark_solve`` with their own
    terminal journal, so both failure classes remain in the denominator.
    """
    _validate_inputs(cell, task, scenario, package, objective, model)
    mechanism = run_train_cell(cell, task=task, scenario=scenario, package=package,
                               objective=objective, sidecar=mechanism_sidecar, model=model,
                               audit_verifier=audit_verifier)
    binding = _binding(cell)
    if mechanism.runtime.status != "succeeded":
        return _result(cell, mechanism, None, None, "mechanism_" + mechanism.runtime.status)
    try:
        provenance = verified_mechanism_provenance(cell=cell, task=task, scenario=scenario,
                                                    package=package, mechanism=mechanism)
    except ContractError:
        # The preceding run exists but its receipt cannot be used as context.
        return _result(cell, mechanism, None, None, "mechanism_receipt_rejected")
    solver = run_benchmark_solve(task=task, public_inputs=public_inputs, image=image,
        package_digest=package.digest, arm=cell.runtime_arm, objective=objective,
        sidecar=solver_sidecar, broker=broker, model=model, audit_verifier=audit_verifier,
        timeout_seconds=timeout_seconds, predecessor_context=provenance,
        panel_cell_binding=binding, mechanism_provenance=provenance)
    status = "linked_succeeded" if solver.status == "execution_succeeded" else "solver_" + solver.status
    return _result(cell, mechanism, solver, provenance, status)


def verified_mechanism_provenance(*, cell: PanelCell, task: PublicTask, scenario: FrozenRecord,
                                  package: CandidatePackage, mechanism: TrainCellResult) -> FrozenRecord:
    """Extract response material only after replaying the real precursor trace."""
    _validate_inputs(cell, task, scenario, package, FrozenRecord.from_dict({"purpose": "binding"}), lambda _: FrozenRecord.from_dict({}))
    if not isinstance(mechanism, TrainCellResult) or mechanism.runtime.status != "succeeded":
        raise ContractError("linked solve requires a successful mechanism runtime receipt")
    # This is the existing panel verifier, including common protocol replay,
    # lock/task/package/arm checks, and model-request cell binding checks.
    PanelReceiptVerifier()._verify_runtime(mechanism.runtime, cell)
    events = _events(mechanism.runtime.trace_path)
    if FrozenRecord.from_dict(events[-1]).content_hash != mechanism.runtime.trace_digest:
        raise ContractError("mechanism trace digest differs from its runtime receipt")
    stages = [event for event in events if event["stage"] == "modular_workflow"
              and event["data"].get("stage") in {"stage_1", "stage_7", "operation_m4_control", "operation_m5_control"}]
    if not stages:
        raise ContractError("mechanism trace lacks an executed mechanism stage")
    calls = _model_calls(events)
    if not calls:
        raise ContractError("mechanism trace lacks model responses")
    return FrozenRecord.from_dict({
        "schema": "verified-mechanism-provenance-v1",
        "panel_cell": _binding(cell).data(),
        "identity": task.identity.data(),
        "task_digest": task.content_hash,
        "scenario_digest": scenario.content_hash,
        "package_digest": package.digest,
        "arm": cell.runtime_arm.data(),
        "runtime_trace_digest": mechanism.runtime.trace_digest,
        "runtime_output_digest": mechanism.runtime.output_digest,
        "mechanism_stages": [{"stage": event["data"]["stage"], "data": event["data"]} for event in stages],
        "responses": calls,
    })


def verify_linked_benchmark_cell(result: LinkedBenchmarkCellResult, *, task: PublicTask,
                                 scenario: FrozenRecord, package: CandidatePackage) -> FrozenRecord:
    """Replay both journals and prove the same verified provenance reached both calls."""
    if not isinstance(result, LinkedBenchmarkCellResult):
        raise ContractError("linked result has an invalid type")
    _validate_inputs(result.cell, task, scenario, package, FrozenRecord.from_dict({"purpose": "binding"}), lambda _: FrozenRecord.from_dict({}))
    PanelReceiptVerifier()._verify_runtime(result.mechanism.runtime, result.cell)
    if result.solver is None:
        if result.provenance is not None or not result.status.startswith("mechanism_"):
            raise ContractError("mechanism-only linked result has contradictory solver material")
    else:
        if result.provenance is None:
            raise ContractError("solver result lacks verified mechanism provenance")
        expected = verified_mechanism_provenance(cell=result.cell, task=task, scenario=scenario,
            package=package, mechanism=result.mechanism)
        if expected.content_hash != result.provenance.content_hash:
            raise ContractError("linked mechanism provenance is not the verified precursor trace")
        solver_trace = verify_benchmark_solve_trace(result.solver.session.sidecar / "trace.jsonl", task)
        solver_events = _events(result.solver.session.sidecar / "trace.jsonl")
        requests = [event["data"]["request"] for event in solver_events if event["stage"] == "model_request"]
        binding, provenance = _binding(result.cell).data(), result.provenance.data()
        if len(requests) and any(request.get("module_context", {}).get("panel_cell") != binding
                                 or request.get("module_context", {}).get("mechanism_provenance") != provenance
                                 or request.get("module_context", {}).get("predecessor_context") != provenance
                                 for request in requests):
            raise ContractError("solver requests do not carry the verified mechanism context")
        if result.solver.execution is not None and result.solver.execution.identity != task.identity:
            raise ContractError("solver execution receipt has foreign task identity")
        if result.receipt.data().get("solver_trace_digest") != solver_trace.data()["trace_digest"]:
            raise ContractError("linked receipt has a solver trace digest mismatch")
    expected_receipt = _receipt(result.cell, result.mechanism, result.solver, result.provenance, result.status)
    if expected_receipt.content_hash != result.receipt.content_hash:
        raise ContractError("linked receipt content does not match its journals")
    return FrozenRecord.from_dict({"schema": "linked-benchmark-cell-verification-v1",
        "cell_key": list(result.cell.key), "status": result.status,
        "receipt_digest": result.receipt.content_hash, "engineering_verified": True,
        "scientific_effect": "not_measured"})


def _validate_inputs(cell: PanelCell, task: PublicTask, scenario: FrozenRecord, package: CandidatePackage,
                     objective: FrozenRecord, model: ModelPort) -> None:
    if not isinstance(cell, PanelCell) or cell.coverage_id not in _SUPPORTED_MECHANISMS or cell.identity.domain != "train":
        raise ContractError("linked benchmark cell supports train Q3.1 or Q4.3 only")
    if not isinstance(task, PublicTask) or task.identity != cell.identity or task.content_hash != cell.task_digest:
        raise ContractError("linked benchmark cell task does not bind the panel cell")
    if not isinstance(scenario, FrozenRecord) or scenario.content_hash != cell.scenario_digest:
        raise ContractError("linked benchmark cell scenario does not bind the panel cell")
    if not isinstance(package, CandidatePackage) or package.digest != cell.package_digest:
        raise ContractError("linked benchmark cell package does not bind the panel cell")
    if not isinstance(objective, FrozenRecord) or not callable(model):
        raise ContractError("linked benchmark cell needs objective and model port")


def _binding(cell: PanelCell) -> FrozenRecord:
    return FrozenRecord.from_dict({"schema": "benchmark-cell-binding-v1", "cell_key": list(cell.key),
        "identity": cell.identity.data(), "task_digest": cell.task_digest,
        "scenario_digest": cell.scenario_digest, "package_digest": cell.package_digest,
        "arm": cell.runtime_arm.data()})


def _events(path: Path) -> list[dict]:
    return [FrozenRecord(line).data() for line in path.read_text(encoding="utf-8").splitlines()]


def _model_calls(events: list[dict]) -> list[dict]:
    pending, calls = {}, []
    for event in events:
        if event["stage"] == "model_request":
            request = event["data"]["request"]
            pending[event["data"]["request_digest"]] = request
        elif event["stage"] == "model_response":
            request_digest = event["data"]["request_digest"]
            request = pending.pop(request_digest, None)
            if request is None:
                raise ContractError("response has no request while extracting mechanism provenance")
            response = FrozenRecord.from_dict(event["data"]["response"])
            calls.append({"slot": request["slot"], "request_digest": request_digest,
                          "request": request, "response_digest": response.content_hash,
                          "response": response.data()})
    return calls


def _result(cell: PanelCell, mechanism: TrainCellResult, solver: BenchmarkSolveResult | None,
            provenance: FrozenRecord | None, status: str) -> LinkedBenchmarkCellResult:
    return LinkedBenchmarkCellResult(cell, mechanism, solver, provenance,
        _receipt(cell, mechanism, solver, provenance, status), status)


def _receipt(cell: PanelCell, mechanism: TrainCellResult, solver: BenchmarkSolveResult | None,
             provenance: FrozenRecord | None, status: str) -> FrozenRecord:
    mechanism_events = _events(mechanism.runtime.trace_path)
    solver_events = _events(solver.session.sidecar / "trace.jsonl") if solver else []
    return FrozenRecord.from_dict({"schema": "linked-benchmark-cell-receipt-v1", "cell_key": list(cell.key),
        "identity": cell.identity.data(), "task_digest": cell.task_digest,
        "scenario_digest": cell.scenario_digest, "package_digest": cell.package_digest,
        "arm": cell.runtime_arm.data(), "status": status,
        "mechanism_trace_digest": mechanism.runtime.trace_digest,
        "mechanism_status": mechanism.runtime.status,
        "mechanism_calls": _model_calls(mechanism_events),
        "mechanism_provenance_digest": provenance.content_hash if provenance else None,
        "solver_trace_digest": FrozenRecord.from_dict(solver_events[-1]).content_hash if solver_events else None,
        "solver_status": solver.status if solver else None,
        "solver_calls": _model_calls(solver_events),
        "execution": solver.execution.data() if solver and solver.execution else None,
        "scientific_effect": "not_measured"})
