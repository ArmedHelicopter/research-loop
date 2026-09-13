# Train-only M4+M5 execution and adapted scoring controller

`combination_train_controller.run_m4_m5_train_panel` connects actual custody
export, the existing shared-session M4+M5 driver, the real `CodexModelPort`,
restricted Docker execution, execution-authority signatures, independently
verified adapted scoring, and the existing grouped contrast estimator.

The entry point executes only `pair:M4+M5`. It uses
`default_compatibility(...).conditional_factorial(("M4", "M5"))` and the existing
`CombinationPanel` checks. This does not remove the catalogue's 36 pair,
five triple or full/leave-one-out obligations, and it does not pretend those
other combinations have this production executor.

## API and frozen material

```python
run = run_m4_m5_train_panel(
    config, custody=custody, snapshot_root=snapshot,
    export_root=public_export, run_root=run_directory,
    model=codex_model_port, audit_verifier=audit_verifier,
    execution_authority=execution_authority,
    scoring_service=independent_combination_scoring_service,
    scorer_authority_keys=scorer_keys,
)
```

`FrozenM4M5TrainConfig` wraps a canonical `FrozenRecord`. Its exact schema is
demonstrated by the synthetic controller integration test. It binds:

- The train allowlist, exact custody identities, prepared public task hashes
  and public CSV hashes, including both core benchmarks and one frozen split.
- The existing compatibility baseline and exactly four package-map entries.
  All four arms use the same actual candidate package and exact task manifest.
- A single core-pair `ScorerConfig`, opaque scorer-handle hashes, and the
  existing contrast analysis policy: unit scale, higher is better, complete
  data required, task/replicate means followed by equal group means.
- Replicates, a reviewed Luna/low model port, exact five response schemas,
  global call/token budgets, a content-pinned Docker image and execution timeout.
- Equal opportunities per cell: `m4_plan`, `m5_mechanism`, `m5_measurement`,
  `analysis_program`, `final_answer`; one Docker attempt and one scoring call.

`compile_m4_m5_train_panel` verifies the materialized packets and creates only
this registered four-arm panel. It accepts no caller-supplied reduced cell
list or alternate contrast. Every planned cell is persisted before any model
call. Docker roots are constructed internally from the public export and run
directories; references and custody metadata are not mounted in the worker.

The model port, schemas, fresh ledger, scoring configuration, frozen handle
delegation and authority keys must match before export. Export verifies the
custody inventory; compilation checks the actual prepared task and CSV against
the caller's frozen bindings. CSVs are rehashed before each cell. A rejection
after materialization leaves a `blocked_before_execution` attempt receipt.
An already used run/export directory or model ledger cannot silently restart.

## Authority and model boundaries

Each successful cell is replayed by
`verify_m4_m5_combination_benchmark_cell`. Only then can
`issue_combination_score_input` sign its actual candidate, executed program,
joint mechanism, runtime trace and frozen scorer binding. The independent
scoring service consumes this signed candidate through its existing single
candidate rubric transport. Its signed response is verified against the
same source, cell and scorer configuration before entering the contrast.

The execution and scorer authority IDs and keys must be distinct, and the
controller verifies that the configured service actually uses those
registered key sets. The Python dependencies are trusted component boundaries;
this integration test does not demonstrate separate OS processes or independently
operated scoring infrastructure. Production must preserve that separation.

Solver requests use the existing public M4/M5 projection. They never receive
the full controller configuration, package map, scorer task handles, reference
material, contrast coefficients or authenticated controller truth. The scorer
receives the existing candidate-only projection, without arm labels or joint
controller material. Synthetic references in tests are generated fixtures.

## Failures and costs

Every planned cell has a durable attempt row, even when an earlier provider
failure prevents a later cell from starting. Failed cells are never retried,
rescored or dropped. Source-replay failures cannot reach scoring. A scoring
call is recorded before invoking the service so a failed call or rejected
response still consumes its allocated opportunity. Raw returned receipts and
the failing stage are retained for verification failures.

The attempt journal stores cumulative model usage immediately before and after
each cell, including known tokens and `usage_incomplete`. A poisoned model
ledger blocks later calls without inventing provider invocations or runtime
traces. Execution receipts retain actual Docker outcomes. Broker preflight
failure blocks all planned cells after one attempt to construct the broker.

Model calls and scorer calls have separate frozen denominators. The existing
rubric transport provides no token/billing receipt or token-budget enforcement;
scorer token accounting is explicitly `transport_not_provided`. It must never
be reported as zero monetary cost after an attempted call. The model token
limit is global, and actual per-cell token consumption is recorded rather than
claimed equal.

If any execution, source verification, scoring or receipt verification fails,
the returned contrast is `inconclusive` under `incomplete_reject`. Complete
verified data uses the existing `estimate_grouped_contrast`; no failed arm is
pruned to manufacture an estimable result. `controller-attempt.json`,
`panel.json` and `controller-receipt.json` retain the frozen plan, per-cell
stages, observed usage and final disposition.

## What the tests establish

The synthetic integration test runs two real custody exports × four arms,
40 calls through the real model port using a mocked process transport, eight
local Docker computations, eight calls to an independent rubric transport,
execution signatures, score verification and grouped contrast. Counterexamples
cover malformed configuration, missing arms, source/configuration/key/handle
drift, foreign cells, solver failure, source-verification failure, scorer
failure, tampered scoring receipts and unavailable execution allocation.

These checks establish engineering and provenance wiring on public synthetic
fixtures. Mock usage counts are not billed costs, adapted scores are not
scientific validity, and a descriptive interaction estimate is not a significance
test or general benefit claim. Validation access remains closed. No paid
models, real benchmark questions or private references are required by these
tests.
