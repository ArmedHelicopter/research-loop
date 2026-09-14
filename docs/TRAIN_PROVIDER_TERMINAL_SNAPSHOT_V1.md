# Terminal accounting after provenance failure

The closed core provider wrappers expose `failure_snapshot()` only after an
existing durable terminal fault. The method never calls `inspect`, performs a
native retry, or produces eligible call views or an original seal.

Its `public-train-provider-terminal-snapshot-v1` record always declares
`current_originals_verified=false`, `score_eligible=false`, and
`current_main_usage_complete=false`. It retains the last complete original
inspection's scalar observation in a separately pinned immutable checkpoint.
The observed call count and known token scalar are **historical lower bounds**;
unknown unobserved opportunities and current totals remain explicit. A missing
or changed checkpoint yields unknown lower bounds, never unchecked cached usage.

The snapshot binds preserved pre-stop `fault-state.json` and
`fault-native-ledger.json` bytes through an explicit allowlist. It does not scan
login homes, auth bodies, memory traces, or arbitrary native directories. TITLE
and all-opportunity tokens and additional-charge settlement remain unknown.

Controllers may persist this snapshot in a distinct aborted-attempt receipt to
retain every planned denominator and permit cleanup. They must not pass it to
scoring or interpret the history as current verified provenance. Normal
`inspect`, `usage`, `calls_since`, and `seal` still reject unresolved original drift. A
successful prefix remains verifiable after legitimate append; corrupting an
original invalidates its current verification even though prior observations
remain inspectable as historical evidence.

For an adapter-state or ledger-disk mismatch, the stop operation preserves the
corrupt bytes before writing its terminal marker from the retained in-memory
record. If those resulting originals replay, an audit seal can still be written;
the durable terminal state makes its score eligibility false. A terminal snapshot
itself never triggers this replay and always marks current originals unverified.
