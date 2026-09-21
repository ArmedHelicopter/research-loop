# S ordinary revision cache: native correctness experiment

VersionCache is an experiment-local ordinary version cache. It observes the existing ledgers' append events, preserves their audit sinks and failure callbacks, and drops cached bundles after any event. The cache key includes identity, question, context budget, mode and baseline summary. Because public context contains global ledger versions, even unrelated evidence updates must invalidate. It is not a new algorithm or selective dependency optimization.

Results: 98 deterministic R/B/S differential checkpoints with exact complete bundle equality; 6 existing real pre-call contexts matched; 4 edge checks (synthetic validation nonretention, object rebinding, displaced observer rejection, failed-write poison) passed. No new model/scorer call or formal VAL input was used. Random synthetic operations are correctness fixtures, not scientific tasks.

Contract: one serial controller, exact native classes, all ledger mutations through public methods, no external journal edits or private-state mutation. Observer hooks are a local experimental seam; not production integration. Observers preserve existing audit callbacks. Cold-start binding, event maintenance and invalidation costs must be included in later measurements.

AND is **not passed**. The native reference has flat disjunctive support roots; withdrawing one of two roots leaves the other supported. depends_on marks downstream interpretations for review and is not a conjunction of support clauses. and-capability-gap.json freezes the minimal representational counterexample. Native equivalence therefore does not establish completion of all semantics in the brief.

No core source was edited. Performance is unmeasured in this experiment. Invoke from repository root: python -B experiments/week1_evidence_cost/check_version_cache.py run --run S-native-r1 (existing output is deliberately exclusive; do not overwrite original receipts). For a new correctness opportunity, freeze into a fresh run directory first.
