# Headless Grok private evaluator

`GrokHeadlessEvaluatorModelPort` accepts only the frozen private rubric request
`frozen-independent-evaluator-call-v1`. It checks evaluator identity/version,
rubric and output schema, canonical TASK/REFERENCE/ANONYMOUS_CANDIDATE material,
and the exact prompt template. Primary and lineage modes bind different rubric
and schema versions. The public TRAIN solver request is not used for reference
material.

The private ledger pins the executable, source, rubric, configuration, budgets
and context roots. Constructor and dispatch share an exclusive allocation lock.
Each call reserves an opportunity before native execution; the headless transport
uses a fresh copied login context, low effort, 60 seconds, no MAIN retry and no
paid fallback. Only the two-attempt account-read recovery policy is accepted.

The port retains the complete request, actual private prompt/schema, native
reservation, observer receipt, raw stream and response. Every successful return,
subsequent dispatch and ledger reopen independently reads the originals again.
Even a whitespace-only change to the typed response file is rejected. A MAIN
that completes before postflight rejection retains its known usage and private
raw response, without delivering a successful evaluator result. A prelaunch
refusal retains its receipt and explicitly unknown MAIN usage. Unknown title
usage and all-call settlement are not zero-cost claims.

The production primary scorer factory selects this port only through the exact
`provider_kind: grok-headless-frozen-evaluator-v1` descriptor. The descriptor
requires absolute context paths, source pins, the concrete model `grok-4.6`,
low effort, budgets and account-read policy. Existing Codex declarations retain
their schema. The protected TRAIN reference store is checked before creating
the evaluator, and both benchmark score returns keep only rubric evidence
digests rather than copying references to the solver.

This implementation establishes the private port and primary factory seam.
The lineage scorer production factory and a controller-wide final evaluator
ledger closure are not yet wired. Per-call replay is not a check after the last
score has already been delivered. An actual scored experiment must separately
bind its complete scorer lifecycle; this port alone does not complete that work.
Synthetic OS/HTTP checks do not establish real benchmark effects, calibration,
independent operating-system principals, or VAL acceptance.
