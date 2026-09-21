# Read-only review 5: ordinary native version cache

Review scope: version_cache.py, check_version_cache.py and S-native-r1 original checks. This is the fifth review package, not an independent scientific sample.

No definite S defect was found within the declared single-controller/public-mutation contract. Whole-cache invalidation is conservative but consistent with public contexts carrying global ledger digests. Old event sinks and failure callbacks are preserved; failed writes poison the cache. Native state can mutate before a failing persistence callback, so fail-closed behavior is necessary. Validation entries are never retained. Rebinding and displaced observer hooks are guarded.

A test gap concerned a nonempty previous failure callback. The implementation looked correct; an additional executed check is now preserved at S-native-r1/failure-callback-check.json: old callback called exactly once, stale reuse rejected, and close restored both original callbacks.

The six saved-request tests alone did not measure a continuously attached cache across real updates. RBS-replay-r1 subsequently did so, with persistent native events, observer binding and maintenance costs. S recorded zero hits in the actual sequences. Warm probes remain separate.

AND groups are unsupported by the native reference. This is a reference expressiveness gap, not an observed S mismatch, and is not counted as a passed AND implementation.
