"""Concrete TRAIN-only M1/M2/M3 plus M4 state-to-prediction cells.

This small driver deliberately reuses the lineage transition and benchmark
solver rather than creating a second controller kernel.  It is only the three
registered pairs named in ``DESIGNS``.
"""
from dataclasses import dataclass
from pathlib import Path

from research_loop.modular.benchmark_solver import run_benchmark_solve_in_session
from research_loop.modular.benchmarks.execution import DockerExecutionBroker
from research_loop.modular.combinations import default_compatibility
from research_loop.modular.contracts import FrozenRecord, PublicTask
from research_loop.modular.lineage_combination_driver import _transition, _source_binding
from research_loop.modular.lineage_combination_material import FrozenLineageMaterial, DualMaterialVerifier, check_material_inputs
from research_loop.modular.modules.improvement import CandidatePackage
from research_loop.modular.panel_receipts import PanelReceiptVerifier, RuntimeReceipt, opaque_panel_cell_binding
from research_loop.modular.runtime import AuditVerifier, RunSession
from research_loop.modular.workflow import ModularWorkflow
from research_loop.ontology import ContractError


DESIGNS = {"pair:M1+M4": ("M1", "M4"), "pair:M2+M4": ("M2", "M4"), "pair:M3+M4": ("M3", "M4")}
SLOTS = ("m4_plan", "analysis_program", "final_answer")


def registered_design(obligation, baseline):
    if obligation not in DESIGNS:
        raise ContractError("unimplemented state prediction combination obligation")
    return default_compatibility(baseline).conditional_factorial(DESIGNS[obligation])


@dataclass(frozen=True)
class StatePredictionCombinationResult:
    cell: object
    runtime: RuntimeReceipt
    solver: object | None
    transition: FrozenRecord
    joint_mechanism: FrozenRecord | None


def _material_verifier(material, verifier):
    from research_loop.modular.admission_combination import FrozenAdmissionMaterial, AdmissionMaterialVerifier
    if type(material) is FrozenAdmissionMaterial:
        if type(verifier) is not AdmissionMaterialVerifier:
            raise ContractError("M1 state combination requires the admission material verifier")
        return True
    if type(material) is not FrozenLineageMaterial or type(verifier) is not DualMaterialVerifier:
        raise ContractError("state prediction combination requires its exact lineage material verifier")
    return False


def _validate(panel, cell, task, scenario, package, material):
    from research_loop.modular.admission_combination import FrozenAdmissionMaterial
    if (getattr(panel, "obligation_id", None) not in DESIGNS or cell not in panel.cells
            or panel.design != registered_design(panel.obligation_id, cell.runtime_arm.data()["baseline_digest"])
            or not isinstance(task, PublicTask) or task.identity != cell.identity or task.content_hash != cell.task_digest
            or not isinstance(package, CandidatePackage) or package.digest != cell.package_digest
            or not isinstance(scenario, FrozenRecord) or scenario.content_hash != cell.scenario_digest
            or not isinstance(material, FrozenLineageMaterial)):
        raise ContractError("state prediction frozen cell binding mismatch")
    if ((panel.obligation_id == "pair:M1+M4" and type(material) is not FrozenAdmissionMaterial)
            or (panel.obligation_id != "pair:M1+M4" and type(material) is not FrozenLineageMaterial)):
        raise ContractError("state prediction obligation requires its exact material type")
    expected = {"schema": "state-prediction-combination-scenario-v1", "obligation_id": panel.obligation_id,
                "design_digest": panel.design.content_hash, "task_digest": task.content_hash,
                "replicate": cell.replicate, "material_digest": material.record.content_hash}
    if scenario.data() != expected:
        raise ContractError("state prediction scenario must freeze its exact material")


def _proposal_context(cell, task, transition):
    # This is intentionally public state, including M1's ordinary-buffer path.
    return FrozenRecord.from_dict({"panel_cell": opaque_panel_cell_binding(cell), "public_task": task.data(),
        "state_projection": transition.data()["public"], "proposal_phase": "competing_prediction"})


def _joint(cell, transition, proposal, plan):
    return FrozenRecord.from_dict({"schema": "state-prediction-public-joint-v1",
        "panel_cell": opaque_panel_cell_binding(cell),
        "state_projection": transition.data()["public"], "proposal": proposal.data(),
        "prediction_plan": None if plan is None else plan.payload.data(),
        "prediction_plan_digest": None if plan is None else plan.payload.content_hash})


