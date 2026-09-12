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
    slots: tuple[str, ...]
    execution_limit: int
    docker_execution: str

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
    slots = ("scenario", "final")
    execution_limit = 0
    docker_execution = "not_requested_by_driver"

    def run(self, workflow: ModularWorkflow, *, cell: PanelCell, scenario: FrozenRecord,
            model: ModelPort, package: CandidatePackage) -> tuple[WorkflowResult, FrozenRecord, tuple[FrozenRecord, ...]]:
        binding = {"experiment_id": cell.coverage_id, "variant": cell.variant,
                   "replicate": cell.replicate, "arm_id": cell.arm_id,
                   "scenario_digest": scenario.content_hash}
        controller = scenario.data()["controller_input"]
        first = workflow.invoke_model("scenario", model, instruction=(
            "Produce exactly a three-branch prediction plan from this exact public scenario with budget_units=3. "
            "Every branch must use one common discriminator, and at least two branches must make different "
            "predictions for it. The plan is not an observation or a scientific result; do not claim either."), module_context=FrozenRecord.from_dict({
                "panel_cell": binding, "scenario_controller_input": controller,
                "candidate_package": package.record.data(),
                "control": "M4" if "M4" not in workflow.enabled else ""}))
        if "M4" in workflow.enabled:
            body = first.data()
            if set(body) != {"question", "branches", "budget_units"}:
                raise ContractError("Q3.1 M4 response lacks an operational prediction plan")
            if body["budget_units"] != 3 or not isinstance(body["branches"], list) or len(body["branches"]) != 3:
                raise ContractError("Q3.1 M4 response requires exactly three branches and budget_units=3")
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
            "Return the bounded candidate record for this train-only run; unknown is allowed. "
            "Copy required_objective_digest exactly into objective_digest; do not calculate or alter it."),
            module_context=FrozenRecord.from_dict({"panel_cell": binding, "candidate_package": package.record.data(),
                                                    "required_objective_digest": workflow.session.objective.content_hash,
                                                    "driver_stage": stage.detail.data()["stage"],
                                                    "driver_result": result_context}))
        return stage, candidate, (first, candidate)


class Q43ReviewDriver:
    """Production Q4.3 driver with a real M5 barrier and matched control calls."""
    experiment_id = "Q4.3"
    slots = ("mechanism_initial", "measurement_initial", "mechanism_revision",
             "measurement_revision", "final")
    execution_limit = 0
    docker_execution = "not_requested_by_driver"

    def run(self, workflow: ModularWorkflow, *, cell: PanelCell, scenario: FrozenRecord,
            model: ModelPort, package: CandidatePackage) -> tuple[WorkflowResult, FrozenRecord, tuple[FrozenRecord, ...]]:
        binding = {"experiment_id": cell.coverage_id, "variant": cell.variant,
                   "replicate": cell.replicate, "arm_id": cell.arm_id,
                   "scenario_digest": scenario.content_hash}
        controller = scenario.data()["controller_input"]
        roles = (("mechanism", "What causal mechanism could produce the public pattern, and what observation would falsify it?"),
                 ("measurement", "Identify a plausible measurement failure and a public check that would distinguish it from the stated mechanism."))
        responses: list[FrozenRecord] = []
        submissions = []
        review_id = None
        m5_enabled = "M5" in workflow.enabled
        if m5_enabled:
            review = workflow.reviews.open(task_binding=workflow.session.task.content_hash,
                evidence_snapshot=scenario.content_hash,
                roles=[{"role_id": role, "question": question} for role, question in roles], budget_units=len(roles))
            review_id = review.review_id
        for index, ((role, question), slot) in enumerate(zip(roles, self.slots[:2])):
            previous = submissions[0].response.data() if (m5_enabled and cell.variant == "sequential" and index) else None
            context = {"panel_cell": binding, "scenario_controller_input": controller,
                       "candidate_package": package.record.data(), "review_role": role,
                       "review_question": question, "review_phase": "initial",
                       "visibility": "sequential" if cell.variant == "sequential" else "sealed"}
            if m5_enabled:
                context.update({"review_id": review_id, "sealed": cell.variant == "sealed_then_exchange",
                                "prior_visible_submission": previous})
            else:
                context.update({"control": "M5", "prior_visible_submission": None,
                                "control_notice": "M5 review intervention disabled; no peer response is exposed."})
            response = workflow.invoke_model(slot, model, instruction="Answer only the assigned review question.",
                module_context=FrozenRecord.from_dict(context))
            responses.append(response)
            if m5_enabled:
                submissions.append(workflow.reviews.submit(review_id, role_id=role,
                    reviewer_id=f"q43-{role}-reviewer", response=response.data(), cost_units=1))
        revisions = []
        revealed = None
        if m5_enabled:
            revealed = workflow.reviews.reveal(review_id)
            workflow.revealed = FrozenRecord.from_dict({"review_id": review_id,
                "submissions": [item.data() for item in revealed]})
        for (role, question), slot in zip(roles, self.slots[2:4]):
            context = {"panel_cell": binding, "scenario_controller_input": controller,
                       "candidate_package": package.record.data(), "review_role": role,
                       "review_question": question, "review_phase": "post_reveal_revision",
                       "visibility": "post_reveal"}
            if m5_enabled:
                context.update({"review_id": review_id, "sealed": False,
                                "revealed_submissions": [item.data() for item in revealed]})
            else:
                context.update({"control": "M5", "revealed_submissions": [],
                                "control_notice": "M5 review intervention disabled; no submissions exist to reveal."})
            response = workflow.invoke_model(slot, model, instruction="Reassess after the declared review visibility stage.",
                module_context=FrozenRecord.from_dict(context))
            responses.append(response)
            if m5_enabled:
                revisions.append(workflow.reviews.revise_after_reveal(review_id, role_id=role,
                    reviewer_id=f"q43-{role}-reviewer", response=response.data()))
        review_context = {"m5_enabled": m5_enabled, "variant": cell.variant,
                          "initial_response_digests": [item.content_hash for item in responses[:2]],
                          "revision_response_digests": [item.content_hash for item in responses[2:]],
                          "review_id": review_id,
                          # This is supplied only after both submissions were
                          # recorded and the sealed barrier was opened.
                          "initial_submissions": [item.data() for item in submissions],
                          "post_reveal_revisions": [item.data() for item in revisions]}
        stage = workflow._trace("stage_7" if m5_enabled else "operation_m5_control", "executed",
            **review_context, review_log_digest=(workflow.revealed.content_hash if workflow.revealed else None),
            revision_count=len(revisions))
        candidate = workflow.invoke_model("final", model, instruction=(
            "Return the bounded candidate record for this train-only run; unknown is allowed. "
            "Copy required_objective_digest exactly into objective_digest; do not calculate or alter it."),
            module_context=FrozenRecord.from_dict({"panel_cell": binding, "candidate_package": package.record.data(),
                "required_objective_digest": workflow.session.objective.content_hash, "driver_stage": stage.detail.data()["stage"],
                "q43_review": review_context}))
        responses.append(candidate)
        if candidate.data().get("objective_digest") != workflow.session.objective.content_hash:
            raise ContractError("Q4.3 final must copy required_objective_digest exactly")
        return stage, candidate, tuple(responses)


