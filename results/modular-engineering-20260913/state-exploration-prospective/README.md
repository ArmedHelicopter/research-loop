# Prospective state/exploration engineering evidence

The exact M1×M7, M2×M7 and M3×M7 TRAIN families have a prospective controller/compiler, a shared state-and-exploration solver, and independent primary scorer processes. M3 retains M2 as fixed background. Final tested source: `c76402ee05a046cb51d2db6ddf99122a007c1ac6`; **88 tests passed**, zero failures/errors/skips, and all 509 tracked Python/Markdown files unchanged. Model responses, original source observations, public primary-like packets and scorer references are synthetic fixtures; Docker and scorer child processes actually ran. There were no paid calls or actual private benchmark reference reads.

| Fixture | Planned / observed | Scored | Failed / blocked | Model calls | Docker / scorer calls | Source calls |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Complete grid | 24 / 24 | 24 | 0 / 0 | 48 | 72 / 24 | 48 |
| M1 qualification differs across arms | 24 / 24 | 24 | 0 / 0 | 48 | 72 / 24 | 48 |
| First model usage unknown | 24 / 24 | 0 | 1 / 23 | 1 | 2 / 0 | 2 |
| State qualification fails | 24 / 24 | 0 | 24 / 0 | 0 | 0 / 0 | 48 |
| Literal auxiliary jobs fail | 24 / 24 | 0 | 24 / 0 | 0 | 48 / 0 | 48 |
| Independent scorer fails | 24 / 24 | 0 | 24 / 0 | 48 | 72 / 24 | 48 |

The complete catalogue freezes before the first qualification/model/scorer call. All cells share the same candidate with exact TRAIN history, bounded context, pinned image and timeout. Every cell reserves two model slots, two source qualifications, two literal auxiliary jobs, one solver Docker opportunity and one scorer opportunity. M7-off runs a useful ordinary dispersion analysis; M7-on uses the actual feasibility/permit/resource-closure path to admit a range probe. Both consume the same two-job/two-cost-unit budget, common first job, dependency/resource constraints and FIFO serial policy. The phase does not enable M8. Outputs from actual jobs and the actual post-transition state enter the same solver requests and generated Python program.

The composite binds exact `FrozenAdmissionMaterial` for M1 or `FrozenLineageMaterial` for M2/M3 to original `FrozenExplorationSchedulerMaterial`, sharing TRAIN identity, task digest, CSV hashes and context budget. Source signatures bind the full cell/scenario digest, including the composite. The phase objective additionally binds the replayed state-transition digest and composite digest. Read-only replay reconstructs source qualification, root/claim state and context, compares persistent evidence/claim journals, and checks phase selection, restricted permit, resource closure, budget, literal programs, returns, FIFO order and completion/merge operations. It checks exact solver instructions, model request/response linkage, program bytes, public inputs and complete bounded Docker argv. Repaired-chain attacks first pass the generic receipt checker, then fail family replay and execution-authority score issuance.

Source/port/root/receipt faults stop before downstream I/O. Every failed or blocked planned cell remains visible, with consumed and unused opportunities retained. M1 qualification-semantic drift retains individual scores and makes the M1 contrast inconclusive. Scorer processes accept only strict, mutually exclusive `state_exploration=True` scope for these three designs; the default scope and existing family restrictions remain closed.

These are synthetic engineering results, not measured scientific effectiveness, benchmark improvement, production readiness or hostile-host attestation. The primary rubric fixture returns controlled synthetic dimensions. No pruning, validation access or scientific promotion occurred. Concurrent functional work makes throughput comparisons inappropriate.

## Frozen evidence

`checks/` preserves every frozen source manifest and JUnit closure. `checks.json` records check outcomes; `denominators.json` records all controller fixtures, including intentional failures. ZIPs contain allowlisted public exports, exact frozen configs, signed qualification receipts, controller journals, model ledgers, literal job/solver programs, phase/runtime journals and scorer client/worker receipts. Raw source snapshots, scorer private stores, server configurations, authority keys and private sentinel bodies are excluded. `archive-members.json` hashes each ZIP member; `archive-integrity.json` hashes every archive artifact.

Absolute paths in receipts are original execution bindings. Reproduce fresh fixtures instead of relocating those journals and treating them as new executions:

```powershell
& E:/_ryanDev/AI/research-loop-modular/work/custody-root-venv/Scripts/python.exe E:/_ryanDev/AI/research-loop-modular/work/run_frozen_useful_checks.py E:/_ryanDev/AI/research-loop-modular/state-exploration-combos E:/_ryanDev/AI/research-loop-modular/work/state-exploration-new-check tests/test_state_exploration_train_controller.py tests/test_state_prediction_scorer_process.py tests/test_label_isolation.py
```

Image: `research-benchmark-python@sha256:1433f0d223b0773b0d8c3184fa4ff6ab0a3891113442f1592d8d7e883d21a349`.
