"""Train-only Q1.1/Q1.2 drivers with journaled M2/M3 state transitions.

The source material is typed, public fixture material bound to the current
``DataIdentity``.  Variant names are never exposed to the model as truth.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, MutableMapping

from research_loop.modular.contracts import FrozenRecord, PublicTask
from research_loop.modular.modules.context import ContextBuilder
from research_loop.modular.panel_receipts import PanelCell
from research_loop.modular.workflow import ModularWorkflow, WorkflowResult
from research_loop.ontology import ContractError, digest


def _binding(cell: PanelCell, scenario: FrozenRecord) -> dict[str, Any]:
    return {"schema": "opaque-panel-cell-binding-v1", "cell_digest": digest(cell.data())}


def _question(task: PublicTask) -> str:
    body = task.payload.data()
    return str(body.get("research_question", body.get("question", task.identity.task_id)))


def _request_material(material: FrozenRecord, evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Project one selected history record into a model-visible payload."""
    body = material.data()
    return {"schema": "typed-public-history-request-v1", "identity": body["identity"],
            "public_evidence": dict(evidence), "transition": body["transition"],
            "historical_summary": body["historical_summary"], "withdrawal": body["withdrawal"],
            "dependency": body["dependency"]}


def _final(workflow: ModularWorkflow, cell: PanelCell, scenario: FrozenRecord, model, package,
           material: FrozenRecord, active_evidence: Mapping[str, Any]) -> FrozenRecord:
    return workflow.invoke_model("final", model, instruction=(
        "Return the bounded train-only candidate. Copy required_objective_digest exactly; "
        "use outcome unknown, no evidence_ids, and programme_complete false."), module_context=FrozenRecord.from_dict({
            "panel_cell": _binding(cell, scenario), "candidate_package": package.record.data(),
            "required_objective_digest": workflow.session.objective.content_hash,
            "history_material": _request_material(material, active_evidence),
            "active_public_evidence": dict(active_evidence),
            "reconstructed_context": ContextBuilder(
                workflow.session.task.identity, budget_bytes=workflow.session.context_budget).build(
                    _question(workflow.session.task), workflow.session.evidence, workflow.session.claims,
                    mode="candidate" if "M3" in workflow.enabled else "baseline",
                    baseline_summary=material.data()["historical_summary"]).data()}))


def _candidate(value: FrozenRecord, objective: FrozenRecord) -> None:
    body = value.data()
    if set(body) != {"objective_digest", "outcome", "evidence_ids", "conclusion", "programme_complete"}:
        raise ContractError("history driver final candidate schema is invalid")
    if body["objective_digest"] != objective.content_hash or body["outcome"] != "unknown" or body["evidence_ids"] != [] or body["programme_complete"] is not False:
        raise ContractError("history driver final candidate must remain train-only unknown")


def _append(session, material: FrozenRecord, root: str, receipt: Mapping[str, Any] | None = None, evidence: Mapping[str, Any] | None = None):
    return session.evidence.append({"kind": "measurement", "root_material": {"history_id": root},
        "representation": "raw", "content": dict(evidence if evidence is not None else material.data()["public_evidence"]),
        "subject_bindings": {"task": session.task.identity.task_id},
        "independent_group": session.task.identity.group_id},
        # A caller-projected public observation is input material, never an
        # independently validated scientific admission.  It may inform the
        # explicit request material below but cannot be promoted by this driver.
        dict(receipt) if receipt is not None else {"trusted_validator": "unverified-public-observation", "validator_verified": False, "admitted": False})


def freeze_history_bundle(task: PublicTask, *, before_evidence: Mapping[str, Any], current_evidence: Mapping[str, Any], transition: Mapping[str, Any],
                          q11: Mapping[str, Mapping[str, Any]], q12: Mapping[str, Mapping[str, Any]]) -> FrozenRecord:
    """Freeze caller-supplied public records; this function never invents facts."""
    if (not isinstance(task, PublicTask) or not isinstance(before_evidence, Mapping) or not isinstance(current_evidence, Mapping)
            or not isinstance(transition, Mapping) or set(transition) != {"action", "reason"}):
        raise ContractError("history bundle needs a typed task, before/current public evidence, and transition")
    if set(q11) != {"correct", "wrong", "neutral"} or set(q12) != {"summary_only", "registered", "withdraw"}:
        raise ContractError("history bundle needs complete Q1.1 and Q1.2 variant coverage")
    for records in (q11, q12):
        for value in records.values():
            if not isinstance(value, Mapping) or set(value) != {"historical_summary", "withdrawal", "dependency"} or not isinstance(value["historical_summary"], str) or not isinstance(value["withdrawal"], bool) or not isinstance(value["dependency"], bool):
                raise ContractError("history bundle variant material is malformed")
    return FrozenRecord.from_dict({"schema": "typed-history-panel-bundle-v1", "identity": task.identity.data(),
        "before_evidence": dict(before_evidence), "current_evidence": dict(current_evidence), "transition": dict(transition), "q11": {key: dict(value) for key, value in q11.items()},
        "q12": {key: dict(value) for key, value in q12.items()}})


