import hashlib
import json
from dataclasses import replace

import pytest

from research_loop.agent import Agent, DEFAULT_CRITERIA, version_id
from research_loop.cli import toy_task
from research_loop.evaluate import evaluate
from research_loop.ontology import (
    ContractError, Task, canonical, code_version_hash, digest, implementation_hash,
)
from research_loop.provider import FixtureProvider, fixture_role_providers
from research_loop.store import Store

# One fixture provider per role; identities are pairwise distinct so every run passes
# the fail-closed audit-independence gate. The providers are stateless.
EXECUTOR, AUDITOR_1, AUDITOR_2 = fixture_role_providers()


@pytest.fixture
def system(tmp_path):
    store = Store(tmp_path / "state.sqlite")
    agent = Agent(store)
    agent.initialize()
    yield agent
    store.close()


class Modified(FixtureProvider):
    def __init__(self, change, identity=None):
        super().__init__(identity)
        self.change = change
        self.seen = []

    def call(self, role, payload):
        self.seen.append((role, payload))
        response = super().call(role, payload)
        return replace(response, value=self.change(role, response.value))


def develop(agent, backend=None):
    backend = backend or EXECUTOR
    agent.enqueue(Task.parse(toy_task("D1", "dev")))
    run = agent.run_next(backend, auditor_provider=AUDITOR_1, auditor2_provider=AUDITOR_2)
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
    system.run_trial(trial, EXECUTOR, auditor_provider=AUDITOR_1, auditor2_provider=AUDITOR_2)
    receipt = evaluate(system.store, trial, labels)
    assert receipt["eligible"]
    assert receipt["metrics"]["baseline"]["errors"] == 2
    assert receipt["metrics"]["candidate"]["errors"] == 0
    assert receipt["evidence_level"] == "engineering_fixture"
    assert receipt["scientific_effectiveness_proven"] is False
    system.promote(trial, reviewer="reviewer")
    system.enqueue(Task.parse(toy_task("D2", "new-development")))
    after = system.run_next(EXECUTOR, auditor_provider=AUDITOR_1, auditor2_provider=AUDITOR_2)
    assert after["status"] == "closed_negative"
    assert after["audit_valid"] is True and after["evidence_admitted"] is True
    assert after["lesson_ids"]
    # Rollback is fail-closed: only an explicitly authorized approver may deploy it.
    assert Agent(system.store, approvers=["reviewer"]).rollback(
        reviewer="reviewer", reason="operator rollback") == base
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
    held = system.run_next(backend, auditor_provider=AUDITOR_1, auditor2_provider=AUDITOR_2)
    assert held["task"]["id"] == "first"
    assert held["status"] == "withdrawn" and held["usage"]["calls"] == 0
    assert held["audit_valid"] is None and not held["evidence_admitted"]
    assert backend.seen == []
    assert system.run_next(backend, auditor_provider=AUDITOR_1,
                           auditor2_provider=AUDITOR_2)["task"]["id"] == "second"
    assert system.run_next(backend, auditor_provider=AUDITOR_1, auditor2_provider=AUDITOR_2) is None


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
    run = system.run_next(backend, auditor_provider=AUDITOR_1, auditor2_provider=AUDITOR_2)
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
    run = system.run_next(EXECUTOR, auditor_provider=Modified(mutate, AUDITOR_1.identity),
                          auditor2_provider=AUDITOR_2)
    assert run["status"] == "invalid"
    assert not run["evidence_admitted"]
    assert run["protocol_violations"] == ["contract_rejected:auditor_1"]


def test_auditors_disagreeing_on_individual_facts_are_rejected(system):
    def disagree_first(role, value):
        if role == "auditor_1":
            value["checks"][0]["pass"] = False
        return value

    def disagree_second(role, value):
        if role == "auditor_2":
            value["checks"][1]["pass"] = False
        return value

    first = Modified(disagree_first, AUDITOR_1.identity)
    second = Modified(disagree_second, AUDITOR_2.identity)
    system.enqueue(Task.parse(toy_task("disagree", "disagree")))
    run = system.run_next(EXECUTOR, auditor_provider=first, auditor2_provider=second)
    assert run["audit_valid"] is False
    assert not run["evidence_admitted"]
    assert "audit_failed_or_disagreed" in run["protocol_violations"]
    seen = [*first.seen, *second.seen]
    assert all("lessons" not in payload and "audits" not in payload
               for role, payload in seen if role.startswith("auditor"))