def _runtime(cell, session, joint, status):
    trace = session.sidecar / "trace.jsonl"
    lines = trace.read_text(encoding="utf-8").splitlines()
    digest = FrozenRecord(lines[-1]).content_hash
    responses = [event.data()["data"]["response"] for event in session._events if event.data()["stage"] == "model_response"]
    output = None if status == "failed" else FrozenRecord.from_dict({"responses": responses, "terminal": session._events[-1].data()["data"]}).content_hash
    return RuntimeReceipt(cell.key, status, trace, digest, output, None if status == "succeeded" else "state/prediction or solve failed")


def _close_failure(session, cell, scenario, exc):
    last = session._events[-1].data()
    if last["stage"] == "model_response":
        session.driver_failure(driver_id=cell.coverage_id, response=FrozenRecord.from_dict(last["data"]["response"]), error_type=type(exc).__name__)
    else:
        session.controller_failure(driver_id=cell.coverage_id, error_type=type(exc).__name__, panel_cell=opaque_panel_cell_binding(cell))


def run_state_prediction_combination_cell(*, panel, cell, task, scenario, package, material, source_verifier,
        objective, sidecar, public_inputs, image, broker, model, audit_verifier, timeout_seconds=20):
    """Run one exact state transition, actual M4 registration, and shared solve."""
    _validate(panel, cell, task, scenario, package, material)
    admission = _material_verifier(material, source_verifier)
    if (not isinstance(objective, FrozenRecord) or not isinstance(sidecar, Path) or sidecar.exists()
            or not isinstance(broker, DockerExecutionBroker) or not callable(model) or not isinstance(audit_verifier, AuditVerifier)):
        raise ContractError("state prediction runtime dependencies are not closed")
    check_material_inputs(material, task, broker, public_inputs)
    source_hash = source_verifier.qualify(material, sidecar / "source-verification.json", cell_binding=_source_binding(cell))
    qualification = source_verifier.assessments(material, sidecar / "source-verification.json", cell_binding=_source_binding(cell)) if admission else None
    session = RunSession(task, package_digest=package.digest, arm=cell.runtime_arm, objective=objective, slots=SLOTS,
        execution_limit=1, sidecar=sidecar / "runtime", verifier=audit_verifier, required_audit=("measurement",),
        context_budget=material.data()["context_budget_bytes"])
    workflow = ModularWorkflow(session)
    transition = _transition(session.evidence, session.claims, session.cache, material, set(workflow.enabled), qualification)
    session._record("state_transition", {"transition": transition.data(), "source_sha256": source_hash})
    try:
        context = _proposal_context(cell, task, transition)
        proposal = workflow.invoke_model("m4_plan", model, instruction=(
            "Return a competing operational prediction plan with exactly question, branches, and budget_units. "
            "Use only the supplied public state; it cannot establish scientific validity or a score."), module_context=context)
        body = proposal.data()
        if set(body) != {"question", "branches", "budget_units"}:
            raise ContractError("state prediction proposal has the wrong contract")
        plan = workflow.predictions.freeze(body["question"], body["branches"], budget_units=body["budget_units"]) if "M4" in workflow.enabled else None
        # Off arms retain the same actual proposal as useful solver context but do not register a plan.
        session._record("state_prediction_plan", {"proposal": proposal.data(), "proposal_digest": proposal.content_hash,
            "registered_plan": None if plan is None else plan.data(), "registered_plan_digest": None if plan is None else plan.payload.content_hash})
        joint = _joint(cell, transition, proposal, plan)
        session._record("state_prediction_joint", {"joint": joint.data(), "joint_digest": joint.content_hash})
        solver = run_benchmark_solve_in_session(session=session, workflow=workflow, public_inputs=public_inputs, image=image,
            broker=broker, model=model, analysis_slot="analysis_program", final_slot="final_answer", joint_mechanism=joint,
            panel_cell_binding=FrozenRecord.from_dict(opaque_panel_cell_binding(cell)), driver_id=cell.coverage_id, timeout_seconds=timeout_seconds)
    except Exception as exc:
        if not session._terminal:
            _close_failure(session, cell, scenario, exc)
        return StatePredictionCombinationResult(cell, _runtime(cell, session, None, "failed"), None, transition, None)
    status = "succeeded" if solver.status == "execution_succeeded" else "failed"
    return StatePredictionCombinationResult(cell, _runtime(cell, session, joint, status), solver, transition, joint)


