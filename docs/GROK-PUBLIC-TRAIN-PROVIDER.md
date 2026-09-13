# Public Grok TRAIN provider: bounded engineering contract

The v4 M4/M5 controller admits exactly two core TRAIN tasks, one replicate,
four useful-control combinations and five slots: 40 MAIN opportunities and
40 possible initial-title opportunities. It is a separate Grok provider;
v1/v3 keep their original Codex admission and protocol identities.

The default entry uses the pinned native v1.0.13 launch contract. Each
opportunity receives a fresh native home, profile and empty public directory.
The caller supplies an already-authorized login directory; auth.json is copied
opaquely without parsing or logging its content. Per-opportunity config bytes
are derived from the frozen slot output cap (2048, or 8192 for analysis_program)
and added to the immutable source manifest. Runtime logs and all config files
must remain available for replay. Never put auth.json into a public archive.

Each native opportunity retains its 60-second lifetime, zero retries, empty
actual tool inventory, grok-4.6 session/main identity, and same-process before
and after included-only billing/no-top-up gates. This is not an atomic account
spending lock. MAIN token limits are observed limits, not a tokenizer quote or
an all-call cost/capacity guarantee. Title usage and final settlement remain
unknown. Known MAIN usage is retained even when a response fails admission.

Before every later call and before scoring, replay checks the saved public
request, emitted native prompt/schema, original RPC request stream, raw native
response stream, receipt, reservation, session/prompt identities, exact config,
source pins, model, empty inventory, and original billing replies. Coherent
local substitutions must still agree with the independent native originals.
Replay faults durably close the ledger. An unresolved reservation on restart
also closes it. Failed and unstarted cells stay in the planned denominator.

Tests use a synthetic executable identity and replace only the OS process spawn
with the ACP peer. They retain default run_native_train and native_launch
validation; they do not bypass native startup or supply an accepted receipt.
The complete fixture still uses eight real Docker executions and an independent
scorer process. These tests establish engineering behavior, not actual Grok
execution or scientific effectiveness. No real provider call is part of this
repair or its frozen verification.