def test_lessons_cannot_cross_scope_or_rule_boundary(system):
    _, candidate = develop(system)
    for index, field in enumerate(("scope", "rule")):
        data = toy_task(f"different-{index}", f"other-{index}")
        if field == "scope":
            data["scope"] = data["evidence"][0]["scope"] = "different.scope"
        else:
            data["rule"] += " New version."
        result = system.execute(Task.parse(data), candidate, EXECUTOR, phase="development",
                                run_id=f"direct-{index}", auditor_provider=AUDITOR_1,
                                auditor2_provider=AUDITOR_2)
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
    results = system.run_trial(trial, EXECUTOR, auditor_provider=AUDITOR_1, auditor2_provider=AUDITOR_2)
    with pytest.raises(ContractError, match="development"):
        system.propose(results[0]["id"], EXECUTOR, proposer="proposer")
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
    system.run_trial(trial, EXECUTOR, auditor_provider=AUDITOR_1, auditor2_provider=AUDITOR_2)
    labels.write_text(canonical({"E1": "proceed", "E2": "proceed"}), encoding="utf-8")
    with pytest.raises(ContractError, match="changed after"):
        evaluate(system.store, trial, labels)
    with pytest.raises(ContractError, match="missing evaluation"):
        system.promote(trial, reviewer="reviewer")


def test_failed_gate_and_role_conflicts_prevent_promotion(system, tmp_path):
    _, candidate = develop(system)
    trial, labels = freeze(system, candidate, tmp_path, max_call_ratio=0.5)
    system.run_trial(trial, EXECUTOR, auditor_provider=AUDITOR_1, auditor2_provider=AUDITOR_2)
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
    assert len(system.run_trial(trial, backend, auditor_provider=AUDITOR_1,
                                auditor2_provider=AUDITOR_2)) == 4
    calls = len(backend.seen)
    assert len(system.run_trial(trial, backend, auditor_provider=AUDITOR_1,
                                auditor2_provider=AUDITOR_2)) == 4
    assert len(backend.seen) == calls
    backend.identity = "another-model"
    with pytest.raises(ContractError, match="configuration changed"):
        system.run_trial(trial, backend, auditor_provider=AUDITOR_1, auditor2_provider=AUDITOR_2)


def test_backend_failure_records_unknown_usage_without_fabrication(system):
    class Broken(FixtureProvider):
        def call(self, role, payload):
            raise RuntimeError("secret-api-key must never reach the journal")
    system.enqueue(Task.parse(toy_task("network", "network")))
    run = system.run_next(Broken(), auditor_provider=AUDITOR_1, auditor2_provider=AUDITOR_2)
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
        system.run_next(EXECUTOR, auditor_provider=AUDITOR_1, auditor2_provider=AUDITOR_2)
    system.recover("interrupted")
    assert system.run_next(EXECUTOR, auditor_provider=AUDITOR_1,
                           auditor2_provider=AUDITOR_2)["task"]["id"] == "two"


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
    runs = system.run_trial(trial, EXECUTOR, auditor_provider=AUDITOR_1, auditor2_provider=AUDITOR_2)
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


def _reindex_trial(store, trial_key, mutate):
    """Simulate an operator rewriting a trial record and recomputing its content address.

    The objects table key is the record id, so a real re-hash moves the storage key too;
    the helper returns the new trial id for downstream reuse attempts.
    """
    record = store.get("trial", trial_key)
    mutate(record)
    record["id"] = digest({k: v for k, v in record.items() if k != "id"})
    store.db.execute("UPDATE objects SET id=?, body=? WHERE kind='trial' AND id=?",
                     (record["id"], canonical(record), trial_key))
    return record["id"]


