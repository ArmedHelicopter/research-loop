"""Caller-bound train-only drivers for Q2.5 evidence polarity and Q2.6 goal locks.

These drivers deliberately expose only caller public material to models.  Typed
admission checks, variants, arm choices, and lock enforcement remain journal
state.  They are installable locally until the production registry is wired.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, MutableMapping

from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask, required_text, strict_bool
from research_loop.modular.modules.admission import AuditItem, EvidenceAdmission, ScientificState
from research_loop.modular.panel_receipts import opaque_panel_cell_binding
from research_loop.ontology import ContractError

_Q25 = ("invalid_positive", "invalid_negative", "valid_negative")
_Q26 = ("secondary_win", "maintenance", "late_pivot")
_CHECKS = {"trusted_validator", "validator_verified", "execution_success", "required_audit", "audit", "subject_bindings", "evidence_ids"}


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping): raise ContractError(f"{name} must be a mapping")
    return value


def _checks(value: Any, identity: DataIdentity) -> Mapping[str, Any]:
    value = _mapping(value, "caller admission checks")
    if set(value) != _CHECKS or value.get("subject_bindings", {}).get("task") != identity.task_id:
        raise ContractError("caller admission checks do not bind the task")
    required_text(value["trusted_validator"], "trusted validator")
    strict_bool(value["validator_verified"], "validator verified"); strict_bool(value["execution_success"], "execution success")
    if (not isinstance(value["required_audit"], list) or not value["required_audit"]
            or not isinstance(value["audit"], list) or not isinstance(value["evidence_ids"], list) or not value["evidence_ids"]):
        raise ContractError("caller admission checks are incomplete")
    try: audit = [AuditItem(**_mapping(item, "audit item")) for item in value["audit"]]
    except TypeError as exc: raise ContractError("caller audit item is malformed") from exc
    if {item.name for item in audit} != set(value["required_audit"]): raise ContractError("caller audit coverage is incomplete")
    return value


def freeze_polarity_goal_bundle(task: PublicTask, *, q25: Mapping[str, Mapping[str, Any]],
                                q26: Mapping[str, Mapping[str, Any]]) -> FrozenRecord:
    if not isinstance(task, PublicTask): raise ContractError("bundle requires a public task")
    body = {"schema": "typed-polarity-goal-panel-bundle-v1", "identity": task.identity.data(),
            "payload_digest": task.payload.content_hash, "q25": {k: dict(v) for k, v in q25.items()},
            "q26": {k: dict(v) for k, v in q26.items()}}
    if set(body["q25"]) != set(_Q25) or set(body["q26"]) != set(_Q26): raise ContractError("bundle variant coverage mismatch")
    for item in body["q25"].values():
        if set(item) != {"public_material", "admission_checks"} or not _mapping(item["public_material"], "public material"):
            raise ContractError("Q2.5 material malformed")
        _checks(item["admission_checks"], task.identity)
    for item in body["q26"].values():
        if set(item) != {"public_material", "locked_objective", "proposal", "admission_checks"}:
            raise ContractError("Q2.6 material malformed")
        if not _mapping(item["public_material"], "public material") or not _mapping(item["proposal"], "proposal"):
            raise ContractError("Q2.6 public material malformed")
        locked = FrozenRecord.from_dict(dict(_mapping(item["locked_objective"], "locked objective")))
        if not locked.data(): raise ContractError("locked objective is empty")
        _checks(item["admission_checks"], task.identity)
    return FrozenRecord.from_dict(body)


def polarity_goal_injection(experiment_id: str, variant: str, *, task: FrozenRecord, evidence: FrozenRecord) -> Mapping[str, Any]:
    body = evidence.data()
    if body.get("schema") != "typed-polarity-goal-panel-bundle-v1":
        return {"fixture_only": True}
    public = PublicTask(DataIdentity.parse(task.data()["identity"]), FrozenRecord.from_dict(task.data()["payload"]))
    bundle = freeze_polarity_goal_bundle(public, q25=body["q25"], q26=body["q26"])
    key = "q25" if experiment_id == "Q2.5" else "q26" if experiment_id == "Q2.6" else None
    if key is None or variant not in body[key]: raise ContractError("unregistered polarity/goal variant")
    return {"schema": "polarity-goal-controller-v1", "bundle": bundle.data()}


def _material(task: PublicTask, scenario: FrozenRecord, experiment: str, variant: str) -> Mapping[str, Any]:
    controller = _mapping(scenario.data().get("controller_input"), "controller input")
    if controller.get("schema") != "polarity-goal-controller-v1": raise ContractError("typed polarity/goal material is required")
    bundle = FrozenRecord.from_dict(dict(_mapping(controller.get("bundle"), "bundle")))
    body = bundle.data()
    remade = freeze_polarity_goal_bundle(task, q25=body.get("q25", {}), q26=body.get("q26", {}))
    if remade.content_hash != bundle.content_hash or scenario.data().get("base", {}).get("evidence") != bundle.content_hash:
        raise ContractError("scenario does not bind its caller material")
    return body["q25" if experiment == "Q2.5" else "q26"][variant]


def _judgement(response: FrozenRecord) -> tuple[ScientificState, str]:
    body = response.data()
    if set(body) != {"validity", "support", "novelty", "investment", "outcome"} or body["outcome"] not in {"positive", "negative"}:
        raise ContractError("driver judgement has invalid schema")
    return ScientificState(body["validity"], body["support"], body["novelty"], body["investment"]), body["outcome"]


def _candidate(response: FrozenRecord, objective: FrozenRecord) -> None:
    body = response.data()
    if (set(body) != {"objective_digest", "outcome", "evidence_ids", "conclusion", "programme_complete"}
            or body["objective_digest"] != objective.content_hash or body["outcome"] != "unknown"
            or body["evidence_ids"] != [] or body["programme_complete"] is not False):
        raise ContractError("final candidate must remain bounded and unknown")


@dataclass(frozen=True)
class _Driver:
    experiment_id: str
    slots: tuple[str, ...] = ("assessment", "final")
    execution_limit: int = 0
    docker_execution: str = "not_requested_by_driver"

    def run(self, workflow, *, cell, scenario: FrozenRecord, model, package):
        material = _material(workflow.session.task, scenario, self.experiment_id, cell.variant)
        if self.experiment_id == "Q2.6":
            locked = FrozenRecord.from_dict(dict(material["locked_objective"]))
            if locked.content_hash != workflow.session.objective.content_hash:
                raise ContractError("session objective differs from the caller-frozen goal lock")
        initial = workflow.invoke_model("assessment", model, instruction="Assess only the supplied public material.",
            evidence_only=True, module_context=FrozenRecord.from_dict({"panel_cell": opaque_panel_cell_binding(cell),
                "public_material": material["public_material"], **({"proposal": material["proposal"]} if self.experiment_id == "Q2.6" else {})}))
        state, outcome = _judgement(initial)
        checks = _checks(material["admission_checks"], workflow.session.task.identity)
        host = {"validator_verified": checks["validator_verified"], "execution_success": checks["execution_success"]}
        admission = None
        enabled = "M1" in workflow.enabled
        if enabled:
            disposition = EvidenceAdmission.decide(identity=workflow.session.task.identity, state=state, outcome=outcome,
                execution_success=checks["execution_success"], trusted_validator=checks["trusted_validator"],
                validator_verified=checks["validator_verified"], evidence_ids=checks["evidence_ids"],
                subject_bindings=checks["subject_bindings"], required_audit=checks["required_audit"],
                audit=[AuditItem(**row) for row in checks["audit"]])
            admission = {"admitted": disposition.admitted, "outcome": disposition.outcome}
        trace = workflow._trace("stage_1" if enabled else "operation_m1_control", "executed", host_checks=host,
            m1_enabled=enabled, admission=admission, material_digest=FrozenRecord.from_dict(dict(material)).content_hash)
        final = workflow.invoke_model("final", model, instruction="Return a bounded train-only unknown candidate.",
            module_context=FrozenRecord.from_dict({"panel_cell": opaque_panel_cell_binding(cell),
                "required_objective_digest": workflow.session.objective.content_hash,
                "public_material": material["public_material"], "processing": {"host_checks": host, "admission": admission}}))
        _candidate(final, workflow.session.objective)
        return trace, final, (initial, final)


@dataclass(frozen=True)
class Q25EvidencePolarityDriver(_Driver):
    experiment_id: str = "Q2.5"


@dataclass(frozen=True)
class Q26GoalLockDriver(_Driver):
    experiment_id: str = "Q2.6"


def install_drivers(target: MutableMapping[str, Any]):
    target.update({"Q2.5": Q25EvidencePolarityDriver(), "Q2.6": Q26GoalLockDriver()})
    return target
