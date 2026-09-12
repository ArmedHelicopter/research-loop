"""Train-only execution of one frozen modular panel cell.

This is the narrow bridge between a prepared public benchmark task and a
``FrozenPanel``.  It records controller calls in a real ``RunSession`` journal;
it does not turn a model response, a Docker exit status, or an optional scorer
receipt into a scientific claim.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from research_loop.modular.contracts import FrozenRecord, PublicTask
from research_loop.modular.experiments import registry
from research_loop.modular.modules.improvement import CandidatePackage
from research_loop.modular.panel_receipts import PanelCell, RuntimeReceipt, ScientificScorerReceipt
from research_loop.modular.runtime import AuditVerifier, RunSession
from research_loop.modular.workflow import ModularWorkflow, WorkflowResult
from research_loop.ontology import ContractError


class ModelPort(Protocol):
    def __call__(self, request: FrozenRecord) -> FrozenRecord: ...


class ScorerPort(Protocol):
    """An independently configured issuer; this runner never creates scores."""
    def __call__(self, cell: PanelCell, runtime: RuntimeReceipt) -> ScientificScorerReceipt: ...


class ScenarioDriver(Protocol):
    experiment_id: str

    def run(self, workflow: ModularWorkflow, *, cell: PanelCell, scenario: FrozenRecord,
            model: ModelPort, package: CandidatePackage) -> tuple[WorkflowResult, FrozenRecord, tuple[FrozenRecord, ...]]: ...


@dataclass(frozen=True)
class TrainCellResult:
    runtime: RuntimeReceipt
    scorer: ScientificScorerReceipt | None
    call_plan: FrozenRecord


class Q31PredictionDriver:
    """The first real driver: Q3.1 routes M4 on/off through ``propose``."""
    experiment_id = "Q3.1"

    def run(self, workflow: ModularWorkflow, *, cell: PanelCell, scenario: FrozenRecord,
            model: ModelPort, package: CandidatePackage) -> tuple[WorkflowResult, FrozenRecord, tuple[FrozenRecord, ...]]:
        binding = {"experiment_id": cell.coverage_id, "variant": cell.variant,
                   "replicate": cell.replicate, "arm_id": cell.arm_id,
                   "scenario_digest": scenario.content_hash}
        controller = scenario.data()["controller_input"]
        first = workflow.invoke_model("scenario", model, instruction=(
            "Produce a bounded three-branch prediction plan from this exact public scenario. "
            "Do not claim a scientific result."), module_context=FrozenRecord.from_dict({
                "panel_cell": binding, "scenario_controller_input": controller,
                "candidate_package": package.record.data(),
                "control": "M4" if "M4" not in workflow.enabled else ""}))
        if "M4" in workflow.enabled:
            body = first.data()
            if set(body) != {"question", "branches", "budget_units"}:
                raise ContractError("Q3.1 M4 response lacks an operational prediction plan")
            plan = workflow.predictions.freeze(body["question"], body["branches"], budget_units=body["budget_units"])
            stage = workflow._trace("stage_1", "executed", plan_digest=plan.payload.content_hash,
                                    scenario_digest=scenario.content_hash)
            result_context = {"prediction_plan": plan.payload.data(),
                              "prediction_plan_digest": plan.payload.content_hash}
        else:
            stage = workflow._trace("operation_m4_control", "executed", response_digest=first.content_hash,
                                    scenario_digest=scenario.content_hash)
            result_context = {"m4_control_response": first.data()}
        candidate = workflow.invoke_model("final", model, instruction=(
            "Return the bounded candidate record for this train-only run; unknown is allowed."),
            module_context=FrozenRecord.from_dict({"panel_cell": binding, "candidate_package": package.record.data(),
                                                    "driver_stage": stage.detail.data()["stage"],
                                                    "driver_result": result_context}))
        return stage, candidate, (first, candidate)


DRIVERS: dict[str, ScenarioDriver] = {"Q3.1": Q31PredictionDriver()}


def run_train_cell(cell: PanelCell, *, task: PublicTask, scenario: FrozenRecord,
                   package: CandidatePackage, objective: FrozenRecord, sidecar: Path,
                   model: ModelPort, audit_verifier: AuditVerifier,
                   scorer: ScorerPort | None = None) -> TrainCellResult:
    """Run one predeclared training cell and return only trace-bound receipts.

    Validation is deliberately absent.  Driver selection is closed, so fixture
    injection text cannot be treated as an executed intervention.
    """
    if not isinstance(cell, PanelCell) or cell.identity.domain != "train":
        raise ContractError("panel runner accepts training cells only")
    if not isinstance(task, PublicTask) or task.identity != cell.identity or task.content_hash != cell.task_digest:
        raise ContractError("public task does not bind this panel cell")
    if not isinstance(scenario, FrozenRecord) or scenario.content_hash != cell.scenario_digest:
        raise ContractError("scenario digest does not bind this panel cell")
    body = scenario.data()
    if body.get("experiment_id") != cell.coverage_id or body.get("variant") != cell.variant:
        raise ContractError("scenario experiment or variant differs from panel cell")
    if not isinstance(body.get("base"), dict) or body["base"].get("task") != task.content_hash:
        raise ContractError("scenario base task does not bind this public task")
    spec = registry().get(cell.coverage_id)
    if spec is None or cell.variant not in spec.variants:
        raise ContractError("panel cell is not a registered scenario variant")
    driver = DRIVERS.get(cell.coverage_id)
    if driver is None:
        raise ContractError("registered scenario has no production panel driver")
    if not isinstance(package, CandidatePackage) or package.digest != cell.package_digest:
        raise ContractError("package digest differs from panel cell")
    if not isinstance(objective, FrozenRecord) or not callable(model):
        raise ContractError("runner needs frozen objective and model port")
    session = RunSession(task, package_digest=package.digest, arm=cell.runtime_arm,
                         objective=objective, slots=("scenario", "final"), execution_limit=0,
                         sidecar=sidecar, verifier=audit_verifier, required_audit=("measurement",))
    workflow = ModularWorkflow(session)
    try:
        stage, candidate, responses = driver.run(workflow, cell=cell, scenario=scenario, model=model, package=package)
    except Exception as exc:
        if not session._terminal:
            last_response = FrozenRecord.from_dict(session._events[-1].data()["data"]["response"])
            session.driver_failure(driver_id=driver.experiment_id, response=last_response, error_type=type(exc).__name__)
        trace_path = sidecar / "trace.jsonl"
        trace_digest = FrozenRecord(trace_path.read_text(encoding="utf-8").splitlines()[-1]).content_hash
        runtime = RuntimeReceipt(cell.key, "failed", trace_path, trace_digest, None,
                                 f"{type(exc).__name__}: driver_or_model_rejected")
        plan = FrozenRecord.from_dict({"schema": "train-panel-call-plan-v1", "driver": driver.experiment_id,
            "cell_key": list(cell.key), "scenario_digest": scenario.content_hash,
            "enabled_modules": cell.runtime_arm.data()["enabled"], "package_digest": package.digest,
            "package_record_digest": package.record.content_hash, "package_changes": package.record.data()["changes"],
            "slots": list(session.slots), "model_calls": session._next_call,
            "execution_attempts": session._attempts, "terminal": session._events[-1].data()["stage"]})
        return TrainCellResult(runtime, None, plan)
    terminal = session.finish(candidate)
    trace_path = sidecar / "trace.jsonl"
    trace_lines = trace_path.read_text(encoding="utf-8").splitlines()
    trace_digest = FrozenRecord(trace_lines[-1]).content_hash
    output_digest = FrozenRecord.from_dict({"responses": [response.data() for response in responses], "terminal": terminal.data()}).content_hash
    decision = terminal.data()["decision"]
    runtime = RuntimeReceipt(cell.key, "blocked" if decision == "blocked" else "succeeded", trace_path,
                             trace_digest, output_digest,
                             "terminal decision blocked" if decision == "blocked" else None)
    plan = FrozenRecord.from_dict({"schema": "train-panel-call-plan-v1", "driver": driver.experiment_id,
        "cell_key": list(cell.key), "scenario_digest": scenario.content_hash,
        "enabled_modules": cell.runtime_arm.data()["enabled"], "package_digest": package.digest,
        "package_record_digest": package.record.content_hash, "package_changes": package.record.data()["changes"],
        "package_binding": "candidate_package_record_in_model_context", "slots": ["scenario", "final"],
        "workflow_stage": stage.detail.data()["stage"], "execution_attempts": session._attempts,
        "model_calls": session._next_call, "docker_execution": "not_requested_by_q3_1_driver"})
    scored = None
    if scorer is not None:
        scored = scorer(cell, runtime)
        if (not isinstance(scored, ScientificScorerReceipt) or scored.cell_key != cell.key
                or not isinstance(scored.receipt, FrozenRecord)):
            raise ContractError("scorer port must return a typed receipt for this cell")
        score = scored.receipt.data()
        if (score.get("schema") != "independent-scored-cell-v1"
                or score.get("runtime_trace_digest") != runtime.trace_digest
                or score.get("scorer_digest") != cell.scorer_digest):
            raise ContractError("scorer receipt lacks exact runtime and scorer binding")
    return TrainCellResult(runtime, scored, plan)
