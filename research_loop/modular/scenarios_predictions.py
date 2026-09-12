"""Fixture-only runners for the remaining M4/M7 prediction scenarios.

The runners bind only an already prepared :class:`PublicTask` and frozen public
controls.  They exercise the real M4 prediction registry and M7 feasibility
ports, while deliberately recording fixture ``unknown`` classifications unless
an injected fixture evaluator supplies another classification.  They do not
load data or labels and they make no claim about benchmark or scientific effect.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask, required_text
from research_loop.modular.modules.exploration import (
    ExplorationPlan, FeasibilityObservation, ResourceClosure, assess_feasibility, select_claimed_diagnostic,
)
from research_loop.modular.modules.predictions import (PredictionPlan, PredictionRegistry,
    deduplicate_mechanism_predictions, freeze_shared_experiment)
from research_loop.modular.modules.predictions import deduplicate_titles
from research_loop.ontology import ContractError, digest


_VARIANTS = {
    "Q3.1": frozenset(("mechanism", "computation", "measurement")),
    "Q3.2": frozenset(("joint", "separate")),
    "Q5.2": frozenset(("zero_exit_same_prediction", "negative_control")),
    "Q5.3": frozenset(("same_mechanism", "opposite_prediction", "title")),
    "Q5.4": frozenset(("subjective", "preregistered_cost")),
}


@dataclass(frozen=True)
class PredictionScenarioResult:
    experiment_id: str
    variant: str
    callback_payloads: tuple[FrozenRecord, ...]
    mechanism_trace: FrozenRecord
    record: FrozenRecord
    callback_responses: tuple[FrozenRecord, ...] = ()


def prediction_injection(experiment_id: str, variant: str) -> Mapping[str, Any]:
    """Closed controller description for the registry hook in ``experiments``."""
    _validate(experiment_id, variant)
    return {"fixture_only": True,
            "fixture_notice": "engineering fixture; not a benchmark measurement",
            "auxiliary": {"prediction_scenario_variant": variant,
                          "requires_public_task": True,
                          "requires_frozen_controls": True}}


def run_prediction_scenario(
    experiment_id: str,
    variant: str,
    *,
    task: PublicTask,
    frozen_controls: FrozenRecord,
    plan_callback: Callable[[FrozenRecord], Mapping[str, str] | None] | None = None,
) -> PredictionScenarioResult:
    """Run one exact Q3/Q5 fixture through frozen M4/M7 mechanism ports.

    The callback receives each actual frozen plan payload.  It may provide a
    fixture-only complete per-branch classification mapping; absence means all
    branches remain ``unknown``.  No observed outcome or expected winner is
    embedded in the implementation.
    """
    _validate(experiment_id, variant)
    controls = _controls(task, frozen_controls)
    registry = PredictionRegistry(task.identity)
    callbacks: list[FrozenRecord] = []
    events: list[dict[str, Any]] = [{"event": "fixture_start", "fixture_only": True,
        "task_digest": task.content_hash, "budget_digest": controls["budget_digest"]}]

    callback_context: dict[str, Any] = {}
    if experiment_id == "Q3.1":
        plans = (_freeze_and_capture(registry, task, callbacks, plan_callback, _three_branch_plan(_intervention(variant)), 3,
                                     observation_ids=("shared-observation-1",)),)
        events.append({"event": "three_competing_mechanisms", "plan_ids": [plans[0].plan_id],
                       "shared_discriminator": "frozen-intervention", "branch_count": 3,
                       "focal_fixture_branch": variant})
    elif experiment_id == "Q3.2":
        if variant == "joint":
            plans = (_freeze_and_capture(registry, task, callbacks, plan_callback, _three_branch_plan("joint-intervention"), 3,
                                         observation_ids=("joint-observation-1", "joint-observation-1", "joint-observation-1")),)
            evidence_layout = [{"hypothesis_id": branch.hypothesis_id, "observation_id": "joint-observation-1"} for branch in plans[0].branches]
        else:
            # Each arm is independently planned with the same total three-unit
            # budget.  A common control branch makes its distinct evidence use
            # explicit instead of allowing separate support searches to look joint.
            plans = tuple(_freeze_and_capture(registry, task, callbacks, plan_callback, pair, 1,
                                               observation_ids=(f"separate-observation-{index}",))
                          for index, pair in enumerate(_separate_pairs(), 1))
            evidence_layout = [{"plan_id": plan.plan_id, "observation_id": f"separate-observation-{index}"}
                               for index, plan in enumerate(plans, 1)]
        events.append({"event": "arm_structure", "mode": variant, "plan_ids": [p.plan_id for p in plans],
                       "total_budget_units": sum(p.budget_units for p in plans),
                       "callback_calls": len(callbacks), "scientific_observations": len({row["observation_id"] for row in evidence_layout}),
                       "evidence_layout": evidence_layout, "selection_bias_not_support": True})
    elif experiment_id == "Q5.2":
        if variant == "zero_exit_same_prediction":
            rejected = _reject_non_discriminating(registry, task, callbacks, plan_callback, events)
            report = _feasibility(task, rejected, "failed", "fixture-same-prediction-measurement")
            plans = ()
        else:
            plan = _freeze_and_capture(registry, task, callbacks, plan_callback, _negative_control_pair(), 2)
            report = _feasibility(task, plan.payload, "passed", "fixture-negative-control-measurement")
            plans = (plan,)
        events.append({"event": "zero_exit_is_not_identifiability", "execution_status": "fixture_zero_exit",
                       "feasibility": dict(report.stages), "next_stage": report.next_stage,
                       "negative_control": variant == "negative_control"})
    elif experiment_id == "Q5.3":
        branches = _opposite_prediction_pair() if variant == "opposite_prediction" else _negative_control_pair()
        proposals = _dedup_proposals(variant)
        kept, removed = deduplicate_mechanism_predictions(proposals)
        title_kept, title_removed = deduplicate_titles(proposals)
        callback_context["dedup"] = {"kept": kept, "removed": removed, "title_baseline": {"kept": title_kept, "removed": title_removed}}
        plan = _freeze_and_capture(registry, task, callbacks, plan_callback, branches, 2, context=callback_context)
        plans = (plan,)
        events.append({"event": "mechanism_prediction_dedup", "mode": variant, "kept": kept,
                       "removed": removed, "title_only_would_keep": [item["title"] for item in proposals],
                       "title_baseline": {"kept": title_kept, "removed": title_removed},
                       "prediction_coverage": sorted({item["prediction_signature"] for item in proposals if item["proposal_id"] in kept})})
    else:  # Q5.4
        selection_plan = _exploration_plan(task)
        policy = FrozenRecord.from_dict({"policy_version": "fixture-frozen-selection-v1", "identity": task.identity.data(),
            "criterion": "subjective" if variant == "subjective" else "uncertainty_per_cost", "frozen_before_validation": True})
        selected = select_claimed_diagnostic(selection_plan, policy, _diagnostics()).data()["diagnostic_id"]
        callback_context["diagnostic_selection"] = {"selected": selected, "policy_digest": policy.content_hash,
                                                       "claimed_plan_digest": selection_plan.content_hash}
        plan = _freeze_and_capture(registry, task, callbacks, plan_callback, _negative_control_pair(), 2, context=callback_context)
        plans = (plan,)
        events.append({"event": "internal_diagnostic_selection", "mode": variant, "selected": selected,
                       "outer_queue": {"policy": "FIFO", "position": 7, "changed": False},
                       "selection_scope": "within_already_claimed_research_item"})

    callback_responses = tuple(_response_record(plan_callback(payload)) for payload in callbacks) if plan_callback else ()
    _record_unknown_outcomes(registry, plans, callbacks, events)
    record = FrozenRecord.from_dict({"fixture_only": True, "experiment_id": experiment_id, "variant": variant,
        "task_digest": task.content_hash, "budget_digest": controls["budget_digest"],
        "plan_ids": [plan.plan_id for plan in plans], "callback_payload_digests": [item.content_hash for item in callbacks],
        "callback_response_digests": [item.content_hash for item in callback_responses],
        "limitation": "mechanism fixture only; it does not measure benchmark efficacy or scientific validity"})
    return PredictionScenarioResult(experiment_id, variant, tuple(callbacks), FrozenRecord.from_dict({"events": events}), record, callback_responses)


def _controls(task: PublicTask, frozen: FrozenRecord) -> dict[str, Any]:
    controls = frozen.data()
    if set(controls) != {"task_digest", "budget_digest", "fixture_only"} or controls["task_digest"] != task.content_hash or controls["fixture_only"] is not True:
        raise ContractError("prediction scenario requires matching frozen fixture controls")
    required_text(controls["budget_digest"], "budget digest")
    return controls


def _freeze_and_capture(registry: PredictionRegistry, task: PublicTask, captured: list[FrozenRecord],
                        callback: Callable[[FrozenRecord], Mapping[str, str] | None] | None,
                        branches: Sequence[Mapping[str, Any]], budget: int, observation_ids: tuple[str, ...] = (), context: Mapping[str, Any] | None = None) -> PredictionPlan:
    plan = freeze_shared_experiment(registry, _question(task), branches, budget_units=budget)
    for observation_id in observation_ids or ("fixture-observation",):
        captured.append(FrozenRecord.from_dict({"schema": "prediction-scenario-plan-v1", "fixture_only": True,
            "task": task.data(), "plan": plan.payload.data(), "plan_id": plan.plan_id,
            "observation_id": observation_id, "call_id": f"{plan.plan_id[:12]}-{len(captured)+1}",
            "scenario_context": dict(context or {})}))
    return plan


def _record_unknown_outcomes(registry: PredictionRegistry, plans: Sequence[PredictionPlan],
                                         payloads: Sequence[FrozenRecord],
                                         events: list[dict[str, Any]]) -> None:
    for plan, payload in zip(plans, payloads):
        classifications = {branch.hypothesis_id: "unknown" for branch in plan.branches}
        shared = next(iter(set.intersection(*({p.discriminator_id for p in b.predictions} for b in plan.branches))))
        update = registry.record_outcome(plan.plan_id, shared, "fixture-observation-" + payload.content_hash[:12], classifications,
                                         {"trusted_evaluator": "fixture-evaluator", "verified": True})
        events.append({"event": "shared_discriminator_recorded", "plan_id": plan.plan_id,
                       "discriminator": shared, "classification_digest": digest(dict(update.per_hypothesis)),
                       "fixture_only": True})


def _three_branch_plan(intervention: str) -> list[dict[str, Any]]:
    return [_branch("mechanism", "organization-effect", "organization changes the outcome", intervention, "positive"),
            _branch("computation", "extra-computation", "extra computation produces the apparent outcome", intervention, "null"),
            _branch("measurement", "measurement-bias", "measurement creates the apparent outcome", intervention, "negative")]


def _separate_pairs() -> tuple[list[dict[str, Any]], ...]:
    rows = _three_branch_plan("separate-intervention")
    return ([rows[0], rows[1]], [rows[0], rows[2]], [rows[1], rows[2]])


def _same_prediction_pair() -> list[dict[str, Any]]:
    return [_branch("mechanism", "shared-mechanism", "same declared mechanism under different prose", "fixed intervention", "positive"),
            _branch("alternative", "separate-title", "different title with same prediction", "fixed intervention", "positive")]


def _reject_non_discriminating(registry: PredictionRegistry, task: PublicTask, captured: list[FrozenRecord], callback, events: list[dict[str, Any]]) -> FrozenRecord:
    """Exercise M4's actual rejection of a plan whose predictions are identical."""
    try:
        freeze_shared_experiment(registry, _question(task), _same_prediction_pair(), budget_units=2)
    except ContractError as exc:
        events.append({"event": "non_discriminating_plan_rejected", "reason": str(exc), "fixture_only": True})
        payload = FrozenRecord.from_dict({"schema": "prediction-scenario-rejected-plan-v1", "fixture_only": True,
            "task": task.data(), "m4_decision": "rejected", "rejection_reason": str(exc),
            "plan_request": {"question": _question(task), "branches": _same_prediction_pair(), "budget_units": 2},
            "observation_id": "fixture-same-prediction-measurement"})
        captured.append(payload)
        return payload
    raise ContractError("fixture non-discriminating plan was unexpectedly admitted")


