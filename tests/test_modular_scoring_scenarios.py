"""Focused fixture tests for the new semantic scorer path only."""
from __future__ import annotations

import pytest

from research_loop.modular.benchmarks import BladeAdapter, DiscoveryBenchAdapter
from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.modular.scenarios_scoring import run_scoring_scenario
from research_loop.modular.semantics import frozen_completion_semantics, judge_completion, semantic_request
from research_loop.ontology import ContractError


def task(adapter):
    identity = DataIdentity("blade" if adapter == "blade" else "discoverybench", f"{adapter}-scoring-fixture", "fixture-group", "v1", "split", "train")
    if adapter == "blade":
        return BladeAdapter().prepare(identity, {"task_id": identity.task_id, "dataset_id": "fixture", "research_question": "What does the public fixture establish?", "data_schema": [{"name": "outcome"}]})
    return DiscoveryBenchAdapter().prepare(identity, {"task_id": identity.task_id, "question": "What does the public fixture establish?", "difficulty": "fixture", "source_kind": "synthetic", "dataset": [{"name": "fixture", "description": "public", "columns": []}]})


def controls(public_task):
    return FrozenRecord.from_dict({"task_digest": public_task.content_hash, "budget_digest": "frozen-scoring-budget", "fixture_only": True})


def semantic_fixture_judge(request):
    # A deterministic engineering substitute for a semantic service. It is
    # intentionally injected by tests; production code has no keyword scorer.
    answer = request.data()["raw_answer"]
    table = {
        "The programme has met its stated endpoint using the cited observation.": ("affirmed", "programme", "considered"),
        "The programme has not met its stated endpoint using the cited observation.": ("negated", "programme", "considered"),
        "The report quotes an earlier statement that the programme had met an endpoint.": ("quoted", "none", "not_applicable"),
        "If the cited observation had held, the programme would have met its endpoint.": ("counterfactual", "none", "not_applicable"),
        "This local analysis step is complete using the cited observation.": ("affirmed", "local", "considered"),
        "A reasonable alternative explanation remains under consideration for the cited observation.": ("unknown", "none", "unknown"),
    }
    base = answer.removesuffix(" The same public record is supplied to this arm.")
    polarity, scope, alternative = table[base]
    abstained = polarity == "unknown"
    return {"polarity": polarity, "scope": scope, "evidence_refs": [] if abstained else ["fixture-evidence-a"], "abstained": abstained,
            "rationale": "deterministic fixture judgement", "alternative_analysis": {"status": alternative, "rationale": "separate fixture alternative analysis"}}


@pytest.mark.parametrize("adapter", ["blade", "discovery"])
@pytest.mark.parametrize(("variant", "claim"), [("affirm", True), ("negate", False), ("quote", False), ("counterfactual", False), ("local", False)])
def test_q22_all_declared_minimal_pairs_use_actual_judge_response(adapter, variant, claim):
    public_task = task(adapter)
    result = run_scoring_scenario("Q2.2", variant, task=public_task, frozen_controls=controls(public_task), semantic_judge=semantic_fixture_judge)
    request = result.judge_requests[0].data()
    assert {"expected", "oracle", "arm", "score"}.isdisjoint(request)
    assert result.scores[0].data()["programme_completion_claim"] is claim
    assert result.record.data()["judgement_digests"] == [result.judgements[0].content_hash]


def test_q64_creates_new_version_for_both_arms_and_keeps_legacy_only_diagnostic():
    public_task = task("blade")
    result = run_scoring_scenario("Q6.4", "alternative", task=public_task, frozen_controls=controls(public_task), semantic_judge=semantic_fixture_judge)
    record = result.record.data()
    assert record["arms"] == ["A", "B"]
    assert len(set(record["arm_scorer_digests"].values())) == 1
    assert record["legacy_diagnostic"]["prior_scorer_version"] == "legacy-unmodified"
    assert "validation" in record["legacy_diagnostic"]["purpose"]
    assert all(score.data()["alternative_analysis"]["status"] == "unknown" for score in result.scores)
    assert all(score.data()["reference_consistency"]["checked"] for score in result.scores)


@pytest.mark.parametrize("variant", ["negation", "quotation", "alternative"])
def test_q64_every_declared_repair_case_changes_public_answer_material_but_uses_same_v2(variant):
    public_task = task("discovery")
    result = run_scoring_scenario("Q6.4", variant, task=public_task, frozen_controls=controls(public_task), semantic_judge=semantic_fixture_judge)
    assert len(result.judge_requests) == 2
    assert result.judge_requests[0].data()["raw_answer"] != result.judge_requests[1].data()["raw_answer"]
    assert result.judge_requests[0].data()["semantics"] == result.judge_requests[1].data()["semantics"]


def test_abstention_and_reference_contract_are_strict():
    public_task = task("blade")
    request = semantic_request(public_task, frozen_completion_semantics(), raw_answer="A public answer.", public_evidence={"e": "public"})
    with pytest.raises(ContractError, match="abstention"):
        judge_completion(request, lambda _: {"polarity": "unknown", "scope": "programme", "evidence_refs": [], "abstained": True, "rationale": "x", "alternative_analysis": {"status": "unknown", "rationale": "x"}})
    with pytest.raises(ContractError, match="public evidence"):
        judge_completion(request, lambda _: {"polarity": "affirmed", "scope": "programme", "evidence_refs": ["hidden"], "abstained": False, "rationale": "x", "alternative_analysis": {"status": "considered", "rationale": "x"}})


def test_default_fixture_judge_abstains_instead_of_inventing_a_completion_call():
    public_task = task("blade")
    result = run_scoring_scenario("Q2.2", "affirm", task=public_task, frozen_controls=controls(public_task))
    assert result.scores[0].data()["abstained"] is True
    assert result.scores[0].data()["programme_completion_claim"] is False
