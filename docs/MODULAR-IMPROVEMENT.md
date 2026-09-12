# M9 train-only improvement boundary

`TrainingManifest.freeze` accepts only `DataIdentity` values in the `train`
domain and stores their exact identities in an immutable record. The bounded
builder accepts that manifest and an immutable parent package; it has no task
generation or validation API. Ordinary candidate packages may change only
`prompt`, `memory`, and `config`. Their train comparison must use the same
manifest and the same recorded search cost.

The independent meta-program phase uses the same bounded builder port but also
freezes the CandidateBuilder source digest and entrypoint in the resulting
package. It remains unable to alter custody, scoring, promotion, permissions,
or the current validation target.

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
benchmark or scientific performance.
