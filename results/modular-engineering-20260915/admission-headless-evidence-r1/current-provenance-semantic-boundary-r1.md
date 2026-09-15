# Current provenance semantic-boundary audit r1

Read-only audit of ROOT `ab244b8a461e7d47a9c1705d255c7f9c7771976f`.
The worktree was clean at inspection.  No benchmark/VAL payload, credential,
model/API, Docker, source, or test execution was accessed.

## Finding

The current public documentation has corrected the historical overstatement:
`docs/MODULE-ARTIFACT-COVERAGE.md:14-18` says that the 52 direct catalogue
references caused by default recent-event attachment do **not** establish
semantic consumption or complete coverage.  `docs/MODULE-ARTIFACT-PROVENANCE.md:48-50`
also says an unknown event remains a coverage gap, and :54-68 separates
`consumes`/`derived_from` from lifecycle edges and requires affected results to
be marked for review after an upstream withdrawal.  The linked C5 narrative is
therefore not currently using `has_direct_catalogue_reference` as a synonym for
`consumes`.

The implementation retains the same distinction in the M2-specific reader:
`evidence_artifacts.py:63-91` emits typed payload `relations`; :115-123 derives
the semantic parents from those relations and then `Runtime.record_artifact`
adds the latest trace parent.  Its replay verifier reconstructs relations and
expects `semantic parents + latest_trace` at `evidence_artifacts.py:244-260`.
For example, an M2 withdrawal has a typed `withdraws` edge to the recorded root
(:69-72), and a subsequent refresh has typed `withdrawal_observed` references
(:87-90).  That is a concrete, producer-specific route; the trailing trace
parent is not relied on as semantic evidence.

## Reproducible gaps (two)

### 1. Generic descriptor parents have no relation type or generic impact closure

`ArtifactCatalogue` v2 accepts and persists only `parents: list[str]`
(`artifact_catalogue.py:57-77`, :99-124).  There is no per-parent relation or
marker for an automatic trace attachment.  `Runtime.record_artifact` then
unconditionally appends the current trace descriptor after caller-supplied
parents (`runtime.py:332-341`), while its docstring calls this an attachment,
not consumption.

Consequently, a generic catalogue consumer can establish only
`has_direct_catalogue_reference`; it cannot determine whether each parent was
a supplied semantic dependency or the automatic trace anchor.  Some module
readers can recover the distinction from their own payload—M2 does—but this is
not a property enforced by the common descriptor contract.  This is the narrow
remaining contract/implementation gap behind the corrected public wording; it
does not invalidate M2's typed replay.

The same limitation prevents a generic failed/withdrawn-to-affected closure:
the common verifier validates only earlier same-identity parents
(`artifact_catalogue.py:74-77`, :106-108, :133-146) and status enum values
(:10, :63-68).  It has no reverse traversal, typed-edge requirement, or
`affected_pending_review` record.  M2's special payload makes a concrete
withdrawal traceable, but a generic failed or withdrawn descriptor with only a
trace anchor has no semantic descendant set.

Therefore the contract requirement at `MODULE-ARTIFACT-PROVENANCE.md:67-68` is
implemented by specialized bridges, not catalogue-wide.  Treating every
reverse-reachable descriptor as affected would be wrong because the automatic
trace edge is chronological attachment rather than semantic consumption.

**Reproduction:** append a module artifact through `Runtime.record_artifact`
after one trace event with no supplied parents, then mark a later generic
descriptor `failed` or `withdrawn`.  A fresh `ArtifactCatalogue.records()`
consumer receives opaque parent hashes only; `verify()` accepts journal
integrity but exposes neither parent semantics nor an impacted-review set.

### 2. Finalize client does not preserve malformed/tampered received closure bytes

`CombinationScorerProcessClient.finalize_headless_evaluator` writes the
finalize request, immediately parses the single received line, constructs a
`FrozenRecord`, and verifies its signature before assigning `self.final_closure`
(`evaluation/modular/scorer_process.py:878-898`).  This path contains no raw
response file, hash record, or client-side finalization journal append before
JSON/schema/signature validation.  A malformed JSON line, a wrong nonce, or a
tampered closure therefore reaches the client but is discarded when the method
raises.

The worker does persist its own *attempted*, *eligible*, or *rejected*
finalization state (`scorer_process.py:611-627`), and the eligible state stores
the worker's verified closure.  That is not an independent preservation of the
bytes the client actually received: a wire-tampered response can differ from
the worker record, and an invalid response has no client raw-byte receipt.
This is a concrete failure-output retention gap; it must not be described as a
failure of preserving already verified closure records.

The current focused C5 stdio test verifies a valid closure and mutates the
already-returned consumer gate (`tests/test_headless_c5_evaluator_stdio.py:83-100`);
the controller test tampers a per-score evaluator response after scoring
(`tests/test_headless_evaluator_controller.py:74-118`).  Neither injects a
malformed or signature-tampered *finalize wire response* and asserts an
immutable client-side raw receipt.  Thus no existing test closes this gap.

**Reproduction:** make the worker/helper emit one syntactically malformed or
MAC-modified finalization response after it has read the request.  The client
raises from :882-895; its score journal remains unchanged and no separate file
contains the exact received line.

## Practical boundary

No documentation rollback is warranted: the coverage document already gives
the calibrated statement.  The two gaps mean future consumers should report
`has_direct_catalogue_reference` unless they verify a module-specific typed
payload/reader (as M2 does), should report failed/withdrawn impact as unknown
when no typed semantic edge exists, and should not claim that every rejected
finalize response is retained.  This audit does not claim that a particular
historical C5 node lacks a producer-specific path; it identifies the generic
boundary that prevents inferring one from automatic trace parents.
