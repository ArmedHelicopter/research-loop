# M6 durable event provenance

`RunSession` registers each Q8/Q8.4 trace event immediately after the original
trace write and fsync. A reservation descriptor therefore exists before the
provider is called, and returned items remain recorded if a later request fails.
Q8.4 attaches a second observer directly to its separate source evidence ledger;
these records do not enter the scientific evidence ledger or bypass P0.

Every descriptor binds the original event, stream position, activation, exact
writer and bridge code snapshots, previous stream item and enclosing trace.
The reader requires exact source/descriptor correspondence and ordering. C4
also replays its actual source policy; its earlier prediction/review calls are
excluded from this policy's scope, while later calls remain subject to failure
checks. Other Q8 policies currently receive event integrity checks; their own
existing policy verifiers remain necessary for semantic acceptance.

An audit write failure terminalizes the session and preserves an independent
failure marker. Partial journals remain inspectable and cannot pass complete
coverage acceptance. Unknown external resource costs remain unknown.

The original M6 helper-only r1 and final-collection r2 checks remain evidence of
those exact versions, not evidence of immediate durable registration. The new
v2 event stream replaces that unmerged bridge. Root development checks exercised
actual retrieval and Q8.4 calls, disabled M6, provider failure, coherent
catalogue/parent/order forgery, missing-file read-only behavior, and failure before
provider I/O. Frozen combined stage evidence is required separately.