def test_trial_records_task_rule_and_label_commitments(system, tmp_path):
    _, candidate = develop(system)
    trial, labels = freeze(system, candidate, tmp_path)
    record = system.trial(trial)
    tasks = [Task.parse(t) for t in record["tasks"]]
    assert record["task_commitments"] == [
        {"id": t.id, "task_hash": digest(t.data()), "rule_hash": t.rule_hash, "fingerprint": t.fingerprint}
        for t in tasks]
    assert record["label_commitment"] == hashlib.sha256(labels.read_bytes()).hexdigest()
    assert record["code_version_hash"] == code_version_hash()
    frozen = system.store.last_event("trial_frozen", trial=trial)
    assert frozen["task_commitments"] == record["task_commitments"]
    assert frozen["label_commitment"] == record["label_commitment"]
    # The freeze event anchors every commitment, not only tasks and labels.
    assert frozen["criteria"] == record["criteria"]
    assert frozen["evaluator"] == record["evaluator"] == "evaluator"
    assert frozen["core_hash"] == record["core_hash"]
    assert frozen["code_version_hash"] == record["code_version_hash"] == code_version_hash()


def test_tampered_trial_record_is_rejected(system, tmp_path):
    _, candidate = develop(system)
    trial, _ = freeze(system, candidate, tmp_path)
    record = system.store.get("trial", trial)
    record["tasks"][0]["rule"] += " Edited in place."
    system.store.db.execute("UPDATE objects SET body=? WHERE kind='trial' AND id=?", (canonical(record), trial))
    with pytest.raises(ContractError, match="frozen trial changed"):
        system.run_trial(trial, EXECUTOR, auditor_provider=AUDITOR_1, auditor2_provider=AUDITOR_2)


def test_reindexed_trial_cannot_change_task_or_rule_commitments(system, tmp_path):
    _, candidate = develop(system)
    trial, labels = freeze(system, candidate, tmp_path)
    forged = _reindex_trial(system.store, trial,
                            lambda r: r["tasks"][0].update(rule=r["tasks"][0]["rule"] + " Rewritten after the freeze."))
    with pytest.raises(ContractError, match="commitment"):
        system.run_trial(forged, EXECUTOR, auditor_provider=AUDITOR_1, auditor2_provider=AUDITOR_2)
    # The evaluation path hits the same checkpoint before any scoring happens.
    with pytest.raises(ContractError, match="commitment"):
        evaluate(system.store, forged, labels)


def test_reindexed_trial_cannot_rewind_commitments_behind_the_journal(system, tmp_path):
    _, candidate = develop(system)
    trial, _ = freeze(system, candidate, tmp_path)

    def forge_everything(record):
        record["tasks"][0]["rule"] += " Rewritten after the freeze."
        task = Task.parse(record["tasks"][0])
        record["task_commitments"][0] = {"id": task.id, "task_hash": digest(task.data()),
                                         "rule_hash": task.rule_hash, "fingerprint": task.fingerprint}
    forged = _reindex_trial(system.store, trial, forge_everything)
    with pytest.raises(ContractError, match="freeze event"):
        system.run_trial(forged, EXECUTOR, auditor_provider=AUDITOR_1, auditor2_provider=AUDITOR_2)


def test_reindexed_trial_cannot_change_label_commitment(system, tmp_path):
    _, candidate = develop(system)
    trial, _ = freeze(system, candidate, tmp_path)
    forged = _reindex_trial(system.store, trial, lambda r: r.update(label_commitment="e" * 64))
    with pytest.raises(ContractError, match="freeze event"):
        system.run_trial(forged, EXECUTOR, auditor_provider=AUDITOR_1, auditor2_provider=AUDITOR_2)


def test_runtime_upgrade_marks_old_versions_and_trials_stale(system, tmp_path, monkeypatch):
    from research_loop import agent as agent_module
    _, candidate = develop(system)
    trial, labels = freeze(system, candidate, tmp_path)
    system.run_trial(trial, EXECUTOR, auditor_provider=AUDITOR_1, auditor2_provider=AUDITOR_2)
    evaluate(system.store, trial, labels)
    monkeypatch.setattr(agent_module, "code_version_hash", lambda: "0" * 64)
    with pytest.raises(ContractError, match="stale version"):
        system.version()  # the active policy is not silently reused after the upgrade
    with pytest.raises(ContractError, match="stale version"):
        system.version(candidate)
    with pytest.raises(ContractError, match="stale trial"):
        system.trial(trial)
    with pytest.raises(ContractError, match="stale trial"):
        system.run_trial(trial, EXECUTOR, auditor_provider=AUDITOR_1, auditor2_provider=AUDITOR_2)
    with pytest.raises(ContractError, match="stale trial"):
        system.promote(trial, reviewer="reviewer")


