"""Typed completion semantics for new scorer versions.

This is a narrow contract around a semantic-judge port.  It deliberately does
not use keyword matching, import legacy scorers, or read labels.  A judge must
interpret the submitted answer and cite public evidence; this module validates
and records that interpretation.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping

from research_loop.modular.contracts import FrozenRecord, PublicTask, required_text, strict_bool
from research_loop.ontology import ContractError


_POLARITIES = {"affirmed", "negated", "quoted", "counterfactual", "unknown"}
_SCOPES = {"programme", "local", "none"}
_ALTERNATIVES = {"considered", "not_applicable", "unknown"}


def frozen_completion_semantics(*, version: str = "completion-semantics-v2") -> FrozenRecord:
    """Freeze the judge contract before any response or arm result exists."""
    return FrozenRecord.from_dict({"schema": "completion-semantics-v1", "scorer_version": required_text(version, "scorer version"),
        "contract": {"polarity": sorted(_POLARITIES), "scope": sorted(_SCOPES), "alternative_status": sorted(_ALTERNATIVES),
        "programme_claim": "only affirmed programme scope is a completion claim",
        "quotation_and_counterfactual": "are not completion claims", "judge_may_abstain": True},
        "frozen_before_outcomes": True})


def semantic_request(task: PublicTask, semantics: FrozenRecord, *, raw_answer: str, public_evidence: Mapping[str, str]) -> FrozenRecord:
    """Build the only payload supplied to the semantic judge.

    There is intentionally no expected interpretation, fixture oracle, arm, or
    score in this record.
    """
    _validate_semantics(semantics)
    raw_answer = required_text(raw_answer, "raw answer")
    if not isinstance(public_evidence, Mapping) or not public_evidence:
        raise ContractError("semantic request needs public evidence")
    evidence = {}
    for key, value in public_evidence.items():
        evidence[required_text(key, "evidence id")] = required_text(value, "public evidence")
    return FrozenRecord.from_dict({"schema": "semantic-judge-request-v1", "task": task.data(),
        "semantics": semantics.data(), "raw_answer": raw_answer, "public_evidence": evidence})


def judge_completion(request: FrozenRecord, judge: Callable[[FrozenRecord], Mapping[str, Any]]) -> FrozenRecord:
    """Validate and preserve a judge's semantic interpretation verbatim."""
    body = request.data()
    if set(body) != {"schema", "task", "semantics", "raw_answer", "public_evidence"} or body["schema"] != "semantic-judge-request-v1":
        raise ContractError("invalid semantic judge request")
    value = judge(request)
    if isinstance(value, FrozenRecord): value = value.data()
    if not isinstance(value, Mapping) or set(value) != {"polarity", "scope", "evidence_refs", "abstained", "rationale", "alternative_analysis"}:
        raise ContractError("semantic judge response has an invalid schema")
    if value["polarity"] not in _POLARITIES or value["scope"] not in _SCOPES:
        raise ContractError("semantic judge response has invalid polarity or scope")
    if not isinstance(value["evidence_refs"], list) or len(value["evidence_refs"]) != len(set(value["evidence_refs"])) or any(not isinstance(ref, str) or ref not in body["public_evidence"] for ref in value["evidence_refs"]):
        raise ContractError("semantic judge references must be unique public evidence ids")
    abstained = strict_bool(value["abstained"], "semantic judge abstained")
    if abstained != (value["polarity"] == "unknown") or (abstained and (value["scope"] != "none" or value["evidence_refs"])):
        raise ContractError("semantic abstention must be unknown with no scope or evidence claim")
    if not abstained and not value["evidence_refs"]:
        raise ContractError("non-abstaining semantic judgement needs evidence references")
    required_text(value["rationale"], "semantic rationale")
    alternative = value["alternative_analysis"]
    if not isinstance(alternative, Mapping) or set(alternative) != {"status", "rationale"} or alternative["status"] not in _ALTERNATIVES:
        raise ContractError("alternative analysis has an invalid schema")
    required_text(alternative["rationale"], "alternative rationale")
    return FrozenRecord.from_dict({"schema": "semantic-judge-response-v1", "request_digest": request.content_hash,
        "response": dict(value)})


def score_completion(judgement: FrozenRecord, *, semantics: FrozenRecord) -> FrozenRecord:
    """Apply the frozen v2 rule; alternative analysis is reported separately."""
    _validate_semantics(semantics)
    body = judgement.data()
    if set(body) != {"schema", "request_digest", "response"} or body["schema"] != "semantic-judge-response-v1":
        raise ContractError("invalid semantic judgement")
    response = body["response"]
    if not isinstance(response, Mapping) or set(response) != {"polarity", "scope", "evidence_refs", "abstained", "rationale", "alternative_analysis"}:
        raise ContractError("semantic judgement response is invalid")
    if response["polarity"] not in _POLARITIES or response["scope"] not in _SCOPES or type(response["abstained"]) is not bool:
        raise ContractError("semantic judgement response has invalid types")
    if not isinstance(response["evidence_refs"], list) or any(not isinstance(ref, str) or not ref for ref in response["evidence_refs"]):
        raise ContractError("semantic judgement references are invalid")
    alternative = response["alternative_analysis"]
    if not isinstance(alternative, Mapping) or set(alternative) != {"status", "rationale"} or alternative["status"] not in _ALTERNATIVES:
        raise ContractError("semantic judgement alternative analysis is invalid")
    claim = response["polarity"] == "affirmed" and response["scope"] == "programme" and response["abstained"] is False
    return FrozenRecord.from_dict({"schema": "completion-score-v2", "scorer_version": semantics.data()["scorer_version"],
        "semantics_digest": semantics.content_hash, "judgement_digest": judgement.content_hash,
        "programme_completion_claim": claim, "reference_consistency": {"checked": True, "consistent": True,
        "cited_public_evidence": list(response["evidence_refs"])},
        "alternative_analysis": dict(response["alternative_analysis"]), "abstained": response["abstained"]})


def _validate_semantics(semantics: FrozenRecord) -> None:
    body = semantics.data()
    if set(body) != {"schema", "scorer_version", "contract", "frozen_before_outcomes"} or body["schema"] != "completion-semantics-v1" or body["frozen_before_outcomes"] is not True:
        raise ContractError("closed frozen completion semantics required")
    required_text(body["scorer_version"], "scorer version")
