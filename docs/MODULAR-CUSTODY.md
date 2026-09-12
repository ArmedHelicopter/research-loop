# Modular custody

`evaluation.modular.custody` inventories only filenames, paths and SHA-256 values.
It does not parse task text, references, labels or CSV cells. DiscoveryBench keeps
its `synth|real` and `train|dev|test` mapping. BLADE has no such split in the
local snapshot; directories without the complete public scoring triplet are
quarantined.

Historical exposure is explicit: the documented DiscoveryBench synth/test
selection and BLADE formal plus development tasks are train-only. This does not
erase their historical validation role; a new protocol must record any use as
training or diagnostics. Unknown exposure is quarantined rather than guessed
clean.

The broker merges items sharing a source-group label or a file hash, then assigns
whole merged groups deterministically. It exports only `DataIdentity(domain=train)`
objects. A validation lease is bound to a frozen split and panel digest and turns
consumed permanently after use.

Example:

```text
python -m evaluation.modular.custody --state work/custody.json inventory --snapshot E:/_ryanDev/AI/research-loop-benchmark-20260912
python -m evaluation.modular.custody --state work/custody.json split --seed stage-1
```

This is an API and export boundary only. Directory separation does not prove OS,
container, cache, network, credential, or process isolation; those controls need
independent deployment verification.
