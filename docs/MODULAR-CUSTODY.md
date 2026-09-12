# Modular custody

`evaluation.modular.custody` inventories only filenames, paths and SHA-256 values.
It does not parse task text, references, labels or CSV cells. DiscoveryBench keeps
its `synth|real` and `train|dev|test` mapping. BLADE has no such split in the
local snapshot. Every BLADE directory starts quarantined: a complete local
`data.csv`/`info.json`/`annotations.csv` shape is not proof of source
independence or non-exposure.

Historical exposure is explicit: the documented DiscoveryBench synth/test
selection and BLADE formal plus development tasks are train-only. This does not
erase their historical validation role; a new protocol must record any use as
training or diagnostics. Unknown exposure is quarantined rather than guessed
clean. A group may leave quarantine only through an explicit independent
custodian attestation carrying immutable source and exposure proof digests and
listing the tested arms from which its custodian is separate. A tested arm ID
cannot also be the custodian ID, and no `clean` inventory value exists for an
arm to self-assign. The API records that claim; authenticating the independent
custodian remains a deployment duty.

The broker merges items sharing a source-group label or a file hash, then assigns
whole merged groups deterministically. It exports only `DataIdentity(domain=train)`
objects. A validation lease is bound to a frozen split, panel digest, scorer,
pre-registered calibration protocol, and exact arm schedule; it turns consumed
permanently after use. A metadata-only `qualify` result is not authenticated and
is never calibration eligible. A lease requires a configured independent
calibration authority's signed receipt, whose frozen criteria bind both
benchmarks' coverage, confusion counts, abstention and finite uncertainty. The CLI
has no calibration key configuration, so it cannot issue a lease. The CLI supports
`attest`, `export`, `qualify`, and `consume` so a child process cannot bypass
those checks.

For panel validation, a configured custody service issues a `custody-panel-lease-v2`
receipt only after consuming its own calibration-eligible lease. The receipt binds
the candidate, panel, split, scorer, protocol, calibration-receipt and criteria
digests, arm schedule, and groups. `PanelReceiptVerifier` verifies this receipt
with configured custody and calibration keys; a standalone caller HMAC, active
lease, or typed field match is insufficient. This remains engineering custody
wiring: it does not prove that calibration materials were independently made or
that an external scientific authority accepted a result.

Exported identities bind the actual split digest, while the separate official
split field preserves upstream provenance. Every member of a merged source
group must have independent custody attestation before that group can enter
validation. A cross-process writer lock and state compare-and-swap reject stale
controllers that would otherwise overwrite another validation lease. Persisted
inventory and split hashes are checked on reopen. These checks detect drift and
concurrent lost writes; they are not authentication against an administrator who
can rewrite the whole custody store.

Example:

```text
python -m evaluation.modular.custody --state work/custody.json inventory --snapshot E:/_ryanDev/AI/research-loop-benchmark-20260912
python -m evaluation.modular.custody --state work/custody.json split --seed stage-1
```

This is an API and export boundary only. Directory separation does not prove OS,
container, cache, network, credential, or process isolation; those controls need
independent deployment verification.

## Cataloged benchmark sets and panel leases

The default required calibration set is DiscoveryBench and BLADE. A frozen panel
may require a larger set from `research_loop.modular.benchmarks.catalog`, but it
must retain those two core benchmarks. A signed calibration may declare a larger
applicable set; eligibility is calculated for the panel's exact frozen set.
Cataloging a source supplies no loader, evaluator, attestation, or automatic
qualification. New cataloged metadata remains quarantined until separate review
and adapter work exist.

Only `lease_panel(panel, calibration_receipt, protocol_digest)` can produce a
lease that custody will sign for panel verification. It compares every frozen
cell's benchmark/task identity, canonical custody group, inventory digest, split
digest, and validation domain with stored state. The raw lease API is metadata
compatibility only; even once consumed it cannot produce a signed panel receipt.
This is engineering enforcement, not evidence that independently produced
calibration materials or scientific acceptance exist.
