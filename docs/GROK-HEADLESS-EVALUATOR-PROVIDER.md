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

The M4/M5 v6 controller explicitly binds the evaluator configuration digest at
worker startup. After the last score, its finalization RPC replays every native
original and matches the ordered calls to the signed scorer receipts. The
closure binds source pins, ledger bytes, per-call evidence, known MAIN tokens
and the exact scored versus unscored panel membership. Title usage and total
settlement remain unknown. A partial scored prefix is never full panel coverage.

A durable finalization attempt closes subsequent scoring even when replay
fails. A repeated closure request checks the finalization history and replays
the originals again, including after a worker restart; a cached receipt alone
cannot pass. The controller retains historical scores and their denominator
when final replay fails, but marks the contrast ineligible. This RPC makes no
model or account calls. Earlier controller schemas retain their declared
provider contracts and do not silently admit this lifecycle.

The lineage factory separately binds its full declared evaluator configuration,
immutable private descriptor, distinct rubric and per-panel allocation. Its
versioned closure replays the outer lineage receipt, nested primary receipt,
raw native response and derived dimensions. The lineage reference must match
the frozen reference pin for the scored subject, even when a changed pointer
has been re-signed. Shared references and each worker's private declarations
are checked separately in the pool. Failed MAIN observations retain their
known usage under the headless accounting contract.

The outer lineage TRAIN controller must still pass each worker's descriptor,
retain ordered per-panel receipts and consume that panel's final closure.
Individual worker checks do not establish the complete four-panel stdio
lifecycle. Frozen engineering coverage is recorded by source version in the
implementation status; this contract alone is not a test result.
Synthetic OS/HTTP checks do not establish real benchmark effects, calibration,
independent operating-system principals, or VAL acceptance.
