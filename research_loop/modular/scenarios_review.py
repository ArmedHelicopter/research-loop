"""Fixture-only Q4 review scenarios over the real M5 sealed-review port.

This module is deliberately a wiring test, not an experiment runner.  It takes
only a prepared public task and controls frozen before any review response.  It
does not open labels, scorer data, network clients, or validation feedback.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from research_loop.modular.contracts import FrozenRecord, PublicTask, required_text
from research_loop.modular.modules.predictions import PredictionRegistry, freeze_shared_experiment
from research_loop.modular.modules.review import ReviewEngine
from research_loop.ontology import ContractError


_VARIANTS = {
    "Q4.1": frozenset(("single", "independent_samples", "roles")),
    "Q4.2": frozenset(("mechanism", "alternative", "measurement", "experiment", "generic")),
    "Q4.3": frozenset(("sealed_then_exchange", "sequential")),
    "Q4.4": frozenset(("none_valid", "defective")),
    "Q4.5": frozenset(("right_to_wrong", "wrong_to_right", "heterogeneous")),
}


class Q4ReviewMaterial:
    """Frozen public material for a production Q4 review intervention."""
    def __init__(self, record: FrozenRecord, *, task_identity: Mapping[str, Any]) -> None:
        if not isinstance(record, FrozenRecord):
            raise ContractError("Q4 requires frozen review material")
        body = record.data()
        required = {"schema", "identity", "public_evidence", "counterexample_material", "initial_answer_material", "summary_material"}
        if set(body) != required or body["schema"] != "q4-review-material-v1" or body["identity"] != task_identity:
            raise ContractError("Q4 review material has unexpected fields or task identity")
        for field in ("public_evidence", "counterexample_material", "initial_answer_material", "summary_material"):
            if not isinstance(body[field], Mapping) or not body[field]:
                raise ContractError(f"Q4 review material requires concrete {field}")
        self.record = record

    def data(self) -> dict[str, Any]:
        return self.record.data()


class Q4ReviewMaterialBundle:
    """One task's public evidence plus every frozen Q4 variant material."""
    def __init__(self, record: FrozenRecord, *, task_identity: Mapping[str, Any]) -> None:
        body = record.data()
        if set(body) != {"schema", "identity", "public_evidence", "materials"} or body["schema"] != "q4-review-material-bundle-v1" or body["identity"] != task_identity:
            raise ContractError("Q4 review material bundle has unexpected fields or task identity")
        if not isinstance(body["public_evidence"], Mapping) or not body["public_evidence"] or not isinstance(body["materials"], Mapping):
            raise ContractError("Q4 review material bundle requires public evidence and materials")
        if set(body["materials"]) != set(_VARIANTS):
            raise ContractError("Q4 review material bundle must cover every Q4 intervention")
        for experiment_id, variants in _VARIANTS.items():
            rows = body["materials"].get(experiment_id)
            if not isinstance(rows, Mapping) or set(rows) != set(variants):
                raise ContractError("Q4 review material bundle lacks a registered variant")
            for item in rows.values():
                if not isinstance(item, Mapping) or set(item) != {"counterexample_material", "initial_answer_material", "summary_material"} or any(not isinstance(value, Mapping) or not value for value in item.values()):
                    raise ContractError("Q4 bundle variant material is incomplete")
        self.record = record

    def selected(self, experiment_id: str, variant: str) -> Q4ReviewMaterial:
        item = self.record.data()["materials"][experiment_id][variant]
        return Q4ReviewMaterial(FrozenRecord.from_dict({"schema": "q4-review-material-v1", "identity": self.record.data()["identity"],
            "public_evidence": self.record.data()["public_evidence"], **item}), task_identity=self.record.data()["identity"])


