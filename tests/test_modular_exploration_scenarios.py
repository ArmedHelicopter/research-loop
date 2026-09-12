"""Integration tests for Q7 fixture mechanisms; these are not benchmark scores."""
from __future__ import annotations

import pytest
import subprocess
import tempfile
from pathlib import Path

from research_loop.modular.benchmarks import BladeAdapter, DiscoveryBenchAdapter
from research_loop.modular.benchmarks.execution import DockerExecutionBroker
from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask
from research_loop.modular.scenarios_exploration import run_exploration_scenario, select_train_ratio
from research_loop.ontology import ContractError


def controls(task: PublicTask) -> FrozenRecord:
    return FrozenRecord.from_dict({"task_digest": task.content_hash, "budget_digest": "fixture-budget", "fixture_only": True})


def execution_root() -> tuple[Path, DockerExecutionBroker]:
    work = Path(__file__).resolve().parents[1] / "work"
    work.mkdir(exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="exploration-tests-", dir=work))
    return root, DockerExecutionBroker([root], runner=lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, b"fixture output\n", b""))


def run(experiment_id: str, variant: str, task: PublicTask, **kwargs):
    if experiment_id in {"Q7.3", "Q7.4"}:
        sidecar, broker = execution_root()
        kwargs.update(sidecar=sidecar, broker=broker)
    return run_exploration_scenario(experiment_id, variant, task=task, frozen_controls=controls(task), **kwargs)


def discovery_task(domain: str = "train") -> PublicTask:
    identity = DataIdentity("discoverybench", "discovery-q7", "group-a", "fixture-v1", "split", domain)
    return DiscoveryBenchAdapter().prepare(identity, {"task_id": "discovery-q7", "question": "Does the public question survive?",
        "difficulty": "fixture", "source_kind": "synthetic", "dataset": [{"name": "fixture", "description": "public", "columns": []}]})


def blade_task(domain: str = "train") -> PublicTask:
    identity = DataIdentity("blade", "blade-q7", "group-b", "fixture-v1", "split", domain)
    return BladeAdapter().prepare(identity, {"task_id": "blade-q7", "dataset_id": "fixture", "research_question": "Does BLADE public context survive?",
        "data_schema": [{"name": "outcome", "description": "fixture", "dtype": "number"}], "task_instructions": "fixture only"})


@pytest.mark.parametrize(("experiment_id", "variant"), [
    ("Q7.1", "low_cost"), ("Q7.1", "data_unknown"), ("Q7.1", "measurement_repair"), ("Q7.1", "valid_negative"), ("Q7.1", "conflict"),
    ("Q7.2", "deterministic"), ("Q7.2", "insufficient"), ("Q7.2", "value"),
    ("Q7.3", "zero"), ("Q7.3", "low"), ("Q7.3", "medium"), ("Q7.3", "high"),
    ("Q7.4", "invalid_measure"), ("Q7.4", "repair"), ("Q7.4", "old_evidence"),
    ("Q7.5", "valid_known"), ("Q7.5", "novel_refuted"), ("Q7.5", "infeasible"), ("Q7.5", "easy_valid"),
    ("Q7.6", "contract_only"), ("Q7.6", "real_counterexample"),
])
def test_all_registered_q7_variants_call_next_payload_on_both_public_adapter_forms(experiment_id: str, variant: str) -> None:
    for task in (discovery_task(), blade_task()):
        seen: list[FrozenRecord] = []
        result = run(experiment_id, variant, task, next_model=lambda payload: (seen.append(payload), {"received": payload.content_hash})[1])
        assert seen == [result.next_payload]
        body = seen[0].data()
        assert body["task"] == task.data()
        assert body["frozen_controls"]["task_digest"] == task.content_hash
        assert result.mechanism_trace.data()["events"][-1]["event"] == "next_model_invoked"
        assert result.next_model_response is not None


def test_q71_keeps_exploration_permission_and_evidence_admission_separate() -> None:
    task = discovery_task()
    low = run("Q7.1", "low_cost", task)
    negative = run("Q7.1", "valid_negative", task)
    unknown = run("Q7.1", "data_unknown", task)
    conflict = run("Q7.1", "conflict", task)
    assert low.next_payload.data()["scenario_auxiliary"]["exploration_allowed"] is True
    assert low.next_payload.data()["scenario_auxiliary"]["evidence_admitted"] is False
    assert negative.next_payload.data()["scenario_auxiliary"]["evidence_admitted"] is True
    assert unknown.next_payload.data()["scenario_auxiliary"]["m7_diagnostic"] is None
    assert conflict.next_payload.data()["scenario_auxiliary"]["enhanced_conflict_review"] is not None


def test_q72_distinguishes_hard_block_from_insufficiency_and_value_appeals() -> None:
    task = discovery_task()
    deterministic = run("Q7.2", "deterministic", task)
    insufficient = run("Q7.2", "insufficient", task)
    value = run("Q7.2", "value", task)
    assert deterministic.next_payload.data()["scenario_auxiliary"]["appeal_status"] == "requires_reassessment"
    assert insufficient.next_payload.data()["scenario_auxiliary"]["appeal_status"] == value.next_payload.data()["scenario_auxiliary"]["appeal_status"] == "diagnostic_permitted"


