import hashlib
import json
from dataclasses import replace

import pytest

from research_loop.agent import Agent, DEFAULT_CRITERIA
from research_loop.cli import toy_task
from research_loop.evaluate import evaluate
from research_loop.ontology import ContractError, Task, canonical
from research_loop.provider import FixtureProvider
from research_loop.store import Store


@pytest.fixture
def system(tmp_path):
    store = Store(tmp_path / "state.sqlite")
    agent = Agent(store)
    agent.initialize()
    yield agent
    store.close()


class Modified(FixtureProvider):
    def __init__(self, change):
        self.change = change
        self.seen = []

    def call(self, role, payload):
        self.seen.append((role, payload))
        response = super().call(role, payload)
        return replace(response, value=self.change(role, response.value))


def develop(agent, backend=None):
    backend = backend or FixtureProvider()
    agent.enqueue(Task.parse(toy_task("D1", "dev")))
    run = agent.run_next(backend)
    candidate = agent.propose(run["id"], backend, proposer="proposer")
    return run, candidate


def freeze(agent, candidate, tmp_path, **criteria):
    tasks = [Task.parse(toy_task("E1", "family-a")), Task.parse(toy_task("E2", "family-b"))]
    labels = tmp_path / "private-labels.json"
    labels.write_text(canonical({"E1": "closed_negative", "E2": "closed_negative"}), encoding="utf-8")
    trial = agent.freeze_trial(
        candidate, tasks, {**DEFAULT_CRITERIA, "min_pairs": 2, **criteria}, evaluator="evaluator",
        label_commitment=hashlib.sha256(labels.read_bytes()).hexdigest())
    return trial, labels


def test_persistent_learning_trial_promotion_and_rollback(system, tmp_path):
    base = system.version()["id"]
    before, candidate = develop(system)
    assert before["status"] == "proceed"
    assert system.version()["id"] == base  # Proposal has no deployment authority.
    trial, labels = freeze(system, candidate, tmp_path)
    system.run_trial(trial, FixtureProvider())
    receipt = evaluate(system.store, trial, labels)
    assert receipt["eligible"]
    assert receipt["metrics"]["baseline"]["errors"] == 2
    assert receipt["metrics"]["candidate"]["errors"] == 0
    assert receipt["evidence_level"] == "engineering_fixture"
    assert receipt["scientific_effectiveness_proven"] is False
    system.promote(trial, reviewer="reviewer")
    system.enqueue(Task.parse(toy_task("D2", "new-development")))
    after = system.run_next(FixtureProvider())
    assert after["status"] == "closed_negative"
    assert after["audit_valid"] is True and after["evidence_admitted"] is True
    assert after["lesson_ids"]
    assert system.rollback(reviewer="reviewer", reason="operator rollback") == base
    reopened = Store(tmp_path / "state.sqlite")
    try:
        assert Agent(reopened).version()["id"] == base
        assert len(reopened.all("run")) == 6
        assert reopened.verify_journal() > 0
    finally:
        reopened.close()


def test_fifo_and_prerequisite_gate_avoid_model_calls(system):
    first = toy_task("first", "one")
    first["prerequisites"]["valid_comparison"] = False
    system.enqueue(Task.parse(first))
    system.enqueue(Task.parse(toy_task("second", "two")))
    backend = Modified(lambda role, value: value)
    held = system.run_next(backend)
    assert held["task"]["id"] == "first"
    assert held["status"] == "withdrawn" and held["usage"]["calls"] == 0
    assert held["audit_valid"] is None and not held["evidence_admitted"]
    assert backend.seen == []
    assert system.run_next(backend)["task"]["id"] == "second"
    assert system.run_next(backend) is None


@pytest.mark.parametrize("change", [
    lambda x: x.update({"rule_hash": "changed-after-observation"}),
    lambda x: x.update({"status": "complete"}),
    lambda x: x.update({"declared_program_complete": "false"}),
    lambda x: x.update({"reason": "The programme is complete"}),
    lambda x: x.update({"evidence_ids": ["invented-observation"]}),
    lambda x: x.update({"gold_status": "proceed"}),
])
def test_bad_executor_never_reaches_evidence_store_or_auditors(system, change):
    def mutate(role, value):
        if role == "executor":
            change(value)
        return value
    backend = Modified(mutate)
    system.enqueue(Task.parse(toy_task("bad", "bad")))
    run = system.run_next(backend)
    assert run["status"] == "invalid" and not run["evidence_admitted"]
    assert run["decision"] is None
    assert [role for role, _ in backend.seen] == ["executor"]