def test_forged_receipt_without_independent_seal_cannot_promote(system, tmp_path):
    _, candidate = develop(system)
    trial, _ = freeze(system, candidate, tmp_path)
    system.run_trial(trial, EXECUTOR, auditor_provider=AUDITOR_1, auditor2_provider=AUDITOR_2)
    forged = {"trial": trial, "trial_hash": digest(system.trial(trial)), "run_hashes": {},
              "metrics": {}, "checks": {}, "eligible": True, "evaluator": "evaluator",
              "provider": "fixture:negative-result-v1", "evidence_level": "engineering_fixture",
              "scientific_effectiveness_proven": False}
    system.store.put("evaluation", trial, forged)  # never produced by the evaluator subprocess
    with pytest.raises(ContractError, match="no completion seal"):
        system.promote(trial, reviewer="reviewer")
    assert system.version()["id"] != candidate


# --- propose quality gates: only fully completed protocols become lessons ---------

def test_propose_rejects_runs_without_a_decision(system):
    # A prerequisite-gated run closes without any model decision at all.
    data = toy_task("held", "held")
    data["prerequisites"]["valid_comparison"] = False
    system.enqueue(Task.parse(data))
    run = system.run_next(EXECUTOR, auditor_provider=AUDITOR_1, auditor2_provider=AUDITOR_2)
    assert run["state"] == "closed" and run["decision"] is None and run["status"] == "withdrawn"
    with pytest.raises(ContractError, match="no decision"):
        system.propose(run["id"], EXECUTOR, proposer="proposer")


def test_propose_rejects_contract_rejected_runs(system):
    # state == "closed" but the protocol rejected the executor output: no decision,
    # no audit, status invalid. None of that failure may become memory.
    def break_executor(role, value):
        if role == "executor":
            value["rule_hash"] = "changed-after-observation"
        return value
    system.enqueue(Task.parse(toy_task("rejected", "rejected")))
    run = system.run_next(Modified(break_executor), auditor_provider=AUDITOR_1,
                          auditor2_provider=AUDITOR_2)
    assert run["state"] == "closed" and run["status"] == "invalid"
    assert run["decision"] is None and run["evidence_admitted"] is False
    with pytest.raises(ContractError, match="no decision"):
        system.propose(run["id"], EXECUTOR, proposer="proposer")


def test_propose_rejects_runs_whose_double_audit_failed(system):
    # A decision exists, but the two auditors disagreed: audit_valid False.
    def disagree(role, value):
        if role == "auditor_1":
            value["checks"][0]["pass"] = False
        return value
    system.enqueue(Task.parse(toy_task("audit-fail", "audit-fail")))
    run = system.run_next(EXECUTOR, auditor_provider=Modified(disagree, AUDITOR_1.identity),
                          auditor2_provider=AUDITOR_2)
    assert run["state"] == "closed" and run["audit_valid"] is False and run["decision"] is not None
    with pytest.raises(ContractError, match="audit is not valid"):
        system.propose(run["id"], EXECUTOR, proposer="proposer")


def test_propose_rejects_withdrawn_status_even_when_audits_pass(system):
    def withdraw(role, value):
        if role == "executor":
            value["status"] = "withdrawn"
        return value
    system.enqueue(Task.parse(toy_task("withdrawn", "withdrawn")))
    run = system.run_next(Modified(withdraw), auditor_provider=AUDITOR_1, auditor2_provider=AUDITOR_2)
    assert run["state"] == "closed" and run["decision"] is not None and run["audit_valid"] is True
    assert run["status"] == "withdrawn" and run["evidence_admitted"] is False
    with pytest.raises(ContractError, match="status does not admit lessons"):
        system.propose(run["id"], EXECUTOR, proposer="proposer")


