# Prediction scenario artifact custody

`run_prediction_scenario()` is an offline, TRAIN-only fixture runner.  It now requires an explicit, new `artifact_root`. Before any callback, it writes an attempt and immutable input record binding the exact public task, identity, frozen controls, experiment, variant, and producer-source snapshots.

Every frozen plan, callback request, raw callback return plus typed response, M4 outcome, and mechanism trace is appended to the durable journal. A callback exception is retained as a failed terminal attempt. A successful attempt writes a terminal result, then the runner calls `verify_prediction_scenario_artifacts()` before returning it.

The verifier is read-only: it invokes no callback and creates or repairs no files. It rejects links, partial/noncanonical journals, extra or missing files, changed source snapshots, mismatched task/control/experiment bindings, broken journal parents, callback response digest drift, missing completed output, and closure/inventory drift. The records keep the runner's existing budgets, Q3.2 joint/separate allocation, Q5.4 FIFO declaration, and fixture-only `unknown` outcome semantics. They do not make a benchmark, model, or scientific-validity claim.

The v2 reader reconstructs the exact mechanism journal in memory using the
caller's task, controls and variant, the seven known producer/contract source
paths, and retained raw callback returns. It does not trust a self-declared
source path or a terminal result as the expected experiment. It checks exact
registry freeze/outcome events, requests, raw-to-typed conversion, trace,
output, module attribution and typed parent links. The producer passes its own
attempt ID to the return consumer. M4 deduplication and M7 feasibility/diagnostic
selection additionally retain their full actual input and output values.
Historical reads require the original source
paths; external identity attestation and complete environment replay remain
outside this fixture seam.

JSON-compatible invalid callback values are retained before adaptation fails.
Unsupported Python objects retain only their type and an explicit unavailable
representation. Failures after callbacks preserve the exact completed prefix;
storage failures retain partial bytes and cannot pass complete verification.
A final delivery failure never rewrites an already closed success: it leaves a
separate failure marker, which prevents that directory from being consumed as
completed. Failure-prefix verification does not prove the reported exception's
external cause. No callback/model cost is inferred from zero exit or call count.

These fixture records are a dedicated journal; a universal cross-directory
catalogue, all module outputs, resource apportionment and scientific efficacy
remain separate work. The v1 implementation and its eight accepted coherent
forgeries are retained as failed engineering evidence, not upgraded in place.
