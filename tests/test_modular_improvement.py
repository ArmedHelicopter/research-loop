from __future__ import annotations

import hashlib
import hmac
from pathlib import Path

import pytest

from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.modular.modules.improvement import (
    AcceptanceAuthority, BoundedCandidateBuilder, CandidatePackage, DeploymentAck,
    ExecutionRuntime, SignedValidation, TrainingManifest, TrainOptimizer,
)
from research_loop.ontology import ContractError


KEY = b"host-held-acceptance-key-32-bytes"
VALIDATION_KEY = b"host-held-validation-key-32-bytes"


def task(task_id: str, domain: str = "train") -> DataIdentity:
    return DataIdentity("discoverybench", task_id, f"group-{task_id}", "fixture-v1", "fixture-split", domain)


class FakeDeployment:
    def __init__(self, package: CandidatePackage) -> None:
        self.package = package
        self.online = True

    def activate(self, package: CandidatePackage, expected_active_digest: str) -> DeploymentAck:
        if not self.online or expected_active_digest != self.package.digest:
            return DeploymentAck("drift", "drift", False)
        self.package = package
        return self.current()

    def current(self) -> DeploymentAck:
        return DeploymentAck(self.package.digest, self.package.memory_digest, self.online)


def manifest() -> TrainingManifest:
    return TrainingManifest.freeze([task("train-a"), task("train-b")])


def baseline() -> CandidatePackage:
    return CandidatePackage.create(manifest=manifest(), parent_digest=None, changes={"memory": {"mode": "off"}}, search_cost=2)


def authority() -> AcceptanceAuthority:
    def validator(_: SignedValidation) -> dict[str, object]:
        return {
            "validator_id": "independent-validator", "candidate_digest": candidate_box["candidate"].digest,
            "expected_active_digest": candidate_box["active"], "trial_digest": "a" * 64,
            "domain": "validation", "offline": False, "decision": "approved",
        }
    return AcceptanceAuthority(KEY, VALIDATION_KEY, validator)


candidate_box: dict[str, object] = {}


def signed_validation() -> SignedValidation:
    record = FrozenRecord.from_dict({"opaque": "independent-validation-service"})
    signature = hmac.new(VALIDATION_KEY, record.encoded.encode("utf-8"), hashlib.sha256).hexdigest()
    return SignedValidation(record, signature)


def test_train_only_candidate_and_real_on_off_on_activation_rollback(tmp_path: Path) -> None:
    base = baseline()
    build = BoundedCandidateBuilder()
    candidate = build.build(manifest(), base, {"memory": {"mode": "on", "lesson": "train-only"}}, search_cost=2)
    optimizer = TrainOptimizer(tmp_path / "optimizer.sqlite")
    optimizer.register(base)
    optimizer.propose(build, manifest(), base, {"memory": {"mode": "on", "lesson": "train-only"}}, search_cost=2)
    optimizer.compare_train(base, candidate)
    deployment = FakeDeployment(base)
    candidate_box.update(candidate=candidate, active=base.digest)
    auth = authority()
    runtime = ExecutionRuntime(tmp_path / "runtime.sqlite", deployment, auth, base)
    first = runtime.run_task(task("next-off"), lambda _task, package: package.record.data()["changes"]["memory"]["mode"])
    receipt = auth.validate(candidate, base.digest, signed_validation())
    runtime.activate(receipt, candidate)
    second = runtime.run_task(task("next-on"), lambda _task, package: package.record.data()["changes"]["memory"]["mode"])
    rollback = auth.authorize_rollback(candidate.digest, base.digest, "fixture rollback")
    runtime.rollback(rollback)
    third = runtime.run_task(task("next-off-again"), lambda _task, package: package.record.data()["changes"]["memory"]["mode"])
    assert (first.data()["result"], second.data()["result"], third.data()["result"]) == ("off", "on", "off")
    assert third.data()["active_digest"] == base.digest
    assert third.data()["memory_digest"] == base.memory_digest
    runtime.close()
    reopened = ExecutionRuntime(tmp_path / "runtime.sqlite", deployment, auth, base)
    assert reopened.run_task(task("reopened"), lambda _task, package: package.record.data()["changes"]["memory"]["mode"]).data()["result"] == "off"
    reopened.close()
    optimizer.close()


def test_second_metaprogram_phase_binds_builder_source_and_entrypoint(tmp_path: Path) -> None:
    base = baseline()
    source = hashlib.sha256(b"frozen CandidateBuilder source").hexdigest()
    builder = BoundedCandidateBuilder(phase="metaprogram", source_digest=source, entrypoint="build_candidate")
    candidate = TrainOptimizer(tmp_path / "optimizer.sqlite").propose(
        builder, manifest(), base, {"prompt": {"style": "train-only-meta"}}, search_cost=2)
    data = candidate.record.data()
    assert data["phase"] == "metaprogram"
    assert data["builder_source_digest"] == source
    assert data["builder_entrypoint"] == "build_candidate"
    assert data["training_manifest"]["domain"] == "train"


def test_validation_and_privileged_surfaces_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(ContractError):
        TrainingManifest.freeze([task("validation-task", "validation")])
    with pytest.raises(ContractError):
        CandidatePackage.create(manifest=manifest(), parent_digest=None, changes={"scorer": {"x": 1}}, search_cost=1)
    with pytest.raises(ContractError):
        CandidatePackage.create(manifest=manifest(), parent_digest=None, changes={"prompt": {}}, search_cost=1, phase="metaprogram")
    optimizer = TrainOptimizer(tmp_path / "optimizer.sqlite")
    with pytest.raises(ContractError, match="matched search cost"):
        optimizer.compare_train(baseline(), CandidatePackage.create(manifest=manifest(), parent_digest=None, changes={"config": {"x": 1}}, search_cost=3))
    optimizer.close()


def test_drift_offline_and_replayed_receipts_fail_closed(tmp_path: Path) -> None:
    base = baseline()
    candidate = BoundedCandidateBuilder().build(manifest(), base, {"memory": {"mode": "on"}}, search_cost=2)
    deployment = FakeDeployment(base)
    candidate_box.update(candidate=candidate, active=base.digest)
    auth = authority()
    runtime = ExecutionRuntime(tmp_path / "runtime.sqlite", deployment, auth, base)
    receipt = auth.validate(candidate, base.digest, signed_validation())
    deployment.online = False
    with pytest.raises(ContractError, match="offline"):
        runtime.activate(receipt, candidate)
    deployment.online = True
    runtime.activate(receipt, candidate)
    with pytest.raises(ContractError, match="already consumed"):
        runtime.activate(receipt, candidate)
    deployment.package = base
    with pytest.raises(ContractError, match="drift"):
        runtime.run_task(task("drifted"), lambda _task, package: package.digest)
    runtime.close()


def test_unsigned_validation_cannot_be_converted_to_acceptance() -> None:
    base = baseline()
    candidate = BoundedCandidateBuilder().build(manifest(), base, {"memory": {"mode": "on"}}, search_cost=2)
    candidate_box.update(candidate=candidate, active=base.digest)
    with pytest.raises(ContractError, match="validation receipt signature"):
        authority().validate(candidate, base.digest, SignedValidation(FrozenRecord.from_dict({"opaque": "forged"}), "forged"))