def test_propose_rejects_runs_without_admitted_evidence(system):
    # Defense in depth: execute() forces evidence_admitted from audit+status, so the
    # only way to reach this gate is a forged-but-sealed record; it must still be
    # refused instead of silently recycled into memory.
    task = Task.parse(toy_task("D1", "dev"))
    run = {"id": "dev-forged-evidence", "task": task.data(), "task_hash": digest(task.data()),
           "version": system.version()["id"], "phase": "development",
           "provider": FixtureProvider().identity, "state": "closed", "status": "proceed",
           "decision": {"status": "proceed", "rule_hash": task.rule_hash, "evidence_ids": ["obs"],
                        "reason": "fixture record", "declared_program_complete": False},
           "audit_valid": True, "evidence_admitted": False, "protocol_violations": [],
           "lesson_ids": [], "usage": {"calls": 3, "complete": True, "input_chars": 10,
                                       "input_tokens": 1, "output_tokens": 1, "elapsed_s": 0.0}}
    system.store.put("run", run["id"], run)
    system.store.event("run_closed", {"run_id": run["id"], "record_hash": digest(run)})
    with pytest.raises(ContractError, match="evidence was not admitted"):
        system.propose(run["id"], EXECUTOR, proposer="proposer")


def test_propose_accepts_proceed_and_closed_negative_runs(system, tmp_path):
    _, candidate = develop(system)  # a normal "proceed" development run proposes fine
    assert len(system.version(candidate)["lessons"]) == 1
    trial, labels = freeze(system, candidate, tmp_path)
    system.run_trial(trial, EXECUTOR, auditor_provider=AUDITOR_1, auditor2_provider=AUDITOR_2)
    assert evaluate(system.store, trial, labels)["eligible"]
    system.promote(trial, reviewer="reviewer")
    system.enqueue(Task.parse(toy_task("D2", "new-development")))
    negative = system.run_next(EXECUTOR, auditor_provider=AUDITOR_1, auditor2_provider=AUDITOR_2)
    assert negative["status"] == "closed_negative" and negative["evidence_admitted"] is True
    candidate2 = system.propose(negative["id"], EXECUTOR, proposer="proposer")
    assert len(system.version(candidate2)["lessons"]) == 2


# --- trial commitments: criteria/evaluator are anchored into the hash chain -------

def test_reindexed_trial_cannot_change_criteria_or_evaluator(system, tmp_path):
    _, candidate = develop(system)
    trial, _ = freeze(system, candidate, tmp_path)
    original = system.store.get("trial", trial)

    def forge(mutate):
        # Each re-hash moves the storage key, so every forgery starts from a copy
        # of the originally frozen record and is re-keyed like an operator would.
        record = json.loads(canonical(original))
        mutate(record)
        record["id"] = digest({k: v for k, v in record.items() if k != "id"})
        system.store.put("trial", record["id"], record)
        return record["id"]

    forged_criteria = forge(lambda r: r["criteria"].update(min_pairs=1))
    with pytest.raises(ContractError, match="freeze event"):
        system.trial(forged_criteria)
    forged_evaluator = forge(lambda r: r.update(evaluator="other-evaluator"))
    with pytest.raises(ContractError, match="freeze event"):
        system.trial(forged_evaluator)
    with pytest.raises(ContractError, match="freeze event"):
        system.run_trial(forged_evaluator, EXECUTOR, auditor_provider=AUDITOR_1,
                         auditor2_provider=AUDITOR_2)


# --- task bindings: scientific scope of tasks and lessons -------------------------

def bound_task(key, family, bindings):
    data = toy_task(key, family)
    data["bindings"] = bindings
    return Task.parse(data)


def test_task_bindings_parse_default_and_roundtrip():
    assert Task.parse(toy_task("T1", "f")).bindings == {}  # legacy tasks stay unbound
    data = toy_task("T2", "f")
    data["bindings"] = {"compound": "aspirin", "condition": "ph7"}
    task = Task.parse(data)
    assert task.bindings == {"compound": "aspirin", "condition": "ph7"}
    assert task.data()["bindings"] == {"compound": "aspirin", "condition": "ph7"}
    assert Task.parse(task.data()) == task  # data() round-trips the binding


def test_task_bindings_reject_non_mapping_and_invalid_identifiers():
    data = toy_task("T3", "f")
    data["bindings"] = ["compound:aspirin"]
    with pytest.raises(ContractError, match="mapping"):
        Task.parse(data)
    data = toy_task("T4", "f")
    data["bindings"] = {"bad key!": "aspirin"}
    with pytest.raises(ContractError, match="binding"):
        Task.parse(data)
    data = toy_task("T5", "f")
    data["bindings"] = {"compound": "bad value!"}
    with pytest.raises(ContractError, match="binding"):
        Task.parse(data)
    data = toy_task("T6", "f")
    data["bindings"] = {"compound": "aspirin"}
    data["unknown_extra"] = "x"
    with pytest.raises(ContractError, match="fields"):
        Task.parse(data)


