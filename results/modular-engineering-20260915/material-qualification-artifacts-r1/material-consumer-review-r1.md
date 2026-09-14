# Material qualification consumer review, r1

Review scope: read-only source/integration review for auditable module outputs. Baseline source checkout: `artifact-evidence-provenance`, HEAD `6b22647be7019e97391e3a078ceb5ddfc6376120`. Implementation checkout: `material-qualification-artifacts`, branch `codex/material-qualification-artifacts`; implementation was uncommitted and actively changing during this initial review. No models, APIs, Docker, or VAL were run/read. This note is not final implementation approval.

## Contract and completion evidence

Behavior: preserve the existing two distinct configured authority opportunities and their exact request, returned typed response, checks, cost state, and overwritten sidecar bytes. Replay is storage-only and cannot invoke authority callbacks. Qualification is TRAIN-scoped pre-enablement work; it does not establish M1 activation, scientific validity, or independent scientific corroboration.

Safety invariant: no downstream model use or successful host verification can bypass the companion reader. Missing/failed/partial custody stays non-accepted while any retained failure evidence remains inspectable. Unknown cost stays unknown. Link/junction rejection must precede file content IO; public exceptions contain stable categories, not original exception text.

Deliverable: this bounded review note and concrete consumer integration assertions sent to the root agent. The root owns integration tests; implementation agent owns source changes.

## Verified existing host seams

- `full_loo_driver.py:78-88`: source qualify, admission assessments, and (for nonbaseline) corpus qualify precede RunSession creation and native provider work. C4 also blocks unknown qualification cost.
- `full_loo_driver.py:225-230`: successful host replay independently calls source replay, admission assessments, and corpus replay. `joint_train_runtime.py:393` reaches this verifier, so C5 inherits this seam.
- `lineage_combination_driver.py:178-180,231-235`: qualification occurs before session/model work; replay and admission assessments are called independently by host verification.
- `state_prediction_combination_driver.py:115-117,158-159`; `state_retrieval_combination_driver.py:163-167,214-216`; `state_exploration_combination_driver.py:165-167,215-216`; `state_scheduling_combination_driver.py:166-168,216-217`: same pre-model / independent replay structure. Retrieval qualifies both state and corpus.
- `state_improvement_build.py:198-201`, `state_improvement_combination_driver.py:73-79,111-114`, and `mechanism_improvement_combination_driver.py:79-91,126-138`: shared qualification in builder/target paths, with unknown cost blocking downstream work.
- `mechanism_exploration_combination_driver.py:184-185,261-262` and `mechanism_scheduling_combination_driver.py:184-185,261-262`: qualification precedes module IO; replay explicitly checks source qualification as the first post-lock trace event.
- `admission_combination.py:97-108`: inherited replay remains mandatory, then both authorities' assessments must match. `transition` makes admitted=false when M1 is disabled, despite the shared qualification having run.

## Minimal meaningful host assertions

1. Reuse `tests/test_joint_train_runtime.py` prepare/executor/full_recipe for one real history + one target execution. The existing bounded fixture uses 11 synthetic MAIN calls and 5 actual Docker calls across these two stages; no costly full grid is necessary. Verify source and corpus companion custody through `runner.verify` for both stages.
2. Reject the companion reader at its actual pre-enablement call during history execution. Assert zero new `common_logs`, no solver/build candidate, and failed/poisoned host state. Verify source/corpus authority counts separately so callback invocations are not confused with MAIN calls.
3. After a valid history, use a separate attack copy and coherently rewrite one companion journal semantic field plus its seal, then update the inner `files` and receipt and outer stage binding to avoid rejection solely on stale hashes. `runner.verify` must still reject the semantic inconsistency without callbacks.
4. One ordinary-control stage checks the shared qualification exists but does not claim M1 enabled/covered; keep existing disabled-module assertions. A passed material reader is not module activation.
5. A successful host case must assert exact sidecar versions (reserved-0, checked-0, reserved-1, checked-1); strict subject/binding; two configured responses; no replay callbacks. Invalid/unknown/rejected/exception cases can stay in the bounded material unit suite.

## Interim findings sent to implementation agent

The initial implementation accepted locally rehashed journals without sufficient event semantics. It also read journal/seal links and allowed non-hex blob references to construct paths. The current interim file adds link checks, strict hexadecimal blob references, and event-kind ordering, but is still being edited.

