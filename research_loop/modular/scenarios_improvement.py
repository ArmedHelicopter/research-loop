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

from evaluation.modular.calibration import CalibrationAuthority, COVERAGE_KINDS, verify_calibration_receipt
from research_loop.modular.contracts import FrozenRecord, PublicTask
from research_loop.modular.deployment import FileDeploymentPort
from research_loop.modular.modules.improvement import (
    AcceptanceAuthority, BoundedCandidateBuilder, CandidatePackage,
    ExecutionRuntime,
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
_CALIBRATION_KEY = b"fixture-calibration-authority-key-32"


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
    task.identity.require_train()
    from research_loop.modular.scenario_artifacts import ScenarioArtifactWriter, _safe_root
    _safe_root(sidecar)
    sidecar.mkdir(parents=True, exist_ok=False)
    if experiment_id == "Q6.3":
        from research_loop.modular.fixture_builder_artifacts import run_q63_fixture
        return run_q63_fixture(task=task,frozen_controls=frozen_controls,sidecar=sidecar,variant=variant,callback=callback)
    writer = ScenarioArtifactWriter(sidecar, task=task, controls=frozen_controls,
                                    injection=injection, experiment_id=experiment_id, variant=variant)
    seen: list[FrozenRecord] = []
    outputs: list[FrozenRecord] = []

    def call(kind: str, body: Mapping[str, Any]) -> FrozenRecord:
        payload = FrozenRecord.from_dict({"schema": "m9-public-fixture-callback-v1", "task": task.data(),
            "kind": kind, "fixture": injection.data(), "body": dict(body)})
        seen.append(payload)
        writer.callback_request(payload)
        try:
            result = callback(payload) if callback else FrozenRecord.from_dict({"kind": kind, "result": "fixture-callback-output"})
        except Exception as exc:
            writer.callback_failure(exc)
            raise
        writer.callback_return(result)
        if type(result) is not FrozenRecord:
            raise ContractError("improvement callback must return FrozenRecord")
        outputs.append(result)
        return result

    try:
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
                try:
                    runtime.activate(type("Forged", (), {"record": FrozenRecord.from_dict({}), "signature": "forged", "receipt_id": "forged"})(), base)  # type: ignore[arg-type]
                finally:
                    runtime.close()
        except (ContractError, AttributeError) as exc:
            errors.append(str(exc))
        detail.update({"attempt_callback_digest": payload.content_hash, "rejections": errors,
            "boundary_limit": "in-process checks show package/API rejection only; they do not demonstrate OS/process isolation or secret custody"})
      elif experiment_id == "Q6.2":
        manual = {"memory": {"mode": "manual", "lesson": "predeclared train-only fixture"}}
        proposal = None if variant == "fixed" else call("train_candidate_proposal", {"arm": variant, "fixed_base_digest": base.digest, "manual_changes": manual, "matched_search_budget": 2})
        changes, rejected = (None if variant == "fixed" else manual if variant == "manual_train" else None), None
        if variant == "automatic_train":
            try:
                body = proposal.data()
                # The callback must supply precisely the restricted candidate
                # changes; malformed/unknown surfaces remain a recorded reject.
                changes = body["changes"] if set(body) == {"changes"} else None
                if changes is None: raise ContractError("automatic proposal has no closed changes field")
                CandidatePackage.create(parent_digest=base.digest, manifest=manifest, changes=changes, search_cost=2)
            except (ContractError, KeyError, TypeError) as exc:
                rejected = str(exc); changes = None
        candidate = base if variant == "fixed" else None
        if changes is not None:
            candidate = BoundedCandidateBuilder().build(manifest, base, changes, search_cost=2)
            optimizer = TrainOptimizer(sidecar / "optimizer.sqlite")
            try:
                optimizer.register(base); optimizer.propose(BoundedCandidateBuilder(), manifest, base, changes, search_cost=2); optimizer.compare_train(base, candidate)
            finally:
                optimizer.close()
        detail.update({"proposal_digest": proposal.content_hash if proposal else None, "candidate_digest": candidate.digest if candidate else None, "candidate_changes": candidate.record.data()["changes"] if candidate and variant != "fixed" else None, "rejected": rejected, "acceptance": "not_requested; validation-only acceptance is external", "cost": 0 if variant == "fixed" else 2, "fixed_identity_preserved": variant != "fixed" or candidate.digest == base.digest, "callback_calls": len(seen)})
      elif experiment_id == "Q6.5":
        rounds, parent, bad_experience = [], base, 0
        deployment = FileDeploymentPort(sidecar / "shadow-deployment.json", base)
        # One authority remains installed for the whole shadow run.  Each
        # signed fixture request binds its candidate and current parent, so a
        # later activation cannot be authorized against an earlier parent.
        shadow_authority = _shadow_authority()
        runtime = ExecutionRuntime(sidecar / "shadow-runtime.sqlite", deployment, shadow_authority, base)
        activation_count = 0
        try:
          for round_id in range(2):
              feedback = call("offline_scoring_feedback", {"round": round_id, "variant": variant, "feedback": "intentionally faulty fixture score", "offline_replay": True, "budget": 2})
              bad_experience += 1
              parent_before = parent.digest
            # The retained callback output is part of the package material;
            # this is a real two-round parent chain, albeit an offline fixture.
              candidate = BoundedCandidateBuilder().build(manifest, parent, {"memory": {"mode": "shadow", "lesson": "fixture-feedback-" + feedback.content_hash}}, search_cost=2)
              decision, active_after, error = "not_attempted", runtime.active().digest, None
              if variant == "unprotected":
                  receipt = shadow_authority.validate(candidate, parent.digest, _signed_shadow_validation(candidate.digest, parent.digest))
                  ack = runtime.activate(receipt, candidate); parent = candidate
                  activation_count += 1
                  decision, active_after = "offline_shadow_activated", ack.active_digest
              else:
                # The calibration receipt is correctly authenticated and binds
                # these exact digests.  It fails eligibility (not its MAC), so
                # no acceptance receipt or activation can be reached.
                  bad = _signed_calibration(parent.digest, base.digest, frozen_controls.content_hash, eligible=False)
                  try:
                      _activate_with_calibration_guard(runtime, shadow_authority, candidate, parent.digest, bad,
                                                        scorer_digest=base.digest, protocol_digest=frozen_controls.content_hash)
                  except ContractError as exc:
                      error = str(exc); decision = "calibration_eligibility_rejected"
              rounds.append({"round": round_id, "feedback_digest": feedback.content_hash, "budget": 2, "parent_digest_before": parent_before, "candidate_digest": candidate.digest, "bad_experience_count": bad_experience, "authority_decision": decision, "active_digest_after": active_after, "activation_attempted": variant == "unprotected", "calibration_receipt_digest": bad.content_hash if variant != "unprotected" else None, "calibration_eligible": None if variant == "unprotected" else False, "rejection": error, "scientific_effect_status": "not_measured"})
        finally:
            runtime.close()
        detail.update({"offline_shadow_rounds": rounds, "promotion": "offline_shadow_activation" if variant == "unprotected" else "calibration_eligibility_rejected", "real_promoter_changed": variant == "unprotected", "activation_count": activation_count, "oracle_visibility": "controller_only_not_callback", "scientific_calibration_claimed": False, "scientific_effect_status": "not_measured"})
      else:
        candidate = BoundedCandidateBuilder().build(manifest, base, {"memory": {"mode": "on", "lesson": "fixture"}}, search_cost=2)
        authority = _authority(lambda: candidate, lambda: base)
        deployment = FileDeploymentPort(sidecar / "deployment.json", base)
        runtime = ExecutionRuntime(sidecar / "runtime.sqlite", deployment, authority, base)
        try:
          before = runtime.run_task(task.identity, lambda _identity, package: package.digest)
          call("validation_acceptance_request", {"candidate_digest": candidate.digest, "expected_active_digest": base.digest})
          receipt = authority.validate(candidate, base.digest, _signed_validation())
          activated = runtime.activate(receipt, candidate)
          next_task = runtime.run_task(task.identity, lambda _identity, package: package.digest)
          boundary_fault = None
          if variant == "duplicate":
            try: runtime.activate(receipt, candidate)
            except ContractError as exc: boundary_fault = str(exc)
          elif variant == "drift":
            # A complete, hash-valid snapshot of the parent is unexpected by
            # runtime state, so this is digest drift rather than corruption.
            deployment.activate(base, candidate.digest)
            try: runtime.run_task(task.identity, lambda _identity, package: package.digest)
            except ContractError as exc: boundary_fault = str(exc)
          elif variant == "offline":
            # Transport-specific fixture failure: state stays complete, but the
            # deployment port's dedicated transport wrapper reports unavailable.
            class OfflineTransport:
                def activate(self, package, expected_active_digest): return deployment.activate(package, expected_active_digest)
                def current(self):
                    current = deployment.current()
                    return type(current)(current.active_digest, current.memory_digest, False)
            runtime._deployment = OfflineTransport()  # owned runtime seam, fixture transport fault
            try: runtime.run_task(task.identity, lambda _identity, package: package.digest)
            except ContractError as exc: boundary_fault = str(exc)
          rollback = None if variant in {"promote", "drift", "offline"} else runtime.rollback(authority.authorize_rollback(candidate.digest, base.digest, "fixture rollback"))
          after = runtime.run_task(task.identity, lambda _identity, package: package.digest) if variant not in {"drift", "offline"} else None
        finally:
            runtime.close()
        detail.update({"before": before.data(), "activation": activated.__dict__, "next_workflow": next_task.data(), "rollback": rollback.__dict__ if rollback else None, "after": after.data() if after else None, "boundary_fault": boundary_fault, "previous_snapshot_digest": deployment.previous().digest if deployment.previous() else None})
      result = ImprovementScenarioResult(experiment_id, variant, tuple(seen), tuple(outputs), FrozenRecord.from_dict({
          "experiment_id": experiment_id, "variant": variant, "fixture_only": True, "journal_directory": str(sidecar),
          "callback_count": len(seen), "detail": detail,
          "limitation": "offline engineering fixtures retain package, receipt, cost and deployment state but do not measure train gains, validation quality, scientific validity, production host isolation, or cross-process security"}))
      writer.close(result=result)
      verify_scenario_artifacts(result, task=task, frozen_controls=frozen_controls,
                                sidecar=sidecar, experiment_id=experiment_id, variant=variant)
      return result
    except Exception as exc:
      if not writer.ended:
          try:
              writer.close(error=exc)
          except Exception as journal_error:
              exc.add_note("scenario artifact closure failure: " + type(journal_error).__name__)
      raise


def _authority(candidate: Callable[[], CandidatePackage], active: Callable[[], CandidatePackage]) -> AcceptanceAuthority:
    def validator(_: SignedValidation) -> Mapping[str, Any]:
        return {"validator_id": "fixture-independent-validation", "candidate_digest": candidate().digest, "expected_active_digest": active().digest,
                "trial_digest": "a" * 64, "domain": "validation", "offline": False, "decision": "approved"}
    return AcceptanceAuthority(_HOST_KEY, _VALIDATION_KEY, validator)


def _signed_validation() -> SignedValidation:
    record = FrozenRecord.from_dict({"opaque": "validation service boundary"})
    return SignedValidation(record, hmac.new(_VALIDATION_KEY, record.encoded.encode("utf-8"), hashlib.sha256).hexdigest())


def _shadow_authority() -> AcceptanceAuthority:
    """Stable offline authority whose signed request binds each parent link."""
    def validator(validation: SignedValidation) -> Mapping[str, Any]:
        data = validation.record.data()
        if set(data) != {"candidate_digest", "expected_active_digest"}:
            raise ContractError("shadow validation has an exact request schema")
        return {"validator_id": "offline-shadow-fixture-validation", "candidate_digest": data["candidate_digest"],
                "expected_active_digest": data["expected_active_digest"], "trial_digest": "a" * 64,
                "domain": "validation", "offline": False, "decision": "approved"}
    return AcceptanceAuthority(_HOST_KEY, _VALIDATION_KEY, validator)


def _signed_shadow_validation(candidate_digest: str, expected_active_digest: str) -> SignedValidation:
    record = FrozenRecord.from_dict({"candidate_digest": candidate_digest, "expected_active_digest": expected_active_digest})
    return SignedValidation(record, hmac.new(_VALIDATION_KEY, record.encoded.encode("utf-8"), hashlib.sha256).hexdigest())


def _signed_calibration(panel_digest: str, scorer_digest: str, protocol_digest: str, *, eligible: bool) -> FrozenRecord:
    """Create signed synthetic calibration material for engineering guard checks."""
    criteria = {"minimum_cases_per_benchmark": 9, "minimum_coverage": {kind: 1 for kind in COVERAGE_KINDS},
                "minimum_precision": 0.8, "minimum_recall": 0.8, "maximum_abstention_rate": 0.2,
                "maximum_uncertainty": 0.2}
    benchmarks = ["blade", "discoverybench"]
    coverage = {kind: 1 for kind in COVERAGE_KINDS}
    # Both bodies have valid schemas and MACs.  Only the negative controller
    # violates frozen precision/recall; neither body measures a real scorer.
    matrix = {"tp": 4, "tn": 4, "fp": 0, "fn": 0, "abstained": 1} if eligible else {"tp": 0, "tn": 0, "fp": 4, "fn": 4, "abstained": 1}
    from research_loop.ontology import digest
    return CalibrationAuthority("fixture-calibration-authority", _CALIBRATION_KEY).issue({
        "schema": "scorer-calibration-v1", "panel_digest": panel_digest, "scorer_digest": scorer_digest,
        "protocol_digest": protocol_digest, "scorer_code_digest": "d" * 64, "judge_identity": "fixture-judge",
        "judge_parameters": {"temperature": 0}, "rubric_digest": "e" * 64,
        "calibration_manifest_digest": "f" * 64, "blind_review_protocol_digest": "1" * 64,
        "arbitration_protocol_digest": "2" * 64, "applicable_benchmarks": benchmarks,
        "criteria": criteria, "criteria_digest": digest(criteria),
        "coverage": {benchmark: coverage for benchmark in benchmarks},
        "confusion_matrix": {benchmark: matrix for benchmark in benchmarks},
        "uncertainty": {benchmark: 0.1 for benchmark in benchmarks},
    })


def _activate_with_calibration_guard(runtime: ExecutionRuntime, authority: AcceptanceAuthority,
                                     candidate: CandidatePackage, expected_active_digest: str,
                                     calibration_receipt: FrozenRecord, *, scorer_digest: str,
                                     protocol_digest: str):
    """The closed sequence used by both positive and negative guard controls."""
    verify_calibration_receipt(calibration_receipt, {"fixture-calibration-authority": _CALIBRATION_KEY},
                               panel_digest=expected_active_digest, scorer_digest=scorer_digest,
                               protocol_digest=protocol_digest)
    acceptance = authority.validate(candidate, expected_active_digest,
                                    _signed_shadow_validation(candidate.digest, expected_active_digest))
    return runtime.activate(acceptance, candidate)


def _controls(task: PublicTask, controls: FrozenRecord) -> None:
    data = controls.data()
    if set(data) != {"task_digest", "budget_digest", "fixture_only"} or data["task_digest"] != task.content_hash or data["fixture_only"] is not True or not isinstance(data["budget_digest"], str) or not data["budget_digest"]:
        raise ContractError("improvement scenario requires matching frozen fixture controls")


def verify_q63_fixture_artifacts(result: ImprovementScenarioResult, *, task: PublicTask,
                                 frozen_controls: FrozenRecord, sidecar: Path, variant: str) -> FrozenRecord:
    """Read original Q6.3 fixture outputs without rerunning callbacks or activation."""
    from research_loop.modular.fixture_builder_artifacts import verify_q63_fixture
    return verify_q63_fixture(result,task=task,frozen_controls=frozen_controls,sidecar=sidecar,variant=variant)


def inspect_q63_fixture_failure(*, task: PublicTask, frozen_controls: FrozenRecord,
                                sidecar: Path, variant: str) -> FrozenRecord:
    """Inspect failed fixture storage without treating it as accepted execution."""
    from research_loop.modular.fixture_builder_artifacts import inspect_q63_fixture_failure as inspect_failure
    return inspect_failure(task=task,frozen_controls=frozen_controls,sidecar=sidecar,variant=variant)


def verify_scenario_artifacts(result: ImprovementScenarioResult, *, task: PublicTask,
                              frozen_controls: FrozenRecord, sidecar: Path,
                              experiment_id: str, variant: str) -> FrozenRecord:
    """Read original non-Q6.3 fixture outputs without replaying the operation."""
    if experiment_id == "Q6.3":
        raise ContractError("Q6.3 retains its dedicated fixture artifact adapter")
    from research_loop.modular.scenario_artifacts import verify_scenario_artifacts as verify
    return verify(result, task=task, frozen_controls=frozen_controls, sidecar=sidecar,
                  experiment_id=experiment_id, variant=variant)


def inspect_scenario_artifact_failure(*, task: PublicTask, frozen_controls: FrozenRecord,
                                      sidecar: Path, experiment_id: str, variant: str) -> FrozenRecord:
    """Read a non-Q6.3 failed prefix without accepting its operation semantics."""
    if experiment_id == "Q6.3":
        raise ContractError("Q6.3 retains its dedicated fixture artifact adapter")
    from research_loop.modular.scenario_artifacts import inspect_scenario_failure
    return inspect_scenario_failure(task=task, frozen_controls=frozen_controls, sidecar=sidecar,
                                    experiment_id=experiment_id, variant=variant)
