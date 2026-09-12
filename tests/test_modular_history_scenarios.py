"""Integration checks for the runnable Q1 history fixtures, not benchmark claims."""
from __future__ import annotations

import pytest

from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask
from research_loop.modular.benchmarks import DiscoveryBenchAdapter
from research_loop.modular.experiments import ControllerInputs, registry, scenario
from research_loop.modular.scenarios_history import run_history_scenario


def task(domain: str = "train") -> PublicTask:
    return PublicTask.create(DataIdentity("fixture", "history-task", "group-a", "v1", "split", domain),
                             {"task_id": "history-task", "research_question": "What does the public fixture show?"})


def controls(public_task: PublicTask) -> FrozenRecord:
    return FrozenRecord.from_dict({"task_digest": public_task.content_hash, "evidence_digest": "frozen-evidence",
                                   "budget_digest": "frozen-budget", "fixture_only": True})


@pytest.mark.parametrize(("experiment_id", "variant"), [
    ("Q1.2", "summary_only"), ("Q1.2", "registered"), ("Q1.2", "withdraw"),
    ("Q1.3", "log"), ("Q1.3", "report"), ("Q1.3", "summary"), ("Q1.3", "memory"),
    ("Q1.4", "one_withdrawn"), ("Q1.4", "all_withdrawn"), ("Q1.4", "copies"),
    ("Q1.5", "blind_first"), ("Q1.5", "summary_first"),
    ("Q1.6", "replacement"), ("Q1.6", "none"), ("Q1.6", "high_score"),
    ("Q1.7", "irrelevant"), ("Q1.7", "causal"), ("Q1.7", "unknown"),
])
def test_every_q1_history_variant_runs_on_current_public_task(experiment_id: str, variant: str):
    public_task, seen = task(), []
    result = run_history_scenario(experiment_id, variant, task=public_task, frozen_controls=controls(public_task), next_model=seen.append)
    assert seen == [result.next_payload]
    body = seen[0].data()
    assert body["task"] == public_task.data() and body["fixture_only"] is True
    assert body["frozen_controls"]["task_digest"] == public_task.content_hash
    assert result.mechanism_trace.data()["events"][-1]["event"] == "next_model_invoked"


def test_q12_registered_revision_and_withdrawal_rebuild_different_real_contexts():
    public_task = task()
    registered = run_history_scenario("Q1.2", "registered", task=public_task, frozen_controls=controls(public_task))
    withdrawn = run_history_scenario("Q1.2", "withdraw", task=public_task, frozen_controls=controls(public_task))
    summary = run_history_scenario("Q1.2", "summary_only", task=public_task, frozen_controls=controls(public_task))
    reg_events, summary_events = registered.mechanism_trace.data()["events"], summary.mechanism_trace.data()["events"]
    assert any(row["event"] == "registered_dependency" for row in reg_events)
    rebuild = next(row for row in reg_events if row["event"] == "context_rebuilt_after_claim_revision")
    assert rebuild["before"] != rebuild["after"] and len(rebuild["revised_claims"]) == 2
    assert registered.next_payload.data()["context"] != withdrawn.next_payload.data()["context"]
    assert any(row["event"] == "summary_source_insufficient" for row in summary_events)


def test_q13_representations_share_one_evidence_root_and_q14_copies_are_one_chain():
    public_task = task()
    duplicate = run_history_scenario("Q1.3", "memory", task=public_task, frozen_controls=controls(public_task))
    copied = run_history_scenario("Q1.4", "copies", task=public_task, frozen_controls=controls(public_task))
    dedup = next(row for row in duplicate.mechanism_trace.data()["events"] if row["event"] == "representation_dedup")
    assert dedup["root_ids"][0] == dedup["root_ids"][1] and dedup["independent_root_count"] == 1
    copied_root = next(row for row in copied.mechanism_trace.data()["events"] if row["event"] == "copied_root")
    assert copied_root["active_roots"] == 1


def test_q14_independent_fixture_chains_have_concrete_provenance_and_partial_revocation():
    public_task = task()
    one = run_history_scenario("Q1.4", "one_withdrawn", task=public_task, frozen_controls=controls(public_task))
    all_withdrawn = run_history_scenario("Q1.4", "all_withdrawn", task=public_task, frozen_controls=controls(public_task))
    one_roots = [row for row in one.next_payload.data()["context"]["entries"]["entries"] if row["kind"] == "evidence"]
    assert len(one_roots) == 1
    material = one_roots[0]["payload"]["root_material"]
    assert {"fixture_experiment_id", "fixture_provenance_id", "qualification_receipt_id"} <= set(material)
    all_entries = all_withdrawn.next_payload.data()["context"]["entries"]["entries"]
    assert not any(row["kind"] == "evidence" for row in all_entries)
    assert all(row.get("support_roots", []) == [] for row in all_entries if row["kind"] == "claim")


