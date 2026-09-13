"""Train-only execution of one frozen modular panel cell.

This is the narrow bridge between a prepared public benchmark task and a
``FrozenPanel``.  It records controller calls in a real ``RunSession`` journal;
it does not turn a model response, a Docker exit status, or an optional scorer
receipt into a scientific claim.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Mapping, Protocol

from research_loop.modular.contracts import FrozenRecord, PublicTask
from research_loop.modular.experiments import registry
from research_loop.modular.modules.improvement import CandidatePackage
from research_loop.modular.panel_receipts import PanelCell, RuntimeReceipt, ScientificScorerReceipt, opaque_panel_cell_binding, require_protocol_refusal
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

    def slots_for(self, cell: PanelCell) -> tuple[str, ...]: ...

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

    def slots_for(self, cell: PanelCell) -> tuple[str, ...]:
        return self.slots

    def run(self, workflow: ModularWorkflow, *, cell: PanelCell, scenario: FrozenRecord,
            model: ModelPort, package: CandidatePackage) -> tuple[WorkflowResult, FrozenRecord, tuple[FrozenRecord, ...]]:
        binding = opaque_panel_cell_binding(cell)
        controller = scenario.data()["controller_input"]
        diagnostic = {name: controller[name] for name in ("diagnostic_focus", "operational_constraints")}
        first = workflow.invoke_model("scenario", model, instruction=(
            "Produce exactly a three-branch prediction plan from this exact public scenario with budget_units=3. "
            "Every branch must use one common discriminator, and at least two branches must make different "
            "predictions for it. The plan is not an observation or a scientific result; do not claim either."), module_context=FrozenRecord.from_dict({
                "panel_cell": binding, "public_diagnostic": diagnostic}))
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
                              "prediction_plan_digest": plan.payload.content_hash,
                              "proposal": first.data()}
        else:
            stage = workflow._trace("operation_m4_control", "executed", response_digest=first.content_hash,
                                    scenario_digest=scenario.content_hash)
            result_context = {"prediction_plan": None, "prediction_plan_digest": None,
                              "proposal": first.data()}
        candidate = workflow.invoke_model("final", model, instruction=(
            "Return the bounded candidate record for this train-only run; unknown is allowed. "
            "Copy required_objective_digest exactly into objective_digest; do not calculate or alter it."),
            module_context=FrozenRecord.from_dict({"panel_cell": binding,
                                                    "required_objective_digest": workflow.session.objective.content_hash,
                                                    "driver_result": result_context}))
        return stage, candidate, (first, candidate)


class Q43ReviewDriver:
    """Production Q4.3 driver with a real M5 barrier and matched control calls."""
    experiment_id = "Q4.3"
    slots = ("mechanism_initial", "measurement_initial", "mechanism_revision",
             "measurement_revision", "final")
    execution_limit = 0
    docker_execution = "not_requested_by_driver"

    def slots_for(self, cell: PanelCell) -> tuple[str, ...]:
        return self.slots

    def run(self, workflow: ModularWorkflow, *, cell: PanelCell, scenario: FrozenRecord,
            model: ModelPort, package: CandidatePackage) -> tuple[WorkflowResult, FrozenRecord, tuple[FrozenRecord, ...]]:
        binding = opaque_panel_cell_binding(cell)
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
            context = {"panel_cell": binding, "review_role": role,
                       "review_question": question, "review_phase": "initial",
                       "prior_visible_submission": previous}
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
            context = {"panel_cell": binding, "review_role": role,
                       "review_question": question, "review_phase": "post_reveal_revision",
                       "revealed_submissions": [item.data() for item in revealed] if revealed else []}
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
            module_context=FrozenRecord.from_dict({"panel_cell": binding,
                "required_objective_digest": workflow.session.objective.content_hash,
                "q43_review": {name: value for name, value in review_context.items()
                               if name not in {"m5_enabled", "variant"}}}))
        responses.append(candidate)
        if candidate.data().get("objective_digest") != workflow.session.objective.content_hash:
            raise ContractError("Q4.3 final must copy required_objective_digest exactly")
        return stage, candidate, tuple(responses)


from research_loop.modular.q15_panel_driver import Q15HistoryReviewDriver
from research_loop.modular.q4_panel_drivers import Q41IndependenceDriver, Q42RoleDriver, Q44CounterexampleDriver, Q45SelfCorrectionDriver
from research_loop.modular.history_panel_drivers import Q11HistoryDriver, Q12DependencyDriver, AdmissionPort
from research_loop.modular.pressure_panel_driver import Q21PressureDriver
from research_loop.modular.support_panel_drivers import Q13RepresentationDriver, Q14SupportDriver
from research_loop.modular.withdrawal_panel_drivers import Q16WithdrawalDriver, Q17TimeInformationDriver
from research_loop.modular.audit_panel_drivers import Q23AuditFaultDriver, Q24AuditPairDriver, AuditReceiptPort, ShadowExecutionPort
from research_loop.modular.prediction_panel_drivers import Q32JointSeparateDriver, Q53DedupDriver
from research_loop.modular.polarity_goal_panel_drivers import Q25EvidencePolarityDriver, Q26GoalLockDriver
from research_loop.modular.scheduler_panel_drivers import M8SchedulerDriver
from research_loop.modular.semantic_panel_drivers import Q22CompletionSemanticsDriver, Q64ScorerRepairDriver
from research_loop.modular.feasibility_panel_drivers import (
    Q51FeasibilityDriver, Q52DistinguishabilityDriver, FeasibilityAuthorityPort)
from research_loop.modular.panel_execution import PublicInputResolver
from research_loop.modular.exploration_panel_drivers import (
    Q71ExplorationAdmissionDriver, Q72FeasibilityAppealDriver, ExplorationAuthorityPort)
from research_loop.modular.exploration_extended_panel_drivers import ExtendedExplorationDriver
from research_loop.modular.q54_causal_driver import Q54CausalDriver, DiagnosticAuthority
from research_loop.modular.q55_causal_driver import Q55Driver, Authority as Q55Authority
from research_loop.modular.protocol_panel_driver import (Q27ProtocolDriver, ProtocolAuditPort, ProtocolReplayAuthority,
    verify_after_finish, verify_protocol_replay_receipt, _exclusive_record)
from research_loop.modular.benchmarks.execution import DockerExecutionBroker


DRIVERS: dict[str, ScenarioDriver] = {"Q1.1": Q11HistoryDriver(), "Q1.2": Q12DependencyDriver(),
    "Q1.3": Q13RepresentationDriver(), "Q1.4": Q14SupportDriver(),
    "Q1.5": Q15HistoryReviewDriver(), "Q1.6": Q16WithdrawalDriver(), "Q1.7": Q17TimeInformationDriver(),
    "Q2.1": Q21PressureDriver(), "Q2.3": Q23AuditFaultDriver(), "Q2.4": Q24AuditPairDriver(),
    "Q2.5": Q25EvidencePolarityDriver(), "Q2.6": Q26GoalLockDriver(), "Q2.7": Q27ProtocolDriver(),
    "Q2.2": Q22CompletionSemanticsDriver(), "Q6.4": Q64ScorerRepairDriver(),
    "Q3.1": Q31PredictionDriver(), "Q3.2": Q32JointSeparateDriver(), "Q5.3": Q53DedupDriver(),
    "Q5.1": Q51FeasibilityDriver(None, None, None), "Q5.2": Q52DistinguishabilityDriver(None, None, None),
    "Q7.1": Q71ExplorationAdmissionDriver(None, None, None), "Q7.2": Q72FeasibilityAppealDriver(None, None, None),
    **{key: ExtendedExplorationDriver(None, None, None, key) for key in ("Q7.3", "Q7.4", "Q7.5", "Q7.6")},
    "Q5.4": Q54CausalDriver(None, None, None),
    "Q5.5": Q55Driver(None, None, None, None, {}),
    "Q3.3": M8SchedulerDriver("Q3.3"), "Q3.4": M8SchedulerDriver("Q3.4"), "Q3.5": M8SchedulerDriver("Q3.5"),
    "Q4.1": Q41IndependenceDriver(), "Q4.2": Q42RoleDriver(), "Q4.3": Q43ReviewDriver(),
    "Q4.4": Q44CounterexampleDriver(), "Q4.5": Q45SelfCorrectionDriver()}


def run_train_cell(cell: PanelCell, *, task: PublicTask, scenario: FrozenRecord,
                   package: CandidatePackage, objective: FrozenRecord, sidecar: Path,
                   model: ModelPort, audit_verifier: AuditVerifier,
                   scorer: ScorerPort | None = None, history_admission_port: AdmissionPort | None = None,
                   audit_receipt_port: AuditReceiptPort | None = None,
                   shadow_execution_port: ShadowExecutionPort | None = None,
                   p0_control: FrozenRecord | None = None,
                   feasibility_broker: DockerExecutionBroker | None = None,
                   feasibility_input_resolver: PublicInputResolver | None = None,
                   feasibility_authority: FeasibilityAuthorityPort | None = None,
                   exploration_broker: DockerExecutionBroker | None = None,
                   exploration_input_resolver: PublicInputResolver | None = None,
                   exploration_authority: ExplorationAuthorityPort | None = None,
                   diagnostic_broker: DockerExecutionBroker | None = None,
                   diagnostic_input_resolver: PublicInputResolver | None = None,
                   diagnostic_authority: DiagnosticAuthority | None = None,
                   q55_broker: DockerExecutionBroker | None = None,
                   q55_provider=None,
                   q55_input_resolver: PublicInputResolver | None = None,
                   q55_authority: Q55Authority | None = None,
                   q55_authority_keys: Mapping[str, bytes] | None = None,
                   protocol_broker: DockerExecutionBroker | None = None,
                   protocol_audit_port: ProtocolAuditPort | None = None,
                   protocol_replay_authority: ProtocolReplayAuthority | None = None) -> TrainCellResult:
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
    if isinstance(driver, Q27ProtocolDriver):
        if (not isinstance(protocol_broker, DockerExecutionBroker) or not callable(protocol_audit_port)
                or not isinstance(protocol_replay_authority, ProtocolReplayAuthority) or not isinstance(p0_control, FrozenRecord)):
            raise ContractError("Q2.7 requires a broker, audit port, replay authority and trusted P0 control")
        driver = replace(driver, broker=protocol_broker, audit_port=protocol_audit_port,
                         expected_p0_control_digest=p0_control.content_hash)
    if isinstance(driver, (Q51FeasibilityDriver, Q52DistinguishabilityDriver)):
        driver = replace(driver,
            broker=feasibility_broker if feasibility_broker is not None else driver.broker,
            input_resolver=feasibility_input_resolver if feasibility_input_resolver is not None else driver.input_resolver,
            authority=feasibility_authority if feasibility_authority is not None else driver.authority)
    if isinstance(driver, (Q71ExplorationAdmissionDriver, ExtendedExplorationDriver)):
        driver = replace(driver,
            broker=exploration_broker if exploration_broker is not None else driver.broker,
            input_resolver=exploration_input_resolver if exploration_input_resolver is not None else driver.input_resolver,
            authority=exploration_authority if exploration_authority is not None else driver.authority)
    if isinstance(driver, Q54CausalDriver):
        driver = replace(driver,
            broker=diagnostic_broker if diagnostic_broker is not None else driver.broker,
            input_resolver=diagnostic_input_resolver if diagnostic_input_resolver is not None else driver.input_resolver,
            authority=diagnostic_authority if diagnostic_authority is not None else driver.authority)
    if isinstance(driver, Q55Driver):
        driver = replace(driver, broker=q55_broker if q55_broker is not None else driver.broker,
            provider=q55_provider if q55_provider is not None else driver.provider,
            resolver=q55_input_resolver if q55_input_resolver is not None else driver.resolver,
            authority=q55_authority if q55_authority is not None else driver.authority,
            authority_keys=q55_authority_keys if q55_authority_keys is not None else driver.authority_keys)
    if p0_control is not None:
        if not isinstance(p0_control, FrozenRecord):
            raise ContractError("P0 control must be a caller-trusted frozen record")
        if isinstance(driver, (Q22CompletionSemanticsDriver, Q64ScorerRepairDriver)):
            driver = replace(driver, expected_p0_control_digest=p0_control.content_hash)
    if history_admission_port is not None:
        if not callable(history_admission_port):
            raise ContractError("history admission must be a caller-owned verification port")
        if isinstance(driver, (Q11HistoryDriver, Q12DependencyDriver, Q13RepresentationDriver, Q14SupportDriver,
                               Q16WithdrawalDriver, Q17TimeInformationDriver)):
            driver = replace(driver, admission_port=history_admission_port)
    for port in (audit_receipt_port, shadow_execution_port):
        if port is not None and not callable(port):
            raise ContractError("audit dependencies must be caller-owned ports")
    if isinstance(driver, (Q23AuditFaultDriver, Q24AuditPairDriver)):
        driver = replace(driver,
            receipt_port=audit_receipt_port if audit_receipt_port is not None else driver.receipt_port,
            shadow_execution_port=shadow_execution_port if shadow_execution_port is not None else driver.shadow_execution_port)
    if not isinstance(package, CandidatePackage) or package.digest != cell.package_digest:
        raise ContractError("package digest differs from panel cell")
    if not isinstance(objective, FrozenRecord) or not callable(model):
        raise ContractError("runner needs frozen objective and model port")
    slots_for = getattr(driver, "slots_for", None)
    slots = slots_for(cell) if callable(slots_for) else driver.slots
    if (not isinstance(slots, tuple) or not slots or any(slot not in driver.slots for slot in slots)):
        raise ContractError("driver variant schedule must be a nonempty subset of its frozen schema slots")
    session = RunSession(task, package_digest=package.digest, arm=cell.runtime_arm,
                         objective=objective, slots=slots, execution_limit=driver.execution_limit,
                         sidecar=sidecar, verifier=audit_verifier, required_audit=("measurement",))
    if isinstance(driver, Q27ProtocolDriver):
        session._record("q27_panel_binding", {"panel_cell": {
            "experiment_id": cell.coverage_id, "variant": cell.variant, "replicate": cell.replicate,
            "arm_id": cell.arm_id, "scenario_digest": scenario.content_hash},
            "p0_control_digest": p0_control.content_hash})
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
            "schema_slots": list(driver.slots), "slots": list(session.slots), "model_calls": session._next_call,
            "execution_attempts": session._attempts, "docker_execution": driver.docker_execution,
            "actual_token_measurement": "not_measured",
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
    protocol_post = None
    if isinstance(driver, Q27ProtocolDriver):
        protocol_post = {"schema": "q27-post-runtime-check-v1", "status": "failed", "reason": None,
            "receipt_path": None, "receipt_digest": None, "source_trace_digest": trace_digest,
            "source_output_digest": output_digest, "cell_key": list(cell.key), "scenario_digest": scenario.content_hash}
        try:
            replay = verify_after_finish(cell=cell, scenario=scenario, session=session, candidate=candidate,
                terminal=terminal, replay_authority=protocol_replay_authority,
                expected_p0_control_digest=p0_control.content_hash)
            protocol_post.update(receipt_path="q27-replay/receipt.json", receipt_digest=replay.content_hash)
            finding = verify_protocol_replay_receipt(replay, cell=cell, scenario=scenario, source_trace_path=trace_path,
                replay_authority=protocol_replay_authority, expected_p0_control_digest=p0_control.content_hash)
            if isinstance(finding, FrozenRecord) and finding.data().get("status") == "ineligible":
                protocol_post.update(status="ineligible", reason="source_ineligible_for_registered_fault")
                runtime = replace(runtime, status="unscored", failure_reason=protocol_post["reason"])
            else:
                require_protocol_refusal(finding, runtime, cell)
                protocol_post.update(status="refused")
        except Exception as exc:
            # The genuine source final decision and output stay untouched.
            protocol_post.update(reason="post_runtime_verification_failed", error_type=type(exc).__name__)
            runtime = replace(runtime, status="unscored", failure_reason="post_runtime_verification_failed")
        try:
            _exclusive_record(sidecar / "protocol-post-runtime.json", FrozenRecord.from_dict(protocol_post))
        except Exception as exc:
            protocol_post.update(status="failed", reason="post_runtime_sidecar_persistence_failed", error_type=type(exc).__name__)
            runtime = replace(runtime, status="unscored", failure_reason=protocol_post["reason"])
    plan = FrozenRecord.from_dict({"schema": "train-panel-call-plan-v1", "driver": driver.experiment_id,
        "cell_key": list(cell.key), "scenario_digest": scenario.content_hash,
        "enabled_modules": cell.runtime_arm.data()["enabled"], "package_digest": package.digest,
        "package_record_digest": package.record.content_hash, "package_changes": package.record.data()["changes"],
        "package_binding": "frozen_session_lock_only_unless_explicitly_deployed", "schema_slots": list(driver.slots), "slots": list(session.slots),
        "workflow_stage": stage.detail.data()["stage"], "execution_attempts": session._attempts,
        "model_calls": session._next_call, "docker_execution": driver.docker_execution,
        "actual_token_measurement": "not_measured", **({"protocol_replay": protocol_post} if protocol_post else {})})
    if protocol_post is not None:
        try:
            _exclusive_record(sidecar / "call-plan.json", plan)
        except Exception as exc:
            protocol_post.update(status="failed", reason="post_runtime_sidecar_persistence_failed", error_type=type(exc).__name__)
            runtime = replace(runtime, status="unscored", failure_reason=protocol_post["reason"])
            # The controller persists this returned plan in its attempt record.
            # An unwritable cell sidecar cannot qualify a successful replay.
            plan = FrozenRecord.from_dict({**plan.data(), "protocol_replay": protocol_post})
    scored = None
    if scorer is not None and (not isinstance(driver, Q27ProtocolDriver) or runtime.status == "succeeded"):
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
