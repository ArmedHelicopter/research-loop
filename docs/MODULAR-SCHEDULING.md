# M8 FIFO parallel scheduling

`FifoScheduler` is a task-local SQLite coordinator. It does not import or touch the repository's existing queue, benchmark inputs, labels, or model runtime.

```python
scheduler = FifoScheduler(sidecar / "scheduler.sqlite", max_concurrency=4, total_budget=80)
state = scheduler.enqueue(
    experiment_id="frozen-panel-1", task_id="measurement-arm",
    dependencies=["setup-arm"], resources=["artifact:dataset-a"], cost_units=8,
    snapshot={"evidence": evidence_hash, "rules": rules_hash, "package": package_hash},
)
lease = scheduler.claim_next("worker-3", lease_seconds=600)
if lease:
    scheduler.complete(lease.run_id, receipt_id=receipt_hash, receipt=receipt, cost_units=lease.cost_units)
results = scheduler.merge("frozen-panel-1")  # only after every current arm completed
```

SQLite `BEGIN IMMEDIATE` makes claim-and-reserve atomic across processes. Tasks are ordered only by insertion FIFO sequence; no quality, score, or prediction field exists in the scheduling schema. A task is runnable only after declared dependencies are complete, without exposing dependency receipts to the dependent lease. Resource overlap blocks concurrent leases. Claiming reserves the declared cost against both hard concurrency and total budget; receipt IDs and cost reservations cannot be reused.

Every arm in one experiment must use identical evidence/rule/package hashes. Completion enters `completed_waiting`; only `merge()` releases the group, preventing an early result from changing an unfinished arm. Lease expiry enters `unknown` and is never automatically requeued. An operator must record `confirm_terminated()` and then explicitly `recover()` a new attempt; the old attempt and its termination receipt remain in the ledger. `invalidate()` records a new safety event and stops matching runs without rewriting any frozen snapshot.

The SQLite file needs normal filesystem locking permissions. This module establishes scheduling invariants only; it does not demonstrate throughput or scientific benefit, which still require the frozen two-benchmark protocol.
