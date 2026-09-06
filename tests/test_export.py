"""跨仓库导出护栏：lesson 只能以带完整来源的 MemoryHint 或候选策略提案离开控制器。"""

from datetime import datetime

import pytest

from research_loop.agent import Agent
from research_loop.cli import toy_task
from research_loop.export import ExportError, export_candidate_policy, export_memory_hint
from research_loop.ontology import Task, digest
from research_loop.provider import fixture_role_providers
from research_loop.store import Store

# Pairwise-distinct per-role fixture identities for the fail-closed audit gate.
EXECUTOR, AUDITOR_1, AUDITOR_2 = fixture_role_providers()


@pytest.fixture
def system(tmp_path):
    store = Store(tmp_path / "state.sqlite")
    agent = Agent(store)
    agent.initialize()
    yield agent
    store.close()


def develop(agent):
    agent.enqueue(Task.parse(toy_task("D1", "dev")))
    run = agent.run_next(EXECUTOR, auditor_provider=AUDITOR_1, auditor2_provider=AUDITOR_2)
    candidate = agent.propose(run["id"], EXECUTOR, proposer="proposer")
    return run, candidate


def sourced_lesson(agent):
    run, candidate = develop(agent)
    lesson = agent.version(candidate)["lessons"][0]
    return run, candidate, lesson


REQUIRED_HINT_FIELDS = ("kind", "source_run", "scope", "rule_hash", "task_fingerprint",
                        "created_at", "payload")


def test_memory_hint_preserves_source_run_scope_and_rule_hash(system):
    run, candidate, lesson = sourced_lesson(system)
    hint = export_memory_hint(lesson, store=system.store, policy_version=candidate)
    task = Task.parse(run["task"])
    for field in REQUIRED_HINT_FIELDS:
        assert field in hint
    assert hint["kind"] == "memory_hint"
    assert hint["source_run"] == run["id"] == lesson["source_run"]
    assert hint["scope"] == lesson["scope"] == task.scope
    assert hint["rule_hash"] == lesson["rule_hash"] == task.rule_hash
    assert hint["task_fingerprint"] == task.fingerprint
    assert hint["policy_version"] == candidate
    datetime.fromisoformat(hint["created_at"])  # must be a real ISO 8601 timestamp
    assert hint["payload"]["instruction"] == lesson["instruction"]
    assert hint["payload"]["evidence_ids"] == lesson["evidence_ids"]
    assert hint["payload"]["source_hash"] == lesson["source_hash"] == digest(run)
    assert hint["hint_hash"] == digest({k: v for k, v in hint.items() if k != "hint_hash"})


def test_memory_hint_is_deterministic_given_the_same_timestamp(system):
    _, _, lesson = sourced_lesson(system)
    first = export_memory_hint(lesson, store=system.store, created_at="2026-09-06T00:00:00+00:00")
    second = export_memory_hint(lesson, store=system.store, created_at="2026-09-06T00:00:00+00:00")
    assert first == second
    assert first["created_at"] == "2026-09-06T00:00:00+00:00"


@pytest.mark.parametrize("field", ["id", "source_run", "source_hash", "scope", "rule_hash",
                                   "instruction", "evidence_ids"])
def test_hint_missing_any_required_provenance_is_refused(system, field):
    _, _, lesson = sourced_lesson(system)
    broken = {k: v for k, v in lesson.items() if k != field}
    with pytest.raises(ExportError, match="provenance"):
        export_memory_hint(broken, store=system.store)


def test_hint_without_resolvable_task_fingerprint_is_refused(system):
    _, candidate, lesson = sourced_lesson(system)
    with pytest.raises(ExportError, match="task_fingerprint"):
        export_memory_hint(lesson)  # no store, no run, no fingerprint: provenance incomplete
    task = Task.parse(system.store.get("run", lesson["source_run"])["task"])
    hint = export_memory_hint(lesson, task_fingerprint=task.fingerprint)
    assert hint["task_fingerprint"] == task.fingerprint


