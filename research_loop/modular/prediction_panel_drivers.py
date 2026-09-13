"""Train-only, planning-only M4 drivers for Q3.2 and Q5.3.

Caller records bind public source and observation identifiers. They are not an
execution receipt, a scientific-independence assertion, or a truth label.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask, required_text
from research_loop.modular.modules.predictions import (
    PredictionRegistry,
    deduplicate_mechanism_predictions,
    deduplicate_titles,
    freeze_shared_experiment,
)
from research_loop.modular.panel_receipts import PanelCell, opaque_panel_cell_binding
from research_loop.ontology import ContractError


_BUNDLE_FIELDS = {"schema", "identity", "public_evidence", "controller_truth", "q32", "q53"}
_EVIDENCE_FIELDS = {"schema", "task_digest", "source_id", "observation_id", "public_summary"}
_TRUTH_FIELDS = {"schema", "marker"}
_SUPPORT_FIELDS = {"schema", "task_digest", "source_id", "observation_id", "public_observation", "branch_ids", "caller_admission_receipt"}
_ADMISSION_FIELDS = {"schema", "task_digest", "source_id", "observation_id", "authority_id", "receipt_digest"}
_Q32_PLAN_FIELDS = {"question", "branches", "budget_units", "support_records"}
_Q53_PLAN_FIELDS = {"question", "branches", "budget_units"}
_BRANCH_FIELDS = {"hypothesis_id", "mechanism_key", "mechanism", "intervention", "elimination_condition", "predictions"}
_PROPOSAL_FIELDS = {"proposal_id", "root_id", "mechanism_key", "prediction_signature", "title"}


def _integer(value: Any, field: str) -> int:
    if type(value) is not int or value <= 0:
        raise ContractError(f"{field} must be a positive integer")
    return value


def _branch(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _BRANCH_FIELDS:
        raise ContractError("prediction material needs complete operational branches")
    return dict(value)


def _public_evidence(task: PublicTask, value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _EVIDENCE_FIELDS or value.get("schema") != "prediction-public-evidence-v1":
        raise ContractError("prediction bundle requires closed public evidence")
    if value.get("task_digest") != task.content_hash:
        raise ContractError("public evidence does not bind the prepared task")
    for field in ("source_id", "observation_id", "public_summary"):
        required_text(value.get(field), f"public evidence {field}")
    return dict(value)


def _controller_truth(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _TRUTH_FIELDS or value.get("schema") != "prediction-controller-truth-v1":
        raise ContractError("prediction bundle requires closed controller-only truth")
    required_text(value.get("marker"), "controller truth marker")
    return dict(value)


def _support_record(task: PublicTask, value: Any, *, branch_ids: set[str]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _SUPPORT_FIELDS or value.get("schema") != "prediction-support-record-v1":
        raise ContractError("Q3.2 support record is not closed")
    if value.get("task_digest") != task.content_hash:
        raise ContractError("Q3.2 support record does not bind the prepared task")
    for field in ("source_id", "observation_id", "public_observation"):
        required_text(value.get(field), f"support record {field}")
    references = value.get("branch_ids")
    if not isinstance(references, list) or set(references) != branch_ids or len(references) != len(branch_ids):
        raise ContractError("support record must cite exactly its plan branches")
    receipt = value.get("caller_admission_receipt")
    if (not isinstance(receipt, Mapping) or set(receipt) != _ADMISSION_FIELDS
            or receipt.get("schema") != "caller-observation-admission-v1"):
        raise ContractError("support record requires a caller admission receipt")
    if (receipt.get("task_digest") != task.content_hash or receipt.get("source_id") != value["source_id"]
            or receipt.get("observation_id") != value["observation_id"]):
        raise ContractError("caller admission receipt does not bind its support record")
    for field in ("authority_id", "receipt_digest"):
        required_text(receipt.get(field), f"caller admission {field}")
    return dict(value)


def _validate_branches(branches: Any, *, field: str) -> list[dict[str, Any]]:
    if not isinstance(branches, list) or len(branches) < 2:
        raise ContractError(f"{field} needs at least two competing branches")
    parsed = [_branch(item) for item in branches]
    if len({item["hypothesis_id"] for item in parsed}) != len(parsed) or len({item["mechanism_key"] for item in parsed}) != len(parsed):
        raise ContractError(f"{field} needs unique hypothesis and candidate mechanism keys")
    common: set[str] | None = None
    for branch in parsed:
        for name in ("hypothesis_id", "mechanism_key", "mechanism", "intervention", "elimination_condition"):
            required_text(branch.get(name), f"{field} branch {name}")
        predictions = branch["predictions"]
        if not isinstance(predictions, list) or not predictions:
            raise ContractError(f"{field} branch needs predictions")
        identifiers = set()
        discriminators = set()
        for prediction in predictions:
            expected = {"prediction_id", "discriminator_id", "observable", "direction", "value_range", "failure_condition"}
            if not isinstance(prediction, Mapping) or set(prediction) != expected:
                raise ContractError(f"{field} prediction has an unexpected schema")
            for name in ("prediction_id", "discriminator_id", "observable", "failure_condition"):
                required_text(prediction.get(name), f"{field} prediction {name}")
            direction, value_range = prediction["direction"], prediction["value_range"]
            if (direction is None) == (value_range is None):
                raise ContractError("prediction requires exactly one of direction or value range")
            if direction is not None:
                required_text(direction, f"{field} prediction direction")
            if value_range is not None:
                if (not isinstance(value_range, list) or len(value_range) != 2
                        or any(type(item) not in {int, float} for item in value_range) or value_range[0] > value_range[1]):
                    raise ContractError(f"{field} prediction value range is invalid")
            identifiers.add(prediction["prediction_id"]); discriminators.add(prediction["discriminator_id"])
        if len(identifiers) != len(predictions):
            raise ContractError(f"{field} branch has duplicate prediction ids")
        common = discriminators if common is None else common & discriminators
    if not common:
        raise ContractError(f"{field} needs a shared discriminator")
    return parsed


def _validate_plan(task: PublicTask, plan: Mapping[str, Any], *, expected_fields: set[str], field: str,
                   allow_identical_predictions: bool = False) -> dict[str, Any]:
    if not isinstance(plan, Mapping) or set(plan) != expected_fields:
        raise ContractError(f"{field} has an unexpected schema")
    question = required_text(plan.get("question"), f"{field} question")
    budget = _integer(plan.get("budget_units"), f"{field} budget")
    parsed = _validate_branches(plan.get("branches"), field=field)
    # In-memory schema validation before any model slot is reserved.
    if not allow_identical_predictions:
        freeze_shared_experiment(PredictionRegistry(task.identity), question, parsed, budget_units=budget)
    return dict(plan)


def _q32_variant(task: PublicTask, key: str, value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {"plans"} or not isinstance(value["plans"], list):
        raise ContractError("Q3.2 requires closed plan material")
    plans = value["plans"]
    if len(plans) != (1 if key == "joint" else 3):
        raise ContractError("Q3.2 needs its declared plan layout")
    parsed = [_validate_plan(task, item, expected_fields=_Q32_PLAN_FIELDS, field="Q3.2 plan") for item in plans]
    budgets = [item["budget_units"] for item in parsed]
    if budgets != ([3] if key == "joint" else [1, 1, 1]):
        raise ContractError("Q3.2 variants require exactly three planning units")
    support_keys: list[tuple[str, str]] = []
    plan_keys: list[str] = []
    for plan in parsed:
        records = plan["support_records"]
        if not isinstance(records, list) or len(records) != 1:
            raise ContractError("each Q3.2 plan requires one bound support record")
        branch_ids = {item["hypothesis_id"] for item in plan["branches"]}
        record = _support_record(task, records[0], branch_ids=branch_ids)
        support_keys.append((record["source_id"], record["observation_id"]))
        plan_keys.append(FrozenRecord.from_dict({name: plan[name] for name in ("question", "branches", "budget_units")}).content_hash)
    if key == "separate" and (len(set(support_keys)) != 3 or len(set(plan_keys)) != 3):
        raise ContractError("Q3.2 separate plans require three distinct source-observation and plan bindings")
    return {"plans": parsed}


def _prediction_signature(branch: Mapping[str, Any]) -> str:
    semantic = [{name: prediction[name] for name in ("discriminator_id", "observable", "direction", "value_range", "failure_condition")}
                for prediction in branch["predictions"]]
    return FrozenRecord.from_dict({"predictions": semantic}).content_hash


def _q53_variant(task: PublicTask, value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {"proposals", "plan"} or not isinstance(value["proposals"], list):
        raise ContractError("Q5.3 requires typed proposals and plan")
    plan = _validate_plan(task, value["plan"], expected_fields=_Q53_PLAN_FIELDS, field="Q5.3 plan",
                          allow_identical_predictions=True)
    by_id = {branch["hypothesis_id"]: branch for branch in plan["branches"]}
    proposals = value["proposals"]
    if len(proposals) < 2 or len(proposals) != len(by_id):
        raise ContractError("Q5.3 requires one proposal for every candidate branch")
    parsed: list[dict[str, Any]] = []
    for proposal in proposals:
        if not isinstance(proposal, Mapping) or set(proposal) != _PROPOSAL_FIELDS:
            raise ContractError("Q5.3 proposal malformed")
        item = dict(proposal)
        proposal_id = required_text(item["proposal_id"], "proposal id")
        branch = by_id.get(proposal_id)
        if branch is None or item["mechanism_key"] != branch["mechanism_key"]:
            raise ContractError("Q5.3 proposal does not bind an actual branch mechanism")
        for field in ("root_id", "title"):
            required_text(item[field], f"proposal {field}")
        if item["prediction_signature"] != _prediction_signature(branch):
            raise ContractError("Q5.3 proposal does not bind an actual branch prediction")
        parsed.append(item)
    if len({item["proposal_id"] for item in parsed}) != len(parsed):
        raise ContractError("Q5.3 proposal ids must be unique")
    return {"proposals": parsed, "plan": plan}


def _validated_bundle(task: PublicTask, body: Any) -> dict[str, Any]:
    if (not isinstance(body, Mapping) or set(body) != _BUNDLE_FIELDS
            or body.get("schema") != "typed-prediction-panel-bundle-v2"
            or body.get("identity") != task.identity.data()):
        raise ContractError("prediction driver requires a closed typed caller bundle")
    q32, q53 = body.get("q32"), body.get("q53")
    if not isinstance(q32, Mapping) or set(q32) != {"joint", "separate"}:
        raise ContractError("prediction bundle lacks frozen Q3.2 variants")
    if not isinstance(q53, Mapping) or set(q53) != {"same_mechanism", "opposite_prediction", "title"}:
        raise ContractError("prediction bundle lacks frozen Q5.3 variants")
    return {"schema": "typed-prediction-panel-bundle-v2", "identity": task.identity.data(),
            "public_evidence": _public_evidence(task, body["public_evidence"]),
            "controller_truth": _controller_truth(body["controller_truth"]),
            "q32": {name: _q32_variant(task, name, q32[name]) for name in ("joint", "separate")},
            "q53": {name: _q53_variant(task, q53[name]) for name in ("same_mechanism", "opposite_prediction", "title")}}


def freeze_prediction_bundle(task: PublicTask, *, public_evidence: Mapping[str, Any],
                             controller_truth: Mapping[str, Any], q32: Mapping[str, Any],
                             q53: Mapping[str, Any]) -> FrozenRecord:
    if not isinstance(task, PublicTask):
        raise ContractError("prediction bundle needs a prepared public task")
    body = _validated_bundle(task, {"schema": "typed-prediction-panel-bundle-v2", "identity": task.identity.data(),
        "public_evidence": dict(public_evidence), "controller_truth": dict(controller_truth),
        "q32": {name: dict(value) for name, value in q32.items()},
        "q53": {name: dict(value) for name, value in q53.items()}})
    return FrozenRecord.from_dict(body)


def _bundle(task: PublicTask, body: Any) -> dict[str, Any]:
    return _validated_bundle(task, body)


def prediction_panel_injection(experiment_id: str, variant: str, *, task: FrozenRecord,
                               evidence: FrozenRecord) -> Mapping[str, Any]:
    raw = task.data()
    public = PublicTask(DataIdentity.parse(raw["identity"]), FrozenRecord.from_dict(raw["payload"]))
    body = _bundle(public, evidence.data())
    key = "q32" if experiment_id == "Q3.2" else "q53"
    if experiment_id not in {"Q3.2", "Q5.3"} or variant not in body[key]:
        raise ContractError("prediction bundle lacks selected variant")
    return {"schema": "prediction-panel-controller-v2", "material_bundle": body}


def _material(task: PublicTask, scenario: FrozenRecord, experiment: str, variant: str) -> tuple[dict[str, Any], dict[str, Any]]:
    controller = scenario.data().get("controller_input", {})
    body = _bundle(task, controller.get("material_bundle", {}))
    if scenario.data().get("base", {}).get("evidence") != FrozenRecord.from_dict(body).content_hash:
        raise ContractError("prediction bundle does not bind scenario evidence")
    key = "q32" if experiment == "Q3.2" else "q53"
    try:
        return body["public_evidence"], body[key][variant]
    except KeyError as exc:
        raise ContractError("prediction scenario lacks its registered material") from exc


def _final(workflow: Any, cell: PanelCell, model: Any, material: Mapping[str, Any]) -> FrozenRecord:
    return workflow.invoke_model("final", model, instruction="Return bounded train-only candidate. Copy required_objective_digest exactly.",
        module_context=FrozenRecord.from_dict({"panel_cell": opaque_panel_cell_binding(cell),
            "required_objective_digest": workflow.session.objective.content_hash,
            "prediction_artifacts": dict(material)}))


def _response_plan(response: FrozenRecord, plan: Mapping[str, Any]) -> dict[str, Any]:
    body = response.data()
    expected = {name: plan[name] for name in ("question", "branches", "budget_units")}
    if body != expected:
        raise ContractError("Q3.2 model response must exactly confirm its frozen operational plan")
    return body


def _dedup_inputs(proposals: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    return [{"proposal_id": item["proposal_id"], "mechanism_key": item["root_id"],
             "prediction_signature": item["prediction_signature"], "title": item["title"]}
            for item in proposals]


def _kept_response(response: FrozenRecord, expected: Sequence[str]) -> tuple[str, ...]:
    body = response.data()
    if set(body) != {"kept_proposal_ids"} or not isinstance(body["kept_proposal_ids"], list):
        raise ContractError("Q5.3 model response requires retained proposal ids")
    if body["kept_proposal_ids"] != list(expected):
        raise ContractError("Q5.3 model response does not match the mechanism-prediction deduplication")
    return tuple(body["kept_proposal_ids"])


@dataclass(frozen=True)
class Q32JointSeparateDriver:
    experiment_id: str = "Q3.2"
    slots: tuple[str, ...] = ("plan_1", "plan_2", "plan_3", "final")
    execution_limit: int = 0
    docker_execution: str = "not_requested_by_driver"

    def slots_for(self, cell: PanelCell) -> tuple[str, ...]:
        return self.slots

    def run(self, workflow: Any, *, cell: PanelCell, scenario: FrozenRecord, model: Any, package: Any) -> tuple[Any, FrozenRecord, tuple[FrozenRecord, ...]]:
        evidence, data = _material(workflow.session.task, scenario, "Q3.2", cell.variant)
        plans = data["plans"]
        responses: list[FrozenRecord] = []
        artifacts: list[dict[str, Any]] = []
        joint_plan = None
        for index in range(3):
            plan = plans[0] if cell.variant == "joint" else plans[index]
            response = workflow.invoke_model(f"plan_{index + 1}", model,
                instruction="Return exactly the supplied public operational prediction plan.",
                module_context=FrozenRecord.from_dict({"panel_cell": opaque_panel_cell_binding(cell),
                    "public_evidence": evidence, "plan_material": plan}))
            responses.append(response)
            if "M4" in workflow.enabled:
                confirmed = _response_plan(response, plan)
                if cell.variant == "joint":
                    joint_plan = joint_plan or freeze_shared_experiment(workflow.predictions, confirmed["question"],
                        confirmed["branches"], budget_units=confirmed["budget_units"])
                    frozen = joint_plan
                else:
                    frozen = freeze_shared_experiment(workflow.predictions, confirmed["question"],
                        confirmed["branches"], budget_units=confirmed["budget_units"])
                artifacts.append({"plan": frozen.payload.data(), "support_records": plan["support_records"],
                    "response": response.data(), "planning_status": "planning_only",
                    "execution_status": "not_measured"})
            else:
                artifacts.append({"plan": None, "support_records": plan["support_records"], "response": response.data(),
                    "planning_status": "not_applied", "execution_status": "not_measured"})
        stage = workflow._trace("stage_1" if "M4" in workflow.enabled else "operation_m4_control", "executed",
            artifact_count=len(artifacts), planning_status="planning_only", execution_status="not_measured")
        final = _final(workflow, cell, model, {"joint_or_separate": artifacts})
        if final.data().get("objective_digest") != workflow.session.objective.content_hash:
            raise ContractError("Q3.2 final objective mismatch")
        return stage, final, tuple(responses + [final])


@dataclass(frozen=True)
class Q53DedupDriver:
    experiment_id: str = "Q5.3"
    slots: tuple[str, ...] = ("dedup", "final")
    execution_limit: int = 0
    docker_execution: str = "not_requested_by_driver"

    def slots_for(self, cell: PanelCell) -> tuple[str, ...]:
        return self.slots

    def run(self, workflow: Any, *, cell: PanelCell, scenario: FrozenRecord, model: Any, package: Any) -> tuple[Any, FrozenRecord, tuple[FrozenRecord, ...]]:
        evidence, data = _material(workflow.session.task, scenario, "Q5.3", cell.variant)
        proposals, plan = data["proposals"], data["plan"]
        dedup_input = _dedup_inputs(proposals)
        expected_kept, removed = deduplicate_mechanism_predictions(dedup_input)
        title_kept, title_removed = deduplicate_titles(dedup_input)
        response = workflow.invoke_model("dedup", model,
            instruction="Return the retained proposal ids after mechanism-root and prediction-signature deduplication.",
            module_context=FrozenRecord.from_dict({"panel_cell": opaque_panel_cell_binding(cell),
                "public_evidence": evidence, "proposals": proposals, "plan_material": plan}))
        if "M4" in workflow.enabled:
            kept = _kept_response(response, expected_kept)
            branches_by_id = {branch["hypothesis_id"]: branch for branch in plan["branches"]}
            retained = [branches_by_id[item] for item in kept]
            if len(retained) < 2:
                artifact = {"kept": list(kept), "removed": list(removed),
                    "title_baseline": {"kept": list(title_kept), "removed": list(title_removed)},
                    "plan": None, "response": response.data(),
                    "planning_status": "not_distinguishable_after_dedup", "execution_status": "not_measured"}
            else:
                frozen = freeze_shared_experiment(workflow.predictions, plan["question"], retained,
                    budget_units=plan["budget_units"])
                artifact = {"kept": list(kept), "removed": list(removed),
                    "title_baseline": {"kept": list(title_kept), "removed": list(title_removed)},
                    "plan": frozen.payload.data(), "response": response.data(),
                    "planning_status": "planning_only", "execution_status": "not_measured"}
        else:
            artifact = {"kept": None, "removed": None, "title_baseline": None, "plan": None,
                "response": response.data(), "planning_status": "not_applied", "execution_status": "not_measured"}
        stage = workflow._trace("stage_1" if "M4" in workflow.enabled else "operation_m4_control", "executed",
            dedup_applied="M4" in workflow.enabled, planning_status=artifact["planning_status"],
            execution_status="not_measured")
        final = _final(workflow, cell, model, {"deduplication": artifact})
        if final.data().get("objective_digest") != workflow.session.objective.content_hash:
            raise ContractError("Q5.3 final objective mismatch")
        return stage, final, (response, final)