def test_task_fingerprint_and_hash_follow_bindings():
    plain = Task.parse(toy_task("T1", "f"))
    aspirin = bound_task("T1", "f", {"compound": "aspirin"})
    ibuprofen = bound_task("T1", "f", {"compound": "ibuprofen"})
    assert len({plain.fingerprint, aspirin.fingerprint, ibuprofen.fingerprint}) == 3
    assert bound_task("T1", "f", {"compound": "aspirin"}).fingerprint == aspirin.fingerprint
    assert digest(aspirin.data()) != digest(plain.data())  # task_hash covers bindings too


def test_lessons_do_not_cross_binding_boundaries(system):
    system.enqueue(bound_task("D1", "dev", {"compound": "aspirin"}))
    run = system.run_next(EXECUTOR, auditor_provider=AUDITOR_1, auditor2_provider=AUDITOR_2)
    candidate = system.propose(run["id"], EXECUTOR, proposer="proposer")
    lesson = system.version(candidate)["lessons"][0]
    assert lesson["bindings"] == {"compound": "aspirin"}
    other = system.execute(bound_task("D2", "other", {"compound": "ibuprofen"}), candidate,
                           EXECUTOR, phase="development", run_id="bound-other",
                           auditor_provider=AUDITOR_1, auditor2_provider=AUDITOR_2)
    unbound = system.execute(Task.parse(toy_task("D3", "third")), candidate,
                             EXECUTOR, phase="development", run_id="unbound",
                             auditor_provider=AUDITOR_1, auditor2_provider=AUDITOR_2)
    same = system.execute(bound_task("D4", "fourth", {"compound": "aspirin"}), candidate,
                          EXECUTOR, phase="development", run_id="bound-same",
                          auditor_provider=AUDITOR_1, auditor2_provider=AUDITOR_2)
    assert not other["lesson_ids"] and not unbound["lesson_ids"]  # fail closed
    assert same["lesson_ids"] == [lesson["id"]]


def test_legacy_lessons_without_bindings_only_serve_unbound_tasks(system):
    base = system.version()
    legacy = {"scope": "toy.assay", "rule_hash": Task.parse(toy_task("X", "f")).rule_hash,
              "id": "legacy-lesson",
              "instruction": "保留有效阴性：negative observation 应依锁定规则关闭假说。"}
    version = {"parent": base["id"], "core_hash": implementation_hash(),
               "code_version_hash": code_version_hash(), "lessons": [legacy],
               "proposer": "controller", "source_run": None}
    version["id"] = version_id(version)
    system.store.put("version", version["id"], version)
    unbound = system.execute(Task.parse(toy_task("U1", "u")), version["id"], EXECUTOR,
                             phase="development", run_id="legacy-unbound",
                             auditor_provider=AUDITOR_1, auditor2_provider=AUDITOR_2)
    bound = system.execute(bound_task("U2", "u2", {"compound": "aspirin"}), version["id"],
                           EXECUTOR, phase="development", run_id="legacy-bound",
                           auditor_provider=AUDITOR_1, auditor2_provider=AUDITOR_2)
    assert unbound["lesson_ids"] == ["legacy-lesson"]  # missing key counts as unbound
    assert not bound["lesson_ids"]                     # a bound task never inherits it


# --- audit independence: pairwise-distinct per-role provider identities -----------

def test_execute_requires_both_auditor_providers(system):
    # Fail closed: reusing the executor provider as auditor, or omitting the second
    # independent deployment, is rejected before any record is written.
    task = Task.parse(toy_task("D1", "dev"))
    key = system.version()["id"]
    with pytest.raises(ContractError, match="pairwise-distinct"):
        system.execute(task, key, EXECUTOR, phase="development", run_id="no-auditor-1")
    with pytest.raises(ContractError, match="second independent auditor deployment"):
        system.execute(task, key, EXECUTOR, phase="development", run_id="no-auditor-2",
                       auditor_provider=AUDITOR_1)
    assert system.store.all("attempt") == [] and system.store.all("run") == []


