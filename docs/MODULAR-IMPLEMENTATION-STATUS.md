# Modular implementation ledger

Goal: implement all 48 research scenarios, M1–M9 including the separate meta-program
stage, and C1–C5 combination experiments defined in the design documents.

## Current scheduler controller checkpoint (2026-09-13)

Source `ce2e81b` additionally connects Q3.3–Q3.5 through the production scenario
compiler, custody exporter, frozen train controller and Codex model port.
The registry now has 23 question drivers. The 36-cell synthetic M8 grid uses
both benchmark adapter shapes, caller-owned integer work and actual worker
threads/SQLite; it does not solve actual benchmark questions. All 212 focused
root checks passed in 319.951 seconds. The agent's source-qualified 100-test
suite and 152-test expanded suite overlap; they are not independent replications.

The baseline actually executes the same workload and publishes each return.
M8-on applies resource locks, invalidation, merge barriers, typed receipt
deduplication and confirmed-termination recovery. Costs include every started
attempt. Q3.3 throughput/fairness, Q3.4 unfinished scientific-context pollution,
OS process-crash durability and benchmark scientific quality remain unmeasured.
See [the driver contract](MODULAR-SCHEDULER-PANEL-DRIVERS.md).

The archive contains 876 byte-hash-indexed files, including closed reports and
the explicit notice excluding intermediate source-unfrozen runs from final
verification. Earlier reports are unchanged. No new paid call, validation lease,
scientific effect, combination pruning or deployment occurred. The separate
full suite on source `fd985fa` is still running and predates these M8 changes.

## Previous combination scoring checkpoint (2026-09-13)

Source `fd985fa` connects 20 production question drivers and the first actual
four-arm M4+M5 execution-to-signed-adapted-score-to-contrast path. Q3.2/Q5.3 are
planning-only; Q2.5/Q2.6 signed material is not session execution evidence.
Source-specific suites passed 63, 42, 131, 108 and 34 tests; the first prediction
semantic failure is retained. A new full suite runs on a separate frozen checkout.
No new paid call, scientific effect, candidate selection or validation acceptance
is claimed. The remaining question drivers and all required combinations stay in scope.

SciCode and ScienceAgentBench have conservative metadata grouping evidence but
remain unknown-exposure and unsplit. A recorded CORE-Bench diagnostic exposure
disqualifies that acquired source from an unseen validation claim in this context.
See [MODULAR-CHECKPOINT-20260913-COMBINED-SCORING.md](MODULAR-CHECKPOINT-20260913-COMBINED-SCORING.md)
for exact behavior, source bindings, failed checks and archived receipts.

## Previous terminal training checkpoint (2026-09-13)

The frozen `c3a4b21` linked train attempt is closed: 12 cells, 10 successful
restricted-Docker executions with independent adapted scores, and 2 retained
execution failures. There were 58 provider calls and 935,043 tokens. Selection
is `inconclusive`; dynamic controller metadata affected all 12 cells, so this
attempt is engineering wiring evidence and does not qualify a clean module
effect. No combination pruning, validation acceptance or deployment occurred.
The full 928-test result belongs only to `c3a4b21`. Subsequent focused suites
passed 26 (`a111e1c`), 61 (`718fc84`), 83 (`b59bb3e`) and 70 (`7aa349d`) tests.

Production drivers cover Q1.1–Q1.7, Q2.1/Q2.3/Q2.4, Q3.1 and Q4.1–Q4.5.
All 48 obligations, combinations and the separate Q6.3 phase remain required.
See [MODULAR-CHECKPOINT-20260913-TRAIN-TERMINAL.md](MODULAR-CHECKPOINT-20260913-TRAIN-TERMINAL.md)
for the terminal attempt, failure denominator, public-context repairs and
source-specific evidence. The archive now contains 852 hash-indexed files.

## Previous scorer checkpoint (2026-09-13)