def test_hint_refuses_scope_rule_or_source_hash_drift_from_the_source_run(system):
    run, _, lesson = sourced_lesson(system)
    with pytest.raises(ExportError, match="scope"):
        export_memory_hint({**lesson, "scope": "another.scope"}, run=run)
    with pytest.raises(ExportError, match="rule_hash"):
        export_memory_hint({**lesson, "rule_hash": "b" * 64}, run=run)
    with pytest.raises(ExportError, match="source_hash"):
        export_memory_hint({**lesson, "source_hash": "c" * 64}, run=run)
    with pytest.raises(ExportError, match="evidence"):
        export_memory_hint({**lesson, "evidence_ids": ["invented"]}, run=run)


def test_hint_refuses_nondevelopment_source_runs(system):
    _, _, lesson = sourced_lesson(system)
    run = system.store.get("run", lesson["source_run"])
    with pytest.raises(ExportError, match="development"):
        export_memory_hint(lesson, run={**run, "phase": "evaluation"})
    with pytest.raises(ExportError, match="closed development"):
        export_memory_hint(lesson, run={**run, "state": "failed"})


def test_hint_refuses_source_runs_without_a_completion_seal(system):
    _, _, lesson = sourced_lesson(system)
    system.store.db.execute("DELETE FROM events WHERE body LIKE '%run_closed%'")
    with pytest.raises(ExportError, match="seal"):
        export_memory_hint(lesson, store=system.store)


def test_hint_refuses_private_payload_fields_and_bad_timestamps(system):
    _, _, lesson = sourced_lesson(system)
    with pytest.raises(ExportError, match="rejected"):
        export_memory_hint({**lesson, "instruction": "peek at gold_status labels"})
    with pytest.raises(ExportError, match="ISO"):
        export_memory_hint(lesson, store=system.store, created_at="yesterday")


def _sealed_run_with(agent, run_id, **overrides):
    """Forge a sealed, otherwise well-formed development run with the given field overrides."""
    task = Task.parse(toy_task("D9", "dev"))
    run = {"id": run_id, "task": task.data(), "task_hash": digest(task.data()),
           "version": agent.version()["id"], "phase": "development",
           "provider": EXECUTOR.identity,
           "providers": {"executor": EXECUTOR.identity, "auditor_1": AUDITOR_1.identity,
                         "auditor_2": AUDITOR_2.identity},
           "state": "closed", "status": "proceed",
           "decision": {"status": "proceed", "rule_hash": task.rule_hash, "evidence_ids": ["obs"],
                        "reason": "fixture record", "declared_program_complete": False},
           "audit_valid": True, "evidence_admitted": True, "protocol_violations": [],
           "lesson_ids": [], "usage": {"calls": 3, "complete": True, "input_chars": 10,
                                       "input_tokens": 1, "output_tokens": 1, "elapsed_s": 0.0}}
    run.update(overrides)
    agent.store.put("run", run_id, run)
    agent.store.event("run_closed", {"run_id": run_id, "record_hash": digest(run)})
    lesson = {"scope": task.scope, "rule_hash": task.rule_hash, "source_run": run_id,
              "source_hash": digest(run), "instruction": "fixture lesson", "evidence_ids": ["obs"]}
    lesson["id"] = digest(lesson)
    return lesson


@pytest.mark.parametrize("overrides", [
    {"status": "withdrawn"},
    {"status": "invalid"},
    {"audit_valid": False},
    {"evidence_admitted": False},
])
def test_export_refuses_sealed_runs_that_do_not_admit_lessons(system, overrides):
    # Same gate as propose(): a sealed run that never walked the full protocol (failed
    # audit, rejected status or unadmitted evidence) must not leave the controller as
    # a memory hint, on the hint path or through a candidate policy proposal.
    lesson = _sealed_run_with(system, "dev-forged-export", **overrides)
    with pytest.raises(ExportError, match="does not admit lessons"):
        export_memory_hint(lesson, store=system.store)
    with pytest.raises(ExportError, match="does not admit lessons"):
        export_candidate_policy([lesson], candidate_version="cand-x", store=system.store)


