# M9 train-only improvement boundary

`TrainingManifest.freeze` accepts only `DataIdentity` values in the `train`
domain and stores their exact identities in an immutable record. The bounded
builder accepts that manifest and an immutable parent package; it has no task
generation or validation API. Ordinary candidate packages may change only
`prompt`, `memory`, and `config`. Their train comparison must use the same
manifest and the same recorded search cost.

The independent meta-program phase uses an actually executed, restricted
CandidateBuilder DSL rather than host code execution. Its exact source has four
fields: the fixed `emit_literal_change_v1` entrypoint, one allowlisted `prompt`
or `memory` surface, an allowlisted key, and a text literal. `RestrictedBuilderPort`
interprets that frozen source only after it matches the expected source digest
and entrypoint; it emits a candidate plus a receipt binding the builder source,
entrypoint, parent package, training manifest, output candidate, and search
cost. It has no filesystem, network, process, validation, task-generation,
scorer, admission, or promotion capability.

`MetaBuilderCandidate` carries the next DSL version as a metaprogram package.
`BuilderRegistry` switches the next-round active builder only after an independent
acceptance receipt for that exact meta package. A builder source or entrypoint
drift, validation provenance, repeated meta receipt, or stale parent builder is
rejected. Ordinary prompt changes cannot use this registry or count as a Q6.3
meta-program run.

`TrainOptimizer` stores candidates and matched-cost comparison links in its own
SQLite database. It has no acceptance, deployment, or validation receipt method.
`AcceptanceAuthority` is configured by the host with separate trusted acceptance
and validation keys plus an independent validator. It first verifies the signed
validation receipt, then signs only a validator decision that binds the exact
candidate, expected active package, validation trial, and validator identity;
there is no caller-provided `accepted` boolean.

`ExecutionRuntime` persists packages, consumed receipt IDs, and active package
in a separate single-writer SQLite database. It activates only after an HMAC
verified acceptance receipt and a live deployment acknowledgment of both package
and memory digest. The next task reads those host-confirmed digests. Rollback
requires a separate signed, one-time authorization and can restore only the
active package's parent; it likewise requires a live host acknowledgment. Offline
hosts, drift, stale receipts, and replayed receipts fail closed.

The included fixture verifies actual off → on → off task behavior, including
memory digest restoration, and a separate meta-program phase package. These are
engineering checks using synthetic train identities only; they do not measure
benchmark or scientific performance. In particular, neither the ordinary M9
candidate path nor the second builder phase has received the required two
benchmark independent validation results.
