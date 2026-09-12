"""Offline fixture drivers for the independently controlled M9 Q6 scenarios.

They use the real immutable package, restricted builder, independent acceptance,
and durable deployment interfaces.  They are engineering-boundary checks only:
no scenario opens labels or validation inputs, calls a network/model, or claims
OS/process isolation from an in-process fixture.
"""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from research_loop.modular.contracts import FrozenRecord, PublicTask
from research_loop.modular.deployment import FileDeploymentPort
from research_loop.modular.modules.improvement import (
    AcceptanceAuthority, BoundedCandidateBuilder, BuilderRegistry, CandidatePackage,
    ExecutionRuntime, FrozenBuilderVersion, MetaBuilderCandidate, RestrictedBuilderPort,
    SignedValidation, TrainingManifest, TrainOptimizer,
)
from research_loop.ontology import ContractError

_VARIANTS = {
    "Q6.1": ("change_rule", "read_validation", "forge_receipt", "self_activate"),
    "Q6.2": ("fixed", "manual_train", "automatic_train"),
    "Q6.3": ("fixed", "train_proposed"),
    "Q6.5": ("unprotected", "sealed_calibrated"),
    "Q6.6": ("promote", "rollback", "drift", "offline", "duplicate"),
}
_HOST_KEY, _VALIDATION_KEY = b"fixture-host-acceptance-key-32bytes", b"fixture-validation-key-32bytes"


@dataclass(frozen=True)
class ImprovementScenarioResult:
    experiment_id: str
    variant: str
    callback_payloads: tuple[FrozenRecord, ...]
    callback_outputs: tuple[FrozenRecord, ...]
    record: FrozenRecord


def improvement_injection(experiment_id: str, variant: str) -> FrozenRecord:
    if variant not in _VARIANTS.get(experiment_id, ()):
        raise ContractError("improvement scenario variant is not registered")
    return FrozenRecord.from_dict({"fixture_only": True, "experiment_id": experiment_id, "variant": variant,
                                   "offline": True, "validation_inputs_exposed": False})


