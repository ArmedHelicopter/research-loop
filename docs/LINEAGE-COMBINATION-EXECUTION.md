# Shared lineage, context and review combination executor

This is the next implementation contract, not an executed experiment. It
covers `pair:M2+M3`, `pair:M2+M5`, `pair:M3+M5` and the required
`triple:M2+M3+M5`. The other pairs, triples, full/LOO and singleton obligations
remain in the existing catalogue. No outcome is used to choose this coverage.

Use the existing registered compatibility designs unchanged. M3 requires M2:
M2/M3 has three executable cells and no identifiable two-factor contrast;
M3/M5 fixes M2 as background; the triple has six executable cells. With one
task from each core benchmark the four panels contain 34 executable cells.
Structural exclusions remain in the design denominator and must not become
invented off cells or interaction estimates. They are independent of efficacy.

Every arm of a panel uses the same frozen task, actual input CSV bytes, caller
public history material, candidate package, budget, response schemas, module
order and scorer. A typed material manifest binds task identity, public input
hash/size, original observations, representations of the same roots, claim
relations, withdrawal actions and the ordinary historical summary. The panel
scenario commits that complete manifest before execution. Caller-owned dual
material verification checks its provenance once per cell with the same
opportunity in every arm. Signatures authenticate configured origin; scientific
validity, independence and scoring calibration remain external obligations.

The executor uses one RunSession and its actual ledgers throughout:

1. M2 on appends the original and derivative records to EvidenceLedger, creates
   the bound ClaimLedger relations, applies withdrawal to the actual roots and
   refreshes dependent claims. Its control preserves the caller's ordinary
   public representation and historical summary. Record the raw representation
   denominator, root denominator and before/after claims; root IDs alone are
   not evidence that these operations occurred.
2. M3 on reconstructs context from that current ledger and removes obsolete
   summary state. M3 off uses the frozen ordinary summary alongside the same
   available public observations. A public context projection omits treatment
   labels and host authority/path details. Preserve its exact byte budget and
   before/after hashes. The configured dependence on M2 is never bypassed.
3. Two matched review calls see that actual post-transition evidence/context.
   M5 on uses ReviewEngine open/submit/reveal and only reveals after both
   submissions. Its control keeps the same two independent calls but does not
   apply the reviewed state. No review or controller ID is visible only in an
   active arm. The consumed review responses must be the original provider
   outputs, not controller-generated summaries.
4. The shared benchmark solver consumes the resulting public memory/context/
   review object in both its analysis-program and final-answer requests. It
   uses the same session, one real Docker opportunity and exact mounted input
   bytes. Generated-program and rejected-answer failures remain failures.

Freeze four model opportunities (two review calls, analysis, answer), one
Docker opportunity, the public context byte cap and one independent scorer
opportunity per cell. Any failed or malformed call consumes its original
reservation; no retries, replacement output or discarded denominator.
M2/M3 operations themselves are deterministic and do not need additional model
calls. Cost equality means the same allocated limits, with actual usage and
unused opportunities reported separately.

Verification must replay the evidence/claim/review logs from their immutable
events, recompute the context from that state, and compare the actual model
request sequence and consumed review outputs. It must also verify actual input
and program files, the shared solver terminal state, rejected raw responses and
the full frozen cell binding. Reuse the shared solver verification and explicit
UTF-8 scorer boundary; do not copy the previous rejected-successor or failed-
execution bugs. An independent scorer evaluates primary benchmark outcomes and
the stated lineage/context/review endpoints under a separately frozen rubric.

First use synthetic public tasks through the real custody/export/compiler,
CodexModelPort with fixture transport, actual Docker and independent fixture
authority. The complete 34-cell grid, withdrawal propagation, same-root copies,
source-byte drift before any model/authority call, review isolation, partial
failures and forged receipt/context mutations need concrete checks. Then freeze
the real train panel and budget after label isolation passes. Validation remains
unopened until the entire candidate and acceptance contract are frozen.

