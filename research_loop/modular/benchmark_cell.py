"""Trace-bound composition of a real panel mechanism run and benchmark solve.

The wrapper is train-only engineering wiring.  It does not enrol itself in a
panel controller, invoke a scorer, or turn the two traces into scientific
acceptance.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

from research_loop.modular.benchmark_solver import BenchmarkSolveResult, CompletedSolverSession, run_benchmark_solve, verify_benchmark_solve_trace
from research_loop.modular.benchmarks.execution import DockerExecutionBroker, ExecutionReceipt, validate_artifact
from research_loop.modular.contracts import FrozenRecord, PublicTask
from research_loop.modular.modules.improvement import CandidatePackage
from research_loop.modular.panel_receipts import PanelCell, PanelReceiptVerifier, RuntimeReceipt, opaque_panel_cell_binding
from research_loop.modular.linked_public_projection import project_linked_public_context, verify_linked_public_context
from research_loop.modular.panel_runner import TrainCellResult, run_train_cell
from research_loop.modular.protocol_trace import verify_protocol_trace
from research_loop.modular.runtime import AuditVerifier
from research_loop.ontology import ContractError


ModelPort = Callable[[FrozenRecord], FrozenRecord]
_SUPPORTED_MECHANISMS = frozenset({"Q1.5", "Q3.1", "Q3.2", "Q4.3", "Q5.3", "Q8.2", "Q8.3"})


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
                       audit_verifier: AuditVerifier, timeout_seconds: int = 20,
                       retrieval_provider=None, retrieval_admission_port=None) -> LinkedBenchmarkCellResult:
    """Run a registered linked mechanism first, then solve from its trace.

    A failed mechanism remains an explicit row and does not call the solver.
    Solver failures are returned from ``run_benchmark_solve`` with their own
    terminal journal, so both failure classes remain in the denominator.
    """
    _validate_inputs(cell, task, scenario, package, objective, model)
    mechanism = run_train_cell(cell, task=task, scenario=scenario, package=package,
                               objective=objective, sidecar=mechanism_sidecar, model=model,
                               audit_verifier=audit_verifier, retrieval_provider=retrieval_provider,
                               retrieval_admission_port=retrieval_admission_port)
    if mechanism.runtime.status != "succeeded":
        return _result(cell, mechanism, None, None, "mechanism_" + mechanism.runtime.status)
    try:
        provenance = verified_mechanism_provenance(cell=cell, task=task, scenario=scenario,
                                                    package=package, mechanism=mechanism)
        public_projection = project_linked_public_context(provenance=provenance, cell=cell,
            task=task, scenario=scenario)
    except ContractError:
        # The preceding run exists but its receipt or public projection cannot
        # be used as solver context.  Keep the denominator row intact.
        return _result(cell, mechanism, None, None, "mechanism_receipt_rejected")
    opaque_binding = FrozenRecord.from_dict(opaque_panel_cell_binding(cell))
    solver = run_benchmark_solve(task=task, public_inputs=public_inputs, image=image,
        package_digest=package.digest, arm=cell.runtime_arm, objective=objective,
        sidecar=solver_sidecar, broker=broker, model=model, audit_verifier=audit_verifier,
        timeout_seconds=timeout_seconds, predecessor_context=public_projection,
        panel_cell_binding=opaque_binding, mechanism_provenance=public_projection)
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
              and event["data"].get("stage") in {"stage_1", "stage_7", "stage_9",
                                                   "operation_m4_control", "operation_m5_control",
                                                   "stage_0.5", "operation_m6_ordinary_baseline",
                                                   "prediction_artifacts"}]
    if not stages:
        raise ContractError("mechanism trace lacks an executed mechanism stage")
    calls = _model_calls(events)
    if not calls:
        raise ContractError("mechanism trace lacks model responses")
    mechanism_stages = [{"stage": event["data"]["stage"], "data": event["data"]} for event in stages]
    if cell.coverage_id in {"Q3.2", "Q5.3"}:
        from research_loop.modular.linked_prediction_projection import prediction_registry_observation
        mechanism_stages.append(prediction_registry_observation(mechanism.runtime.trace_path.parent))
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
        "mechanism_stages": mechanism_stages,
        "responses": calls,
    })


def restore_completed_benchmark_cell(*, cell: PanelCell, task: PublicTask, scenario: FrozenRecord,
                                    package: CandidatePackage, runtime: RuntimeReceipt,
                                    linked_receipt: FrozenRecord, solver_sidecar: Path | None,
                                    public_inputs: Mapping[str, Path]) -> LinkedBenchmarkCellResult:
    """Rehydrate closed execution evidence for scoring, without any execution port.

    The caller supplies the original frozen runtime and linked receipts. Every
    restored field is replayed against those receipts and the current artifact
    bytes. The old call plan was not persisted by the linked controller: the
    replacement field explicitly records recovery, never an invented old plan.
    This function writes nothing and has no model, Docker, scorer, or RunSession
    constructor. Original failures remain failures.
    """
    if not isinstance(runtime, RuntimeReceipt) or not isinstance(linked_receipt, FrozenRecord):
        raise ContractError("recovery requires original typed execution receipts")
    _validate_inputs(cell, task, scenario, package, FrozenRecord.from_dict({"purpose": "recovery"}), lambda _: None)
    PanelReceiptVerifier()._verify_runtime(runtime, cell)
    source = linked_receipt.data()
    mechanism = TrainCellResult(runtime, None, FrozenRecord.from_dict({
        "schema": "completed-linked-cell-recovery-v1", "cell_key": list(cell.key),
        "original_linked_receipt_digest": linked_receipt.content_hash,
        "original_call_plan": "not_persisted", "execution_repeated": False}))
    provenance = None
    solver = None
    if source.get("solver_trace_digest") is not None:
        if not isinstance(solver_sidecar, Path):
            raise ContractError("recovery lacks the original solver sidecar")
        trace_path = solver_sidecar / "trace.jsonl"
        verify_benchmark_solve_trace(trace_path, task)
        events = _events(trace_path)
        if FrozenRecord.from_dict(events[-1]).content_hash != source["solver_trace_digest"]:
            raise ContractError("recovery solver trace differs from the original receipt")
        lock = FrozenRecord.from_dict(events[0]["data"])
        state = _solver_journal_state(events)
        artifacts = tuple(validate_artifact(task.identity, name, path) for name, path in sorted(public_inputs.items()))
        declarations = [{"artifact": artifact.record.data(), "container_path": "/input/" + artifact.artifact_id}
                        for artifact in artifacts]
        analysis_requests = [event["data"]["request"] for event in events if event["stage"] == "model_request"
                             and event["data"]["request"]["slot"] == "analysis_program"]
        if analysis_requests and analysis_requests[0]["module_context"].get("public_artifacts") != declarations:
            raise ContractError("recovery public inputs differ from the original request")
        execution = state["execution"]
        if execution is not None:
            if execution.record.data().get("input_artifacts") != {a.artifact_id: a.record.data() for a in artifacts}:
                raise ContractError("recovery public inputs differ from executed input bytes")
            if execution.artifact is not None:
                program_path = solver_sidecar / "analysis-1.py"
                restored = validate_artifact(task.identity, "program", program_path)
                if restored.content_hash != execution.artifact.content_hash:
                    raise ContractError("recovery program differs from executed program bytes")
                if state["analysis"] is None or program_path.read_text(encoding="utf-8") != state["analysis"].data().get("program"):
                    raise ContractError("recovery program differs from the original model response")
        session = CompletedSolverSession(task, lock, FrozenRecord.from_dict(lock.data()["objective"]), solver_sidecar)
        solver = BenchmarkSolveResult(session, artifacts, state["analysis"], execution,
                                      state["answer"], state["decision"], state["status"])
        provenance = verified_mechanism_provenance(cell=cell, task=task, scenario=scenario,
                                                   package=package, mechanism=mechanism)
    elif solver_sidecar is not None:
        raise ContractError("recovery cannot attach solver material absent from the original receipt")
    result = LinkedBenchmarkCellResult(cell, mechanism, solver, provenance, linked_receipt, source.get("status"))
    verify_linked_benchmark_cell(result, task=task, scenario=scenario, package=package)
    return result


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
        if result.mechanism.runtime.status == "succeeded":
            if result.status != "mechanism_receipt_rejected" or result.provenance is not None:
                raise ContractError("mechanism-only result requires a reproducible receipt rejection after a successful precursor")
            try:
                expected = verified_mechanism_provenance(cell=result.cell, task=task, scenario=scenario,
                    package=package, mechanism=result.mechanism)
                public_projection = project_linked_public_context(provenance=expected, cell=result.cell,
                    task=task, scenario=scenario)
                verify_linked_public_context(projection=public_projection, provenance=expected,
                    cell=result.cell, task=task, scenario=scenario)
            except ContractError:
                pass
            else:
                raise ContractError("mechanism-only receipt rejection cannot be reproduced from the journal")
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
        public_projection = project_linked_public_context(provenance=expected, cell=result.cell,
            task=task, scenario=scenario)
        verify_linked_public_context(projection=public_projection, provenance=expected,
            cell=result.cell, task=task, scenario=scenario)
        opaque_binding = opaque_panel_cell_binding(result.cell)
        if len(requests) and any(request.get("module_context", {}).get("panel_cell") != opaque_binding
                                 or request.get("module_context", {}).get("mechanism_provenance") != public_projection.data()
                                 or request.get("module_context", {}).get("predecessor_context") != public_projection.data()
                                 for request in requests):
            raise ContractError("solver requests do not carry the verified public mechanism context")
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
        raise ContractError("linked benchmark cell supports train Q1.5, Q3.1, or Q4.3 only")
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
        if stage == "model_request" and data["request"]["slot"] in {"analysis_program", "final_answer"}:
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
