"""Train-only scheduler interventions on caller-owned, bounded integer work.

Both arms run the same worker.  SQLite provides the M8 intervention; the frozen
control is a naive in-memory FIFO with per-return publication and no locks,
withdrawal handling, receipt deduplication, leases, or crash recovery.  Resource
writes and failures are confined to this pure-computation harness.  These are
engineering observations, never benchmark scores or scientific validation.
"""
from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Event, Lock
from typing import Any, Callable, Mapping, MutableMapping

from research_loop.modular.contracts import DataIdentity, FrozenRecord, PublicTask
from research_loop.modular.modules.scheduling import FifoScheduler, TaskLease
from research_loop.modular.modules.improvement import CandidatePackage
from research_loop.modular.panel_receipts import PanelCell, opaque_panel_cell_binding
from research_loop.modular.workflow import ModularWorkflow
from research_loop.ontology import ContractError


_VARIANTS = {
    "Q3.3": frozenset(("one_worker", "k_workers")),
    "Q3.4": frozenset(("favorable_first", "unfavorable_first")),
    "Q3.5": frozenset(("write_conflict", "withdrawal", "crash", "expiry", "duplicate")),
}
_POLICY = FrozenRecord.from_dict({
    "schema": "m8-compute-policy-v2", "worker": "integer-reduction-v1",
    "baseline": "naive-fifo-per-return-v1", "max_attempts": 2,
    "cost": "charge-every-started-attempt-including-failures-and-cancellations",
    "fault_target": "first-fifo-job", "withdrawal": "before-computation",
    "crash": "after-computation-before-delivery", "expiry": "after-computation-before-delivery",
    "duplicate": "first-receipt-delivered-to-second-before-second-return",
    "resources": "in-memory-write-with-observed-version",
})
BundleResolver = Callable[[PublicTask, FrozenRecord], FrozenRecord]


def _hash(value: Mapping[str, Any]) -> str:
    return FrozenRecord.from_dict(value).content_hash


