import hashlib
import hmac
import multiprocessing
from pathlib import Path

import pytest

from research_loop.modular.benchmarks import BladeAdapter
from research_loop.modular.combinations import default_compatibility
from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.modular.deployment import FileDeploymentPort
from research_loop.modular.modules.improvement import (
    AcceptanceAuthority, BoundedCandidateBuilder, CandidatePackage, ExecutionRuntime,
    SignedValidation, TrainingManifest,
)
from research_loop.modular.runtime import AuditVerifier, RunSession
from research_loop.modular.workflow import ModularWorkflow
from research_loop.ontology import ContractError


KEY = b"deployment-acceptance-key-32bytes"
VALIDATION_KEY = b"deployment-validation-key-32bytes"
AUDIT_KEYS = {"audit-a": b"a" * 32, "audit-b": b"b" * 32}


def identity(name: str) -> DataIdentity:
    return DataIdentity("blade", name, "fixture-group", "fixture-v1", "fixture-split", "train")


def packages() -> tuple[CandidatePackage, CandidatePackage]:
    manifest = TrainingManifest.freeze([identity("train-a")])
    base = CandidatePackage.create(parent_digest=None, manifest=manifest,
                                   changes={"memory": {"mode": "off"}}, search_cost=1)
    candidate = BoundedCandidateBuilder().build(
        manifest, base,
        {"prompt": {"instructions": "Use the frozen train instruction."},
         "memory": {"mode": "on", "lesson": "frozen train lesson"},
         "config": {"max_steps": 3, "revision_limit": 1, "temperature": 0.25}},
        search_cost=1,
    )
    return base, candidate


def authority(candidate: CandidatePackage, active: CandidatePackage) -> AcceptanceAuthority:
    def validate(_validation: SignedValidation) -> dict[str, object]:
        return {"validator_id": "independent-fixture", "candidate_digest": candidate.digest,
                "expected_active_digest": active.digest, "trial_digest": "b" * 64,
                "domain": "validation", "offline": False, "decision": "approved"}
    return AcceptanceAuthority(KEY, VALIDATION_KEY, validate)


def signed_validation() -> SignedValidation:
    record = FrozenRecord.from_dict({"opaque": "independent fixture"})
    return SignedValidation(record, hmac.new(VALIDATION_KEY, record.encoded.encode(), hashlib.sha256).hexdigest())


def _competing_activate(state_path: str, initial_record: str, candidate_record: str,
                        expected_digest: str, barrier, results) -> None:
    initial = CandidatePackage(FrozenRecord(initial_record))
    candidate = CandidatePackage(FrozenRecord(candidate_record))
    port = FileDeploymentPort(Path(state_path), initial)
    barrier.wait(timeout=10)
    ack = port.activate(candidate, expected_digest)
    results.put((ack.online, ack.active_digest, ack.memory_digest))


def test_file_port_on_off_on_persists_and_rejects_drift_offline_replay_and_forgery(tmp_path: Path) -> None:
    base, candidate = packages()
    port = FileDeploymentPort(tmp_path / "active-package.json", base)
    auth = authority(candidate, base)
    runtime = ExecutionRuntime(tmp_path / "runtime.sqlite", port, auth, base)
    receipt = auth.validate(candidate, base.digest, signed_validation())
    assert runtime.run_task(identity("off"), lambda _, package: package.record.data()["changes"]["memory"]["mode"]).data()["result"] == "off"
    runtime.activate(receipt, candidate)
    assert runtime.run_task(identity("on"), lambda _, package: package.record.data()["changes"]["memory"]["mode"]).data()["result"] == "on"
    rollback = auth.authorize_rollback(candidate.digest, base.digest, "fixture rollback")
    runtime.rollback(rollback)
    with pytest.raises(ContractError, match="already consumed"):
        runtime.activate(receipt, candidate)
    assert runtime.run_task(identity("off-again"), lambda _, package: package.record.data()["changes"]["memory"]["mode"]).data()["result"] == "off"
    runtime.close()

    reopened_port = FileDeploymentPort(tmp_path / "active-package.json", base)
    reopened = ExecutionRuntime(tmp_path / "runtime.sqlite", reopened_port, auth, base)
    assert reopened.run_task(identity("reopen"), lambda _, package: package.digest).data()["active_digest"] == base.digest
    state = tmp_path / "active-package.json"
    state.write_bytes(state.read_bytes() + b" ")
    with pytest.raises(ContractError, match="drift or offline"):
        reopened.run_task(identity("tampered"), lambda _, package: package.digest)
    reopened.close()

    clean_port = FileDeploymentPort(tmp_path / "fresh.json", base)
    fresh = ExecutionRuntime(tmp_path / "fresh.sqlite", clean_port, auth, base)
    with pytest.raises(ContractError, match="signature"):
        fresh.activate(type(receipt)(receipt.record, "forged"), candidate)
    (tmp_path / "fresh.json.sha256").unlink()
    with pytest.raises(ContractError, match="offline"):
        fresh.activate(receipt, candidate)
    with pytest.raises(ContractError, match="corrupt or incomplete"):
        FileDeploymentPort(tmp_path / "fresh.json", base)


