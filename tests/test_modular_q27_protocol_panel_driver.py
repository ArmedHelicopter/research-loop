"""Public two-benchmark checks for the typed Q2.7 source/replay seam."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from research_loop.modular.benchmarks import BladeAdapter, DiscoveryBenchAdapter, DockerExecutionBroker
from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.modular.modules.admission import AuditItem, ScientificState
from research_loop.modular.modules.improvement import CandidatePackage, TrainingManifest
from research_loop.modular.p0_panel import fixed_control_design
from research_loop.modular.panel_receipts import PanelCell
from research_loop.modular.protocol_panel_driver import ProtocolReplayAuthority, Q27ProtocolDriver, freeze_protocol_bundle, protocol_panel_injection, verify_after_finish
from research_loop.modular.runtime import AuditAuthority, AuditVerifier, RunSession
from research_loop.modular.workflow import ModularWorkflow
from research_loop.ontology import ContractError


IMAGE = "research-benchmark-python@sha256:1433f0d223b0773b0d8c3184fa4ff6ab0a3891113442f1592d8d7e883d21a349"
SPLIT = "7" * 64
AUDIT_KEYS = {"q27-a": b"a" * 32, "q27-b": b"b" * 32}


def _task(benchmark):
    identity = DataIdentity(benchmark, "q27-" + benchmark, benchmark + ":q27", "synthetic-v1", SPLIT, "train")
    if benchmark == "blade":
        return BladeAdapter().prepare(identity, {"task_id": identity.task_id, "dataset_id": "public",
            "research_question": "What public mean is observed?", "data_schema": [{"name": "x", "dtype": "float"}]})
    return DiscoveryBenchAdapter().prepare(identity, {"task_id": identity.task_id, "question": "What public mean is observed?",
        "source_kind": "synthetic", "dataset": [{"name": "public.csv", "columns": [{"name": "x"}]}]})


def _execution():
    csv = b"x\n1\n3\n"
    return {"program": "from pathlib import Path\nprint(Path('/input/public_csv').read_text().strip())",
        "csv_bytes_hex": csv.hex(), "csv_sha256": hashlib.sha256(csv).hexdigest(),
        "image": IMAGE, "timeout_seconds": 20}


def _scenario(task, variant, control):
    grid = fixed_control_design("q" * 64, control.content_hash)
    bundle = freeze_protocol_bundle(task, execution=_execution(), p0_fixed_control=grid)
    injection = protocol_panel_injection(variant, task=FrozenRecord.from_dict(task.data()), evidence=bundle,
        p0_fixed_control=grid)
    budget = FrozenRecord.from_dict({"model_calls": 1, "docker_attempts": 1, "audit_receipts": 2})
    scenario = FrozenRecord.from_dict({"experiment_id": "Q2.7", "variant": variant,
        "controller_input": injection, "base": {"task": task.content_hash, "evidence": bundle.content_hash,
        "budget": budget.content_hash}, "controls": {"same_task": True, "same_evidence": True, "same_budget": True}})
    package = CandidatePackage.create(parent_digest=None, manifest=TrainingManifest.freeze([task.identity]),
        changes={"prompt": {"instructions": "synthetic public train package"}}, search_cost=0)
    cell = PanelCell("Q2.7", task.identity, "r1", variant, "p0-fixed", FrozenRecord.from_dict(grid.data()["runtime_arm"]),
        task.content_hash, scenario.content_hash, package.digest, "a" * 64)
    return grid, scenario, package, cell


def _audit_port(calls):
    def issue(subject):
        body = subject.data(); calls.append(body)
        assert set(body) == {"schema", "identity", "task_digest", "objective_digest", "execution_digest", "execution_status", "required_audit"}
        return [AuditAuthority(name, key).issue(identity=DataIdentity.parse(body["identity"]), objective_digest=body["objective_digest"],
            execution_digest=body["execution_digest"], state=ScientificState("valid", "supported", "unknown", "explore"),
            outcome="positive", audit=[AuditItem("measurement", True, True)]) for name, key in AUDIT_KEYS.items()]
    return issue


def _model(seen):
    def call(request):
        body = request.data(); seen.append(body)
        encoded = request.encoded
        for marker in ('"arm_id"', '"variant"', '"controller_input"', '"csv_bytes_hex"', '"p0_fixed_control"'):
            assert marker not in encoded
        public = body["module_context"]["public_execution"]
        assert set(public) == {"program_sha256", "csv_sha256", "image", "execution_digest", "execution_status"}
        assert body["execution_feedback"][0]["stdout"].strip() == "x\n1\n3"
        return FrozenRecord.from_dict({"objective_digest": body["module_context"]["required_objective_digest"],
            "outcome": "positive", "evidence_ids": [public["execution_digest"]],
            "conclusion": "The public execution returned the supplied rows.", "programme_complete": False})
    return call


def _run(root: Path, benchmark: str, variant: str):
    task, control = _task(benchmark), FrozenRecord.from_dict({"p0": "trusted synthetic control"})
    grid, scenario, package, cell = _scenario(task, variant, control)
    sidecar = root / benchmark / variant; sidecar.mkdir(parents=True)
    session = RunSession(task, package_digest=package.digest, arm=cell.runtime_arm,
        objective=FrozenRecord.from_dict({"objective": "registered public execution endpoint"}), slots=("final",),
        execution_limit=1, sidecar=sidecar, verifier=AuditVerifier(AUDIT_KEYS), required_audit=("measurement",))
    calls, seen = [], []
    driver = Q27ProtocolDriver(broker=DockerExecutionBroker([sidecar]), audit_port=_audit_port(calls),
        expected_p0_control_digest=control.content_hash)
    stage, candidate, responses = driver.run(ModularWorkflow(session), cell=cell, scenario=scenario,
        model=_model(seen), package=package)
    terminal = session.finish(candidate)
    return task, grid, scenario, cell, session, stage, candidate, responses, terminal, calls, seen


@pytest.mark.parametrize("benchmark", ["blade", "discoverybench"])
@pytest.mark.parametrize("variant", ["missing_lock", "missing_execution", "missing_audit", "illegal_state"])
def test_complete_source_runs_have_identical_budget_and_a_refused_offline_fault_replay(tmp_path, benchmark, variant):
    _task_row, grid, scenario, cell, session, stage, candidate, responses, terminal, audits, seen = _run(tmp_path, benchmark, variant)
    source = session.sidecar / "trace.jsonl"; original = source.read_bytes()
    assert terminal.data()["decision"] == "proceed" and session._attempts == 1 and session._next_call == 1
    assert len(audits) == 1 and len(seen) == len(responses) == 1
    assert stage.detail.data()["budget"] == {"docker": 1, "audit_receipts": 2, "model": 1}
    assert grid.data()["runtime_arm"] == cell.runtime_arm.data()
    authority = ProtocolReplayAuthority("replay", b"r" * 32)
    receipt = verify_after_finish(cell=cell, scenario=scenario, session=session, candidate=candidate, terminal=terminal,
        replay_authority=authority)
    finding = authority.verify(receipt).data()
    assert finding["fault"] == variant and finding["source_decision"] == "proceed"
    assert finding["replay_refusal"] and finding["budget"] == {"docker": 1, "audit_receipts": 2, "model": 1}
    assert source.read_bytes() == original
    replay = session.sidecar / finding["replay"]["path"]
    assert replay.exists() and replay.read_bytes() != original


def test_bundle_and_p0_mismatch_fail_before_docker_or_model(tmp_path):
    task, control = _task("blade"), FrozenRecord.from_dict({"p0": "trusted synthetic control"})
    grid = fixed_control_design("q" * 64, control.content_hash)
    bad = _execution(); bad["csv_sha256"] = "0" * 64
    with pytest.raises(ContractError, match="CSV digest"):
        freeze_protocol_bundle(task, execution=bad, p0_fixed_control=grid)
    bundle = freeze_protocol_bundle(task, execution=_execution(), p0_fixed_control=grid)
    other = fixed_control_design("q" * 64, FrozenRecord.from_dict({"p0": "different"}).content_hash)
    with pytest.raises(ContractError, match="P0 control differs"):
        protocol_panel_injection("missing_lock", task=FrozenRecord.from_dict(task.data()), evidence=bundle,
            p0_fixed_control=other)
    assert not list(tmp_path.rglob("analysis-*.py"))


def test_replay_receipt_signature_and_source_candidate_binding_are_fail_closed(tmp_path):
    _task_row, _grid, scenario, cell, session, _stage, candidate, _responses, terminal, _audits, _seen = _run(tmp_path, "blade", "missing_audit")
    authority = ProtocolReplayAuthority("replay", b"r" * 32)
    receipt = verify_after_finish(cell=cell, scenario=scenario, session=session, candidate=candidate, terminal=terminal,
        replay_authority=authority)
    forged = receipt.data(); forged["finding"]["fault"] = "missing_lock"
    with pytest.raises(ContractError, match="signature"):
        authority.verify(FrozenRecord.from_dict(forged))
    wrong = FrozenRecord.from_dict({**terminal.data(), "candidate_digest": "0" * 64})
    with pytest.raises(ContractError, match="candidate"):
        verify_after_finish(cell=cell, scenario=scenario, session=session, candidate=candidate, terminal=wrong,
            replay_authority=authority)