@pytest.mark.parametrize("case", ["missing", "duplicate", "string_false", "integer_true", "extra", "unknown_ref"])
def test_audit_requires_complete_unique_typed_checks(system, case):
    def mutate(role, value):
        if role == "auditor_1":
            checks = value["checks"]
            if case == "missing":
                checks.pop()
            elif case == "duplicate":
                checks[-1] = dict(checks[0])
            elif case == "string_false":
                checks[0]["pass"] = "false"
            elif case == "integer_true":
                checks[0]["pass"] = 1
            elif case == "extra":
                value["status"] = "proceed"
            else:
                checks[0]["evidence_ids"] = ["unknown"]
        return value
    system.enqueue(Task.parse(toy_task("audit", "audit")))
    run = system.run_next(Modified(mutate))
    assert run["status"] == "invalid"
    assert not run["evidence_admitted"]
    assert run["protocol_violations"] == ["contract_rejected:auditor_1"]


def test_auditors_disagreeing_on_individual_facts_are_rejected(system):
    def mutate(role, value):
        if role == "auditor_1":
            value["checks"][0]["pass"] = False
        if role == "auditor_2":
            value["checks"][1]["pass"] = False
        return value
    backend = Modified(mutate)
    system.enqueue(Task.parse(toy_task("disagree", "disagree")))
    run = system.run_next(backend)
    assert run["audit_valid"] is False
    assert not run["evidence_admitted"]
    assert "audit_failed_or_disagreed" in run["protocol_violations"]
    assert all("lessons" not in payload and "audits" not in payload
               for role, payload in backend.seen if role.startswith("auditor"))


def test_lessons_cannot_cross_scope_or_rule_boundary(system):
    _, candidate = develop(system)
    for index, field in enumerate(("scope", "rule")):
        data = toy_task(f"different-{index}", f"other-{index}")
        if field == "scope":
            data["scope"] = data["evidence"][0]["scope"] = "different.scope"
        else:
            data["rule"] += " New version."
        result = system.execute(Task.parse(data), candidate, FixtureProvider(),
                                phase="development", run_id=f"direct-{index}")
        assert not result["lesson_ids"]
        assert result["status"] == "proceed"


def test_ontology_rejects_mismatched_evidence_scope_and_private_nested_fields():
    data = toy_task("bad", "bad")
    data["evidence"][0]["scope"] = "another.scope"
    with pytest.raises(ContractError, match="scope"):
        Task.parse(data)
    data = toy_task("bad", "bad")
    data["evidence"][0]["content"] = '{"gold_reason":"hidden"}'
    with pytest.raises(ContractError, match="private"):
        Task.parse(data)
    data = toy_task("bad", "bad")
    data["prerequisites"]["valid_comparison"] = "false"
    with pytest.raises(ContractError, match="booleans"):
        Task.parse(data)


def test_evaluation_cannot_become_reflection_or_development(system, tmp_path):
    _, candidate = develop(system)
    trial, _ = freeze(system, candidate, tmp_path)
    results = system.run_trial(trial, FixtureProvider())
    with pytest.raises(ContractError, match="development"):
        system.propose(results[0]["id"], FixtureProvider(), proposer="proposer")
    with pytest.raises(ContractError, match="evaluation"):
        system.enqueue(Task.parse(toy_task("later", "family-a")))


def test_trial_blocks_development_overlap_and_previously_used_families(system, tmp_path):
    _, candidate = develop(system)
    tasks = [Task.parse(toy_task("E1", "dev")), Task.parse(toy_task("E2", "new"))]
    with pytest.raises(ContractError, match="already used"):
        system.freeze_trial(candidate, tasks, {**DEFAULT_CRITERIA, "min_pairs": 2},
                            evaluator="evaluator", label_commitment="a" * 64)
    trial, _ = freeze(system, candidate, tmp_path)
    with pytest.raises(ContractError, match="already used"):
        system.freeze_trial(candidate, [Task.parse(t) for t in system.trial(trial)["tasks"]],
                            {**DEFAULT_CRITERIA, "min_pairs": 2},
                            evaluator="evaluator", label_commitment="a" * 64)


def test_renaming_task_and_family_cannot_hide_exact_content_reuse(system):
    _, candidate = develop(system)
    disguised = toy_task("D1", "dev")
    disguised["id"], disguised["family"] = "renamed", "unseen"
    with pytest.raises(ContractError, match="already used"):
        system.freeze_trial(candidate, [Task.parse(disguised), Task.parse(toy_task("E2", "second"))],
                            {**DEFAULT_CRITERIA, "min_pairs": 2},
                            evaluator="evaluator", label_commitment="a" * 64)


