# P0 custody audit snapshots

`evaluation.modular.custody_audit_projection` is an auditor-only, read-only view of a currently produced `modular-custody-v2` state file. It is neutral evidence: it does not fabricate a single TRAIN `DataIdentity` for mixed custody metadata, enter packet/optimizer paths, issue or consume leases, or claim operating-system isolation.

The caller must retain the original state bytes and supply an exact `custody-state-byte-anchor-v1` SHA-256/byte-count anchor. `verify_custody_snapshot` parses those pinned bytes with duplicate JSON keys rejected, replays the implemented inventory/group/split allocation, validates stored attestation and lease-record digests, and checks the identical state bytes again before returning. It contains aggregate digests and lease bindings; it omits rows, task identifiers, private state/data paths, protected contents, and keys. Source bindings retain the auditor and reused source-file paths, hashes, and byte counts.

Those metadata checks do not authenticate an external custodian or calibration authority. The result explicitly records both as unverified. A separately persisted `custody-panel-lease-v2` record may be supplied to the callable with a caller-held mapping of trusted HMAC authority keys. Those are symmetric verifier secrets, not public keys and never appear in output. The reader verifies the existing signature semantics and requires exact replay of one retained, panel-validated, consumed lease. Without such a record it reports `receipt_observation.status: "absent"`; it never infers receipt issuance.

The result also binds SHA-256/byte snapshots of this auditor, `custody.py`, and `panel_receipts.py`, because it reuses their inventory and HMAC receipt semantics. A byte anchor proves the supplied historical state bytes, not scientific validity, OS/process isolation, external-custodian authority, calibration authority, or any unretained receipt.

The CLI intentionally supports state-only audits, so it cannot solicit or serialize HMAC authority material:

```powershell
python -m evaluation.modular.custody_audit_projection `
  --state <custody-state.json> `
  --state-sha256 <caller-retained-sha256> `
  --state-bytes <caller-retained-byte-count> `
  --output <new-auditor-owned-result.json>
```

`--output` creates a new auditor result exclusively; the custody state is never written. This preserves the existing custody store and its deployment-specific process/mount boundary.
