from pathlib import Path

import pytest

from research_loop.modular.benchmarks import BladeAdapter, DiscoveryBenchAdapter
from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.modular.deployment import FileDeploymentPort
from research_loop.modular.experiments import registry
from research_loop.modular.modules.improvement import BoundedCandidateBuilder, CandidatePackage, ExecutionRuntime, TrainingManifest
from research_loop.modular.scenarios_improvement import (
    _VARIANTS, _activate_with_calibration_guard, _shadow_authority,
    _signed_calibration, run_improvement_scenario,
)


def task_for(adapter: str):
    identity = DataIdentity(adapter, "m9-fixture", "m9-group", "v1", "split", "train")
    if adapter == "blade":
        return BladeAdapter().prepare(identity, {"task_id": "m9-fixture", "dataset_id": "public", "research_question": "Does x change?", "data_schema": [{"name": "x"}]})
    return DiscoveryBenchAdapter().prepare(identity, {"task_id": "m9-fixture", "question": "Does x change?", "source_kind": "synthetic", "dataset": [{"name": "public", "columns": [{"name": "x"}]}]})


def controls(task): return FrozenRecord.from_dict({"task_digest": task.content_hash, "budget_digest": "matched-search-two", "fixture_only": True})


def test_variants_match_registry():
    assert {key: tuple(value) for key, value in _VARIANTS.items()} == {key: registry()[key].variants for key in _VARIANTS}


@pytest.mark.parametrize("adapter", ["blade", "discoverybench"])
@pytest.mark.parametrize(("experiment", "variant"), [(key, variant) for key, variants in _VARIANTS.items() for variant in variants])
def test_m9_variants_retain_public_callback_payloads(tmp_path: Path, adapter: str, experiment: str, variant: str):
    task = task_for(adapter); seen = []
    result = run_improvement_scenario(experiment, variant, task=task, frozen_controls=controls(task), sidecar=tmp_path / experiment / variant,
                                      callback=lambda request: seen.append(request) or FrozenRecord.from_dict({"callback": request.data()["kind"]}))
    assert result.callback_payloads == tuple(seen)
    assert all(payload.data()["task"] == task.data() for payload in seen)
    assert "labels" not in "".join(payload.encoded for payload in seen).lower()


def test_q63_executes_restricted_meta_builder(tmp_path: Path):
    task = task_for("blade")
    fixed = run_improvement_scenario("Q6.3", "fixed", task=task, frozen_controls=controls(task), sidecar=tmp_path / "fixed")
    meta = run_improvement_scenario("Q6.3", "train_proposed", task=task, frozen_controls=controls(task), sidecar=tmp_path / "meta", callback=lambda _request: FrozenRecord.from_dict({"builder_dsl": {"entrypoint": "emit_literal_change_v1", "surface": "memory", "key": "mode", "value": "from-train-trace"}}))
    assert fixed.record.data()["detail"]["builder_receipt"]["output_candidate_digest"] == fixed.record.data()["detail"]["candidate_digest"]
    assert meta.record.data()["detail"]["builder_receipt"]["output_candidate_digest"] == meta.record.data()["detail"]["candidate_digest"]
    assert fixed.record.data()["detail"]["builder_digest"] != meta.record.data()["detail"]["active_builder_digest"]


def test_q66_next_workflow_observes_candidate_then_rollback_digest(tmp_path: Path):
    task = task_for("discoverybench")
    result = run_improvement_scenario("Q6.6", "rollback", task=task, frozen_controls=controls(task), sidecar=tmp_path / "rollback")
    detail = result.record.data()["detail"]
    assert detail["before"]["active_digest"] != detail["next_workflow"]["active_digest"]
    assert detail["after"]["active_digest"] == detail["before"]["active_digest"]


