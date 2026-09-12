"""Fixture-only Q2.2/Q6.4 semantic-scoring and scorer-revision traces."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from research_loop.modular.contracts import FrozenRecord, PublicTask, required_text
from research_loop.modular.semantics import (alternative_request, assess_alternatives, frozen_completion_semantics,
    judge_completion, score_completion, semantic_request)
from research_loop.ontology import ContractError


_VARIANTS = {"Q2.2": frozenset(("affirm", "negate", "quote", "counterfactual", "local")),
             "Q6.4": frozenset(("negation", "quotation", "alternative"))}


@dataclass(frozen=True)
class ScoringScenarioResult:
    experiment_id: str
    variant: str
    judge_requests: tuple[FrozenRecord, ...]
    judgements: tuple[FrozenRecord, ...]
    alternative_requests: tuple[FrozenRecord, ...]
    alternative_assessments: tuple[FrozenRecord, ...]
    scores: tuple[FrozenRecord, ...]
    record: FrozenRecord


def scoring_injection(experiment_id: str, variant: str) -> Mapping[str, Any]:
    _validate(experiment_id, variant)
    return {"fixture_only": True, "fixture_notice": "semantic scorer engineering fixture; not a calibration result",
            "auxiliary": {"scoring_scenario_variant": variant, "requires_public_task": True,
                          "requires_frozen_semantics": True, "preserves_legacy_results": True}}


def run_scoring_scenario(experiment_id: str, variant: str, *, task: PublicTask, frozen_controls: FrozenRecord,
                         semantic_judge: Callable[[FrozenRecord], Mapping[str, Any]] | None = None,
                         alternative_judge: Callable[[FrozenRecord], Mapping[str, Any]] | None = None) -> ScoringScenarioResult:
    """Run a closed semantic judge chain for every declared Q2.2/Q6.4 variant.

    Q6.4 creates only a new scorer-version record.  It retains a prior-result
    digest as diagnostic provenance and never opens or rewrites an old result.
    The two fixture arms use the same v2 semantics digest before either answer
    is judged.
    """
    _validate(experiment_id, variant)
    controls = _controls(task, frozen_controls)
    semantics = frozen_completion_semantics()
    cases = _cases(experiment_id, variant)
    requests, judgements, alternative_requests, alternative_assessments, scores = [], [], [], [], []
    for case in cases:
        request = semantic_request(task, semantics, raw_answer=case["raw_answer"], public_evidence=case["public_evidence"])
        judgement = judge_completion(request, semantic_judge or _abstaining_fixture_judge)
        alternative = alternative_request(request, judgement)
        assessment = assess_alternatives(alternative, alternative_judge or _unknown_alternative_judge)
        score = score_completion(judgement, semantics=semantics, request=request, alternative_assessment=assessment)
        requests.append(request); judgements.append(judgement); alternative_requests.append(alternative); alternative_assessments.append(assessment); scores.append(score)
    arms = [case["arm"] for case in cases]
    diagnostic = None
    if experiment_id == "Q6.4":
        diagnostic = {"prior_scorer_version": "legacy-unmodified", "prior_result_digest": "synthetic-prior-result-not-opened",
                      "purpose": "post-revision comparison is diagnostic only; not a validation measurement"}
    record = FrozenRecord.from_dict({"fixture_only": True, "experiment_id": experiment_id, "variant": variant,
        "task_digest": task.content_hash, "controls_digest": frozen_controls.content_hash, "semantics": semantics.data(),
        "semantics_digest": semantics.content_hash, "arms": arms, "arm_scorer_digests": {case["arm"]: semantics.content_hash for case in cases},
        "judge_request_digests": [item.content_hash for item in requests], "judgement_digests": [item.content_hash for item in judgements],
        "alternative_request_digests": [item.content_hash for item in alternative_requests], "alternative_assessment_digests": [item.content_hash for item in alternative_assessments],
        "score_digests": [item.content_hash for item in scores], "legacy_diagnostic": diagnostic,
        "denominator": {"declared_cases": len(cases), "judge_calls": len(requests), "scored_cases": len(scores)},
        "limitation": "controller fixture only; no independent labels, scorer calibration, historical-result rescore, or efficacy measurement"})
    return ScoringScenarioResult(experiment_id, variant, tuple(requests), tuple(judgements), tuple(alternative_requests), tuple(alternative_assessments), tuple(scores), record)


def _controls(task: PublicTask, frozen: FrozenRecord) -> dict[str, Any]:
    body = frozen.data()
    if set(body) != {"task_digest", "budget_digest", "fixture_only"} or body["task_digest"] != task.content_hash or body["fixture_only"] is not True:
        raise ContractError("scoring scenario requires matching closed fixture controls")
    required_text(body["budget_digest"], "budget digest")
    return body


def _cases(experiment_id: str, variant: str):
    public_evidence = {"fixture-evidence-a": "The public record states the programme scope and current observation."}
    if experiment_id == "Q2.2":
        text = {"affirm": "The programme has met its stated endpoint using the cited observation.",
                "negate": "The programme has not met its stated endpoint using the cited observation.",
                "quote": "The report quotes an earlier statement that the programme had met an endpoint.",
                "counterfactual": "If the cited observation had held, the programme would have met its endpoint.",
                "local": "This local analysis step is complete using the cited observation."}[variant]
        return [{"arm": "fixture", "raw_answer": text, "public_evidence": public_evidence}]
    # Different public answer material is submitted to A/B, but v2 and its
    # frozen contract are identical for both arms.
    text = {"negation": "The programme has not met its stated endpoint using the cited observation.",
            "quotation": "The report quotes an earlier statement that the programme had met an endpoint.",
            "alternative": "A reasonable alternative explanation remains under consideration for the cited observation."}[variant]
    return [{"arm": "A", "raw_answer": text, "public_evidence": public_evidence},
            {"arm": "B", "raw_answer": text + " The same public record is supplied to this arm.", "public_evidence": public_evidence}]


def _abstaining_fixture_judge(request: FrozenRecord) -> Mapping[str, Any]:
    return {"polarity": "unknown", "scope": "none", "evidence_refs": [], "abstained": True,
            "rationale": "no semantic judge was injected", "alternative_analysis": {"status": "unknown", "rationale": "no semantic judge was injected", "candidate_specifications": []}}


def _unknown_alternative_judge(request: FrozenRecord) -> Mapping[str, Any]:
    return {"scientific_acceptability": "unknown", "rationale": "no independent alternative judge was injected"}


def _validate(experiment_id: str, variant: str) -> None:
    if experiment_id not in _VARIANTS or variant not in _VARIANTS[experiment_id]:
        raise ContractError("scoring scenario variant is not registered")
