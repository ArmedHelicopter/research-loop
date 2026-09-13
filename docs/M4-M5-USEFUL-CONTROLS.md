# Prospective M4/M5 useful-output control recipe

This is a new TRAIN-only recipe, not a reinterpretation of the earlier frozen
M4/M5 runs. The historical driver retained matched off-arm calls in its trace
but omitted their proposals/reviews from downstream solver input. Equal call
counts alone therefore did not establish an equally capable reasoning baseline.

The new explicit v3 controller configuration uses the sealed primary TRAIN
exporter and freezes the recipe into every scenario and thus every panel and
signed score binding. Legacy v1/v2 configurations retain their original
behavior; adding a recipe flag to an old configuration is rejected.

All four cells retain five slots: proposal, mechanism review, measurement
review, analysis program, final answer; one bounded Docker attempt and one
independent adapted-score opportunity. Both proposal/review outputs reach the
solver in every arm. M4-off uses ordinary three-branch reasoning; M4-on asks for
discriminating predictions and records the actual PredictionRegistry plan.
M5-off uses sequential self-revision, allowing the second review to see the
first. M5-on uses separate sealed contexts and the actual ReviewEngine barrier.
Neither arm can see benchmark references, labels, design coefficients or arm
identifiers. Off outputs remain provisional reasoning, never admitted evidence.

The estimand is structured discriminating prediction plus registration versus
ordinary proposal, and sealed review versus sequential review, with useful
outputs in both arms. It is not an isolated effect of persistence, not a claim
of independent model errors, and not exact equality of realized token use.
Input length, realized calls/tokens, failures and missing scores remain visible.
The existing token threshold is not a provider-side per-request hard cap.

Verification must execute the two-benchmark eight-cell grid through primary
TRAIN export, actual Docker and independent scorer processes, with synthetic
model/reference fixtures. Replay must reject discarded or substituted off-arm
outputs, sealed-review cross-contamination, and post-freeze recipe changes,
even after a caller rehashes the trace. Failed cells retain the full denominator.
Actual TRAIN effectiveness, calibration, all other combination obligations and
validation acceptance remain separate unfinished work.
