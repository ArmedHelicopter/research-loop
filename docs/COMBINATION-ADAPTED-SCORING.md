# M4+M5 combination adapted scoring boundary

`evaluation.modular.combination_scoring` accepts only an actual
`CombinationBenchmarkCellResult` from the registered `pair:M4+M5` executor.
Before it derives a candidate, it replays the shared RunSession trace, the M4
prediction registry, the M5 review log, the joint-mechanism artifact, and the
solver program/artifact/answer binding. Failed cells and post-module solver
failures cannot produce a score input.

The execution authority signs `combination-benchmark-score-input-v1`, which
binds the frozen panel and design, exact cell, runtime and solver traces, joint
artifact digest, executed program digest, task/scenario/package/arm bindings,
and the anonymous candidate. `CombinationAdaptedScoringService` verifies that
input, sends only the bounded candidate plus service-owned task handle through
the existing frozen rubric transport, then emits a separately signed
`combination-adapted-scored-cell-v1` receipt. Execution and scorer authority
identifiers and key material must be distinct.

The common combination verifier accepts this signed receipt only after its
caller supplies `verify_combination_adapted_receipt`; the contrast estimator
then consumes its standard finite numeric metric. Every successful cell needs
one verified receipt. Any missing, failed, blocked, duplicate, foreign, or
drifted cell rejects the whole frozen four-arm contrast under the existing
`incomplete_reject` policy.

This is train-only engineering provenance and a descriptive adapted-score
estimate. It does not establish scientific validity, calibration, independent
deployment isolation, validation acceptance, or an effect of M4, M5, or their
combination.