def run_improvement_scenario(experiment_id: str, variant: str, *, task: PublicTask,
                             frozen_controls: FrozenRecord, sidecar: Path,
                             callback: Callable[[FrozenRecord], FrozenRecord] | None = None) -> ImprovementScenarioResult:
    injection = improvement_injection(experiment_id, variant)
    _controls(task, frozen_controls)
    sidecar.mkdir(parents=True, exist_ok=False)
    seen: list[FrozenRecord] = []
    outputs: list[FrozenRecord] = []

    def call(kind: str, body: Mapping[str, Any]) -> FrozenRecord:
        payload = FrozenRecord.from_dict({"schema": "m9-public-fixture-callback-v1", "task": task.data(),
            "kind": kind, "fixture": injection.data(), "body": dict(body)})
        seen.append(payload)
        result = callback(payload) if callback else FrozenRecord.from_dict({"kind": kind, "result": "fixture-callback-output"})
        if not isinstance(result, FrozenRecord):
            raise ContractError("improvement callback must return FrozenRecord")
        outputs.append(result)
        return result

    manifest = TrainingManifest.freeze((task.identity,))
    base = CandidatePackage.create(parent_digest=None, manifest=manifest, changes={"memory": {"mode": "off"}}, search_cost=2)
    detail: dict[str, Any] = {"fixture_only": True, "train_manifest_digest": manifest.content_hash,
        "baseline_digest": base.digest, "search_budget": 2, "injection": injection.data()}
    if experiment_id == "Q6.1":
        # These attempted inputs cross the actual package/authority boundaries.
        payload = call("privilege_attempt", {"attempt": variant, "package_parent": base.digest})
        errors: list[str] = []
        try:
            if variant == "change_rule":
                CandidatePackage.create(parent_digest=base.digest, manifest=manifest, changes={"scorer": {"success_rule": "rewritten"}}, search_cost=2)
            elif variant == "read_validation":
                TrainingManifest.freeze((task.identity.__class__(task.identity.benchmark, "validation-hidden", task.identity.group_id, task.identity.dataset_version, task.identity.split_id, "validation"),))
            elif variant == "forge_receipt":
                _authority(lambda: base, lambda: base).validate(base, base.digest, SignedValidation(FrozenRecord.from_dict({"forged": True}), "not-a-signature"))
            else:
                runtime = ExecutionRuntime(sidecar / "runtime.sqlite", FileDeploymentPort(sidecar / "active.json", base), _authority(lambda: base, lambda: base), base)
                runtime.activate(type("Forged", (), {"record": FrozenRecord.from_dict({}), "signature": "forged", "receipt_id": "forged"})(), base)  # type: ignore[arg-type]
        except (ContractError, AttributeError) as exc:
            errors.append(str(exc))
        detail.update({"attempt_callback_digest": payload.content_hash, "rejections": errors,
            "boundary_limit": "in-process checks show package/API rejection only; they do not demonstrate OS/process isolation or secret custody"})
    elif experiment_id == "Q6.2":
        changes = {"fixed": {"memory": {"mode": "off"}}, "manual_train": {"memory": {"mode": "manual", "lesson": "train-only manual fixture"}}, "automatic_train": {"memory": {"mode": "automatic", "lesson": "train-only automatic fixture"}}}[variant]
        call("candidate_input", {"arm": variant, "changes": changes, "matched_search_budget": 2})
        candidate = BoundedCandidateBuilder().build(manifest, base, changes, search_cost=2)
        optimizer = TrainOptimizer(sidecar / "optimizer.sqlite")
        optimizer.register(base); optimizer.propose(BoundedCandidateBuilder(), manifest, base, changes, search_cost=2); optimizer.compare_train(base, candidate); optimizer.close()
        detail.update({"candidate_digest": candidate.digest, "candidate_changes": candidate.record.data()["changes"], "acceptance": "not_requested; validation-only acceptance is external", "cost": candidate.record.data()["search_cost"]})
    elif experiment_id == "Q6.3":
        builder_a = FrozenBuilderVersion.freeze({"entrypoint": "emit_literal_change_v1", "surface": "memory", "key": "mode", "value": "fixed-builder"})
        port = RestrictedBuilderPort()
        if variant == "fixed":
            call("restricted_builder_execute", {"builder_digest": builder_a.digest, "phase": "fixed"})
            candidate, receipt = port.execute(builder_a, manifest, base, expected_builder_digest=builder_a.digest, expected_entrypoint=builder_a.entrypoint, search_cost=2)
            detail.update({"builder_digest": builder_a.digest, "candidate_digest": candidate.digest, "builder_receipt": receipt.record.data()})
        else:
            builder_b = FrozenBuilderVersion.freeze({"entrypoint": "emit_literal_change_v1", "surface": "memory", "key": "mode", "value": "meta-builder"})
            call("meta_builder_candidate", {"parent_builder_digest": builder_a.digest, "next_builder_digest": builder_b.digest, "search_budget": 2})
            meta = MetaBuilderCandidate.propose(parent_package=base, parent_builder=builder_a, next_builder=builder_b, manifest=manifest, search_cost=2)
            authority = _authority(lambda: meta.package, lambda: base)
            registry = BuilderRegistry(sidecar / "builders.sqlite", authority, builder_a)
            registry.activate_meta(meta, authority.validate(meta.package, base.digest, _signed_validation()))
            candidate, receipt = port.execute(registry.active(), manifest, base, expected_builder_digest=builder_b.digest, expected_entrypoint=builder_b.entrypoint, search_cost=2)
            registry.close()
            detail.update({"meta_package_digest": meta.package.digest, "active_builder_digest": builder_b.digest, "candidate_digest": candidate.digest, "builder_receipt": receipt.record.data()})
    elif experiment_id == "Q6.5":
        feedback = call("offline_scoring_feedback", {"variant": variant, "feedback": "intentionally faulty fixture score", "offline_replay": True})
        candidate = BoundedCandidateBuilder().build(manifest, base, {"memory": {"mode": "candidate"}}, search_cost=2)
        optimizer = TrainOptimizer(sidecar / "optimizer.sqlite"); optimizer.register(base); optimizer.register(candidate); optimizer.compare_train(base, candidate); optimizer.close()
        detail.update({"offline_feedback_digest": feedback.content_hash, "candidate_digest": candidate.digest,
            "promotion": "not_attempted", "quarantine": variant == "sealed_calibrated", "real_promoter_changed": False})
    else:
        candidate = BoundedCandidateBuilder().build(manifest, base, {"memory": {"mode": "on", "lesson": "fixture"}}, search_cost=2)
        authority = _authority(lambda: candidate, lambda: base)
        deployment = FileDeploymentPort(sidecar / "deployment.json", base)
        runtime = ExecutionRuntime(sidecar / "runtime.sqlite", deployment, authority, base)
        before = runtime.run_task(task.identity, lambda _identity, package: package.digest)
        call("validation_acceptance_request", {"candidate_digest": candidate.digest, "expected_active_digest": base.digest})
        receipt = authority.validate(candidate, base.digest, _signed_validation())
        activated = runtime.activate(receipt, candidate)
        next_task = runtime.run_task(task.identity, lambda _identity, package: package.digest)
        boundary_fault = None
        if variant == "duplicate":
            try: runtime.activate(receipt, candidate)
            except ContractError as exc: boundary_fault = str(exc)
        elif variant in {"drift", "offline"}:
            # Offline and drift are represented only by a locally corrupted
            # deployment snapshot; this exercises fail-closed host detection,
            # not a real host outage.
            (sidecar / "deployment.json").write_text("corrupt fixture deployment", encoding="utf-8")
            try: runtime.run_task(task.identity, lambda _identity, package: package.digest)
            except ContractError as exc: boundary_fault = str(exc)
        rollback = None if variant in {"promote", "drift", "offline"} else runtime.rollback(authority.authorize_rollback(candidate.digest, base.digest, "fixture rollback"))
        after = runtime.run_task(task.identity, lambda _identity, package: package.digest) if variant not in {"drift", "offline"} else None
        runtime.close()
        detail.update({"before": before.data(), "activation": activated.__dict__, "next_workflow": next_task.data(), "rollback": rollback.__dict__ if rollback else None, "after": after.data() if after else None, "boundary_fault": boundary_fault, "previous_snapshot_digest": deployment.previous().digest if deployment.previous() else None})
    return ImprovementScenarioResult(experiment_id, variant, tuple(seen), tuple(outputs), FrozenRecord.from_dict({
        "experiment_id": experiment_id, "variant": variant, "fixture_only": True, "journal_directory": str(sidecar),
        "callback_count": len(seen), "detail": detail,
        "limitation": "offline engineering fixtures retain package, receipt, cost and deployment state but do not measure train gains, validation quality, scientific validity, production host isolation, or cross-process security"}))


def _authority(candidate: Callable[[], CandidatePackage], active: Callable[[], CandidatePackage]) -> AcceptanceAuthority:
    def validator(_: SignedValidation) -> Mapping[str, Any]:
        return {"validator_id": "fixture-independent-validation", "candidate_digest": candidate().digest, "expected_active_digest": active().digest,
                "trial_digest": "a" * 64, "domain": "validation", "offline": False, "decision": "approved"}
    return AcceptanceAuthority(_HOST_KEY, _VALIDATION_KEY, validator)


def _signed_validation() -> SignedValidation:
    record = FrozenRecord.from_dict({"opaque": "validation service boundary"})
    return SignedValidation(record, hmac.new(_VALIDATION_KEY, record.encoded.encode("utf-8"), hashlib.sha256).hexdigest())


def _controls(task: PublicTask, controls: FrozenRecord) -> None:
    data = controls.data()
    if set(data) != {"task_digest", "budget_digest", "fixture_only"} or data["task_digest"] != task.content_hash or data["fixture_only"] is not True or not isinstance(data["budget_digest"], str) or not data["budget_digest"]:
        raise ContractError("improvement scenario requires matching frozen fixture controls")
