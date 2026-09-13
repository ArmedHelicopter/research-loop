# Q1.3 and Q1.4 support panel drivers

`freeze_support_bundle()` freezes caller-supplied public source records, claim
statements, representation records, and source-bound withdrawal actions for one
task. Its digest is checked against scenario evidence before a model request.

Q1.3 writes the raw record and the selected representation through the caller
admission port only when M2 is enabled. Both writes share the caller root
material, so the ledger records one root. The M2-off arm receives the same
public representation as a frozen external control without ledger promotion.

Q1.4 records caller-defined sources and applies caller-defined withdrawals only
after its initial model call. The initial payload contains no future withdrawal
actions. M2 rechecks claims after withdrawal; M2-off retains its frozen context
while receiving the same post-action external source projection. These are
engineering traces, not benchmark measurements or evidence of an effect.
