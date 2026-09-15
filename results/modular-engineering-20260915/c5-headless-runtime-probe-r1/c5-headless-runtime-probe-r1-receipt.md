# C5 headless runtime probe r1 receipt

This is an engineering-only synthetic native probe. It is not a C5
qualification run, does not score a panel, does not execute the full controller,
does not select a result, and does not access labels or VAL material.

## Source and scope

- Worktree: `E:/_ryanDev/AI/research-loop-modular/c5-headless-runtime-integration-r1`
- Base: `0a9ca90abfb16ded9a6d5f312739a56cf18e7bb9`
- New test before commit: `tests/test_c5_headless_runtime_integration.py`
- Test SHA-256 before commit: `EB5AC56E9900749C284E525B5310B8E11D1479CDAE26B7D8EA473FD0CDDC2ADE`
- Commit: `fad4ed4b2d8d3782f7e0b9366af8b9967ef282c1`
- Test SHA-256 after commit: `EB5AC56E9900749C284E525B5310B8E11D1479CDAE26B7D8EA473FD0CDDC2ADE`
- Worktree was clean after the commit.
- `git diff --check`: passed before commit.
- Sparse checkout excludes `results/` and `data/labels/`.

## Retained invocations

Every invocation used a distinct external `--basetemp`, with `TEMP` and `TMP`
on `E:`. All native process sessions returned by the shell tool were joined.

| run | basetemp / JUnit | result | reason |
| --- | --- | --- | --- |
| r1 | `work/c5-headless-runtime-probe-r1-basetemp`; `...-r1-junit.xml` | collection failure | imported `_plan` from `test_modular_benchmark_solver`; that module does not export it. No probe body ran. |
| r2 | `work/c5-headless-runtime-probe-r2-basetemp`; `...-r2-junit.xml` | assertion failure | stage inner receipt has no `component_digests`; the C5 outer stage record is the correct component binding. |
| r3 | `work/c5-headless-runtime-probe-r3-basetemp`; `...-r3-junit.xml` | assertion failure | history has no solver execution; only the target stage owns solver execution. |
| r4 | `work/c5-headless-runtime-probe-r4-basetemp`; `...-r4-junit.xml` | passed | one test passed after native session `12979` was joined to exit 0. |

The r1--r3 files are retained and were not overwritten by r4.

Retention gap: r1--r3 have retained JUnit files and distinct basetemp
directories, but no separate immutable source copy was made before each attempt.
The committed/r4 source cannot reconstruct the exact r1--r3 bytes. The stated
failure reasons come from retained pytest output, not complete per-attempt
source archives.

## Prepared full-controller path

Commit `3c1a7f59fcd0a5c3978ae3152bff0ebc914cae0f` adds
`tests/test_c5_headless_runtime_controller_full.py` (SHA-256
`3F7872B1041B4B0280EF908D67B5527CE4C2942EF424155E5F1CA10E705BB6CD`).
It is an explicit pytest skip pending root profiling review. Its future
single-run path calls `run_joint_common_train` with the real headless stdio
scorer factory, then verifies the run and exercises authenticated selection
registration and registration verification. Its gated verification invocation
retained `work/c5-headless-runtime-controller-gated-r1-basetemp` and
`...-gated-r1-junit.xml`; it skipped one test and dispatched no solver or
evaluator process.

Commit `d955f5a30d1360360e673e6bb3555f57237b72ab` corrects the future receipt
assertion to `complete_train_engineering`, removes a duplicate full verifier
call before registration, and adds registration-level selection assertions.
It also adds a no-grid factory preflight for deterministic frozen handle hashes,
pure evaluator-descriptor equality, and server serialization. Its r4 JUnit is
`work/c5-headless-runtime-controller-preflight-r4-junit.xml`: one pass and one
intentional full-grid skip, with no solver or evaluator dispatch.

## r4 observed scope

The test froze `HEADLESS_OBLIGATION`, 59 recipes, 46 canonical history builds,
two TRAIN targets, 930 solver opportunities, and 118 target/scorer cells. It
used `GrokHeadlessTrainProvider` with
`grok-headless-train-solver-port-v1`, then executed only the full-recipe history
stage and one target stage. Eleven synthetic solver calls occurred. The pure
headless evaluator descriptor bound the worker configuration, but evaluator
prompts and native GETs both remained zero: evaluator execution, final closure,
selection, and registration were not exercised.

The retained run root is
`work/c5-headless-runtime-probe-r4-basetemp/test_c5_headless_runtime_probe0/headless-common-run`.
The history stage id is
`950f42de4d4b0eb198b1582e809e7f681e2ba42008499cdc48dbb0e7a7f6357e`; the target
stage id is `e1c5188232f8b94daa4c1db56b8e4bc05049842acc33ec8efb2063ab7075f4f1`.
Each has `runtime/artifacts.jsonl`, `runtime/trace.jsonl`, a stage record, a
provider ledger, and its immutable provider-originals file referenced by that
ledger. `provider-scopes.json` is at the common-run root.

Artifact-descriptor status counts are retained facts, not a claim of full-grid
coverage. History: M1 produced 1; M2 produced 13, withdrawn 1; M3 produced 6;
M4 produced 2; M5 produced 7; M6 produced 14; M7 produced 8; M8 not_applied
13; M9 produced 8. Target: M1 produced 1; M2 produced 13, withdrawn 1; M3
produced 7; M4 produced 2; M5 produced 7; M6 produced 14; M7 produced 8; M8
produced 14; M9 has no target-stage descriptor because it is history-build-only.
No descriptor has status `failed`.