def test_candidate_policy_exports_proposals_never_active_policies(system):
    run, candidate, lesson = sourced_lesson(system)
    base = system.version()["id"]
    proposal = export_candidate_policy([lesson], candidate_version=candidate, base_version=base,
                                       store=system.store)
    assert proposal["kind"] == "policy_proposal"
    assert proposal["status"] == "candidate"
    assert proposal["promotion"]["eligible"] is False
    assert proposal["candidate_version"] == candidate and proposal["base_version"] == base
    assert [h["lesson_id"] for h in proposal["lessons"]] == [lesson["id"]]
    assert all(h["kind"] == "memory_hint" and h["policy_version"] == candidate
               for h in proposal["lessons"])
    assert proposal["proposal_hash"] == digest({k: v for k, v in proposal.items() if k != "proposal_hash"})
    with pytest.raises(ExportError, match="candidate"):
        export_candidate_policy([lesson], candidate_version=candidate, status="active",
                                store=system.store)


def test_candidate_policy_refuses_lessons_outside_the_candidate_version(system):
    run, candidate, lesson = sourced_lesson(system)
    forged = {**lesson, "id": "lesson-not-in-any-version"}
    with pytest.raises(ExportError, match="candidate version"):
        export_candidate_policy([forged], candidate_version=candidate, store=system.store)
    with pytest.raises(ExportError, match="candidate version"):
        export_candidate_policy([lesson], candidate_version="missing-version", store=system.store)
    with pytest.raises(ExportError, match="at least one"):
        export_candidate_policy([], candidate_version=candidate, store=system.store)


def test_candidate_policy_base_version_must_be_verifiable_against_the_store(system):
    run, candidate, lesson = sourced_lesson(system)
    base = system.version()["id"]  # the candidate's parent and the active version here
    # A claimed base version that is never checked is worse than none: no store, no export.
    with pytest.raises(ExportError, match="requires the controller store"):
        export_candidate_policy([lesson], candidate_version=candidate, base_version=base)
    # Neither the candidate's parent nor the current active version: refused.
    with pytest.raises(ExportError, match="neither its parent nor the current active version"):
        export_candidate_policy([lesson], candidate_version=candidate, base_version="f" * 64,
                                store=system.store)
    # The candidate's parent is accepted.
    proposal = export_candidate_policy([lesson], candidate_version=candidate, base_version=base,
                                       store=system.store)
    assert proposal["base_version"] == base


def test_candidate_policy_base_version_can_be_the_current_active_version(system):
    run, candidate, lesson = sourced_lesson(system)
    base = system.version()["id"]
    system.store.set_value("active_version", candidate)  # as a promotion would
    # The parent is still accepted...
    assert export_candidate_policy([lesson], candidate_version=candidate, base_version=base,
                                   store=system.store)["base_version"] == base
    # ...and so is the current active version even though it is not the parent.
    assert export_candidate_policy([lesson], candidate_version=candidate, base_version=candidate,
                                   store=system.store)["base_version"] == candidate
    with pytest.raises(ExportError, match="neither its parent nor the current active version"):
        export_candidate_policy([lesson], candidate_version=candidate, base_version=base + "0",
                                store=system.store)


def develop_bound(agent, key, bindings):
    data = toy_task(key, "dev")
    data["bindings"] = bindings
    agent.enqueue(Task.parse(data))
    run = agent.run_next(EXECUTOR, auditor_provider=AUDITOR_1, auditor2_provider=AUDITOR_2)
    candidate = agent.propose(run["id"], EXECUTOR, proposer="proposer")
    return run, candidate, agent.version(candidate)["lessons"][0]


def test_memory_hint_carries_task_bindings_and_covers_them_in_hint_hash(system):
    run, candidate, lesson = develop_bound(system, "D9", {"compound": "aspirin"})
    assert lesson["bindings"] == {"compound": "aspirin"}
    hint = export_memory_hint(lesson, store=system.store, policy_version=candidate)
    assert hint["bindings"] == {"compound": "aspirin"} == Task.parse(run["task"]).bindings
    assert hint["hint_hash"] == digest({k: v for k, v in hint.items() if k != "hint_hash"})


def test_memory_hint_for_unbound_task_keeps_previous_format(system):
    _, _, lesson = sourced_lesson(system)  # toy task without bindings
    hint = export_memory_hint(lesson, store=system.store)
    assert "bindings" not in hint  # empty bindings are omitted, not exported as {}
    assert hint["hint_hash"] == digest({k: v for k, v in hint.items() if k != "hint_hash"})
