# Independent integrated artifact review r1

Reviewed checkout: `E:/_ryanDev/AI/research-loop-modular/artifact-evidence-provenance`.
Reviewed commit: `128fad63aea95eb9e77d764e9fb17d1e858ef83a`.
Date: 2026-09-14. Scope: M3/M4/M5/M6 event provenance and their C4 stage reader integration, plus the Q8.4 source ledger seam. M7/M8/M9 and scientific efficacy were outside this bounded review.

No reviewed source, test fixture, or real data was written by this reviewer. All synthetic output was confined to the sibling `work` directory. No real model API, Docker invocation, scoring process, or validation data was used. Runtime model callbacks in the reproducer return a literal synthetic FrozenRecord.

## Actionable findings

### 1. [P2] M3 reader accepts an after-the-fact context witness with no parent

Location at reviewed commit: `research_loop/modular/context_artifact.py:174-218`; integrated at `research_loop/modular/full_loo_driver.py:184-194`.

The reader selects all `model_context` descriptors and validates their contents against requests and evidence snapshots, but never checks descriptor parents or the descriptor's position within the catalogue. `RunSession.invoke` actually writes this descriptor before `model_request`, anchored to the immediately preceding trace. An attacker or damaged exporter can move it after `model_response`, clear `parents`, and coherently recompute the catalogue and seal; the provenance readers still accept it.

Minimal verified case: create one synthetic session, invoke its sole final slot, seal, move the `model_context` envelope to the end, set its descriptor parents to `[]`, rebuild descriptor/envelope hashes and seal. All four readers called in `verify_stage`—evidence, context, M4/M5, and retrieval-event—accept. Repeated for both enabled M3 (`M2,M3`) and disabled M3 (empty arm). Trace bytes and module output bytes remain unchanged.

Required regression: reject late, missing-parent, wrong-parent, duplicated, and orphan context descriptors; retain acceptance for the actual pre-request writer order in both activation states. Bind the witness to the immediately preceding trace and the next matching model request; do not require it to follow its request.

### 2. [P2] M4 freeze correspondence is checked after the catalogue traversal, so delayed freeze witnesses pass

Location: `research_loop/modular/m4_m5_artifacts.py:286-305` (`_check_c4_prediction_freezes`, called at line 236). The function is called after all catalogue descriptors have been consumed.

The C4 freeze check searches the complete prediction journal for a matching registered plan. It does not require the corresponding M4 descriptor to have preceded the `c4_prediction_frozen` trace event. The general per-journal parent check only checks the latest trace at the descriptor's new position.

Minimal verified case: create an M4 session, freeze a public plan, record `c4_prediction_frozen` with its real registered plan, and seal. Move the single M4 journal descriptor after the C4 freeze trace, retie its parent to that trace, then rebuild hashes/seal. All four stage readers still accept. The trace and prediction source journal are unchanged, so the later `verify_stage` journal/content replay cannot distinguish this mutation.

Required regression: resolve the exact registered plan against an already-seen M4 freeze descriptor while traversing the C4 trace; reject a matching descriptor recorded only later. Apply the corresponding preceding-submission invariant to M5's C4 sealed events if that event is intended to attest that durable submission has already occurred. The latter is a suggested coverage requirement, not a separately reproduced M5 bypass.

### 3. [P2] Q8.4 source-ledger reader permits a different task payload under the same DataIdentity

Location at reviewed commit: `research_loop/modular/retrieval_artifacts.py:160-174`.

`verify_q84_source_ledger_artifacts` compares the lock's identity with `task.identity`, but does not compare the lock's `task_digest` to `task.content_hash`. Reopening `EvidenceLedger` validates its DataIdentity; it does not provide the missing PublicTask payload binding.

Minimal verified case: run the real `_provenance` method using three synthetic sources and literal admission/provenance callbacks. Call the source-ledger reader with a new PublicTask that retains the same DataIdentity but changes `{'question':'public x'}` to `{'question':'different public question'}`. It returns a three-descriptor verified record. The adjacent `verify_retrieval_event_stream` correctly rejects that changed task, which isolates the mismatch to the source-ledger entrypoint.

Required regression: reject same-identity/different-task-hash inputs; bind the source ledger's subject bindings and accounting/version trace to the same lock and durable trace. Repository-wide code search found no non-test caller of `verify_q84_source_ledger_artifacts`; the Q8.4 acceptance path still needs an integration check demonstrating that it actually invokes this reader. C4 itself does not emit Q8.4 source-ledger rows.

### 4. [P2] Complete-grid test reads the old catalogue row shape

Location: `tests/test_full_loo_runtime.py:159-163`.

The test JSON-loads `artifacts.jsonl`, then accesses `d['coverage']`, `d['module']`, and `d['scientific_validated']`. Current rows are `artifact-catalogue-entry-v2` envelopes, and those fields live under `row['descriptor']`. The first such field access therefore raises KeyError after the grid completes. This is a deterministic test defect identified by reading the writer and consumer, not a completed full-grid test run by this reviewer.

Required change: unwrap the envelope or use the public catalogue records reader before asserting module coverage and scientific flags. Then rerun the actual complete-grid integration test with root-owned resources.

## Reproduction evidence

- `work/integrated-artifact-repro-r1.py`: combined synthetic M3/Q8.4 reproducer (later extended with the M4 case).
- `work/integrated-artifact-repro-9f7ff0caf4/`: first successful run against the reviewed commit, confirming both M3 activation states and Q8.4 task substitution.
- `work/integrated-artifact-m4-repro-r1.py`: independent M4-only reproducer with no model invocation.
- `work/integrated-artifact-repro-c895248f93/`: successful M4 mutation output.

Command pattern: `python -B E:/_ryanDev/AI/research-loop-modular/work/integrated-artifact-m4-repro-r1.py`. Set `PYTHONDONTWRITEBYTECODE=1` when reproducing against a frozen source checkout. The script intentionally asserts/prints currently accepted bad provenance; convert these cases to `pytest.raises(ContractError)` for regressions after repair.

A first setup attempt used the illegal arm `M3` without required `M2`, correctly failed the compatibility contract, and was repaired to `M2,M3`. This did not touch the reviewed source. Later, root-owned edits appeared in `context_artifact.py` and `retrieval_artifacts.py` while HEAD remained at the reviewed commit. A rerun then rejected the honest M3 pre-request descriptor; this was reported immediately to the parent. This report's findings concern the original reviewed commit, and it does not certify those in-progress repairs.

## Verified strengths and remaining acceptance

- `verify_stage` calls source/canonical catalogue verification, exact trace correspondence, M1/M2 replay, M3 snapshot replay, M4/M5 replay, and M6 event replay before continuing with provider evidence.
- The retrieval trace bridge is synchronous after durable trace append. Existing targeted tests cover provider reservation before I/O, failed provider cost preservation, missing/extra/substituted events, delayed trace witnesses, and terminalization when a witness cannot be written.
- Q8.4 uses a dedicated persisted ledger with a synchronous source-ledger bridge; it does not mint entries in the session's scientific evidence ledger.
- Enabled/disabled statuses are checked explicitly in the readers. Their status checks do not repair the causal gaps described above.

Independent confidence: high for the reproduced M3, M4, and Q8.4 reader failures, and high for the static test row-shape defect. No finding claims a false scientific result or efficacy. Final acceptance requires repaired regressions plus the root's complete native-stage/control checks; this bounded review did not rerun the 22-cell Docker grid.