def _hex(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _names(value: Any, *, empty: bool = True) -> bool:
    return (isinstance(value, list) and (empty or bool(value))
            and all(isinstance(x, str) and 0 < len(x) <= 128 and x.strip() == x for x in value)
            and len(set(value)) == len(value))


def freeze_scheduler_source(task: PublicTask, *, values: list[int]) -> FrozenRecord:
    """Freeze synthetic/public integer inputs; identity binding is not authenticity."""
    if not isinstance(task, PublicTask):
        raise ContractError("scheduler source requires a typed task")
    body = {"schema": "m8-public-compute-source-v1", "identity": task.identity.data(),
            "task_digest": task.content_hash, "values": values}
    _validate_source(task, body)
    return FrozenRecord.from_dict(body)


def _validate_source(task: PublicTask, source: Any) -> None:
    task.identity.require_train()
    if (not isinstance(source, Mapping)
            or set(source) != {"schema", "identity", "task_digest", "values"}
            or source["schema"] != "m8-public-compute-source-v1"
            or source["identity"] != task.identity.data() or source["task_digest"] != task.content_hash
            or not isinstance(source["values"], list) or not 1 <= len(source["values"]) <= 128
            or any(type(x) is not int or abs(x) > 1000000 for x in source["values"])):
        raise ContractError("scheduler source must contain bounded task-bound public integers")


def freeze_scheduler_bundle(task: PublicTask, *, source: FrozenRecord, package_digest: str,
                            schedules: Mapping[str, Any]) -> FrozenRecord:
    """Freeze a complete nine-variant bundle before either arm executes.

    Each row has jobs, completion_order, withdraw_subjects, budget_units.  Each
    job has task_id, dependencies, resources, cost_units and payload (operation
    sum/sum_squares, indices).  Units equal the number of selected source values.
    Recovery variants allocate one extra first-job attempt in BOTH arms.
    """
    if not isinstance(task, PublicTask) or not isinstance(source, FrozenRecord):
        raise ContractError("scheduler bundle requires typed public task/source")
    body = {"schema": "typed-m8-scheduler-panel-bundle-v2", "identity": task.identity.data(),
            "task_digest": task.content_hash, "source": source.data(), "rules": _POLICY.data(),
            "snapshot": {"evidence": source.content_hash, "rules": _POLICY.content_hash, "package": package_digest},
            "schedules": schedules}
    _validate_bundle(task, body)
    return FrozenRecord.from_dict(body)


def _validate_bundle(task: PublicTask, body: Any) -> None:
    if (not isinstance(task, PublicTask) or not isinstance(body, Mapping)
            or set(body) != {"schema", "identity", "task_digest", "source", "rules", "snapshot", "schedules"}
            or body["schema"] != "typed-m8-scheduler-panel-bundle-v2"
            or body["identity"] != task.identity.data() or body["task_digest"] != task.content_hash):
        raise ContractError("scheduler bundle has an invalid task binding or schema")
    _validate_source(task, body["source"])
    snapshot = body["snapshot"]
    if (body["rules"] != _POLICY.data() or not isinstance(snapshot, Mapping)
            or set(snapshot) != {"evidence", "rules", "package"}
            or snapshot["evidence"] != _hash(body["source"]) or snapshot["rules"] != _POLICY.content_hash
            or not _hex(snapshot["package"])):
        raise ContractError("scheduler snapshot must bind the actual source, rules and package")
    schedules = body["schedules"]
    if not isinstance(schedules, Mapping) or set(schedules) != set(_VARIANTS):
        raise ContractError("scheduler bundle needs all registered experiments")
    workload = None
    resources = None
    for experiment, variants in _VARIANTS.items():
        rows = schedules[experiment]
        if not isinstance(rows, Mapping) or set(rows) != variants:
            raise ContractError("scheduler bundle needs every registered variant")
        for variant in sorted(variants):
            row = rows[variant]
            if not isinstance(row, Mapping) or set(row) != {"jobs", "completion_order", "withdraw_subjects", "budget_units"}:
                raise ContractError("scheduler row has invalid fields")
            jobs = row["jobs"]
            if not isinstance(jobs, list) or len(jobs) != 2:
                raise ContractError("scheduler panel requires exactly two FIFO jobs")
            for job in jobs:
                if (not isinstance(job, Mapping)
                        or set(job) != {"task_id", "dependencies", "resources", "cost_units", "payload"}
                        or not _names([job["task_id"]], empty=False) or job["dependencies"] != []
                        or not _names(job["resources"], empty=False) or len(job["resources"]) > 4):
                    raise ContractError("scheduler work item has invalid names or dependencies")
                payload = job["payload"]
                if (not isinstance(payload, Mapping) or set(payload) != {"operation", "indices"}
                        or payload["operation"] not in ("sum", "sum_squares")
                        or not isinstance(payload["indices"], list) or not 1 <= len(payload["indices"]) <= 128
                        or any(type(i) is not int or not 0 <= i < len(body["source"]["values"]) for i in payload["indices"])
                        or type(job["cost_units"]) is not int or job["cost_units"] != len(payload["indices"])):
                    raise ContractError("scheduler payload or deterministic cost is invalid")
            ids = [job["task_id"] for job in jobs]
            if len(set(ids)) != 2 or not _names(row["completion_order"], empty=False) or set(row["completion_order"]) != set(ids):
                raise ContractError("completion order must name both distinct FIFO jobs")
            expected_order = list(reversed(ids)) if variant == "unfavorable_first" else ids
            if row["completion_order"] != expected_order:
                raise ContractError("completion order differs from the preregistered intervention")
            common = [{k: job[k] for k in ("task_id", "dependencies", "cost_units", "payload")} for job in jobs]
            if workload is None:
                workload = common
            elif workload != common:
                raise ContractError("all variants must execute the same caller workload")
            pair = [job["resources"] for job in jobs]
            overlap = bool(set(pair[0]) & set(pair[1]))
            if overlap != (variant == "write_conflict"):
                raise ContractError("resource overlap must match the conflict intervention")
            if variant != "write_conflict":
                if resources is None:
                    resources = pair
                elif resources != pair:
                    raise ContractError("non-conflict variants must keep resource allocation fixed")
            withdrawn = row["withdraw_subjects"]
            if not _names(withdrawn) or (variant != "withdrawal" and withdrawn):
                raise ContractError("withdrawal subjects only belong in the withdrawal cell")
            if variant == "withdrawal" and (not withdrawn or not set(withdrawn) <= set(pair[1]) or set(withdrawn) & set(pair[0])):
                raise ContractError("withdrawal must target only the second FIFO job's resources")
            expected_budget = sum(job["cost_units"] for job in jobs)
            if variant in ("crash", "expiry"):
                expected_budget += jobs[0]["cost_units"]
            if type(row["budget_units"]) is not int or row["budget_units"] != expected_budget:
                raise ContractError("budget must exactly allocate the registered attempts in both arms")


def select_scheduler_material(bundle: FrozenRecord, task: PublicTask, experiment_id: str, variant: str) -> FrozenRecord:
    if not isinstance(bundle, FrozenRecord):
        raise ContractError("scheduler material must be frozen")
    body = bundle.data()
    _validate_bundle(task, body)
    if variant not in _VARIANTS.get(experiment_id, ()):
        raise ContractError("scheduler driver variant is not registered")
    return FrozenRecord.from_dict({"schema": "typed-selected-m8-scheduler-material-v2",
        "identity": task.identity.data(), "task_digest": task.content_hash,
        "source": body["source"], "snapshot": body["snapshot"], "bundle_digest": bundle.content_hash,
        "experiment_id": experiment_id, **body["schedules"][experiment_id][variant]})


def scheduler_panel_injection(experiment_id: str, variant: str, *, task: FrozenRecord, evidence: FrozenRecord) -> Mapping[str, Any]:
    if not isinstance(task, FrozenRecord):
        raise ContractError("scheduler injection needs a frozen task")
    body = task.data()
    if set(body) != {"identity", "payload"} or not isinstance(body["payload"], Mapping):
        raise ContractError("scheduler injection task is malformed")
    public = PublicTask(DataIdentity.parse(body["identity"]), FrozenRecord.from_dict(body["payload"]))
    select_scheduler_material(evidence, public, experiment_id, variant)
    return {"schema": "scheduler-panel-controller-v2", "material_bundle": evidence.data()}


def _resolve(resolver: BundleResolver | None, task: PublicTask, scenario: FrozenRecord, experiment_id: str, variant: str) -> FrozenRecord:
    body = scenario.data()
    base = body.get("base")
    if not isinstance(base, Mapping) or base.get("task") != task.content_hash:
        raise ContractError("scheduler scenario does not bind the prepared task")
    controller = body.get("controller_input")
    if controller is not None:
        if (not isinstance(controller, Mapping) or set(controller) != {"schema", "material_bundle"}
                or controller["schema"] != "scheduler-panel-controller-v2" or not isinstance(controller["material_bundle"], Mapping)):
            raise ContractError("scheduler controller material is malformed")
        bundle = FrozenRecord.from_dict(controller["material_bundle"])
    elif resolver is not None:
        bundle = resolver(task, scenario)
    else:
        raise ContractError("scheduler panel requires caller-owned material")
    if not isinstance(bundle, FrozenRecord) or bundle.content_hash != base.get("evidence"):
        raise ContractError("scheduler bundle does not match frozen scenario evidence")
    return select_scheduler_material(bundle, task, experiment_id, variant)


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
        if (not isinstance(workflow, ModularWorkflow) or not isinstance(cell, PanelCell)
                or not isinstance(scenario, FrozenRecord) or not isinstance(package, CandidatePackage)):
            raise ContractError("scheduler run requires typed workflow, cell, scenario and candidate package")
        session = workflow.session
        lock = session.lock.data()
        if (cell.coverage_id != self.experiment_id or cell.identity != session.task.identity
                or cell.task_digest != session.task.content_hash or cell.scenario_digest != scenario.content_hash
                or cell.package_digest != package.digest or lock["package_digest"] != package.digest
                or cell.runtime_arm != session.arm
                or set(cell.runtime_arm.data()["enabled"]) != set(workflow.enabled)
                or scenario.data().get("variant") != cell.variant or scenario.data().get("experiment_id") != self.experiment_id):
            raise ContractError("scheduler cell/session/scenario/package binding mismatch")
        material = _resolve(self.material_resolver, session.task, scenario, self.experiment_id, cell.variant).data()
        if material["snapshot"]["package"] != package.digest:
            raise ContractError("scheduler bundle package differs from the executed candidate")
        # The panel digest can be created after the bundle: bind the actual runtime
        # objective here without a bundle -> panel -> bundle hash cycle.
        material["snapshot"]["rules"] = _hash({"policy_digest": _POLICY.content_hash,
            "objective_digest": session.objective.content_hash})
        observation = _run_scheduler(session.sidecar, cell, material)
        # Journal spent work before the model seam: a failed model call cannot
        # erase already executed attempts or their safety outcomes.
        stage = workflow._trace("stage_8" if "M8" in workflow.enabled else "operation_m8_control", "executed",
                                scheduler_observation=observation)
        candidate = workflow.invoke_model("final", model, instruction=(
            "Return a bounded train-only candidate. Set outcome to unknown, evidence_ids to an empty list, "
            "programme_complete to false, and copy required_objective_digest exactly."),
            module_context=FrozenRecord.from_dict({"panel_cell": opaque_panel_cell_binding(cell),
                "public_task": session.task.data(), "scheduler_observation": _model_observation(observation),
                "required_objective_digest": session.objective.content_hash}))
        body = candidate.data()
        if (body.get("objective_digest") != session.objective.content_hash or body.get("outcome") != "unknown"
                or body.get("evidence_ids") != [] or body.get("programme_complete") is not False):
            raise ContractError("scheduler driver final candidate is invalid")
        return stage, candidate, (candidate,)


def _model_observation(observation: Mapping[str, Any]) -> dict[str, Any]:
    """Allowlist public artifacts; the schema is identical in every cell/arm."""
    return {"schema": "public-work-observation-v2", "input_binding": observation["input_binding"],
            "outputs": observation["public_outputs"], "visibility": observation["public_visibility"],
            "missing_output_bindings": observation["missing_output_bindings"]}


def _compute(job: Mapping[str, Any], material: Mapping[str, Any]) -> dict[str, Any]:
    payload = job["payload"]
    values = [material["source"]["values"][i] for i in payload["indices"]]
    value = sum(values) if payload["operation"] == "sum" else sum(x * x for x in values)
    return {"schema": "integer-reduction-result-v1", "task_digest": material["task_digest"],
            "source_digest": _hash(material["source"]), "job_digest": _hash(dict(job)),
            "payload_digest": _hash(payload), "value": value, "operations": len(values)}


@dataclass
class _Attempt:
    run_id: str
    task_id: str
    attempt: int
    job: Mapping[str, Any]
    snapshot: FrozenRecord
    lease: TaskLease | None = None
    state: str = "pending"
    started: Event | None = None
    gate: Event | None = None
    action: str = "compute"
    future: Future | None = None
    output: dict[str, Any] | None = None
    receipt: FrozenRecord | None = None
    context_digest: str | None = None
    resource_versions: dict[str, int] | None = None


class _Harness:
    """Controlled threads really overlap; event gates select return order.

    No thread can access a model, filesystem, network, or external resource via
    its work description.  Names in resources refer solely to this in-memory
    event simulation.  A five-second coordination timeout is a failed run.
    """
    def __init__(self, sidecar: Path, cell: PanelCell, material: Mapping[str, Any]):
        if (sidecar / "m8-controller-observation.json").exists():
            raise ContractError("scheduler cell already ran; preserve its observation and use a new cell")
        self.material, self.cell = material, cell
        self.jobs = material["jobs"]
        self.enabled = "M8" in cell.runtime_arm.data()["enabled"]
        self.workers = 1 if cell.variant == "one_worker" else 2
        self.experiment = "m8-" + opaque_panel_cell_binding(cell)["cell_digest"]
        self.snapshot = FrozenRecord.from_dict(material["snapshot"])
        self.scheduler = None
        if self.enabled:
            path = sidecar / "m8-scheduler.sqlite"
            if path.exists():
                raise ContractError("scheduler cell needs a fresh sidecar; existing evidence is preserved")
            self.scheduler = FifoScheduler(path, max_concurrency=self.workers, total_budget=material["budget_units"])
        self.attempts: list[_Attempt] = []
        self.events: list[dict[str, Any]] = []
        self.visible: list[FrozenRecord] = []
        self.visibility: list[list[FrozenRecord]] = []
        self.active: dict[str, _Attempt] = {}
        self.resources: dict[str, dict[str, Any]] = {}
        self.peak = 0
        self.charged = 0
        self.lock = Lock()
        self.pool = ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix="m8-pure")
        for job in self.jobs:
            if self.scheduler:
                state = self.scheduler.enqueue(experiment_id=self.experiment, task_id=job["task_id"],
                    dependencies=job["dependencies"], resources=job["resources"],
                    cost_units=job["cost_units"], snapshot=self.snapshot.data())
                run_id = state.run_id
            else:
                run_id = _hash({"experiment": self.experiment, "task_id": job["task_id"], "attempt": 1})
            self.attempts.append(_Attempt(run_id, job["task_id"], 1, job, self.snapshot))
        self.record("enqueued", task_ids=[a.task_id for a in self.attempts])

    def record(self, operation: str, **detail: Any) -> None:
        with self.lock:
            self.events.append({"sequence": len(self.events), "operation": operation, **detail})

    def dispatch(self) -> list[_Attempt]:
        started = []
        while len(self.active) < self.workers:
            pending = [a for a in self.attempts if a.state == "pending"]
            if not pending:
                break
            if self.scheduler:
                # A long second lease permits the controlled clock to expire only
                # the first job without accidentally expiring unrelated workers.
                seconds = 30 if pending[0].task_id == self.jobs[0]["task_id"] else 300
                lease = self.scheduler.claim_next("worker-" + str(len(self.active) + 1), lease_seconds=seconds)
                if lease is None:
                    self.record("dispatch_blocked", pending=[a.run_id for a in pending])
                    break
                item = next(a for a in pending if a.run_id == lease.run_id)
                item.lease = lease
                item.snapshot = lease.snapshot
            else:
                item = pending[0]
                if self.charged + item.job["cost_units"] > self.material["budget_units"]:
                    self.record("dispatch_blocked", pending=[a.run_id for a in pending])
                    break
            self.charged += item.job["cost_units"]
            item.context_digest = _hash({"snapshot_digest": item.snapshot.content_hash,
                "visible_receipts": [r.content_hash for r in self.visible]})
            item.started, item.gate = Event(), Event()
            item.state = "leased" if self.enabled else "running"
            item.future = self.pool.submit(self.work, item)
            if not item.started.wait(5):
                raise ContractError("pure worker failed to start")
            started.append(item)
        return started

    def work(self, item: _Attempt) -> dict[str, Any] | None:
        with self.lock:
            overlap = [other.run_id for other in self.active.values()
                       if set(other.job["resources"]) & set(item.job["resources"])]
            self.active[item.run_id] = item
            item.resource_versions = {name: self.resources.get(name, {}).get("version", 0)
                                      for name in item.job["resources"]}
            self.peak = max(self.peak, len(self.active))
            self.events.append({"sequence": len(self.events), "operation": "worker_started", "run_id": item.run_id,
                "task_id": item.task_id, "attempt": item.attempt, "active": len(self.active),
                "overlapping_resource_runs": overlap, "context_digest": item.context_digest})
        item.started.set()
        try:
            if not item.gate.wait(5):
                raise ContractError("pure worker release timed out")
            if item.action == "cancel":
                if not self.enabled:
                    item.state = "cancelled"
                self.record("worker_cancelled", run_id=item.run_id)
                return None
            output = _compute(item.job, self.material)
            item.output = output
            self.record("work_computed", run_id=item.run_id, output_digest=_hash(output), cost_units=item.job["cost_units"])
            # Actual writes to harness-owned memory only. Concurrent baseline
            # writers can overwrite a version that changed since their start;
            # durable lock deferral makes the second worker observe the update.
            with self.lock:
                for name, observed_version in item.resource_versions.items():
                    current_version = self.resources.get(name, {}).get("version", 0)
                    self.resources[name] = {"version": current_version + 1,
                        "output_digest": _hash(output), "run_id": item.run_id}
                    self.events.append({"sequence": len(self.events), "operation": "resource_written",
                        "run_id": item.run_id, "resource": name, "observed_version": observed_version,
                        "previous_version": current_version, "new_version": current_version + 1,
                        "stale_write": observed_version != current_version})
            if item.action == "crash":
                raise _ControlledCrash("injected after compute, before return")
            return output
        finally:
            with self.lock:
                self.active.pop(item.run_id, None)

    def release(self, item: _Attempt, action: str = "compute") -> FrozenRecord | None:
        item.action = action
        item.gate.set()
        try:
            output = item.future.result(timeout=5)
        except _ControlledCrash:
            item.state = "unknown" if self.enabled else "failed"
            self.record("worker_failed", run_id=item.run_id, reason="injected_crash")
            return None
        except Exception as exc:
            item.state = "unknown" if self.enabled else "failed"
            self.record("worker_failed", run_id=item.run_id, reason=type(exc).__name__)
            raise
        if output is None:
            item.state = self.scheduler.state(item.run_id).status if self.scheduler else "cancelled"
            return None
        item.receipt = FrozenRecord.from_dict({"schema": "m8-public-work-receipt-v2",
            "run_id": item.run_id, "task_id": item.task_id, "attempt": item.attempt,
            "snapshot_digest": item.snapshot.content_hash, "context_digest": item.context_digest,
            "task_digest": self.material["task_digest"], "source_digest": _hash(self.material["source"]),
            "job_digest": _hash(dict(item.job)), "cost_units": item.job["cost_units"], "output": output})
        self.record("worker_returned", run_id=item.run_id, receipt_digest=item.receipt.content_hash)
        return item.receipt

    def deliver(self, item: _Attempt, receipt: FrozenRecord) -> bool:
        self.record("delivery_attempt", run_id=item.run_id, receipt_digest=receipt.content_hash)
        if self.scheduler:
            try:
                state = self.scheduler.complete(item.run_id, receipt_id=receipt.content_hash,
                    receipt=receipt.data(), cost_units=item.job["cost_units"])
            except ContractError as exc:
                self.record("delivery_rejected", run_id=item.run_id, receipt_digest=receipt.content_hash, reason=str(exc))
                return False
            item.state = state.status
        else:
            # Frozen naive callback: no run binding or receipt uniqueness check.
            # Duplicate deliveries really append the same receipt twice.
            item.state = "completed"
            self.visible.append(receipt)
            self.visibility.append(list(self.visible))
        self.record("delivery_accepted", run_id=item.run_id, receipt_digest=receipt.content_hash)
        if not self.scheduler:
            self.record("merge_visible", receipt_digests=[r.content_hash for r in self.visible])
        return True

    def merge(self) -> bool:
        self.record("merge_attempt")
        if not self.scheduler:
            return True
        try:
            rows = self.scheduler.merge(self.experiment)
        except ContractError as exc:
            self.record("merge_blocked", reason=str(exc))
            return False
        by_id = {a.run_id: a for a in self.attempts}
        # Read the actual durable payload, not regenerated output after merging.
        self.visible = [self.scheduler.receipt(row.run_id) for row in rows]
        for row in rows:
            by_id[row.run_id].state = row.status
        self.visibility.append(list(self.visible))
        self.record("merge_visible", receipt_digests=[r.content_hash for r in self.visible])
        return True

    def recover(self, item: _Attempt, *, crash: bool) -> None:
        if not self.scheduler:
            # Queue jobs are popped at dispatch.  There is no recovery subsystem.
            self.record("failed_job_not_requeued", run_id=item.run_id)
            return
        if crash:
            path = self.scheduler.path
            self.scheduler = FifoScheduler(path, max_concurrency=self.workers, total_budget=self.material["budget_units"])
            self.record("scheduler_reopened", run_id=item.run_id)
        expired = self.scheduler.expire_leases(now=item.lease.lease_until + 1)
        self.record("leases_expired", run_ids=list(expired))
        item.state = self.scheduler.state(item.run_id).status
        unintended = self.scheduler.claim_next("no-implicit-retry", lease_seconds=30)
        self.record("autorerun_probe", claimed_run_id=unintended.run_id if unintended else None)
        if unintended is not None:
            raise ContractError("unknown attempt was implicitly redispatched")
        try:
            self.scheduler.recover(item.run_id)
        except ContractError as exc:
            self.record("recovery_blocked", run_id=item.run_id, reason=str(exc))
        else:
            raise ContractError("unknown work recovered without termination evidence")
        if item.receipt is not None:
            self.deliver(item, item.receipt)  # Late return must actually be rejected.
        if not item.future.done() or item.run_id in self.active:
            raise ContractError("termination evidence requires a stopped worker")
        termination = {"schema": "joined-pure-worker-v1", "run_id": item.run_id,
                       "future_done": item.future.done(), "worker_active": item.run_id in self.active}
        self.scheduler.confirm_terminated(item.run_id, termination_receipt=termination)
        item.state = self.scheduler.state(item.run_id).status
        self.record("termination_confirmed", **termination)
        state = self.scheduler.recover(item.run_id)
        self.attempts.append(_Attempt(state.run_id, item.task_id, state.attempt, item.job, item.snapshot))
        self.record("recovered", parent_run_id=item.run_id, run_id=state.run_id, task_id=state.task_id, attempt=state.attempt)

    def close(self) -> None:
        # Unexpected exceptions cancel only this harness's pure work; no external
        # resource or inherited scheduler evidence is touched.
        for item in self.attempts:
            if item.future is not None and not item.future.done():
                item.action = "cancel"
                item.gate.set()
        self.pool.shutdown(wait=True)

    def observation(self) -> dict[str, Any]:
        states = ([asdict(row) for row in self.scheduler.runs(self.experiment)] if self.scheduler else
                  [{"run_id": a.run_id, "task_id": a.task_id, "attempt": a.attempt, "status": a.state,
                    "snapshot_hash": a.snapshot.content_hash, "receipt_id": a.receipt.content_hash if a.receipt else None}
                   for a in self.attempts])
        receipts = [r.data() for r in self.visible]
        def public(receipt: FrozenRecord) -> dict[str, Any]:
            row = receipt.data()
            return {"binding": receipt.content_hash, "input_binding": row["output"]["payload_digest"],
                    "value": row["output"]["value"], "operations": row["output"]["operations"]}
        missing = [a for a in self.attempts[:2] if not any(r["task_id"] == a.task_id for r in receipts)]
        budget = self.scheduler.reserved_cost_units() if self.scheduler else self.charged
        accepted = {e["receipt_digest"] for e in self.events if e["operation"] == "delivery_accepted"}
        if budget != self.charged:
            raise ContractError("durable reservation and dispatched attempt accounting disagree")
        return {"engine": "durable_fifo" if self.enabled else "memory_fifo_baseline",
            "kind": self.cell.variant, "policy_digest": _POLICY.content_hash,
            "input_binding": _hash({"task_digest": self.material["task_digest"], "source_digest": _hash(self.material["source"]),
                                    "snapshot_digest": self.snapshot.content_hash}),
            "worker_count": self.workers, "peak_active_workers": self.peak,
            "issued_task_ids": [e["task_id"] for e in self.events if e["operation"] == "worker_started"],
            "merged_task_ids": [r["task_id"] for r in receipts],
            "work_output_digests": [_hash(r["output"]) for r in receipts],
            "work_outputs": [r["output"] for r in receipts], "receipts": receipts,
            "public_outputs": [public(r) for r in self.visible],
            "public_visibility": [[public(r) for r in group] for group in self.visibility],
            "missing_output_bindings": [_hash({"task_digest": self.material["task_digest"], "job_digest": _hash(dict(a.job))}) for a in missing],
            "allocated_budget_units": self.material["budget_units"], "reserved_cost_units": budget,
            "actual_spent_cost_units": self.charged,
            "actual_computed_cost_units": sum(a.job["cost_units"] for a in self.attempts if a.output is not None),
            "actual_returned_cost_units": sum(a.job["cost_units"] for a in self.attempts if a.receipt is not None),
            "actual_completed_cost_units": sum(a.job["cost_units"] for a in self.attempts
                                                if a.receipt is not None and a.receipt.content_hash in accepted),
            "failed_attempt_count": sum(e["operation"] == "worker_failed" for e in self.events),
            "cancelled_attempt_count": sum(e["operation"] == "worker_cancelled" for e in self.events),
            "duplicate_visible_count": len(self.visible) - len({r.content_hash for r in self.visible}),
            "remaining_budget_units": self.material["budget_units"] - budget,
            "remaining_leases": [r["run_id"] for r in states if r["status"] == "leased"],
            "unknown_runs": [r["run_id"] for r in states if r["status"] == "unknown"],
            "unfinished_runs": [r["run_id"] for r in states if r["status"] in ("pending", "running", "leased", "unknown", "completed_waiting")],
            "states": states, "events": self.events, "snapshot_digest": self.snapshot.content_hash,
            "simulated_resources": self.resources,
            "attempts": [{"run_id": a.run_id, "task_id": a.task_id, "attempt": a.attempt,
                "context_digest": a.context_digest, "snapshot_digest": a.snapshot.content_hash,
                "output": a.output, "receipt": a.receipt.data() if a.receipt else None} for a in self.attempts],
            "prediction_ordering_used": False}