def _negative_control_pair() -> list[dict[str, Any]]:
    return [_branch("mechanism", "organization-effect", "intervention changes the outcome", "frozen intervention", "positive"),
            _branch("measurement", "measurement-bias", "negative control predicts no outcome change", "frozen intervention", "null")]


def _opposite_prediction_pair() -> list[dict[str, Any]]:
    return [_branch("mechanism", "shared-mechanism", "same mechanism predicts increase", "frozen intervention", "positive"),
            _branch("alternative", "shared-mechanism-alt", "same mechanism predicts decrease", "frozen intervention", "negative")]


def _branch(identifier: str, key: str, mechanism: str, intervention: str, direction: str, *, discriminator: str = "frozen-intervention") -> dict[str, Any]:
    prediction: dict[str, Any] = {"prediction_id": identifier + "-prediction", "discriminator_id": discriminator,
        "observable": "public fixture outcome", "direction": direction, "value_range": None,
        "failure_condition": "fixture observation differs"}
    return {"hypothesis_id": identifier, "mechanism_key": key, "mechanism": mechanism, "intervention": intervention,
            "elimination_condition": "declared prediction fails", "predictions": [prediction]}


def _feasibility(task: PublicTask, frozen_plan: FrozenRecord, discriminating: str, measurement_id: str):
    exploration = ExplorationPlan("fixture-feasibility", task.identity, frozen_plan,
        ResourceClosure("fixture-public-data", "fixture-artifact", "fixture-negative-control", 1, 1))
    return assess_feasibility(exploration, {"data": FeasibilityObservation("data", "passed", "fixture-data"),
        "minimal_run": FeasibilityObservation("minimal_run", "passed", "fixture-zero-exit"),
        "discriminating_measurement": FeasibilityObservation("discriminating_measurement", discriminating, measurement_id)})


