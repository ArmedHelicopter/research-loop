# Q3.2 durable M4 artifact review, r1

Baseline reviewed read-only: `artifact-evidence-provenance` at `e76f548700954afc7d054d208922d8558ee450e6`. No models, APIs, Docker, or VAL were executed/read. Root owns implementation. A later explicit delegation authorizes this agent to add only `tests/test_q32_artifact_attacks.py` in the isolated `codex/q32-artifact-review` worktree based on e76f5487; tests have not been executed pending the final root interface and frozen source.

## Actual producer and consumer map

- `q32_execution.py:67` creates an in-memory PredictionRegistry during compilation. It validates caller plans but is not the actual runtime durable M4 producer.
- `Q32ExecutionStage.__init__`, lines 142-155, creates the actual RunSession and a separate PredictionRegistry with `storage_path=predictions.jsonl`. Its freeze loop writes through the registry, but it supplies no `event_sink`, so the durable M4 journal never enters the existing per-event artifact bridge.
- `modules/predictions.py:_apply(persist=True)` calls JSONL append/fsync before the event sink. The replay constructor uses `_apply(..., persist=False)`, but `_JsonlLog.__init__` still calls mkdir/touch on a supplied path. A read-only verifier must preflight/read the original bytes and reconstruct in memory, rather than create a filesystem-backed replay constructor.
- `q32_execution.py:184-186` writes `execution-seal.json` and records its value in the trace. `execute_next:193` compares a decoded FrozenRecord to in-memory seal, so whitespace drift is not caught as literal original-file drift. It does not recheck the durable prediction journal before using its in-memory registry.
- `execute_next:200-211` traces the execution job and derived observation/range membership. `run:259-260` traces the terminal result and writes `result.json`. These are actual output sites; they are not durable typed M4 descriptors with explicit plan/seal/observation parents, and the Q3.2 route never seals its session artifact catalogue.
- Actual independent verifier is `evaluation/modular/q32_execution_verifier.py:verify_q32_execution` (not q32_execution_verify.py). It checks trace chronology and reconstructs sealed jobs, observations, range memberships, final context and denominators. It does not read predictions.jsonl, execution-seal.json, result.json, the artifact catalogue or its seal.
- `q32_native_provider.py:run_native` calls that trace verifier and derives `projected_events`, then binds projected requests to the PhaseProviderLedger. Projection is a checked derived view of original traces, not an actual prediction/seal/result producer.

## Confirmed baseline bug

The joint variant assigns `_plans=[task['plans'][0]]*3` and freezes every element in the same registry. PredictionRegistry rejects the second identical plan ID. Freeze each unique plan ID once: one durable freeze for joint, three for separate. Preserve the three measurement jobs and all original budget/denominator semantics.

## Smallest correct integration

Attach `M4M5ArtifactBridge.journal('predictions', event)` to the real runtime registry writer. A dedicated Q32ArtifactBridge may own the Q3.2 files and typed descriptors; no new review journal is necessary. Do not call the existing generic M4/M5 reader unchanged because it requires both prediction and review source files.

The accepted descriptor graph should bind the exact unique plan freeze(s), all three real producer responses, durable execution seal, each actual execution binding/observation, comparison-ready input and final result. Seal/result file bytes must be fsynced and bound exactly, and successful closure requires the final catalogue seal. Prefix verification before each model/execution call must reconstruct the expected graph from original files, not trust the in-memory registry. Full independent verification must require both this graph and the existing trace semantics.

Range matching must remain a Q3.2 engineering observation. Do not call PredictionRegistry.record_outcome or manufacture its trusted evaluator receipt: that API represents a separate validated evaluator operation. M4 remains fixed background, all scientific_validated flags remain false, and four model/three execution opportunities per cell remain unchanged.

## Lifecycle and filesystem gaps sent to root

1. Native stage construction occurs outside its guarded try. A real freeze-sink failure can escape without a closed cell/panel denominator. Guard initialization and preserve its zero-call failure prefix.
2. `run` final finish/result trace/file writes occur after its try. Artifact publication failure there must leave independent failure evidence and a non-accepted stage.
3. Native `value is None -> blocked(cell)` reports zero attempts even if final publication fails after models/executions. Retain actual consumed counts and rows in a failure envelope; do not replace paid/executed history with unattempted placeholders.
4. Native earlier-cell checks only re-inspect provider sessions. A changed earlier prediction/seal/result/catalogue can survive while provider originals remain healthy. Reverify prior completed stages before later cell dispatch and again before aggregate eligibility. Existing later_provenance semantics ([4,4,0,0] calls and six historical executions) give a bounded analogous test.
5. Reject output links/junctions before content IO and before opening replay constructors. Literal file reads and byte snapshots must check exact newline/canonical representation and must not silently recreate missing journals.
6. Existing trace-only attacks should be moved into complete copied sidecars, with an untouched-copy positive check first, so rejection cannot be explained solely by missing artifacts after the new guard is introduced.

## Independent tests in preparation

The separate test file uses real Q3.2 file writers/readers with explicitly synthetic in-process model and broker fixtures; it is not Docker execution evidence. It covers unique freeze counts, independent exact-file verification, missing-journal read-only behavior, prediction drift before the second model callback, seal drift before first broker invocation, and linked outputs. Every completed original is preserved, and file/DAG attacks use independent full-sidecar copies. Coherently rehashed parent-link tests await the root bridge's exact descriptor interface.

