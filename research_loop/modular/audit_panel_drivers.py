"""Train-only Q2.3/Q2.4 drivers for caller-supplied dual-audit material.

The caller owns both the audit receipt authority and the restricted shadow
execution port.  This module only binds their returned records through the real
``RunSession.admit``/``AuditVerifier`` path; it never manufactures an admission
or an independent authority.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any, Callable, Mapping, MutableMapping

from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask
from research_loop.modular.panel_receipts import PanelCell, opaque_panel_cell_binding
from research_loop.modular.runtime import RunSession
from research_loop.modular.workflow import ModularWorkflow
from research_loop.ontology import ContractError


AuditReceiptPort = Callable[[PublicTask, FrozenRecord, FrozenRecord, Any], FrozenRecord]
ShadowExecutionPort = Callable[[RunSession, PublicTask, FrozenRecord], Any]

_Q23 = ("false", "string_false", "empty", "duplicate", "unknown", "missing", "parse_error")
_Q24 = ("one_fail", "both_fail", "disagree", "same_wrong")


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _validate_shadow_execution(value: Any) -> None:
    """Accept only a caller-frozen program and public-input hash contract."""
    if (not isinstance(value, Mapping) or set(value) != {"schema", "program_sha256", "input_sha256"}
            or value.get("schema") != "frozen-shadow-execution-contract-v1"
            or not _sha256(value.get("program_sha256"))
            or not isinstance(value.get("input_sha256"), Mapping) or not value["input_sha256"]
            or any(not _text(name) or not _sha256(digest) for name, digest in value["input_sha256"].items())):
        raise ContractError("shadow execution contract is malformed")


def _validate_selected(item: Any) -> None:
    if (not isinstance(item, Mapping) or set(item) != {"audit_template", "independent_check"}
            or not isinstance(item["audit_template"], Mapping) or not item["audit_template"]
            or not isinstance(item["independent_check"], Mapping) or not item["independent_check"]):
        raise ContractError("audit variant material is malformed")
    template = item["audit_template"]
    if template.get("kind") == "raw_parse_error":
        if set(template) != {"kind", "raw_text"} or not _text(template["raw_text"]):
            raise ContractError("raw audit parse template is malformed")
    elif template.get("kind") == "signed_audit_pair":
        if set(template) != {"kind", "receipts"} or not isinstance(template["receipts"], list) or len(template["receipts"]) != 2:
            raise ContractError("signed audit template requires two receipt bodies")
        for receipt in template["receipts"]:
            if not isinstance(receipt, Mapping) or set(receipt) != {"state", "outcome", "audit"}:
                raise ContractError("signed audit template is malformed")
    else:
        raise ContractError("audit template kind is unknown")


def _validate_bundle(task: PublicTask, body: Mapping[str, Any]) -> None:
    if (set(body) != {"schema", "identity", "subject", "public_evidence", "shadow_execution", "q23", "q24"}
            or body["schema"] != "typed-audit-panel-bundle-v1" or body["identity"] != task.identity.data()
            or not isinstance(body["subject"], Mapping) or set(body["subject"]) != {"task", "subject"}
            or body["subject"].get("task") != task.identity.task_id or not _text(body["subject"].get("subject"))
            or not isinstance(body["public_evidence"], Mapping) or not body["public_evidence"]
            or not isinstance(body["q23"], Mapping) or set(body["q23"]) != set(_Q23)
            or not isinstance(body["q24"], Mapping) or set(body["q24"]) != set(_Q24)):
        raise ContractError("audit bundle identity or coverage mismatch")
    _validate_shadow_execution(body["shadow_execution"])
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
        "shadow_execution": body["shadow_execution"], "audit_template": selected["audit_template"],
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


def _payload_digest(value: str) -> str:
    if not isinstance(value, str):
        raise ContractError("audit payload must be serialized text")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _receipt_binding(port_record: FrozenRecord, *, task: PublicTask, material: FrozenRecord,
                     objective: FrozenRecord, execution: Any) -> tuple[tuple[FrozenRecord, ...], str | None]:
    body = port_record.data()
    if (set(body) != {"schema", "material_digest", "identity", "objective_digest", "execution_digest",
                     "shadow_receipt_digest", "audit_payloads", "audit_payload_digests"}
            or body["schema"] != "caller-dual-audit-binding-v1" or body["material_digest"] != material.content_hash
            or body["identity"] != task.identity.data() or body["objective_digest"] != objective.content_hash
            or body["execution_digest"] != execution.content_hash or body["shadow_receipt_digest"] != execution.content_hash
            or not isinstance(body["audit_payloads"], list) or len(body["audit_payloads"]) != 2
            or not isinstance(body["audit_payload_digests"], list) or len(body["audit_payload_digests"]) != 2
            or body["audit_payload_digests"] != [_payload_digest(value) for value in body["audit_payloads"]]):
        raise ContractError("caller dual-audit binding does not match frozen execution material")
    template = material.data()["audit_template"]
    try:
        receipts = tuple(FrozenRecord(value) for value in body["audit_payloads"])
    except ContractError:
        if template.get("kind") == "raw_parse_error" and body["audit_payloads"] == [template["raw_text"]] * 2:
            return (), "audit payload parse failed"
        raise ContractError("audit payload parse failed")
    if template.get("kind") != "signed_audit_pair" or set(template) != {"kind", "receipts"}:
        raise ContractError("audit template is not a signed audit projection")
    for receipt, expected in zip(receipts, template["receipts"]):
        audit = receipt.data().get("body")
        if not isinstance(audit, Mapping) or any(audit.get(field) != expected[field] for field in ("state", "outcome", "audit")):
            raise ContractError("authenticated audit does not match frozen caller template")
    return receipts, None


def _shadow_execution_binding(execution: Any, material: FrozenRecord) -> None:
    """Bind the caller port's actual receipt to its frozen executable contract."""
    plan = material.data()["shadow_execution"]
    artifact = getattr(execution, "artifact", None)
    if artifact is None or artifact.sha256 != plan["program_sha256"]:
        raise ContractError("shadow execution program does not match the frozen contract")
    record = getattr(execution, "record", None)
    if not isinstance(record, FrozenRecord):
        raise ContractError("shadow execution lacks a typed receipt")
    actual = record.data().get("input_artifacts")
    expected = plan["input_sha256"]
    if (not isinstance(actual, Mapping) or set(actual) != set(expected)
            or any(not isinstance(actual[name], Mapping) or actual[name].get("sha256") != digest
                   for name, digest in expected.items())):
        raise ContractError("shadow execution inputs do not match the frozen contract")


