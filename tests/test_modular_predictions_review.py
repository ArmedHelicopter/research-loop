from pathlib import Path

import pytest

from research_loop.modular.contracts import DataIdentity
from research_loop.modular.modules.predictions import PredictionRegistry
from research_loop.modular.modules.review import ReviewEngine
from research_loop.ontology import ContractError


def identity(domain="train"):
    return DataIdentity("synthetic", "public-task", "family-a", "v1", "split-a", domain)


def branches():
    return [
        {"hypothesis_id": "mechanism", "mechanism_key": "real-effect", "mechanism": "treatment changes outcome", "intervention": "randomize treatment", "elimination_condition": "opposite result",
         "predictions": [{"prediction_id": "p1", "discriminator_id": "shared", "observable": "outcome delta", "direction": "positive", "value_range": None, "failure_condition": "delta nonpositive"}]},
        {"hypothesis_id": "measurement", "mechanism_key": "instrument-bias", "mechanism": "instrument creates apparent delta", "intervention": "blind instrument", "elimination_condition": "delta remains blind",
         "predictions": [{"prediction_id": "p2", "discriminator_id": "shared", "observable": "outcome delta", "direction": None, "value_range": [-0.1, 0.1], "failure_condition": "delta outside null range"}]},
    ]


def response(assessment="accept"):
    return {"assessment": assessment, "evidence_refs": ["root-a"], "counterexamples": [], "uncertainty": "limited sample"}


def test_q31_q32_operational_competitors_shared_discriminator_and_updates(tmp_path: Path):
    registry = PredictionRegistry(identity(), storage_path=tmp_path / "predictions.jsonl")
    plan = registry.freeze("why did outcome change?", branches(), budget_units=3)
    assert plan.frozen and len(plan.branches) == 2
    update = registry.record_outcome(plan.plan_id, "shared", "outcome-1", {"mechanism": "consistent", "measurement": "failed"}, {"trusted_evaluator": "broker", "verified": True})
    assert dict(update.per_hypothesis)["measurement"] == "failed"
    with pytest.raises(ContractError):
        registry.record_outcome(plan.plan_id, "shared", "different", {"mechanism": "consistent", "measurement": "failed"}, {"trusted_evaluator": "broker", "verified": True})
    assert PredictionRegistry(identity(), storage_path=tmp_path / "predictions.jsonl").updates(plan.plan_id) == (update,)


def test_q31_q53_reject_title_diversity_and_non_discriminating_predictions():
    duplicate = branches()
    duplicate[1]["mechanism_key"] = "real-effect"
    duplicate[1]["predictions"] = duplicate[0]["predictions"]
    with pytest.raises(ContractError):
        PredictionRegistry(identity()).freeze("q", duplicate, budget_units=2)
    same = branches()
    same[1]["predictions"][0].update({"direction": "positive", "value_range": None, "failure_condition": "delta nonpositive"})
    with pytest.raises(ContractError):
        PredictionRegistry(identity()).freeze("q", same, budget_units=2)


def test_same_mechanism_with_opposite_predictions_remains_a_competitor(tmp_path: Path):
    candidates = branches()
    candidates[1]["mechanism_key"] = candidates[0]["mechanism_key"]
    registry = PredictionRegistry(identity(), storage_path=tmp_path / "same-mechanism.jsonl")
    plan = registry.freeze("same mechanism under competing predictions", candidates, budget_units=2)
    assert len(plan.branches) == 2
    assert PredictionRegistry(identity(), storage_path=tmp_path / "same-mechanism.jsonl").plan(plan.plan_id) == plan


def test_q41_q42_q43_sealed_barrier_concrete_roles_and_revision(tmp_path: Path):
    engine = ReviewEngine(identity(), storage_path=tmp_path / "review.jsonl")
    session = engine.open(task_binding="public-task", evidence_snapshot="snapshot-hash", budget_units=5,
                          roles=[{"role_id": "mechanism", "question": "Does the mechanism explain the observation?"},
                                 {"role_id": "measurement", "question": "Could measurement generate this observation?"}])
    engine.submit(session.review_id, role_id="mechanism", reviewer_id="sample-a", response=response(), cost_units=2)
    with pytest.raises(ContractError):
        engine.reveal(session.review_id)
    with pytest.raises(ContractError):
        engine.submit(session.review_id, role_id="measurement", reviewer_id="sample-a", response=response(), cost_units=2)
    engine.submit(session.review_id, role_id="measurement", reviewer_id="sample-b", response=response("unknown"), cost_units=2)
    assert len(engine.reveal(session.review_id)) == 2
    revision = engine.revise_after_reveal(session.review_id, role_id="mechanism", reviewer_id="sample-a", response=response("concern"))
    assert revision.role_id == "mechanism"
    assert ReviewEngine(identity(), storage_path=tmp_path / "review.jsonl").barrier_open(session.review_id)


def test_q44_q45_accept_allowed_and_only_trusted_scorer_records_correctness():
    engine = ReviewEngine(identity())
    session = engine.open(task_binding="public-task", evidence_snapshot="snapshot", budget_units=2,
                          roles=[{"role_id": "discriminator", "question": "Which discriminating test is missing?"}])
    # A valid reviewer may find no counterexample and accept; no self-reported correctness field exists.
    engine.submit(session.review_id, role_id="discriminator", reviewer_id="sample-a", response=response("accept"), cost_units=1)
    with pytest.raises(ContractError):
        engine.record_score(session.review_id, changes=[{"role_id": "discriminator", "before": "correct", "after": "incorrect"}], scorer_receipt={"trusted_scorer": "sealed", "verified": "true"})
    receipt = engine.record_score(session.review_id, changes=[{"role_id": "discriminator", "before": "correct", "after": "incorrect"}], scorer_receipt={"trusted_scorer": "sealed", "verified": True})
    assert receipt.changes == (("discriminator", "correct", "incorrect"),)


def test_identity_binding_blocks_cross_task_review_and_prediction_logs(tmp_path: Path):
    registry = PredictionRegistry(identity(), storage_path=tmp_path / "p.jsonl")
    registry.freeze("q", branches(), budget_units=2)
    with pytest.raises(ContractError):
        PredictionRegistry(DataIdentity("synthetic", "other", "family-a", "v1", "split-a", "train"), storage_path=tmp_path / "p.jsonl")
    engine = ReviewEngine(identity(), storage_path=tmp_path / "r.jsonl")
    engine.open(task_binding="public-task", evidence_snapshot="s", budget_units=1, roles=[{"role_id": "r", "question": "Specific question?"}])
    with pytest.raises(ContractError):
        ReviewEngine(DataIdentity("synthetic", "other", "family-a", "v1", "split-a", "train"), storage_path=tmp_path / "r.jsonl")
