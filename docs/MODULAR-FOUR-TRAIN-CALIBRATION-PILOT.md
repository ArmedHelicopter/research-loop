# Four-TRAIN diagnostic calibration contract

This pilot freezes four caller-authorized TRAIN identities, two per primary
benchmark, and all nine material categories for each identity. Its 36 slots
remain four source tasks; group denominators are reported separately. Every
slot has two evaluator opportunities, including unavailable, failed and unknown
slots. No RuntimeReceipt is synthesized, no validation lease is accepted and no
formal CalibrationReceipt is issued.

Private material receipts bind the candidate, original expected dimensions or
unknown, source identity and support digest. Two distinct reviewer authorities
receive blinded requests without expected dimensions, the other review, arm or
judge output. A single distinct arbitrator is called only on disagreement.
Decisions for every slot are frozen before the first evaluator request. Signatures
authenticate a delegated authority; they do not prove human independence or truth.

All billable ports require explicit caller-frozen model/parameters/context,
tokenizer, pricing and capacity authority contracts. Signed reliable capacity and
cost upper bounds must match the exact request before durable reservation and
I/O. Reviewer calls (at most 72), arbitration (at most 36), and evaluator calls
(at most 72) have separate counters and share the global budget. Unknown or
untrusted cost consumes its reservation and blocks further I/O. No production
price, accuracy or dollar limit is supplied by this module.

The worker owns the standard FrozenTrainReferenceResolver and reuses
FrozenBenchmarkRubricEndpoint. Private journals retain raw responses and partial
failures before validation. Public results contain counts, hashes, normalized
dimensions, confusion matrices, continuous errors and paired repeat differences;
they contain no candidate, expected rationale, reference text or dynamic error.

Acceptance for this implementation requires real subprocess synthetic coverage
of all 36 slots / 72 opportunities, both benchmarks, isolated review requests,
fixed arbitration, unknown / unavailable cases, capacity and budget refusal,
raw partial failure preservation, source drift, and explicit rejection by the
formal calibration verifier. Scientific calibration remains not established.

## Deployment seam and evidence limits

`calibration_pilot_process.run_config(config, reviewer1=..., reviewer2=...,
arbitrator=..., evaluator=..., capacity_port=...)` is the worker-owned entry.
`serve_once` exposes its one-shot file protocol and `launch_once` pins the Python
executable, worker file, exact config/output arguments and verifies the signed
diagnostic result. A deployment entry script supplies reviewed ports; the test
helper is deliberately not a production evaluator. There is no automatic CLI
model, tokenizer, price or reviewer implementation hidden behind a default.

The frozen manifest includes the actual pilot, process, rubric and resolver code
hashes, caller source/eligibility pins, the four exact store-backed task/public
and reference digests, and the 36 signed material commitments. The worker checks
caller inputs before and after every capacity measurement and after the run.
The standard resolver rechecks its frozen reference bytes. These checks are
application boundaries, not OS isolation or evidence of unlogged access absence.

The nonbillable capacity port receives the exact private request plus the frozen
port model/parameters/context/tokenizer/pricing contract. Its separately signed
receipt must certify complete request capacity and a reliable monetary upper
bound. This delegation must be backed by a reviewed tokenizer/context and pricing
implementation before any actual pilot. A synthetic or assertion-only measurement
port cannot establish that qualification. Each billable port returns an immutable
output and request/config-bound usage evidence; partial transport failures retain
both raw partial output and raw reported cost in the private journal. Confirmed
reservation breaches retain reported usage and close further I/O.

Reviewer receipts target normalized rubric dimensions or explicit unknown / not
applicable. Material expectations do not enter either blind review request or
the judge prompt; disagreements with the frozen material expectations are counted
separately. Reviewer consensus or one fixed arbitration produces the prospectively
frozen diagnostic target. These are authenticated judgements, not proof of expert
correctness. There is no binary calibration eligibility threshold or confidence
interval inferred from these four tasks.

Reviewer deployments must resolve the blinded task handle with the standard
FrozenTrainReferenceResolver and verify the exact reference digest. Supplying a
callback does not mean an independent reviewer model or expert has been deployed.
The request intentionally omits expected targets and other reviews.

Any detected source guard failure permanently closes further I/O in that pilot,
even if original bytes reappear. Usage evidence must identify an independently
recorded actual call (for example a provider ledger reservation/usage receipt),
not merely hash identical response content. Reusing one usage evidence digest
retains the new reservation as unknown and blocks further I/O. Transport failures
and invalid received responses have separate counters. Parent timeouts preserve
captured partial stdout/stderr privately, mark the child call/token/money totals
unknown pending private-ledger reconciliation, and never retry automatically.

## Frozen synthetic verification

Source `c160b8341b12a827825d223822cdf5f5d4a72870` passed 115 related checks in
459.575 seconds, with zero failures/errors/skips and all 459 tracked Python file
hashes unchanged. The suite includes a real one-shot worker, standard resolver,
36 distinct synthetic material slots, both primary benchmarks and 72 evaluator
opportunities. Its ordinary full grid dispatched 36 + 36 blinded reviewer calls,
zero arbitration calls and 72 canned evaluator calls. The disagreement grid
used all 36 arbitration opportunities. These are synthetic ports, not paid model
calls or scientific accuracy evidence.

Twenty final-run journals retain 182 reviewer1, 178 reviewer2, 36 arbitrator and
359 evaluator dispatch attempts across positive and adversarial tests. All raw
responses, invalid receipts, unknown costs and budget reservations stay in the
private synthetic journals. Their hash chains and metadata are indexed under
`work/cal-pilot-checks/synthetic-denominators-r2.json`.

The earlier 112-check run retains one fixture-shape failure (111 passed), with
unchanged source. Independent branch `codex/calibration-boundary-red` / `4187412`
retains three failing counterexamples on the old worker: nonpersistent source
halt, reused usage evidence, and discarded timeout partial streams. That RED
branch is evidence only and must not be integrated. The repaired boundary checks
and the complete final regression passed. No actual four-task reference, model,
Docker, validation lease, split or hold was used or changed by this work.

[Verification metadata](calibration-pilot-verification.json) identifies the exact
JUnit and source hashes. The actual pilot still requires independently reviewed
material/reviewer services and reliable model/context/pricing ports.

## Deployment budget constraint (2026-09-13)

The current run has no additional API-fee budget. Existing subscription or
local resources may be used; Grok CLI `grok 4.6` is an explicitly authorized
candidate. This does not assert that a CLI is free, capacity-qualified or
already integrated. A new subscription/quota deployment must bind its actual
authentication, model, request limits and usage receipts without fabricating
a zero-USD API tariff or silently changing this historical HTTP contract.
The four-task/nine-category diagnostic, frozen rubric and TRAIN-only boundary
remain unchanged. No direct DragonAPI generation is scheduled under this
constraint.
