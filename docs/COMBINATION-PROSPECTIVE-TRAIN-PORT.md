# Prospective primary training input for combinations

Behavior: the three existing M4/M5, lineage and retrieval/review controllers may
consume `PrimaryProspectiveTrainExporter` packets directly. Version 1 configuration
and `benchmark:task_id` keys remain exact legacy contracts. Version 2 explicitly
requires `export_mode=primary_prospective` and opaque TRAIN export tokens; neither
format is inferred or converted into a synthetic legacy custody store.

Invariant: exactly one typed source is supplied, its roots and split match the
frozen configuration, and the standard exporter enforces the sealed allocation,
eligibility holds, input pins and exposure journal. Exported token, identity,
task, CSV and serialized packet bindings must match before any model, source
authority, Docker or scorer call. A train export followed by rejection retains
the original exposure and blocked controller receipt. Validation tokens are
rejected by the original exporter before public materialization. No reference
payload is available through this port.

Verification: execute each actual controller with two synthetic tasks exported
by the real primary broker, preserve its complete factor grid, and check all
actual model requests and scorer bindings. Exercise cross-mode ports, wrong
roots/split/token/identity, stale public bytes and export failures; verify zero
downstream I/O on rejection. Existing legacy controller, exporter and label
isolation checks remain required. These synthetic checks establish an integration
seam, not actual training effects, scorer calibration or validation acceptance.

Deliverable: explicit configuration handling, one shared packet-source helper,
three wired controllers, integration/failure evidence and frozen source hashes.
This change does not increase model opportunities, alter combination designs or
prune any experiment.

The first frozen 24-check run on `9208a2c` retained 21 passes and three failed
normal grids. Its synthetic final-response callback incorrectly required
`execution_feedback.exit_code`, while the actual public contract exposes
`status/stdout/stderr`. Each controller retained its first failed call and all
later blocked cells. The corrected callback checks the existing `succeeded`
status; no production behavior or acceptance threshold was relaxed.
