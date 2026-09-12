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