Source `c3a4b21040e419692a74382c973104d5fe5cf7e1` adds production Q1.1–Q1.4 and
Q2.1 wiring, frozen train-reference extraction, a separate evaluator provider
contract and a real stdio scorer process. The current archive has 448 files,
including both failed planning-assertion reports and their 55-test repair.
The source is frozen in a separate worktree for a full regression and the first
12-cell linked training solve/adapted-score run; neither is claimed complete in
this checkpoint. See [MODULAR-CHECKPOINT-20260913-SCORER.md](MODULAR-CHECKPOINT-20260913-SCORER.md).

## Previous selection checkpoint (2026-09-13)

Source `bd302e7b91771514f1f327f5e0229b5d00baeae3` additionally integrates the
linked training controller, signed linked adapted scorer, train-only grouped
selection and Q4.1/Q4.2/Q4.4/Q4.5 material-bundle drivers. The controller/selection
seams passed 42 focused tests and Q4/compiler regressions passed 81. This batch
has no full-suite result, live effect estimate or validation result; Q4.5
heterogeneous routing remains unsupported and counted as failed observations.
There are 413 hash-indexed archive files. See
[MODULAR-CHECKPOINT-20260913-SELECTION.md](MODULAR-CHECKPOINT-20260913-SELECTION.md).

## Previous full-suite checkpoint (2026-09-13)

Source `cc640f79fe258bd27cd0d1d43ac1036f2d8957cf` passed the full 854-test suite
with zero failures/errors/skips (1438.961 seconds). Q1.5/Q3.1/Q4.3 production
mechanisms, Q3.1/Q4.3 linked benchmark solver, complete protocol terminal checks
and frozen rubric endpoint are integrated. No module efficacy, scorer
calibration or validation result is claimed. The archive now has 404 hashed
files, preserving the previous 395 files byte for byte.

See [MODULAR-CHECKPOINT-20260913-LINKED.md](MODULAR-CHECKPOINT-20260913-LINKED.md)
for the tested source and remaining obligations. Linked controller, adapted
train selection and additional Q drivers are the next integration batch.

## Earlier live training checkpoint (2026-09-13)

The tested source is `67b55b07464df9baa4666d4027f3ce376f8fcb2c`: 815 tests passed,
zero failures/errors/skips (690.571 seconds). The first complete scheduled real
Q3.1 training transport panel made 23 provider calls, used 208,955 tokens and
retained 11 successful runtime cells plus one rejected prediction plan. It is
`execution_incomplete`, with no benchmark-program execution, independent score,
scientific effect or validation result. The two new pinned sources were actually
acquired and imported as 182 unknown-exposure items in a separate unsplit store.
The original 403-item store is unchanged. Combination panels and grouped contrast
calculation now exist, but actual combined module intervention is not connected.

See [MODULAR-CHECKPOINT-20260913.md](MODULAR-CHECKPOINT-20260913.md) and
`results/modular-engineering-20260912/live-training-20260913/` for that checkpoint's evidence,
complete failure denominators and scope. The sections below preserve the earlier
2026-09-12 checkpoint and do not supersede the newer record.

## Earlier working state (2026-09-12)

- Integration checkout: `E:/_ryanDev/AI/research-loop-modular/integration`, branch
  `codex/modular-integration`, based on `dfaebe554d8bae0191ece2251a812682054a2169`.
- P0 and M1–M9 have initial implementations, independent worktree commits and
  component tests. Shared immutable contracts bind task/source/split identities.
- M2/M3 include claim dependencies, continuous revisions, withdrawal propagation,
  independent surviving roots and context rebuilding. M4–M8 have workflow hooks.
- Stage 9 now makes actual evidence-first/sealed/reveal review calls, with a
  matched summary-first control. Frontier audit makes a source-bound proposal
  call and rejects validation-to-training exports and programme completion.
- M9 includes a genuinely executed restricted meta-builder DSL, independent
  acceptance signatures and whole-package file deployment/rollback fixtures.
- `python -m research_loop.modular plan` emits all 48 Q obligations, 9 singleton
  or conditional designs, 36 pairs, 5 specified triples, full-bundle ablations
  and a pending train-selected final target. Illegal cells remain unscored.
