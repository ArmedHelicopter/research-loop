# C5 frozen handoff (wave 1)

This module freezes a structurally complete TRAIN-only joint-bundle handoff and
a paired C5 validation-panel description. It binds each closure's component
package, config, state view, background, resource schedule, candidate panel,
candidate receipts, rule, selected target, baseline/control/ablation closures,
and paired core-benchmark validation identities.

`prepare_joint_train_handoff` is deliberately **not** a validation admission.
Existing one-Q `train_selection` receipts cannot authenticate a cross-C2–C4
joint winner, and there is no current typed joint-controller verifier adapter.
The handoff therefore records
`unavailable_no_typed_joint_train_verifier` and exposes no lease, score,
acceptance, or deployment port. A later wave must add a typed verifier for a
complete joint controller before custody can consume this panel.

The module never changes the Q1–Q8, C2–C4, or Q6.3 registries.
