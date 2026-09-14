# Common C5 stage runtime kernel

`FrozenJointTrainRuntimePlan` admits one complete common TRAIN protocol and its
original prospective packets, history trace/CSV, parent, fixed builder, qualified
state/retrieval and auxiliary materials, source authorities and scorer handles.
The complete current implementation tree is pinned. Each component template must
name the fixed imported consumer and its actual history/material/parent/builder
inputs; arbitrary component config/state is not treated as executed policy.

`JointTrainStageExecutor` owns one fresh `PhaseProviderSession`. Its actual stage
calls use the existing `full_loo_modules`/`run_stage` pipeline, with exact native
slot caps and original replay through globally unique phase scopes. Plan, data,
source and consumer bindings are checked before each model call and after each
stage. Unknown MAIN and provenance failures stop the allocation. Known MAIN usage
is retained separately from unknown initial TITLE and all-opportunity settlement.

Each new C5 outer stage binds the original inner pipeline receipt and provider
seal. Reusing the inner `c4-stage-receipt-v1` format does not complete C4, original
Q obligations or the complete common grid. The kernel always reports
`score_eligible=false`; partial checkpoints retain every canonical history build
and target row from the unmodified formal catalogue. This permits bounded stage
integration checks without creating a truncated formal experiment.

`JointTrainBarrier.seal` rejects incomplete history grids. It replays all original
canonical builds before `compile_panel` can produce the full `JointTrainPanel`.
The kernel alone does not schedule the full grid, issue scoring inputs, select a
candidate, apply independent component updates or open validation. Those require
the subsequent controller and authenticated selection boundary.

The sole imported unmerged C4 dependency is the `verify_stage` phase-ledger
extension from commit `a08dc1c` (identical in `021c40d`), imported separately at
`8b103fc`. The C4 controller, plan, panel and native-provider files are unchanged.
Root should compare/deduplicate this exact file when integrating the C4 branch.

Tests use synthetic provider/qualification peers with actual restricted builder,
Docker history/target execution and original replay. They never launch an actual
model, use an API, score scientific outcomes or access validation.