def select_history_material(bundle: FrozenRecord, task: PublicTask, experiment_id: str, variant: str) -> FrozenRecord:
    body = bundle.data()
    if (set(body) != {"schema", "identity", "before_evidence", "current_evidence", "transition", "q11", "q12"}
            or body["schema"] != "typed-history-panel-bundle-v1" or body["identity"] != task.identity.data()):
        raise ContractError("history bundle identity or schema mismatch")
    table = body["q11"] if experiment_id == "Q1.1" else body["q12"] if experiment_id == "Q1.2" else None
    if not isinstance(table, Mapping) or variant not in table:
        raise ContractError("history bundle lacks selected variant material")
    selected = table[variant]
    return FrozenRecord.from_dict({"schema": "typed-public-history-material-v1", "identity": task.identity.data(),
        "before_evidence": body["before_evidence"], "current_evidence": body["current_evidence"], "transition": body["transition"], "historical_summary": selected["historical_summary"], "withdrawal": selected["withdrawal"], "dependency": selected["dependency"]})


def _resolve(resolver: Callable[[PublicTask, FrozenRecord], FrozenRecord] | None, task: PublicTask, scenario: FrozenRecord, experiment_id: str, variant: str) -> FrozenRecord:
    if resolver is None:
        raise ContractError("history driver requires caller-supplied frozen history bundle resolver")
    bundle = resolver(task, scenario)
    if not isinstance(bundle, FrozenRecord) or scenario.data().get("base", {}).get("evidence") != bundle.content_hash:
        raise ContractError("history bundle does not match the scenario frozen evidence")
    return select_history_material(bundle, task, experiment_id, variant)


@dataclass(frozen=True)
class Q11HistoryDriver:
    experiment_id: str = "Q1.1"
    slots: tuple[str, ...] = ("history_baseline", "history_rebuilt", "final")
    execution_limit: int = 0
    docker_execution: str = "not_requested_by_driver"
    material_resolver: Callable[[PublicTask, FrozenRecord], FrozenRecord] | None = None

    def run(self, workflow: ModularWorkflow, *, cell: PanelCell, scenario: FrozenRecord, model, package):
        material = _resolve(self.material_resolver, workflow.session.task, scenario, "Q1.1", cell.variant)
        enabled = "M3" in workflow.enabled
        before = ContextBuilder(workflow.session.task.identity, budget_bytes=workflow.session.context_budget).build(
            _question(workflow.session.task), workflow.session.evidence, workflow.session.claims,
            mode="candidate" if enabled else "baseline", baseline_summary=material.data()["historical_summary"])
        first = workflow.invoke_model("history_baseline", model, instruction="Assess the typed public history without treating it as truth.",
            baseline_summary=material.data()["historical_summary"], module_context=FrozenRecord.from_dict({"panel_cell": _binding(cell, scenario), "history_material": _request_material(material, material.data()["before_evidence"]), "active_public_evidence": material.data()["before_evidence"], "m3": "enabled" if enabled else "frozen_control", "context_material": before.data()}))
        if enabled:
            old = _append(workflow.session, material, "q11-prior", evidence=material.data()["before_evidence"])
            workflow.session.evidence.withdraw(old.root_id, material.data()["transition"]["reason"])
            _append(workflow.session, material, "q11-current", evidence=material.data()["current_evidence"])
            after = ContextBuilder(workflow.session.task.identity, budget_bytes=workflow.session.context_budget).build(_question(workflow.session.task), workflow.session.evidence, workflow.session.claims)
            workflow._trace("operation_m3_context_rebuild", "executed", before_context=before.data(), after_context=after.data(), invalidated_evidence_root=old.root_id)
        else:
            after = before; workflow._trace("operation_m3_control", "executed", frozen_context=before.data())
        second = workflow.invoke_model("history_rebuilt", model, instruction="Assess the current typed public material after the declared context operation.",
            baseline_summary=material.data()["historical_summary"], module_context=FrozenRecord.from_dict({"panel_cell": _binding(cell, scenario), "history_material": _request_material(material, material.data()["current_evidence"] if enabled else material.data()["before_evidence"]), "active_public_evidence": material.data()["current_evidence"] if enabled else material.data()["before_evidence"], "m3": "enabled" if enabled else "frozen_control", "context_material": after.data()}))
        final = _final(workflow, cell, scenario, model, package, material,
                       material.data()["current_evidence"] if enabled else material.data()["before_evidence"]); _candidate(final, workflow.session.objective)
        return workflow._trace("stage_7" if enabled else "operation_m3_control_final", "executed", material_digest=material.content_hash), final, (first, second, final)


