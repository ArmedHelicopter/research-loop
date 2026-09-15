# M2 typed-relation projection

`research_loop.modular.evidence_relation_projection` provides a read-only view
of typed relations already recorded in M2 ledger payloads.  It does not add a
relation registry or infer relations from the catalogue's chronological parent
links.

## Reader contract

`project_m2_typed_edges(catalogue, sidecar, *, seal)` requires an exact
`FrozenRecord` catalogue seal.  It validates that seal, snapshots the raw
catalogue bytes and descriptors, runs `verify_evidence_artifacts` against the
sidecar journals, then rechecks both the byte snapshot and the same seal before
returning any projection.  A changed or resealed catalogue is rejected rather
than retried.

The projection includes M2 descriptor status and `module_enabled`, along with
the canonical `relations` payload.  This preserves a `not_applied` control
record as such; a relation in its retained ledger payload does not prove M2 was
enabled.

The existing `evidence_artifacts.py` bridge is intentionally unchanged.  Each
M2 payload binds that bridge's source snapshot, and its existing semantic replay
requires the installed bridge source to match the recorded one.  The projection
also reports that semantic-replay snapshot and its own reader snapshot.  It
does not execute or migrate a different worktree's archived source.

```python
from research_loop.modular.evidence_relation_projection import (
    project_m2_typed_edges,
    query_m2_withdrawal_observations,
)

projection = project_m2_typed_edges(session.artifacts, session.sidecar,
                                    seal=sealed_catalogue).data()
withdrawal = next(node['descriptor_digest'] for node in projection['nodes']
                  if node['event'] == 'withdraw')
observations = query_m2_withdrawal_observations(
    withdrawal, ((session.artifacts, session.sidecar, sealed_catalogue),)
).data()
assert observations['complete'] is False
```

`query_m2_withdrawal_observations(withdrawal_descriptor_digest, sources)`
accepts explicit `(catalogue, sidecar, seal)` inputs only and requires all
sources to replay under the same installed M2 bridge source.  It returns two
separate lists: `withdrawn_roots` from direct `withdraws` relations, and
`observed` from `withdrawal_observed` relations.  The latter records that a
refresh observed a withdrawal; it is not a causal affected-artifact claim.
The query never traverses `supports`, `refutes`, `depends_on`, `supersedes`, or
generic/latest-trace parents.  Its `complete` remains `false` and
`unknown_scope` remains `true`, so it provides no inferred global or causal
closure.

## Verification boundary

At frozen commit `fff899`, 15 synthetic tests passed.  At ROOT commit
`a0ec428d`, the 23-test root receipt passed: 10 label-isolation tests, 3 M2
projection tests, and 10 gate tests.  Source bytes were unchanged during those
receipts.  These checks use synthetic fixtures; they do not establish a real
API invocation, a VAL result, or scientific validity.

The related admission/headless evidence package is documented in
[the archived receipt](../results/modular-engineering-20260915/admission-headless-evidence-r1/README.md).
