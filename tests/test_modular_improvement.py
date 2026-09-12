from __future__ import annotations

import hashlib
import hmac
from pathlib import Path

import pytest

from research_loop.modular.contracts import DataIdentity, FrozenRecord
from research_loop.modular.modules.improvement import (
    AcceptanceAuthority, BoundedCandidateBuilder, BuilderRegistry, CandidatePackage, DeploymentAck,
    ExecutionRuntime, FrozenBuilderVersion, MetaBuilderCandidate, RestrictedBuilderPort,
    SignedValidation, TrainingManifest, TrainOptimizer,
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


def test_second_metaprogram_phase_executes_frozen_builder_then_switches_next_round(tmp_path: Path) -> None:
    base = baseline()
    builder_a = FrozenBuilderVersion.freeze({"entrypoint": "emit_literal_change_v1", "surface": "memory", "key": "mode", "value": "builder-a"})
    builder_b = FrozenBuilderVersion.freeze({"entrypoint": "emit_literal_change_v1", "surface": "memory", "key": "mode", "value": "builder-b"})
    port = RestrictedBuilderPort()
    out_a, receipt_a = port.execute(builder_a, manifest(), base, expected_builder_digest=builder_a.digest,
                                    expected_entrypoint=builder_a.entrypoint, search_cost=2)
    meta = MetaBuilderCandidate.propose(parent_package=base, parent_builder=builder_a, next_builder=builder_b,
                                        manifest=manifest(), search_cost=2)
    candidate_box.update(candidate=meta.package, active=base.digest)
    registry = BuilderRegistry(tmp_path / "builders.sqlite", authority(), builder_a)
    registry.activate_meta(meta, authority().validate(meta.package, base.digest, signed_validation()))
    out_b, receipt_b = port.execute(registry.active(), manifest(), base, expected_builder_digest=builder_b.digest,
                                    expected_entrypoint=builder_b.entrypoint, search_cost=2)
    assert out_a.record.data()["changes"]["memory"]["mode"] == "builder-a"
    assert out_b.record.data()["changes"]["memory"]["mode"] == "builder-b"
    assert receipt_a.record.data()["output_candidate_digest"] == out_a.digest
    assert receipt_b.record.data()["builder_digest"] == builder_b.digest
    registry.close()


def test_validation_and_privileged_surfaces_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(ContractError):
        TrainingManifest.freeze([task("validation-task", "validation")])
    with pytest.raises(ContractError):
        CandidatePackage.create(manifest=manifest(), parent_digest=None, changes={"scorer": {"x": 1}}, search_cost=1)
    with pytest.raises(ContractError):
        CandidatePackage.create(manifest=manifest(), parent_digest=None, changes={"prompt": {}}, search_cost=1, phase="metaprogram")
    optimizer = TrainOptimizer(tmp_path / "optimizer.sqlite")
    with pytest.raises(ContractError, match="matched search cost"):
        optimizer.compare_train(baseline(), CandidatePackage.create(manifest=manifest(), parent_digest=None, changes={"config": {"max_steps": 1}}, search_cost=3))
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


def test_factory_bypass_and_builder_drift_are_rejected_at_composition_boundaries(tmp_path: Path) -> None:
    validation_manifest = FrozenRecord.from_dict({"domain": "train", "identities": [task("private", "validation").data()]})
    with pytest.raises(ContractError, match="training provenance"):
        TrainingManifest(validation_manifest)
    forged = FrozenRecord.from_dict({"parent_digest": None, "training_manifest": manifest().record.data(),
                                     "training_manifest_digest": manifest().content_hash, "changes": {"config": {"custody": "rewrite"}},
                                     "search_cost": False, "phase": "candidate"})
    with pytest.raises(ContractError):
        CandidatePackage(forged)
    builder = FrozenBuilderVersion.freeze({"entrypoint": "emit_literal_change_v1", "surface": "memory", "key": "mode", "value": "safe"})
    with pytest.raises(ContractError, match="source drift"):
        RestrictedBuilderPort().execute(builder, manifest(), baseline(), expected_builder_digest="a" * 64,
                                        expected_entrypoint=builder.entrypoint, search_cost=2)
    with pytest.raises(ContractError, match="entrypoint drift"):
        RestrictedBuilderPort().execute(builder, manifest(), baseline(), expected_builder_digest=builder.digest,
                                        expected_entrypoint="other", search_cost=2)
    class ForgingBuilder:
        def build(self, *_args, **_kwargs):
            return CandidatePackage.create(manifest=manifest(), parent_digest=None, changes={"memory": {"mode": "bad"}}, search_cost=2)
    with pytest.raises(ContractError, match="outside its train-only contract"):
        TrainOptimizer(tmp_path / "optimizer.sqlite").propose(ForgingBuilder(), manifest(), baseline(), {"memory": {"mode": "on"}}, search_cost=2)
