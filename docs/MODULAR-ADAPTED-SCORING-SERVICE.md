# Independent adapted scoring service

`evaluation.modular.scoring_service` is an authenticated aggregation boundary
for the required DiscoveryBench and BLADE adapted metrics.  It extracts the final
immutable candidate from the hash-chained runtime trace and sends it to an
independently owned `FrozenRubricTransport`; callers cannot submit arbitrary
candidate material or dimensions.  The evaluator is selected through a
controller-owned opaque task-handle map.  A solver request, panel receipt and
score receipt contain digests and handles only; they never contain a reference
payload or expected dimensions.  A mismatched runtime cell, trace digest,
output digest, final-candidate digest, or supplied trace candidate is rejected.

`ScorerConfig.digest` is frozen into every `PanelCell.scorer_digest`.  A
`core_pair` config serves both required benchmarks while preserving their
benchmark-specific dimensions and aggregate. The
service signs a v2 receipt that binds the panel digest, exact cell key, runtime
trace and output digest, scorer config, task-handle digest, submission digest,
dimension results and recomputed adapted metric.  `AdaptedMetricReceiptVerifier`
checks the authority MAC, every binding, exact metric contract and aggregate.
It can be supplied as `PanelReceiptVerifier(scorer_verifier=...)`.

The package now includes `FrozenBenchmarkRubricEndpoint`. Its service-owned
resolver binds nonempty train references to the task handle, identity and
benchmark. Its independent model port receives the actual frozen Discovery
dimensions or full BLADE criterion text, anonymous candidate and protected
references. The rubric digest covers the rules, schemas and executable prompt
templates; implementation drift is rejected before resolving a reference or
calling the evaluator. Values must follow each benchmark's discrete/range
contract; aggregation is deterministic.

This endpoint evaluates one candidate at a time, unlike the historical paired
judge. It does not claim numerical equivalence to that judge or official scorer
calibration. The references and evaluator transport have not been deployed in
an independently operated service. Tests use synthetic references and explicit
model responses to exercise the real endpoint contract:

`actual journal candidate -> frozen rubric endpoint -> service calculation -> signed receipt -> receipt verifier`.

It does not access a benchmark reference, calibrate either benchmark scorer,
measure a module effect, or demonstrate scientific validity.  `PanelVerdict`
therefore reports `adapted_score_verified` separately and leaves
`scientific_verified` false for v2 receipts; they cannot enter scientific or
validation acceptance. A production
deployment must run the evaluator and signing key outside the solver process,
bind its task-handle map to custody, and separately satisfy the existing
validation calibration and acceptance gates.  Failed or unavailable runtime
cells remain `RuntimeReceipt` failures/unscored observations; they are not
converted to zero adapted scores.