def test_file_port_compare_and_swap_is_cross_process_and_preserves_previous_snapshot(tmp_path: Path) -> None:
    base, candidate_a = packages()
    manifest = TrainingManifest(FrozenRecord.from_dict(base.record.data()["training_manifest"]))
    candidate_b = CandidatePackage.create(parent_digest=base.digest, manifest=manifest,
        changes={"memory": {"mode": "on", "lesson": "independent competitor"}}, search_cost=1)
    state = tmp_path / "shared.json"
    FileDeploymentPort(state, base)
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)
    results = context.Queue()
    processes = [context.Process(target=_competing_activate, args=(str(state), base.record.encoded,
        candidate.record.encoded, base.digest, barrier, results)) for candidate in (candidate_a, candidate_b)]
    for process in processes:
        process.start()
    for process in processes:
        process.join(15)
        assert process.exitcode == 0
    acknowledgements = [results.get(timeout=2) for _ in processes]
    winners = [ack for ack in acknowledgements if ack[0]]
    assert len(winners) == 1
    active_digest = winners[0][1]
    active = FileDeploymentPort(state, base)
    assert active.current().online and active.current().active_digest == active_digest
    assert active.previous() is not None and active.previous().digest == base.digest
    snapshot = FrozenRecord(state.read_text(encoding="utf-8")).data()
    selected = next(candidate for candidate in (candidate_a, candidate_b) if candidate.digest == active_digest)
    assert snapshot["package"] == selected.record.data()
    assert snapshot["memory_view"] == selected.record.data()["changes"].get("memory", {})
    assert snapshot["memory_digest"] == selected.memory_digest


def test_m9_binds_locked_package_and_injects_frozen_payload_for_m4_m5_m6_and_final(tmp_path: Path) -> None:
    base, candidate = packages()
    auth = authority(candidate, base)
    port = FileDeploymentPort(tmp_path / "active.json", base)
    runtime = ExecutionRuntime(tmp_path / "runtime.sqlite", port, auth, base)
    task = BladeAdapter().prepare(identity("next"), {"task_id": "next", "dataset_id": "fixture",
        "research_question": "Does deployment bind the next task?", "data_schema": [{"name": "x"}]})
    session = RunSession(task, package_digest=candidate.digest,
        arm=default_compatibility("base").arm(["M1", "M2", "M3", "M4", "M5", "M6", "M9"]),
        objective=FrozenRecord.from_dict({"question": "locked question", "primary": "locked endpoint"}),
        slots=("m4", "r1", "r2", "m6", "final"), execution_limit=2, sidecar=tmp_path / "run",
        verifier=AuditVerifier(AUDIT_KEYS), required_audit=("measurement",))
    workflow = ModularWorkflow(session, deployment=runtime)
    assert workflow.m9_policy(FrozenRecord.from_dict({"policy": "fixture"}),
                               receipt=auth.validate(candidate, base.digest, signed_validation()), candidate=candidate).status == "executed"
    seen = []
    def model(request: FrozenRecord) -> FrozenRecord:
        seen.append(request.data())
        slot = request.data()["slot"]
        if slot == "m4":
            return FrozenRecord.from_dict({"question": "q", "branches": [{"hypothesis_id": "h1", "mechanism_key": "m1", "mechanism": "one", "intervention": "i", "elimination_condition": "no", "predictions": [{"prediction_id": "p1", "discriminator_id": "d", "observable": "o", "direction": "up", "value_range": None, "failure_condition": "down"}]}, {"hypothesis_id": "h2", "mechanism_key": "m2", "mechanism": "two", "intervention": "i", "elimination_condition": "no", "predictions": [{"prediction_id": "p2", "discriminator_id": "d", "observable": "o", "direction": "down", "value_range": None, "failure_condition": "up"}]}], "budget_units": 1})
        return FrozenRecord.from_dict({"assessment": "accept", "evidence_refs": ["root"], "counterexamples": [], "uncertainty": "u"}) if slot in {"r1", "r2"} else FrozenRecord.from_dict({"ok": slot})
    workflow.propose("m4", model, instruction="propose")
    workflow.independent_review([("r1", "mechanism", "why", "a"), ("r2", "measurement", "bias", "b")], model, evidence_snapshot=session.evidence.version)
    workflow.invoke_model("m6", model, instruction="retrieve result")
    workflow.invoke_model("final", model, instruction="final")
    expected = candidate.record.data()["changes"]
    assert [row["slot"] for row in seen] == ["m4", "r1", "r2", "m6", "final"]
    assert all(row["module_context"]["deployment"] == {"package_digest": candidate.digest, "prompt": expected["prompt"], "memory": expected["memory"], "config": expected["config"]} for row in seen)
    assert all(row["objective"] == session.objective.data() for row in seen)
    assert "submissions" not in seen[1]["module_context"] and "submissions" not in seen[2]["module_context"]
    assert session.slots == ("m4", "r1", "r2", "m6", "final") and session.execution_limit == 2

    bad_session = RunSession(task, package_digest=base.digest,
        arm=default_compatibility("base").arm(["M1", "M2", "M3", "M9"]), objective=session.objective,
        slots=("final",), execution_limit=2, sidecar=tmp_path / "bad-run", verifier=AuditVerifier(AUDIT_KEYS), required_audit=("measurement",))
    blocked = ModularWorkflow(bad_session, deployment=runtime).m9_policy(None, receipt=auth.validate(candidate, base.digest, signed_validation()), candidate=candidate)
    assert blocked.status == "blocked" and blocked.detail.data()["reason"] == "candidate_lock_mismatch"