def _dedup_proposals(variant: str) -> list[dict[str, str]]:
    if variant == "same_mechanism":
        return [{"proposal_id": "a", "title": "First wording", "mechanism_key": "shared", "prediction_signature": "d:positive"},
                {"proposal_id": "b", "title": "Different wording", "mechanism_key": "shared", "prediction_signature": "d:positive"}]
    if variant == "opposite_prediction":
        return [{"proposal_id": "a", "title": "Nearly same wording", "mechanism_key": "shared", "prediction_signature": "d:positive"},
                {"proposal_id": "b", "title": "Nearly same wording revised", "mechanism_key": "shared", "prediction_signature": "d:negative"}]
    return [{"proposal_id": "a", "title": "Repeated title", "mechanism_key": "one", "prediction_signature": "d:positive"},
            {"proposal_id": "b", "title": "Repeated title", "mechanism_key": "two", "prediction_signature": "d:null"}]


def _diagnostics() -> tuple[FrozenRecord, ...]:
    return (FrozenRecord.from_dict({"diagnostic_id": "broad", "subjective_score": 9, "uncertainty_reduction": 1, "cost": 5}),
            FrozenRecord.from_dict({"diagnostic_id": "focused", "subjective_score": 6, "uncertainty_reduction": 4, "cost": 1}))


def _exploration_plan(task: PublicTask) -> ExplorationPlan:
    return ExplorationPlan("fixture-claimed-item", task.identity, FrozenRecord.from_dict({"task": task.content_hash, "fixture_only": True}),
        ResourceClosure("fixture-public-data", "fixture-artifact", "fixture-negative-control", 1, 1))


def _response_record(value: Any) -> FrozenRecord:
    if isinstance(value, FrozenRecord):
        return value
    if value is None or isinstance(value, Mapping):
        return FrozenRecord.from_dict({"schema": "prediction-scenario-callback-response-v1", "response": value})
    raise ContractError("plan callback response must be a frozen record, mapping, or None")


def _intervention(variant: str) -> str:
    return {"mechanism": "organization-intervention", "computation": "compute-matched-intervention",
            "measurement": "blinded-measurement-intervention"}[variant]


def _question(task: PublicTask) -> str:
    payload = task.payload.data()
    return str(payload.get("research_question", payload.get("question", task.identity.task_id)))


def _validate(experiment_id: str, variant: str) -> None:
    if experiment_id not in _VARIANTS or variant not in _VARIANTS[experiment_id]:
        raise ContractError("prediction scenario variant is not registered")
