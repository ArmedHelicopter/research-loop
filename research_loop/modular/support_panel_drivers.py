"""Train-only Q1.3/Q1.4 support-state drivers with caller-supplied records."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, MutableMapping

from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask
from research_loop.modular.modules.context import ContextBuilder
from research_loop.modular.panel_receipts import PanelCell, opaque_panel_cell_binding
from research_loop.modular.workflow import ModularWorkflow
from research_loop.ontology import ContractError, canonical

AdmissionPort = Callable[[PublicTask, FrozenRecord], Mapping[str, Any]]


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _context(workflow: ModularWorkflow, *, enabled: bool, summary: str):
    return workflow.session.cache.get_or_build(
        ContextBuilder(workflow.session.task.identity, budget_bytes=workflow.session.context_budget),
        canonical(workflow.session.task.payload.data()), workflow.session.evidence, workflow.session.claims,
        mode="candidate" if enabled else "baseline", baseline_summary=summary)


def _record(identity: Mapping[str, Any], source: Mapping[str, Any], *, source_key: str, representation: str) -> FrozenRecord:
    return FrozenRecord.from_dict({"schema": "typed-public-support-record-v1", "identity": dict(identity),
        "source_key": source_key, "representation": representation, "root_material": source["root_material"],
        "public_evidence": source["public_evidence"]})


def _admit(port: AdmissionPort | None, task: PublicTask, record: FrozenRecord) -> Mapping[str, Any]:
    if port is None:
        raise ContractError("support ledger admission requires a caller-owned receipt port")
    receipt = port(task, record)
    if (not isinstance(receipt, Mapping) or set(receipt) != {"record_digest", "trusted_validator", "validator_verified", "admitted"}
            or receipt.get("record_digest") != record.content_hash or not _text(receipt.get("trusted_validator"))
            or receipt.get("validator_verified") is not True or receipt.get("admitted") is not True):
        raise ContractError("support admission receipt does not bind its public record")
    return dict(receipt)


def _append(session, record: FrozenRecord, receipt: Mapping[str, Any]):
    body = record.data()
    observation = {"kind": "measurement", "root_material": dict(body["root_material"]),
        "representation": body["representation"], "content": body["public_evidence"],
        "subject_bindings": {"task": session.task.identity.task_id}, "independent_group": session.task.identity.group_id}
    return session.evidence.append(observation, {key: receipt[key] for key in ("trusted_validator", "validator_verified", "admitted")})


def _validate_source(source: Any) -> None:
    if (not isinstance(source, Mapping) or set(source) != {"root_material", "public_evidence"}
            or not isinstance(source["root_material"], Mapping) or not source["root_material"]
            or not isinstance(source["public_evidence"], Mapping)):
        raise ContractError("support bundle source is malformed")


def _validate(task: PublicTask, body: Mapping[str, Any]) -> None:
    if (set(body) != {"schema", "identity", "q13", "q14"} or body["schema"] != "typed-support-panel-bundle-v1"
            or body["identity"] != task.identity.data() or not isinstance(body["q13"], Mapping) or not isinstance(body["q14"], Mapping)
            or set(body["q13"]) != {"log", "report", "summary", "memory"}
            or set(body["q14"]) != {"one_withdrawn", "all_withdrawn", "copies"}):
        raise ContractError("support bundle identity or coverage mismatch")
    for row in body["q13"].values():
        if not isinstance(row, Mapping) or set(row) != {"source", "representation", "claim_statement"} or row["representation"] not in {"raw", "report", "summary"} or not _text(row["claim_statement"]):
            raise ContractError("Q1.3 material is malformed")
        _validate_source(row["source"])
    q13_sources = [row["source"] for row in body["q13"].values()]
    if any(source != q13_sources[0] for source in q13_sources[1:]):
        raise ContractError("Q1.3 representations must share one caller source")
    for variant, row in body["q14"].items():
        if not isinstance(row, Mapping) or set(row) != {"sources", "withdraw_actions", "claim_statement"} or not isinstance(row["sources"], Mapping) or not _text(row["claim_statement"]) or not isinstance(row["withdraw_actions"], list):
            raise ContractError("Q1.4 material is malformed")
        if not row["sources"]:
            raise ContractError("Q1.4 needs caller supplied sources")
        for key, source in row["sources"].items():
            if not _text(key): raise ContractError("Q1.4 source key is malformed")
            _validate_source(source)
        seen = set()
        for action in row["withdraw_actions"]:
            if not isinstance(action, Mapping) or set(action) != {"source_key", "reason"} or not _text(action["source_key"]) or not _text(action["reason"]) or action["source_key"] not in row["sources"] or action["source_key"] in seen:
                raise ContractError("Q1.4 withdrawal action is malformed")
            seen.add(action["source_key"])
        source_roots = {canonical(source["root_material"]) for source in row["sources"].values()}
        withdrawn_roots = {canonical(row["sources"][action["source_key"]]["root_material"]) for action in row["withdraw_actions"]}
        if len(withdrawn_roots) != len(row["withdraw_actions"]):
            raise ContractError("Q1.4 withdrawal actions must target distinct source roots")
        if variant == "one_withdrawn" and (len(source_roots) < 2 or not withdrawn_roots or withdrawn_roots == source_roots):
            raise ContractError("Q1.4 one_withdrawn must leave a caller root")
        if variant == "all_withdrawn" and (not source_roots or withdrawn_roots != source_roots):
            raise ContractError("Q1.4 all_withdrawn must withdraw every caller root")
        if variant == "copies" and (len(source_roots) != 1 or len(row["sources"]) < 2 or row["withdraw_actions"]):
            raise ContractError("Q1.4 copies must be multiple records of one caller root")


def freeze_support_bundle(task: PublicTask, *, q13: Mapping[str, Mapping[str, Any]], q14: Mapping[str, Mapping[str, Any]]) -> FrozenRecord:
    if not isinstance(task, PublicTask) or not isinstance(q13, Mapping) or not isinstance(q14, Mapping):
        raise ContractError("support bundle needs typed caller material")
    body = {"schema": "typed-support-panel-bundle-v1", "identity": task.identity.data(),
            "q13": {key: dict(value) for key, value in q13.items()}, "q14": {key: dict(value) for key, value in q14.items()}}
    _validate(task, body)
    return FrozenRecord.from_dict(body)


def select_support_material(bundle: FrozenRecord, task: PublicTask, experiment_id: str, variant: str) -> FrozenRecord:
    body = bundle.data(); _validate(task, body)
    if experiment_id not in {"Q1.3", "Q1.4"} or variant not in body["q13" if experiment_id == "Q1.3" else "q14"]:
        raise ContractError("support bundle lacks the selected material")
    selected = body["q13" if experiment_id == "Q1.3" else "q14"][variant]
    return FrozenRecord.from_dict({"schema": "typed-selected-support-material-v1", "experiment_id": experiment_id,
        "identity": body["identity"], **selected})


def support_panel_injection(experiment_id: str, variant: str, *, task: FrozenRecord, evidence: FrozenRecord) -> Mapping[str, Any]:
    if evidence.data().get("schema") != "typed-support-panel-bundle-v1":
        from research_loop.modular.scenarios_history import history_injection
        return history_injection(experiment_id, variant)
    body = task.data(); public = PublicTask(DataIdentity.parse(body["identity"]), FrozenRecord.from_dict(body["payload"]))
    select_support_material(evidence, public, experiment_id, variant)
    return {"schema": "support-panel-controller-v1", "material_bundle": evidence.data()}


def _resolve(resolver, task: PublicTask, scenario: FrozenRecord, experiment_id: str, variant: str) -> FrozenRecord:
    controller = scenario.data().get("controller_input")
    if isinstance(controller, Mapping) and controller.get("schema") == "support-panel-controller-v1":
        bundle = FrozenRecord.from_dict(controller["material_bundle"])
    elif resolver is not None:
        bundle = resolver(task, scenario)
    else:
        raise ContractError("support driver requires a caller bundle resolver")
    if not isinstance(bundle, FrozenRecord) or bundle.content_hash != scenario.data().get("base", {}).get("evidence"):
        raise ContractError("support bundle does not match frozen scenario evidence")
    return select_support_material(bundle, task, experiment_id, variant)


def _final(workflow, cell, scenario, model, package, material: Mapping[str, Any], context, receipt_context: Mapping[str, Any]):
    result = workflow.invoke_model("final", model, instruction="Return a bounded train-only candidate: unknown, no evidence_ids, and programme_complete false.",
        baseline_summary=canonical(material), module_context=FrozenRecord.from_dict({"panel_cell": opaque_panel_cell_binding(cell),
            "candidate_package": package.record.data(), "required_objective_digest": workflow.session.objective.content_hash,
            "public_support_state": dict(material), "reconstructed_context": context.data(), **dict(receipt_context)}))
    body = result.data()
    if body.get("objective_digest") != workflow.session.objective.content_hash or body.get("outcome") != "unknown" or body.get("evidence_ids") != [] or body.get("programme_complete") is not False:
        raise ContractError("support driver final candidate is invalid")
    return result


@dataclass(frozen=True)
class Q13RepresentationDriver:
    experiment_id: str = "Q1.3"; slots: tuple[str, ...] = ("representation_initial", "representation_next", "final"); execution_limit: int = 0; docker_execution: str = "not_requested_by_driver"
    material_resolver: Callable[[PublicTask, FrozenRecord], FrozenRecord] | None = None; admission_port: AdmissionPort | None = None
    def run(self, workflow: ModularWorkflow, *, cell: PanelCell, scenario: FrozenRecord, model, package):
        material = _resolve(self.material_resolver, workflow.session.task, scenario, "Q1.3", cell.variant).data(); enabled = "M2" in workflow.enabled
        raw = _record(material["identity"], material["source"], source_key="same_source", representation="raw")
        record = _record(material["identity"], material["source"], source_key="same_source", representation=material["representation"])
        raw_receipt = _admit(self.admission_port, workflow.session.task, raw) if enabled else None
        receipt = None; roots = []
        if enabled:
            roots = [_append(workflow.session, raw, raw_receipt)]
            claim = workflow.session.claims.create(material["claim_statement"], subject_bindings={"task": workflow.session.task.identity.task_id})
            workflow.session.claims.apply(claim.claim_id, {"supports": [roots[0].root_id], "refutes": [], "subject_bindings": {"task": workflow.session.task.identity.task_id}}, expected_revision=0)
        before = _context(workflow, enabled=enabled, summary=canonical(material["source"]))
        initial = {"schema": "q13-public-projection-v2", "phase": "before", "records": [raw.data()], "claim_statement": material["claim_statement"]}
        first = workflow.invoke_model("representation_initial", model, instruction="Assess the supplied public support material.", baseline_summary=canonical(material["source"]), module_context=FrozenRecord.from_dict({"panel_cell": opaque_panel_cell_binding(cell), "public_support_state": initial, "ledger_mode": "deduplicated" if enabled else "frozen_non_deduplicated_control", "context_material": before.data(), "record_digest": raw.content_hash, **({"admission_receipt": raw_receipt} if raw_receipt else {})}))
        if enabled:
            receipt = _admit(self.admission_port, workflow.session.task, record); roots.append(_append(workflow.session, record, receipt)); after = _context(workflow, enabled=True, summary=canonical(material["source"]))
        else:
            after = before
        projection = {"schema": "q13-public-projection-v2", "phase": "after", "records": [raw.data(), record.data()], "claim_statement": material["claim_statement"]}
        second = workflow.invoke_model("representation_next", model, instruction="Assess the current supplied public support material.", baseline_summary=canonical(material["source"]), module_context=FrozenRecord.from_dict({"panel_cell": opaque_panel_cell_binding(cell), "public_support_state": projection, "ledger_mode": "deduplicated" if enabled else "frozen_non_deduplicated_control", "context_material": after.data(), "record_digest": record.content_hash, **({"admission_receipt": receipt} if receipt else {})}))
        final = _final(workflow, cell, scenario, model, package, projection, after, {"record_digest": record.content_hash, **({"admission_receipt": receipt} if receipt else {})})
        return workflow._trace("operation_m2_root_dedup" if enabled else "operation_m2_control", "executed", root_ids=[item.root_id for item in roots]), final, (first, second, final)


@dataclass(frozen=True)
class Q14SupportDriver:
    experiment_id: str = "Q1.4"; slots: tuple[str, ...] = ("support_initial", "support_rechecked", "final"); execution_limit: int = 0; docker_execution: str = "not_requested_by_driver"
    material_resolver: Callable[[PublicTask, FrozenRecord], FrozenRecord] | None = None; admission_port: AdmissionPort | None = None
    def run(self, workflow: ModularWorkflow, *, cell: PanelCell, scenario: FrozenRecord, model, package):
        material = _resolve(self.material_resolver, workflow.session.task, scenario, "Q1.4", cell.variant).data(); enabled = "M2" in workflow.enabled
        records = {key: _record(material["identity"], source, source_key=key, representation="raw") for key, source in material["sources"].items()}
        receipts, roots = {}, {}
        if enabled:
            for key, record in records.items(): receipts[key] = _admit(self.admission_port, workflow.session.task, record); roots[key] = _append(workflow.session, record, receipts[key])
            claim = workflow.session.claims.create(material["claim_statement"], subject_bindings={"task": workflow.session.task.identity.task_id})
            workflow.session.claims.apply(claim.claim_id, {"supports": sorted({item.root_id for item in roots.values()}), "refutes": [], "subject_bindings": {"task": workflow.session.task.identity.task_id}}, expected_revision=0)
        before = _context(workflow, enabled=enabled, summary=material["claim_statement"])
        initial = {"schema": "q14-public-support-projection-v1", "phase": "before", "sources": {key: item.data() for key, item in records.items()}, "claim_statement": material["claim_statement"]}
        first = workflow.invoke_model("support_initial", model, instruction="Assess only the supplied public support records.", baseline_summary=material["claim_statement"], module_context=FrozenRecord.from_dict({"panel_cell": opaque_panel_cell_binding(cell), "public_support_state": initial, "context_material": before.data(), "m2": "enabled" if enabled else "frozen_control"}))
        if enabled:
            for action in material["withdraw_actions"]: workflow.session.evidence.withdraw(roots[action["source_key"]].root_id, action["reason"])
            revisions = workflow.session.claims.refresh_after_withdrawal()
            after = _context(workflow, enabled=True, summary=material["claim_statement"])
        else:
            revisions = (); after = before
        withdrawn_roots = {
            canonical(records[action["source_key"]].data()["root_material"])
            for action in material["withdraw_actions"]
        }
        surviving = {
            key: record.data() for key, record in records.items()
            if canonical(record.data()["root_material"]) not in withdrawn_roots
        }
        post = {"schema": "q14-public-support-projection-v1", "phase": "after", "sources": surviving, "withdraw_actions": material["withdraw_actions"], "claim_statement": material["claim_statement"]}
        second = workflow.invoke_model("support_rechecked", model, instruction="Assess the current supplied support records after the declared source actions.", baseline_summary=material["claim_statement"], module_context=FrozenRecord.from_dict({"panel_cell": opaque_panel_cell_binding(cell), "public_support_state": post, "reconstructed_context": after.data(), "m2": "enabled" if enabled else "frozen_control"}))
        final = _final(workflow, cell, scenario, model, package, post, after, {})
        return workflow._trace("operation_m2_support_recheck" if enabled else "operation_m2_control", "executed", revised_claims=[item.claim.data() for item in revisions], surviving_sources=sorted(surviving)), final, (first, second, final)


def install_drivers(target: MutableMapping[str, Any], *, material_resolver=None, admission_port: AdmissionPort | None = None):
    target.update({"Q1.3": Q13RepresentationDriver(material_resolver=material_resolver, admission_port=admission_port), "Q1.4": Q14SupportDriver(material_resolver=material_resolver, admission_port=admission_port)})
    return target
