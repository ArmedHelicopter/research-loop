from __future__ import annotations

import pytest

from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.modular.modules.exploration import (
    Appeal, ExplorationBudget, ExplorationPlan, ExplorationRatioCandidate,
    FeasibilityObservation, InstrumentRepair, ResourceClosure, Veto,
    admit_exploration, appeal_veto, assess_feasibility, review_appeal,
)
from research_loop.modular.modules.retrieval import (
    FrozenRetrievalPolicy, FrozenSourceBundle, RetrievalBudget, RetrievalSignals,
    SourceDocument, retrieve,
)
from research_loop.ontology import ContractError


def record(value: str) -> FrozenRecord:
    return FrozenRecord.from_dict({"value": value})


class Provider:
    def __init__(self, results: dict[str, list[SourceDocument]]) -> None:
        self.results, self.calls = results, []

    def search(self, *, lane: str, query: FrozenRecord, source_bundle: FrozenSourceBundle,
               call_limit: int, source_limit: int) -> list[SourceDocument]:
        self.calls.append((lane, call_limit, source_limit))
        return self.results[lane]


def test_three_lane_retrieval_uses_frozen_bundle_and_deduplicates_roots() -> None:
    support = SourceDocument("s1", "root-1", "support", record("support"))
    paraphrase = SourceDocument("s2", "root-1", "counter", record("paraphrase"))
    method = SourceDocument("m1", "root-2", "method", record("method"))
    bundle = FrozenSourceBundle("snapshot-1", (support, paraphrase, method))
    provider = Provider({"support": [support], "counter": [paraphrase], "method": [method]})
    policy = FrozenRetrievalPolicy("frozen-policy", ("new_mechanism", "key_conflict", "stagnation"), RetrievalBudget(1, 2))
    result = retrieve(provider=provider, query=record("query"), source_bundle=bundle, policy=policy,
                      signals=RetrievalSignals(new_mechanism=True, stagnation=True,
                                               cheap_distinguishing_diagnostic_locked=True))
    assert result.active_triggers == ("new_mechanism",)
    assert result.by_lane["support"] == (support,)
    assert result.by_lane["counter"] == ()
    assert result.by_lane["method"] == (method,)
    assert result.dropped_duplicate_roots == ("root-1",)
    assert len(provider.calls) == 3


def test_retrieval_does_not_call_provider_without_a_frozen_trigger() -> None:
    bundle = FrozenSourceBundle("snapshot", ())
    provider = Provider({"support": [], "counter": [], "method": []})
    result = retrieve(provider=provider, query=record("query"), source_bundle=bundle,
                      policy=FrozenRetrievalPolicy("policy", ("key_conflict",), RetrievalBudget(1, 1)),
                      signals=RetrievalSignals())
    assert result.by_lane == {"support": (), "counter": (), "method": ()}
    assert provider.calls == []


def train_identity() -> DataIdentity:
    return DataIdentity("bench", "task", "group", "version", "train", "train")


def plan() -> ExplorationPlan:
    return ExplorationPlan("p1", train_identity(), record("locked-plan"), ResourceClosure("data-v1", "artifact", "negative", 4, 100))


def test_feasibility_requires_all_stages_and_train_only_appeals() -> None:
    current = plan()
    partial = assess_feasibility(current, {"data": FeasibilityObservation("data", "passed", "d")})
    assert partial.stages["minimal_run"] == "pending"
    assert not partial.is_ready
    assert admit_exploration(plan=current, feasibility=partial, budget=ExplorationBudget(4, 100)).evidence_admission == "not_evidence"
    ready = assess_feasibility(current, {
        "data": FeasibilityObservation("data", "passed", "d"),
        "minimal_run": FeasibilityObservation("minimal_run", "passed", "run"),
        "discriminating_measurement": FeasibilityObservation("discriminating_measurement", "passed", "measure"),
        "independent_result": FeasibilityObservation("independent_result", "passed", "result", "other-group"),
    })
    assert ready.is_ready
    veto = Veto("evidence_insufficient", "needs a small diagnostic", "veto")
    appeal = Appeal(veto, record("diagnostic"), 1, 10)
    permit = appeal_veto(plan=current, veto=veto, appeal=appeal, budget=ExplorationBudget(4, 100))
    assert permit.evidence_admission == "not_evidence"
    deterministic = Veto("deterministic_block", "missing authorization", "block")
    repaired = Appeal(deterministic, record("diagnostic"), 1, 10, repair_digest="repair")
    decision = review_appeal(plan=current, veto=deterministic, appeal=repaired, budget=ExplorationBudget(4, 100))
    assert decision.status == "requires_reassessment"
    with pytest.raises(ContractError, match="reassessment"):
        appeal_veto(plan=current, veto=deterministic, appeal=repaired, budget=ExplorationBudget(4, 100))
    validation = DataIdentity("bench", "task", "group", "version", "validation", "validation")
    with pytest.raises(ContractError, match="training provenance"):
        ExplorationRatioCandidate("ratio", validation, 20)


def test_instrument_repair_requires_new_execution_for_invalidated_evidence() -> None:
    repair = InstrumentRepair("measure-v2", "old", "repair", ("old-evidence",))
    assert repair.requires_new_execution("old-evidence")
    assert not repair.requires_new_execution("unrelated-evidence")
