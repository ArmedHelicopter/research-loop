# Prospective state/scheduling engineering evidence

The exact M1×M8, M2×M8 and M3×M8 TRAIN families have a prospective controller/compiler, a shared state-and-scheduling solver, and independent primary scorer processes. M3 retains M2 as fixed background. Final tested source: `7ddf8d0a7d864a2ffbee2401b61aba0513c022e9`; **102 tests passed**, zero failures/errors/skips, and all 517 tracked Python/Markdown files unchanged. Public primary-like packets, source qualification, model responses and scorer references are synthetic fixtures. Docker and scorer child processes actually ran; no paid calls or actual private benchmark references were used.

| Controller fixture | Planned / observed | Scored | Failed / blocked | Model calls | Docker/broker attempts | Scorer calls | Source calls |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Complete grid | 24 / 24 | 24 | 0 / 0 | 48 | 72 | 24 | 48 |
| M1 qualification differs across arms | 24 / 24 | 24 | 0 / 0 | 48 | 72 | 24 | 48 |
| First model usage unknown | 24 / 24 | 0 | 1 / 23 | 1 | 2 | 0 | 2 |
| State qualification fails | 24 / 24 | 0 | 24 / 0 | 0 | 0 | 0 | 48 |
| Literal auxiliary jobs fail | 24 / 24 | 0 | 24 / 0 | 0 | 48 | 0 | 48 |
| Independent scorer fails | 24 / 24 | 0 | 24 / 0 | 48 | 72 | 24 | 48 |
| Auxiliary provider usage unknown | 24 / 24 | 0 | 24 / 0 | 0 | 48 unknown | 0 | 48 |

The unknown-provider case raises before Docker invocation. Its 48 reserved broker attempts are explicitly marked as unknown-cost attempts, not confirmed container executions. All failures, blocked cells and unused opportunities remain in their original denominator; no cell is pruned.

The full 24-cell catalogue freezes before qualification, model or scorer I/O. Each arm receives the same candidate package with exact TRAIN provenance and the same two useful auxiliary jobs, job/cost budget, public inputs, context ceiling, pinned image and timeout. M8-off executes those jobs serially; M8-on uses actual `FifoScheduler` leases with concurrency capped at two, immutable snapshots, dependency/resource exclusion, and a completion barrier before merging. Both select jobs 0 and 1 from the unchanged shared phase material contract. M7 stays disabled, no exploration permit is issued, and the frozen third probe slot is never selected. Existing M7 and M7×M8 recipes and receipts are unchanged.

The independent-job grid checks actual overlapping Docker-call intervals under M8 and zero overlap under serial execution. A focused driver fixture additionally captures monotonic start/end times inside the actual containers and verifies intersecting execution intervals. Separate actual-Docker variants verify serialization under dependencies or shared resource locks, reversed completion with stable FIFO publication, and timeout cleanup. Successful variants also cross the independent primary scorer process. These checks establish executed concurrency behavior; concurrent functional work makes throughput comparisons inappropriate.

The composite binds exact admission material for M1 or lineage material for M2/M3 to literal TRAIN job material, with identical task/CSV/context bindings. Signed source requests bind the complete cell/scenario digest; phase snapshots bind both the original composite and replayed state transition. Read-only replay reconstructs qualification and state, compares persistent evidence/claim journals, verifies literal programs and complete Docker argv, checks model requests/responses and solver artifacts, and replays actual SQLite leases, budgets, snapshots, returns, barrier and merge order. Repaired-chain attacks first pass the generic receipt verifier, then fail family replay and execution-authority score issuance. M1 semantic qualification drift preserves scores while making the M1 contrast inconclusive.

The scorer process accepts only strict, mutually exclusive `state_scheduling=True` scope for the exact three pairs. Existing family scopes and the original default remain closed. All reported scores and effects are synthetic engineering checks, not measured scientific improvement, production readiness or hostile-host attestation. Validation remains unopened and scientific effectiveness remains unproven.

## Frozen evidence

`checks/` preserves all frozen source manifests and JUnit closures. `checks.json` records each check; `denominators.json` records every controller outcome, including intentional failures. `scheduling-evidence.json` summarizes selected jobs, closed leases, serial/parallel intervals and the independently scored container-timestamp variant. ZIPs contain allowlisted public exports, frozen configs, qualification receipts, model ledgers, controller journals, literal job/solver programs, phase/runtime journals, closed scheduler databases, and scorer client/worker receipts. Raw source snapshots, private scorer stores, server configs, keys and private sentinel bodies are excluded. `archive-members.json` hashes each ZIP member; `archive-integrity.json` hashes all archive artifacts.

Absolute paths are historical execution bindings. Reproduce fresh fixtures rather than relocating journals and treating them as new executions:

```powershell
& E:/_ryanDev/AI/research-loop-modular/work/custody-root-venv/Scripts/python.exe E:/_ryanDev/AI/research-loop-modular/work/run_frozen_useful_checks.py E:/_ryanDev/AI/research-loop-modular/state-scheduling-combos E:/_ryanDev/AI/research-loop-modular/work/state-scheduling-new-check tests/test_state_scheduling_train_controller.py tests/test_state_prediction_scorer_process.py tests/test_label_isolation.py
```

Image: `research-benchmark-python@sha256:1433f0d223b0773b0d8c3184fa4ff6ab0a3891113442f1592d8d7e883d21a349`.
