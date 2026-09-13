# Remaining primary TRAIN source ports

This extension connects the previously executed admission and M7/M8 combination
controllers, plus the separate Q3.2 execution phase, to the same explicit sealed
primary TRAIN exporter used by the other three combination families. It does
not add experimental arms, change the model or execution budgets, replace the
independent scorers, or promote any scientific endpoint.

Admission and M7/M8 each get an explicit v2 configuration with
`export_mode=primary_prospective`, opaque export tokens and exact task/CSV source
bindings. Legacy v1 accepts only legacy custody identities. Exactly one source
port is allowed. Each export must retain the original batch/per-packet receipts
and completion audit chain, even if a later compiler rejects the packet.

Q3.2 receives a separate typed prospective-source entry while retaining its old
planning and legacy execution contracts. Caller materials and the source/task
allowlist freeze before export. Three programs and all input bindings still
freeze before any Docker observation. Successful execution does not establish
independent data or scientific measurement validity.

Integration checks must run the actual controllers using synthetic sealed
primary packets, actual bounded Docker and the existing independent scorer
processes where applicable. Test all original legal cells, legacy regressions,
wrong source mode, mismatched roots/splits, validation tokens, token swaps,
forged packet metadata and missing completion anchors. Reject before downstream
model/authority/Docker/scorer I/O, preserving completed export receipts. Actual
private reference payloads and validation exports remain excluded.

Verification on 2026-09-13: the isolated source passed 54 checks with 466
unchanged source/document hashes. The actual primary-packet grids reached all
24 admission scores, eight scheduler scores and 12 Q3.2 measurements. The first
scheduler attempt failed all eight cells before any Docker/model/scorer call
because execution still used a legacy task-name lookup; its original report and
full denominators remain archived. The repair uses complete identity binding.
No scientific efficacy or validation eligibility is inferred.
