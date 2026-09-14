# Actual isolated Grok1.0.30 readiness observations

Both attempts used separate once-only launch reservations, source/config/exe
pins and fresh opaque copies of the authorized login. Global login metadata
stayed unchanged; no login contents or hashes are part of this archive.

r1:5.703s, initialize/session-new returned; no inventory had arrived before the
old immediate check. preprompt_inventory_missing,0 billing,0 prompt. Its exact
source is recovered from the pre-check disk-source ZIP where integration later
changed; every recovered byte matches the original envelope hash.

r2:10.109s, after the independently tested ordering fix. Two explicit empty-tool
inventory updates and same-process included-subscription/no-topup gate passed.
One MAIN prompt reservation/write occurred. Then an unsolicited response with
id skills-reload caused rpc_binding rejection. No terminal usage was observed:
MAIN usage and possible initial TITLE/all-settlement totals remain UNKNOWN.
The failed attempt is spent; it is not a zero-cost success or retryable slot.

The captured response was {"jsonrpc":"2.0","id":"skills-reload",
"result":{"result":{"reloaded":1}}}. The pinned public source in app.rs
contains a filesystem watcher injecting internal reload requests with this ID;
agent_ops.rs counts resident sessions when dispatching ReloadSkills. The
session_setup.rs implementation reloads skills from disk and updates the
baseline. Thus this may affect context, and is not treated as an ignorable
notification merely to pass readiness. Public source is not proven identical
to this binary. No third real probe or permissive handler is part of this archive.

Native raw streams, refreshed login copies and account RPC bodies remain at
their original private paths. This archive contains frame hashes/structure,
allowlisted closure, exact source/config bytes and reviewed public source.
No benchmark materials, validation access or scientific result was produced.
