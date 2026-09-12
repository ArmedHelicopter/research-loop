# Independent adapted scoring service

`evaluation.modular.scoring_service` is the controller/service boundary for
the required DiscoveryBench and BLADE adapted metrics.  It extracts the final
immutable candidate from the hash-chained runtime trace and sends it to an
independently owned `ReferenceEvaluator`; callers cannot submit arbitrary
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

The provided test uses a synthetic protected evaluator to exercise:

`immutable submission -> service calculation -> signed receipt -> receipt verifier`.

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
