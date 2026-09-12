# Complete modular panel receipts

`research_loop.modular.panel_receipts` verifies a whole frozen panel.  It is a
new boundary beside the legacy per-experiment ledger; it does not change that
ledger or make its two-receipt check sufficient.

A `FrozenPanel` freezes every expected cell: all 48 Q1--Q8 coverage IDs, each
benchmark, task/source-group/replicate, variant, legal module arm, scenario,
package and scorer digest.  The verifier requires an exact set of receipts.
Duplicates, omissions, unexpected cells, a changed package/scorer/arm/task,
or a non-cartesian variant-by-arm task panel fail closed.  Source-group
distinctness is keyed by `(benchmark, group)`; the two benchmarks remain
separate.  Failures, blocked cells and unscored cells remain counted as their
own statuses and are never converted to a score of zero.

The frozen combination routing carries all 36 pairs, the five registered
triples, the full M1--M9 arm, and leave-one-out coverage. The verifier labels
that portion `routing_only`: it does not claim an interaction was measured
unless a separate panel supplies and verifies the exact contrast matrix.

For every runtime receipt, the verifier calls `verify_trace` on the actual
JSONL sidecar and then checks its hash-chained objective lock against the
expected `DataIdentity`, package and canonical legal arm.  A trace hash proves
only journal integrity and binding; it does not establish a valid measurement,
score, or scientific conclusion.

The verdict exposes three separate levels: `engineering_verified`,
`scientific_verified`, and `acceptance_verified`.  Independent scorer receipts
are trusted only through a configured independent verifier.  Validation can be
`accepted` only after that scorer path succeeds and independently signed
custody and acceptance receipts bind the exact frozen panel digest, candidate,
split, arm schedule, groups, and lease.  With no trusted scorer service, the
module stops honestly at engineering evidence and refuses acceptance.  Train
panels cannot consume acceptance at all. `SignedAuthority` is a test fixture
for a key held outside the candidate process; it is not wired to
`evaluation.modular.custody`. Production integration still needs a custody
service that issues this signed panel lease after enforcing its private split.
