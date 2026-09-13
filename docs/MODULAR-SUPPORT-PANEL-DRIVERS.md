# Q1.3 and Q1.4 support panel drivers

`freeze_support_bundle()` freezes caller-supplied public source records, claim
statements, representation records, and source-bound withdrawal actions for one
task. Its digest is checked against scenario evidence before a model request.

Q1.3 starts both arms with the same caller raw observation.  Only after the
initial call does each arm receive the caller-selected representation alongside
that raw observation. M2 admits those records through a caller receipt port and
rebuilds a root-deduplicated ledger view; M2-off receives the same two public
records as a frozen external control. The model is asked to assess supplied
material, without a prompt that asserts how repeated representations should be
treated.

Q1.4 records caller-defined sources and applies caller-defined withdrawals only
after its initial model call. The initial payload contains no future withdrawal
actions. Bundle validation requires one-withdrawn to preserve a distinct caller
root, all-withdrawn to cover every caller root, and copies to contain multiple
records of one root. M2 rechecks claims after withdrawal; M2-off retains its
frozen context while receiving the same post-action external source projection.
Different caller root material is an engineering input constraint; scientific
independence of support still requires separate review. These are engineering
traces, not benchmark measurements or evidence of an effect.