## Delivered independent tests and interim integration review

Delivered commit `17a4e8af` on `codex/q32-artifact-review`, isolated tree `E:/_ryanDev/AI/research-loop-modular/q32-artifact-review`. The only committed file is `tests/test_q32_artifact_attacks.py` (207 lines; 20 parametrized cases). Root owns integration and authoritative frozen execution. These tests have not been run; only the staged whitespace/diff check completed successfully. This is a test implementation deliverable, not passing test evidence.

Additional cases now include linked public trace, linked catalogue, four coherently rehashed missing-parent attacks (seal, observation, comparison-ready, result), literal analysis program substitution with a recomputed closure inventory, and program mutation after the first broker call that must prevent the second call. The coherent graph attacks recompute payload metadata, descriptor hashes, parent remapping, catalogue chain/seal and closure inventory, then assert the generic catalogue reader accepts the structure before the dedicated semantic reader rejects the missing dependency. Each completed original remains intact; each full copied sidecar passes the independent reader before mutation. Readers are checked for absence of callbacks and file recreation.

The root working implementation was reviewed as an interim mutable patch, not a final commit. Its Q32ArtifactBridge records q32_output descriptors into the existing RunSession catalogue and reuses M4M5ArtifactBridge only for the actual prediction journal event sink. Prefix/full verification reconstructs the expected unique freeze journal in memory, checks exact output bytes and explicit parents, and binds the complete closure inventory. Additional critical gaps reported during that review were public trace content IO preceding link rejection and an analysis-program inventory hash that lacked comparison to its actual sealed producer/execution binding. Root reports repairs to both, strict sequence/bool checks, output allowlisting, empty evidence/claims for this M4-only host, guarded initialization/final publication, historical count retention, and prior-cell/final eligibility rechecks. Those reported repairs await frozen combined verification; this note does not upgrade them into executed evidence.

No model/API/Docker invocation, subprocess experiment execution, VAL inspection, or scientific validation was performed by this reviewer during this Q3.2 assignment. TRAIN scope and the original four model/three execution opportunities per cell remain the intended invariant.

## Frozen r1 outcome and exact-byte repair

The completed r1 closure records source commit `13ab80cc363742ed35201f513d9dd6abd98e313b`, exit 1, 51 tests, 23 passed, 28 failed, zero errors/skips, and unchanged frozen sources. Root reports 276.578 seconds and 739 unchanged source files. The failed originals and JUnit remain at `work/q32-artifacts-frozen-r1` and `work/q32-artifacts-frozen-r1.xml`; this failed run is retained rather than overwritten.

Static inspection confirmed the shared failure: the new writer emitted canonical JSON plus LF, but `execute_next` passed the entire file text to FrozenRecord, whose constructor rejects any encoded string unequal to canonical(decoded). The exception occurs before equality comparison, stopping the first execution after three producer calls. No second compatibility issue was established by the bounded reader scan.

Single-line repair in `4798e81a354d5c8203f1b88dada35cc2643c98f1`: compare `plain(seal_path).read_bytes()` directly with `(self._seal.encoded + '\n').encode('utf-8')`, preserving exact bytes and the existing prefix gate. Root owns the r2 frozen rerun; this reviewer did not execute tests or modify repository files.

## External archive helper pre-execution review

Read-only review of `work/archive_q32_artifacts_r1.py` found that runtime files are copied as original bytes with before/after read equality and SHA-256 inventories, source archives have per-member length/hash checks plus ZIP CRC checks, and the helper invokes only independent readers. It selects runtime subdirectories rather than provider/private scoring directories, and explicitly disclaims full native provider/environment replay.

Three changes were sent to root before archive execution: distinguish a structurally verified failure/incomplete envelope from an actually successful complete runtime when assigning status/counts; retain literal original pre-producer independent-inputs.json and panel compiled.json bytes alongside the reconstructed reader inputs; and compare current imported reader source bytes to the closed successful source manifest before imports/verification and after archiving. The original helper's complete_runtime_verified count can include failure envelopes with blocked rows because the independent verifier correctly accepts honest failure histories. The test-window source_unchanged flag alone does not bind a later mutable-source archive invocation. These are archive evidence/classification concerns, not a claim that callbacks were rerun or private providers were copied.

## Root frozen verification and archive repair follow-through

Root completed r2 at 4798e81a354d5c8203f1b88dada35cc2643c98f1: 51/51 checks passed, zero failures/errors/skips, 418.093 seconds, 739 unchanged source files. Native exec session 9836 exited 0 before any subsequent repository edits. The original accounting reader counted 172 synthetic model requests, 117 execution requests, and 70 distinct actual Docker invocation receipts; the other execution receipts belong to explicitly synthetic broker tests. No model service, paid API or real VAL was invoked. r1 retains 143 synthetic model requests and zero execution requests; its failed records and source archive remain unchanged.

Before archive execution, root separated verified_completed_allocation, verified_failure_envelope, prefix_only and nonaccepted_retained_bytes. Completed allocation can include a failed measurement program and does not mean scientific success or native panel eligibility; per-measurement statuses remain explicit. The helper now copies exact original independent-inputs.json/compiled.json bytes, and checks current reader source hashes against the closed manifest before imports and after archiving. This paragraph records root verification, not a claim that the independent reviewer executed it.