def q4_injection(experiment_id: str, variant: str, *, task: FrozenRecord, evidence: FrozenRecord) -> Mapping[str, Any]:
    """Bind production Q4 drivers to caller-supplied material, never fixture truth."""
    _validate(experiment_id, variant)
    task_body = task.data()
    identity = task_body.get("identity") if isinstance(task_body, Mapping) else None
    if not isinstance(identity, Mapping):
        raise ContractError("Q4 task must carry a typed public identity")
    if evidence.data().get("schema") == "q4-review-material-bundle-v1":
        bundle = Q4ReviewMaterialBundle(evidence, task_identity=dict(identity))
        material = bundle.selected(experiment_id, variant)
        return {"fixture_only": True, "fixture_notice": "synthetic public material; not a benchmark effect",
                "auxiliary": {"review_scenario_variant": variant, "requires_public_task": True,
                              "requires_frozen_material": True}, "q4_review_material": material.data(),
                "q4_review_material_digest": material.record.content_hash,
                "q4_review_material_bundle_digest": bundle.record.content_hash}
    if evidence.data().get("schema") != "q4-review-material-v1":
        # Planning may retain a public evidence digest shared with another
        # intervention.  It is not an executable Q4 material: the production
        # driver rejects it before its first model request.
        return {"fixture_only": True, "fixture_notice": "Q4 material absent; production execution is closed",
                "auxiliary": {"review_scenario_variant": variant, "requires_public_task": True,
                              "requires_frozen_material": True}, "q4_review_material_missing": True}
    material = Q4ReviewMaterial(evidence, task_identity=dict(identity))
    return {"fixture_only": True, "fixture_notice": "synthetic public material; not a benchmark effect",
            "auxiliary": {"review_scenario_variant": variant, "requires_public_task": True,
                          "requires_frozen_material": True},
            "q4_review_material": material.data(), "q4_review_material_digest": material.record.content_hash}


@dataclass(frozen=True)
class ReviewScenarioResult:
    experiment_id: str
    variant: str
    callback_payloads: tuple[FrozenRecord, ...]
    callback_responses: tuple[FrozenRecord, ...]
    mechanism_trace: FrozenRecord
    record: FrozenRecord


def review_injection(experiment_id: str, variant: str) -> Mapping[str, Any]:
    """Closed controller metadata; the shared registry wires this separately."""
    _validate(experiment_id, variant)
    return {"fixture_only": True, "fixture_notice": "engineering fixture; not a benchmark measurement",
            "auxiliary": {"review_scenario_variant": variant, "requires_public_task": True,
                          "requires_frozen_controls": True, "controls_predeclared": True}}


