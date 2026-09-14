"""Freeze the additional sealed-prefix replay checks without losing the red run."""
from pathlib import Path

prior = Path(__file__).with_name('archive_provider_observation_r1.py')
source = prior.read_text(encoding='utf-8')
source = source.replace('provider-observation', 'provider-seal-observation')
source = source.replace('for path in (__file__, work/', 'for path in (__file__, prior, work/')
source = source.replace("[('red-r1',4,4), ('green-r1',67,1), ('green-r2',67,0)]",
                        "[('red-r1',4,4), ('green-r1',71,0)]")
source = source.replace('build_provider_phase reviewed production 78481b6; no concrete correctness issue found',
    'build_provider_phase reviewed d7935c1; same terminal flag logic after fresh original inspection, no persistent cache')
start=source.index("(out/'README.md').write_bytes(b'''")
end=source.index("write(out/'archive-integrity.json',")
readme='''# One fresh original pass for sealed-prefix eligibility

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
'''
source=source[:start]+"(out/'README.md').write_bytes("+repr(readme.encode())+")\n"+source[end:]
exec(compile(source,str(prior),'exec'))
