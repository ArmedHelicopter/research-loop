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
from research_loop.modular.benchmarks.execution import DockerExecutionBroker, ExecutionReceipt
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
        terminal = _events(result.mechanism.runtime.trace_path)[-1]["stage"]
        expected = "mechanism_" + result.mechanism.runtime.status
        if result.status == "mechanism_receipt_rejected":
            if result.mechanism.runtime.status != "succeeded" or result.provenance is not None:
                raise ContractError("mechanism receipt rejection does not match a successful precursor")
        elif result.provenance is not None or result.status != expected or terminal not in {"model_failure", "driver_failure", "controller_failure", "final_decision"}:
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
        mechanism_lock = _events(result.mechanism.runtime.trace_path)[0]["data"]
        state = _solver_journal_state(solver_events)
        lock = solver_events[0]["data"]
        if (lock.get("identity") != result.cell.identity.data() or lock.get("task_digest") != result.cell.task_digest
                or lock.get("package_digest") != result.cell.package_digest or lock.get("arm") != result.cell.runtime_arm.data()
                or lock.get("objective") != mechanism_lock.get("objective")):
            raise ContractError("solver lock does not bind the mechanism cell task, package, arm, and objective")
        if (result.solver.session.task.identity != result.cell.identity
                or result.solver.session.task.content_hash != result.cell.task_digest
                or result.solver.session.lock.data() != lock
                or result.solver.session.objective.data() != lock["objective"]):
            raise ContractError("solver result session drifts from its journal lock")
        _compare_solver_result(result.solver, state)
        derived_status = "linked_succeeded" if state["status"] == "execution_succeeded" else "solver_" + state["status"]
        if result.status != derived_status:
            raise ContractError("linked result status is not derived from the solver journal")
        requests = [event["data"]["request"] for event in solver_events if event["stage"] == "model_request"]
        binding, provenance = _binding(result.cell).data(), result.provenance.data()
        if len(requests) and any(request.get("module_context", {}).get("panel_cell") != binding
                                 or request.get("module_context", {}).get("mechanism_provenance") != provenance
                                 or request.get("module_context", {}).get("predecessor_context") != provenance
                                 for request in requests):
            raise ContractError("solver requests do not carry the verified mechanism context")
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
                          "response": response.data(), "status": "responded"})
        elif event["stage"] == "model_failure":
            request_digest = event["data"]["request_digest"]
            request = pending.pop(request_digest, None)
            if request is None:
                raise ContractError("failure has no request while extracting model calls")
            calls.append({"slot": request["slot"], "request_digest": request_digest,
                          "request": request, "status": "failed",
                          "error_type": event["data"]["error_type"]})
    return calls


def _solver_journal_state(events: list[dict]) -> dict:
    """Derive every mutable solver result field from the hash-chained journal."""
    requests, responses, execution = {}, {}, None
    for event in events:
        stage, data = event["stage"], event["data"]
        if stage == "model_request":
            requests[data["request_digest"]] = data["request"]
        elif stage == "model_response":
            responses[data["request_digest"]] = FrozenRecord.from_dict(data["response"])
        elif stage == "execution_result":
            execution = ExecutionReceipt.parse(data["receipt"])
    terminal = events[-1]
    terminal_stage, terminal_data = terminal["stage"], terminal["data"]
    analysis = next((responses[key] for key, request in requests.items()
                     if request["slot"] == "analysis_program" and key in responses), None)
    answer = next((responses[key] for key, request in requests.items()
                    if request["slot"] == "final_answer" and key in responses), None)
    decision = FrozenRecord.from_dict(terminal_data) if terminal_stage == "final_decision" else None
    if terminal_stage == "final_decision" and execution is not None:
        status = "execution_" + execution.status
    elif terminal_stage == "execution_terminal" and execution is not None:
        status = "execution_" + execution.status
    elif terminal_stage == "execution_failure":
        status = "execution_setup_failed"
    elif terminal_stage == "model_failure":
        request = requests.get(terminal_data["request_digest"], {})
        status = "analysis_model_failed" if request.get("slot") == "analysis_program" else "answer_model_failed"
    elif terminal_stage == "driver_failure":
        request = requests.get(terminal_data["request_digest"], {})
        status = "analysis_rejected" if request.get("slot") == "analysis_program" else "answer_rejected"
    elif terminal_stage == "controller_failure":
        status = {"InputArtifactDrift": "input_artifact_drift", "ExecutionProgramDrift": "execution_program_drift"}.get(
            terminal_data.get("error_type"), "input_preflight_failed" if not requests else "execution_setup_failed")
    else:
        raise ContractError("solver journal has no recognized terminal state")
    return {"status": status, "analysis": analysis, "execution": execution, "answer": answer,
            "decision": decision, "calls": len(requests)}


def _compare_solver_result(solver: BenchmarkSolveResult, state: dict) -> None:
    for field in ("analysis", "execution", "answer", "decision"):
        actual, expected = getattr(solver, field), state[field]
        if (actual is None) != (expected is None):
            raise ContractError("solver result omits or invents journal material")
        if actual is not None and actual.content_hash != expected.content_hash:
            raise ContractError("solver result material does not match its journal")
    if solver.status != state["status"]:
        raise ContractError("solver result status is not derived from its journal")


def _result(cell: PanelCell, mechanism: TrainCellResult, solver: BenchmarkSolveResult | None,
            provenance: FrozenRecord | None, status: str) -> LinkedBenchmarkCellResult:
    return LinkedBenchmarkCellResult(cell, mechanism, solver, provenance,
        _receipt(cell, mechanism, solver, provenance, status), status)


def _receipt(cell: PanelCell, mechanism: TrainCellResult, solver: BenchmarkSolveResult | None,
             provenance: FrozenRecord | None, status: str) -> FrozenRecord:
    mechanism_events = _events(mechanism.runtime.trace_path)
    solver_events = _events(solver.session.sidecar / "trace.jsonl") if solver else []
    solver_state = _solver_journal_state(solver_events) if solver_events else None
    return FrozenRecord.from_dict({"schema": "linked-benchmark-cell-receipt-v1", "cell_key": list(cell.key),
        "identity": cell.identity.data(), "task_digest": cell.task_digest,
        "scenario_digest": cell.scenario_digest, "package_digest": cell.package_digest,
        "arm": cell.runtime_arm.data(), "status": status,
        "mechanism_trace_digest": mechanism.runtime.trace_digest,
        "mechanism_status": mechanism.runtime.status,
        "mechanism_calls": _model_calls(mechanism_events),
        "mechanism_provenance_digest": provenance.content_hash if provenance else None,
        "solver_trace_digest": FrozenRecord.from_dict(solver_events[-1]).content_hash if solver_events else None,
        "solver_status": solver_state["status"] if solver_state else None,
        "solver_calls": _model_calls(solver_events),
        "execution": solver_state["execution"].data() if solver_state and solver_state["execution"] else None,
        "scientific_effect": "not_measured"})