def run_review_scenario(
    experiment_id: str,
    variant: str,
    *,
    task: PublicTask,
    frozen_controls: FrozenRecord,
    review_callback: Callable[[FrozenRecord], Mapping[str, Any]] | None = None,
    review_log_path: Path | None = None,
    artifact_root: Path | None = None,
    reviewer_identities: Mapping[str, Mapping[str, Any]] | None = None,
) -> ReviewScenarioResult:
    """Exercise one Q4 fixture with sealed submissions and retained responses.

    ``review_callback`` receives the exact frozen payload that is submitted to
    M5.  Its response is retained and scored only by the separate local fixture
    oracle below; callback text never chooses an outcome.  ``heterogeneous``
    requires caller-supplied, attributable provider/model metadata so the
    fixture never invents a provider identity.
    """
    _validate(experiment_id, variant)
    controls = _controls(task, frozen_controls)
    roles, costs, visibility, case = _design(experiment_id, variant)
    call_plan = _freeze_call_plan(experiment_id, variant, roles, costs)
    identities = _identities(roles, reviewer_identities, heterogeneous=(experiment_id == "Q4.5" and variant == "heterogeneous"))
    engine = ReviewEngine(task.identity, storage_path=review_log_path)
    session = engine.open(task_binding=task.content_hash, evidence_snapshot=controls["evidence_digest"],
                          roles=roles, budget_units=sum(item["fixture_units"] for item in call_plan))
    payloads: list[FrozenRecord] = []
    responses: list[FrozenRecord] = []
    prediction_candidates: list[Mapping[str, Any]] = []
    submissions = []
    events: list[dict[str, Any]] = [{"event": "fixture_start", "fixture_only": True,
        "task_digest": task.content_hash, "evidence_digest": controls["evidence_digest"],
        "budget_digest": controls["budget_digest"], "controls_predeclared": True,
        "callback_plan": call_plan, "planned_call_count": len(call_plan),
        "planned_fixture_units": sum(item["fixture_units"] for item in call_plan),
        "real_token_matching_claimed": False}]

    for index, role in enumerate(roles):
        prior = submissions[0].data() if visibility == "sequential" and index else None
        allocation = _reserve(events, call_plan, "initial", role["role_id"])
        payload = _payload(task, controls, session.review_id, role, identities[role["role_id"]],
                           invocation="initial", prior_visible_submission=prior, case=case)
        response, candidate = _call(review_callback, payload, case)
        if candidate is not None: prediction_candidates.append(candidate)
        submission = engine.submit(session.review_id, role_id=role["role_id"],
                                   reviewer_id=identities[role["role_id"]]["reviewer_id"],
                                   response=response.data(), cost_units=allocation["fixture_units"])
        payloads.append(payload); responses.append(response); submissions.append(submission)
    revealed = engine.reveal(session.review_id)
    events.append({"event": "sealed_barrier_revealed", "review_id": session.review_id,
                   "submission_hashes": [item.before_hash for item in revealed], "visibility": visibility})

    # Q4.3 and Q4.5 require actual post-reveal revisions, preserving both forms.
    revisions = []
    if experiment_id in {"Q4.3", "Q4.5"}:
        for role in roles:
            role_id = role["role_id"]
            _reserve(events, call_plan, "revision", role_id)
            payload = _payload(task, controls, session.review_id, role, identities[role_id], invocation="revision",
                               prior_visible_submission=[item.data() for item in revealed], case=case)
            response, _ = _call(review_callback, payload, case)
            revision = engine.revise_after_reveal(session.review_id, role_id=role_id,
                                                  reviewer_id=identities[role_id]["reviewer_id"], response=response.data())
            payloads.append(payload); responses.append(response); revisions.append(revision)
        events.append({"event": "post_reveal_revisions", "before_hashes": [item.before_hash for item in revealed],
                       "after_hashes": [item.after_hash for item in revisions]})

    score_changes, metrics = _fixture_oracle(case, revealed, revisions)
    receipt = engine.record_score(session.review_id, changes=score_changes,
                                  scorer_receipt={"trusted_scorer": "fixture-oracle-v1", "verified": True})
    events.append({"event": "independent_fixture_oracle", "score_receipt": receipt.data(), "metrics": metrics,
                   "oracle_not_exposed_to_callback": True})
    m4 = _freeze_callback_predictions(task, experiment_id, prediction_candidates, call_plan)
    events.append({"event": "callback_prediction_extraction", **m4})
    record = FrozenRecord.from_dict({"fixture_only": True, "experiment_id": experiment_id, "variant": variant,
        "task_digest": task.content_hash, "controls_digest": frozen_controls.content_hash,
        "review_id": session.review_id, "budget": {"fixture_units": sum(item["fixture_units"] for item in call_plan),
        "initial_submission_units": sum(item["fixture_units"] for item in call_plan if item["phase"] == "initial"),
        "revision_callback_units": sum(item["fixture_units"] for item in call_plan if item["phase"] == "revision"),
        "initial_calls": len(roles), "revision_calls": len(revisions), "real_token_matching_claimed": False},
        "callback_plan": call_plan, "callback_reservations": [item for item in events if item["event"] == "callback_reserved"],
        "module_switches": {"M5": "on", "M4": m4["status"]}, "m4": m4,
        "callback_payload_digests": [item.content_hash for item in payloads],
        "callback_response_digests": [item.content_hash for item in responses], "metrics": metrics,
        "limitation": "fixture-only mechanism trace; no benchmark efficacy, provider independence, or scientific validity claim"})
    result = ReviewScenarioResult(experiment_id, variant, tuple(payloads), tuple(responses),
                                  FrozenRecord.from_dict({"events": events}), record)
    if artifact_root is not None:
        from research_loop.modular.review_scenario_artifacts import write_review_artifacts
        write_review_artifacts(artifact_root, task=task, controls=frozen_controls, result=result)
    return result


def _controls(task: PublicTask, frozen: FrozenRecord) -> dict[str, Any]:
    body = frozen.data()
    if set(body) != {"task_digest", "evidence_digest", "budget_digest", "fixture_only"} or body["task_digest"] != task.content_hash or body["fixture_only"] is not True:
        raise ContractError("review scenario requires matching closed fixture controls")
    required_text(body["evidence_digest"], "evidence digest"); required_text(body["budget_digest"], "budget digest")
    return body


