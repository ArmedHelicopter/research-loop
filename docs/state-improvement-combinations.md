# History build, candidate freeze and target solve

The remaining M9 inventory consists of eight distinct pairs M1×M9 through
M8×M9 and the frozen triples M3×M6×M9 and M7×M8×M9. Their outer inventory is
47 legal history builds and 94 legal target cells across two TRAIN benchmarks,
plus the two structurally unavailable M2-off/M9-on target cells. This slice
implements only M1×M9, M2×M9 and M3×M9: 11 builds, 22 legal target cells and
the same two structural exclusions. The other seven panels remain required.
Nothing here prunes singletons, the 36 pairs or five triples, opens validation,
or replaces the distinct Q6.2 optimization and Q6.3 metaprogram experiments.
The frozen estimand is total history-build and target-state interaction; this
design does not identify learning-only and inference-only effects separately.

`FrozenStateImprovementPlan` declares all build and target recipes before source
qualification or model calls. Existing closed TRAIN history is disjoint from
the two prospective TRAIN targets. Every history observation is tied to its
original runtime byte hash and literal keyed execution stdout. Candidate
training manifests contain that history identity only. `StateImprovementPanel`
adds the explicit `state-improvement-exposure-v1` contract for this separation;
the default `CombinationPanel` still requires exact target-manifest equality.
Disjointness is checked for the benchmark/task/group subject tuple. It does not
assert that different task IDs from a shared group are independent families.

Each legal arm receives two independent source calls, the actual typed state
transition, one useful proposal and one restricted-builder execution. M1 uses
subject-bound admission assessments; M2 and M3 use literal lineage material.
M3 has fixed M2 in both phases. M1×M9 also fixes M2 to satisfy M9's prerequisite.
M2-off/M9-on is a structural exclusion, not a failed or synthesized candidate.
M9-on executes the original proposed DSL. M9-off executes the useful frozen
builder while retaining its matched proposal opportunity and original response.
Unselected proposal text is excluded from target context.

All 11 candidates must pass read-only build replay before the immutable global
barrier can open. A failed build leaves all 22 target opportunities blocked.
Target code receives only actual post-transition state and the selected
candidate's consumed instruction/memory surface, then uses the same two-slot
benchmark solver and one Docker allocation. Model, source, context, builder
search-cost, Docker image/timeout and slot ordering are frozen and matched.
All target responses are sealed before process scoring. Scoring replays the
history, literal provider responses, builder receipt/output, candidate barrier,
state journals, target CSV/program/execution, shared request schema, panel and
scorer bindings. Source signatures authenticate observations; they do not
establish scientific validity. M1 comparisons become inconclusive when consumed
qualification semantics differ between arms in either phase.

Normal slice allocation is 55 model calls (11 proposal + 44 target), 11 builder
executions, 66 source qualification calls, 22 Docker attempts and 22 independent
process scores. Unknown source/provider costs block future downstream calls.
Failures and blocked cells remain in the predeclared denominator; no automatic
retry or pruning is allowed. Prior history acquisition has separate inherited
cost and is not included in these 55 calls. The source mode is explicitly
primary prospective TRAIN; legacy source routes elsewhere remain unchanged.

All tests for this slice use synthetic model transport, synthetic qualification
observations and synthetic scorer references. Docker, the restricted builder
and the separate scoring process execute real code. Passing those checks is
engineering evidence only and cannot establish causal efficacy or completion
of the larger research programme.