class _ControlledCrash(Exception):
    pass


def _run_scheduler(sidecar: Path, cell: PanelCell, material: Mapping[str, Any]) -> dict[str, Any]:
    harness = _Harness(sidecar, cell, material)
    try:
        active = harness.dispatch()
        by_task = {a.task_id: a for a in active}
        handled: set[str] = set()
        variant = cell.variant
        if variant == "withdrawal":
            subjects = material["withdraw_subjects"]
            harness.record("withdrawal_injected", subjects=subjects)
            if harness.scheduler:
                affected = harness.scheduler.invalidate(harness.experiment, subjects=subjects, reason="frozen public withdrawal")
                harness.record("runs_invalidated", run_ids=list(affected))
                for a in active:
                    if a.run_id in affected:
                        harness.release(a, "cancel")
                        handled.add(a.run_id)
        if variant in ("crash", "expiry"):
            first = active[0]
            receipt = harness.release(first, "crash" if variant == "crash" else "compute")
            handled.add(first.run_id)
            harness.record("fault_injected", fault=variant, run_id=first.run_id)
            if variant == "expiry" and not harness.scheduler:
                harness.deliver(first, receipt)
            else:
                harness.recover(first, crash=variant == "crash")
        for task_id in material["completion_order"]:
            item = by_task.get(task_id)
            if item is None or item.run_id in handled:
                continue
            receipt = harness.release(item)
            if receipt:
                harness.deliver(item, receipt)
                if variant == "duplicate" and item is active[0]:
                    harness.record("duplicate_injected", receipt_digest=receipt.content_hash, target_run_id=active[1].run_id)
                    harness.deliver(active[1], receipt)
                if cell.coverage_id == "Q3.4":
                    pending = [a for a in active if not a.future.done()]
                    if pending:
                        harness.merge()
                        harness.record("pending_context_observed", run_id=pending[0].run_id,
                            context_digest=pending[0].context_digest, snapshot_digest=pending[0].snapshot.content_hash,
                            visible_receipts=[r.content_hash for r in harness.visible])
        # FIFO drain covers one-worker dispatch, lock release, and genuine retry.
        while True:
            more = harness.dispatch()
            if not more:
                break
            for item in more:
                receipt = harness.release(item)
                if receipt:
                    harness.deliver(item, receipt)
        harness.merge()
        return harness.observation()
    except BaseException as exc:
        harness.record("controller_failed", error_type=type(exc).__name__)
        raise
    finally:
        harness.close()
        # This survives worker exceptions and precedes the model call. Residual
        # SQLite states are reported as found, including leases on failed runs.
        (sidecar / "m8-controller-observation.json").write_text(
            FrozenRecord.from_dict(harness.observation()).encoded + "\n", encoding="utf-8")


def install_drivers(target: MutableMapping[str, Any], *, material_resolver: BundleResolver | None = None):
    target.update({experiment_id: M8SchedulerDriver(experiment_id, material_resolver=material_resolver) for experiment_id in _VARIANTS})
    return target
