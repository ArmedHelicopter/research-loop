# One fresh original pass for sealed-prefix eligibility

FrozenTrainProviderLedgerV2._verify_originals previously called inspect(), then
terminal(), which called inspect() again. Four red cases on f2f28d2 observed
[1,2,1,2] rather than [1,2] original replays in one check. d7935c1 derives the
identical terminal boolean from the state and native ledger already checked by
that fresh inspection. It does not cache results across calls, relax prefix or
terminal eligibility, or skip later appended originals.

The repaired source passed 71/71 with all 619 source hashes unchanged. Both
provider types are exercised through healthy original-prefix verification,
later call append, replaced original response or sealed bytes, and terminal
refusal without further dispatch. Existing phase, runtime event binding,
terminal accounting and label isolation regressions also passed. Independent
source review found the change consistent with the same original/state rules.

This is a bounded duplicate-I/O removal, not an overall throughput claim.
Every real model peer is replaced by an explicit synthetic fixture; no Grok/API
generation, extra purchase or validation acceptance occurred. Test failures,
exact pre-run source snapshots and all safe original fixture files remain
available. Keys, profile files, stores and caches are excluded explicitly; the
ZIPs are not standalone authenticated replay environments.