def _design(experiment_id: str, variant: str):
    concrete = {
        "mechanism": "What causal mechanism could produce the observed pattern, and what observation would falsify it?",
        "alternative": "State a distinct alternative explanation and the observable that separates it from the stated mechanism.",
        "measurement": "Identify a plausible measurement failure and a public check that would distinguish it from the stated mechanism.",
        "experiment": "Propose one discriminating experiment with a predeclared observable and failure condition.",
    }
    if experiment_id == "Q4.1":
        if variant == "single": return ([{"role_id": "assessment", "question": concrete["mechanism"]}], {"assessment": 4}, "sealed", _case("neutral"))
        if variant == "independent_samples":
            roles = [{"role_id": f"sample_{n}", "question": concrete["mechanism"]} for n in range(1, 5)]
            return roles, {item["role_id"]: 1 for item in roles}, "sealed", _case("neutral")
        roles = [{"role_id": name, "question": concrete[name]} for name in ("mechanism", "alternative", "measurement", "experiment")]
        return roles, {item["role_id"]: 1 for item in roles}, "sealed", _case("neutral")
    if experiment_id == "Q4.2":
        question = concrete.get(variant, "Please oppose this conclusion.")
        return ([{"role_id": "assigned_review", "question": question}], {"assigned_review": 1}, "sealed", _case("neutral"))
    if experiment_id == "Q4.3":
        roles = [{"role_id": "mechanism", "question": concrete["mechanism"]}, {"role_id": "measurement", "question": concrete["measurement"]}]
        return roles, {"mechanism": 1, "measurement": 1}, "sealed" if variant == "sealed_then_exchange" else "sequential", _case("defect")
    if experiment_id == "Q4.4":
        return ([{"role_id": "counterexample", "question": "Assess the public observation for a concrete counterexample; report none when none is supported."}], {"counterexample": 1}, "sealed", _case("qualified" if variant == "none_valid" else "defect"))
    if variant == "heterogeneous":
        roles = [{"role_id": "reviewer_one", "question": "Assess the public observation and identify a concrete concern only when supported."},
                 {"role_id": "reviewer_two", "question": "Independently assess the public observation and identify a concrete concern only when supported."}]
        return roles, {"reviewer_one": 1, "reviewer_two": 1}, "sealed", _case("defect")
    roles = [{"role_id": "reviewer_one", "question": "Assess the public observation and identify a concrete concern only when supported."}]
    return roles, {"reviewer_one": 1}, "sealed", _case("qualified" if variant == "right_to_wrong" else "defect")


def _case(kind: str) -> dict[str, Any]:
    # This material is reviewer-visible.  The adjudication mapping is kept only
    # in _fixture_oracle, and neither IDs nor prompts encode its classification.
    if kind == "defect":
        return {"observations": [{"evidence_id": "fixture-observation-a", "statement": "allocation was reported before the outcome measurement"},
                                  {"evidence_id": "fixture-observation-b", "statement": "the recorded allocation table omits one enrolled group"}]}
    return {"observations": [{"evidence_id": "fixture-observation-a", "statement": "allocation and outcome tables cover the same enrolled groups"}]}


def _identities(roles, supplied, *, heterogeneous: bool) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for index, role in enumerate(roles, 1):
        role_id = role["role_id"]
        raw = dict((supplied or {}).get(role_id, {}))
        if not raw:
            if heterogeneous:
                raise ContractError("heterogeneous review requires explicit reviewer provenance for every role")
            raw = {"reviewer_id": f"fixture-reviewer-{index}", "model_id": "fixture-synthetic-model",
                   "provider": None, "provenance": "synthetic engineering callback; no provider assertion"}
        if set(raw) != {"reviewer_id", "model_id", "provider", "provenance"}:
            raise ContractError("reviewer identity requires reviewer_id, model_id, provider, provenance")
        for key in ("reviewer_id", "model_id", "provenance"): required_text(raw[key], key)
        if raw["provider"] is not None: required_text(raw["provider"], "provider")
        if heterogeneous and raw["provider"] is None: raise ContractError("heterogeneous provider identity must be explicit")
        result[role_id] = raw
    if len({item["reviewer_id"] for item in result.values()}) != len(result): raise ContractError("reviewer identities must be unique")
    if heterogeneous and len({(item["provider"], item["model_id"]) for item in result.values()}) < 2:
        raise ContractError("heterogeneous review requires distinct provider/model identities")
    return result


def _payload(task, controls, review_id, role, identity, *, invocation, prior_visible_submission, case) -> FrozenRecord:
    return FrozenRecord.from_dict({"schema": "review-scenario-input-v1", "fixture_only": True, "task": task.data(),
        "frozen_controls": controls, "review_id": review_id, "role": role, "reviewer_identity": identity,
        "invocation": invocation, "public_case": case, "prior_visible_submission": prior_visible_submission,
        "visibility_notice": "independent sealed submission" if prior_visible_submission is None else "prior submission was intentionally visible"})


def _freeze_call_plan(experiment_id: str, variant: str, roles, costs) -> list[dict[str, Any]]:
    """Declare every callback and fixture unit before any callback runs."""
    needs_revision = experiment_id in {"Q4.3", "Q4.5"}
    plan = []
    for role in roles:
        units = costs[role["role_id"]]
        # Q4.5 comparisons use a four-unit allocation despite one versus two
        # reviewers.  This is declared accounting, never a token-cost claim.
        if experiment_id == "Q4.5" and variant != "heterogeneous": units = 2
        plan.append({"phase": "initial", "role_id": role["role_id"], "fixture_units": units})
    if needs_revision:
        for role in roles:
            units = costs[role["role_id"]]
            if experiment_id == "Q4.5" and variant != "heterogeneous": units = 2
            plan.append({"phase": "revision", "role_id": role["role_id"], "fixture_units": units})
    return plan