The existing M4/M5 paid run is preserved independently. This implementation
must not retrofit its package, criteria, failed cells or scoring results.

## Implemented train API and verification boundary

`FrozenLineageTrainConfig` and `compile_lineage_train_panels` freeze exactly
these four registered designs. `run_lineage_train_panels` exports only the
allowlisted custody train tasks, checks every material/CSV before any source or
model call, then closes all 34 cells for one task per core benchmark. Each cell
uses `run_lineage_combination_cell` and one `RunSession`; no singleton result is
consulted to select or prune a combination. The M2/M3 pair and the triple retain
their registered structural exclusions and unidentifiable full interactions.
The other two pairs retain ordinary zero contrasts when outputs coincide.

`FrozenLineageMaterial` explicitly types original observations, derivative
representations, root-to-claim relations, an ordered claim dependency DAG,
withdrawals, the ordinary summary, complete public input records and a context
byte cap. No CSV is provided inline. The controller accepts exactly the exported
`public_csv` bytes. The standalone cell API also supports a complete named input
set with matching typed commitments. Material and scenario digests are bound
before execution, and the source authorities receive the exact material plus
opaque cell/scenario bindings, preventing cross-cell receipt reuse.

`DualMaterialVerifier` uses two configured `MaterialAuthority` callbacks, each
with its own signing identity, key and source-group name. Each call is persisted
as reserved with limits and unknown cost before the callback. Both opportunities
are attempted even when the first is rejected, unknown or raises; the failure
and raw returned response are retained. No model or Docker runs unless both
exact provenance subjects qualify. The source file is replayed read-only and its
literal SHA256 is bound in the session transition. Source-group names and MACs
are provenance conditions, not proof of independent scientific observations,
source lineage qualification, OS isolation or scientific validity.

The driver writes actual evidence/claim/review journals. Verification recomputes
the original, derivative, claim, dependency and withdrawal operations, compares
the entire event sequences, reconstructs both public and builtin request context,
checks the review barrier/order and original provider outputs, and checks the
shared solver files/inputs/final context and original failures. The on/off public
joint has the same fields, with actual observations, memory, review responses or
nulls. Actual source keys, authority identities, host paths and treatment labels
are excluded from it. The underlying ledger uses a fixed public provenance label,
which authenticates no scientific validator. Every final candidate remains the
shared train-only `unknown` protocol with no scientific evidence IDs.

The new `LineageCombinationScoringService` consumes a source-authorized primary
candidate and the exact public joint context in one `FrozenRubricTransport`
opportunity. The independent provider must return the existing adapted primary
dimensions, frozen rubric evidence, and four bounded endpoint estimates:
`root_attribution`, `withdrawal_awareness`, `context_currency` and
`review_responsiveness`. Its complete response, primary signature and endpoint
values are retained and checked together. Endpoint meanings and calibration must
be frozen by the caller's rubric; the fixture values demonstrate transport and
binding only. Source/execution/scoring trust is configured host trust, not a
scientific or process-isolation attestation.

The public M2 root selector now chooses admitted representatives deterministically
(raw preferred, then stable record ID), preserving admission priority and
withdrawal semantics. The M3 context builder retains `undetermined` when a
withdrawal leaves neither active support nor active refutation. It no longer
turns missing evidence into `refuted`. New-process and explicit withdrawal RED
reports preserve the previous behaviors. Old research journals and scores are
not rewritten or reclassified by this engineering change.

Reports distinguish allocated model/Docker/source/scorer opportunities, actual
calls and Docker attempts, unused opportunities and unknown accounting. Failure
at any stage leaves its planned row. Source/model/scorer exceptions are recorded
by type, without host exception text in public prompts. Timeouts retain the
existing solver contract; the narrow failed-final recognizer is only for a
strict integer nonzero exit. Replay assumes immutable original host artifacts;
it does not protect against a privileged concurrent writer replacing the whole
artifact tree and its trusted external pins.
