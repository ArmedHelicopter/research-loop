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
