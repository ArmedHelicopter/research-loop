# C5 checkpoint-plan cache evidence stage

The cache precomputes only immutable planned checkpoint rows at executor construction. It does not cache filesystem, frozen-protocol, dependency, provider, allocation, or status observations. This stage contains synthetic retained test evidence only.

The `actual-history-target.pstats` profile is incomplete: it was deliberately stopped after 107.661 seconds, so it is a bounded cost observation and not a passing test result. No original profile helper exists; its separately labeled command record is reconstructed.

The full-case ZIPs preserve each selected synthetic test directory, including checkpoint, plan/protocol, stage/provider-ledger, trace, input-binding, and cached-status evidence. Fixture-private filenames are retained because these cases use synthetic providers and no actual credentials/API authentication were present. The narrower runtime ZIPs are derivative extracts of the full cases and are not independent samples. The stage does not make a full-grid performance claim and did not change live immutable-record-runtime source.