def test_execute_rejects_identities_that_are_not_pairwise_distinct(system):
    task = Task.parse(toy_task("D1", "dev"))
    key = system.version()["id"]
    with pytest.raises(ContractError, match="pairwise-distinct"):
        system.execute(task, key, EXECUTOR, phase="development", run_id="executor-audits",
                       auditor_provider=EXECUTOR, auditor2_provider=AUDITOR_2)
    # Identity is the isolation boundary, not object identity: two distinct fixture
    # instances sharing one identity are still one deployment.
    with pytest.raises(ContractError, match="pairwise-distinct"):
        system.execute(task, key, EXECUTOR, phase="development", run_id="shared-auditor",
                       auditor_provider=FixtureProvider(AUDITOR_1.identity),
                       auditor2_provider=FixtureProvider(AUDITOR_1.identity))
    assert system.store.all("attempt") == [] and system.store.all("run") == []


def test_run_record_seals_per_role_provider_identities(system):
    system.enqueue(Task.parse(toy_task("D1", "dev")))
    run = system.run_next(EXECUTOR, auditor_provider=AUDITOR_1, auditor2_provider=AUDITOR_2)
    assert run["providers"] == {"executor": EXECUTOR.identity, "auditor_1": AUDITOR_1.identity,
                                "auditor_2": AUDITOR_2.identity}
    assert len(set(run["providers"].values())) == 3
    assert run["provider"] == EXECUTOR.identity  # legacy field kept for compatibility
    system.store.verify_seal("run", run["id"], system.store.get("run", run["id"]))
    # The sealed mapping covers every role: swapping one identity breaks the seal.
    stored = system.store.get("run", run["id"])
    stored["providers"]["auditor_2"] = EXECUTOR.identity
    system.store.db.execute("UPDATE objects SET body=? WHERE kind='run' AND id=?",
                            (canonical(stored), run["id"]))
    with pytest.raises(ContractError, match="sealed record"):
        system.store.verify_seal("run", run["id"], system.store.get("run", run["id"]))
    with pytest.raises(ContractError, match="sealed record"):
        system.propose(run["id"], EXECUTOR, proposer="proposer")


def test_propose_requires_the_executor_provider_identity(system):
    # The reflector rides the executor provider, so the proposing identity must be
    # exactly the sealed run's executor identity.
    system.enqueue(Task.parse(toy_task("D1", "dev")))
    run = system.run_next(EXECUTOR, auditor_provider=AUDITOR_1, auditor2_provider=AUDITOR_2)
    with pytest.raises(ContractError, match="provider"):
        system.propose(run["id"], AUDITOR_1, proposer="proposer")
    candidate = system.propose(run["id"], EXECUTOR, proposer="proposer")
    assert len(system.version(candidate)["lessons"]) == 1


# --- rollback authorization: explicit fail-closed approver allowlist --------------

def test_approver_allowlist_is_validated_deduplicated_and_frozen(system):
    with pytest.raises(ContractError, match="identifier"):
        Agent(system.store, approvers=["bad id!"])
    with pytest.raises(ContractError, match="approvers"):
        Agent(system.store, approvers="ops-reviewer")  # a bare string is not a collection
    agent = Agent(system.store, approvers=["ops-reviewer", "ops-reviewer"])
    assert agent.approvers == frozenset({"ops-reviewer"})


def test_rollback_is_denied_by_default_and_requires_an_authorized_approver(system):
    # Default empty allowlist: rollback is disabled entirely, even for well-formed names.
    with pytest.raises(ContractError, match="authorized approver"):
        system.rollback(reviewer="reviewer", reason="default deny")
    base = system.version()["id"]
    _, candidate = develop(system)
    system.store.set_value("active_version", candidate)
    agent = Agent(system.store, approvers=["ops-reviewer", "ops-reviewer"])
    with pytest.raises(ContractError, match="authorized approver"):
        agent.rollback(reviewer="insider", reason="valid identifier, but not authorized")
    assert agent.rollback(reviewer="ops-reviewer", reason="authorized operator") == base
    event = system.store.last_event("version_rolled_back")
    assert event["reviewer"] == "ops-reviewer" and event["from"] == candidate and event["to"] == base
