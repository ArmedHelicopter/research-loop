# ACP Option/default and lifecycle review

This review follows the two preserved native attempts. It introduces no model
request. Source is pinned to `xai-org/grok-build` commit
`37949780c144e37df692e3d669051a21fec24f20`. Source and installed executable have
not been proved identical; an unrecognized meaningful event still rejects the
transport. The previous attempts remain rejected with their original receipts.

| Surface | Wire requirement | Transport decision |
| --- | --- | --- |
| `initialize.protocolVersion` | Required integer | Exactly 1, boolean rejected. |
| New session ID and selected model | Session ID required; model capability data may vary by ACP peer | This pinned native route requires canonical UUID and selected grok-4.6 before a prompt. |
| `available_commands_update` | Available commands list; Grok `_meta.tools` extension | Require an actual empty tool list for this same session before sending. Unknown/missing inventory does not mean empty. |
| Queue changed | Required session and entries; running ID/text/kind/combined-text fields optional | At most our one pending prompt or our current running prompt. No combined prompts, other IDs, extra entries or unknown fields. Text remains private. |
| Response started | Model and message ID optional; input/cache counters default u64 | If present, model must match and counters must be nonnegative integers. At most one boundary. |
| Reasoning completed | Signature optional | Missing/null/string accepted and kept private. No reasoning enters observer. |
| Response completed | `message_id`, `stop_reason`, `usage`, `signature`, `stop_sequence` all optional | Exactly one response boundary required by this experiment. Missing stop/usage is allowed. Present usage must reconcile with separately complete bound terminal accounting. Intermediate stop cannot substitute for terminal `end_turn`. |
| Turn completed | Prompt ID and stop reason required; result/error/usage/duration optional | Require current prompt and `end_turn`, no typed error. Preserve parseable usage when present. Its absence does not invent zero usage. |
| `_x.ai/session/prompt_complete` | Session ID, prompt ID, stop reason and nullable result; error/cancellation/turnId added conditionally | Accept one bound ordinary `end_turn` notification. Reject cancellation/error/unknown fields. It does not substitute for the JSON-RPC response. No turnId was requested. |
| RPC `_meta` identifiers | Session/request/prompt/model IDs and total context tokens required | Match session and requested prompt UUID (`requestId=promptId` in source), model and integer context count. |
| RPC `_meta` scalar input/output/cache/reasoning | Optional last-call counts | Do not require them or add them to whole-prompt totals; validate their types when present. |
| RPC `_meta.usage` | Optional whole-prompt ledger | This experiment requires a valid ledger to accept a main response and check its main-call/output bounds. If absent, reject with unknown main aggregate, retaining any valid intermediate usage. |
| RPC structured output | Optional unless requested/produced; error is separate | This experiment requested a schema, so require validated structured JSON matching emitted text. |
| RPC tool overrides | Optional backend-hosted search override | Reject presence in this no-search contract. Empty search options can enable unbounded hosted search, so do not treat them as harmless empty tools. |
| RPC completion/cancellation fields | Optional, absent for normal completion | Reject presence; they indicate no-run or early termination. |
| PromptUsage counters | Default unsigned integers; serialized as fields | All present token counters must be typed and internally consistent. Input includes cache; reasoning is part of output. Require main `numTurns=1`, `modelCalls=1`, one matching accounting model. |
| PromptUsage cost/incomplete flags | Cost optional; partial/incomplete omitted when false | Missing cost is unknown. Partial/incomplete never becomes zero cost. Independently parseable counts survive rejection. |

The optional intermediate stop was the second attempt's failure: native emitted
`response_completed` with only `sessionUpdate`, `usage`, `signature`. Its known
response counters were 1,360 uncached input, 896 cached input, 44 output including
35 reasoning, total 2,300. The client terminated before a final prompt response;
these are partial response counters, not a complete main/title settlement.

The review also identified the separately emitted prompt-complete notification
before the RPC result. It now has explicit binding and ordinary-success checks.
The native producer sets `requestId` equal to supplied `promptId`; optional
last-call scalar fields and missing intermediate usage are not required merely
because fixtures happened to contain them.

After rejection, no more request is sent. The reader retains bytes already
delivered before process-tree closure; a bounded stream (8 MiB total, 1 MiB
frame cap) is inspected for typed usage in RPC `_meta.usage`, durable turn usage,
and `error.data.promptUsage`. This recovery cannot clear a fault or accept an
output. Unknown and tool events remain in the private raw stream. Public
recovery exposes only known scalar accounting and explicit binding/completeness
status; provider error messages and model text stay private.

Remaining deliberate restrictions are not claims that all ACP peers require
them: same-session empty inventory, pinned model, one observed response
boundary, complete main ledger for acceptance, requested output schema, and no
arbitrary tools/retries/unknown work belong to this experiment. First-title
usage and all-opportunity totals remain unknown under the explicit
main1+initial-title1 contract.

Source anchors:

* [Notification fields and accounting](https://github.com/xai-org/grok-build/blob/37949780c144e37df692e3d669051a21fec24f20/crates/codegen/xai-grok-shell/src/extensions/notification.rs#L80), including `ResponseCompleted` at lines 1042–1058.
* [Typed prompt response metadata](https://github.com/xai-org/grok-build/blob/37949780c144e37df692e3d669051a21fec24f20/crates/codegen/xai-grok-shell/src/agent/mvp_agent/mod.rs#L416).
* [Prompt-complete producer](https://github.com/xai-org/grok-build/blob/37949780c144e37df692e3d669051a21fec24f20/crates/codegen/xai-grok-shell/src/agent/mvp_agent/acp_agent.rs#L1501) and [payload builder](https://github.com/xai-org/grok-build/blob/37949780c144e37df692e3d669051a21fec24f20/crates/codegen/xai-grok-shell/src/session/turn_completion.rs#L37).
* [Queue producer](https://github.com/xai-org/grok-build/blob/37949780c144e37df692e3d669051a21fec24f20/crates/codegen/xai-grok-shell/src/session/acp_session_impl/prompt_queue.rs#L429).
* [Usage attached to errors](https://github.com/xai-org/grok-build/blob/37949780c144e37df692e3d669051a21fec24f20/crates/codegen/xai-grok-shell/src/sampling/error.rs#L330).
* [Hosted search overrides](https://github.com/xai-org/grok-build/blob/37949780c144e37df692e3d669051a21fec24f20/crates/codegen/xai-grok-sampling-types/src/tool_overrides.rs#L286).
