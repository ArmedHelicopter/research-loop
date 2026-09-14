# Prediction scenario artifact custody

`run_prediction_scenario()` is an offline, TRAIN-only fixture runner.  It now requires an explicit, new `artifact_root`. Before any callback, it writes an attempt and immutable input record binding the exact public task, identity, frozen controls, experiment, variant, and producer-source snapshots.

Every frozen plan, callback request, raw callback return plus typed response, M4 outcome, and mechanism trace is appended to the durable journal. A callback exception is retained as a failed terminal attempt. A successful attempt writes a terminal result, then the runner calls `verify_prediction_scenario_artifacts()` before returning it.

The verifier is read-only: it invokes no callback and creates or repairs no files. It rejects links, partial/noncanonical journals, extra or missing files, changed source snapshots, mismatched task/control/experiment bindings, broken journal parents, callback response digest drift, missing completed output, and closure/inventory drift. The records keep the runner's existing budgets, Q3.2 joint/separate allocation, Q5.4 FIFO declaration, and fixture-only `unknown` outcome semantics. They do not make a benchmark, model, or scientific-validity claim.
