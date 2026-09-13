# Running the modular implementation

Use an isolated checkout and Python 3.11 or later with the project's development
dependencies, including the custody extra for the bounded YAML metadata parsers:
`python -m pip install -e ".[dev,custody]"`. Existing production pause and historical
study protocols are separate. Record the interpreter and resolved dependency
versions with each source-qualified run; a globally installed package is not a
declared project dependency.
Solver exports and test temporary roots must be outside every ancestor containing
`data/labels`. Create a task work directory beside the source checkout, then use
a new absolute subdirectory for each pytest run. Do not relax the label-isolation
guard to run an exported solver beneath this checkout. Keep retained evidence
outside pytest's temporary directory, which pytest may clean on reuse.

```powershell
python -m pytest tests --disable-warnings --basetemp ABSOLUTE_TASK_WORK/pytest-RUN_ID
python -m research_loop.modular plan --baseline BASELINE_COMMIT --output work/programme-plan.json
python -m research_loop.modular plan --baseline BASELINE_COMMIT --benchmark scienceagentbench --benchmark scicode --benchmark corebench --benchmark airsbench --output work/expanded-programme-plan.json
python -m evaluation.modular.custody --state work/custody.json inventory --snapshot SNAPSHOT_ROOT
python -m evaluation.modular.custody --state work/custody.json split --seed modular-v1
python -m evaluation.modular.custody --state work/custody.json export
python -m research_loop.modular trace work/RUN/trace.jsonl
```

The plan includes all 48 original obligations, 9 singleton/conditional designs,
36 pairs, the 5 specified triples, full-bundle ablations and a pending final
train-selected target. It records exact source hashes. A plan is not an executed
experiment or an acceptance receipt. Preserve a changed plan under a new path.

`RunSession` freezes one public task, objective, package, activation vector, call
schedule, required audit checklist and execution allocation. Its model callback
receives an immutable public request. Generated Python goes through the restricted
Docker broker. Both scientific audit signatures must bind the same task, objective
and actual execution; missing, inconsistent or malformed audits block the final
positive/negative decision. A withdrawn evidence root remains ineligible even if
an older audit admitted it. Scientific state still depends on the independent
validator's substantive judgment, rather than on HMAC or process exit status.

Calls are reserved before I/O, failures are retained, and incomplete sessions
cannot silently resume their provider calls. The trace command checks ordering
and hash linkage; its journal is not an external signature or an OS boundary.
Deployment must keep audit keys, scorer inputs and validation logs outside model
workers and optimizer access. Passing local component tests does not establish
that complete deployment isolation.

The two benchmark adapters preserve public input schemas. Historical scores are
adapted scores with separate dimensions, not official leaderboard results. Only
new runs with explicit data provenance, frozen scorers, mechanism-specific
coverage and complete paired receipts can advance their experiment obligations.
Training feedback may select configurations; validation only accepts or rejects
the preregistered target. Additional validation source groups are still required.

The expanded plan freezes its benchmark set for every obligation. Additional
catalog entries currently require their own public adapter, independent data
qualification and scorer; a plan alone does not make them runnable. The original
two benchmarks remain in the plan. Changing this set creates a new plan digest.

For validation, configure custody and calibration authority keys on the trusted
service. Use `CustodyStore.lease_panel()` with an actual `FrozenPanel`, then
consume its one-use lease and obtain `issued_validation_receipt()`. The raw
metadata lease API cannot issue a panel acceptance receipt. Exact inventory
task, canonical group, dataset version, split and scorer calibration are checked.
The CLI intentionally has no key-loading shortcut to bypass this service boundary.

`panel_plan.compile_train_panel()` consumes already prepared training `PublicTask`
objects, per-task public evidence, frozen budget/scorer/criteria records and an
actual `CandidatePackage` for every legal runtime-arm digest. It constructs the
complete task × variant × arm × replicate grid for any or all 48 obligations.
P0-only obligations have one fixed control arm bound to a source/protocol hash;
P0 is always enabled. Compiling a grid does not qualify its driver or scoring.

`panel_runner.run_train_cell()` supports Q1.1–Q1.7, Q2.1/Q2.3–Q2.6, Q3.1–Q3.5,
Q4.1–Q4.5 and Q5.3. Q3.2/Q5.3 currently execute planning operations only.
Q2.5/Q2.6 require signed caller material; Q2.6 also requires the exact per-task
`objective_by_task` mapping frozen before panel compilation. Material audit
signatures do not replace actual session execution receipts.
Q3.3–Q3.5 require a caller-frozen scheduler source/bundle with exact prepared
task, candidate and workload bindings. Their bounded integer workers measure
synthetic scheduling behavior; actual benchmark evaluation is a separate seam.
Q1.1–Q1.4 and Q1.6/Q1.7 require typed caller material and the record-bound
`history_admission_port`, which the train controller forwards. Q2.1 and the Q4
family require their typed per-task material bundles. Planning fixtures cannot
substitute for these runtime inputs. Q4.5 heterogeneous routing still fails
without the required independent route evidence and remains in the denominator.
Q2.3/Q2.4 require `audit_receipt_port` and `shadow_execution_port`, with actual
program/input hashes matching the frozen shadow contract. Fixed host checks
remain common to both arms; only M1-on admits the evidence.
Typed runtime and optional scorer receipts pass to `PanelReceiptVerifier`.

The controller's explicit `linked_benchmark_solve` mode currently supports
Q1.5, Q3.1 and Q4.3. It adds analysis-program and final-answer calls, executes
the program in the frozen restricted Docker image, and exposes verified
`linked_results` for scoring without rerunning the solver. No token matching or
scientific efficacy follows from completed execution.

The separate train-only stdio scoring worker is described in
[MODULAR-LINKED-SCORER-PROCESS.md](MODULAR-LINKED-SCORER-PROCESS.md). It requires a
full frozen panel, configuration hash, private train-reference manifest and
separate executor/scorer authority keys. Run the production worker with empty
stdin first to check initialization without a provider request. Keep evaluator
ledgers and references in the private store; use a fixed reviewed environment
and a fresh no-tools context check for every provider call. Unknown reservations
must be investigated, never silently retried. This process boundary does not
establish OS account isolation or scientific scorer calibration.

SciCode and ScienceAgentBench accept restricted public projections through their
adapters. They do not acquire source data or accept complete Hugging Face rows.
See [MODULAR-EXTENDED-INGESTION.md](MODULAR-EXTENDED-INGESTION.md) for the pinned
source schema, private-field boundary and pending custody work.

## Terminal linked training attempt and new runs

The first scored linked attempt is preserved, closed and inconclusive; see
[MODULAR-CHECKPOINT-20260913-TRAIN-TERMINAL.md](MODULAR-CHECKPOINT-20260913-TRAIN-TERMINAL.md).
Do not resume or overwrite its directories. Its clean base context did not
prevent dynamic request metadata leakage. A subsequent attempt needs a new
frozen source/configuration, directory, reviewed dynamic public projections
and explicit training-only scoring allocation. Full controller provenance is
retained for verification; the solver receives only the typed public projection.
