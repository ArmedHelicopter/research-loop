"""Q2.4/Q2.5 engineering fixtures exercise the real signed audit gate."""
from __future__ import annotations

import subprocess

import pytest

from research_loop.modular.benchmarks import BladeAdapter, DiscoveryBenchAdapter
from research_loop.modular.benchmarks.execution import DockerExecutionBroker
from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask
from research_loop.modular.experiments import ControllerInputs, registry, scenario
from research_loop.modular.scenarios_audit import run_audit_scenario


def public_task(adapter: str) -> PublicTask:
    identity = DataIdentity("blade" if adapter == "blade" else "discoverybench", f"{adapter}-fixture", "fixture-group", "v1", "split", "train")
    if adapter == "blade":
        return BladeAdapter().prepare(identity, {"task_id": identity.task_id, "dataset_id": "public-fixture",
            "research_question": "Does the public fixture pass the gate?", "data_schema": [{"name": "x"}]})
    return DiscoveryBenchAdapter().prepare(identity, {"task_id": identity.task_id, "question": "Does the public fixture pass the gate?",
        "difficulty": "fixture", "source_kind": "synthetic", "dataset": [{"name": "fixture", "description": "public", "columns": []}]})


def controls(task: PublicTask) -> FrozenRecord:
    return FrozenRecord.from_dict({"task_digest": task.content_hash, "budget_digest": "fixture-frozen-budget", "fixture_only": True})


def broker(root):
    root.mkdir()
    return DockerExecutionBroker([root], runner=lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, b"fixture output\n", b""))


@pytest.mark.parametrize("adapter", ["blade", "discovery"])
@pytest.mark.parametrize(("experiment_id", "variant"), [
    ("Q2.4", "one_fail"), ("Q2.4", "both_fail"), ("Q2.4", "disagree"), ("Q2.4", "same_wrong"),
    ("Q2.5", "invalid_positive"), ("Q2.5", "invalid_negative"), ("Q2.5", "valid_negative"),
])
def test_all_audit_variants_run_real_execution_audit_gate_and_model_payload(tmp_path, adapter, experiment_id, variant):
    task = public_task(adapter)
    sidecar = tmp_path / f"{adapter}-{experiment_id}-{variant}"
    result = run_audit_scenario(experiment_id, variant, task=task, frozen_controls=controls(task), sidecar=sidecar, broker=broker(sidecar))
    assert result.model_payload.data()["task"] == task.data()
    assert result.model_payload.data()["module_context"]["fixture_only"] is True
    assert len(result.audit_receipts) == 2
    assert result.trace.data()["terminal"] and "execution_result" in result.trace.data()["stages"]
    assert result.record.data()["denominator"] == {"scheduled": 1, "execution_attempts": 1, "model_calls": 1, "finalized": 1}


@pytest.mark.parametrize("variant", ["one_fail", "both_fail", "disagree"])
def test_q24_incomplete_or_disagreeing_audits_cannot_proceed(tmp_path, variant):
    task, sidecar = public_task("blade"), tmp_path / variant
    result = run_audit_scenario("Q2.4", variant, task=task, frozen_controls=controls(task), sidecar=sidecar, broker=broker(sidecar))
    assert result.gate.data()["decision"] == "blocked"
    assert "audit_rejected" in result.trace.data()["stages"] or result.record.data()["admission"]["admitted"] is False


def test_q24_same_wrong_records_real_false_admission_limitation_without_leaking_truth_to_model(tmp_path):
    task, sidecar = public_task("discovery"), tmp_path / "wrong"
    result = run_audit_scenario("Q2.4", "same_wrong", task=task, frozen_controls=controls(task), sidecar=sidecar, broker=broker(sidecar))
    assert result.gate.data()["decision"] == "proceed"
    limitation = result.record.data()["residual_limitation"]
    assert limitation["false_admission_observed"] and limitation["fixture_controller_ground_truth"] == "scientifically_wrong"
    assert "scientifically_wrong" not in result.model_payload.encoded


def test_q25_invalid_polarities_are_blocked_but_valid_negative_closes_negative(tmp_path):
    task = public_task("blade")
    decisions = {}
    for variant in ("invalid_positive", "invalid_negative", "valid_negative"):
        sidecar = tmp_path / variant
        result = run_audit_scenario("Q2.5", variant, task=task, frozen_controls=controls(task), sidecar=sidecar, broker=broker(sidecar))
        decisions[variant] = result.gate.data()["decision"]
    assert decisions == {"invalid_positive": "blocked", "invalid_negative": "blocked", "valid_negative": "closed_negative"}


def test_registry_binds_closed_fixture_audit_injections():
    inputs = ControllerInputs(FrozenRecord.from_dict({"task": "public"}), FrozenRecord.from_dict({"evidence": "public"}), FrozenRecord.from_dict({"budget": "frozen"}))
    controlled = scenario(registry()["Q2.4"], "same_wrong", inputs=inputs).data()
    assert controlled["controller_input"]["fixture_only"] is True
    assert controlled["controller_input"]["auxiliary"]["controller_ground_truth_private"] is True


@pytest.mark.parametrize("adapter", ["blade", "discovery"])
@pytest.mark.parametrize("variant", registry()["Q2.3"].variants)
def test_q23_authenticated_malformed_audits_block_the_actual_final_gate(tmp_path, adapter, variant):
    task, sidecar = public_task(adapter), tmp_path / (adapter + variant)
    result = run_audit_scenario("Q2.3", variant, task=task, frozen_controls=controls(task),
        sidecar=sidecar, broker=broker(sidecar))
    assert result.gate.data()["decision"] == "blocked"
    assert result.record.data()["admission"] is None or result.record.data()["admission"]["admitted"] is False
    stages = result.trace.data()["stages"]
    assert "execution_result" in stages and "scientific_audit_inputs" in stages and "final_decision" in stages
    assert result.model_payload.data()["task"] == task.data()
    events = [FrozenRecord(line).data() for line in (sidecar / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
    response = next(event["data"]["response"] for event in events if event["stage"] == "model_response")
    assert response["outcome"] == "positive"
    assert response["evidence_ids"] == [result.record.data()["execution_digest"]]
