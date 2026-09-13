# Q5.1 / Q5.2 bounded feasibility drivers v2

This train-only API tests engineering and causal wiring on caller-frozen public
material. It does not promote scientific evidence, open validation, establish
source truth, or establish scientific independence. The prior v1 document is
preserved in `FEASIBILITY-PANEL-DRIVERS-V1-ARCHIVE.md`; its claims and original
36-cell passing test do not verify these repaired contracts.

## Integration API

`freeze_feasibility_panel_bundle(task, q51=..., q52=...)` returns
`feasibility-panel-bundle-v2`. Use `feasibility_panel_injection` to obtain the
`feasibility-panel-controller-v2` injection. `install_drivers` requires a caller
restricted `DockerExecutionBroker`, a public input resolver, and a trusted
`FeasibilityAuthorityPort` with **both** `verify_stage(subject)` and
`verify_prediction_outcome(subject)` for Q5.2. Install both drivers in the target
registry; the common production registry and train controller are unchanged.

Every arm has the exact same three model slots: `subjective`, `diagnostic`,
`final`, and one Docker allocation. Subjective returns `{feasibility,rationale}`
with feasibility feasible/infeasible/unknown. Diagnostic returns
`{decision,rationale}` with decision continue/stop/defer. Final returns the
unchanged standard candidate: objective_digest, outcome, evidence_ids,
conclusion, programme_complete. It is the last complete model response and is
returned verbatim, so existing replay/candidate response binding is retained.
Final outcome is invalid on diagnostic stop, otherwise unknown; evidence_ids is
empty and programme_complete is false. No feasibility result is scientific
positive/negative support.

## Frozen caller material

Each registered variant has a literal LF program and SHA-256 of its actual host
execution bytes (Windows translates LF to CRLF), pinned image, exact CSV named
hash/length declarations, closure, stage contracts, measurement contract and
verification budget. Closure execution_units is exactly one, token_units a
strict nonnegative integer, minimum_artifact_digest equals the program hash,
and negative_control_id matches the measurement contract. Token units describe
caller material; actual model token allocation/accounting belongs to the
production CodexModelPort, not this diagnostic driver.

The four stage contracts have exact fields source_id, contract_id, authorities.
Each authorities list contains exactly two `{authority_id,source_group}` rows.
The IDs differ; for independent_result the two sources also differ from one
another and the task group. These are necessary metadata constraints, not a
proof of scientific independence. Source-lineage qualification remains the
trusted verifier's responsibility. The driver does not enforce OS/process
separation of authorities.

Measurement contract fields are source_id, contract_id, discriminator_id,
observable, negative_control_id. Q5.2 includes two to eight fully typed branches
with unique hypothesis IDs, one shared intervention and one prediction per
branch bound to that discriminator/observable. Identical declared predictions
are a legitimate unidentifiable experiment, not malformed configuration. M4-on
actually invokes PredictionRegistry and retains its rejection; M4-off creates
no runtime substitute plan. Both execute their matched program once. Other
malformed branch structures are rejected during reconstruction before I/O.

Verification budget is exact: `{stage_calls:4,prediction_calls:0 or 1,
cost_accounting:"authority_reported_or_unknown"}`. Every Q5.1 arm performs four
stage verifications; every Q5.2 arm performs these plus one prediction outcome
verification. Off arms retain these as shadow observations in controller logs,
with null slots in the public observation. M4-off + M7-on is legal and uses the
caller measurement contract and caller prediction specification.

## Verifier subjects and responses

Stage subjects bind full task identity, prepared task digest, objective, bundle,
source, stage, authority contract, measurement contract, literal program hash,
actual execution input artifacts, execution digest/status and public execution
observation. Q5.2 stage subjects also include the caller prediction specification.
Prediction subjects additionally bind the full frozen caller prediction plan,
its digest, discriminator, measurement receipt digest/status and the same actual
execution. Runtime M4 plans and prediction updates are separately bound in the
controller trace to the caller plan and verified prediction subject.

`verify_stage` returns exact `verified-feasibility-stage-v2` fields schema,
subject_digest, status, observations, cost. `verify_prediction_outcome` returns
`verified-prediction-outcome-v2` with the same fields plus classifications.
Each of the two observations contains authority_id, source_group,
observation_digest, contract_id, subject_digest, status and literal boolean
signature_verified. Every field binds the frozen authority contract and exact
request; observation digests differ. The trusted port verifies real signatures
and source/measurement qualifications before returning this typed attestation.
The driver cannot make an untrusted callable trustworthy by checking a boolean.

Aggregate status is failed if either observation failed, otherwise unknown if
either is unknown, otherwise passed. Success of the actual execution is a
necessary condition for minimal_run and later passing gates, never sufficient
for measurement or independent_result. Equal declared predictions cannot pass
discriminating_measurement. Failed/unknown measurement, failed/unknown outcome,
or equal predictions require all prediction classifications unknown; none can
create a definite consistent/failed hypothesis update.

Each verifier call is journaled before I/O with limits, used calls, full subject
and unknown cost. Returned original receipts are journaled before validation.
Result or failure records retain cost `{unit:"verifier_units",units:int|null}`;
contract failure preserves any reported cost as untrusted and verified cost as
unknown. All remaining frozen verifier opportunities are attempted after a
verifier failure, without retry; the cell then fails before the diagnostic/final
model calls. Execution or model failure may prevent verification from starting;
the existing allocation and actual attempt records distinguish this from zero
cost or completion. Unknown cost is never represented as zero. These call limits
are enforceable; a numeric monetary ceiling is not claimed when cost is unknown.

## Decisions and public context

All arms expose the same public observation schema with execution result,
subjective assessment, four nullable stage slots and a nullable prediction slot.
M7-on exposes its sequential stage report; M4-on exposes actual identifiability
and independently verified classifications. Off slots are null. There are no
engine, module, arm, variant, package/controller labels or full execution
receipts in these slots. Execution projection excludes host paths, argv, image
and container IDs. It retains the actual public stdout, status/exit code,
artifact hashes and opaque execution binding. Caller-provided task text and
program output must themselves be public; projection cannot sanitize arbitrary
caller content into independent scientific evidence.

Diagnostic decision is stop for execution failure, explicit unidentifiability
or failed visible gates; defer for unknown/blocked visible gates; continue for
passed visible observations. With no visible observations it uses the same
subjective feasible/infeasible/unknown baseline. The controller checks the real
model diagnostic response against that frozen rule and records a module
decision. A model override fails closed. The final receives the same public
observation and accepted diagnostic, and must retain its prescribed bounded
outcome. Thus on/off differences can affect the actual final runtime outcome,
without exposing the experimental arm or claiming scientific support.

## Verification scope

The test suite covers all 36 cells (two benchmark adapters, five Q5.1 variants
and two Q5.2 variants, their legal module arms), actual public CSV computation
and negative control in pinned Docker, signed synthetic observation documents,
matched verifier calls, stage progression, real M4 same-prediction rejection,
classified updates, diagnostic changes and full receipt replay. Counterexamples
cover execution failure, CSV mutation between preflight/execution, bad subject,
nonboolean/unverified signatures, duplicate observation/foreign source,
unknown/failed measurements, malformed deep contracts, model decision override
and prediction-subject replay. The model transport is a deterministic fixture;
production CodexModelPort/custody/scoring seams remain the integrating
controller's separate obligation. Passing this suite is synthetic engineering
evidence, not a benchmark scientific effect or authority deployment validation.
