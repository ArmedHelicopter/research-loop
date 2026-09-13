# Grok CLI subscription transport contract review

Checked 2026-09-13. **No additional model generation occurred in this review.** Read-only native ACP billing requests and one prompt-free session setup were performed. Original account configuration and credentials were not inspected or changed. r5 remains one successful transport generation with an incomplete tool-isolation contract.

## Findings and current decision

A corrected no-tool transport is supported by the installed binary: the explicit 33-name denylist in `candidate-agent-profile.json` produced two ACP `available_commands_update` notifications whose `_meta.tools` are empty. Session setup succeeded without a model prompt. Evidence: [tool-preflight-receipt.json](grok-subscription-contract-review-r1/tool-preflight-receipt.json). Do not substitute an empty allowlist, a wildcard denylist, or an empty curated tool configuration.

The latest billing snapshot supports using the included subscription route with paid fallback unavailable under the documented account model. Missing usage percentage need not block a bounded request: exhaustion must be recorded as a failed attempt without retry or purchase. This relies on the service honoring its account billing configuration; no local or per-request spending lock was found. It does **not** establish a zero-dollar model tariff or prove the settlement of r5's reported cost.

## Why r5 exposed tools

- Windows did preserve the empty argument. The exact frozen Popen argument list round-trips through native `CommandLineToArgvW`; a real child launched using the same Python subprocess mechanism also receives the empty string. This verifies the launch construction, not a historical process-level capture. See [windows-empty-argv-verification.json](grok-subscription-contract-review-r1/windows-empty-argv-verification.json).
- Official source `headless/cli.rs:134-142` maps an empty comma list to `None`; `headless.rs:918-920` uses it for `--tools`. Thus `--tools ""` supplies no override and leaves the default tools. [Source](https://github.com/xai-org/grok-build/blob/37949780c144e37df692e3d669051a21fec24f20/crates/codegen/xai-grok-pager/src/headless/cli.rs#L134).
- `send_available_commands_update` obtains names from `bridge.tool_definitions()`. They are registered session definitions, not a static global catalog. Therefore the 21 r5 names are material; zero actual tool calls only proves none were invoked. [Source](https://github.com/xai-org/grok-build/blob/37949780c144e37df692e3d669051a21fec24f20/crates/codegen/xai-grok-shell/src/session/acp_session_impl/session_setup.rs#L250).
- Deny entries match an exact full tool id or its short name. `*` is not a tool wildcard. `dontAsk` still allows built-in read-only operations unless denied. Hooks fail open on errors and are unsuitable as the sole guard. [Tool matching](https://github.com/xai-org/grok-build/blob/37949780c144e37df692e3d669051a21fec24f20/crates/codegen/xai-grok-agent/src/config.rs#L1200); installed docs `22-permissions-and-safety.md:142` and `10-hooks.md:173-190`.
- The builder rejects `injectDefaultTools:false` combined with an empty declared `toolConfig.tools`. Explicit deny entries are applied after optional tool injection. [Builder](https://github.com/xai-org/grok-build/blob/37949780c144e37df692e3d669051a21fec24f20/crates/codegen/xai-grok-agent/src/builder.rs).

The source snapshot is pinned to commit `37949780c144e37df692e3d669051a21fec24f20`. No release tag establishes equivalence to installed 1.0.13; the separate installed-binary metadata probe confirms the proposed denylist works on this host.

## Billing evidence and meaning

The native `grok agent stdio` process accepted `initialize`, `_x.ai/billing`, and `_x.ai/auto-topup-rule` with no `session/new` or prompt. These are read-only GET handlers using the CLI's own authentication. The review never extracted credentials. [Handler source](https://github.com/xai-org/grok-build/blob/37949780c144e37df692e3d669051a21fec24f20/crates/codegen/xai-grok-shell/src/extensions/billing.rs#L133).

At 2026-09-13 14:06:24 UTC, the response showed:

| Field | Value | Interpretation |
|---|---:|---|
| subscription_tier | SuperGrok | Existing subscription account |
| isUnifiedBillingUser | true | Shared usage pool model |
| onDemandCap.val | 0 | Zero cents of configured legacy on-demand allowance; not an unlimited sentinel in reviewed client model |
| onDemandUsed.val | 0 | No recorded on-demand spend in this snapshot |
| prepaidBalance.val | 0 | No purchased fallback credits |
| auto-topup result | `{}` | Successful response with no rule; known disabled rule state under client semantics |
| creditUsagePercent | absent | Remaining percentage unavailable; do not synthesize 100% remaining |
| currentPeriod | Sep 13 08:25:07 UTC to Sep 20 08:25:07 UTC | Weekly period |

Evidence: [billing-readonly-receipt.json](grok-subscription-contract-review-r1/billing-readonly-receipt.json). `AutoTopupFetch::Resolved` explicitly represents either a real rule or disabled when the backend reports none. The credit display distinguishes unified prepaid billing from legacy on-demand billing, so `onDemandCap=0` alone is insufficient; combine it with unified-account status, zero prepaid balance, and successful no-rule response. [Client semantics](https://github.com/xai-org/grok-build/blob/37949780c144e37df692e3d669051a21fec24f20/crates/codegen/xai-grok-pager/src/views/credit_bar.rs).

Official policy says Build shares the weekly included pool, paid features pause at exhaustion, and paid continuation requires extra credits, an upgrade, or configured Auto Top Up. Therefore the combined snapshot supports fail-closed exhaustion without requiring a known remaining percentage. Backend enforcement was not stress-tested by exhausting quota. [Official FAQ](https://docs.x.ai/grok/faq#what-happens-when-i-reach-my-weekly-limit).

## Concrete next transport contract

1. Keep r5's isolated child HOME/USERPROFILE/APPDATA/LOCALAPPDATA/GROK_HOME and clean working directory; preserve empty external discovery, disabled memory/workflows/subagents/web/managed MCP, and an allowlisted environment without API keys or custom providers.
2. Refresh the two read-only billing methods immediately before dispatch. Accept only a successful typed snapshot: unified subscription, explicit zero on-demand cap and prepaid balance, successful auto-topup response with no rule or `enabled:false`. Missing percentage is allowed and remains null. Fail before model dispatch on request errors, malformed billing, unknown/positive paid fallback, or an enabled top-up rule. Do not mutate account settings.
3. Use the exact [candidate profile](grok-subscription-contract-review-r1/candidate-agent-profile.json). The executable agent file is [transport-no-tools.md](grok-subscription-contract-review-r1/transport-no-tools.md). For headless mode use `--agent <absolute agent-file>` and `--disallowed-tools <comma-joined disallowedTools from that file>`; remove `--tools ""`. Retain `--no-subagents --disable-web-search --deny MCPTool --permission-mode dontAsk`. Optional defense adds explicit `--deny Bash --deny Read --deny Grep --deny Edit --deny Write --deny WebFetch`.
4. For a true **upfront tool gate**, native ACP permits `session/new` with `_meta.agentProfile`, then verification of `available_commands_update._meta.tools == []` **before sending `session/prompt` in that same session**. That metadata step is already verified. Headless `available_commands` is an audit signal after launch, not a guarantee that a host can kill before inference starts. Never call a post-dispatch parser check an upfront enforcement barrier.
5. Freeze executable/config/profile/prompt hashes, correct TOML `[model."grok-4.6"]`, requested `max_completion_tokens=128`, `max_retries=0`, one turn/request reservation, and 60-second wall cap. The prompt-free ACP check did not test the generation-time headless port; keep that distinction in any subsequent separately authorized receipt.
6. Reject any nonempty runtime tools event or any tool event; terminate without retry. Preserve partial output, known tokens, accounting and failure denominator. Do not silently fall through to another model, API key, purchased credits or top-up. Refresh billing after completion to reconcile on-demand/prepaid changes; this is accounting, not the pre-call guard.
7. Preserve actual server cost separately from settlement: r5 reports $0.00644164 and 9,381 tokens; zero current on-demand use is supporting account evidence, not a per-request invoice. Record unknown costs/settlement as null. A quota failure remains an executed failed attempt, never a reason to buy or repeat automatically.

Known non-generation checks here: billing metadata in 4.391 seconds; tool session metadata in 9.078 seconds; Windows argv verification. No benchmark or validation data was opened. Raw ACP responses and stderr remain private; archive only named sanitized receipts, candidate profile, report, and their hash manifest.
