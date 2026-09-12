"""Offline M7/M8 recovery fixtures for Q3.3--Q3.5, Q5.1, and Q5.5.

These scenarios use the durable SQLite scheduler and explicit feasibility
objects.  They deliberately record engineering receipts and blocked states,
never benchmark scores or scientific conclusions.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from research_loop.modular.contracts import FrozenRecord, PublicTask, required_text
from research_loop.modular.modules.exploration import (
    ExplorationPlan, FeasibilityObservation, ResourceClosure, assess_feasibility,
)
from research_loop.modular.modules.scheduling import FifoScheduler
from research_loop.ontology import ContractError, digest


_VARIANTS = {
    "Q3.3": frozenset(("one_worker", "k_workers")),
    "Q3.4": frozenset(("favorable_first", "unfavorable_first")),
    "Q3.5": frozenset(("write_conflict", "withdrawal", "crash", "expiry", "duplicate")),
    "Q5.1": frozenset(("subjective", "data", "minimal_run", "measurement", "independent")),
    "Q5.5": frozenset(("missing_data", "missing_method", "missing_budget", "missing_control")),
}
_SNAPSHOT = {"evidence": "fixture-evidence-v1", "rules": "fixture-rules-v1", "package": "fixture-package-v1"}


@dataclass(frozen=True)
class RecoveryScenarioResult:
    experiment_id: str
    variant: str
    next_payload: FrozenRecord
    mechanism_trace: FrozenRecord
    controller_record: FrozenRecord
    next_model_response: FrozenRecord | None = None


def recovery_injection(experiment_id: str, variant: str) -> Mapping[str, Any]:
    _validate(experiment_id, variant)
    return {"fixture_only": True, "fixture_notice": "offline engineering fixture; not a benchmark or scientific measurement",
            "auxiliary": {"experiment": experiment_id, "variant": variant, "requires_public_task": True,
                          "requires_frozen_controls": True}}


def run_recovery_scenario(experiment_id: str, variant: str, *, task: PublicTask,
                          frozen_controls: FrozenRecord, sidecar: Path | None = None,
                          next_model: Callable[[FrozenRecord], Any] | None = None) -> RecoveryScenarioResult:
    """Exercise one registered fixture without reading labels, gold, or datasets."""
    _validate(experiment_id, variant)
    controls = _controls(task, frozen_controls)
    trace: list[dict[str, Any]] = [{"event": "fixture_start", "fixture_only": True,
                                     "task_digest": task.content_hash, "budget_digest": controls["budget_digest"]}]
    if experiment_id.startswith("Q3"):
        if sidecar is None:
            raise ContractError("M8 recovery fixtures require an explicit E-volume sidecar")
        auxiliary, private = _m8(experiment_id, variant, task, sidecar, trace)
    elif experiment_id == "Q5.1":
        auxiliary, private = _staged_qualification(variant, task, trace)
    else:
        auxiliary, private = _closure_rejection(variant, task, trace)
    payload = FrozenRecord.from_dict({"schema": "recovery-scenario-next-model-v1", "fixture_only": True,
        "task": task.data(), "frozen_controls": controls, "experiment_id": experiment_id, "variant": variant,
        "scenario_auxiliary": auxiliary, "mechanism_trace_digest": digest(trace)})
    response = None
    if next_model is None:
        trace.append({"event": "next_model_payload_prepared", "payload_digest": payload.content_hash})
    else:
        response = _response_record(next_model(payload))
        trace.append({"event": "next_model_invoked", "payload_digest": payload.content_hash,
                      "response_digest": response.content_hash})
    return RecoveryScenarioResult(experiment_id, variant, payload, FrozenRecord.from_dict({"events": trace}),
                                  FrozenRecord.from_dict(private), response)


def _m8(experiment_id: str, variant: str, task: PublicTask, sidecar: Path, trace: list[dict[str, Any]]):
    _safe_sidecar(sidecar)
    db = sidecar / (experiment_id.replace(".", "-") + "-" + variant + ".sqlite")
    scheduler = FifoScheduler(db, max_concurrency=1 if variant == "one_worker" else 2, total_budget=4)
    experiment = "fixture-" + experiment_id + "-" + variant
    first = scheduler.enqueue(experiment_id=experiment, task_id="first", dependencies=(), resources=("fixture-a",), cost_units=1, snapshot=_SNAPSHOT)
    second_resource = "fixture-a" if variant == "write_conflict" else "fixture-b"
    second = scheduler.enqueue(experiment_id=experiment, task_id="second", dependencies=(), resources=(second_resource,), cost_units=1, snapshot=_SNAPSHOT)
    leases = [scheduler.claim_next("fixture-worker-1", lease_seconds=30)]
    leases.append(scheduler.claim_next("fixture-worker-2", lease_seconds=30))
    active = [lease for lease in leases if lease is not None]
    private: dict[str, Any] = {"fixture_only": True, "scheduler_path": str(db), "snapshot_hash": first.snapshot_hash,
                               "initial_run_ids": [first.run_id, second.run_id], "actual_claimed_run_ids": [x.run_id for x in active]}
    if experiment_id == "Q3.3":
        # FIFO is established by run ids/queue order; the K-worker arm is only
        # permitted to claim concurrently runnable work, never a scored choice.
        if variant == "one_worker":
            assert len(active) == 1
            scheduler.complete(active[0].run_id, receipt_id="q33-one-1", receipt={"run": "first", "actual_cost": 1}, cost_units=1)
            later = scheduler.claim_next("fixture-worker-1", lease_seconds=30)
            assert later is not None
            scheduler.complete(later.run_id, receipt_id="q33-one-2", receipt={"run": "second", "actual_cost": 1}, cost_units=1)
        else:
            assert [x.task_id for x in active] == ["first", "second"]
            for index, lease in enumerate(active, 1):
                scheduler.complete(lease.run_id, receipt_id=f"q33-k-{index}", receipt={"run": lease.task_id, "actual_cost": 1}, cost_units=1)
        merged = scheduler.merge(experiment)
        auxiliary = {"fifo_policy": "fixed_monotonic_order", "worker_count": 1 if variant == "one_worker" else 2,
                     "merged_task_ids": [item.task_id for item in merged], "receipt_cost_units": 2,
                     "prediction_quality_used_for_ordering": False}
        trace.append({"event": "fifo_claim_complete_merge", **auxiliary})
    elif experiment_id == "Q3.4":
        assert len(active) == 2
        ordered = active if variant == "favorable_first" else list(reversed(active))
        first_completed = ordered[0]
        scheduler.complete(first_completed.run_id, receipt_id="q34-first-" + variant,
                           receipt={"reported_fixture_result": variant, "actual_cost": 1}, cost_units=1)
        before = scheduler.runs(experiment)
        barrier_blocked = False
        try: scheduler.merge(experiment)
        except ContractError: barrier_blocked = True
        remaining = ordered[1]
        scheduler.complete(remaining.run_id, receipt_id="q34-last-" + variant,
                           receipt={"reported_fixture_result": "other", "actual_cost": 1}, cost_units=1)
        merged = scheduler.merge(experiment)
        auxiliary = {"completion_order": [item.task_id for item in ordered], "merge_barrier_blocked": barrier_blocked,
                     "pending_snapshot_hash": next(item.snapshot_hash for item in before if item.run_id == remaining.run_id),
                     "final_snapshot_hashes": sorted({item.snapshot_hash for item in merged}),
                     "pending_context_or_rules_changed": False}
        trace.append({"event": "completion_order_barrier", **auxiliary})
    else:
        auxiliary = _fault(scheduler, experiment, variant, active, first, second, trace)
    private["final_runs"] = [item.__dict__ for item in scheduler.runs(experiment)]
    return auxiliary, private


def _fault(scheduler: FifoScheduler, experiment: str, variant: str, active, first, second, trace):
    if variant == "write_conflict":
        assert len(active) == 1 and active[0].run_id == first.run_id
        auxiliary = {"resource_conflict": True, "deferred_run_id": second.run_id, "double_execution": False}
    elif variant == "withdrawal":
        assert len(active) == 2
        invalidated = scheduler.invalidate(experiment, subjects=("fixture-b",), reason="fixture dependency withdrawn")
        auxiliary = {"withdrawn_subject": "fixture-b", "invalidated_run_ids": list(invalidated),
                     "snapshot_mutated": False, "replacement_enqueued": False}
    elif variant in {"crash", "expiry"}:
        lease = active[0]
        unknown = scheduler.expire_leases(now=10**12)
        blocked = scheduler.claim_next("no-autorerun", lease_seconds=10) is None
        scheduler.confirm_terminated(lease.run_id, termination_receipt={"confirmed": "fixture process ended"})
        recovered = scheduler.recover(lease.run_id)
        auxiliary = {"fault": variant, "unknown_run_ids": list(unknown), "autorerun_blocked": blocked,
                     "termination_confirmed": True, "recovery_attempt": recovered.attempt}
    else:  # duplicate receipt
        lease = active[0]
        scheduler.complete(lease.run_id, receipt_id="q35-duplicate", receipt={"actual_cost": 1}, cost_units=1)
        duplicate_rejected = False
        other = next(x for x in active if x.run_id != lease.run_id)
        try: scheduler.complete(other.run_id, receipt_id="q35-duplicate", receipt={"actual_cost": 1}, cost_units=1)
        except ContractError: duplicate_rejected = True
        auxiliary = {"duplicate_receipt_rejected": duplicate_rejected, "charged_cost_units": 1,
                     "receipt_retained_on_run": lease.run_id}
    trace.append({"event": "recovery_fault_exercised", **auxiliary})
    return auxiliary


def _staged_qualification(variant: str, task: PublicTask, trace: list[dict[str, Any]]):
    closure = ResourceClosure("fixture-public-data-v1", "fixture-minimal-artifact", "fixture-negative-control", 1, 0)
    plan = ExplorationPlan("fixture-stage-plan", task.identity, FrozenRecord.from_dict({"task": task.content_hash, "fixture_only": True}), closure)
    passed = {"data": FeasibilityObservation("data", "passed", "fixture-data-receipt"),
              "minimal_run": FeasibilityObservation("minimal_run", "passed", "fixture-execution-receipt"),
              "discriminating_measurement": FeasibilityObservation("discriminating_measurement", "passed", "fixture-measurement-receipt"),
              "independent_result": FeasibilityObservation("independent_result", "passed", "fixture-independent-receipt", "fixture-independent-group")}
    count = {"subjective": 0, "data": 1, "minimal_run": 2, "measurement": 3, "independent": 4}[variant]
    report = assess_feasibility(plan, {key: passed[key] for key in list(passed)[:count]})
    auxiliary = {"subjective_score": 8 if variant == "subjective" else None, "stages": dict(report.stages),
                 "next_stage": report.next_stage, "qualified": report.is_ready,
                 "zero_exit_is_scientific_claim": False, "explicit_receipt_stages": list(passed)[:count]}
    trace.append({"event": "stage_qualification", **auxiliary})
    return auxiliary, {"fixture_only": True, "plan_digest": plan.content_hash, "receipt_digests": [x.artifact_digest for x in list(passed.values())[:count]]}


def _closure_rejection(variant: str, task: PublicTask, trace: list[dict[str, Any]]):
    values = {"data_version": "fixture-data-v1", "minimum_artifact_digest": "fixture-method-artifact",
              "negative_control_id": "fixture-negative-control", "execution_units": 1, "token_units": 0}
    missing = {"missing_data": "data_version", "missing_method": "minimum_artifact_digest",
               "missing_budget": "execution_units", "missing_control": "negative_control_id"}[variant]
    values[missing] = "" if missing != "execution_units" else -1
    rejected = False
    try: ResourceClosure(**values)
    except ContractError: rejected = True
    if not rejected: raise ContractError("controlled resource closure omission was unexpectedly admitted")
    auxiliary = {"missing_requirement": missing, "resource_closure_rejected_before_execution": True,
                 "execution_started": False, "subjective_feasibility_score_is_not_substitute": True}
    trace.append({"event": "resource_closure_rejected", **auxiliary})
    return auxiliary, {"fixture_only": True, "task_digest": task.content_hash, "rejection": auxiliary}


def _controls(task: PublicTask, frozen: FrozenRecord) -> dict[str, Any]:
    data = frozen.data()
    if set(data) != {"task_digest", "budget_digest", "fixture_only"} or data["task_digest"] != task.content_hash or data["fixture_only"] is not True:
        raise ContractError("recovery scenario requires matching frozen fixture controls")
    required_text(data["budget_digest"], "budget digest")
    return data


def _safe_sidecar(sidecar: Path) -> None:
    resolved = sidecar.resolve()
    if "data" in {part.lower() for part in resolved.parts} or "labels" in {part.lower() for part in resolved.parts}:
        raise ContractError("scheduler sidecar must be outside data and labels trees")
    resolved.mkdir(parents=True, exist_ok=True)


def _response_record(value: Any) -> FrozenRecord:
    if isinstance(value, FrozenRecord): return value
    if value is None or isinstance(value, Mapping): return FrozenRecord.from_dict({"schema": "recovery-scenario-response-v1", "response": value})
    raise ContractError("next model response must be a frozen record, mapping, or None")


def _validate(experiment_id: str, variant: str) -> None:
    if variant not in _VARIANTS.get(experiment_id, ()):
        raise ContractError("recovery scenario variant is not registered")
