# C5 frozen handoff, wave 1

This module creates a **prepared** C5 handoff. It does not select a winner,
issue a custody lease, score validation data, accept a bundle, or deploy one.

`PreparedJointTrainHandoff` is bound to a typed, complete C2--C4 `CombinationPanel`
and to canonical `JointClosure` objects. Each closure seals its M1--M9 component
versions, configs and state views; the legal compatibility arm; fixed baseline
and background; always-enabled P0 control; and resource schedule. The B0 closure
is legal with an empty optional-module activation because P0/core remains bound.
The object explicitly reports `requires_typed_joint_train_verifier`; current
combination panels expose the original train structure but not a joint-selection
verifier that this wave can consume.

`freeze_c5_validation_panel` accepts only the fixed proposed target, the complete
pre-registered target/baseline/control/ablation arms, typed validation
`DataIdentity` cells, a target-relative `joint_bundle` coefficient matrix,
criteria, and resource schedule. Every arm must occur for every
`(benchmark, source group, task, replicate)` cell. Multiple independent groups
are allowed; BLADE and DiscoveryBench group names are deliberately not compared
across benchmarks. All records remain validation-, acceptance-, and
 deployment-ineligible.

The next wave needs an independently typed joint TRAIN verifier that consumes the
original runtime receipt set, then separately independent validation/calibration
and custody/deployment gates. This module must not be used to bypass those seams.
