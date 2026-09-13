"""Actual shared-session M4+M5 train combination execution.

This intentionally implements one registered pair only.  Other catalogue
obligations remain planned designs until they have an equally concrete module
executor; they are never simulated by a generic combination prompt.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

from research_loop.modular.benchmark_solver import BenchmarkSolveResult, run_benchmark_solve_in_session
from research_loop.modular.benchmark_cell import _solver_journal_state, _compare_solver_result
from research_loop.modular.benchmarks.execution import DockerExecutionBroker
from research_loop.modular.combination_panels import CombinationPanel
from research_loop.modular.contracts import FrozenRecord, PublicTask
from research_loop.modular.modules.improvement import CandidatePackage
from research_loop.modular.modules.predictions import PredictionRegistry
from research_loop.modular.modules.review import ReviewEngine
from research_loop.modular.panel_receipts import PanelCell, RuntimeReceipt, PanelReceiptVerifier
from research_loop.modular.panel_receipts import opaque_panel_cell_binding
from research_loop.modular.protocol_trace import verify_protocol_trace
from research_loop.modular.runtime import AuditVerifier, RunSession, verify_trace
from research_loop.modular.workflow import ModularWorkflow
from research_loop.ontology import ContractError


ModelPort = Callable[[FrozenRecord], FrozenRecord]
_PAIR = "pair:M4+M5"
_SLOTS = ("m4_plan", "m5_mechanism", "m5_measurement", "analysis_program", "final_answer")
_ROLES = (("mechanism", "Identify a plausible public mechanism and an observation that could falsify it."),
          ("measurement", "Identify a public measurement risk and an observation that could distinguish it."))


@dataclass(frozen=True)
class CombinationBenchmarkCellResult:
    cell: PanelCell
    runtime: RuntimeReceipt
    solver: BenchmarkSolveResult | None
    joint_mechanism: FrozenRecord | None


def run_m4_m5_combination_benchmark_cell(*, panel: CombinationPanel, cell: PanelCell,
                                         task: PublicTask, scenario: FrozenRecord,
                                         package: CandidatePackage, objective: FrozenRecord,
                                         sidecar: Path, public_inputs: Mapping[str, Path], image: str,
                                         broker: DockerExecutionBroker, model: ModelPort,
                                         audit_verifier: AuditVerifier,
                                         timeout_seconds: int = 20) -> CombinationBenchmarkCellResult:
    """Execute one frozen M4/M5 factorial cell in one session and one trace."""
    _validate(panel, cell, task, scenario, package, objective, sidecar, broker, model, audit_verifier, timeout_seconds)
    session = RunSession(task, package_digest=package.digest, arm=cell.runtime_arm, objective=objective,
                         slots=_SLOTS, execution_limit=1, sidecar=sidecar, verifier=audit_verifier,
                         required_audit=("measurement",))
    workflow = ModularWorkflow(session)
    binding = FrozenRecord.from_dict(opaque_panel_cell_binding(cell))
    try:
        plan, m4_response = _run_m4(workflow, cell, scenario, model, binding)
        revealed, review_id, review_responses = _run_m5(workflow, cell, scenario, model, binding, plan)
        joint = _joint(cell, task, scenario, panel, plan, revealed, review_id, m4_response, review_responses)
        session._record("combination_mechanism", {"joint": joint.data(), "joint_digest": joint.content_hash,
            "controller_contrast_coefficient": panel.design.data()["contrast"][cell.arm_id]})
        solver = run_benchmark_solve_in_session(session=session, workflow=workflow, public_inputs=public_inputs,
            image=image, broker=broker, model=model, analysis_slot="analysis_program", final_slot="final_answer",
            joint_mechanism=joint, panel_cell_binding=binding, driver_id=cell.coverage_id, timeout_seconds=timeout_seconds)
    except Exception as exc:
        if not session._terminal:
            _close_failure(session, cell, scenario, exc)
        return CombinationBenchmarkCellResult(cell, _runtime(cell, session, None, "failed"), None, None)
    status = "succeeded" if solver.status == "execution_succeeded" else "failed"
    return CombinationBenchmarkCellResult(cell, _runtime(cell, session, joint, status), solver, joint)


def verify_m4_m5_combination_benchmark_cell(result: CombinationBenchmarkCellResult, *, panel: CombinationPanel,
                                              task: PublicTask, scenario: FrozenRecord,
                                              package: CandidatePackage) -> FrozenRecord:
    """Replay the one session and module logs before accepting joint context."""
    if not isinstance(result, CombinationBenchmarkCellResult):
        raise ContractError("typed M4/M5 combination result required")
    _validate_panel_inputs(panel, result.cell, task, scenario, package)
    PanelReceiptVerifier()._verify_runtime(result.runtime, result.cell)
    events = [FrozenRecord(line).data() for line in result.runtime.trace_path.read_text(encoding="utf-8").splitlines()]
    if not events or FrozenRecord.from_dict(events[-1]).content_hash != result.runtime.trace_digest:
        raise ContractError("combination runtime receipt does not bind its trace")
    verify_trace(result.runtime.trace_path)
    verify_protocol_trace(result.runtime.trace_path)
    requests = [event["data"]["request"] for event in events if event["stage"] == "model_request"]
    slots = [request["slot"] for request in requests]
    if tuple(slots) != _SLOTS[:len(slots)]:
        raise ContractError("combination trace schedule drifted")
    if any(_private_arm_marker(request) for request in requests):
        raise ContractError("combination model request leaks arm or truth metadata")
    if result.joint_mechanism is None:
        if result.solver is not None:
            raise ContractError("failed mechanism cannot have a solver result")
        return FrozenRecord.from_dict({"schema": "m4-m5-combination-verification-v1", "cell_key": list(result.cell.key),
            "status": result.runtime.status, "engineering_verified": True, "joint_mechanism": None,
            "scientific_effect": "not_measured"})
    joint_events = [event["data"] for event in events if event["stage"] == "combination_mechanism"]
    if len(joint_events) != 1 or joint_events[0].get("joint") != result.joint_mechanism.data() or joint_events[0].get("joint_digest") != result.joint_mechanism.content_hash:
        raise ContractError("joint mechanism record does not bind its trace")
    joint = result.joint_mechanism.data()
    enabled = set(result.cell.runtime_arm.data()["enabled"])
    _verify_module_logs(result.runtime.trace_path.parent, task, joint, enabled)
    module_requests = [event for event in events if event["stage"] == "model_request" and event["data"]["request"]["slot"] in _SLOTS[:3]]
    module_responses = [event for event in events if event["stage"] == "model_response"]
    by_digest = {event["data"]["request_digest"]: FrozenRecord.from_dict(event["data"]["response"]) for event in module_responses}
    actual = [by_digest.get(event["data"]["request_digest"]) for event in module_requests]
    if len(module_requests) != 3 or any(item is None for item in actual) or [item.content_hash for item in actual] != joint.get("module_response_digests"):
        raise ContractError("joint mechanism response digests do not bind the three actual module calls")
    joint_index = next(index for index,event in enumerate(events) if event["stage"] == "combination_mechanism")
    response_indexes = [index for index,event in enumerate(events) if event["stage"] == "model_response" and event["data"]["request_digest"] in {item["data"]["request_digest"] for item in module_requests}]
    solver_indexes = [index for index,event in enumerate(events) if event["stage"] == "model_request" and event["data"]["request"]["slot"] == "analysis_program"]
    if not response_indexes or not solver_indexes or not max(response_indexes) < joint_index < min(solver_indexes):
        raise ContractError("joint mechanism event is not ordered after module responses and before solver")
    if joint["prediction_plan"] is not None and any(event["data"]["request"]["module_context"].get("prediction_plan") != joint["prediction_plan"] for event in module_requests[1:]):
        raise ContractError("M5 review requests do not carry the actual frozen M4 plan")
    if len(requests) < 3:
        raise ContractError("joint mechanism did not reach both matched module calls")
    first_response = next(event["data"]["response"] for event in events
                          if event["stage"] == "model_response" and event["data"]["request_digest"]
                          == next(item["data"]["request_digest"] for item in events if item["stage"] == "model_request" and item["data"]["request"]["slot"] == "m5_mechanism"))
    if FrozenRecord.from_dict(first_response).encoded in FrozenRecord.from_dict(requests[2]).encoded:
        raise ContractError("second sealed reviewer received the first submission")
    if result.solver is None:
        raise ContractError("successful combination mechanism requires an in-trace solver result")
    state = _solver_journal_state(events)
    _compare_solver_result(result.solver, state)
    if result.solver.status != state["status"] or result.runtime.status != ("succeeded" if state["status"] == "execution_succeeded" else "failed"):
        raise ContractError("combination receipt status is not derived from the shared solver journal")
    solver_requests = [request for request in requests if request["slot"] in {"analysis_program", "final_answer"}]
    if result.solver is not None and (len(solver_requests) and any(request["module_context"].get("joint_mechanism") != joint
                                                               or request["module_context"].get("joint_mechanism_digest") != result.joint_mechanism.content_hash
                                                               for request in solver_requests)):
        raise ContractError("solver request does not carry the trace-bound joint mechanism")
    if result.solver is not None and result.solver.session.sidecar != result.runtime.trace_path.parent:
        raise ContractError("combination solver used a second session")
    return FrozenRecord.from_dict({"schema": "m4-m5-combination-verification-v1", "cell_key": list(result.cell.key),
        "status": result.runtime.status, "engineering_verified": True, "joint_mechanism_digest": result.joint_mechanism.content_hash,
        "scientific_effect": "not_measured"})


def _run_m4(workflow: ModularWorkflow, cell: PanelCell, scenario: FrozenRecord, model: ModelPort,
            binding: FrozenRecord):
    response = workflow.invoke_model("m4_plan", model, instruction=(
        "Produce exactly a three-branch public prediction plan with budget_units=3. Each branch must use one common "
        "discriminator and at least two branches must differ on it. This is train-only reasoning, not a score or truth."),
        module_context=FrozenRecord.from_dict({"panel_cell": binding.data(), "combination_scenario": scenario.data(),
                                                "mechanism_phase": "proposal"}))
    if "M4" not in workflow.enabled:
        workflow._trace("operation_m4_control", "executed", response_digest=response.content_hash)
        return None, response
    body = response.data()
    if set(body) != {"question", "branches", "budget_units"} or body["budget_units"] != 3 or not isinstance(body["branches"], list) or len(body["branches"]) != 3:
        raise ContractError("M4 combination response requires the frozen three-branch plan")
    plan = workflow.predictions.freeze(body["question"], body["branches"], budget_units=3)
    workflow._trace("stage_1", "executed", plan_id=plan.plan_id, plan_digest=plan.payload.content_hash,
                    response_digest=response.content_hash)
    return plan, response


def _run_m5(workflow: ModularWorkflow, cell: PanelCell, scenario: FrozenRecord, model: ModelPort,
            binding: FrozenRecord, plan):
    review, submissions, responses = None, [], []
    if "M5" in workflow.enabled:
        review = workflow.reviews.open(task_binding=workflow.session.task.content_hash, evidence_snapshot=scenario.content_hash,
                                       roles=[{"role_id": role, "question": question} for role, question in _ROLES], budget_units=2)
    plan_payload = plan.payload.data() if plan is not None else None
    for slot, (role, question) in zip(_SLOTS[1:3], _ROLES):
        context = {"panel_cell": binding.data(), "public_task": workflow.session.task.data(), "mechanism_phase": "sealed_review",
                   "review_role": role, "review_question": question,
                   "prediction_plan": plan_payload, "sealed": True}
        response = workflow.invoke_model(slot, model, instruction="Answer only the assigned public review question.",
                                         module_context=FrozenRecord.from_dict(context))
        responses.append(response)
        if review is not None:
            submissions.append(workflow.reviews.submit(review.review_id, role_id=role, reviewer_id="m4m5-" + role,
                                                        response=response.data(), cost_units=1))
    if review is None:
        workflow._trace("operation_m5_control", "executed", response_digests=[item.content_hash for item in responses])
        return None, None, tuple(responses)
    revealed = workflow.reviews.reveal(review.review_id)
    workflow.revealed = FrozenRecord.from_dict({"review_id": review.review_id, "submissions": [item.data() for item in revealed]})
    workflow._trace("stage_7", "executed", review_id=review.review_id, review_digest=workflow.revealed.content_hash,
                    response_digests=[item.content_hash for item in responses])
    return workflow.revealed, review.review_id, tuple(responses)


def _joint(cell: PanelCell, task: PublicTask, scenario: FrozenRecord, panel: CombinationPanel, plan, revealed,
           review_id: str | None, m4_response: FrozenRecord, review_responses: tuple[FrozenRecord, ...]) -> FrozenRecord:
    return FrozenRecord.from_dict({"schema": "m4-m5-joint-mechanism-v1", "panel_cell": opaque_panel_cell_binding(cell),
        "task_digest": task.content_hash, "scenario_digest": scenario.content_hash, "design_digest": panel.design.content_hash,
        "prediction_plan": plan.payload.data() if plan else None,
        "prediction_plan_id": plan.plan_id if plan else None, "prediction_plan_digest": plan.payload.content_hash if plan else None,
        "review_id": review_id, "revealed_review": revealed.data() if revealed else None,
        "review_digest": revealed.content_hash if revealed else None,
        "module_response_digests": [m4_response.content_hash, *[item.content_hash for item in review_responses]]})


def _runtime(cell: PanelCell, session: RunSession, joint: FrozenRecord | None, status: str) -> RuntimeReceipt:
    trace = session.sidecar / "trace.jsonl"; lines = trace.read_text(encoding="utf-8").splitlines()
    digest = FrozenRecord(lines[-1]).content_hash
    responses = [event.data()["data"]["response"] for event in session._events if event.data()["stage"] == "model_response"]
    output = None if status == "failed" else FrozenRecord.from_dict({"responses": responses,
        "terminal": session._events[-1].data()["data"]}).content_hash
    return RuntimeReceipt(cell.key, status, trace, digest, output, None if status == "succeeded" else "combination mechanism or solve failed")


def _close_failure(session: RunSession, cell: PanelCell, scenario: FrozenRecord, exc: Exception) -> None:
    last = session._events[-1].data()
    if last["stage"] == "model_response":
        session.driver_failure(driver_id=cell.coverage_id, response=FrozenRecord.from_dict(last["data"]["response"]),
                               error_type=type(exc).__name__)
    else:
        session.controller_failure(driver_id=cell.coverage_id, error_type=type(exc).__name__,
                                   panel_cell=opaque_panel_cell_binding(cell))


def _validate(panel, cell, task, scenario, package, objective, sidecar, broker, model, verifier, timeout) -> None:
    _validate_panel_inputs(panel, cell, task, scenario, package)
    if (not isinstance(objective, FrozenRecord) or not isinstance(sidecar, Path) or not isinstance(broker, DockerExecutionBroker)
            or not callable(model) or not isinstance(verifier, AuditVerifier) or type(timeout) is not int or not 1 <= timeout <= 120):
        raise ContractError("M4/M5 combination executor needs typed runtime dependencies")


def _validate_panel_inputs(panel: CombinationPanel, cell: PanelCell, task: PublicTask,
                           scenario: FrozenRecord, package: CandidatePackage) -> None:
    if not isinstance(panel, CombinationPanel) or panel.obligation_id != _PAIR or cell not in panel.cells:
        raise ContractError("no actual combination executor registered for this obligation")
    if (not isinstance(task, PublicTask) or task.identity != cell.identity or task.content_hash != cell.task_digest
            or not isinstance(scenario, FrozenRecord) or scenario.content_hash != cell.scenario_digest
            or not isinstance(package, CandidatePackage) or package.digest != cell.package_digest):
        raise ContractError("M4/M5 combination cell binding mismatch")
    expected = {"00": set(), "10": {"M4"}, "01": {"M5"}, "11": {"M4", "M5"}}
    if cell.arm_id not in expected or set(cell.runtime_arm.data().get("enabled", ())) != expected[cell.arm_id]:
        raise ContractError("M4/M5 combination arm is not the frozen four-arm grid")


def _verify_module_logs(sidecar: Path, task: PublicTask, joint: Mapping, enabled: set[str]) -> None:
    registry = PredictionRegistry(task.identity, storage_path=sidecar / "predictions.jsonl")
    reviews = ReviewEngine(task.identity, storage_path=sidecar / "reviews.jsonl")
    if "M4" in enabled:
        plan = registry.plan(joint["prediction_plan_id"])
        if plan.payload.content_hash != joint["prediction_plan_digest"] or plan.payload.data() != joint["prediction_plan"]:
            raise ContractError("joint M4 plan does not replay from the prediction log")
    elif any(joint[key] is not None for key in ("prediction_plan", "prediction_plan_id", "prediction_plan_digest")):
        raise ContractError("M4 control invented a prediction artifact")
    if "M5" in enabled:
        revealed = reviews.reveal(joint["review_id"])
        body = FrozenRecord.from_dict({"review_id": joint["review_id"], "submissions": [item.data() for item in revealed]})
        if body.content_hash != joint["review_digest"] or body.data() != joint["revealed_review"]:
            raise ContractError("joint M5 review does not replay from the review log")
    elif any(joint[key] is not None for key in ("review_id", "revealed_review", "review_digest")):
        raise ContractError("M5 control invented a review artifact")


def _private_arm_marker(request: Mapping) -> bool:
    encoded = FrozenRecord.from_dict(request).encoded
    return any(marker in encoded for marker in ('"arm_id"', '"enabled"', '"control"', '"truth"', '"contrast"', '"candidate_package"'))