def _model_processing(*, execution: Any, verified: FrozenRecord | None,
                      admission: FrozenRecord | None) -> Mapping[str, Any]:
    """Expose a fixed-shape engineering projection without revealing the arm."""
    if admission is None:
        admission_state = "not_promoted"
    else:
        admission_state = "admitted" if admission.data().get("admitted") is True else "not_admitted"
    return {"schema": "audit-model-processing-projection-v1", "execution_status": execution.status,
            "host_verification": {"status": "verified" if verified else "rejected"},
            "admission": {"status": admission_state}}


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
        _shadow_execution_binding(execution, material)
        if self.receipt_port is None:
            raise ContractError("audit driver requires a caller-owned dual audit receipt port")
        port_record = self.receipt_port(workflow.session.task, material, workflow.session.objective, execution)
        if not isinstance(port_record, FrozenRecord):
            raise ContractError("audit receipt port requires one frozen caller binding")
        receipts, host_error = _receipt_binding(port_record, task=workflow.session.task, material=material,
                                                objective=workflow.session.objective, execution=execution)
        verified, admission, rejection = None, None, None
        if host_error is None:
            try:
                verified = workflow.session.verifier.verify_evidence(list(receipts), identity=workflow.session.task.identity,
                    objective_digest=workflow.session.objective.content_hash, execution=execution,
                    required_audit=workflow.session.required_audit)
            except ContractError as exc:
                host_error = str(exc)
        workflow.session._record("host_audit_verified" if verified else "host_audit_rejected", {
            "execution_digest": execution.content_hash, "receipt_binding_digest": port_record.content_hash,
            **({"verified": verified.data()} if verified else {"reason": host_error})})
        m1_enabled = "M1" in workflow.enabled
        if m1_enabled and verified is not None:
            # M1 alone applies EvidenceAdmission and may promote the verified
            # record into the session ledger. The host checks above are fixed P0.
            try:
                admission = workflow.session.admit(execution.content_hash, list(receipts))
            except ContractError as exc:
                rejection = str(exc)
        elif host_error is not None:
            rejection = host_error
        processing = {"schema": "audit-processing-result-v1", "execution_status": execution.status,
            "host_verification": verified.data() if verified else {"status": "rejected", "reason": host_error},
            "m1_policy": "applied" if admission else "not_applied_common_p0_rejection" if host_error else "frozen_shadow_control",
            "admission": admission.data() if admission else {"status": "not_promoted", "reason": rejection},
            "independent_check": {"retained_by_controller": True, "scientific_authority": "not_established"}}
        model_processing = _model_processing(execution=execution, verified=verified, admission=admission)
        stage = workflow._trace("stage_1" if m1_enabled else "operation_m1_shadow_control", "executed",
            host_audit_verifier="always_on", receipt_binding_digest=port_record.content_hash,
            host_verification="verified" if verified else "rejected",
            controller_only_independent_check=body["controller_only_independent_check"], processing=processing)
        final = workflow.invoke_model("final", model,
            instruction="Return a bounded train-only unknown candidate. The audit processing state is an engineering result, not scientific authority.",
            module_context=FrozenRecord.from_dict({"panel_cell": opaque_panel_cell_binding(cell),
                "required_objective_digest": workflow.session.objective.content_hash,
                "audit_processing": model_processing}))
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
