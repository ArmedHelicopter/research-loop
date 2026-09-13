# Training reference store

`evaluation.modular.reference_store.prepare_train_reference_store` is the
custodian-side bridge from frozen training allocations to the adapted rubric
endpoint. It verifies the entire requested packet allowlist before reading
source content, requires a new destination separate from the source and public
packet directories, and returns only a manifest hash, task handles and counts.
It does not allocate, expose or qualify validation data.

Discovery public export now records the exact metadata filename, file hash and
query index in its packet receipt. Reference extraction uses this selector and
the frozen metadata/query IDs, checks the public question, and requires exactly
one matching nonempty hypothesis in an explicitly hash-pinned answer key. The
aggregate key is parsed by the custodian; only allocated training rows enter
the exported store. Encodings are explicit, including the snapshot's CP1252
punctuation, and quoted newlines are preserved.

BLADE extraction requires every reference column in the received CSV and parses
all rows. Empty fields are allowed because different rows encode different
analysis alternatives. Every nonempty conceptual, transformation, model,
annotated-variable, annotated-transformation and dependency-graph JSON field is
retained; only wholly empty rows and duplicate complete semantic records are
skipped. No row or text-length truncation is performed. This follows the
historical benchmark scorer's field-selection contract; missing annotations
remain unavailable, not zero scores.

`FrozenTrainReferenceResolver` belongs to the scoring component. It pins and
rechecks the manifest and selected reference bytes on every lookup, matches the
task handle to its benchmark/train identity, and recomputes the exact public
task digest from the stored identity and context. Foreign handles, a changed
source selector, altered reference files or mismatched public task context fail
closed. `FrozenBenchmarkRubricEndpoint` consumes the returned reference record
without changing its frozen rubric or scoring semantics.

The tests use synthetic source files and actual public export, panel compilation,
runtime journals, endpoint calls, signed scoring receipts and receipt verification.
They test component wiring, complete field handling, allocation refusal and source
binding. This file interface does not establish OS access isolation, independent
scorer deployment, calibration, benchmark efficacy or validation acceptance.