Remaining checks needed before final approval: exact snapshot progression including immutable prior call rows; exact response type/status/error semantics; strict terminal and begin/seal attempt binding; exact event schemas; source snapshot presence; partial write preservation; safe link checks on every writer/read path. `returned.typed=false` must not coexist with an accepted FrozenRecord response. A complete failed custody may be storage-valid but must not pass qualification replay.

No final verification claim is made against an uncommitted moving target. A final-commit re-review should append its commit and observed test evidence below.

## Bounded synthetic reproduction after first implementation commit

Implementation first announced `05018c7df97b1e29bebd5e9b30a137bb57dd752b` ready, but resumed editing before the probe imported it. Therefore the probe is explicitly NOT commit-pure. Captured companion source SHA-256 is `6da894cbac1de71c2d79da222a21bfad9a25b2e4104659584027b7ea35d49859`; qualifier source SHA-256 is `52b5aa0a4cb05810567320afdf51ac4fab45ba403461ed80d81742338c02f858`. Their literal bytes are retained by the original qualification companion. Probe: `work/material_consumer_probe_r1.py`; evidence: `work/material-consumer-probe-r1/outcome.json`.

The probe constructs one synthetic TRAIN material in memory (no datasets), two local signed authority callbacks, an original custody directory, and four independent attack copies. A separately injected sidecar-write failure makes one further local callback. Total: 3 synthetic authority callbacks, zero models/API/Docker/VAL.

Observed: removed producer inventory and injected checked error chain were rejected after intervening implementation fixes. A coherently rehashed extra event field was still ACCEPTED. A malformed checked data value produced raw TypeError instead of ContractError. Failure on the second sidecar `_write` propagated original OSError text `synthetic-private-storage-text`; partial storage inspection was readable after intervening edits. These findings were sent to root and implementation agent immediately. Successful inspection of partial storage is not accepted qualification.

## Ownership change and repair delivery

The root explicitly reassigned implementation ownership of `research_loop/modular/material_qualification_artifacts.py` and `tests/test_material_qualification_artifacts.py` to this agent after the initial implementer stopped. The root retained ownership of `lineage_combination_material.py`, `admission_combination.py`, and separate host/failure tests. This phase was authorized implementation, not read-only review.

Repair commit: `c775593d` (only the class and its focused tests). Root fixes were cherry-picked into the implementation checkout as `479c525b` (upstream bfb24afb), `da106849` (267ab4c3), `429bcead` (790e49ed), and `a077468e` (757c899c). Root should cherry-pick only `c775593d` into its already updated source tree.

The class now records original request/material/binding/cell inputs in an exclusive `attempt.json` before blob/source work; validates exact event/data/seal fields and canonical bytes; rejects unknown files, unreferenced blobs and links before content IO; binds exact earlier sidecar versions in order; binds accepted response types, authority/request/limits and cost accounting; checks all three current producer source snapshots; and exposes a storage-only inspector for rejected and partial failures. Failed storage has an independent inventory covering retained companion bytes plus current receipt and temporary receipt. Parseable complete original attempt and begin identifiers must match the failure marker. If the first attempt write itself is malformed, the retained marker is storage-only and does not authenticate a historical subject ID. Arbitrary untyped objects retain an explicit type-only coverage marker; bounded plain JSON values retain literal canonical contents without invoking repr/str.

Preliminary native run r2 actually exited 1: 50 tests, 49 passed, 1 failure, zero errors/skips, 457.329 seconds. The failing authority-attack case failed during original qualify before any attack modification while the source file was still being edited; traceback lines consequently refer to changed source. This run is NOT commit-pure and is not final approval. Retained JUnit: `work/material-own-r2.xml`; final failure/summary stdout: `work/material-own-r2-output.txt`; all original and attack-copy files: `work/material-own-r2/`. Earlier r1 was explicitly interrupted after partial progress when superseded, and is not counted as a completed verification.

After r2 exit the queued metadata/failed-attempt/canonical-byte repairs and three additional tests (unknown cost and two failure-marker attacks) were included in `c775593d`. Static py_compile and git diff --check passed. The root explicitly owns the authoritative frozen-source rerun of all 53 focused tests plus host integration; no duplicate full run was launched here. No model, API, Docker, or VAL operation was performed by this agent. Native sessions are complete or explicitly interrupted, with none left running.
