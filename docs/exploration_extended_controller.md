# Q7.3–Q7.6 formal train controller

The four extended exploration questions now run through the closed production
registry, scenario compiler, `FrozenTrainControllerConfig`, `run_train_panel`
and real `CodexModelPort`. No registry/compiler patch is needed. The original
driver-only results and their failed attempts remain unchanged in
`exploration_extended_verification.json`.

The caller supplies `exploration_authority=` with the frozen material described
in `exploration_extended_panel_drivers.md`. Execution imports use the public
`panel_execution` API. Q7.3–Q7.5 expose three actual model slots and Q7.6 exposes
four, so the complete two-adapter grid reserves 88 cells and 280 model calls.
The nested opportunity budget must exactly equal the exported `BUDGET` contract;
boolean counters cannot impersonate integer budgets.

The controller exports real custody-authorized train packets, reconstructs all
typed bundles and checks every variant's actual job/input declarations against
the exact exported CSV before any panel model or authority call. This includes
unselected later jobs. A foreign declaration in any of Q7.3–Q7.6 consumes zero
model/authority calls and leaves a preserved controller-attempt receipt. Normal
driver checks revalidate inputs before execution and trusted observation.

Source froze at `2628ec3` on base `7441cfd`. Four production source files had
identical hashes before and after the complete run. The existing isolated
`custody-root-venv` ran pytest 8.4.2 / PyYAML 6.0.3; no dependencies changed.
The frozen suite passed **102 tests in 674.145 seconds**, with zero failures,
errors or skips. It covers experiments, panel compilation/receipts, label
isolation, the new formal controller, the existing Q7.1/Q7.2 formal controller
and direct extended-driver boundary tests. The repeated standalone 88-cell
driver grid was excluded because the formal controller exercised that grid.

The new formal grid completed 160 real restricted Docker executions, 280 real
model-port invocations with mocked transport, and 320 caller verification calls.
The persistent model ledger retained 560 synthetic transport-reported tokens;
there were no actual paid provider calls. All 88 trace chains and unchanged final
candidate digests were checked. An additional read-only artifact check verified
the actual M1/M2/M5/M7 operation differences reached the next model requests;
Q7.6 scientific admission followed the independent review submission. The old
52-cell Q7.1/Q7.2 formal controller also remained engineering-complete.

The resulting 40 `proceed`, 16 `closed_negative`, 24 `invalid` and 8 `unknown`
decisions concern newly authored synthetic data. Both synthetic task adapters
selected ratio 25 under the previously frozen fixture criterion. These counts
verify entry-point wiring and fixture behavior, not real-model improvements,
real DiscoveryBench/BLADE scores, independent scientific discovery or programme
completion. P0, existing split states and validation leases were not changed.

`exploration_extended_controller_verification.json` records exact source
hashes, JUnit hash, controller/model/manifest paths, all 88 trace paths/hashes,
ratio-selection rows and the preserved earlier driver evidence reference.
The frozen JUnit is:

`E:/_ryanDev/AI/research-loop-modular/work/exploration-extended-controller-checks/frozen-r1.xml`

SHA256 `13d401b1b3a95f89cab8a9f5de9f8fa64a6831bb94d791ce40ff2f468096ec00`.
The public controller manifest is:

`E:/_ryanDev/AI/research-loop-modular/work/exploration-extended-controller-checks/frozen-r1/test_complete_88_cell_export_m0/controller-verification.json`

All raw artifacts are public synthetic fixtures. The machine receipt supplies
the exact per-cell paths rather than relying on directory-name reconstruction.

## Failure-cost review supplement

Independent review found that a malformed typed exception cost could be lost
when its unit/amount schema was rejected. Commit `31813c5` now persists that raw
Mapping/FrozenRecord report before validation, records its validation status,
and keeps verified cost unknown. The separate known/unknown partial-cost and two
malformed-cost representation checks passed (4 tests). This changes only the
failed verifier path; the earlier 102-test/88-cell frozen run remains archived
at `2628ec3` and was not relabeled as a run of the later source. Exact hashes and
JUnit are in `exploration_extended_cost_review.json`.
