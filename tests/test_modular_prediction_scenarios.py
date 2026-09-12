"""M4/M7 prediction fixtures are engineering traces, not benchmark results."""
from __future__ import annotations

import pytest

from research_loop.modular.benchmarks import BladeAdapter, DiscoveryBenchAdapter
from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask
from research_loop.modular.scenarios_predictions import run_prediction_scenario
from research_loop.ontology import ContractError


def public_task(adapter: str, domain: str = "train") -> PublicTask:
    identity = DataIdentity("blade" if adapter == "blade" else "discoverybench", adapter + "-prediction-fixture", "fixture-group", "v1", "split", domain)
    if adapter == "blade":
        return BladeAdapter().prepare(identity, {"task_id": identity.task_id, "dataset_id": "public-fixture", "research_question": "Can public observations distinguish explanations?", "data_schema": [{"name": "x"}]})
    return DiscoveryBenchAdapter().prepare(identity, {"task_id": identity.task_id, "question": "Can public observations distinguish explanations?", "difficulty": "fixture", "source_kind": "synthetic", "dataset": [{"name": "public", "description": "fixture", "columns": []}]})


def controls(task: PublicTask) -> FrozenRecord:
    return FrozenRecord.from_dict({"task_digest": task.content_hash, "budget_digest": "frozen-fixture-budget", "fixture_only": True})


@pytest.mark.parametrize("adapter", ["blade", "discovery"])
@pytest.mark.parametrize(("experiment_id", "variant"), [
    ("Q3.1", "mechanism"), ("Q3.1", "computation"), ("Q3.1", "measurement"),
    ("Q3.2", "joint"), ("Q3.2", "separate"),
    ("Q5.2", "zero_exit_same_prediction"), ("Q5.2", "negative_control"),
    ("Q5.3", "same_mechanism"), ("Q5.3", "opposite_prediction"), ("Q5.3", "title"),
    ("Q5.4", "subjective"), ("Q5.4", "preregistered_cost"),
])
def test_registered_variants_capture_actual_frozen_plan_payloads(adapter, experiment_id, variant):
    task = public_task(adapter)
    seen = []
    result = run_prediction_scenario(experiment_id, variant, task=task, frozen_controls=controls(task), plan_callback=lambda payload: seen.append(payload) or None)
    assert result.callback_payloads == tuple(seen)
    assert all(item.data()["task"] == task.data() for item in seen)
    assert all(item.data()["fixture_only"] is True for item in seen)
    assert result.record.data()["limitation"].startswith("mechanism fixture")
    events = {event["event"] for event in result.mechanism_trace.data()["events"]}
    assert "shared_discriminator_recorded" in events or events >= {"fixture_start", "non_discriminating_plan_rejected"}


def test_joint_and_separate_have_same_budget_but_explicitly_different_evidence_layout():
    task = public_task("blade")
    joint = run_prediction_scenario("Q3.2", "joint", task=task, frozen_controls=controls(task))
    separate = run_prediction_scenario("Q3.2", "separate", task=task, frozen_controls=controls(task))
    joint_event = next(x for x in joint.mechanism_trace.data()["events"] if x["event"] == "arm_structure")
    separate_event = next(x for x in separate.mechanism_trace.data()["events"] if x["event"] == "arm_structure")
    assert joint_event["total_budget_units"] == separate_event["total_budget_units"] == 3
    assert len({row["observation_id"] for row in joint_event["evidence_layout"]}) == 1
    assert len({row["observation_id"] for row in separate_event["evidence_layout"]}) == 3


def test_q52_retains_zero_exit_as_engineering_status_and_requires_measurement():
    result = run_prediction_scenario("Q5.2", "zero_exit_same_prediction", task=public_task("discovery"), frozen_controls=controls(public_task("discovery")))
    event = next(x for x in result.mechanism_trace.data()["events"] if x["event"] == "zero_exit_is_not_identifiability")
    assert event["execution_status"] == "fixture_zero_exit"
    assert event["feasibility"]["discriminating_measurement"] == "failed"
    assert event["feasibility"]["independent_result"] == "blocked"


def test_q53_dedup_uses_mechanism_and_prediction_not_titles():
    task = public_task("blade")
    repeated = run_prediction_scenario("Q5.3", "same_mechanism", task=task, frozen_controls=controls(task))
    opposite = run_prediction_scenario("Q5.3", "opposite_prediction", task=task, frozen_controls=controls(task))
    title = run_prediction_scenario("Q5.3", "title", task=task, frozen_controls=controls(task))
    event = lambda item: next(x for x in item.mechanism_trace.data()["events"] if x["event"] == "mechanism_prediction_dedup")
    assert event(repeated)["removed"] == ["b"]
    assert event(opposite)["removed"] == []
    assert event(title)["removed"] == []


def test_q54_selection_is_within_claimed_item_and_leaves_outer_fifo_untouched():
    task = public_task("blade")
    subjective = run_prediction_scenario("Q5.4", "subjective", task=task, frozen_controls=controls(task))
    diagnostic = run_prediction_scenario("Q5.4", "preregistered_cost", task=task, frozen_controls=controls(task))
    event = lambda item: next(x for x in item.mechanism_trace.data()["events"] if x["event"] == "internal_diagnostic_selection")
    assert event(subjective)["selected"] == "broad"
    assert event(diagnostic)["selected"] == "focused"
    assert event(diagnostic)["outer_queue"] == {"policy": "FIFO", "position": 7, "changed": False}
    validation = public_task("blade", "validation")
    assert run_prediction_scenario("Q5.4", "subjective", task=validation, frozen_controls=controls(validation)).record.data()["fixture_only"]


def test_closed_controls_and_callback_classification_boundaries():
    task = public_task("discovery")
    with pytest.raises(ContractError):
        run_prediction_scenario("Q3.1", "mechanism", task=task, frozen_controls=FrozenRecord.from_dict({"task_digest": task.content_hash, "budget_digest": "b", "fixture_only": False}))
    result = run_prediction_scenario("Q3.1", "mechanism", task=task, frozen_controls=controls(task), plan_callback=lambda _payload: {"ordinary_model_text": "not a scientific verdict"})
    assert result.callback_responses[0].data()["response"]["ordinary_model_text"] == "not a scientific verdict"
