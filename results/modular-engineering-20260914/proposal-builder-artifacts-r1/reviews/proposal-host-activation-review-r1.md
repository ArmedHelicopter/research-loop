# Q6.5 shared proposal versus M9 activation

2026-09-14, source 35d2209. Read-only review while proposal-builder-hosts-r3
is running; the frozen source tree has not been edited.

`train_operations._AttemptPlan.selected_builder` always uses the proposed
builder for Q6.5. Its downstream guard is independently enabled only for the
sealed_calibrated variant with M9 in the arm. Sharing a proposed builder across
controls must not mark a disabled M9 arm as applied. The new
`metaprogram_training._builder_applied` currently returns True for Q6.5 before
checking the arm and would emit produced/applied descriptors for disabled arms.
The direct host tests cover enabled/fixed control but not this shared-proposal
operation case. Existing operation tests check outcomes rather than this new
artifact attribute, so a passing r3 must not be treated as closing this finding.

After r3 closes, retain its exact source/report and check actual Q6.5 artifact
records for this mismatch. Check the disabled arm first in the activation helper;
keep the existing selected_builder policy unchanged. Add assertions through the
actual Q6.5 operation grid that disabled arms have not_applied builder witnesses
while their original response and selected DSL remain the proposed builder.
For enabled arms, produced records identify the configured M9 component and
actual outputs, not a causal estimate of the shared builder's contribution.
The downstream guard's application is a separate operation artifact still
requiring its own adapter. Preserve fixed Q6.2/Q6.3 selection and the other
operation selectors, their search allocation and all outcome thresholds.
