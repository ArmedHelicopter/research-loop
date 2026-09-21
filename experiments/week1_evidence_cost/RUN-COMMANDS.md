# Executed entry points and immutable evidence

Working tree: E:/_ryanDev/AI/research-loop-week1. All paths below are relative to experiments/week1_evidence_cost unless noted. Existing run names are immutable and commands creating their directories must not be rerun over them.

- measure.py freeze/run --run r1: original existing-record inventory/diagnostic; sources and execution receipt in r1/.
- qualify_domain.py: public TRAIN adaptation attempts r1–r4; successful identities, paths and hashes in qualification/r4/public-index.json. Failed adapters retained.
- domain_pilot.py freeze/run --run domain-pilot-r1/r2/r3 --index N: actual per-version producers are archived in each series. Started opportunity registry gives the exact attempted indices; do not infer that all manifest indices ran.
- measure_domain.py --run domain-pilot-r2 --only week1-domain-2-r2 --output measurement-task2; analogous task3 and domain-pilot-r3 measurement-task1: exact pre-call diagnostics.
- check_version_cache.py freeze/run --run S-native-r1: 98 native correctness checks, saved-request equality and explicit AND gap. Additional callback check retained.
- compare_native_replay.py freeze/run --run RBS-replay-r1: three short workflows, 180 children.
- check_domain_rich.py: fixture r1 failure retained; r2 real Docker/RunSession with substituted model transport. check_rich_bindings.py: pointer binding and negative checks.
- domain_rich.py freeze/run --run domain-rich-r1 --index 0: fifth live opportunity, qualification not measured.
- domain_rich_v2.py freeze/run --run domain-rich-r2 --index 0: sixth live opportunity, mounted-file correction, 14 statistics and one declared dependency.
- audit_rich.py domain-rich-r1 week1-rich-domain-1-r1; audit_rich.py domain-rich-r2 week1-rich-domain-1-r2: exact fact/program/receipt/pointer bindings and observed operation costs.
- measure_rich.py --run domain-rich-r1 --only week1-rich-domain-1-r1 --output measurement-r1; analogous r2: 900 diagnostic batches each, separate from native scheme comparisons.
- compare_rich_replay.py freeze/run --run RBS-rich-r1: 180s parent bound, incomplete at 46/60.
- compare_rich_replay_bounded.py freeze/run --run RBS-rich-r1b: fresh 600s parent batch, 60 children.
- compare_rich_replay_v2.py freeze/run --run RBS-rich-r2: real dependency sequence, 60 children.
- summarize_replay.py RBS-rich-r1b and RBS-rich-r2: independent per-child component sums and descriptive timing quartiles.
- audit_week1.py: six original opportunities, 13 completed client turns and prompt hashes, all current input/core hashes, explicit unsatisfied native AND capability.

Use python -B from the worktree with the frozen source version. Runtime is pinned in manifests, not inferred from a future PATH. Archived producer files preserve source bytes; run from the original source location or establish a new declared workspace rather than silently modifying archived source. Native replay does not need dataset CSVs; actual new domain execution requires the exact public CSV hashes and a newly authorized opportunity (current six-opportunity cap exhausted).

Runtime journals for native replay are under E:/_ryanDev/AI/research-loop-modular/work/<run>/; schedules and all returned measurements are committed. Quota receipts and authorization remain in that work directory; BUDGET-ACCOUNTING.json exports only sanitized fields. No authentication material is part of the delivery.
