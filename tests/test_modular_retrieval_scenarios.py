"""Focused public-seam checks for Q8 retrieval scenarios."""
from pathlib import Path

import pytest

from research_loop.modular.benchmarks import BladeAdapter, DiscoveryBenchAdapter
from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.modular.runtime import verify_trace
from research_loop.modular.scenarios_retrieval import _VARIANTS, run_retrieval_scenario


def task_for(adapter: str, domain: str = "train"):
    identity = DataIdentity(adapter, "q8-fixture", "fixture-group", "v1", "split", domain)
    if adapter == "blade":
        return BladeAdapter().prepare(identity, {"task_id": "q8-fixture", "dataset_id": "public-fixture", "research_question": "What changes?", "data_schema": [{"name": "x"}]})
    return DiscoveryBenchAdapter().prepare(identity, {"task_id": "q8-fixture", "question": "What changes?", "source_kind": "synthetic", "dataset": [{"name": "public-fixture", "columns": [{"name": "x"}]}]})


def controls(task):
    return FrozenRecord.from_dict({"task_digest": task.content_hash, "budget_digest": "one-call-per-lane", "fixture_only": True})


@pytest.mark.parametrize("adapter", ["blade", "discoverybench"])
@pytest.mark.parametrize(("experiment", "variant"), [(experiment, variant) for experiment, variants in _VARIANTS.items() for variant in variants])
def test_q8_registered_variants_keep_public_payloads_and_journals(tmp_path: Path, adapter: str, experiment: str, variant: str):
    task = task_for(adapter)
    seen = []
    result = run_retrieval_scenario(experiment, variant, task=task, frozen_controls=controls(task), sidecar=tmp_path / experiment / variant,
                                    model=lambda request: seen.append(request) or _response(request))
    assert result.requests == tuple(seen)
    assert all(item.data()["task"] == task.data() for item in seen)
    assert verify_trace(Path(result.record.data()["journal"])).data()["events"] > 0
    assert result.record.data()["denominator"]["calls_made"] == len(seen)
    assert "labels" not in "".join(item.encoded for item in seen).lower()


def _response(request: FrozenRecord) -> FrozenRecord:
    slot = request.data()["slot"]
    if slot == "stage_1":
        return FrozenRecord.from_dict({"question": "What changes?", "branches": [{"hypothesis_id": "h1", "mechanism_key": "m1", "mechanism": "a", "intervention": "i", "elimination_condition": "down", "predictions": [{"prediction_id": "p1", "discriminator_id": "d", "observable": "x", "direction": "up", "value_range": None, "failure_condition": "down"}]}, {"hypothesis_id": "h2", "mechanism_key": "m2", "mechanism": "b", "intervention": "i", "elimination_condition": "up", "predictions": [{"prediction_id": "p2", "discriminator_id": "d", "observable": "x", "direction": "down", "value_range": None, "failure_condition": "up"}]}], "budget_units": 2})
    if slot.startswith("stage_7") or slot.startswith("stage_9"):
        return FrozenRecord.from_dict({"assessment": "unknown", "evidence_refs": [], "counterexamples": [], "uncertainty": "fixture"})
    if slot == "frontier":
        return FrozenRecord.from_dict({"proposals": [], "empty_reason": "fixture", "programme_complete": False})
    if slot == "final":
        objective = FrozenRecord.from_dict(request.data()["objective"])
        return FrozenRecord.from_dict({"objective_digest": objective.content_hash, "outcome": "unknown", "evidence_ids": [], "conclusion": "unresolved", "programme_complete": False})
    return FrozenRecord.from_dict({"response": "fixture"})


def test_q81_binds_every_required_real_stage_to_a_trace(tmp_path: Path):
    task = task_for("blade")
    result = run_retrieval_scenario("Q8.1", "all_stages", task=task, frozen_controls=controls(task), sidecar=tmp_path / "all")
    coverage = result.record.data()["detail"]["stage_coverage"]
    assert {row["stage"] for row in coverage if row["status"] == "executed"} >= {"coverage_stage_0.5", "coverage_stage_1", "coverage_stage_3", "coverage_stage_7", "coverage_stage_9", "coverage_frontier"}


def test_q83_same_budget_calls_all_lanes_and_allows_empty_routes(tmp_path: Path):
    task = task_for("blade")
    arms = [run_retrieval_scenario("Q8.3", name, task=task, frozen_controls=controls(task), sidecar=tmp_path / name) for name in ("support_only", "neutral", "three_lane")]
    assert [arm.record.data()["detail"]["budget"] for arm in arms] == [{"calls_per_lane": 1, "sources_per_lane": 1}] * 3
    assert [len(arm.record.data()["detail"]["provider_calls"]) for arm in arms] == [3, 3, 3]


def test_q84_shared_source_is_one_m2_root_but_independent_sources_are_three(tmp_path: Path):
    task = task_for("blade")
    shared = run_retrieval_scenario("Q8.4", "shared_root", task=task, frozen_controls=controls(task), sidecar=tmp_path / "shared")
    independent = run_retrieval_scenario("Q8.4", "independent_roots", task=task, frozen_controls=controls(task), sidecar=tmp_path / "independent")
    assert shared.record.data()["detail"]["same_document_count"] == independent.record.data()["detail"]["same_document_count"] == 3
    assert shared.record.data()["detail"]["evidence_root_count"] == 1
    assert independent.record.data()["detail"]["evidence_root_count"] == 3


def test_q85_cheap_diagnostic_blocks_stagnation_calls(tmp_path: Path):
    task = task_for("blade")
    blocked = run_retrieval_scenario("Q8.5", "cheap_diagnostic", task=task, frozen_controls=controls(task), sidecar=tmp_path / "cheap")
    active = run_retrieval_scenario("Q8.5", "stagnation", task=task, frozen_controls=controls(task), sidecar=tmp_path / "stagnation")
    assert blocked.record.data()["detail"]["provider_calls"] == []
    assert len(active.record.data()["detail"]["provider_calls"]) == 3


def test_q86_source_text_cannot_change_lock_and_q87_empty_frontier_has_no_authority(tmp_path: Path):
    task = task_for("blade")
    q86 = run_retrieval_scenario("Q8.6", "malicious_text", task=task, frozen_controls=controls(task), sidecar=tmp_path / "authority")
    assert q86.record.data()["detail"]["final_gate"]["decision"] == "unknown"
    q87 = run_retrieval_scenario("Q8.7", "empty_frontier", task=task, frozen_controls=controls(task), sidecar=tmp_path / "frontier")
    exported = q87.record.data()["detail"]["training_export"]
    assert exported["proposals"] == [] and exported["benchmark_admission"] is False and exported["queue_admission"] is False and exported["programme_complete"] is False
