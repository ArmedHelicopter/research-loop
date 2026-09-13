"""Train-only Q1.1/Q1.2 drivers with journaled M2/M3 state transitions."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, MutableMapping

from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask
from research_loop.modular.modules.context import ContextBuilder
from research_loop.modular.panel_receipts import PanelCell, opaque_panel_cell_binding
from research_loop.modular.workflow import ModularWorkflow
from research_loop.ontology import ContractError, canonical

AdmissionPort = Callable[[PublicTask, FrozenRecord], Mapping[str, Any]]


def _binding(cell: PanelCell, scenario: FrozenRecord) -> dict[str, Any]:
    return opaque_panel_cell_binding(cell)


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _record(material: FrozenRecord, phase: str) -> FrozenRecord:
    if phase not in {"before", "current"}:
        raise ContractError("history record phase is invalid")
    body = material.data()
    return FrozenRecord.from_dict({"schema": "typed-public-history-record-v1", "identity": body["identity"],
                                   "phase": phase, "evidence": body[phase + "_evidence"]})


def _context(workflow: ModularWorkflow, *, mode: str, baseline_summary: str):
    """Use the same cached, canonical task context as RunSession.invoke."""
    return workflow.session.cache.get_or_build(
        ContextBuilder(workflow.session.task.identity, budget_bytes=workflow.session.context_budget),
        canonical(workflow.session.task.payload.data()), workflow.session.evidence, workflow.session.claims,
        mode=mode, baseline_summary=baseline_summary)


def _request_material(material: FrozenRecord, record: FrozenRecord, *, phase: str) -> dict[str, Any]:
    """Expose one selected record; never send the inactive record or other variants."""
    body = material.data()
    result = {"schema": "typed-public-history-request-v2", "identity": body["identity"],
              "phase": phase, "public_record": record.data()}
    if body["experiment_id"] == "Q1.1":
        result["historical_summary"] = body["historical_summary"]
    elif phase == "before":
        result.update({"pre_transition_summary": body["pre_transition_summary"],
                       "upstream_claim": body["upstream_claim"]})
    else:
        result.update({"transition": body["transition"], "post_transition_summary": body["post_transition_summary"],
                       "downstream_claim": body["downstream_claim"], "withdrawal": body["withdrawal"],
                       "dependency": body["dependency"]})
    return result


def public_admission_receipt(receipt: Mapping[str, Any]) -> dict[str, Any]:
    """Keep subject/qualification, with an opaque authority binding for models."""
    result = dict(receipt)
    result["trusted_validator"] = FrozenRecord.from_dict({"authority_id": receipt["trusted_validator"]}).content_hash
    return result


def _admission_context(record: FrozenRecord, receipt: Mapping[str, Any] | None) -> dict[str, Any]:
    result = {"public_record_digest": record.content_hash}
    if receipt is not None:
        result["admission_receipt"] = public_admission_receipt(receipt)
    return result


def _append(session, *, record: FrozenRecord, root: str, receipt: Mapping[str, Any]):
    """Append only a caller-admitted observation, bound to the frozen record."""
    observation = {"kind": "measurement",
        "root_material": {"history_id": root, "public_record_digest": record.content_hash},
        "representation": "raw", "content": record.data()["evidence"],
        "subject_bindings": {"task": session.task.identity.task_id},
        "independent_group": session.task.identity.group_id}
    receipt_fields = {key: public_admission_receipt(receipt).get(key) for key in ("trusted_validator", "validator_verified", "admitted")}
    return session.evidence.append(observation, receipt_fields)


def _admit(port: AdmissionPort | None, task: PublicTask, record: FrozenRecord, *, purpose: str) -> Mapping[str, Any]:
    if port is None:
        raise ContractError(purpose + " requires a caller-supplied verified admission receipt")
    receipt = port(task, record)
    if (not isinstance(receipt, Mapping) or set(receipt) != {"record_digest", "trusted_validator", "validator_verified", "admitted"}
            or receipt.get("record_digest") != record.content_hash or not _nonempty(receipt.get("trusted_validator"))
            or receipt.get("validator_verified") is not True or receipt.get("admitted") is not True):
        raise ContractError("history admission receipt does not bind the supplied public record")
    return dict(receipt)


def _validate_transition(transition: Any) -> None:
    if (not isinstance(transition, Mapping) or set(transition) != {"action", "reason"}
            or transition["action"] != "replace_public_measurement" or not _nonempty(transition["reason"])):
        raise ContractError("history transition must be replace_public_measurement with a nonempty reason")


def _validate_bundle_body(task: PublicTask, body: Mapping[str, Any]) -> None:
    if (set(body) != {"schema", "identity", "before_evidence", "current_evidence", "transition", "q11", "q12"}
            or body["schema"] != "typed-history-panel-bundle-v2" or body["identity"] != task.identity.data()
            or not isinstance(body["before_evidence"], Mapping) or not isinstance(body["current_evidence"], Mapping)):
        raise ContractError("history bundle identity or schema mismatch")
    _validate_transition(body["transition"])
    q11, q12 = body["q11"], body["q12"]
    if not isinstance(q11, Mapping) or set(q11) != {"correct", "wrong", "neutral"}:
        raise ContractError("history bundle needs complete Q1.1 variant coverage")
    if not isinstance(q12, Mapping) or set(q12) != {"summary_only", "registered", "withdraw"}:
        raise ContractError("history bundle needs complete Q1.2 variant coverage")
    for item in q11.values():
        if not isinstance(item, Mapping) or set(item) != {"historical_summary"} or not _nonempty(item["historical_summary"]):
            raise ContractError("Q1.1 history material is malformed")
    required_q12 = {"pre_transition_summary", "post_transition_summary", "upstream_claim", "downstream_claim", "withdrawal", "dependency"}
    for item in q12.values():
        if (not isinstance(item, Mapping) or set(item) != required_q12
                or not all(_nonempty(item[key]) for key in ("pre_transition_summary", "post_transition_summary", "upstream_claim", "downstream_claim"))
                or type(item["withdrawal"]) is not bool or type(item["dependency"]) is not bool):
            raise ContractError("Q1.2 history material is malformed")


def freeze_history_bundle(task: PublicTask, *, before_evidence: Mapping[str, Any], current_evidence: Mapping[str, Any],
                          transition: Mapping[str, Any], q11: Mapping[str, Mapping[str, Any]],
                          q12: Mapping[str, Mapping[str, Any]]) -> FrozenRecord:
    """Freeze caller-supplied public records; this function never invents facts."""
    if (not isinstance(task, PublicTask) or not all(isinstance(item, Mapping)
            for item in (before_evidence, current_evidence, transition, q11, q12))):
        raise ContractError("history bundle needs typed task and mapping inputs")
    body = {"schema": "typed-history-panel-bundle-v2", "identity": task.identity.data(),
            "before_evidence": dict(before_evidence), "current_evidence": dict(current_evidence),
            "transition": dict(transition), "q11": {key: dict(value) for key, value in q11.items()},
            "q12": {key: dict(value) for key, value in q12.items()}}
    _validate_bundle_body(task, body)
    return FrozenRecord.from_dict(body)


def select_history_material(bundle: FrozenRecord, task: PublicTask, experiment_id: str, variant: str) -> FrozenRecord:
    body = bundle.data()
    _validate_bundle_body(task, body)
    if experiment_id == "Q1.1":
        if variant not in body["q11"]:
            raise ContractError("history bundle lacks selected Q1.1 material")
        selected = body["q11"][variant]
    elif experiment_id == "Q1.2":
        if variant not in body["q12"]:
            raise ContractError("history bundle lacks selected Q1.2 material")
        selected = body["q12"][variant]
    else:
        raise ContractError("history driver experiment is unsupported")
    return FrozenRecord.from_dict({"schema": "typed-public-history-material-v2", "experiment_id": experiment_id,
        "identity": body["identity"], "before_evidence": body["before_evidence"],
        "current_evidence": body["current_evidence"], "transition": body["transition"], **selected})


def _resolve(resolver: Callable[[PublicTask, FrozenRecord], FrozenRecord] | None, task: PublicTask,
             scenario: FrozenRecord, experiment_id: str, variant: str) -> FrozenRecord:
    if resolver is None:
        body = scenario.data().get("controller_input", {})
        if body.get("schema") != "history-panel-controller-v1" or not isinstance(body.get("material_bundle"), Mapping):
            raise ContractError("history driver requires a compiler-bound frozen history bundle")
        bundle = FrozenRecord.from_dict(body["material_bundle"])
    else:
        bundle = resolver(task, scenario)
    if not isinstance(bundle, FrozenRecord) or scenario.data().get("base", {}).get("evidence") != bundle.content_hash:
        raise ContractError("history bundle does not match the scenario frozen evidence")
    return select_history_material(bundle, task, experiment_id, variant)


def history_panel_injection(experiment_id: str, variant: str, *, task: FrozenRecord, evidence: FrozenRecord) -> Mapping[str, Any]:
    """Compiler projection; the selected variant is resolved inside the driver."""
    if evidence.data().get("schema") != "typed-history-panel-bundle-v2":
        # Planning fixtures stay distinct from runtime-ready public materials.
        if experiment_id == "Q1.1":
            from research_loop.modular.scenarios_core import core_injection
            return core_injection(experiment_id, variant)
        from research_loop.modular.scenarios_history import history_injection
        return history_injection(experiment_id, variant)
    task_body = task.data()
    public_task = PublicTask(DataIdentity.parse(task_body["identity"]), FrozenRecord.from_dict(task_body["payload"]))
    select_history_material(evidence, public_task, experiment_id, variant)
    return {"schema": "history-panel-controller-v1", "material_bundle": evidence.data()}


def _candidate(value: FrozenRecord, objective: FrozenRecord) -> None:
    body = value.data()
    if set(body) != {"objective_digest", "outcome", "evidence_ids", "conclusion", "programme_complete"}:
        raise ContractError("history driver final candidate schema is invalid")
    if body["objective_digest"] != objective.content_hash or body["outcome"] != "unknown" or body["evidence_ids"] != [] or body["programme_complete"] is not False:
        raise ContractError("history driver final candidate must remain train-only unknown")


def _final(workflow: ModularWorkflow, cell: PanelCell, scenario: FrozenRecord, model, package, material: FrozenRecord,
           record: FrozenRecord, context, baseline_summary: str, receipt: Mapping[str, Any] | None) -> FrozenRecord:
    return workflow.invoke_model("final", model, instruction=(
        "Return the bounded train-only candidate. Copy required_objective_digest exactly; "
        "use outcome unknown, no evidence_ids, and programme_complete false."), baseline_summary=baseline_summary,
        module_context=FrozenRecord.from_dict({"panel_cell": _binding(cell, scenario),
            "required_objective_digest": workflow.session.objective.content_hash,
            "history_material": _request_material(material, record, phase="current"),
            "reconstructed_context": context.public_data(), **_admission_context(record, receipt)}))


@dataclass(frozen=True)
class Q11HistoryDriver:
    experiment_id: str = "Q1.1"
    slots: tuple[str, ...] = ("history_baseline", "history_rebuilt", "final")
    execution_limit: int = 0
    docker_execution: str = "not_requested_by_driver"
    material_resolver: Callable[[PublicTask, FrozenRecord], FrozenRecord] | None = None
    admission_port: AdmissionPort | None = None

    def run(self, workflow: ModularWorkflow, *, cell: PanelCell, scenario: FrozenRecord, model, package):
        material = _resolve(self.material_resolver, workflow.session.task, scenario, "Q1.1", cell.variant)
        before_record, current_record = _record(material, "before"), _record(material, "current")
        before_receipt = _admit(self.admission_port, workflow.session.task, before_record, purpose="Q1.1 before record")
        before_root = _append(workflow.session, record=before_record, root="public-history-0", receipt=before_receipt)
        enabled = "M3" in workflow.enabled
        summary = material.data()["historical_summary"]
        before = _context(workflow, mode="candidate" if enabled else "baseline", baseline_summary=summary)
        first = workflow.invoke_model("history_baseline", model, instruction="Assess the typed public history without treating it as truth.",
            baseline_summary=summary, module_context=FrozenRecord.from_dict({
                "panel_cell": _binding(cell, scenario), "history_material": _request_material(material, before_record, phase="before"),
                "context_material": before.public_data(),
                **_admission_context(before_record, before_receipt)}))
        current_receipt = _admit(self.admission_port, workflow.session.task, current_record, purpose="Q1.1 current record")
        workflow.session.evidence.withdraw(before_root.root_id, material.data()["transition"]["reason"])
        current_root = _append(workflow.session, record=current_record, root="public-history-1", receipt=current_receipt)
        workflow._trace("operation_public_record_replacement", "executed", before_record_digest=before_record.content_hash,
                        current_record_digest=current_record.content_hash, withdrawn_root=before_root.root_id,
                        current_root=current_root.root_id)
        if enabled:
            after = _context(workflow, mode="candidate", baseline_summary=summary)
            workflow._trace("operation_m3_context_rebuild", "executed", before_context=before.data(), after_context=after.data(),
                            invalidated_evidence_root=before_root.root_id)
        else:
            after = before
            workflow._trace("operation_m3_control", "executed", frozen_context=before.data())
        second = workflow.invoke_model("history_rebuilt", model, instruction="Assess the current typed public material after the declared context operation.",
            baseline_summary=summary, module_context=FrozenRecord.from_dict({
                "panel_cell": _binding(cell, scenario), "history_material": _request_material(material, current_record, phase="current"),
                "context_material": after.public_data(),
                **_admission_context(current_record, current_receipt)}))
        final = _final(workflow, cell, scenario, model, package, material, current_record, after, summary, current_receipt)
        _candidate(final, workflow.session.objective)
        return workflow._trace("stage_7" if enabled else "operation_m3_control_final", "executed", material_digest=material.content_hash), final, (first, second, final)


@dataclass(frozen=True)
class Q12DependencyDriver:
    experiment_id: str = "Q1.2"
    slots: tuple[str, ...] = ("upstream_before_withdrawal", "downstream_after_withdrawal", "final")
    execution_limit: int = 0
    docker_execution: str = "not_requested_by_driver"
    material_resolver: Callable[[PublicTask, FrozenRecord], FrozenRecord] | None = None
    admission_port: AdmissionPort | None = None

    def run(self, workflow: ModularWorkflow, *, cell: PanelCell, scenario: FrozenRecord, model, package):
        material = _resolve(self.material_resolver, workflow.session.task, scenario, "Q1.2", cell.variant)
        before_record, current_record = _record(material, "before"), _record(material, "current")
        m2, m3 = "M2" in workflow.enabled, "M3" in workflow.enabled
        before_receipt = None
        root = upstream = downstream = None
        if m2:
            before_receipt = _admit(self.admission_port, workflow.session.task, before_record, purpose="Q1.2 M2 before record")
            root = _append(workflow.session, record=before_record, root="public-history-0", receipt=before_receipt)
            bindings = {"task": workflow.session.task.identity.task_id}
            upstream = workflow.session.claims.create(material.data()["upstream_claim"], subject_bindings=bindings)
            upstream = workflow.session.claims.apply(upstream.claim_id, {"supports": [root.root_id], "refutes": [], "subject_bindings": bindings}, expected_revision=0).claim
            downstream = workflow.session.claims.create(material.data()["downstream_claim"], subject_bindings=bindings)
            if material.data()["dependency"]:
                downstream = workflow.session.claims.apply(downstream.claim_id, {"supports": [root.root_id], "refutes": [], "subject_bindings": bindings}, expected_revision=0).claim
                downstream = workflow.session.claims.link_dependencies(downstream.claim_id, [upstream.claim_id], expected_revision=1).claim
            workflow._trace("operation_m2_claim_revision", "executed", upstream=upstream.data(), downstream=downstream.data(),
                            before_record_digest=before_record.content_hash)
        else:
            workflow._trace("operation_m2_control", "executed", before_record_digest=before_record.content_hash)
        pre_summary = material.data()["pre_transition_summary"]
        before = _context(workflow, mode="candidate" if m3 else "baseline", baseline_summary=pre_summary)
        first = workflow.invoke_model("upstream_before_withdrawal", model,
            instruction="Assess typed upstream public material and its declared dependency state.", baseline_summary=pre_summary,
            module_context=FrozenRecord.from_dict({"panel_cell": _binding(cell, scenario),
                "history_material": _request_material(material, before_record, phase="before"), "claim_context": before.public_data(),
                **_admission_context(before_record, before_receipt)}))
        revisions = ()
        if m2 and material.data()["withdrawal"]:
            workflow.session.evidence.withdraw(root.root_id, material.data()["transition"]["reason"])
            revisions = workflow.session.claims.refresh_after_withdrawal()
            workflow._trace("operation_m2_dependency_invalidated", "executed", withdrawn_root=root.root_id,
                            revisions=[item.claim.data() for item in revisions])
        if m3:
            after = _context(workflow, mode="candidate", baseline_summary=pre_summary)
            workflow._trace("operation_m3_context_rebuild", "executed", before_context=before.data(), after_context=after.data(),
                            revised_claims=[item.claim.data() for item in revisions])
        else:
            after = before
            workflow._trace("operation_m3_control", "executed", frozen_context=before.data(),
                            revised_claims=[item.claim.data() for item in revisions])
        second = workflow.invoke_model("downstream_after_withdrawal", model,
            instruction="Assess the current typed dependency material after any upstream withdrawal.", baseline_summary=pre_summary,
            module_context=FrozenRecord.from_dict({"panel_cell": _binding(cell, scenario),
                "history_material": _request_material(material, current_record, phase="current"),
                "reconstructed_context": after.public_data(), "withdrawal_applied": bool(revisions),
                **_admission_context(current_record, None)}))
        final = _final(workflow, cell, scenario, model, package, material, current_record, after, pre_summary, None)
        _candidate(final, workflow.session.objective)
        return workflow._trace("stage_7" if m3 else "operation_m3_control_final", "executed", material_digest=material.content_hash), final, (first, second, final)


def install_drivers(target: MutableMapping[str, Any], *, material_resolver: Callable[[PublicTask, FrozenRecord], FrozenRecord] | None = None,
                    admission_port: AdmissionPort | None = None) -> MutableMapping[str, Any]:
    """Install only these drivers into a caller-owned registry mapping."""
    target.update({"Q1.1": Q11HistoryDriver(material_resolver=material_resolver, admission_port=admission_port),
                   "Q1.2": Q12DependencyDriver(material_resolver=material_resolver, admission_port=admission_port)})
    return target
