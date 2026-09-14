# Atomic C5 joint deployment engineering checkpoint

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
