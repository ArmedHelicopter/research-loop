# Single authless Grok 1.0.30 initialize diagnostic

2026-09-14. One native launch closed after **60.171 seconds** with a timeout,
zero stdout/stderr bytes and no parsed initialize response. No model, session,
authentication or billing RPC was dispatched. The fresh home initially held
only the isolated config; no auth path appeared. The observed context remained
valid. The process Job and retained process handle were closed, with creation
FILETIME checked against that same handle. No retry was issued.

This establishes that the observed stall can also happen without supplied cached
authentication. It does not identify the upstream cause or establish model
availability. Earlier authenticated runs include both timeouts and one protocol
1 response followed by rejected notifications. Those observations are retained;
the trials are not a contemporaneous randomized comparison.

The root reviewed the interrupted subagent's unexecuted draft. Before native
use it added a metadata-only new-auth-path guard, explicit process-handle closure
and the correct context-observer exception type. The original engine digest is
recorded separately. The 261-byte initialize request, native argv, timeout,
held-stdin behavior and response parser were preserved.

Four synthetic checks passed before launch: two delayed-peer timeouts, a response
followed by a notification, and detection of a new synthetic auth path. All
owned process Jobs/handles closed and exactly one initialize write was recorded
per check. These checks do not demonstrate real Grok generation.

Public evidence in this directory:

- `envelope.json`: source/config/executable pins and frozen native bounds.
- `synthetic-checks.json`: exact helper sources and four check outcomes.
- `native-reservation.json`: one-use launch reservation.
- `closure.json`: typed native result and cleanup evidence; SHA-256
  `bcf04278f8309b6d012fe28eedf1f503491aae107b2fb933647ebd3435ae7ddd`.

Raw streams remain private. No existing credential file was opened, copied,
hashed or modified. Settlement and model usage remain unknown; zero dispatched
model RPCs are not represented as a verified billing settlement. No Daybreak or
paid API route was introduced. The repository's included-subscription model
readiness gates remain unfulfilled by this diagnostic.
