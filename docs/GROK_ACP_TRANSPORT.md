# Grok ACP two-opportunity transport contract

The subprocess protocol engine is implemented and tested with synthetic peers.
`run_native` requires the explicit versioned `main-and-initial-title-v2` contract:
one main prompt and at most one initial title request opportunity. The earlier
single-total-request entry was blocked in commit 73197ce; that evidence remains
valid. This module is separate from the programme's operational ModelPort.

## What the engine checks

`SinglePromptACP` initializes a native JSON-RPC stdio session and creates a fresh
session with an explicit agent profile. It requires grok-4.6 as the selected
model, every observed same-session tool inventory to be empty, no MCP tools,
and the full exact built-in deny list. An empty CLI allowlist means inheritance;
`*` is not a supported wildcard for the source's exact/short-name comparison.

Immediately before a prompt it requests billing and the auto-top-up rule on
the same process. The included-only account snapshot requires unified billing,
SuperGrok, integer zero on-demand cap/used/prepaid balance, a current period,
and a successful response with no top-up rule. An RPC error cannot become an
empty result. Missing remaining percentage stays unknown and does not block
quota exhaustion from failing closed. This snapshot is not an atomic spending
lock and does not prevent another client from changing account settings.

It verifies frozen files, exclusively persists and fsyncs a reservation, then
sends one `session/prompt`. It never retries or purchases anything. Windows job
closure and Unix process-group termination stop descendants on completion,
rejection or timeout. Client requests for permissions/tools fail immediately.
Unexpected notifications, selected-model changes, nonempty inventories, extra
calls and result/session/prompt mismatches reject the result. A reservation
survives every uncertain dispatch. All stream files and prompt text stay in the
caller-designated private directory; the observer contains controlled status
codes, hashes, token counts and accounting rather than prompts or thoughts.

ACP accounting is parsed directly from native `_meta.usage`. Its `inputTokens`
already includes cache-read and cache-creation tokens. Reasoning is a subset
of `outputTokens`. One intermediate response usage must reconcile with the
terminal ledger and per-model totals. Known accounting is retained on rejected
results. Missing/partial cost remains unknown; reported cost is not an invoice.
The receipt separately states that wire output cap, side-call completeness and
actual additional settlement are not certified. It never translates ACP into
headless events or adopts the Codex transport type/policy.

## Why this contract includes the first-title opportunity

The installed executable is GrokCLI 1.0.13, SHA-256
`bf43dc75f5478a106eab1e86d422c963e4dbe9666cf14dab363733d27bf1e672`.
The public explanatory source is pinned to
`37949780c144e37df692e3d669051a21fec24f20`; binary/source equivalence is not proved.

The source has two different mechanisms:

* `features.turn_summary=false` and `features.title_refresh=false` disable
  post-turn side calls. The private native config and environment pin both.
* The first-title generator is independent. A normal prompt sends a
  `PersistenceMsg::ContentChunk`; persistence calls `SummaryGenerator::update`,
  which changes Idle to Done and starts a separate model request. Fresh
  persistence constructs it as Idle even with `sessionKind=headless`.
  `ManualTitleRenamed` updates remote synchronization and does not mark that
  generator done. Local/writeback storage modes both retain persistence.

See the pinned official
[prompt path](https://github.com/xai-org/grok-build/blob/37949780c144e37df692e3d669051a21fec24f20/crates/codegen/xai-grok-shell/src/session/acp_session_impl/turn.rs#L1072),
[persistence](https://github.com/xai-org/grok-build/blob/37949780c144e37df692e3d669051a21fec24f20/crates/codegen/xai-grok-shell/src/session/persistence.rs#L2154),
[first-title generator](https://github.com/xai-org/grok-build/blob/37949780c144e37df692e3d669051a21fec24f20/crates/codegen/xai-grok-shell/src/session/summary.rs#L41),
and [title request helper](https://github.com/xai-org/grok-build/blob/37949780c144e37df692e3d669051a21fec24f20/crates/codegen/xai-grok-shell/src/session/helpers/session_summary.rs#L128).

The versioned two-opportunity contract explicitly pins
`models.session_summary="grok-4.6"`: the summary client inherits primary retries,
and the helper makes one collect request with a requested 100 output-token cap,
at most 8,000 source-text bytes and a forced internal `session_title` function.
This is different from the main session's empty tool inventory. The helper
discards response usage; one main model call does not settle total side usage.
The old r5 private logs did not expose a recoverable title usage/cost receipt.
Neither an empty title nor process exit proves no title dispatch.

No supported switch was established that suppresses this first-title request
while retaining the required fresh session. The revised authorization budgets
that additional opportunity and preserves unknown side usage/cost and unknown
total calls/tokens/cost. Main prompt ledger counts never become totals for the
two opportunities. One generated-title update and its title-only session-info
update may be observed; no arbitrary tool activity is allowed. Both requests
use the included-only account route established immediately before prompting.

## Validation boundary

`tests/test_grok_acp_transport.py` exercises real fixture subprocesses: request
ordering and binding, paid fallback, malformed money and JSON, top-up errors,
tools, unknown messages, usage disagreement, unknown/partial costs, schema
checking, frozen-file changes, durable reservations and descendant cleanup.
`tests/test_label_isolation.py` remains required before any model operation.
Fixture success is engineering evidence, not a live ACP compatibility claim,
subscription settlement proof or scientific result. No benchmark inputs are
used by these tests.