- Original study protocols, results, production pause and historical worktrees
  are unchanged. The two original checkouts retain only their prior design edits.
- A full regression attempt beneath the source checkout correctly triggered the
  inherited `data/labels` ancestor guard. The runner root was moved outside the
  checkout; the guard was preserved. A subsequent missing-parent setup failure
  was repaired by creating the E-drive task work parent before retrying.

## Evidence boundaries

The combined Python suite passed 768 tests with no failures, errors or skips
on source commit `6ac59bad4fc7fb0215a6a80b3fa0b1fc9e1cc6d0` (397.321 seconds).
The earlier 308, 435 and 723-test checkpoints remain retained. The intervening
767-test run had one real Windows SQLite handle-cleanup failure; its report is
preserved alongside the scheduler lifecycle repair and 44 passing focused checks.
The final source hashes, all 48 coverage records, 826 compiled synthetic cells,
source metadata and raw test reports are archived under
`results/modular-engineering-20260912/expanded-sources-and-panels-01/`.
Current test commands and entrypoints
are in [MODULAR-RUNNING.md](MODULAR-RUNNING.md). Component test counts are not
scientific benchmark results.

Two synthetic tasks passed actual public-adapter → restricted Docker → dual
scientific-audit verifier → final gate wiring. Both adapter schemas were exercised;
these are synthetic integration observations, not DiscoveryBench/BLADE efficacy
measurements. The Docker checks also cover non-root execution, no networking,
read-only input/root, timeout cleanup and path/junction rejection.

Two actual previously exposed training packets (one per benchmark) were exported
using the custody allowlist and matching input hashes. The first real Luna model
call completed, but the port rejected additional CLI usage fields; its raw event
stream reports 15,980 input and 989 output tokens. It also warned that global
skill descriptions were present despite the requested configuration. This run
is a retained transport failure, not an accepted benchmark experiment. Read-only
reconciliation now recovers its output and all five usage fields, while keeping
the skill-context faults and original failure. Context isolation still needs
verification before the next experimental call.

All 48 obligations now have typed input builders and callable engineering
scenario drivers. The added drivers cover the exact registered Q3 recovery,
Q4 review, Q5 feasibility, Q6 improvement/scorer and Q8 retrieval variants;
Q1.1/Q2.1/Q2.3 no longer stop at input metadata. Q6.3 executes the restricted
meta-builder separately. These are fixture mechanisms, not 48 completed
benchmark experiments. Several drivers still need their full formal-panel
adapter, matched module-off control and provider/scorer integration.

The train-only panel compiler now constructs a complete frozen grid for every
registered obligation from prepared public tasks and actual package records.
P0-only Q2.2/Q2.7/Q6.4 use a single fixed control bound to source/protocol material;
P0 never has an off arm. The production per-cell entry point currently connects
Q3.1 through real runtime requests, M4 plan/control handling and final journals.
The compiled two-benchmark synthetic Q3.1 grid contains 12 cells. A separate full
grid fixture retains two failed cells (a rejected plan and a model exception),
and its verifier rejects tampered failure binding. Other formal per-cell drivers
remain explicitly unavailable at this entry point.

Q6.2's fixed arm now preserves the original package and invokes no optimizer or
proposal callback. Q6.5 executes two linked offline-shadow updates through one
authority. Its protected control rejects an authenticated but ineligible
synthetic calibration receipt before activation; a positive control proves the
same guard admits an eligible receipt. This checks the guard mechanism and does
not establish calibration of a real scientific scorer or a measured feedback effect.

ExperimentLedger now re-verifies a complete FrozenPanel, actual RunSession
journals and independently verified scorer receipts before measurement. Legacy
opaque hashes are insufficient. Candidate selection binds the training panel,
split, scorer, criteria and required benchmark set. Validation requires a
consumed custody-issued lease, eligible signed scorer calibration and an
independent decision; the final ledger decision must match it. Custody checks
each panel identity against its actual inventory and split before issuing a
panel receipt. These local checks still require separately deployed trusted
services and access restrictions; in-process signing fixtures do not establish
that deployment or substantive scientific calibration.

