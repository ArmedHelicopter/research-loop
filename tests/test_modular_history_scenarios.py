"""Integration checks for the runnable Q1 history fixtures, not benchmark claims."""
from __future__ import annotations

import pytest

from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask
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


def test_q12_registered_dependency_revises_downstream_but_summary_is_source_insufficient():
    public_task = task()
    registered = run_history_scenario("Q1.2", "registered", task=public_task, frozen_controls=controls(public_task))
    summary = run_history_scenario("Q1.2", "summary_only", task=public_task, frozen_controls=controls(public_task))
    reg_events, summary_events = registered.mechanism_trace.data()["events"], summary.mechanism_trace.data()["events"]
    assert any(row["event"] == "registered_dependency" for row in reg_events)
    assert len(next(row for row in reg_events if row["event"] == "withdrawal_refresh")["revised_claims"]) == 2
    assert any(row["event"] == "summary_source_insufficient" for row in summary_events)


def test_q13_representations_share_one_evidence_root_and_q14_keeps_qualified_chain():
    public_task = task()
    duplicate = run_history_scenario("Q1.3", "memory", task=public_task, frozen_controls=controls(public_task))
    copied = run_history_scenario("Q1.4", "copies", task=public_task, frozen_controls=controls(public_task))
    dedup = next(row for row in duplicate.mechanism_trace.data()["events"] if row["event"] == "representation_dedup")
    provenance = next(row for row in copied.mechanism_trace.data()["events"] if row["event"] == "fixture_provenance")
    assert dedup["root_ids"][0] == dedup["root_ids"][1] and dedup["independent_root_count"] == 1
    assert provenance["statistical_source_group"] == public_task.identity.group_id
    assert provenance["distinct_ids_do_not_prove_independence"] is True


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
