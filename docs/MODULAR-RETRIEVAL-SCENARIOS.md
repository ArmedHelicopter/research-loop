# Q8 retrieval scenario driver

`research_loop.modular.scenarios_retrieval` implements the Q8.1--Q8.7
engineering scenarios with frozen local source bundles.  These bundles are
explicit fixtures, not an open-web qualification, external scientific corpus,
or model-training input.

Each arm takes a public task, a closed `task_digest`/budget fixture control, a
fresh sidecar, and a provider callback.  The callback sees only a frozen public
request.  The driver preserves each request, response, provider call, and
controller journal; fixture truth and labels never enter those payloads.

| Coverage ID | Runnable contrast and retained seam |
| --- | --- |
| Q8.1 | Calls Stage 0.5 retrieval, Stage 1 prediction planning, Stage 3 restricted execution, Stage 7 independent review, Stage 9 retrospective review, and frontier audit. `record_stages` binds each executed stage to its actual journal trace. |
| Q8.2 | Uses three concrete local source texts: a correction, a runnable method/resource, and a reframing challenge. Output reports context change only; it makes no parameter-update claim. |
| Q8.3 | Compares support-only, neutral, and three-lane source layouts under one call and source limit per lane. All lanes are called; an empty lane is valid. |
| Q8.4 | Runs M6 then materializes selected sources through the M2 evidence ledger. Three documents with one root give one ledger root; three independent roots give three. |
| Q8.5 | Freezes trigger inputs for new mechanisms, conflicts, innovation, unknown dependencies, stagnation, and a locked cheap diagnostic. The cheap diagnostic suppresses stagnation before any provider call. |
| Q8.6 | Sends malicious and conflicting source text through M6, then applies the original RunSession lock at the final gate. A legal pause and a separately versioned research request remain dispositions, not source-authorized rewrites. |
| Q8.7 | Builds frontier inputs from remaining claims, anomalies, failed checks, untested plans, and the locked objective boundary. It executes the frontier callback even when empty. Validation cannot export follow-ups; train exports retain `proposals_only`, no benchmark admission, no queue admission, and `programme_complete: false`. |

The scenarios are controller/integration checks. They do not measure retrieval
quality, scientific validity, novelty, real instrumentation, or benchmark
performance. They do not qualify a source bundle for open-web use.
