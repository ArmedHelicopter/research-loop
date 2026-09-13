# State improvement combination handoff

Source: `E:/_ryanDev/AI/research-loop-modular/state-improvement-combos`, branch `codex/state-improvement-combos`, final production pin `e99ffb0e580762c310fec73b16aaf392a15c4c4a`, base `143a1057531285815f0118cad4ad88a425e979ba`. Root owns integration. This report accompanies the synthetic handoff ZIP and its per-file SHA-256 manifest.

The implemented slice is M1/M2/M3 × M9: 11 legal history builds, 22 legal target cells, and two structural exclusions. The documentation retains all ten outer panels (47 builds, 94 legal targets, two structural exclusions). Other M9 pairs and triples are not implemented by this slice and are not pruned. The estimand is the total history-build and target-state interaction, with fixed M2 for M3 and M1 as required by M9's prerequisite.

The controller freezes recipes before source/model calls, qualifies literal existing TRAIN history, executes actual state transitions and restricted builders, freezes all selected candidates before targets, then runs shared target solver/Docker and independent primary-rubric process scoring. M9-off gets a useful fixed candidate plus the same proposal and actual builder opportunity; unselected proposals do not enter target context. The new exposure contract preserves ordinary CombinationPanel exact-manifest behavior. Disjointness is the benchmark/task/group subject tuple; different tasks in a shared group are not asserted to be independent families.

Each successful normal fixture uses synthetic model/source/reference data with 55 model transport calls (11 proposals, 44 target), 66 source qualification calls, 11 actual builder executions, 22 actual target Docker executions and 22 independent process scores. Its separately acquired synthetic history uses two prior transport calls and one prior Docker execution. No actual model generation, paid API calls, real private references, or validation data were used. Partial and unknown costs, inherited-history costs, blocked targets, structural exclusions and unsuccessful scoring remain explicit in the receipts.

## Preserved verification sequence

| Closure | Source | Result | Interpretation |
|---|---|---|---|
| R1 | 41171aa9d5534cdfc585f45d1f91e9fce33b582a | 16 pass, 22 fail | Initial source qualifier binding integration failure; preserved |
| R2 | 0396aa0d5b2204927f05556ca4ae07fe5e42aa88 | 1 fail | Duplicate proposal request identity at build ledger replay; preserved |
| R3 | 60d59f1569360e9c37ad1efe9cfbd810377b9bfd | 33 pass | Actual normal slice and failure/tamper checks |
| R4 | 68dcfa8272b33e3f6e6ac83d107669ff12187361 | 36 pass, 1 fail | History attack fixture omitted terminal candidate hash repair |
| Default R4 | 68dcfa8272b33e3f6e6ac83d107669ff12187361 | 52 pass | Label isolation, default panels, combination/default/prediction process regressions |
| R5 | a43f5eac9d49f77a8848d0e7ef4ce2566936fda3 | 6 pass | Corrected history attack and previously unreached barrier, source and scoring cases |
| R6 RED | 137bfe65c6aa69f11349fe7f45a3dbf028579db9 | 1 fail | Reproduced score-input issuance through a proxy despite corrupted build |
| R7 | e99ffb0e580762c310fec73b16aaf392a15c4c4a | 1 pass | Concrete barrier/plan/ledger replay guard and no-new-I/O regression |

Every named attempt has its original before/closed source map, JUnit output, synthetic run artifacts, source/call ledgers and failed budgets retained. All eight closures have unchanged source bytes during their run (512 tracked Python/Markdown files). Across the current cases, 95 distinct checks passed: 43 family checks and 52 default regressions. This is accumulated evidence across the pinned corrections, not a fresh 95-case run at the final pin. R4's passed cases were not rerun after its one-line fixture repair. Production bytes from 68dcfa8 to a43f5ea are exactly identical; the historical byte proof is included. The later eight-line production repair is limited to the state improvement driver, controller and build verifier.

The root review at 68dcfa8 is retained unchanged as historical review evidence. It did not catch the subsequently reproduced proxy bypass. R6 includes `barrier-proxy-counterexample.json`: a real score input was issued after changing a candidate file, although the real barrier rejected it. The repair requires exact CandidateBarrier, FrozenStateImprovementPlan, FrozenProviderLedger and BuildResult types before replay. Its regression disables new source qualification, model, builder and Docker calls, proves normal replay still works, and rejects the corrupt-build proxy and nested plan/ledger proxies.

Passing synthetic checks demonstrates covered engineering behavior. It does not establish causal benefit, qualified real-source scientific truth, or completion of the larger programme. Primary rubric fixture scores are not evidence of scientific efficacy. The next integration step remains the root's source merge and replay review, including reconciliation of scorer-process flags with parallel slices.