def _reserve(events: list[dict[str, Any]], plan: list[dict[str, Any]], phase: str, role_id: str) -> dict[str, Any]:
    matches = [item for item in plan if item["phase"] == phase and item["role_id"] == role_id]
    if len(matches) != 1: raise ContractError("callback is absent from the frozen allocation plan")
    allocation = matches[0]
    if any(item.get("phase") == phase and item.get("role_id") == role_id for item in events if item["event"] == "callback_reserved"):
        raise ContractError("callback allocation was already reserved")
    events.append({"event": "callback_reserved", **allocation, "reserved_before_callback": True})
    return allocation


def _call(callback, payload, case) -> tuple[FrozenRecord, Mapping[str, Any] | None]:
    value = callback(payload) if callback else {"assessment": "unknown", "evidence_refs": [case["observations"][0]["evidence_id"]], "counterexamples": [], "uncertainty": "fixture default; no model invoked"}
    if isinstance(value, FrozenRecord): value = value.data()
    if not isinstance(value, Mapping): raise ContractError("review callback must return a response mapping")
    candidate = None
    if set(value) == {"review", "prediction_candidate"}:
        candidate = value["prediction_candidate"]
        value = value["review"]
        if candidate is not None and not isinstance(candidate, Mapping):
            raise ContractError("prediction candidate must be a mapping or null")
    return FrozenRecord.from_dict(dict(value)), dict(candidate) if candidate is not None else None


def _freeze_callback_predictions(task: PublicTask, experiment_id: str,
                                 candidates: list[Mapping[str, Any]], call_plan: list[dict[str, Any]]) -> dict[str, Any]:
    """Use only callback-provided M4 branches; never fill in missing structure."""
    if experiment_id != "Q4.1":
        return {"status": "off", "reason": "Q4.1 is the only M4/M5 review scenario"}
    if len(candidates) < 2:
        return {"status": "rejected", "reason": "fewer than two callback prediction candidates", "candidate_count": len(candidates)}
    try:
        plan = freeze_shared_experiment(PredictionRegistry(task.identity), _question(task), candidates,
                                        budget_units=sum(item["fixture_units"] for item in call_plan))
    except ContractError as exc:
        return {"status": "rejected", "reason": str(exc), "candidate_count": len(candidates)}
    return {"status": "on", "plan_id": plan.plan_id, "plan_digest": plan.payload.content_hash,
            "candidate_count": len(candidates), "budget_units": plan.budget_units,
            "outcome": "unknown", "limitation": "fixture verifies declared prediction structure only"}


def _question(task: PublicTask) -> str:
    payload = task.payload.data()
    return str(payload.get("research_question", payload.get("question", task.identity.task_id)))


def _fixture_oracle(case, submissions, revisions):
    """Score actual responses against an isolated fixture oracle, never a forced callback result."""
    target = "fixture-observation-b" if len(case["observations"]) == 2 else "fixture-observation-a"
    def classify(response):
        body = response.data()
        if len(case["observations"]) == 1:
            return "correct" if body["assessment"] == "accept" else "incorrect" if body["assessment"] == "concern" else "unknown"
        return "correct" if body["assessment"] == "concern" and target in body["evidence_refs"] else "incorrect" if body["assessment"] == "accept" else "unknown"
    revised = {item.role_id: item for item in revisions}
    changes = []
    counts = {"right_to_wrong": 0, "wrong_to_right": 0, "unchanged": 0, "denominator": len(submissions)}
    for item in submissions:
        before = classify(item.response); after = classify(revised[item.role_id].response) if item.role_id in revised else before
        changes.append({"role_id": item.role_id, "before": before, "after": after})
        if (before, after) == ("correct", "incorrect"): counts["right_to_wrong"] += 1
        elif (before, after) == ("incorrect", "correct"): counts["wrong_to_right"] += 1
        else: counts["unchanged"] += 1
    counts["net_correction"] = counts["wrong_to_right"] - counts["right_to_wrong"]
    return changes, counts


def _validate(experiment_id: str, variant: str) -> None:
    if experiment_id not in _VARIANTS or variant not in _VARIANTS[experiment_id]:
        raise ContractError("review scenario variant is not registered")
