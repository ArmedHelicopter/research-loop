# V3 admission qualification parity

The v3 useful-review recipe leaves the legacy v1/v2 lineage and admission
estimands unchanged. It adds a fail-closed comparability check only to the
v3 admission controller, where M1 consumes admission qualifications.

Each arm still obtains its registered two independent qualification calls.
The controller does not compare complete signed receipts because the exact
cell binding, signature, and call bookkeeping properly differ between arms.
Instead, before estimating a panel contrast, it compares every arm for the
same task and replicate using a digest of the exact transition inputs:

- task and frozen material digests;
- the configured source-authority policy binding; and
- each original's separate `before` and `after` assessment fields consumed by
  admission: subject digest, scientific state, outcome, execution result, and
  required audit items.

When a group differs, all rows, source calls, model calls, Docker attempts,
and scores remain in the TRAIN receipt. Its panel contrast is
`inconclusive` with compact arm-to-semantic-digest drift evidence. No cell is
pruned and validation remains closed. A missing or unknown source result
continues through the existing failed/incomplete-cell policy.

This is an engineering comparability guard, not an effectiveness or
calibration result. Non-admission lineage material provenance only accepts or
rejects the exact frozen material and is not consumed by its transition, so it
does not use this variable-assessment parity gate.

## Integrated verification

Source `33296e42c875d6c407e9de5f59e71418989d411c` passed 25 checks with 490
unchanged frozen files. The normal v3 admission run scored all 24 cells; its
six matched task/pair groups each had one consumed-semantics digest and its
three contrasts were estimated. The adversarial source run also scored every
cell, but each group had two semantic digests and all three contrasts were
inconclusive. Legacy admission and both lineage dependency restrictions kept
their original contrast behavior.

Original JUnit, before/after hashes, controller and process journals, replay
forgeries, exclusions and derived denominator checks are archived in
`results/modular-engineering-20260913/lineage-parity-root/`. The archive contains
12 files and 3,615 independently rehashed ZIP members, all synthetic. Earlier
isolated parity-test reports were not located and are not used as evidence.
