import subprocess
from copy import deepcopy
from pathlib import Path

import pytest

from research_loop.modular.benchmarks import BladeAdapter
from research_loop.modular.benchmarks.execution import DockerExecutionBroker
from research_loop.modular.combinations import default_compatibility
from research_loop.modular.contracts import ContractError, DataIdentity, FrozenRecord
from research_loop.modular.modules.admission import AuditItem, ScientificState
from research_loop.modular.modules.context import ContextBuilder, ContextCache
from research_loop.modular.modules.evidence import ClaimLedger, EvidenceLedger
from research_loop.modular.runtime import AuditAuthority, AuditVerifier, RunSession, verify_trace


KEYS = {"audit-a": b"a" * 32, "audit-b": b"b" * 32}


def session_at(path, *, outcome="positive", slots=("final",), modules=("M1", "M2", "M3")):
    identity = DataIdentity("blade", "fixture", "source-a", "v1", "split", "train")
    task = BladeAdapter().prepare(identity, {"task_id": "fixture", "dataset_id": "fixture-data",
        "research_question": "Does the fixture change?", "data_schema": [{"name": "x"}]})
    session = RunSession(task, package_digest="package", arm=default_compatibility("base").arm(modules),
        objective=FrozenRecord.from_dict({"question": "Does the fixture change?", "primary_endpoint": "difference"}),
        slots=slots, execution_limit=1, sidecar=path, verifier=AuditVerifier(KEYS), required_audit=("measurement",))
    data = path / "public.csv"
    data.write_text("x\n1\n", encoding="utf-8")
    broker = DockerExecutionBroker([path], runner=lambda *a, **kw: subprocess.CompletedProcess(a[0], 0, b"observed 1\n", b""))
    execution = session.execute("print(1)", broker=broker, image="fixture@sha256:" + "a" * 64, inputs={"data": data})
    state = ScientificState("valid", "supported" if outcome == "positive" else "refuted", "unknown", "explore")
    receipts = [AuditAuthority(name, key).issue(identity=identity, objective_digest=session.objective.content_hash,
        execution_digest=execution.content_hash, state=state, outcome=outcome,
        audit=[AuditItem("measurement", True, True)]) for name, key in KEYS.items()]
    return session, execution, receipts


def final_candidate(session, execution, outcome="positive"):
    return FrozenRecord.from_dict({"objective_digest": session.objective.content_hash, "outcome": outcome,
        "evidence_ids": [execution.content_hash], "conclusion": "fixture observation", "programme_complete": False})


@pytest.mark.parametrize("modules", [("M1",), ("M1", "M2")])
def test_invoke_respects_m2_control_but_withdrawal_still_blocks_scientific_final(tmp_path, modules):
    session, execution, receipts = session_at(tmp_path / "run", modules=modules)
    session.admit(execution.content_hash, receipts)
    root = session.admission_roots[execution.content_hash]
    bindings = {"task": session.task.identity.task_id, "objective": session.objective.content_hash}
    claim = session.claims.create("caller-supported claim", subject_bindings=bindings)
    session.claims.apply(claim.claim_id, {"supports": [root], "refutes": [], "subject_bindings": bindings}, expected_revision=0)
    session.evidence.withdraw(root, "caller withdraws the supporting observation")
    candidate = final_candidate(session, execution)
    seen = []
    session.invoke("final", lambda request: seen.append(request) or candidate, instruction="Assess current material.")
    current = session.claims.claims()[0]
    if "M2" in modules:
        assert not current.support_roots and current.needs_review and current.revision == 2
    else:
        assert current.support_roots == (root,) and not current.needs_review and current.revision == 1
    assert "mode" not in seen[0].data()["context"]
    assert session.finish(candidate).data()["decision"] == "blocked"


@pytest.mark.parametrize("outcome", ["positive", "negative"])
def test_public_adapter_execution_dual_audit_real_final_gate(tmp_path, outcome):
    session, execution, receipts = session_at(tmp_path / outcome, outcome=outcome)
    session.admit(execution.content_hash, receipts)
    seen = []
    session.invoke("final", lambda request: seen.append(request) or final_candidate(session, execution, outcome), instruction="Report evidence.")
    result = session.finish(final_candidate(session, execution, outcome)).data()
    assert result["decision"] == ("proceed" if outcome == "positive" else "closed_negative")
    assert result["programme_complete"] is False
    assert seen[0].data()["context"]["entries"]["entries"][0]["kind"] == "evidence"
    trace = verify_trace(session.sidecar / "trace.jsonl").data()
    assert trace["terminal"] and "scientific_admission" in trace["stages"]
    with pytest.raises(ContractError):
        session.finish(final_candidate(session, execution, outcome))


