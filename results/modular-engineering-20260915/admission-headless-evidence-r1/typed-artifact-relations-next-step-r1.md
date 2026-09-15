# Typed artifact relations: minimal compatible next step

## Decision

Keep `artifact-descriptor-v2` and every existing `artifacts.jsonl`/seal byte
unchanged.  Do **not** add a `relation` field to descriptor parents or rewrite
old catalogues: that would invalidate the exact-field validator in
`artifact_catalogue.py:57-77` and historical seals.  The compatible addition is
an optional, append-only companion receipt for newly produced operations.
Absence of that receipt means `unknown`, never `consumes`.

The first real writer should be **M2 `EvidenceArtifactBridge.ledger` only**.
It already derives relations from the concrete EvidenceLedger/ClaimLedger
operation at `evidence_artifacts.py:63-101`, writes the module output at
:115-123, and independently reconstructs those relations during replay at
:244-260.  It is the smallest actual consumption/withdrawal seam; no general
runtime hook may infer relations from the latest trace.

## New sidecar, not a descriptor migration

For a newly created M2 sidecar, write
`typed-relations.jsonl` beside `artifacts.jsonl`, with a new self-contained
`typed-artifact-relation-entry-v1` hash chain.  Each entry is a canonical
record containing:

```text
sequence, previous, relation_id,
source = {catalogue_path, catalogue_seal_digest-or-null, descriptor_digest},
target = {catalogue_path, catalogue_seal_digest-or-null, descriptor_digest},
kind = withdraws | supports | refutes | depends_on | supersedes |
       checked_by | withdrawal_observed,
producer_source snapshot, operation_digest, identity, status=produced
```

The source/target ordering is explicit: `source --kind--> target`.  A
withdrawal event therefore writes `withdrawal_descriptor --withdraws--> root`;
a claim refresh writes `claim_descriptor --withdrawal_observed--> withdrawal`.
The M2 bridge may emit only the relations it already builds from ledger state.
It must neither convert the automatically appended trace parent into a sidecar
edge nor add a relation for an adjacent event.

Write the relation entry immediately after the descriptor exists and before
returning the operation.  If the relation-sidecar write fails, the M2 operation
must be reported as failed/incomplete and must not be advertised as typed-edge
covered.  It does not retroactively delete the immutable descriptor or journal
event.  The M2 replay verifier must rebuild exactly the sidecar rows from the
same original journals, descriptor digests, and bridge source snapshot; an
extra, missing, reordered, or altered row rejects replay.

No existing historical sidecar is synthesized.  Existing C5 registration
already has a separate typed `derived_from` projection
(`c5_selected_artifact_registration.py:50-68`), but it remains its own
canonical record and is not relabelled as an M2 or catalogue relation.

## Bounded cross-directory impact query

Add one read-only function next to the M2 relation verifier, not a registry or
background index:

```text
query_withdrawal_impact(withdrawal_source, relation_paths: tuple[Path, ...])
    -> {affected: [...], unresolved: [...], complete: bool}
```

Inputs are explicit, caller-provided sealed sidecar paths.  The reader first
checks every sidecar chain and source/target identity, then starts only from
the supplied M2 withdrawal descriptor and traverses only typed `withdraws`,
`withdrawal_observed`, `supports`, `refutes`, `depends_on`, or declared future
`consumes`/`derived_from` entries.  A result may say:

* `affected`: a descriptor reached through explicit typed edges;
* `unresolved`: an edge points to an unavailable/unsealed supplied sidecar, or
  an external consumer was not supplied; and
* `complete=false` unless the caller supplies an authenticated, closed scope
  manifest enumerating all relation sidecars expected for that subject.

It writes no status back to either directory.  It cannot label all
chronologically later artifacts as affected, and it cannot turn a historical
missing edge into a negative result.  The query is an audit result, not a
scientific refutation, selection decision, or deployment gate.

## One integration check

Extend the existing actual M2 withdrawal/replay path used by
`tests/test_admission_combination.py` (the real withdrawal is emitted at
`admission_combination.py:143-147`).  Use its existing public synthetic
materials and two deliberately disjoint sidecar directories; no benchmark or
VAL material is needed.  Assert all of the following in one focused check:

1. the M2 writer produces `withdraws` and `withdrawal_observed` entries whose
   descriptor digests exactly match the module payload relations;
2. the normal M2 replay rejects a sidecar deletion, reordering, altered kind,
   or a fabricated trace-anchor `consumes` entry before any model/scorer call;
3. the explicit-path query returns the known affected M2 descriptors, retains
   an absent second path as `unresolved`, and reports `complete=false`;
4. original `artifacts.jsonl`, its seal, failure prefix, and legacy run without
   the new sidecar remain byte-identical and still verify under v2.

This adds one real writer, one real verifier extension, and one reader.  It
does not create a universal graph service, alter current C5 artifacts, change
old seals, or claim total cross-directory impact coverage.
