# M4/M5 event provenance

`ModularWorkflow` installs optional observers on `PredictionRegistry` and `ReviewEngine`.
Each observer runs only after the module has appended and fsynced its original JSONL event.
It writes one `journal_event` descriptor for each M4 `freeze`/`outcome` and M5
`open`/`submit`/`revise`/`score` event.

`ReviewEngine.reveal` intentionally has no JSONL event. Its optional output
observer therefore writes a separate `reveal_output` descriptor containing the
actual returned ordered submission tuple and parents every sealed submission.
This does not change the existing review journal format or algorithm.

The descriptor holds the exact persisted event, journal index, activation status,
module source snapshot, and bridge source snapshot. M4 outcomes parent the frozen
plan. M5 submissions parent their `open`; revisions and scores also parent the
sealed submissions. A disabled arm remains traceable as `not_applied`.

`verify_m4_m5_artifacts` reopens the source journals, reconciles every ordered event
descriptor, checks identity, lock activation, source snapshots, causal parents,
duplicate and barrier semantics, and validates any C4 reveal against the complete
sealed submissions. It returns engineering provenance only and keeps
`scientific_validated: false`.

If descriptor writing fails after a module journal fsync, the bridge writes the
runtime terminal audit-failure marker before the caller can make another model
request. This preserves the durable event and prevents later model calls from being
mistaken for a complete artifact stream.
