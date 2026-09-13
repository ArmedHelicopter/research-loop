"""Regression coverage for protocol replay of interrupted run journals."""
from pathlib import Path

import pytest

from research_loop.modular.benchmarks import BladeAdapter
from research_loop.modular.combinations import default_compatibility
from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.modular.protocol_trace import verify_protocol_trace
from research_loop.modular.runtime import AuditVerifier, RunSession
from research_loop.ontology import ContractError


def _session(path: Path) -> RunSession:
    identity = DataIdentity("blade", "terminal-fixture", "source-a", "v1", "split", "train")
    task = BladeAdapter().prepare(identity, {"task_id": "terminal-fixture", "dataset_id": "fixture-data",
        "research_question": "Does the fixture change?", "data_schema": [{"name": "x"}]})
    return RunSession(task, package_digest="package", arm=default_compatibility("base").arm(["M1", "M2", "M3"]),
        objective=FrozenRecord.from_dict({"question": "Does the fixture change?", "primary_endpoint": "difference"}),
        slots=("final",), execution_limit=0, sidecar=path,
        verifier=AuditVerifier({"audit-a": b"a" * 32, "audit-b": b"b" * 32}), required_audit=("measurement",))


def _candidate(session: RunSession) -> FrozenRecord:
    return FrozenRecord.from_dict({"objective_digest": session.objective.content_hash, "outcome": "unknown",
        "evidence_ids": [], "conclusion": "fixture observation", "programme_complete": False})


def _record_pending_request(session: RunSession) -> None:
    request = FrozenRecord.from_dict({"schema": "public-model-request-v1", "task": session.task.data(),
        "lock_digest": session.lock.content_hash, "objective": session.objective.data(), "slot": "final",
        "instruction": "Report fixture.", "context": {}, "module_context": {}, "execution_feedback": []})
    session._record("model_request", {"request_digest": request.content_hash, "request": request.data()})


@pytest.mark.parametrize("state", ["lock", "pending_model", "complete_response"])
def test_protocol_trace_rejects_nonterminal_journals(tmp_path, state):
    session = _session(tmp_path / state)
    if state == "pending_model":
        _record_pending_request(session)
    elif state == "complete_response":
        session.invoke("final", lambda _: _candidate(session), instruction="Report fixture.")

    with pytest.raises(ContractError, match="incomplete without a terminal"):
        verify_protocol_trace(session.sidecar / "trace.jsonl")


def test_protocol_trace_accepts_final_and_typed_failure_terminals(tmp_path):
    final = _session(tmp_path / "final")
    final.invoke("final", lambda _: _candidate(final), instruction="Report fixture.")
    final.finish(_candidate(final))
    assert verify_protocol_trace(final.sidecar / "trace.jsonl").data()["decision"] == "unknown"

    model_failure = _session(tmp_path / "model_failure")
    with pytest.raises(TimeoutError):
        model_failure.invoke("final", lambda _: (_ for _ in ()).throw(TimeoutError("fixture")), instruction="Report fixture.")
    assert verify_protocol_trace(model_failure.sidecar / "trace.jsonl").data()["decision"] is None

    controller_failure = _session(tmp_path / "controller_failure")
    controller_failure.controller_failure(driver_id="fixture-driver", error_type="FixtureError")
    assert verify_protocol_trace(controller_failure.sidecar / "trace.jsonl").data()["decision"] is None
