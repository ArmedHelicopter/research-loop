# Q3.3–Q3.5 scheduler interventions on synthetic public work

The v2 driver executes the same caller-owned integer workload in both arms.
M8-on uses `FifoScheduler` and durable receipts. M8-off is the frozen
`naive-fifo-per-return-v1` baseline: an in-memory FIFO which publishes every
returned receipt and has no resource locks, withdrawal handling, receipt
deduplication, leases, or crash recovery. Neither arm invokes arbitrary code,
Docker, external resources, benchmark scoring, or paid models from its worker.
The driver makes one caller-supplied model call in the `final` slot.

This is a deliberately limited synthetic control. Comparisons establish
engineering behavior and causal wiring under this baseline, not general
scheduler quality, throughput, benchmark task performance, or scientific
effectiveness. Public source hashes establish artifact consistency; they do
not authenticate a scientific source or demonstrate that integer inputs solve
the associated benchmark question. The previous report is retained verbatim in
[the 6911f42 archive](archive/MODULAR-SCHEDULER-PANEL-DRIVERS-6911f42.md); its
claims about matched execution and label-free observations do not describe v1
correctly and must not be reused as verification evidence.

## Caller contract

```python
source = freeze_scheduler_source(prepared_task, values=[2, -3, 4])
bundle = freeze_scheduler_bundle(
    prepared_task, source=source, package_digest=candidate.digest,
    schedules=schedules,
)
```

`schedules` must cover both Q3.3 variants, both Q3.4 variants and all five Q3.5
variants. Every row has exactly `jobs`, `completion_order`, `withdraw_subjects`
and `budget_units`. There are exactly two jobs, each with `task_id`, empty
`dependencies`, nonempty `resources`, `cost_units`, and a payload like
`{"operation": "sum", "indices": [0, 1]}` or
`{"operation": "sum_squares", "indices": [0, 1, 2]}`. This panel intentionally
excludes dependency graphs so its concurrency and completion-order tests do
not change the dependency topology.

The source has 1–128 integers in [-1,000,000, 1,000,000]. Each payload selects
1–128 valid indices. The cost must equal the number of selected values, and
booleans are not accepted as integers. Job IDs, payloads and costs must match
across all nine variants. Non-conflict resource allocations must also match.
Only `write_conflict` has overlapping resources. Only `withdrawal` carries
withdrawn subjects, and they must target the second job's resources exclusively.
Only `unfavorable_first` reverses the FIFO completion order. These labels
identify registered interventions and do not assert scientific favorability
of either numeric result.

The bundle freezes the prepared task hash and identity, actual source body and
hash, versioned policy, and candidate digest. At execution it must match the
cell, scenario evidence hash, session task, session arm and candidate. The
runtime snapshot additionally binds the actual session objective, avoiding a
compile-time bundle/panel hash cycle. Legacy v1 snapshots containing arbitrary
names are rejected, not silently upgraded. All these checks precede worker
dispatch and model invocation.

## Executed interventions

| Panel | Both arms' workload | M8-on | Frozen baseline |
| --- | --- | --- | --- |
| Q3.3 | Same FIFO work, one or two workers | Actual leased worker threads overlap only up to the limit; group merge | Actual FIFO worker threads obey the same worker count; every return is published |
| Q3.4 | Same two concurrently active workers; controlled return order | First merge attempt is rejected; both actual receipts become visible only after completion, in FIFO order | First return is immediately visible; subsequent return appends to that actual visible context |
| Q3.5 conflict | Two pure jobs write results to the same harness-owned memory entry | Real claim defers the second job; it observes the new version before writing | Both threads observe version 0; the second actually overwrites version 1, recording a stale write |
| Q3.5 withdrawal | Withdrawal arrives after dispatch, before computation | Real resource-based invalidation cancels second computation; first remains `completed_waiting`, second `invalidated`, group is not falsely merged | Baseline ignores the event and publishes both returns from the captured snapshot |
| Q3.5 crash | First thread computes, then raises before delivery | Reopen SQLite, expire only that lease, reject unconfirmed recovery, join the stopped worker, confirm termination and execute the same job at attempt 2 | Popped job fails and is not requeued; only the second result is published |
| Q3.5 expiry | First thread computes; return is held until the controlled lease expiry | Actual late delivery is rejected; confirmed termination permits the same job at attempt 2 | Baseline has no lease clock and accepts the returned result |
| Q3.5 duplicate | Deliver first receipt to the second run, then deliver the second's actual receipt | Actual bound-receipt rejection, followed by normal second completion | Naive callback actually appends the duplicate and later the second receipt |

