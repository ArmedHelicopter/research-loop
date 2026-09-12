# Q3/Q5 prediction fixture scenarios

`research_loop.modular.scenarios_predictions.run_prediction_scenario()` implements the remaining exact fixture mechanisms for Q3.1, Q3.2, Q5.2, Q5.3, and Q5.4.  It accepts an already-prepared immutable `PublicTask`, a closed frozen public control record, and an optional callback.  It never accepts a path, data contents, labels, gold answers, score, optimizer state, validation feedback, or network/model client.

Every registered variant freezes and exposes the actual M4 plan payload to the callback, records a real shared-discriminator update through `PredictionRegistry` when M4 admits the plan, and retains both payload and ordinary callback-response digests. Callback text is never treated as a trusted scientific validator; admitted plans remain recorded as `unknown`, which deliberately avoids inventing an outcome or a scientific winner.

Q3.1 freezes organization, extra-computation, and measurement-bias branches against one common intervention discriminator; each registered focal variant binds a different frozen intervention in the callback payload. Q3.2 compares one three-branch joint plan with three pairwise plans under the same three-unit budget, emits three callback requests in each arm, and retains explicit observation identifiers. This is an accounting and mechanism fixture; it does not establish calibration, data independence, or a preferred arm.

Q5.2 combines M4 with M7 feasibility stages: the same-prediction request is retained as an M4 rejection receipt and its own frozen request feeds the failed measurement stage; it is never replaced with the negative-control plan. Q5.3 performs both declared mechanism/prediction deduplication and a title-only baseline before the next callback, which receives the frozen result. Q5.4 performs M7 selection inside an already-claimed research item before the next callback; it requires a frozen policy bound to that plan and identity, and validation requires evidence that the policy was frozen before validation. Outer FIFO remains unchanged.

The registry hook name for `research_loop.modular.experiments.scenario()` is `prediction_injection`. The shared registry is intentionally not edited in this worktree.

These are engineering fixture traces across both public adapter forms. They demonstrate that the specified ports, controls, and callback bindings execute. They are not a benchmark run, a measurement of efficacy, evidence of scientific validity, or a result about actual model behavior.

The fixture's local `frozen_before_validation` declaration is not a custody
receipt proving when a policy was frozen. Formal validation still requires the
independent panel lease and policy/package binding; callers cannot use this
fixture declaration to qualify a validation search. Title comparison is
implemented; an embedding baseline remains unmeasured. Observation IDs in these
fixtures are declared synthetic IDs, not proof of independent source data.