def test_q65_never_activates_the_real_promoter(tmp_path: Path):
    task = task_for("blade")
    result = run_improvement_scenario("Q6.5", "sealed_calibrated", task=task, frozen_controls=controls(task), sidecar=tmp_path / "feedback")
    detail = result.record.data()["detail"]
    assert detail["promotion"] == "calibration_eligibility_rejected"
    assert detail["real_promoter_changed"] is False and detail["activation_count"] == 0
    assert len(detail["offline_shadow_rounds"]) == 2
    assert all(row["authority_decision"] == "calibration_eligibility_rejected" and row["activation_attempted"] is False for row in detail["offline_shadow_rounds"])
    assert all("frozen criteria" in row["rejection"] and row["scientific_effect_status"] == "not_measured" for row in detail["offline_shadow_rounds"])


def test_q62_fixed_reuses_original_package_without_callback_or_optimizer(tmp_path: Path):
    task = task_for("blade")
    result = run_improvement_scenario("Q6.2", "fixed", task=task, frozen_controls=controls(task), sidecar=tmp_path / "fixed")
    detail = result.record.data()["detail"]
    assert detail["candidate_digest"] == detail["baseline_digest"]
    assert detail["proposal_digest"] is None and detail["callback_calls"] == 0 and detail["cost"] == 0


def test_q65_unprotected_uses_actual_offline_shadow_activation(tmp_path: Path):
    task = task_for("blade")
    result = run_improvement_scenario("Q6.5", "unprotected", task=task, frozen_controls=controls(task), sidecar=tmp_path / "shadow")
    detail = result.record.data()["detail"]
    assert detail["real_promoter_changed"] is True
    rounds = detail["offline_shadow_rounds"]
    assert detail["activation_count"] == 2 and len(rounds) == 2
    assert all(row["authority_decision"] == "offline_shadow_activated" and row["activation_attempted"] is True for row in rounds)
    assert rounds[1]["parent_digest_before"] == rounds[0]["candidate_digest"]
    assert rounds[1]["active_digest_after"] == rounds[1]["candidate_digest"]
    assert detail["scientific_calibration_claimed"] is False and detail["scientific_effect_status"] == "not_measured"


def test_q65_calibration_guard_can_activate_only_with_eligible_signed_receipt(tmp_path: Path):
    task = task_for("blade")
    frozen = controls(task)
    manifest = TrainingManifest.freeze((task.identity,))
    base = CandidatePackage.create(parent_digest=None, manifest=manifest, changes={"memory": {"mode": "off"}}, search_cost=2)
    candidate = BoundedCandidateBuilder().build(manifest, base, {"memory": {"mode": "shadow", "lesson": "guard-positive-control"}}, search_cost=2)
    runtime = ExecutionRuntime(tmp_path / "guard.sqlite", FileDeploymentPort(tmp_path / "guard.json", base), _shadow_authority(), base)
    try:
        acknowledged = _activate_with_calibration_guard(runtime, _shadow_authority(), candidate, base.digest,
                                                        _signed_calibration(base.digest, base.digest, frozen.content_hash, eligible=True),
                                                        scorer_digest=base.digest, protocol_digest=frozen.content_hash)
        assert acknowledged.active_digest == candidate.digest and runtime.active().digest == candidate.digest
    finally:
        runtime.close()


def test_q62_automatic_uses_callback_train_proposal_or_records_rejection(tmp_path: Path):
    task = task_for("blade")
    valid = run_improvement_scenario("Q6.2", "automatic_train", task=task, frozen_controls=controls(task), sidecar=tmp_path / "valid", callback=lambda _request: FrozenRecord.from_dict({"changes": {"memory": {"mode": "automatic", "lesson": "derived-train-trace"}}}))
    invalid = run_improvement_scenario("Q6.2", "automatic_train", task=task, frozen_controls=controls(task), sidecar=tmp_path / "invalid", callback=lambda _request: FrozenRecord.from_dict({"changes": {"scorer": {"rewrite": "no"}}}))
    assert valid.record.data()["detail"]["candidate_changes"]["memory"]["lesson"] == "derived-train-trace"
    assert invalid.record.data()["detail"]["candidate_digest"] is None and invalid.record.data()["detail"]["rejected"]
