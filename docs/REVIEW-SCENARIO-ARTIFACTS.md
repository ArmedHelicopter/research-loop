# Review scenario artifacts

`run_review_scenario(..., artifact_root=...)` requires a new, non-linked output
directory. Before the first callback opportunity it durably writes the frozen
TRAIN task, cell identity, controls, and both producer-source snapshots. It
then appends each reservation, exact callback request, raw callback return,
typed response, and actual M5 engine event. Success retains the original
reveal, score, prediction-extraction trace, and result; callback failures close
the partial audit with an explicit failed terminal record.

`verify_review_artifacts()` is an offline strict consumer. It checks literal
inventory and bytes, independently supplied task/cell/variant/controls and the
known producer sources; reconstructs permitted requests, visibility, reveal,
revisions, and M5 journal in memory; and never invokes callbacks or writes,
recreates, or repairs an artifact. This is engineering provenance for an
offline fixture. It does not dispatch a benchmark or establish efficacy,
provider independence, or scientific validity.
