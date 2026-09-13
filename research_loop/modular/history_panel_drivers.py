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
from research_loop.ontology import ContractError


def _binding(cell: PanelCell, scenario: FrozenRecord) -> dict[str, Any]:
    return {"experiment_id": cell.coverage_id, "variant": cell.variant,
            "replicate": cell.replicate, "arm_id": cell.arm_id,
            "scenario_digest": scenario.content_hash}


def _question(task: PublicTask) -> str:
    body = task.payload.data()
    return str(body.get("research_question", body.get("question", task.identity.task_id)))


def _final(workflow: ModularWorkflow, cell: PanelCell, scenario: FrozenRecord, model, package, material: FrozenRecord) -> FrozenRecord:
    return workflow.invoke_model("final", model, instruction=(
        "Return the bounded train-only candidate. Copy required_objective_digest exactly; "
        "use outcome unknown, no evidence_ids, and programme_complete false."), module_context=FrozenRecord.from_dict({
            "panel_cell": _binding(cell, scenario), "candidate_package": package.record.data(),
            "required_objective_digest": workflow.session.objective.content_hash,
            "history_material": material.data(), "reconstructed_context": ContextBuilder(
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


def _append(session, material: FrozenRecord, root: str):
    return session.evidence.append({"kind": "measurement", "root_material": {"history_id": root},
        "representation": "raw", "content": material.data()["public_evidence"],
        "subject_bindings": {"task": session.task.identity.task_id},
        "independent_group": session.task.identity.group_id},
        {"trusted_validator": "public-fixture", "validator_verified": True, "admitted": True})


def freeze_history_bundle(task: PublicTask, *, public_evidence: Mapping[str, Any],
                          q11: Mapping[str, Mapping[str, Any]], q12: Mapping[str, Mapping[str, Any]]) -> FrozenRecord:
    """Freeze caller-supplied public records; this function never invents facts."""
    if not isinstance(task, PublicTask) or not isinstance(public_evidence, Mapping):
        raise ContractError("history bundle needs a typed task and public evidence")
    if set(q11) != {"correct", "wrong", "neutral"} or set(q12) != {"summary_only", "registered", "withdraw"}:
        raise ContractError("history bundle needs complete Q1.1 and Q1.2 variant coverage")
    for records in (q11, q12):
        for value in records.values():
            if not isinstance(value, Mapping) or set(value) != {"historical_summary", "withdrawal"} or not isinstance(value["historical_summary"], str) or not isinstance(value["withdrawal"], bool):
                raise ContractError("history bundle variant material is malformed")
    return FrozenRecord.from_dict({"schema": "typed-history-panel-bundle-v1", "identity": task.identity.data(),
        "public_evidence": dict(public_evidence), "q11": {key: dict(value) for key, value in q11.items()},
        "q12": {key: dict(value) for key, value in q12.items()}})


def select_history_material(bundle: FrozenRecord, task: PublicTask, experiment_id: str, variant: str) -> FrozenRecord:
    body = bundle.data()
    if (set(body) != {"schema", "identity", "public_evidence", "q11", "q12"}
            or body["schema"] != "typed-history-panel-bundle-v1" or body["identity"] != task.identity.data()):
        raise ContractError("history bundle identity or schema mismatch")
    table = body["q11"] if experiment_id == "Q1.1" else body["q12"] if experiment_id == "Q1.2" else None
    if not isinstance(table, Mapping) or variant not in table:
        raise ContractError("history bundle lacks selected variant material")
    selected = table[variant]
    return FrozenRecord.from_dict({"schema": "typed-public-history-material-v1", "identity": task.identity.data(),
        "public_evidence": body["public_evidence"], "historical_summary": selected["historical_summary"], "withdrawal": selected["withdrawal"]})


def _resolve(resolver: Callable[[PublicTask, FrozenRecord], FrozenRecord] | None, task: PublicTask, scenario: FrozenRecord, experiment_id: str, variant: str) -> FrozenRecord:
    if resolver is None:
        raise ContractError("history driver requires caller-supplied frozen history bundle resolver")
    return select_history_material(resolver(task, scenario), task, experiment_id, variant)


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
            baseline_summary=material.data()["historical_summary"], module_context=FrozenRecord.from_dict({"panel_cell": _binding(cell, scenario), "history_material": material.data(), "m3": "enabled" if enabled else "frozen_control", "context_material": before.data()}))
        if enabled:
            old = _append(workflow.session, material, "q11-prior")
            workflow.session.evidence.withdraw(old.root_id, "public history superseded by current public material")
            _append(workflow.session, material, "q11-current")
            after = ContextBuilder(workflow.session.task.identity, budget_bytes=workflow.session.context_budget).build(_question(workflow.session.task), workflow.session.evidence, workflow.session.claims)
            workflow._trace("operation_m3_context_rebuild", "executed", before_context=before.data(), after_context=after.data(), invalidated_evidence_root=old.root_id)
        else:
            after = before; workflow._trace("operation_m3_control", "executed", frozen_context=before.data())
        second = workflow.invoke_model("history_rebuilt", model, instruction="Assess the current typed public material after the declared context operation.",
            baseline_summary=material.data()["historical_summary"], module_context=FrozenRecord.from_dict({"panel_cell": _binding(cell, scenario), "history_material": material.data(), "m3": "enabled" if enabled else "frozen_control", "context_material": after.data()}))
        final = _final(workflow, cell, scenario, model, package, material); _candidate(final, workflow.session.objective)
        return workflow._trace("stage_7" if enabled else "operation_m3_control_final", "executed", material_digest=material.content_hash), final, (first, second, final)


@dataclass(frozen=True)
class Q12DependencyDriver:
    experiment_id: str = "Q1.2"
    slots: tuple[str, ...] = ("upstream_before_withdrawal", "downstream_after_withdrawal", "final")
    execution_limit: int = 0
    docker_execution: str = "not_requested_by_driver"
    material_resolver: Callable[[PublicTask, FrozenRecord], FrozenRecord] | None = None

    def run(self, workflow: ModularWorkflow, *, cell: PanelCell, scenario: FrozenRecord, model, package):
        material = _resolve(self.material_resolver, workflow.session.task, scenario, "Q1.2", cell.variant)
        m2, m3 = "M2" in workflow.enabled, "M3" in workflow.enabled
        root = upstream = downstream = None
        if m2:
            root = _append(workflow.session, material, "q12-upstream")
            upstream = workflow.session.claims.create("typed public upstream observation", subject_bindings={"task": workflow.session.task.identity.task_id})
            upstream = workflow.session.claims.apply(upstream.claim_id, {"supports": [root.root_id], "refutes": [], "subject_bindings": {"task": workflow.session.task.identity.task_id}}, expected_revision=0).claim
            downstream = workflow.session.claims.create("typed public downstream interpretation", subject_bindings={"task": workflow.session.task.identity.task_id})
            if cell.variant != "summary_only":
                downstream = workflow.session.claims.link_dependencies(downstream.claim_id, [upstream.claim_id], expected_revision=0).claim
            workflow._trace("operation_m2_claim_revision", "executed", upstream=upstream.data(), downstream=downstream.data(), history_material=material.data())
        else:
            workflow._trace("operation_m2_control", "executed", frozen_history_material=material.data())
        before = ContextBuilder(workflow.session.task.identity, budget_bytes=workflow.session.context_budget).build(_question(workflow.session.task), workflow.session.evidence, workflow.session.claims, mode="candidate" if m3 else "baseline", baseline_summary=material.data()["historical_summary"])
        first = workflow.invoke_model("upstream_before_withdrawal", model, instruction="Assess typed upstream public material and its declared dependency state.", baseline_summary=material.data()["historical_summary"], module_context=FrozenRecord.from_dict({"panel_cell": _binding(cell, scenario), "history_material": material.data(), "claim_context": before.data(), "m2": "enabled" if m2 else "frozen_control", "m3": "enabled" if m3 else "frozen_control"}))
        revisions = ()
        if m2 and cell.variant == "withdraw":
            workflow.session.evidence.withdraw(root.root_id, "typed public upstream withdrawal")
            revisions = workflow.session.claims.refresh_after_withdrawal()
            workflow._trace("operation_m2_dependency_invalidated", "executed", withdrawn_root=root.root_id, revisions=[item.claim.data() for item in revisions])
        after = ContextBuilder(workflow.session.task.identity, budget_bytes=workflow.session.context_budget).build(_question(workflow.session.task), workflow.session.evidence, workflow.session.claims, mode="candidate" if m3 else "baseline", baseline_summary=material.data()["historical_summary"])
        workflow._trace("operation_m3_context_rebuild" if m3 else "operation_m3_control", "executed", before_context=before.data(), after_context=after.data(), revised_claims=[item.claim.data() for item in revisions])
        second = workflow.invoke_model("downstream_after_withdrawal", model, instruction="Assess the current typed dependency material after any upstream withdrawal.", baseline_summary=material.data()["historical_summary"], module_context=FrozenRecord.from_dict({"panel_cell": _binding(cell, scenario), "history_material": material.data(), "reconstructed_context": after.data(), "withdrawal_applied": bool(revisions), "m2": "enabled" if m2 else "frozen_control", "m3": "enabled" if m3 else "frozen_control"}))
        final = _final(workflow, cell, scenario, model, package, material); _candidate(final, workflow.session.objective)
        return workflow._trace("stage_7" if m3 else "operation_m3_control_final", "executed", material_digest=material.content_hash), final, (first, second, final)


def install_drivers(target: MutableMapping[str, Any], *, material_resolver: Callable[[PublicTask, FrozenRecord], FrozenRecord] | None = None) -> MutableMapping[str, Any]:
    """Install only these drivers into a caller-owned registry mapping."""
    target.update({"Q1.1": Q11HistoryDriver(material_resolver=material_resolver), "Q1.2": Q12DependencyDriver(material_resolver=material_resolver)})
    return target