def test_q15_review_callback_receives_real_ordered_payloads_and_seals_response_before_followup():
    public_task, blind_seen, summary_seen = task(), [], []
    def blind_callback(payload):
        blind_seen.append(payload)
        return {"assessment": "unknown", "evidence_refs": ["fixture-root"], "counterexamples": [], "uncertainty": "fixture-only"}
    def summary_callback(payload):
        summary_seen.append(payload)
        return {"assessment": "unknown", "evidence_refs": ["fixture-root"], "counterexamples": [], "uncertainty": "fixture-only"}
    blind = run_history_scenario("Q1.5", "blind_first", task=public_task, frozen_controls=controls(public_task), review_model=blind_callback)
    summary = run_history_scenario("Q1.5", "summary_first", task=public_task, frozen_controls=controls(public_task), review_model=summary_callback)
    assert len(blind_seen) == len(summary_seen) == 2
    assert blind_seen[0].data()["phase"] == "evidence_only"
    assert summary_seen[0].data()["phase"] == "summary_first"
    assert blind_seen[0].data() != summary_seen[0].data()
    assert blind_seen[0].data()["public_evidence"] == summary_seen[0].data()["public_evidence"]
    assert blind_seen[1].data()["public_evidence"] == summary_seen[1].data()["public_evidence"]
    assert "sealed_submission" in blind_seen[1].data() and blind.review_payloads == tuple(blind_seen)
    assert summary.review_payloads == tuple(summary_seen)
    review = blind.next_payload.data()["scenario_auxiliary"]["review"]
    assert review["sealed_response"]["uncertainty"] == "fixture-only"
    assert review["revised_response"]["uncertainty"] == "fixture-only"


def test_q16_replacement_and_high_score_change_actual_payload_but_never_restore_invalid_support():
    public_task = task()
    replacement = run_history_scenario("Q1.6", "replacement", task=public_task, frozen_controls=controls(public_task))
    none = run_history_scenario("Q1.6", "none", task=public_task, frozen_controls=controls(public_task))
    high = run_history_scenario("Q1.6", "high_score", task=public_task, frozen_controls=controls(public_task))
    replacement_entries = replacement.next_payload.data()["context"]["entries"]["entries"]
    assert any(row["kind"] == "evidence" for row in replacement_entries)
    none_entries = none.next_payload.data()["context"]["entries"]["entries"]
    assert not any(row["kind"] == "evidence" for row in none_entries)
    assert all(row.get("support_roots", []) == [] for row in none_entries if row["kind"] == "claim")
    assert high.next_payload.data()["scenario_auxiliary"]["old_history"]["prior_score"] == 0.99
    assert not any(row["kind"] == "evidence" for row in high.next_payload.data()["context"]["entries"]["entries"])


def test_q17_causal_payload_contains_actual_ordered_timestamps():
    public_task = task()
    causal = run_history_scenario("Q1.7", "causal", task=public_task, frozen_controls=controls(public_task))
    causal_evidence = next(row for row in causal.next_payload.data()["context"]["entries"]["entries"] if row["kind"] == "evidence")
    material = causal_evidence["payload"]["root_material"]
    assert material["causal_predecessor_at"] < material["observed_at"]


def test_registry_binds_q1_scenarios_to_fixture_only_auxiliary_controls():
    inputs = ControllerInputs(FrozenRecord.from_dict({"public": "task"}), FrozenRecord.from_dict({"public": "evidence"}), FrozenRecord.from_dict({"public": "budget"}))
    controlled = scenario(registry()["Q1.6"], "none", inputs=inputs).data()
    assert controlled["controller_input"]["fixture_only"] is True
    assert controlled["base"] == {"task": inputs.task.content_hash, "evidence": inputs.evidence.content_hash, "budget": inputs.budget.content_hash}


def test_validation_is_current_task_only_and_controls_reject_drift():
    public_task = task("validation")
    result = run_history_scenario("Q1.5", "blind_first", task=public_task, frozen_controls=controls(public_task))
    assert result.next_payload.data()["context"]["ephemeral"] is True
    wrong = FrozenRecord.from_dict({**controls(public_task).data(), "task_digest": "other"})
    with pytest.raises(Exception, match="task or fixture"):
        run_history_scenario("Q1.7", "unknown", task=public_task, frozen_controls=wrong)


def test_prepared_payload_is_not_claimed_invoked_without_callback():
    public_task = task()
    result = run_history_scenario("Q1.7", "unknown", task=public_task, frozen_controls=controls(public_task))
    assert result.mechanism_trace.data()["events"][-1]["event"] == "next_model_payload_prepared"


def test_discovery_adapter_question_is_carried_into_context():
    identity = DataIdentity("discoverybench", "discovery-task", "group-a", "v1", "split", "train")
    public_task = DiscoveryBenchAdapter().prepare(identity, {"task_id": "discovery-task", "question": "Does the public question survive?",
        "difficulty": "fixture", "source_kind": "synthetic", "dataset": [{"name": "fixture", "description": "public", "columns": []}]})
    result = run_history_scenario("Q1.7", "unknown", task=public_task, frozen_controls=controls(public_task))
    assert result.next_payload.data()["context"]["question"] == "Does the public question survive?"


def test_default_review_response_is_not_described_as_a_callback():
    public_task = task()
    result = run_history_scenario("Q1.5", "blind_first", task=public_task, frozen_controls=controls(public_task))
    assert any(row["event"] == "sealed_review_fixture_default_response" for row in result.mechanism_trace.data()["events"])