Threads wait on start/release events; no sleep is used to manufacture a
concurrency observation. This measures overlapping active work intervals,
including the controlled wait, not parallel CPU speedup. A coordination
timeout fails the run. The crash is a controlled thread exception, not an OS
process kill; SQLite is genuinely reopened but this panel alone does not prove
process-crash durability. Generic scheduler tests separately exercise competing
claims across spawned processes.

Q3.3 does not measure throughput or wall time, and two small integer jobs are
not a fairness stress workload. In Q3.4 both arms freeze each worker's context
at dispatch; the arithmetic worker does not read later changes to global
visibility. The panel tests early global publication and merge ordering, not
contamination of an unfinished worker's scientific context or result quality.

The worker receipt contains the actual numeric result, prepared-task/source/job
bindings, snapshot, captured visible-context hash, run ID and attempt. Durable
completion validates the typed run/snapshot/cost binding, and merge reads the
stored receipt body instead of recomputing an output afterward. The pending
worker's captured context and snapshot hashes are retained before and after
the first Q3.4 visibility event.

## Costs, incomplete work and model isolation

Allocated units equal the sum of both job costs, plus one first-job retry for
crash and expiry. Both arms allocate the same amount. Every started attempt is
charged, including cancellation and failed delivery; retries never rename the
job or reset its cost. The controller separately reports allocated, reserved,
spent, computed, returned, accepted-completion and remaining units. Duplicate
delivery adds no new computation charge. M8-on reservations are read from
SQLite and reconciled against actual dispatches. All run states and remaining
leases come from the backend; withdrawal may leave unmerged completed work,
and unexpected errors may leave persisted leased states. Those are recorded,
not replaced by empty arrays or successful completion flags.

`m8-controller-observation.json` and the pre-model workflow journal preserve
actual events, results, costs, failures and residual states. The controller
artifact survives an unexpected worker error, and model failure cannot erase
already executed work. Reusing the same cell sidecar is rejected in both arms.

Every model call has the same observation schema: public numeric `outputs`,
their actual `visibility` history, missing-output bindings and an opaque input
binding. There are no engine, arm, variant, package, controller-state, failure
condition or expected-outcome fields in this projection. Observable result
count/order differences are consequences of executed interventions. Full
condition and backend state remain in controller-only traces. The candidate
must preserve the objective and return `outcome=unknown`, no evidence IDs, and
`programme_complete=false`.

## Verification boundary

The synthetic test matrix contains 36 separately parametrized cells: two
public benchmark adapter shapes × nine variants × two M8 settings. Assertions
cover actual arithmetic, worker start/return ordering, concurrent resource
overlap, persisted SQLite receipt contents, merge timing, captured context,
withdrawal, actual duplicate-delivery attempts, recovery gating, attempt costs
and residual state. Counterexamples reject malformed nested input, wrong
prepared-task/source/package/scenario bindings and validation provenance before
any model or scheduler call. Additional checks exercise an entirely independent
baseline, source changes that alter computed values, worker/model failure
evidence, sidecar reuse rejection, and typed receipt snapshot tampering.

No real benchmark questions, validation data, private references or paid model
calls are used by these tests. The production registry and scenario compiler
route Q3.3/Q3.4/Q3.5 to these caller-bound drivers. Dedicated integration checks
exercise every cell through custody export, the frozen train controller and
the actual Codex model port with mocked process transport. Scientific benchmark
evaluation, throughput/fairness and scientific-context contamination remain
separate qualification obligations.