def test_precommitted_labels_cannot_change_after_results(system, tmp_path):
    _, candidate = develop(system)
    trial, labels = freeze(system, candidate, tmp_path)
    system.run_trial(trial, FixtureProvider())
    labels.write_text(canonical({"E1": "proceed", "E2": "proceed"}), encoding="utf-8")
    with pytest.raises(ContractError, match="changed after"):
        evaluate(system.store, trial, labels)
    with pytest.raises(ContractError, match="missing evaluation"):
        system.promote(trial, reviewer="reviewer")


def test_failed_gate_and_role_conflicts_prevent_promotion(system, tmp_path):
    _, candidate = develop(system)
    trial, labels = freeze(system, candidate, tmp_path, max_call_ratio=0.5)
    system.run_trial(trial, FixtureProvider())
    receipt = evaluate(system.store, trial, labels)
    assert receipt["checks"]["fewer_errors"] and not receipt["checks"]["call_budget"]
    with pytest.raises(ContractError, match="separate"):
        system.promote(trial, reviewer="proposer")
    with pytest.raises(ContractError, match="separate"):
        system.promote(trial, reviewer="evaluator")
    with pytest.raises(ContractError, match="did not pass"):
        system.promote(trial, reviewer="reviewer")


def test_trial_restarts_reuse_sealed_runs_and_reject_backend_changes(system, tmp_path):
    _, candidate = develop(system)
    trial, _ = freeze(system, candidate, tmp_path)
    backend = Modified(lambda role, value: value)
    assert len(system.run_trial(trial, backend)) == 4
    calls = len(backend.seen)
    assert len(system.run_trial(trial, backend)) == 4
    assert len(backend.seen) == calls
    backend.identity = "another-model"
    with pytest.raises(ContractError, match="configuration changed"):
        system.run_trial(trial, backend)


def test_backend_failure_records_unknown_usage_without_fabrication(system):
    class Broken(FixtureProvider):
        def call(self, role, payload):
            raise RuntimeError("secret-api-key must never reach the journal")
    system.enqueue(Task.parse(toy_task("network", "network")))
    run = system.run_next(Broken())
    assert run["state"] == "failed" and run["decision"] is None
    assert run["usage"]["calls"] == 1
    assert run["usage"]["input_tokens"] is None
    assert not run["usage"]["complete"]
    assert "secret-api-key" not in canonical(system.store.all("run"))
    with pytest.raises(ContractError, match="completed development"):
        system.propose(run["id"], Broken(), proposer="proposer")


def test_interrupted_fifo_requires_explicit_recovery(system):
    system.enqueue(Task.parse(toy_task("one", "one")))
    system.enqueue(Task.parse(toy_task("two", "two")))
    system.store.db.execute("UPDATE queue SET state='running',run_id='interrupted' WHERE task_id='one'")
    with pytest.raises(ContractError, match="recover"):
        system.run_next(FixtureProvider())
    system.recover("interrupted")
    assert system.run_next(FixtureProvider())["task"]["id"] == "two"


def test_tampered_version_trial_run_and_receipt_are_detected(system, tmp_path):
    run, candidate = develop(system)
    body = system.store.get("version", candidate)
    body["lessons"][0]["instruction"] = "edited"
    system.store.db.execute("UPDATE objects SET body=? WHERE kind='version' AND id=?", (canonical(body), candidate))
    with pytest.raises(ContractError, match="version content"):
        system.version(candidate)
    # Restoring the original source preserves the test's remaining independent boundary.
    original = {**body, "lessons": [{**body["lessons"][0], "instruction":
                "保留有效阴性：negative observation 应依锁定规则关闭假说，不能写成支持。"}]}
    system.store.db.execute("UPDATE objects SET body=? WHERE kind='version' AND id=?", (canonical(original), candidate))
    trial, labels = freeze(system, candidate, tmp_path)
    runs = system.run_trial(trial, FixtureProvider())
    receipt = evaluate(system.store, trial, labels)
    receipt["eligible"] = False
    system.store.db.execute("UPDATE objects SET body=? WHERE kind='evaluation' AND id=?", (canonical(receipt), trial))
    with pytest.raises(ContractError, match="sealed record"):
        system.promote(trial, reviewer="reviewer")
    modified = {**runs[0], "status": "withdrawn"}
    system.store.db.execute("UPDATE objects SET body=? WHERE kind='run' AND id=?", (canonical(modified), modified["id"]))
    with pytest.raises(ContractError, match="sealed record"):
        evaluate(system.store, trial, labels)


def test_journal_detects_accidental_edits(system):
    system.store.db.execute("UPDATE events SET body=? WHERE seq=1", (json.dumps({"edited": True}),))
    with pytest.raises(ContractError, match="journal"):
        system.store.verify_journal()
