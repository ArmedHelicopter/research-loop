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
_ACCEPTABILITY = {"unknown", "supported", "rejected"}
_CONTRACT = {"polarity": sorted(_POLARITIES), "scope": sorted(_SCOPES), "alternative_status": sorted(_ALTERNATIVES),
             "programme_claim": "only affirmed programme scope is a completion claim",
             "quotation_and_counterfactual": "are not completion claims", "judge_may_abstain": True}


def frozen_completion_semantics(*, version: str = "completion-semantics-v2") -> FrozenRecord:
    """Freeze the judge contract before any response or arm result exists."""
    return FrozenRecord.from_dict({"schema": "completion-semantics-v2", "scorer_version": required_text(version, "scorer version"),
        "contract": _CONTRACT,
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
    _validate_response(value, public_evidence=body["public_evidence"])
    return FrozenRecord.from_dict({"schema": "semantic-judge-response-v1", "request_digest": request.content_hash,
        "semantics_digest": FrozenRecord.from_dict(body["semantics"]).content_hash, "response": dict(value)})


def alternative_request(request: FrozenRecord, judgement: FrozenRecord) -> FrozenRecord:
    """Ask a separate port whether alternatives are scientifically acceptable."""
    body = request.data(); judged = judgement.data()
    if judged.get("request_digest") != request.content_hash: raise ContractError("alternative assessment must bind the exact semantic request")
    return FrozenRecord.from_dict({"schema": "alternative-analysis-request-v1", "task": body["task"], "semantics": body["semantics"],
        "judgement_digest": judgement.content_hash, "candidate_specifications": judged["response"]["alternative_analysis"]["candidate_specifications"],
        "public_evidence": body["public_evidence"]})


def assess_alternatives(request: FrozenRecord, judge: Callable[[FrozenRecord], Mapping[str, Any]]) -> FrozenRecord:
    body = request.data()
    if set(body) != {"schema", "task", "semantics", "judgement_digest", "candidate_specifications", "public_evidence"} or body["schema"] != "alternative-analysis-request-v1":
        raise ContractError("invalid alternative analysis request")
    value = judge(request)
    if isinstance(value, FrozenRecord): value = value.data()
    if not isinstance(value, Mapping) or set(value) != {"scientific_acceptability", "rationale"} or value["scientific_acceptability"] not in _ACCEPTABILITY:
        raise ContractError("alternative assessment has an invalid schema")
    required_text(value["rationale"], "alternative assessment rationale")
    return FrozenRecord.from_dict({"schema": "alternative-analysis-response-v1", "request_digest": request.content_hash, "assessment": dict(value)})


def score_completion(judgement: FrozenRecord, *, semantics: FrozenRecord, request: FrozenRecord,
                     alternative_assessment: FrozenRecord) -> FrozenRecord:
    """Apply the frozen v2 rule; alternative analysis is reported separately."""
    _validate_semantics(semantics)
    body = judgement.data()
    request_body = request.data()
    if set(body) != {"schema", "request_digest", "semantics_digest", "response"} or body["schema"] != "semantic-judge-response-v1" or body["request_digest"] != request.content_hash or body["semantics_digest"] != semantics.content_hash:
        raise ContractError("invalid semantic judgement")
    if request_body.get("semantics") != semantics.data(): raise ContractError("semantic score request rubric mismatch")
    response = body["response"]
    _validate_response(response, public_evidence=request_body["public_evidence"])
    assessed = alternative_assessment.data()
    if set(assessed) != {"schema", "request_digest", "assessment"} or assessed["schema"] != "alternative-analysis-response-v1":
        raise ContractError("invalid alternative assessment")
    expected_alt = alternative_request(request, judgement)
    if assessed["request_digest"] != expected_alt.content_hash: raise ContractError("alternative assessment request binding mismatch")
    if not isinstance(assessed["assessment"], Mapping) or set(assessed["assessment"]) != {"scientific_acceptability", "rationale"} or assessed["assessment"]["scientific_acceptability"] not in _ACCEPTABILITY:
        raise ContractError("invalid alternative assessment")
    claim = response["polarity"] == "affirmed" and response["scope"] == "programme" and response["abstained"] is False
    return FrozenRecord.from_dict({"schema": "completion-score-v2", "scorer_version": semantics.data()["scorer_version"],
        "semantics_digest": semantics.content_hash, "judgement_digest": judgement.content_hash,
        "programme_completion_claim": claim, "reference_contract": {"public_reference_ids_validated": True,
        "cited_public_evidence": list(response["evidence_refs"]), "scientific_reference_consistency": "not_measured"},
        "alternative_analysis": {**dict(response["alternative_analysis"]), "external_assessment": dict(assessed["assessment"])}, "abstained": response["abstained"]})


def _validate_semantics(semantics: FrozenRecord) -> None:
    body = semantics.data()
    if set(body) != {"schema", "scorer_version", "contract", "frozen_before_outcomes"} or body["schema"] != "completion-semantics-v2" or body["contract"] != _CONTRACT or body["frozen_before_outcomes"] is not True:
        raise ContractError("closed frozen completion semantics required")
    required_text(body["scorer_version"], "scorer version")


def _validate_response(value: Mapping[str, Any], *, public_evidence: Mapping[str, str]) -> None:
    if value["polarity"] not in _POLARITIES or value["scope"] not in _SCOPES: raise ContractError("semantic judge response has invalid polarity or scope")
    refs = value["evidence_refs"]
    if not isinstance(refs, list) or len(refs) != len(set(refs)) or any(not isinstance(ref, str) or ref not in public_evidence for ref in refs): raise ContractError("semantic judge references must be unique public evidence ids")
    abstained = strict_bool(value["abstained"], "semantic judge abstained")
    if abstained != (value["polarity"] == "unknown") or (abstained and (value["scope"] != "none" or refs)): raise ContractError("semantic abstention must be unknown with no scope or evidence claim")
    if not abstained and not refs: raise ContractError("non-abstaining semantic judgement needs evidence references")
    required_text(value["rationale"], "semantic rationale")
    alternative = value["alternative_analysis"]
    if not isinstance(alternative, Mapping) or set(alternative) != {"status", "rationale", "candidate_specifications"} or alternative["status"] not in _ALTERNATIVES: raise ContractError("alternative analysis has an invalid schema")
    required_text(alternative["rationale"], "alternative rationale")
    specs = alternative["candidate_specifications"]
    if not isinstance(specs, list) or any(not isinstance(item, Mapping) or set(item) != {"specification_id", "link", "function"} for item in specs): raise ContractError("alternative candidate specifications are invalid")
    if len({item["specification_id"] for item in specs}) != len(specs): raise ContractError("alternative candidate specifications repeat ids")
    for item in specs:
        required_text(item["specification_id"], "alternative specification id"); required_text(item["link"], "alternative link"); required_text(item["function"], "alternative function")
