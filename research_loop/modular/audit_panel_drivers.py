"""Train-only Q2.3/Q2.4 drivers for caller-supplied dual-audit material.

The caller owns both the audit receipt authority and the restricted shadow
execution port.  This module only binds their returned records through the real
``RunSession.admit``/``AuditVerifier`` path; it never manufactures an admission
or an independent authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, MutableMapping

from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask
from research_loop.modular.panel_receipts import PanelCell, opaque_panel_cell_binding
from research_loop.modular.runtime import RunSession
from research_loop.modular.workflow import ModularWorkflow
from research_loop.ontology import ContractError


AuditReceiptPort = Callable[[PublicTask, FrozenRecord, FrozenRecord, Any], tuple[FrozenRecord, FrozenRecord]]
ShadowExecutionPort = Callable[[RunSession, PublicTask, FrozenRecord], Any]

_Q23 = ("false", "string_false", "empty", "duplicate", "unknown", "missing", "parse_error")
_Q24 = ("one_fail", "both_fail", "disagree", "same_wrong")


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validate_selected(item: Any) -> None:
    if (not isinstance(item, Mapping) or set(item) != {"audit_material", "independent_check"}
            or not isinstance(item["audit_material"], Mapping) or not item["audit_material"]
            or not isinstance(item["independent_check"], Mapping) or not item["independent_check"]):
        raise ContractError("audit variant material is malformed")


def _validate_bundle(task: PublicTask, body: Mapping[str, Any]) -> None:
    if (set(body) != {"schema", "identity", "subject", "public_evidence", "shadow_execution", "q23", "q24"}
            or body["schema"] != "typed-audit-panel-bundle-v1" or body["identity"] != task.identity.data()
            or not isinstance(body["subject"], Mapping) or set(body["subject"]) != {"task", "subject"}
            or body["subject"].get("task") != task.identity.task_id or not _text(body["subject"].get("subject"))
            or not isinstance(body["public_evidence"], Mapping) or not body["public_evidence"]
            or not isinstance(body["shadow_execution"], Mapping) or not body["shadow_execution"]
            or not isinstance(body["q23"], Mapping) or set(body["q23"]) != set(_Q23)
            or not isinstance(body["q24"], Mapping) or set(body["q24"]) != set(_Q24)):
        raise ContractError("audit bundle identity or coverage mismatch")
    for item in tuple(body["q23"].values()) + tuple(body["q24"].values()):
        _validate_selected(item)


def freeze_audit_bundle(task: PublicTask, *, subject: Mapping[str, Any], public_evidence: Mapping[str, Any],
                        shadow_execution: Mapping[str, Any], q23: Mapping[str, Mapping[str, Any]],
                        q24: Mapping[str, Mapping[str, Any]]) -> FrozenRecord:
    if not isinstance(task, PublicTask):
        raise ContractError("audit bundle requires a prepared public task")
    body = {"schema": "typed-audit-panel-bundle-v1", "identity": task.identity.data(), "subject": dict(subject),
            "public_evidence": dict(public_evidence), "shadow_execution": dict(shadow_execution),
            "q23": {key: dict(value) for key, value in q23.items()},
            "q24": {key: dict(value) for key, value in q24.items()}}
    _validate_bundle(task, body)
    return FrozenRecord.from_dict(body)


def select_audit_material(bundle: FrozenRecord, task: PublicTask, experiment_id: str, variant: str) -> FrozenRecord:
    body = bundle.data()
    _validate_bundle(task, body)
    key = {"Q2.3": "q23", "Q2.4": "q24"}.get(experiment_id)
    if key is None or variant not in body[key]:
        raise ContractError("audit bundle lacks selected variant material")
    selected = body[key][variant]
    return FrozenRecord.from_dict({"schema": "typed-selected-audit-material-v1", "identity": body["identity"],
        "subject": body["subject"], "public_evidence": body["public_evidence"],
        "shadow_execution": body["shadow_execution"], "audit_material": selected["audit_material"],
        # This record remains in controller trace state.  It is deliberately not
        # included in a model request: agreement on signatures is not scientific truth.
        "controller_only_independent_check": selected["independent_check"]})


def audit_panel_injection(experiment_id: str, variant: str, *, task: FrozenRecord, evidence: FrozenRecord) -> Mapping[str, Any]:
    if evidence.data().get("schema") != "typed-audit-panel-bundle-v1":
        from research_loop.modular.scenarios_audit import audit_injection
        return audit_injection(experiment_id, variant)
    body = task.data()
    public = PublicTask(DataIdentity.parse(body["identity"]), FrozenRecord.from_dict(body["payload"]))
    select_audit_material(evidence, public, experiment_id, variant)
    return {"schema": "audit-panel-controller-v1", "material_bundle": evidence.data()}


def _resolve(task: PublicTask, scenario: FrozenRecord, experiment_id: str, variant: str) -> FrozenRecord:
    controller = scenario.data().get("controller_input")
    if (not isinstance(controller, Mapping) or controller.get("schema") != "audit-panel-controller-v1"
            or not isinstance(controller.get("material_bundle"), Mapping)):
        raise ContractError("audit driver requires compiler-bound caller material")
    bundle = FrozenRecord.from_dict(controller["material_bundle"])
    if bundle.content_hash != scenario.data().get("base", {}).get("evidence"):
        raise ContractError("audit bundle does not match frozen scenario evidence")
    return select_audit_material(bundle, task, experiment_id, variant)


def _candidate(record: FrozenRecord, objective: FrozenRecord) -> None:
    body = record.data()
    if (set(body) != {"objective_digest", "outcome", "evidence_ids", "conclusion", "programme_complete"}
            or body.get("objective_digest") != objective.content_hash or body.get("outcome") != "unknown"
            or body.get("evidence_ids") != [] or not _text(body.get("conclusion"))
            or body.get("programme_complete") is not False):
        raise ContractError("audit driver final must be a bounded unknown candidate")


@dataclass(frozen=True)
class _AuditDriver:
    experiment_id: str
    slots: tuple[str, ...] = ("audit_initial", "final")
    execution_limit: int = 1
    docker_execution: str = "offline_restricted_shadow_required"
    receipt_port: AuditReceiptPort | None = None
    shadow_execution_port: ShadowExecutionPort | None = None

    def slots_for(self, cell: PanelCell) -> tuple[str, ...]:
        return self.slots

    def run(self, workflow: ModularWorkflow, *, cell: PanelCell, scenario: FrozenRecord, model, package):
        material = _resolve(workflow.session.task, scenario, self.experiment_id, cell.variant)
        body = material.data()
        initial = workflow.invoke_model("audit_initial", model,
            instruction="Assess only the supplied public evidence. Audit processing has not yet been reported.",
            evidence_only=True, module_context=FrozenRecord.from_dict({"panel_cell": opaque_panel_cell_binding(cell),
                "subject": body["subject"], "public_evidence": body["public_evidence"]}))
        if self.shadow_execution_port is None:
            raise ContractError("audit driver requires a restricted caller shadow execution port")
        execution = self.shadow_execution_port(workflow.session, workflow.session.task, material)
        if getattr(execution, "content_hash", None) not in workflow.session.executions:
            raise ContractError("audit shadow port did not execute through this RunSession")
        if self.receipt_port is None:
            raise ContractError("audit driver requires a caller-owned dual audit receipt port")
        receipts = self.receipt_port(workflow.session.task, material, workflow.session.objective, execution)
        if not isinstance(receipts, tuple) or len(receipts) != 2 or any(not isinstance(item, FrozenRecord) for item in receipts):
            raise ContractError("audit receipt port requires exactly two frozen receipt records")
        admission, rejection = None, None
        try:
            admission = workflow.session.admit(execution.content_hash, list(receipts))
        except ContractError as exc:
            rejection = str(exc)
        processing = {"schema": "audit-processing-result-v1", "execution_status": execution.status,
            "admission": admission.data() if admission else {"status": "rejected", "reason": rejection},
            "independent_check": {"retained_by_controller": True, "scientific_authority": "not_established"}}
        stage = workflow._trace("stage_1" if "M1" in workflow.enabled else "operation_m1_shadow_control", "executed",
            host_audit_verifier="always_on", audit_receipt_digests=[item.content_hash for item in receipts],
            controller_only_independent_check=body["controller_only_independent_check"], processing=processing)
        final = workflow.invoke_model("final", model,
            instruction="Return a bounded train-only unknown candidate. The audit processing state is an engineering result, not scientific authority.",
            module_context=FrozenRecord.from_dict({"panel_cell": opaque_panel_cell_binding(cell),
                "candidate_package": package.record.data(), "required_objective_digest": workflow.session.objective.content_hash,
                "audit_processing": processing}))
        _candidate(final, workflow.session.objective)
        return stage, final, (initial, final)


@dataclass(frozen=True)
class Q23AuditFaultDriver(_AuditDriver):
    experiment_id: str = "Q2.3"


@dataclass(frozen=True)
class Q24AuditPairDriver(_AuditDriver):
    experiment_id: str = "Q2.4"


def install_drivers(target: MutableMapping[str, Any], *, receipt_port: AuditReceiptPort | None = None,
                    shadow_execution_port: ShadowExecutionPort | None = None):
    target.update({"Q2.3": Q23AuditFaultDriver(receipt_port=receipt_port, shadow_execution_port=shadow_execution_port),
                   "Q2.4": Q24AuditPairDriver(receipt_port=receipt_port, shadow_execution_port=shadow_execution_port)})
    return target