@dataclass(frozen=True)
class Q12DependencyDriver:
    experiment_id: str = "Q1.2"
    slots: tuple[str, ...] = ("upstream_before_withdrawal", "downstream_after_withdrawal", "final")
    execution_limit: int = 0
    docker_execution: str = "not_requested_by_driver"
    material_resolver: Callable[[PublicTask, FrozenRecord], FrozenRecord] | None = None
    admission_port: Callable[[PublicTask, FrozenRecord], Mapping[str, Any]] | None = None

    def run(self, workflow: ModularWorkflow, *, cell: PanelCell, scenario: FrozenRecord, model, package):
        material = _resolve(self.material_resolver, workflow.session.task, scenario, "Q1.2", cell.variant)
        m2, m3 = "M2" in workflow.enabled, "M3" in workflow.enabled
        root = upstream = downstream = None
        if m2:
            if self.admission_port is None:
                raise ContractError("Q1.2 M2 requires a caller-supplied verified admission receipt")
            root = _append(workflow.session, material, "q12-upstream", self.admission_port(workflow.session.task, material), material.data()["before_evidence"])
            upstream = workflow.session.claims.create("typed public upstream observation", subject_bindings={"task": workflow.session.task.identity.task_id})
            upstream = workflow.session.claims.apply(upstream.claim_id, {"supports": [root.root_id], "refutes": [], "subject_bindings": {"task": workflow.session.task.identity.task_id}}, expected_revision=0).claim
            downstream = workflow.session.claims.create("typed public downstream interpretation", subject_bindings={"task": workflow.session.task.identity.task_id})
            if material.data()["dependency"]:
                downstream = workflow.session.claims.link_dependencies(downstream.claim_id, [upstream.claim_id], expected_revision=0).claim
            workflow._trace("operation_m2_claim_revision", "executed", upstream=upstream.data(), downstream=downstream.data(), history_material=material.data())
        else:
            workflow._trace("operation_m2_control", "executed", frozen_history_material=material.data())
        before = ContextBuilder(workflow.session.task.identity, budget_bytes=workflow.session.context_budget).build(_question(workflow.session.task), workflow.session.evidence, workflow.session.claims, mode="candidate" if m3 else "baseline", baseline_summary=material.data()["historical_summary"])
        first = workflow.invoke_model("upstream_before_withdrawal", model, instruction="Assess typed upstream public material and its declared dependency state.", baseline_summary=material.data()["historical_summary"], module_context=FrozenRecord.from_dict({"panel_cell": _binding(cell, scenario), "history_material": _request_material(material, material.data()["before_evidence"]), "active_public_evidence": material.data()["before_evidence"], "claim_context": before.data(), "m2": "enabled" if m2 else "frozen_control", "m3": "enabled" if m3 else "frozen_control"}))
        revisions = ()
        if m2 and material.data()["withdrawal"]:
            workflow.session.evidence.withdraw(root.root_id, "typed public upstream withdrawal")
            revisions = workflow.session.claims.refresh_after_withdrawal()
            workflow._trace("operation_m2_dependency_invalidated", "executed", withdrawn_root=root.root_id, revisions=[item.claim.data() for item in revisions])
        if m3:
            after = ContextBuilder(workflow.session.task.identity, budget_bytes=workflow.session.context_budget).build(
                _question(workflow.session.task), workflow.session.evidence, workflow.session.claims,
                mode="candidate", baseline_summary=material.data()["historical_summary"])
            workflow._trace("operation_m3_context_rebuild", "executed", before_context=before.data(),
                            after_context=after.data(), revised_claims=[item.claim.data() for item in revisions])
        else:
            after = before
            workflow._trace("operation_m3_control", "executed", frozen_context=before.data(),
                            revised_claims=[item.claim.data() for item in revisions])
        active_evidence = material.data()["current_evidence"] if m3 else material.data()["before_evidence"]
        second = workflow.invoke_model("downstream_after_withdrawal", model, instruction="Assess the current typed dependency material after any upstream withdrawal.", baseline_summary=material.data()["historical_summary"], module_context=FrozenRecord.from_dict({"panel_cell": _binding(cell, scenario), "history_material": _request_material(material, active_evidence), "active_public_evidence": active_evidence, "reconstructed_context": after.data(), "withdrawal_applied": bool(revisions), "m2": "enabled" if m2 else "frozen_control", "m3": "enabled" if m3 else "frozen_control"}))
        final = _final(workflow, cell, scenario, model, package, material,
                       material.data()["current_evidence"] if m3 else material.data()["before_evidence"]); _candidate(final, workflow.session.objective)
        return workflow._trace("stage_7" if m3 else "operation_m3_control_final", "executed", material_digest=material.content_hash), final, (first, second, final)


def install_drivers(target: MutableMapping[str, Any], *, material_resolver: Callable[[PublicTask, FrozenRecord], FrozenRecord] | None = None,
                    admission_port: Callable[[PublicTask, FrozenRecord], Mapping[str, Any]] | None = None) -> MutableMapping[str, Any]:
    """Install only these drivers into a caller-owned registry mapping."""
    target.update({"Q1.1": Q11HistoryDriver(material_resolver=material_resolver), "Q1.2": Q12DependencyDriver(material_resolver=material_resolver, admission_port=admission_port)})
    return target
