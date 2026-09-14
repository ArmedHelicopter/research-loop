# C5 structural preparation: supported source and remaining work

`prepare_joint_train_handoff` now has a callable, journal-replayed path from the
existing `run_combination_cell` public runner. This adapter accepts exactly the
ordinary `CombinationPanel` M4/M5 factorial (`interaction_on_scale`) and its
complete successful TRAIN receipt grid. It is **preparation only**: no joint
TRAIN selection, validation read, custody lease, scoring, acceptance or deployment
is implemented or authorized here. A terminal `unknown` source decision can be
bound structurally and does not become a scientific result.

The adapter is named `m4-m5-combination-binding-only-v1`. It recognizes the
runner's original objective lock, package/scenario model request, response and
final gate; common protocol and panel verifiers replay the original journals.
It binds the actual `combination-package-bundle-v1` FrozenRecord, keyed by
runtime-arm digest. This repository has no separate `PackageBundle` class.
Every arm, including empty optional-module B0, retains its exact whole-arm
`CandidatePackage`. Component fields are explicitly **projections of that
whole-arm package**, not independently built module versions or proof that a
module effect ran. The adapter rejects specialized five-slot runtime journals
and other panel subclasses rather than partially validating them.

Closures are reconstructed from each source arm and each original journal.
All task/replicate instances must agree on package, compatible activation,
baseline, fixed background/objective, P0 checklist/final gate and call/resource
schedule. Supplying closures is optional; if supplied, all four must exactly
match this reconstruction. Swapped arm packages, an unrelated B0 package,
missing/extra arms and unobserved component state are rejected. Original
canonical journal records are sealed into the handoff; freeze replays the
source again so later file modification invalidates the handoff.

Both direct dataclass constructors and factories enforce the same invariants.
The full M4/M5 arm `11` is a fixed **proposal**, not a selected winner. The C5
preparation retains exactly one target and one B0 plus control and ablation
arms, with a separate target-minus-comparator contrast for every other arm.
There is no score input or alternative-winner selector. Every arm must occur
for every complete `DataIdentity` and replicate; dataset version and `split_id`
(the actual field carrying the split digest) participate in pairing. Both core
benchmarks are required, the source split remains fixed, and source TRAIN groups
are excluded. These identity checks do not authenticate holdout custody.

Acceptance criteria are concrete frozen per-benchmark score definitions/ranges,
minimum gains, zero allowed safety regression, maximum cost ratios, minimum
independent groups, explicit failure policy and the complete multiplicity family.
Every comparator is tested separately in each benchmark under those proposed
criteria. The preparation records criteria, contrasts and schedule in full; no
threshold is inferred from an observed score and no criterion is evaluated here.
The source adapter currently has one fixed call schedule, checked for every
closure. Example thresholds in tests apply to synthetic data only and are not
the research programme's approved scientific criteria.

`tests/test_c5_frozen_handoff.py` builds a real typed two-benchmark, eight-cell
TRAIN source using the public runner and in-process synthetic responses, then
freezes a 32-cell synthetic C5 identity grid. It exercises original journal
replay, constructor bypass attempts, arm/package/P0/context/source substitution,
full-identity pairing, roles, contrast coefficients and frozen criteria. These
are engineering checks with no remote model call, real validation dataset or
scientific score.

The remaining work is unchanged: independently authenticated joint TRAIN
selection across broader candidate families; adapters for all required ordinary
and specialized sources; independently versioned joint component builds;
C5/V_final allocation and custody; calibrated independent contrast acceptance;
atomic joint deployment/rollback. All 48 question contracts, nine singleton or
conditional studies, 36 pairs, five triples, C4 full/leave-one-out and the separate
Q6.3 metaprogram remain obligations. This narrow adapter neither completes nor
prunes any of them. The earlier two-test implementation remains in Git history
(`3c18e16`, `c94286d`) as the unverified version superseded by this repair.
