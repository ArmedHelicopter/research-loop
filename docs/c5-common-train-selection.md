# Common TRAIN selection

`select_joint_common_train` consumes the exact `JointCommonTrainRun` and invokes
its complete current-original verifier. It has no raw-score or old-family-score
entry point. The precommitted `FrozenTrainSelectionRule` is taken from the actual
common protocol. Every cell must be authenticated and scored, including B0;
only the matched recipes participate in ranking. Paired differences are averaged
within source groups and then equally across groups and the two benchmarks.
The original tie order and per-benchmark regression limits remain unchanged.

The selected subject binds the full recipe, original history build, learned
package and all nine component templates. Two recipes sharing a package retain
different activation identities. All matched candidates and structural exclusions
remain in the result; negative single-module scores never prune combinations.
`verify_joint_common_selection` replays the original controller and recalculates
the choice, so a saved hash or selected-arm string alone cannot qualify it.

This is an offline TRAIN decision. It does not construct the final nine-component
deployment snapshot, open validation, issue acceptance or complete any original
Q/C experiment. The private arithmetic helper is not an authenticated selection
API. A successful whole-controller-to-selection integration is required before
claiming that execution boundary works; arithmetic tests alone do not prove it.
