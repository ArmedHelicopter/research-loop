"""Formal train-only Q3.3--Q3.5 drivers over the durable M8 scheduler.

The caller freezes public task-specific work, resource locks, and completion
orders in a typed bundle.  This module never invents a fixture endpoint or
uses a model response to select FIFO work.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, MutableMapping

from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask, required_text
from research_loop.modular.modules.scheduling import FifoScheduler, TaskLease
from research_loop.modular.panel_receipts import PanelCell, opaque_panel_cell_binding
from research_loop.modular.workflow import ModularWorkflow, WorkflowResult
from research_loop.ontology import ContractError


_VARIANTS = {
    "Q3.3": frozenset(("one_worker", "k_workers")),
    "Q3.4": frozenset(("favorable_first", "unfavorable_first")),
    "Q3.5": frozenset(("write_conflict", "withdrawal", "crash", "expiry", "duplicate")),
}
BundleResolver = Callable[[PublicTask, FrozenRecord], FrozenRecord]


def freeze_scheduler_bundle(task: PublicTask, *, snapshot: Mapping[str, str], schedules: Mapping[str, Mapping[str, Mapping[str, Any]]]) -> FrozenRecord:
    """Freeze caller-owned public scheduler material for all Q3 M8 variants."""
    if not isinstance(task, PublicTask) or not isinstance(snapshot, Mapping) or not isinstance(schedules, Mapping):
        raise ContractError("scheduler bundle needs a typed public task and caller schedules")
    body = {"schema": "typed-m8-scheduler-panel-bundle-v1", "identity": task.identity.data(),
            "snapshot": dict(snapshot), "schedules": {key: {variant: dict(item) for variant, item in values.items()}
                                                        for key, values in schedules.items()}}
    _validate_bundle(task, body)
    return FrozenRecord.from_dict(body)


def select_scheduler_material(bundle: FrozenRecord, task: PublicTask, experiment_id: str, variant: str) -> FrozenRecord:
    body = bundle.data(); _validate_bundle(task, body)
    if variant not in _VARIANTS.get(experiment_id, ()):
        raise ContractError("scheduler driver variant is not registered")
    return FrozenRecord.from_dict({"schema": "typed-selected-m8-scheduler-material-v1", "identity": task.identity.data(),
                                    "experiment_id": experiment_id, "snapshot": body["snapshot"],
                                    **body["schedules"][experiment_id][variant]})


def scheduler_panel_injection(experiment_id: str, variant: str, *, task: FrozenRecord, evidence: FrozenRecord) -> Mapping[str, Any]:
    """Expose only a caller bundle reference to the controller, never a fixture result."""
    body = task.data()
    public = PublicTask(DataIdentity.parse(body["identity"]), FrozenRecord.from_dict(body["payload"]))
    select_scheduler_material(evidence, public, experiment_id, variant)
    return {"schema": "scheduler-panel-controller-v1", "material_bundle": evidence.data()}


def _validate_bundle(task: PublicTask, body: Mapping[str, Any]) -> None:
    if (set(body) != {"schema", "identity", "snapshot", "schedules"} or body["schema"] != "typed-m8-scheduler-panel-bundle-v1"
            or body["identity"] != task.identity.data() or not isinstance(body["snapshot"], Mapping)
            or set(body["snapshot"]) != {"evidence", "rules", "package"} or not all(isinstance(value, str) and value for value in body["snapshot"].values())
            or not isinstance(body["schedules"], Mapping) or set(body["schedules"]) != set(_VARIANTS)):
        raise ContractError("scheduler bundle has an invalid identity, snapshot, or coverage")
    for experiment_id, variants in _VARIANTS.items():
        rows = body["schedules"][experiment_id]
        if not isinstance(rows, Mapping) or set(rows) != variants:
            raise ContractError("scheduler bundle does not cover every registered variant")
        for variant, row in rows.items():
            if not isinstance(row, Mapping) or set(row) != {"jobs", "completion_order", "withdraw_subjects"}:
                raise ContractError("scheduler schedule has invalid fields")
            jobs = row["jobs"]
            if not isinstance(jobs, list) or len(jobs) != 2 or any(not isinstance(job, Mapping) for job in jobs):
                raise ContractError("scheduler schedule needs two typed work items")
            expected = {"task_id", "dependencies", "resources", "cost_units"}
            if any(set(job) != expected or not isinstance(job["task_id"], str) or not job["task_id"]
                   or not isinstance(job["dependencies"], list) or not isinstance(job["resources"], list)
                   or type(job["cost_units"]) is not int or job["cost_units"] <= 0 for job in jobs):
                raise ContractError("scheduler work item is malformed")
            ids = [job["task_id"] for job in jobs]
            if len(set(ids)) != len(ids) or row["completion_order"] not in (ids, list(reversed(ids))):
                raise ContractError("scheduler completion order must name the two FIFO work items")
            if not isinstance(row["withdraw_subjects"], list) or any(not isinstance(item, str) or not item for item in row["withdraw_subjects"]):
                raise ContractError("scheduler withdrawal subjects are malformed")


def _resolve(resolver: BundleResolver | None, task: PublicTask, scenario: FrozenRecord, experiment_id: str, variant: str) -> FrozenRecord:
    controller = scenario.data().get("controller_input")
    if isinstance(controller, Mapping) and controller.get("schema") == "scheduler-panel-controller-v1":
        bundle = FrozenRecord.from_dict(controller["material_bundle"])
    elif resolver is not None:
        bundle = resolver(task, scenario)
    else:
        raise ContractError("scheduler panel driver requires a caller bundle resolver")
    if not isinstance(bundle, FrozenRecord) or bundle.content_hash != scenario.data().get("base", {}).get("evidence"):
        raise ContractError("scheduler bundle does not match frozen scenario evidence")
    return select_scheduler_material(bundle, task, experiment_id, variant)


def _claim(scheduler: FifoScheduler, worker: str) -> TaskLease | None:
    return scheduler.claim_next(worker, lease_seconds=30)


def _receipt(lease: TaskLease) -> FrozenRecord:
    return FrozenRecord.from_dict({"schema": "m8-public-work-receipt-v1", "task_id": lease.task_id,
                                    "attempt": lease.attempt, "cost_units": lease.cost_units})


def _complete(scheduler: FifoScheduler, lease: TaskLease) -> None:
    receipt = _receipt(lease)
    scheduler.complete(lease.run_id, receipt_id=receipt.content_hash, receipt=receipt.data(), cost_units=lease.cost_units)


@dataclass(frozen=True)
class M8SchedulerDriver:
    experiment_id: str
    material_resolver: BundleResolver | None = None
    slots: tuple[str, ...] = ("final",)
    execution_limit: int = 0
    docker_execution: str = "not_requested_by_driver"

    def slots_for(self, cell: PanelCell) -> tuple[str, ...]:
        return self.slots

    def run(self, workflow: ModularWorkflow, *, cell: PanelCell, scenario: FrozenRecord, model, package):
        material = _resolve(self.material_resolver, workflow.session.task, scenario, self.experiment_id, cell.variant).data()
        observation = _run_scheduler(workflow.session.sidecar, cell, material)
        # The model receives public task material and an opaque cell binding only;
        # no arm, variant, package, controller, or outcome label is exposed.
        candidate = workflow.invoke_model("final", model, instruction=(
            "Return a bounded train-only candidate. Set outcome to unknown, evidence_ids to an empty list, "
            "programme_complete to false, and copy required_objective_digest exactly."),
            module_context=FrozenRecord.from_dict({"panel_cell": opaque_panel_cell_binding(cell),
                "public_task": workflow.session.task.data(), "scheduler_observation": _model_observation(observation),
                "required_objective_digest": workflow.session.objective.content_hash}))
        body = candidate.data()
        if (body.get("objective_digest") != workflow.session.objective.content_hash or body.get("outcome") != "unknown"
                or body.get("evidence_ids") != [] or body.get("programme_complete") is not False):
            raise ContractError("scheduler driver final candidate is invalid")
        stage = workflow._trace("stage_8" if "M8" in workflow.enabled else "operation_m8_control", "executed",
                                scheduler_observation=observation)
        return stage, candidate, (candidate,)


def _model_observation(observation: Mapping[str, Any]) -> dict[str, Any]:
    """Remove controller condition labels before the single public model call."""
    return {key: value for key, value in observation.items()
            if key not in {"kind", "recovery_attempt", "merge_barrier_blocked"}}


def _run_scheduler(sidecar: Path, cell: PanelCell, material: Mapping[str, Any]) -> dict[str, Any]:
    jobs = material["jobs"]
    variant, experiment_id = cell.variant, cell.coverage_id
    if "M8" not in cell.runtime_arm.data()["enabled"]:
        return _baseline_replay(jobs, material)
    workers = 1 if (experiment_id == "Q3.3" and variant == "one_worker") else 2
    total_budget = sum(job["cost_units"] for job in jobs)
    scheduler = FifoScheduler(sidecar / "m8-scheduler.sqlite", max_concurrency=workers, total_budget=total_budget)
    experiment = "m8-" + opaque_panel_cell_binding(cell)["cell_digest"]
    states = [scheduler.enqueue(experiment_id=experiment, task_id=job["task_id"], dependencies=job["dependencies"],
                                resources=job["resources"], cost_units=job["cost_units"], snapshot=material["snapshot"])
              for job in jobs]
    first, second = _claim(scheduler, "m8-worker-1"), _claim(scheduler, "m8-worker-2")
    active = [lease for lease in (first, second) if lease is not None]
    if experiment_id == "Q3.3":
        if variant == "one_worker":
            if len(active) != 1: raise ContractError("one-worker scheduler did not enforce its concurrency limit")
            _complete(scheduler, active[0]); later = _claim(scheduler, "m8-worker-1")
            if later is None: raise ContractError("FIFO scheduler did not release the next work item")
            _complete(scheduler, later)
        else:
            if [lease.task_id for lease in active] != [job["task_id"] for job in jobs]:
                raise ContractError("k-worker scheduler did not claim FIFO runnable work")
            for lease in active: _complete(scheduler, lease)
        merged = scheduler.merge(experiment)
        return {"engine": "durable_fifo", "kind": "fifo_workers", "issued_task_ids": [row.task_id for row in merged],
                "merged_task_ids": [row.task_id for row in merged], "worker_count": workers,
                "reserved_cost_units": total_budget, "actual_completed_cost_units": total_budget, "remaining_leases": [], "prediction_ordering_used": False}
    if experiment_id == "Q3.4":
        if len(active) != 2: raise ContractError("completion-order driver requires two active leases")
        by_task = {lease.task_id: lease for lease in active}; ordered = [by_task[task_id] for task_id in material["completion_order"]]
        _complete(scheduler, ordered[0]); barrier = False
        try: scheduler.merge(experiment)
        except ContractError: barrier = True
        pending = scheduler.state(ordered[1].run_id)
        _complete(scheduler, ordered[1]); merged = scheduler.merge(experiment)
        return {"engine": "durable_fifo", "kind": "completion_order", "issued_task_ids": [lease.task_id for lease in active],
                "completion_task_ids": [lease.task_id for lease in ordered], "merge_barrier_blocked": barrier,
                "pending_snapshot_hash": pending.snapshot_hash, "merged_snapshot_hashes": sorted({row.snapshot_hash for row in merged}),
                "reserved_cost_units": total_budget, "actual_completed_cost_units": total_budget, "remaining_leases": []}
    if experiment_id != "Q3.5": raise ContractError("M8 driver supports Q3.3 through Q3.5 only")
    if variant == "write_conflict":
        if len(active) != 1: raise ContractError("write-conflict schedule did not defer the locked work item")
        scheduler.invalidate(experiment, subjects=jobs[0]["resources"], reason="preflight retained conflict")
        return {"engine": "durable_fifo", "kind": "write_conflict", "issued_task_ids": [active[0].task_id], "deferred_task_ids": [states[1].task_id],
                "double_execution": False, "reserved_cost_units": total_budget, "actual_completed_cost_units": 0, "remaining_leases": []}
    if variant == "withdrawal":
        affected = scheduler.invalidate(experiment, subjects=material["withdraw_subjects"], reason="caller public withdrawal")
        return {"engine": "durable_fifo", "kind": "withdrawal", "invalidated_run_ids": list(affected), "issued_task_ids": [lease.task_id for lease in active],
                "snapshot_mutated": False, "reserved_cost_units": total_budget, "actual_completed_cost_units": 0, "remaining_leases": []}
    if variant in {"crash", "expiry"}:
        if not active: raise ContractError("recovery schedule obtained no lease")
        lease = active[0]; unknown = scheduler.expire_leases(now=lease.lease_until + 1)
        blocked = _claim(scheduler, "m8-no-autorerun") is None
        scheduler.confirm_terminated(lease.run_id, termination_receipt={"schema": "m8-termination-v1", "task_id": lease.task_id})
        retry = scheduler.recover(lease.run_id)
        scheduler.invalidate(experiment, subjects=[item for job in jobs for item in job["resources"]], reason="preflight recovery closure")
        return {"engine": "durable_fifo", "kind": variant, "unknown_run_ids": list(unknown), "autorerun_blocked": blocked,
                "recovery_attempt": retry.attempt, "reserved_cost_units": total_budget, "actual_completed_cost_units": 0, "remaining_leases": []}
    if len(active) != 2: raise ContractError("duplicate receipt schedule requires two active leases")
    receipt = _receipt(active[0]); scheduler.complete(active[0].run_id, receipt_id=receipt.content_hash, receipt=receipt.data(), cost_units=active[0].cost_units)
    rejected = False
    try: scheduler.complete(active[1].run_id, receipt_id=receipt.content_hash, receipt=receipt.data(), cost_units=active[1].cost_units)
    except ContractError: rejected = True
    scheduler.invalidate(experiment, subjects=jobs[1]["resources"], reason="preflight duplicate closure")
    return {"engine": "durable_fifo", "kind": "duplicate", "duplicate_receipt_rejected": rejected, "issued_task_ids": [lease.task_id for lease in active],
            "reserved_cost_units": total_budget, "actual_completed_cost_units": active[0].cost_units, "remaining_leases": []}


def _baseline_replay(jobs: list[Mapping[str, Any]], material: Mapping[str, Any]) -> dict[str, Any]:
    """Pre-registered safe control: records planned work, never leases or merges it."""
    return {"engine": "deterministic_preflight_baseline", "planned_task_ids": [job["task_id"] for job in jobs],
            "planned_resource_sets": [list(job["resources"]) for job in jobs], "reserved_cost_units": sum(job["cost_units"] for job in jobs),
            "actual_completed_cost_units": 0, "remaining_leases": [], "unsafe_execution_started": False,
            "snapshot_digest": FrozenRecord.from_dict(dict(material["snapshot"])).content_hash}


def install_drivers(target: MutableMapping[str, Any], *, material_resolver: BundleResolver | None = None):
    target.update({experiment_id: M8SchedulerDriver(experiment_id, material_resolver=material_resolver) for experiment_id in _VARIANTS})
    return target
