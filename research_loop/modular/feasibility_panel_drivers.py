"""Train-only Q5.1/Q5.2 drivers with real bounded Docker receipts.

Authority verifier ports are configured outside this module.  A verified
signature and source binding establish provenance only; they do not establish
scientific correctness or calibration.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, MutableMapping, Protocol

from research_loop.modular.benchmarks.execution import DockerExecutionBroker, ExecutionReceipt
from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask, required_text, strict_bool
from research_loop.modular.modules.exploration import ExplorationPlan, FeasibilityObservation, ResourceClosure, assess_feasibility
from research_loop.modular.modules.predictions import PredictionRegistry
from research_loop.modular.panel_receipts import opaque_panel_cell_binding
from research_loop.ontology import ContractError


_Q51 = ("subjective", "data", "minimal_run", "measurement", "independent")
_Q52 = ("zero_exit_same_prediction", "negative_control")
_STAGES = ("data", "minimal_run", "discriminating_measurement", "independent_result")


class FeasibilityAuthorityPort(Protocol):
    """Caller-owned signature verifier; it must not return an unsigned dict."""
    def verify_stage(self, subject: FrozenRecord) -> FrozenRecord: ...


class PublicInputResolver(Protocol):
    def __call__(self, task: PublicTask, bundle: FrozenRecord) -> Mapping[str, Path]: ...


def _map(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError(f"{name} must be a mapping")
    return value


def _hex(value: Any, name: str) -> str:
    value = required_text(value, name)
    if len(value) != 64 or any(item not in "0123456789abcdef" for item in value):
        raise ContractError(f"{name} must be a sha256 digest")
    return value


def _inputs(value: Any) -> dict[str, dict[str, Any]]:
    rows = _map(value, "public CSV artifact declarations")
    if not rows:
        raise ContractError("at least one public CSV artifact is required")
    result = {}
    for artifact_id, row in rows.items():
        row = dict(_map(row, "public CSV artifact"))
        if set(row) != {"sha256", "byte_count"} or type(row["byte_count"]) is not int or row["byte_count"] < 0:
            raise ContractError("public CSV artifact declaration is invalid")
        result[required_text(artifact_id, "artifact id")] = {"sha256": _hex(row["sha256"], "artifact sha256"),
                                                               "byte_count": row["byte_count"]}
    return result


def _closure(value: Any) -> dict[str, Any]:
    row = dict(_map(value, "resource closure"))
    if set(row) != {"data_version", "minimum_artifact_digest", "negative_control_id", "execution_units", "token_units"}:
        raise ContractError("resource closure fields are incomplete")
    ResourceClosure(**row)
    return row


def _stage_contracts(value: Any, identity: DataIdentity) -> dict[str, dict[str, str]]:
    rows = _map(value, "stage contracts")
    if set(rows) != set(_STAGES):
        raise ContractError("every feasibility stage needs a caller source-bound contract")
    result = {}
    for stage, row in rows.items():
        row = dict(_map(row, "stage contract"))
        if set(row) != {"source_id", "contract_id"} or row["source_id"] != identity.group_id:
            raise ContractError("stage contract does not bind the public task source")
        result[stage] = {"source_id": required_text(row["source_id"], "stage source"),
                         "contract_id": required_text(row["contract_id"], "stage contract id")}
    return result


def _item(value: Any, identity: DataIdentity, *, prediction: bool) -> dict[str, Any]:
    row = dict(_map(value, "feasibility material"))
    required = {"source_id", "program", "program_sha256", "image", "inputs", "closure", "stage_contracts", "measurement_contract"}
    if prediction:
        required.add("branches")
    if set(row) != required or row["source_id"] != identity.group_id:
        raise ContractError("feasibility material has incomplete or unbound fields")
    program = required_text(row["program"], "bounded public program")
    if "\r" in program or hashlib.sha256(program.replace("\n", os.linesep).encode("utf-8")).hexdigest() != _hex(row["program_sha256"], "program sha256"):
        raise ContractError("program text and frozen byte hash differ")
    image = required_text(row["image"], "pinned execution image")
    # ExecutionRequest validates the image grammar again at the execution edge.
    result = {"source_id": required_text(row["source_id"], "material source"), "program": program,
              "program_sha256": row["program_sha256"], "image": image, "inputs": _inputs(row["inputs"]),
              "closure": _closure(row["closure"]), "stage_contracts": _stage_contracts(row["stage_contracts"], identity),
              "measurement_contract": FrozenRecord.from_dict(dict(_map(row["measurement_contract"], "measurement contract"))).data()}
    if not result["measurement_contract"]:
        raise ContractError("measurement contract cannot be empty")
    if prediction:
        branches = row["branches"]
        if not isinstance(branches, list) or len(branches) < 2:
            raise ContractError("Q5.2 requires caller-supplied competing prediction branches")
        result["branches"] = branches
    return result


def freeze_feasibility_panel_bundle(task: PublicTask, *, q51: Mapping[str, Mapping[str, Any]],
                                    q52: Mapping[str, Mapping[str, Any]]) -> FrozenRecord:
    if not isinstance(task, PublicTask) or not isinstance(q51, Mapping) or not isinstance(q52, Mapping):
        raise ContractError("feasibility bundle needs public task material")
    if set(q51) != set(_Q51) or set(q52) != set(_Q52):
        raise ContractError("feasibility bundle variant coverage mismatch")
    return FrozenRecord.from_dict({"schema": "feasibility-panel-bundle-v1", "identity": task.identity.data(),
        "payload_digest": task.payload.content_hash, "q51": {name: _item(item, task.identity, prediction=False) for name, item in q51.items()},
        "q52": {name: _item(item, task.identity, prediction=True) for name, item in q52.items()}})


def feasibility_panel_injection(experiment_id: str, variant: str, *, task: FrozenRecord, evidence: FrozenRecord) -> Mapping[str, Any]:
    if experiment_id not in {"Q5.1", "Q5.2"}:
        raise ContractError("feasibility injection only covers Q5.1/Q5.2")
    public = PublicTask(DataIdentity.parse(task.data()["identity"]), FrozenRecord.from_dict(task.data()["payload"]))
    body = evidence.data()
    if body.get("schema") != "feasibility-panel-bundle-v1":
        raise ContractError("caller-frozen feasibility bundle is required")
    bundle = FrozenRecord.from_dict(body)
    remade = freeze_feasibility_panel_bundle(public, q51=body.get("q51", {}), q52=body.get("q52", {}))
    if bundle.content_hash != remade.content_hash:
        raise ContractError("feasibility bundle is not a closed canonical reconstruction")
    if variant not in body["q51" if experiment_id == "Q5.1" else "q52"]:
        raise ContractError("feasibility variant is not registered")
    return {"schema": "feasibility-panel-controller-v1", "bundle": bundle.data()}


def _material(task: PublicTask, scenario: FrozenRecord, experiment_id: str, variant: str) -> tuple[FrozenRecord, dict[str, Any]]:
    body = scenario.data()
    if set(body) != {"experiment_id", "variant", "controller_input", "base", "controls"} or body["experiment_id"] != experiment_id or body["variant"] != variant:
        raise ContractError("feasibility scenario binding drift")
    controller = _map(body["controller_input"], "feasibility controller")
    if set(controller) != {"schema", "bundle"} or controller["schema"] != "feasibility-panel-controller-v1":
        raise ContractError("feasibility controller fields are incomplete")
    bundle = FrozenRecord.from_dict(dict(_map(controller["bundle"], "feasibility bundle")))
    raw = bundle.data(); remade = freeze_feasibility_panel_bundle(task, q51=raw.get("q51", {}), q52=raw.get("q52", {}))
    base = _map(body["base"], "feasibility base")
    if (bundle.content_hash != remade.content_hash or set(base) != {"task", "evidence", "budget"}
            or base["task"] != task.content_hash or base["evidence"] != bundle.content_hash):
        raise ContractError("feasibility caller material does not bind this scenario task")
    key = "q51" if experiment_id == "Q5.1" else "q52"
    return bundle, raw[key][variant]


def _authority(port: FeasibilityAuthorityPort, subject: FrozenRecord, *, independent: bool, identity: DataIdentity) -> tuple[FeasibilityObservation, dict[str, Any]]:
    verify = getattr(port, "verify_stage", None)
    if not callable(verify):
        raise ContractError("configured feasibility authority must verify signed stage receipts")
    receipt = verify(subject)
    if not isinstance(receipt, FrozenRecord):
        raise ContractError("authority verifier may not return an ordinary dict")
    row = receipt.data(); required = {"schema", "subject_digest", "authorities", "signature_verified", "status", "independent_source_group", "classifications"}
    if set(row) != required or row["schema"] != "verified-feasibility-stage-v1" or row["subject_digest"] != subject.content_hash:
        raise ContractError("verified stage authority receipt has invalid subject binding")
    if not isinstance(row["authorities"], list) or len(row["authorities"]) < 2 or len(set(row["authorities"])) != len(row["authorities"]) or any(not isinstance(item, str) or not item for item in row["authorities"]):
        raise ContractError("stage authority receipt needs distinct signed authorities")
    if strict_bool(row["signature_verified"], "stage signature verified") is not True or row["status"] not in {"passed", "failed", "unknown"}:
        raise ContractError("stage authority is not a verified typed result")
    group = row["independent_source_group"]
    if group is not None and (not isinstance(group, str) or not group):
        raise ContractError("independent source group must be text or null")
    if independent and row["status"] == "passed" and (group is None or group == identity.group_id):
        raise ContractError("independent result lacks a separate source group")
    classifications = row["classifications"]
    if classifications is not None and (not isinstance(classifications, Mapping) or any(not isinstance(key, str) or value not in {"consistent", "failed", "unknown"} for key, value in classifications.items())):
        raise ContractError("authority classifications are invalid")
    return FeasibilityObservation(subject.data()["stage"], row["status"], receipt.content_hash, group), dict(row)


def _execute(workflow, *, bundle: FrozenRecord, item: Mapping[str, Any], broker: DockerExecutionBroker, resolver: PublicInputResolver) -> tuple[ExecutionReceipt, tuple[Any, ...]]:
    inputs = resolver(workflow.session.task, bundle)
    if not isinstance(inputs, Mapping) or set(inputs) != set(item["inputs"]):
        raise ContractError("public input resolver does not provide the frozen artifact set")
    artifacts = broker.validate_inputs(workflow.session.task.identity, inputs)
    for artifact in artifacts:
        expected = item["inputs"][artifact.artifact_id]
        if artifact.sha256 != expected["sha256"] or artifact.byte_count != expected["byte_count"]:
            raise ContractError("actual public CSV bytes differ from the frozen artifact declaration")
    receipt = workflow.session.execute(item["program"], broker=broker, image=item["image"], inputs=inputs)
    if receipt.artifact is None or receipt.artifact.sha256 != item["program_sha256"]:
        raise ContractError("actual execution program artifact differs from frozen byte hash")
    return receipt, artifacts


def _stage_subject(task: PublicTask, bundle: FrozenRecord, item: Mapping[str, Any], *, stage: str,
                   execution: ExecutionReceipt, artifacts, plan_digest: str | None) -> FrozenRecord:
    return FrozenRecord.from_dict({"schema": "feasibility-stage-subject-v1", "identity": task.identity.data(),
        "task_digest": task.content_hash, "bundle_digest": bundle.content_hash, "source_id": item["source_id"], "stage": stage,
        "stage_contract": item["stage_contracts"][stage], "measurement_contract": item["measurement_contract"],
        "program_sha256": item["program_sha256"], "input_artifacts": [artifact.record.data() for artifact in artifacts],
        "execution_digest": execution.content_hash, "execution_status": execution.status, "prediction_plan_digest": plan_digest})


def _subjective(workflow, cell, model, item, execution: ExecutionReceipt) -> FrozenRecord:
    response = workflow.invoke_model("subjective", model, instruction="Assess the supplied public feasibility material only. Return feasibility, rationale, and no scientific claim.",
        module_context=FrozenRecord.from_dict({"panel_cell": opaque_panel_cell_binding(cell), "required_objective_digest": workflow.session.objective.content_hash,
            "public_material": {"program_sha256": item["program_sha256"], "inputs": item["inputs"], "measurement_contract": item["measurement_contract"]},
            "execution_receipt": execution.data()}))
    row = response.data()
    if set(row) != {"feasibility", "rationale"} or row["feasibility"] not in {"feasible", "infeasible", "unknown"} or not isinstance(row["rationale"], str) or not row["rationale"].strip():
        raise ContractError("subjective feasibility response is invalid")
    return response


def _final(workflow, cell, model, *, execution: ExecutionReceipt, report: Mapping[str, Any], subjective: FrozenRecord) -> FrozenRecord:
    response = workflow.invoke_model("final", model, instruction="Return the bounded train-only candidate record. Copy required_objective_digest exactly; feasibility is not scientific evidence.",
        module_context=FrozenRecord.from_dict({"panel_cell": opaque_panel_cell_binding(cell), "required_objective_digest": workflow.session.objective.content_hash,
            "execution_receipt": execution.data(), "actual_artifact_summary": {"authority_receipt_digests": report.get("authority_receipts", []),
                "prediction_plan_digest": report.get("prediction_plan_digest")}, "subjective_assessment": subjective.data()}))
    row = response.data()
    if (set(row) != {"objective_digest", "outcome", "evidence_ids", "conclusion", "programme_complete"} or row["objective_digest"] != workflow.session.objective.content_hash
            or row["outcome"] not in {"positive", "negative", "unknown", "invalid", "withdrawn"} or row["evidence_ids"] != []
            or not isinstance(row["conclusion"], str) or not row["conclusion"].strip() or row["programme_complete"] is not False):
        raise ContractError("feasibility final candidate is invalid")
    return response


@dataclass(frozen=True)
class Q51FeasibilityDriver:
    broker: DockerExecutionBroker
    input_resolver: PublicInputResolver
    authority: FeasibilityAuthorityPort
    experiment_id: str = "Q5.1"
    slots: tuple[str, ...] = ("subjective", "final")
    execution_limit: int = 1
    docker_execution: str = "one_matched_public_docker_execution"

    def slots_for(self, cell): return self.slots

    def run(self, workflow, *, cell, scenario: FrozenRecord, model, package):
        bundle, item = _material(workflow.session.task, scenario, self.experiment_id, cell.variant)
        execution, artifacts = _execute(workflow, bundle=bundle, item=item, broker=self.broker, resolver=self.input_resolver)
        subjective = _subjective(workflow, cell, model, item, execution)
        observations = {}
        if "M7" in workflow.enabled:
            for stage in _STAGES:
                subject = _stage_subject(workflow.session.task, bundle, item, stage=stage, execution=execution, artifacts=artifacts, plan_digest=None)
                observations[stage], _ = _authority(self.authority, subject, independent=stage == "independent_result", identity=workflow.session.task.identity)
            plan = ExplorationPlan("q51-" + bundle.content_hash, workflow.session.task.identity, bundle, ResourceClosure(**item["closure"]))
            report = assess_feasibility(plan, observations)
            detail = {"subjective": subjective.data(), "stages": dict(report.stages), "next_stage": report.next_stage,
                      "authority_receipts": [value.artifact_digest for value in observations.values()]}
            stage = workflow._trace("stage_3", "executed", **detail, execution_digest=execution.content_hash)
        else:
            detail = {"subjective": subjective.data(), "stages": {stage: "not_gated" for stage in _STAGES}, "next_stage": None,
                      "authority_receipts": []}
            stage = workflow._trace("operation_m7_control", "executed", **detail, execution_digest=execution.content_hash)
        final = _final(workflow, cell, model, execution=execution, report=detail, subjective=subjective)
        return stage, final, (subjective, final)


@dataclass(frozen=True)
class Q52DistinguishabilityDriver:
    broker: DockerExecutionBroker
    input_resolver: PublicInputResolver
    authority: FeasibilityAuthorityPort
    experiment_id: str = "Q5.2"
    slots: tuple[str, ...] = ("subjective", "final")
    execution_limit: int = 1
    docker_execution: str = "one_matched_public_docker_execution"

    def slots_for(self, cell): return self.slots

    def run(self, workflow, *, cell, scenario: FrozenRecord, model, package):
        bundle, item = _material(workflow.session.task, scenario, self.experiment_id, cell.variant)
        registry = PredictionRegistry(workflow.session.task.identity, storage_path=workflow.session.sidecar / "predictions.jsonl")
        plan = None; m4_status = "control_no_runtime_plan"
        if "M4" in workflow.enabled:
            try:
                plan = registry.freeze("caller-frozen public distinguishability", item["branches"], budget_units=1)
                m4_status = "frozen"
            except ContractError as exc:
                m4_status = "unidentifiable_rejected"
                workflow._trace("m4_prediction_rejected", "rejected", error_type=type(exc).__name__)
        execution, artifacts = _execute(workflow, bundle=bundle, item=item, broker=self.broker, resolver=self.input_resolver)
        subjective = _subjective(workflow, cell, model, item, execution)
        observations = {}; authority_rows = {}
        if "M7" in workflow.enabled:
            for stage in _STAGES:
                subject = _stage_subject(workflow.session.task, bundle, item, stage=stage, execution=execution, artifacts=artifacts,
                    plan_digest=plan.payload.content_hash if plan else None)
                observations[stage], authority_rows[stage] = _authority(self.authority, subject, independent=stage == "independent_result", identity=workflow.session.task.identity)
        update_digest = None
        if plan is not None:
            if "discriminating_measurement" in observations:
                outcome = observations["discriminating_measurement"]
                outcome_row = authority_rows["discriminating_measurement"]
            else:
                measurement_subject = _stage_subject(workflow.session.task, bundle, item, stage="discriminating_measurement", execution=execution,
                    artifacts=artifacts, plan_digest=plan.payload.content_hash)
                outcome, outcome_row = _authority(self.authority, measurement_subject, independent=False, identity=workflow.session.task.identity)
            classifications = outcome_row["classifications"]
            if not isinstance(classifications, Mapping) or set(classifications) != {branch.hypothesis_id for branch in plan.branches}:
                raise ContractError("verified measurement authority lacks classifications for every frozen hypothesis")
            update = registry.record_outcome(plan.plan_id, plan.branches[0].predictions[0].discriminator_id, outcome.artifact_digest,
                classifications, {"trusted_evaluator": "+".join(outcome_row["authorities"]), "verified": True})
            update_digest = FrozenRecord.from_dict(update.data()).content_hash
        if "M7" in workflow.enabled:
            frozen = plan.payload if plan is not None else FrozenRecord.from_dict(item["measurement_contract"])
            report = assess_feasibility(ExplorationPlan("q52-" + bundle.content_hash, workflow.session.task.identity, frozen, ResourceClosure(**item["closure"])), observations)
            stages, next_stage = dict(report.stages), report.next_stage
        else:
            stages, next_stage = {stage: "not_gated" for stage in _STAGES}, None
        detail = {"m4_status": m4_status, "prediction_plan_digest": plan.payload.content_hash if plan else None,
                  "prediction_update_digest": update_digest, "stages": stages, "next_stage": next_stage,
                  "authority_receipts": [value.artifact_digest for value in observations.values()]}
        stage = workflow._trace("stage_1" if "M4" in workflow.enabled else "operation_m4_control", "executed", **detail,
            execution_digest=execution.content_hash, m7_enabled="M7" in workflow.enabled)
        final = _final(workflow, cell, model, execution=execution, report=detail, subjective=subjective)
        return stage, final, (subjective, final)


def install_drivers(target: MutableMapping[str, Any], *, broker: DockerExecutionBroker, input_resolver: PublicInputResolver,
                    authority: FeasibilityAuthorityPort):
    target.update({"Q5.1": Q51FeasibilityDriver(broker, input_resolver, authority),
                   "Q5.2": Q52DistinguishabilityDriver(broker, input_resolver, authority)})
    return target