def verify_state_prediction_combination_cell(result, *, panel, task, scenario, package, material, source_verifier,
        public_inputs, broker):
    """Replay exact state material and require the plan before any solver call."""
    if not isinstance(result, StatePredictionCombinationResult):
        raise ContractError("typed state prediction result required")
    _validate(panel, result.cell, task, scenario, package, material)
    admission = _material_verifier(material, source_verifier)
    check_material_inputs(material, task, broker, public_inputs)
    PanelReceiptVerifier()._verify_runtime(result.runtime, result.cell)
    events = [FrozenRecord(line).data() for line in result.runtime.trace_path.read_text(encoding="utf-8").splitlines()]
    source_hash = source_verifier.replay(material, result.runtime.trace_path.parent.parent / "source-verification.json", cell_binding=_source_binding(result.cell))
    qualification = source_verifier.assessments(material, result.runtime.trace_path.parent.parent / "source-verification.json", cell_binding=_source_binding(result.cell)) if admission else None
    from research_loop.modular.modules.context import ContextCache
    from research_loop.modular.modules.evidence import EvidenceLedger, ClaimLedger
    enabled = set(result.cell.runtime_arm.data()["enabled"])
    # Replay uses one shared ledger, exactly as the live transition did.
    evidence = EvidenceLedger(task.identity); claims = ClaimLedger(evidence)
    transition = _transition(evidence, claims, ContextCache(), material, enabled, qualification)
    rows = [e for e in events if e["stage"] == "state_transition"]
    if len(rows) != 1 or rows[0]["data"] != {"transition": transition.data(), "source_sha256": source_hash} or transition != result.transition:
        raise ContractError("state transition replay drift")
    requests = [e["data"]["request"] for e in events if e["stage"] == "model_request"]
    if tuple(r["slot"] for r in requests) != SLOTS[:len(requests)]:
        raise ContractError("state prediction request schedule drift")
    if result.joint_mechanism is None:
        if result.solver is not None or any(r["slot"] != "m4_plan" for r in requests):
            raise ContractError("failed state prediction cell started an unbound solver")
        return FrozenRecord.from_dict({"schema":"state-prediction-combination-verification-v1", "engineering_verified":True, "scientific_effect":"not_measured"})
    proposal = next((FrozenRecord.from_dict(e["data"]["response"]) for e in events if e["stage"] == "model_response" and e["data"]["request_digest"] == next(r for r in [x["data"] for x in events if x["stage"] == "model_request"] if r["request"]["slot"] == "m4_plan")["request_digest"]), None)
    if proposal is None or requests[0]["module_context"] != _proposal_context(result.cell, task, transition).data():
        raise ContractError("M4 did not consume actual transitioned public state")
    if "M4" in enabled:
        plan_rows = [e for e in events if e["stage"] == "state_prediction_plan"]
        if len(plan_rows) != 1 or plan_rows[0]["data"].get("registered_plan") is None:
            raise ContractError("M4-on did not use PredictionRegistry")
        from research_loop.modular.modules.predictions import PredictionRegistry
        registry = PredictionRegistry(task.identity, storage_path=result.runtime.trace_path.parent / "predictions.jsonl")
        registered = plan_rows[0]["data"]["registered_plan"]
        plan_id = registered.get("plan_id")
        if not isinstance(plan_id, str) or registry.plan(plan_id).data() != registered:
            raise ContractError("state prediction journal does not match persistent registry")
        if result.joint_mechanism.data().get("prediction_plan") != registered["payload"]:
            raise ContractError("solver joint did not consume the actual registered prediction plan")
    expected = _joint(result.cell, transition, proposal, None) if "M4" not in enabled else result.joint_mechanism
    if "M4" not in enabled and result.joint_mechanism != expected:
        raise ContractError("M4-off did not preserve its ordinary proposal")
    joint_events = [e for e in events if e["stage"] == "state_prediction_joint"]
    if len(joint_events) != 1 or joint_events[0]["data"].get("joint") != result.joint_mechanism.data():
        raise ContractError("state prediction joint drift")
    joint_i = events.index(joint_events[0]); analysis_i = next((i for i,e in enumerate(events) if e["stage"] == "model_request" and e["data"]["request"]["slot"] == "analysis_program"), None)
    if analysis_i is not None and joint_i >= analysis_i:
        raise ContractError("prediction plan was not frozen before Docker solver")
    return FrozenRecord.from_dict({"schema":"state-prediction-combination-verification-v1", "engineering_verified":True,
        "transition_digest":transition.content_hash, "joint_digest":result.joint_mechanism.content_hash, "scientific_effect":"not_measured"})
