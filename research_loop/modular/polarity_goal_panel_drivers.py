"""Caller-bound, train-only Q2.5 polarity and Q2.6 objective-lock drivers.

The model sees only source-bound public material and its own prior response.
Caller authority receipts are verified before either request, retained in the
journal, and are never exposed as controller flags or model instructions.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, MutableMapping

from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask, required_text
from research_loop.modular.modules.admission import AuditItem, EvidenceAdmission, ScientificState
from research_loop.modular.panel_receipts import opaque_panel_cell_binding
from research_loop.ontology import ContractError

_Q25 = ("invalid_positive", "invalid_negative", "valid_negative")
_Q26 = ("secondary_win", "maintenance", "late_pivot")


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError(f"{name} must be a mapping")
    return value


def _public_material(value: Any, identity: DataIdentity) -> dict[str, str]:
    body = dict(_mapping(value, "public material"))
    if set(body) != {"source_id", "observation"} or body.get("source_id") != identity.group_id:
        raise ContractError("public material must bind the caller source")
    return {"source_id": required_text(body["source_id"], "public source id"),
            "observation": required_text(body["observation"], "public observation")}


def _proposal(value: Any, identity: DataIdentity) -> dict[str, str]:
    body = dict(_mapping(value, "public proposal"))
    if set(body) != {"source_id", "statement"} or body.get("source_id") != identity.group_id:
        raise ContractError("public proposal must bind the caller source")
    return {"source_id": required_text(body["source_id"], "proposal source id"),
            "statement": required_text(body["statement"], "proposal statement")}


def _locked(value: Any) -> FrozenRecord:
    record = FrozenRecord.from_dict(dict(_mapping(value, "locked objective")))
    if not record.data():
        raise ContractError("locked objective is empty")
    return record


def admission_subject(task: PublicTask, *, experiment_id: str, public_material: Mapping[str, Any],
                      locked_objective: Mapping[str, Any] | None = None,
                      proposal: Mapping[str, Any] | None = None) -> FrozenRecord:
    """Build the exact public subject that caller audit receipts must sign."""
    if not isinstance(task, PublicTask) or experiment_id not in {"Q2.5", "Q2.6"}:
        raise ContractError("admission subject requires a registered public task")
    body: dict[str, Any] = {"schema": "polarity-goal-public-subject-v1", "experiment_id": experiment_id,
                            "identity": task.identity.data(), "public_material": _public_material(public_material, task.identity)}
    if experiment_id == "Q2.6":
        if locked_objective is None or proposal is None:
            raise ContractError("goal-lock receipt subject is incomplete")
        body["locked_objective"] = _locked(locked_objective).data()
        body["proposal"] = _proposal(proposal, task.identity)
    elif locked_objective is not None or proposal is not None:
        raise ContractError("polarity receipt subject has goal-only fields")
    return FrozenRecord.from_dict(body)


def _receipts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) != 2 or any(not isinstance(row, Mapping) for row in value):
        raise ContractError("two caller authority receipts are required")
    # Preserve the opaque signed envelope exactly; signature verification happens
    # before a model request through the trusted session verifier.
    return [dict(row) for row in value]


def _item(task: PublicTask, experiment_id: str, value: Any) -> dict[str, Any]:
    body = dict(_mapping(value, "caller material item"))
    required = {"public_material", "admission_receipts"}
    if experiment_id == "Q2.6":
        required |= {"locked_objective", "proposal"}
    if set(body) != required:
        raise ContractError("caller material fields are incomplete")
    public = _public_material(body["public_material"], task.identity)
    result: dict[str, Any] = {"public_material": public, "admission_receipts": _receipts(body["admission_receipts"])}
    if experiment_id == "Q2.6":
        result["locked_objective"] = _locked(body["locked_objective"]).data()
        result["proposal"] = _proposal(body["proposal"], task.identity)
    # Validate all immutable nested records now, so malformed materials cannot
    # spend a model call before the real verifier checks their signatures.
    admission_subject(task, experiment_id=experiment_id, public_material=public,
                      locked_objective=result.get("locked_objective"), proposal=result.get("proposal"))
    return result


def freeze_polarity_goal_bundle(task: PublicTask, *, q25: Mapping[str, Mapping[str, Any]],
                                q26: Mapping[str, Mapping[str, Any]]) -> FrozenRecord:
    if not isinstance(task, PublicTask):
        raise ContractError("bundle requires a public task")
    if not isinstance(q25, Mapping) or not isinstance(q26, Mapping) or set(q25) != set(_Q25) or set(q26) != set(_Q26):
        raise ContractError("bundle variant coverage mismatch")
    body = {"schema": "typed-polarity-goal-panel-bundle-v2", "identity": task.identity.data(),
            "payload_digest": task.payload.content_hash,
            "q25": {name: _item(task, "Q2.5", row) for name, row in q25.items()},
            "q26": {name: _item(task, "Q2.6", row) for name, row in q26.items()}}
    return FrozenRecord.from_dict(body)


def polarity_goal_injection(experiment_id: str, variant: str, *, task: FrozenRecord, evidence: FrozenRecord) -> Mapping[str, Any]:
    body = evidence.data()
    if body.get("schema") != "typed-polarity-goal-panel-bundle-v2":
        raise ContractError("typed polarity/goal caller material is required")
    public = PublicTask(DataIdentity.parse(task.data()["identity"]), FrozenRecord.from_dict(task.data()["payload"]))
    bundle = freeze_polarity_goal_bundle(public, q25=body.get("q25", {}), q26=body.get("q26", {}))
    key = "q25" if experiment_id == "Q2.5" else "q26" if experiment_id == "Q2.6" else None
    if key is None or variant not in body[key]:
        raise ContractError("unregistered polarity/goal variant")
    return {"schema": "polarity-goal-controller-v2", "bundle": bundle.data()}


def _material(task: PublicTask, scenario: FrozenRecord, experiment: str, variant: str) -> tuple[dict[str, Any], FrozenRecord]:
    controller = _mapping(scenario.data().get("controller_input"), "controller input")
    if controller.get("schema") != "polarity-goal-controller-v2":
        raise ContractError("typed polarity/goal material is required")
    bundle = FrozenRecord.from_dict(dict(_mapping(controller.get("bundle"), "bundle")))
    body = bundle.data()
    remade = freeze_polarity_goal_bundle(task, q25=body.get("q25", {}), q26=body.get("q26", {}))
    if remade.content_hash != bundle.content_hash or scenario.data().get("base", {}).get("evidence") != bundle.content_hash:
        raise ContractError("scenario does not bind its caller material")
    key = "q25" if experiment == "Q2.5" else "q26"
    if variant not in body[key]:
        raise ContractError("material variant is unregistered")
    item = _item(task, experiment, body[key][variant])
    subject = admission_subject(task, experiment_id=experiment, public_material=item["public_material"],
                                locked_objective=item.get("locked_objective"), proposal=item.get("proposal"))
    return item, subject


def _judgement(response: FrozenRecord) -> tuple[ScientificState, str]:
    body = response.data()
    if set(body) != {"validity", "support", "novelty", "investment", "outcome"} or body.get("outcome") not in {"positive", "negative"}:
        raise ContractError("driver judgement has invalid schema")
    return ScientificState(body["validity"], body["support"], body["novelty"], body["investment"]), body["outcome"]


def _goal_intent(response: FrozenRecord) -> str:
    body = response.data()
    if set(body) != {"validity", "support", "novelty", "investment", "outcome", "selected_objective_digest"}:
        raise ContractError("goal-lock assessment has invalid schema")
    _judgement(FrozenRecord.from_dict({name: body[name] for name in ("validity", "support", "novelty", "investment", "outcome")}))
    return required_text(body["selected_objective_digest"], "selected objective digest")


def _candidate(response: FrozenRecord) -> dict[str, Any]:
    body = response.data()
    if (set(body) != {"objective_digest", "outcome", "evidence_ids", "conclusion", "programme_complete"}
            or not isinstance(body["objective_digest"], str) or not body["objective_digest"]
            or body["outcome"] not in {"positive", "negative", "unknown", "invalid", "withdrawn"}
            or not isinstance(body["evidence_ids"], list) or any(not isinstance(x, str) or not x for x in body["evidence_ids"])
            or len(set(body["evidence_ids"])) != len(body["evidence_ids"])
            or not isinstance(body["conclusion"], str) or not body["conclusion"].strip()
            or body["programme_complete"] is not False):
        raise ContractError("final candidate has invalid bounded schema")
    return body


@dataclass(frozen=True)
class _Driver:
    experiment_id: str
    slots: tuple[str, ...] = ("assessment", "final")
    execution_limit: int = 0
    docker_execution: str = "not_requested_by_driver"

    def slots_for(self, cell) -> tuple[str, ...]:
        return self.slots

    def run(self, workflow, *, cell, scenario: FrozenRecord, model, package):
        material, subject = _material(workflow.session.task, scenario, self.experiment_id, cell.variant)
        if self.experiment_id == "Q2.6" and _locked(material["locked_objective"]).content_hash != workflow.session.objective.content_hash:
            raise ContractError("session objective differs from the caller-frozen goal lock")
        verified = workflow.session.verifier.verify_material(
            [FrozenRecord.from_dict(row) for row in material["admission_receipts"]], identity=workflow.session.task.identity,
            subject_digest=subject.content_hash, required_audit=("measurement",))
        verified_body = verified.data()
        public_context: dict[str, Any] = {"panel_cell": opaque_panel_cell_binding(cell),
                                          "public_material": material["public_material"]}
        if self.experiment_id == "Q2.6":
            public_context.update({"locked_objective": material["locked_objective"], "proposal": material["proposal"],
                                   "required_objective_digest": workflow.session.objective.content_hash})
        initial = workflow.invoke_model("assessment", model,
            instruction=("Assess only the supplied source-bound public material. "
                         "For a goal lock, report the objective digest you would retain; do not alter the lock."),
            evidence_only=True, module_context=FrozenRecord.from_dict(public_context))
        if self.experiment_id == "Q2.6":
            selected_goal = _goal_intent(initial)
            state, outcome = _judgement(FrozenRecord.from_dict({name: initial.data()[name] for name in
                ("validity", "support", "novelty", "investment", "outcome")}))
        else:
            state, outcome = _judgement(initial)
            selected_goal = workflow.session.objective.content_hash
        receipt_match = verified_body["state"] == state.__dict__ and verified_body["outcome"] == outcome
        goal_match = selected_goal == workflow.session.objective.content_hash
        enabled = "M1" in workflow.enabled
        admission = None
        if enabled:
            disposition = EvidenceAdmission.decide(identity=workflow.session.task.identity, state=state, outcome=outcome,
                execution_success=bool(verified_body["execution_success"]) and receipt_match,
                trusted_validator="+".join(verified_body["authorities"]), validator_verified=True,
                evidence_ids=[subject.content_hash], subject_bindings={"task": workflow.session.task.identity.task_id,
                                                                        "source": material["public_material"]["source_id"]},
                required_audit=("measurement",), audit=[AuditItem(**row) for row in verified_body["audit"]])
            admission = {"receipt_digest": verified.content_hash, "receipt_match": receipt_match,
                         "selected_goal_digest": selected_goal if self.experiment_id == "Q2.6" else None,
                         "goal_match": goal_match if self.experiment_id == "Q2.6" else None,
                         "disposition": {"admitted": disposition.admitted, "reason": disposition.reason,
                                         "outcome": disposition.outcome, "evidence_ids": list(disposition.evidence_ids)}}
            permitted = ["positive", "negative", "unknown", "invalid", "withdrawn"] if disposition.admitted and goal_match else ["unknown"]
        else:
            permitted = ["positive", "negative", "unknown", "invalid", "withdrawn"]
        trace = workflow._trace("stage_1" if enabled else "operation_m1_control", "executed",
            receipt_digest=verified.content_hash, judgement_digest=initial.content_hash, m1_enabled=enabled,
            admission=admission, selected_goal_digest=selected_goal if self.experiment_id == "Q2.6" else None,
            goal_match=goal_match if self.experiment_id == "Q2.6" else None,
            material_digest=subject.content_hash)
        final_context = {"panel_cell": opaque_panel_cell_binding(cell), "required_objective_digest": workflow.session.objective.content_hash,
                         "public_material": material["public_material"], "assessment": initial.data(),
                         "permitted_outcomes": permitted}
        if self.experiment_id == "Q2.6":
            final_context.update({"locked_objective": material["locked_objective"], "proposal": material["proposal"]})
        final = workflow.invoke_model("final", model,
            instruction=("Return the bounded train-only candidate record. Copy or choose the required objective digest only from "
                         "the public context; evidence promotion remains controller-gated."),
            module_context=FrozenRecord.from_dict(final_context))
        candidate = _candidate(final)
        if enabled and (candidate["outcome"] not in permitted or (self.experiment_id == "Q2.6" and not goal_match)):
            raise ContractError("M1 admission or objective-lock gate rejected the model candidate")
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