def test_q73_refuses_validation_before_iterating_score_rows() -> None:
    identity = discovery_task("validation").identity
    class ExplodesIfRead:
        def __iter__(self):
            raise AssertionError("validation score rows must not be read")
    with pytest.raises(ContractError, match="training provenance"):
        select_train_ratio(identity=identity, rows=ExplodesIfRead())  # type: ignore[arg-type]


def test_q73_full_scenario_rejects_validation_before_any_ratio_execution() -> None:
    task = discovery_task("validation")
    sidecar, broker = execution_root()
    with pytest.raises(ContractError, match="training provenance"):
        run_exploration_scenario("Q7.3", "low", task=task, frozen_controls=controls(task), sidecar=sidecar, broker=broker)
    assert not list(sidecar.iterdir())


def test_q73_selects_finite_train_ratio_and_never_places_score_rows_in_model_payload() -> None:
    task = blade_task()
    result = run("Q7.3", "medium", task)
    private = result.controller_record.data()["train_ratio_selection"]
    assert private["selected"]["ratio_id"] == "high"
    allocations = result.controller_record.data()["execution_allocations"]
    assert allocations[-1]["exploration_execution_units"] == 3
    assert allocations[-1]["main_task_execution_units"] == 1
    assert len(allocations[-1]["main_receipt_digests"]) == 1
    assert allocations[-1]["budget_after_main"]["execution_used"] == 4
    assert allocations[-1]["token_budget"] == "not_exercised"
    assert "candidates" not in result.next_payload.data()["scenario_auxiliary"]
    assert result.next_payload.data()["scenario_auxiliary"]["selection_scope"] == "train_only"


def test_q74_repair_never_resurrects_old_invalid_evidence() -> None:
    task = blade_task()
    repaired = run("Q7.4", "repair", task)
    aux = repaired.next_payload.data()["scenario_auxiliary"]
    assert aux["old_evidence_admitted"] is True
    assert aux["old_root_active_after_withdrawal"] is False
    assert aux["old_requires_new_execution"] is True
    assert aux["new_evidence_admitted"] is True


def test_q74_withdraws_previously_admitted_old_positive_and_negative_controls() -> None:
    task = blade_task()
    positive = run("Q7.4", "invalid_measure", task).next_payload.data()["scenario_auxiliary"]
    negative = run("Q7.4", "old_evidence", task).next_payload.data()["scenario_auxiliary"]
    assert positive["old_evidence_admitted"] is negative["old_evidence_admitted"] is True
    assert positive["old_root_active_after_withdrawal"] is negative["old_root_active_after_withdrawal"] is False
    assert positive["new_execution"] is negative["new_execution"] is None


def test_q75_preserves_four_dimensions_and_m2_relations() -> None:
    task = discovery_task()
    novel = run("Q7.5", "novel_refuted", task)
    easy = run("Q7.5", "easy_valid", task)
    assert novel.next_payload.data()["scenario_auxiliary"]["state"] == {"validity": "valid", "support": "refuted", "novelty": "known", "investment": "stop"}
    assert novel.next_payload.data()["scenario_auxiliary"]["claim_status"] == "refuted"
    assert novel.next_payload.data()["scenario_auxiliary"]["novelty_transition"] == {"before": "novel", "after": "known", "reason": "fixture prior-art withdrawal", "observation_root_retained": True}
    assert easy.next_payload.data()["scenario_auxiliary"]["active_root_count"] == 1


def test_q76_authentic_contract_admission_is_not_semantic_truth_and_callback_is_real() -> None:
    task, seen = blade_task(), []
    def reviewer(payload: FrozenRecord):
        seen.append(payload)
        return {"assessment": "unknown", "evidence_refs": ["contract-evidence"], "counterexamples": ["fixture-counterexample"], "uncertainty": "semantic relevance remains fixture-only"}
    result = run("Q7.6", "real_counterexample", task, review_model=reviewer)
    assert result.review_payloads == tuple(seen)
    assert result.next_payload.data()["scenario_auxiliary"]["contract_admitted"] is True
    review_payload = seen[0].data()
    assert {"theory", "construct", "observation"} <= set(review_payload)
    assert result.next_payload.data()["scenario_auxiliary"]["review_response"]["counterexamples"] == ["fixture-counterexample"]
    assert result.controller_record.data()["semantic_fixture_truth"] == "counterexample_hits_theory"
    assert "semantic_fixture_truth" not in result.next_payload.encoded


def test_closed_controls_reject_task_drift() -> None:
    task = discovery_task()
    wrong = FrozenRecord.from_dict({"task_digest": "other", "budget_digest": "fixture-budget", "fixture_only": True})
    with pytest.raises(ContractError, match="matching closed"):
        run_exploration_scenario("Q7.1", "low_cost", task=task, frozen_controls=wrong)
