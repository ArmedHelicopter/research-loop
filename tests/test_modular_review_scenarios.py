"""Q4 engineering fixtures: callback binding and M5 receipts, not experiments."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from research_loop.modular.benchmarks import BladeAdapter, DiscoveryBenchAdapter
from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.modular.scenarios_review import run_review_scenario as _run_review_scenario
from research_loop.ontology import ContractError


def run_review_scenario(*args, **kwargs):
    """Every fixture invocation supplies a fresh durable producer root."""
    root = Path(tempfile.mkdtemp(prefix="q4-review-"))
    root.rmdir()
    kwargs["artifact_root"] = root
    return _run_review_scenario(*args, **kwargs)


def task(adapter: str):
    identity = DataIdentity("blade" if adapter == "blade" else "discoverybench", f"{adapter}-review-fixture", "fixture-group", "v1", "split", "train")
    if adapter == "blade":
        return BladeAdapter().prepare(identity, {"task_id": identity.task_id, "dataset_id": "fixture", "research_question": "Can the public observation distinguish explanations?", "data_schema": [{"name": "outcome"}]})
    return DiscoveryBenchAdapter().prepare(identity, {"task_id": identity.task_id, "question": "Can the public observation distinguish explanations?", "difficulty": "fixture", "source_kind": "synthetic", "dataset": [{"name": "fixture", "description": "public", "columns": []}]})


def controls(public_task):
    return FrozenRecord.from_dict({"task_digest": public_task.content_hash, "evidence_digest": "frozen-public-evidence", "budget_digest": "frozen-review-budget", "fixture_only": True})


def responder(payload):
    case = payload.data()["public_case"]["observations"]
    revision = payload.data()["invocation"] == "revision"
    # The callback derives its own response from the visible public material.
    # It is not passed the separate fixture oracle or a desired score.
    if len(case) == 1:
        assessment = "concern" if revision else "accept"
        refs = [case[0]["evidence_id"]]
    else:
        assessment = "concern" if revision else "accept"
        refs = [case[-1]["evidence_id"]]
    return {"assessment": assessment, "evidence_refs": refs, "counterexamples": [], "uncertainty": "deterministic engineering callback"}


def prediction_responder(payload):
    review = responder(payload)
    role = payload.data()["role"]["role_id"]
    directions = {"sample_1": "positive", "sample_2": "negative", "sample_3": "null", "sample_4": "positive",
                  "mechanism": "positive", "alternative": "negative", "measurement": "null", "experiment": "positive"}
    return {"review": review, "prediction_candidate": {"hypothesis_id": f"candidate-{role}", "mechanism_key": f"mechanism-{role}",
        "mechanism": f"callback supplied mechanism {role}", "intervention": "fixed-public-intervention",
        "elimination_condition": "callback prediction fails", "predictions": [{"prediction_id": f"prediction-{role}",
        "discriminator_id": "shared-public-discriminator", "observable": "public fixture outcome", "direction": directions[role],
        "value_range": None, "failure_condition": f"declared {directions[role]} outcome is absent"}]}}


@pytest.mark.parametrize("adapter", ["blade", "discovery"])
@pytest.mark.parametrize(("experiment_id", "variant"), [
    ("Q4.1", "single"), ("Q4.1", "independent_samples"), ("Q4.1", "roles"),
    ("Q4.2", "mechanism"), ("Q4.2", "alternative"), ("Q4.2", "measurement"), ("Q4.2", "experiment"), ("Q4.2", "generic"),
    ("Q4.3", "sealed_then_exchange"), ("Q4.3", "sequential"),
    ("Q4.4", "none_valid"), ("Q4.4", "defective"),
    ("Q4.5", "right_to_wrong"), ("Q4.5", "wrong_to_right"),
])
def test_registered_q4_variant_uses_prepared_public_task_and_retains_actual_callback(adapter, experiment_id, variant):
    public_task = task(adapter)
    result = run_review_scenario(experiment_id, variant, task=public_task, frozen_controls=controls(public_task), review_callback=responder)
    assert len(result.callback_payloads) == len(result.callback_responses)
    assert result.record.data()["task_digest"] == public_task.content_hash
    assert all(payload.data()["task"] == public_task.data() for payload in result.callback_payloads)
    assert result.record.data()["callback_response_digests"] == [response.content_hash for response in result.callback_responses]


def test_q41_has_equal_accounted_budget_but_actual_distinct_call_counts():
    public_task = task("blade")
    single = run_review_scenario("Q4.1", "single", task=public_task, frozen_controls=controls(public_task), review_callback=responder)
    repeated = run_review_scenario("Q4.1", "independent_samples", task=public_task, frozen_controls=controls(public_task), review_callback=responder)
    roles = run_review_scenario("Q4.1", "roles", task=public_task, frozen_controls=controls(public_task), review_callback=responder)
    assert single.record.data()["budget"]["fixture_units"] == 4
    assert repeated.record.data()["budget"]["fixture_units"] == 4
    assert roles.record.data()["budget"]["fixture_units"] == 4
    assert single.record.data()["budget"]["initial_calls"] == 1
    assert repeated.record.data()["budget"]["initial_calls"] == roles.record.data()["budget"]["initial_calls"] == 4
    assert len({item.data()["role"]["question"] for item in roles.callback_payloads}) == 4


def test_q41_only_freezes_m4_from_real_callback_candidates_without_synthesizing_missing_branches():
    public_task = task("blade")
    no_candidates = run_review_scenario("Q4.1", "single", task=public_task, frozen_controls=controls(public_task), review_callback=responder)
    result = run_review_scenario("Q4.1", "roles", task=public_task, frozen_controls=controls(public_task), review_callback=prediction_responder)
    assert no_candidates.record.data()["m4"]["status"] == "rejected"
    assert result.record.data()["m4"]["status"] == "on"
    assert result.record.data()["m4"]["outcome"] == "unknown"


def test_revision_callbacks_are_preallocated_and_q45_matches_fixture_units_not_tokens():
    public_task = task("blade")
    right_wrong = run_review_scenario("Q4.5", "right_to_wrong", task=public_task, frozen_controls=controls(public_task), review_callback=responder)
    identities = {
        "reviewer_one": {"reviewer_id": "local-a", "model_id": "model-a", "provider": "local-host-a", "provenance": "caller-supplied receipt A"},
        "reviewer_two": {"reviewer_id": "local-b", "model_id": "model-b", "provider": "local-host-b", "provenance": "caller-supplied receipt B"},
    }
    heterogeneous = run_review_scenario("Q4.5", "heterogeneous", task=public_task, frozen_controls=controls(public_task), review_callback=responder, reviewer_identities=identities)
    for result in (right_wrong, heterogeneous):
        record = result.record.data()
        assert len(record["callback_reservations"]) == len(result.callback_payloads)
        assert all(row["reserved_before_callback"] for row in record["callback_reservations"])
        assert record["budget"]["fixture_units"] == 4
        assert record["budget"]["real_token_matching_claimed"] is False


def test_q43_sealed_and_sequential_have_actual_different_visibility_and_revisions(tmp_path):
    public_task = task("discovery")
    sealed = run_review_scenario("Q4.3", "sealed_then_exchange", task=public_task, frozen_controls=controls(public_task), review_callback=responder, review_log_path=tmp_path / "sealed.jsonl")
    sequential = run_review_scenario("Q4.3", "sequential", task=public_task, frozen_controls=controls(public_task), review_callback=responder, review_log_path=tmp_path / "sequential.jsonl")
    assert sealed.callback_payloads[1].data()["prior_visible_submission"] is None
    assert sequential.callback_payloads[1].data()["prior_visible_submission"] is not None
    assert [item.data()["invocation"] for item in sealed.callback_payloads] == ["initial", "initial", "revision", "revision"]
    assert "revise" in (tmp_path / "sealed.jsonl").read_text(encoding="utf-8")


def test_q45_scores_actual_before_after_responses_through_separate_fixture_oracle():
    public_task = task("blade")
    right_wrong = run_review_scenario("Q4.5", "right_to_wrong", task=public_task, frozen_controls=controls(public_task), review_callback=responder)
    wrong_right = run_review_scenario("Q4.5", "wrong_to_right", task=public_task, frozen_controls=controls(public_task), review_callback=responder)
    assert right_wrong.record.data()["metrics"]["right_to_wrong"] == 1
    assert wrong_right.record.data()["metrics"]["wrong_to_right"] == 1
    assert right_wrong.record.data()["metrics"]["net_correction"] == -1
    assert wrong_right.record.data()["metrics"]["net_correction"] == 1


def test_q45_heterogeneous_requires_real_explicit_provenance_without_fabrication():
    public_task = task("blade")
    with pytest.raises(ContractError, match="explicit reviewer provenance"):
        run_review_scenario("Q4.5", "heterogeneous", task=public_task, frozen_controls=controls(public_task))
    identities = {
        "reviewer_one": {"reviewer_id": "local-a", "model_id": "model-a", "provider": "local-host-a", "provenance": "caller-supplied local deployment receipt A"},
        "reviewer_two": {"reviewer_id": "local-b", "model_id": "model-b", "provider": "local-host-b", "provenance": "caller-supplied local deployment receipt B"},
    }
    result = run_review_scenario("Q4.5", "heterogeneous", task=public_task, frozen_controls=controls(public_task), review_callback=responder, reviewer_identities=identities)
    seen = [item.data()["reviewer_identity"] for item in result.callback_payloads[:2]]
    assert seen == [identities["reviewer_one"], identities["reviewer_two"]]
