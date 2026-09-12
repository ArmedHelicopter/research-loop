import multiprocessing
from pathlib import Path

import pytest

from research_loop.modular.modules.scheduling import FifoScheduler
from research_loop.ontology import ContractError


SNAPSHOT = {"evidence": "evidence-v1", "rules": "rules-v1", "package": "package-v1"}


def _claim_in_process(path: str, worker: str, queue) -> None:
    scheduler = FifoScheduler(Path(path), max_concurrency=1, total_budget=10)
    lease = scheduler.claim_next(worker, lease_seconds=60)
    queue.put(lease.run_id if lease else None)


def scheduler(tmp_path: Path, *, concurrency=2, budget=10):
    return FifoScheduler(tmp_path / "queue.sqlite", max_concurrency=concurrency, total_budget=budget)


def enqueue(s, task, *, experiment="exp", dependencies=(), resources=(), cost=1):
    return s.enqueue(experiment_id=experiment, task_id=task, dependencies=dependencies, resources=resources, cost_units=cost, snapshot=SNAPSHOT)


def test_fifo_order_resource_lock_and_hard_budget(tmp_path: Path):
    s = scheduler(tmp_path, concurrency=2, budget=3)
    first, second, third = enqueue(s, "first", resources=("artifact",), cost=2), enqueue(s, "second", resources=("artifact",), cost=1), enqueue(s, "third", resources=("other",), cost=2)
    lease = s.claim_next("w1", lease_seconds=30)
    assert lease and lease.run_id == first.run_id  # only FIFO, no score input exists
    assert s.claim_next("w2", lease_seconds=30) is None  # second lock conflicts, third exceeds remaining hard budget
    s.complete(lease.run_id, receipt_id="r1", receipt={"ok": True}, cost_units=2)
    next_lease = s.claim_next("w2", lease_seconds=30)
    assert next_lease and next_lease.run_id == second.run_id
    with pytest.raises(ContractError):
        s.complete(next_lease.run_id, receipt_id="r1", receipt={"duplicate": True}, cost_units=1)


def test_real_multiprocess_atomic_competing_claim_and_crash_recovery(tmp_path: Path):
    s = scheduler(tmp_path, concurrency=1, budget=10)
    run = enqueue(s, "one")
    ctx, queue = multiprocessing.get_context("spawn"), multiprocessing.get_context("spawn").Queue()
    p1 = ctx.Process(target=_claim_in_process, args=(str(tmp_path / "queue.sqlite"), "worker-a", queue))
    p2 = ctx.Process(target=_claim_in_process, args=(str(tmp_path / "queue.sqlite"), "worker-b", queue))
    p1.start(); p2.start(); p1.join(10); p2.join(10)
    claimed = [queue.get(timeout=5), queue.get(timeout=5)]
    assert claimed.count(run.run_id) == 1 and claimed.count(None) == 1
    expired = s.expire_leases(now=10**12)
    assert expired == (run.run_id,) and s.state(run.run_id).status == "unknown"
    assert s.claim_next("worker-c", lease_seconds=10) is None
    s.confirm_terminated(run.run_id, termination_receipt={"process": "confirmed dead"})
    retry = s.recover(run.run_id)
    assert retry.attempt == 2 and s.state(run.run_id).status == "terminated"


def test_uniform_snapshot_completion_order_and_barrier(tmp_path: Path):
    s = scheduler(tmp_path)
    left, right = enqueue(s, "left", resources=("left",)), enqueue(s, "right", resources=("right",))
    a, b = s.claim_next("a", lease_seconds=10), s.claim_next("b", lease_seconds=10)
    assert {a.run_id, b.run_id} == {left.run_id, right.run_id}
    # Finish in reverse order. Neither result is merged until the last arm.
    s.complete(b.run_id, receipt_id="right-receipt", receipt={"run": "right"}, cost_units=1)
    with pytest.raises(ContractError):
        s.merge("exp")
    s.complete(a.run_id, receipt_id="left-receipt", receipt={"run": "left"}, cost_units=1)
    merged = s.merge("exp")
    assert {run.status for run in merged} == {"merged"}
    with pytest.raises(ContractError):
        s.enqueue(experiment_id="exp", task_id="bad", dependencies=(), resources=(), cost_units=1,
                  snapshot={"evidence": "changed", "rules": "rules-v1", "package": "package-v1"})


def test_dependency_dag_and_safety_invalidation_preserve_snapshot(tmp_path: Path):
    s = scheduler(tmp_path)
    root = enqueue(s, "root")
    child = enqueue(s, "child", dependencies=("root",), resources=("subject-x",))
    lease = s.claim_next("worker", lease_seconds=10)
    assert lease.run_id == root.run_id
    s.complete(root.run_id, receipt_id="root-r", receipt={"done": 1}, cost_units=1)
    # Child can execute on its original snapshot but cannot read the root receipt before merge.
    child_lease = s.claim_next("worker", lease_seconds=10)
    assert child_lease.run_id == child.run_id and child_lease.snapshot.data() == SNAPSHOT
    assert s.invalidate("exp", subjects=("subject-x",), reason="new safety event") == (child.run_id,)
    assert s.state(child.run_id).status == "invalidated"
