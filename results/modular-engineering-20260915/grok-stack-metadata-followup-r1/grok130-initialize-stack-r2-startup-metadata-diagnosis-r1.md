# Closed r2 initialize metadata diagnosis

## Scope and custody

This is a read-only extraction from the closed r2 originals.  It does not
rerun Grok, CDB, a model, or an account/API operation, and it does not modify
`WORK/grok130-initialize-stack-r2`.

The public structural extraction is
`WORK/grok130-initialize-stack-r2-metadata-v3.json`.  It was derived from
private stdout SHA-256
`750bfcc11ecbb22dec5f775c892a14c9d2524ce5fd4a9fccbc50e6b3e5f033d0` and
private CDB stdout SHA-256
`489e2f51157f58f5883038537505ac5106123a64fb34e6860b81df7ab0eab9ec`.
It emits no parameter values, JSON body text, stack addresses, arguments, or
raw stack lines.

The r2 closure records one `initialize`, zero `session/new`, `authenticate`,
`session/prompt`, billing, or auto-topup writes; no server request; unchanged
source/context/auth metadata; process-tree closure; and no model usage or
settled charge.  It records the valid-shaped response at 17.454 seconds and
the conditional CDB capture at 15 seconds.  This timing correlation does not
establish that debugger suspension caused the response.

## JSON-RPC structural result

Private stdout contains seven valid JSON-RPC frames: one response followed by
six notifications.  The response has only `_meta`, `agentCapabilities`,
`authMethods`, and `protocolVersion` result keys.  The notification sequence
is four identical `_x.ai/models/update` frames, one `_x.ai/settings/update`,
and one `_x.ai/announcements/update`; their frame digests and parameter-key
sets are retained in the public metadata JSON.  No frame is a server request.

The init-only harness necessarily records `unexpected_notification` because
its loop rejects every `method` frame at
`WORK/grok130-initialize-stack-r2/init_engine.py:118-120`; the queued frame
after that rejection produces `extra_captured_frame` at lines 152-156.  Thus
those two faults describe the diagnostic harness's intentionally narrow
acceptance rule, not an RPC error response or a server request.

The production ACP transport at pinned integration commit
`98eae2811b929d2d2f0eaf2863711280cf753ce5` explicitly recognizes these
startup method families: `_x.ai/models/update` is validated against its
selected model at `integration/research_loop/modular/grok_acp_transport.py:447-448`,
while `_x.ai/settings/update` and `_x.ai/announcements/update` are treated as
advisory startup metadata and not copied to the observer at lines 484-485.
The closed extraction deliberately does not reveal `currentModelId`, so it
does **not** establish that the four model updates would meet the production
model-value check.  It does establish that their method names and parameter
key shapes belong to a source-recognized startup path.  No gate has been
relaxed from this observation.

The inspected source byte pins are r2 `init_engine.py`
`73b4d0693ff3ded68a7e8a4f1c710c32c1e4206a06d53e2f28c45a45fc71bdc7` and
integration `grok_acp_transport.py`
`f736d68218e49bf90fa6ead447097d8366d3827932bea5565c854e71d07aa855`.

## CDB structural result

The capture exited 0 in 1.531 seconds, parsed 400 standard frames under its
capture parser, and observed the owned child alive after `qd`; this is not an
independent detach/resumption proof.  The independent sanitizer parsed 399
stack-frame lines from private stdout and found module counts: `grok` 210,
`ntdll` 113, `kernel32` 40, `kernelbase` 35, and `mswsock` 1.  It found two
recognized operating-system wait frames, both `single_object_wait`, on CDB
thread 36: `ntdll!ntwaitforsingleobject` and
`kernelbase!waitforsingleobjectex`.  The report exposes no other function
labels, so it cannot identify a precise application lock owner or blocker.

`-pv` may briefly suspend the target.  The stack proves only this bounded
snapshot and does not explain the earlier timeout or establish a durable
native startup fix.  Any production transport change would need an isolated
contract test that validates the model-update values and preserves all strict
notification, session, billing, and source-pin checks.
