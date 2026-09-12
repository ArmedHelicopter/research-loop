# Running the modular implementation

Use an isolated checkout and Python 3.11 or later with the project's development
dependencies. Existing production pause and historical study protocols are separate.
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

`panel_runner.run_train_cell()` currently supports Q3.1. Its two real model
requests bind the task, controlled diagnostic, package and exact panel cell.
M4-on freezes a prediction plan and supplies it to the final request; M4-off
supplies the control response. Typed runtime and optional scorer receipts pass
to `PanelReceiptVerifier`. Other Q drivers fail closed at this entry point until
their mechanisms are connected. The existing engineering scenario drivers are
not automatically substituted as formal benchmark runs. This Q3.1 driver does
not execute code or claim matched token consumption.

SciCode and ScienceAgentBench accept restricted public projections through their
adapters. They do not acquire source data or accept complete Hugging Face rows.
See [MODULAR-EXTENDED-INGESTION.md](MODULAR-EXTENDED-INGESTION.md) for the pinned
source schema, private-field boundary and pending custody work.