@pytest.mark.parametrize("fault", ["one_audit", "tampered", "string_false", "missing_check", "other_task", "disagree"])
def test_invalid_audit_cannot_reach_final_proceed(tmp_path, fault):
    session, execution, receipts = session_at(tmp_path / fault)
    if fault == "one_audit":
        receipts = receipts[:1]
    elif fault == "tampered":
        forged = deepcopy(receipts[0].data())
        forged["body"]["outcome"] = "negative"
        receipts[0] = FrozenRecord.from_dict(forged)
    elif fault == "string_false":
        forged = deepcopy(receipts[0].data())
        forged["body"]["audit"][0]["passed"] = "false"
        receipts[0] = FrozenRecord.from_dict(forged)
    else:
        identity = session.task.identity if fault != "other_task" else DataIdentity("blade", "other", "g", "v", "s", "train")
        receipts[0] = AuditAuthority("audit-a", KEYS["audit-a"]).issue(identity=identity,
            objective_digest=session.objective.content_hash, execution_digest=execution.content_hash,
            state=ScientificState("valid", "supported", "unknown", "explore"), outcome="positive",
            audit=[] if fault == "missing_check" else [AuditItem("measurement", True, fault != "disagree")])
    with pytest.raises(ContractError):
        session.admit(execution.content_hash, receipts)
    session.invoke("final", lambda _: final_candidate(session, execution), instruction="Report.")
    result = session.finish(final_candidate(session, execution)).data()
    assert result["decision"] == "blocked"
    assert "missing_validated_evidence" in result["reasons"]
    assert "audit_rejected" in verify_trace(session.sidecar / "trace.jsonl").data()["stages"]


def test_cache_respects_history_budget_and_next_model_payload_revocation(tmp_path):
    session, execution, receipts = session_at(tmp_path / "history", slots=("before", "after"))
    session.admit(execution.content_hash, receipts)
    seen = []
    capture = lambda r: seen.append(r.data()) or FrozenRecord.from_dict({"recorded": True})
    session.invoke("before", capture, instruction="Inspect.")
    root = session.evidence.roots()[0].root_id
    session.evidence.withdraw(root, "measurement invalidated")
    session.invoke("after", capture, instruction="Inspect.")
    assert seen[0]["context"]["entries"]["entries"]
    assert seen[1]["context"]["entries"]["entries"] == []
    assert session.finish(final_candidate(session, execution)).data()["decision"] == "blocked"
    evidence, claims = session.evidence, session.claims
    cache = ContextCache()
    builder = ContextBuilder(session.task.identity, budget_bytes=12000)
    a = cache.get_or_build(builder, "q", evidence, claims, mode="baseline", baseline_summary="correct")
    b = cache.get_or_build(builder, "q", evidence, claims, mode="baseline", baseline_summary="incorrect")
    assert a.content_hash != b.content_hash
    small = cache.get_or_build(ContextBuilder(session.task.identity, budget_bytes=1), "q", evidence, claims, mode="baseline", baseline_summary="correct")
    assert small.entries.data()["entries"] == []


def test_call_failure_consumes_slot_and_trace_detects_mutation(tmp_path):
    session, _, _ = session_at(tmp_path / "failure")
    def fail(_):
        raise TimeoutError("provider unavailable")
    with pytest.raises(TimeoutError):
        session.invoke("final", fail, instruction="Report.")
    with pytest.raises(ContractError):
        session.invoke("final", fail, instruction="Retry.")
    path = session.sidecar / "trace.jsonl"
    assert verify_trace(path).data()["terminal"]
    lines = path.read_text(encoding="utf-8").splitlines()
    rows = [FrozenRecord(line).data() for line in lines]
    rows[1]["data"]["attempt"] = 99
    path.write_text("\n".join(FrozenRecord.from_dict(row).encoded for row in rows), encoding="utf-8")
    with pytest.raises(ContractError):
        verify_trace(path)
