# ACP diagnostic wrapper receipt audit r1

## What is known about the launch chain

The only native diagnostic launch was issued through the tool command
`python run_acp_initialize_only.py` with `yield_time_ms: 30000`.  The tool
returned after 30.2 seconds with empty output and without a session handle.
The helper's own deadline was 20 seconds.  Its timeout branch then invokes
`taskkill /PID <child> /T /F` with no subprocess timeout and calls a second
`communicate(timeout=10)`.  Its nominal worst path is therefore at least 30
seconds before writing `receipt.json`, with no allowance for process startup,
`taskkill`, scheduling, or filesystem finalization.  This overlaps the outer
tool yield boundary.

The helper uses `subprocess.Popen` at lines 140--143 with stdin/stdout/stderr
pipes and then stores every decisive fact only after both communicate calls:
PID at line 160, raw stream files at lines 154--157, and `receipt.json` at
line 179.  None was durable immediately after launch.  The existing
`receipt.incomplete.json` is a later metadata salvage, not a primary process
receipt; it must remain immutable.

There was no preserved PowerShell wrapper PID or tool-side process handle.  A
subsequent local snapshot observed a Python helper process with PID 39236,
started at `2026-09-15 10:24:44 +08:00`; its executable path was unavailable.
That process later disappeared.  The runtime home contains a memtrace filename
ending in `59036`, created at `2026-09-15T02:25:11.600Z`, but a filename alone
does not prove a child PID, executable path, parent relationship, or cleanup
outcome.  It must not be promoted to a process identity.

The helper source contains the owned-tree cleanup instruction, but there is no
persisted taskkill exit code, completion timestamp, or child-tree listing.
Consequently, execution of that cleanup is unproven.  The current process scan
found no process whose executable path is the pinned Grok executable and no
process whose command line names the diagnostic directory (apart from the scan
command itself).  This is a current absence observation, not evidence that the
earlier child was cleanly closed.

## Why the final receipt was lost

The durable facts support a wrapper-lifetime race, not a unique internal cause:

1. the outer 30-second yield and the helper's 20+10-second timeout path had no
   margin;
2. launch/child identity, partial streams, and cleanup state were retained only
   in helper memory until after the second communicate; and
3. the timeout cleanup `taskkill` was unbounded, so it could extend that path.

The safe runtime log confirms the single request reached `agent initialized`
and `auth method selection`; it cannot establish which process-owned handle
was later closed.  No model, prompt, session, evaluator, VAL, or Docker request
was constructed by the helper.  Usage and settlement remain unknown.

## Narrow robustness fix for any future diagnostic

Use a two-layer supervisor whose maximum runtime is comfortably below the
calling tool's wait boundary.  Immediately after `Popen`, write and fsync a
`launch.json` containing child PID, supervisor PID, safe command hash, start
wall/monotonic times, and inherited-handle policy.  Stream stdout/stderr into
private files as they arrive rather than waiting to materialize them after
`communicate`.

At the deadline, write and fsync `timeout-entered.json`; run owned-tree closure
with its own short timeout; write its return/exception; then poll the exact
recorded PID and recorded descendants for a bounded grace period.  Always write
`final.json` in a `finally` block with `finalization_incomplete` when necessary.
Reserve outer-tool margin for that finalization (for example, a 15-second child
deadline plus at most 5 seconds for closure/finalization under a 30-second tool
yield), or use a supervising process whose completion marker is independently
durable.  Never infer closure from process-name lookup; require the recorded
PID/tree query and persisted cleanup result.

This is instrumentation guidance only.  It authorizes neither a rerun nor a
change to the closed M4/M5 or diagnostic allocation.