DRIVERS: dict[str, ScenarioDriver] = {"Q3.1": Q31PredictionDriver(), "Q4.3": Q43ReviewDriver()}


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
                         objective=objective, slots=driver.slots, execution_limit=driver.execution_limit,
                         sidecar=sidecar, verifier=audit_verifier, required_audit=("measurement",))
    workflow = ModularWorkflow(session)
    try:
        stage, candidate, responses = driver.run(workflow, cell=cell, scenario=scenario, model=model, package=package)
    except Exception as exc:
        if not session._terminal:
            last = session._events[-1].data()
            if last["stage"] == "model_response":
                session.driver_failure(driver_id=driver.experiment_id,
                                       response=FrozenRecord.from_dict(last["data"]["response"]),
                                       error_type=type(exc).__name__)
            else:
                session.controller_failure(driver_id=driver.experiment_id, error_type=type(exc).__name__, panel_cell={
                    "experiment_id": cell.coverage_id, "variant": cell.variant, "replicate": cell.replicate,
                    "arm_id": cell.arm_id, "scenario_digest": scenario.content_hash})
        trace_path = sidecar / "trace.jsonl"
        trace_digest = FrozenRecord(trace_path.read_text(encoding="utf-8").splitlines()[-1]).content_hash
        runtime = RuntimeReceipt(cell.key, "failed", trace_path, trace_digest, None,
                                 f"{type(exc).__name__}: driver_or_model_rejected")
        plan = FrozenRecord.from_dict({"schema": "train-panel-call-plan-v1", "driver": driver.experiment_id,
            "cell_key": list(cell.key), "scenario_digest": scenario.content_hash,
            "enabled_modules": cell.runtime_arm.data()["enabled"], "package_digest": package.digest,
            "package_record_digest": package.record.content_hash, "package_changes": package.record.data()["changes"],
            "slots": list(session.slots), "model_calls": session._next_call,
            "execution_attempts": session._attempts, "docker_execution": driver.docker_execution,
            "terminal": session._events[-1].data()["stage"]})
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
        "package_binding": "candidate_package_record_in_model_context", "slots": list(session.slots),
        "workflow_stage": stage.detail.data()["stage"], "execution_attempts": session._attempts,
        "model_calls": session._next_call, "docker_execution": driver.docker_execution})
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
