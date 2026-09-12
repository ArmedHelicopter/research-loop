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
objects. A validation lease is bound to a frozen split, panel digest, and exact
arm schedule; it turns consumed permanently after use. The CLI also supports
`attest`, `export`, `qualify`, and `consume` so a child process cannot bypass
those checks.

Example:

```text
python -m evaluation.modular.custody --state work/custody.json inventory --snapshot E:/_ryanDev/AI/research-loop-benchmark-20260912
python -m evaluation.modular.custody --state work/custody.json split --seed stage-1
```

This is an API and export boundary only. Directory separation does not prove OS,
container, cache, network, credential, or process isolation; those controls need
independent deployment verification.
