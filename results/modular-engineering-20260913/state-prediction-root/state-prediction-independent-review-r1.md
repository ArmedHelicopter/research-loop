# Independent state/prediction review r1

Reviewed 2026-09-13, read-only apart from this report. Source checkout: `E:/_ryanDev/AI/research-loop-modular/state-prediction-combos`, HEAD `81e988ee9eb364e48a9729150e3c40d1cfa91b1d`. No tests, Docker, model calls or private reference-store reads were performed. The archived tested commit is `1cfee61e33b70de8ec15f095ae9351affb27dfe3`; `git diff <tested> HEAD -- research_loop evaluation tests` was empty. The integration checkout was not reviewed.

**Result: no concrete blocking defect found in this bounded review.** This is source inspection and archival consistency evidence, not independent execution or causal-efficacy evidence.

- Actual mechanisms are exercised. Driver lines 109–139 enforce exact admission material/verifier for M1 and exact lineage material/verifier for M2/M3, apply `_transition`, then register M4 only when enabled. The original `m4_plan` response remains solver context in both M4-off/on arms. There is no variant-dependent replacement proposal. Lineage transition actually appends/deduplicates evidence, updates claims, withdraws roots, and builds context; admission transition consumes signed subject-bound assessments. `conditional_factorial` fixes M2 throughout M3×M4 through the declared M3 dependency.
- Matching and qualification are guarded. Controller lines 85–115 require exact task/CSV/material bindings, one candidate package across arms and equal context budgets. Lines 215–225 check pair-specific verifier/scorer scope and authority separation. M1 semantic projection preserves the consumed before/after subject, state, outcome, execution and audit fields while excluding incidental cell/signature bookkeeping. Differing complete matched arms retain their scores but get an inconclusive contrast (lines 285–288, 318–322).
- Successful replay binds source receipts and CSV, evidence/claim journals, the original proposal, the persistent prediction registry, transition/plan/joint ordering, actual solver requests and responses, literal program bytes, execution feedback and final candidate (driver lines 148–233; shared `_verify_solver_files`). Score issuance calls this replay first. Shared score serialization and verification bind candidate, package, task, arm, design, pair, panel and scorer digests. The process scope accepts one strict boolean scope and the exact registered state/prediction design (`scorer_process.py:129–180`).
- Controller lines 240–260 persist all 24 cells before qualification/model/scoring and deterministic material checks. The configuration reserves 72 shared model slots, 24 Docker/scoring and 48 source opportunities. Source/export preflight faults stop downstream calls; per-cell source outages retain failed rows and allow other cells to continue. Unknown model usage blocks later cells before their source/model/scorer calls. Contrast estimation rejects incomplete cells. These are different failure scopes, not a global abort on every authority outage.

The normal archived receipt reports 24/24 scored, 72 scripted model calls, 24 Docker/scorer calls, 48 source calls, no pruning and no validation access. The source-outage archive retains 24 rows (8 failed, 16 scored); poisoned usage retains 1 failed plus 23 blocked. The archive reports 45 tests passing, zero paid calls and fixed synthetic rubric outputs. Initial failed attempts remain documented. None of these establish model quality, scientific usefulness, production readiness or coverage of the larger programme.

Coverage limits, without asserting speculative defects:

1. The eleven rehashed mutation cases explicitly select BLADE arms `00`/`01` (`test_state_prediction_train_controller.py:249–253`). Full-grid execution covers all arms/tasks, but mutation rejection is not independently exercised for `10`/`11` or DiscoveryBench.
2. The ordinary proposal fixture is always a valid `_plan`; it does not exercise malformed proposal contents, later analysis/final model failures or Docker timeout/failure in this three-pair controller. M4's own semantic validation runs only when enabled; do not infer identical malformed-proposal behavior from the matched valid fixtures.
3. The scripted solver echoes the state-derived proposal marker and executes a public CSV calculation; fixed synthetic scores verify plumbing/arithmetic, not whether the state or plan improves the task answer.

Source SHA256 pins:

```text
feee74cea3d6b9ad95d08f9431b2a11127ade91cad1547d70206810daa8488fc research_loop/modular/state_prediction_combination_driver.py
bdaeb370ac90a4b87757acbba5675aa067fe35aab937281adfee78b67624dc1e research_loop/modular/state_prediction_combination_controller.py
c96d5b51f43e1089a13bb52e256b082c50cdcb17f2afbe4e9170a2de614fe081 evaluation/modular/state_prediction_scoring.py
ca044ce76f73bc2bf479a9da41fb1090d9171fbd193e99b182290fac2005b07f evaluation/modular/scorer_process.py
59b3cd0af0afb9e1b49773d6daf5c186ad38bc6afd576ed622e9e630b3a754f1 research_loop/modular/lineage_combination_controller.py
fc677a364cd4df0d8d128377ff31f0a75f347e2466061ca2f74a6ec31aa3b42e tests/test_state_prediction_train_controller.py
```
