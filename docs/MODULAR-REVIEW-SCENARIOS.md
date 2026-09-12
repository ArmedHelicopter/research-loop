# Q4 review fixture scenarios

`research_loop.modular.scenarios_review.run_review_scenario()` implements the registered Q4.1--Q4.5 variants as fixture-only integration traces. It accepts one already prepared `PublicTask`, a closed frozen record containing public task, evidence, and budget digests, an optional deterministic engineering callback, and an optional M5 JSONL journal path. It accepts no task path, labels, gold answers, scorer result, validation feedback, optimizer state, network client, or paid-call configuration.

Every callback receives the actual frozen payload submitted to `ReviewEngine`; each response is sealed, retained, revealed, and, for Q4.3/Q4.5, revised after reveal. The journal records the real M5 open/submit/revise/score events and can later be attached to a panel receipt. The callback response is never discarded or converted into a synthetic preferred answer.

Q4.1 fixes four budget units before callbacks: `single` makes one four-unit call, while `independent_samples` and `roles` make four one-unit calls. The roles arm has four concrete questions for mechanism, alternative, measurement failure, and a discriminating experiment. Thus budget equality is an explicit accounting control, while call count remains visible rather than being claimed equal.

Q4.2 gives one concrete duty per registered arm; only the `generic` arm uses the generic opposing instruction. Q4.3 compares sealed submissions with intentionally sequential visibility, then uses M5 reveal and revisions in both cases. Q4.4 permits an `accept` response for material with no supported counterexample and records concern/accept outcomes rather than rewarding opposition.

Q4.5 scores actual before and revised callback responses with a local fixture oracle held outside callback payloads. It reports separate right-to-wrong, wrong-to-right, unchanged, denominator, and net-correction counts. The oracle is an engineering test oracle, not benchmark labels or a scientific scorer. `heterogeneous` refuses to run until the caller supplies every reviewer ID, model ID, provider, and provenance. No default provider identity is invented.

The controls, arm definition, callback count, and budget are constructed before any callback response. There is no outcome-derived arm selection or validation optimization. These traces only establish that the ports and receipts execute across the public adapter forms. They do not measure benchmark efficacy, prove independent training priors or provider diversity, demonstrate scientific validity, or count as completed experiments.