The retained Discovery training output was executed once as a separate Docker
diagnostic without new model calls. It observed a constant target across 500
rows and skipped regression. No scientific audit or score was issued; the
original failed pilot remains unchanged. Q2.4 also retains the authentic but
scientifically wrong agreeing-auditor fixture as a false-admission observation.
The original pilot's CLI cwd was inside the source checkout, so it also lacks
the required exported-workspace qualification. Future model runs must use a
fixed public work root outside all label-bearing source ancestors.

The subsequent BLADE training transport call completed with 7,085 input and
1,271 output tokens and no tool events. Its pre-call visible context matched a
reviewed frozen two-message base context. The controller nevertheless rejected
the CLI startup notice containing `skip_host_skill_discovery` as a skill-context
fault. This failed pilot is retained; it is not an efficacy observation. A
separate, zero-new-model-call diagnostic executed its program on the allowed
250-row BLADE fish input in restricted Docker. No scientific audit or score was
issued. Exact startup-notice classification has since been repaired and its two
prospective exceptions reviewed, without reinterpreting the failed ledger. Every
future model call still requires a fresh live match to its reviewed context. A
preceding root audit also caught a changed bundled
skill file; its failed audit and the subsequent stable render are preserved.

Review rejected preliminary Q7 code that relabelled validation identity as
train, and Q3/Q5 fixtures whose variant changes did not reach callbacks. The
integrated repairs preserve original provenance, retain actual callback outputs,
and exercise fixed execution allocation and evidence withdrawal. Q7's fixture
token budget is explicitly unexercised; four-execution ratio rounding is reported
alongside requested and effective percentages. No fixture result qualifies a
validation lease or turns successful execution into scientific evidence.

No new module or combination has completed its required paired training effect
study and independent validation. The live metadata inventory checked in this
continuation contains 403 items: 81 training items in 23 source groups, 322
quarantined items in 53 groups, no validation items and no leases. No task or
reference content was opened for this count. Repetitions or renamed tasks do
not create independent data.

The user authorized additional relevant datasets on 2026-09-12. The frozen
required benchmark set can now include ScienceAgentBench, SciCode, CORE-Bench
and AIRS-Bench while retaining DiscoveryBench and BLADE. Their source catalog
and metadata pins are in [MODULAR-EXTENDED-DATASETS.md](MODULAR-EXTENDED-DATASETS.md).
Catalog membership does not mean a runtime adapter, qualified split or scorer
exists. Shared datasets, papers and artifacts must be grouped before splitting.

All four new sources have retained pinned Git-tree metadata and repository
license artifacts with verified hashes. SciCode and ScienceAgentBench also have
restricted public-projection adapters and synthetic runtime-request integration
checks. CORE-Bench and AIRS-Bench remain catalog-only. No new source task payload
has been acquired, no validation groups have been assigned, and no scientific
score has been obtained from these four sources.

## Next required work

1. Complete the next bounded training transport contract with the repaired
   model port and freshly reviewed context; retain both earlier failed pilots.
2. Finish formal per-cell scenario adapters and substantive blind scorer
   calibration. Do not substitute synthetic signed counts for actual calibration.
3. Freeze matched schedules and conduct all required training-side module and
   combination experiments, including the separate meta-builder phase. A
   dedicated combination panel is still required: the Q-specific factor
   restriction cannot encode arbitrary pair/triple/full/LOO scopes. Its routing
   manifest must not be treated as an executed or scored contrast.
4. Acquire and qualify independent data under the expanded source scope, add
   restricted public adapters/scorers, verify deployment access isolation, then
   freeze validation panels and run acceptance. Never tune from validation.
5. Verify approved whole-package deployment and rollback on the intended host;
   report every Q/C obligation with evidence and unresolved limitations.
