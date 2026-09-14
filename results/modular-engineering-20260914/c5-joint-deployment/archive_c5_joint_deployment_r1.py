"""Reuse the audited frozen-campaign archiver with explicit C5 checkpoint pins."""
from pathlib import Path

prior = Path(__file__).with_name('archive_provider_observation_r1.py')
source = prior.read_text(encoding='utf-8')
source = source.replace('provider-observation', 'c5-joint-deployment')
source = source.replace('for path in (__file__, work/', 'for path in (__file__, prior, work/')
source = source.replace("[('red-r1',4,4), ('green-r1',67,1), ('green-r2',67,0)]",
                        "[('r1',79,20), ('r2',79,0), ('r3',82,0)]")
source = source.replace('build_provider_phase reviewed production 78481b6; no concrete correctness issue found',
    'c4_provider_port found re-enveloped acceptance replay on 049b323; re-reviewed fc11452 and found the repair closed')
start = source.index("(out/'README.md').write_bytes(b'''")
end = source.index("write(out/'archive-integrity.json')") if "write(out/'archive-integrity.json')" in source else source.index("write(out/'archive-integrity.json',")
readme = '''# Atomic C5 joint deployment engineering checkpoint

Each of nine component versions has its own source manifest, configuration,
state and TRAIN provenance. The complete bundle also binds parent, baseline,
P0 and resources. SQLite publishes every component, active pointer, grant and
independent acceptance consumption in one transaction. Task dispatch takes one
immutable whole snapshot; rollback restores the exact stored parent.

The first frozen attempt (133f8b4) passed 59/79: all 20 new tests stopped at an
incorrect dictionary passed to the compatibility API. 049b323 passes explicit
module names and passed 79/79. Independent review then found an authorization
replay gap: only the signed envelope was one-use. fc11452 additionally consumes
the original acceptance_digest, reconstructs historical consumption on reopen,
and rejects re-enveloped reuse. The final check passed 82/82, with all 621
source hashes unchanged. Independent re-review found that repair closed.

The checks include real SQLite transactions and two competing processes, a
failure after each of nine component writes, transaction-tail failure, source
drift, untrusted signatures, target/stage/parent substitution, exact rollback,
restart, and a running task pinned across a concurrent activation. An actual
RunSession request receives all nine synthetic component configuration/state
payloads before activation, after activation, and after rollback.

Build bytes and deployment grants are synthetic. This is not execution of all
nine module algorithms, actual TRAIN selection, independent benchmark scoring,
calibration, V_final allocation, or scientific acceptance. The grant issuer is
still an upstream acceptance-service contract; this store cannot mint approval.
No real model/API calls, validation data, extra fees or deployed user workload
occurred. Whole-snapshot storage is not atomic publication to external services.

Exact tested source bytes were archived before each run and matched to its
original before manifest. First failures remain here. Explicit exclusions cover
keys, profile material, stores and caches; these are not standalone authenticated
replay environments. Complete original local paths remain in the check records.
'''
source = source[:start] + "(out/'README.md').write_bytes(" + repr(readme.encode()) + ")\n" + source[end:]
exec(compile(source, str(prior), 'exec'))
