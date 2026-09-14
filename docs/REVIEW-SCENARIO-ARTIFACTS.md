# Review scenario artifacts

`run_review_scenario(..., artifact_root=...)` can retain a fixture-only review audit.
The reader validates the original frozen task and controls, callback payloads and
responses, mechanism trace, result record, and byte hashes without invoking a
callback or opening a review engine. This is engineering provenance for the
offline fixture; it does not make the scenario a benchmark dispatcher or claim
efficacy, provider independence, or scientific validity.
