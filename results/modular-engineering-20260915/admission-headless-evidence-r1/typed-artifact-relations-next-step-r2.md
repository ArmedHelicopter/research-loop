# Typed artifact relations r2: projection before a new sidecar

## Revision to r1

The r1 `typed-relations.jsonl` sidecar is **not required for the first step**.
For M2, the current immutable descriptor payload already contains the typed
relations needed for a read-only projection:

* `EvidenceArtifactBridge._relations` derives `withdraws`, `checked_by`,
  `supersedes`, `supports`, `refutes`, `depends_on`, and
  `withdrawal_observed` from actual ledger state, rather than trace order
  (`evidence_artifacts.py:63-91`);
* `ledger` uses those relation artefact digests as its supplied parents before
  `RunSession.record_artifact` appends the separate trace anchor
  (`evidence_artifacts.py:115-123`; `runtime.py:332-341`); and
* the M2 verifier replays the original journals, reconstructs `relations`, and
  requires the descriptor payload and `semantic parents + latest_trace` to
  match (`evidence_artifacts.py:244-260`).

Thus a pure reader can enumerate the M2 descriptor payload's `relations` and
classify only those as typed semantic edges.  The remaining descriptor parent
is merely `has_direct_catalogue_reference` unless the module payload identifies
it.  This avoids a duplicate write, a new partial-write point, and any change
to descriptor v2 or old seals.

## Minimal read-only projection

Add one reader near `verify_evidence_artifacts`, for newly or historically
valid M2 catalogues alike:

```text
project_m2_typed_edges(catalogue, seal) -> FrozenRecord
```

It must first call `catalogue.verify(seal)`, select only descriptors whose
canonical payload schema is `m2-ledger-artifact-v1`, and return entries of:

```text
{from_descriptor_digest, relation, to_descriptor_digest,
 identity, catalogue_head, catalogue_seal_digest, payload_digest,
 bridge_source, ledger_source}
```

The reader rejects an edge unless the target digest appears in the same
verified catalogue and in the descriptor's payload `relations`; it must not
derive an edge from `parents`, `journal_index`, a trace predecessor, or a
filesystem name.  It also rejects a claimed M2 relation if a separate M2
replay does not reconstruct the same payload.  The result is an audit
projection with `scientific_validated=false`; it grants no selection,
deployment, or score authority.

## What existing data cannot authenticate

M2 is sufficient for all **local** relation derivation, but not for a complete
cross-directory impact claim:

1. The relation payload contains only descriptor digests, not an external
   catalogue identifier/path/seal.  This is correct for the local M2 writer:
   `ArtifactCatalogue` forbids foreign parents and cross-subject/domain parents
   (`artifact_catalogue.py:74-79`, :106-110).
2. A local catalogue seal authenticates that catalogue's own head and binding
   (`artifact_catalogue.py:125-145).  It does not enumerate every consumer
   catalogue in other directories.
3. Existing C5 selected registration has its own typed `derived_from` fields
   (`c5_selected_artifact_registration.py:50-68`), but it identifies component
   and bundle digests, not a sealed set of external ArtifactCatalogue locations
   or a withdrawal-impact scope.

Those are concrete scope/authentication gaps, not a reason to duplicate M2
relations.  A first cross-directory query may therefore accept explicit
`(catalogue_path, seal)` inputs, verify and project each independently, and
return reachable typed paths only.  It must always return `complete=false` and
list unsupplied consumer roots as `unknown` unless a later, separately
authenticated closed scope manifest supplies the complete directory set.  It
must never turn an absent path, a generic descriptor parent, or a historical
prefix without M2 payload into a negative impact result.

## One first integration check

Extend the existing actual M2 withdrawal route in
`admission_combination.py:143-147` and its existing replay-focused test
surface.  On public synthetic materials only, verify that a read-only
projection:

1. produces exactly the `withdraws` and `withdrawal_observed` payload edges;
2. rejects a payload/parent mismatch through the existing M2 replay before any
   model or scorer call;
3. with two explicit verified directories, returns known local reachability,
   `complete=false`, and an `unknown` unsupplied cross-directory consumer; and
4. makes no write: `artifacts.jsonl`, its seal, evidence/claim journals, and
   the retained failure prefix have identical bytes before and after.

Only if a future module has a typed relation that cannot be recovered from its
already verified payload should a companion sidecar be reconsidered.  It would
need explicit external catalogue/seal endpoint fields and a closed-scope
authority; r1's generic sidecar alone would not supply that authority.
