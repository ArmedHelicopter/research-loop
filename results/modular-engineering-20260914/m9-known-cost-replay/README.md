# M9 known source cost replay

The original frozen source reproduced nine failures: seven target score inputs
were accepted and two canonical builds replayed successfully after their source
cost became unknown. Original generic replay still passed. The separate repair
checkpoint passed all 22 selected tests without source drift.

Each checkpoint's normal state and mechanism fixtures used 17 canonical builds,
133 scripted model calls, 142 source qualifications, 24 retrieval operations,
46 target Docker executions and 46 independent process scores. Two prior-history
fixtures each add two model calls and one Docker execution; GREEN also retains
the selected original stop-case fixtures separately in denominators.json.
The nine replay cases themselves issued no new model, source or Docker calls.

Original and modified source/trace/build receipts, exact JUnit failures,
source manifests and separate GREEN closure are preserved. Unknown source cost
is rejected by the canonical builder and the state/mechanism family verifiers,
including M6 corpus qualification. The generic provenance contract is unchanged.

These are synthetic engineering checks, not demonstrated benchmark gains,
known real API settlement, scientific effectiveness or validation acceptance.
