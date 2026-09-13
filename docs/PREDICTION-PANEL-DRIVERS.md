# Prediction panel drivers

Q3.2 and Q5.3 require a closed caller bundle bound to the prepared public task,
public source and observation identifiers, and caller admission-receipt
identifiers. The receipt fields bind caller-supplied provenance only; this
in-process driver does not verify authority signatures or establish scientific
independence.

Q3.2 validates all operational branches before reserving a model slot. Its
joint arm confirms and freezes one three-unit plan. Its separate arm confirms
and freezes three distinct one-unit plans, each with a distinct
source-observation binding. Both arms retain the same four model slots.

Q5.3 binds each proposal to an actual plan branch, its candidate mechanism key,
and an order-independent semantic prediction signature. Deduplication uses the
declared mechanism key plus that signature; a common source root is not evidence
of a common mechanism. M4-off applies the title-only baseline to the actual
retained branches. M4-on applies mechanism-and-prediction deduplication and
freezes the retained discriminating plan. Opposite predictions under the same
mechanism remain distinct alternatives. If deduplication leaves
fewer than two candidates, the run records `not_distinguishable_after_dedup`
instead of freezing the unfiltered plan.

Both drivers are planning-only and set execution status to `not_measured`. They
do not execute an experiment, consume data, or establish calibration,
independence, scientific effect, or validation acceptance. Controller-only truth
is closed in the bundle and never forwarded to a model request.

Both arms use matching request schemas. The model sees actual retained branches,
plan material and public observations; controller stage/status and unverified
caller admission identifiers remain in the trace. These tests qualify the
planning seam; observation execution, independent admission, and benchmark
outcome scoring for these Q IDs remain separate required work.
