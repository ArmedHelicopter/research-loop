# Post-auth model-state source follow-up r2

## Source acquisition record

The pinned public `chat_modes.rs` URL was retrieved at commit
`bc7f02eddd3d84085849dc19ed216f11c23b0571`:

`https://raw.githubusercontent.com/xai-org/grok-build/bc7f02eddd3d84085849dc19ed216f11c23b0571/crates/codegen/xai-grok-shell/src/agent/chat_modes.rs`

Its lines 17--24 define `GROK_CHAT_MODE` but make
`process_chat_mode_enabled()` unconditionally return `false`; comments say
release builds hard-off the branch so it cannot be enabled through the
environment.  The chat-specific `model_state().await` path therefore cannot be
selected by a runtime environment switch in this saved release source.

I requested the exact pinned `mvp_agent` directory listing from the public
GitHub contents API before choosing any further path.  GitHub returned HTTP 403
rate-limit exceeded.  No guessed path was fetched and no additional source file
was downloaded.  The requested implementation of synchronous
`self.model_state(None)` and its dependencies is therefore not located by this
study.

## What follows from the available saved source

Saved `acp_agent.rs` calls synchronous `self.model_state(None)` after auth
method selection because the chat condition is hard-off.  The observed
post-selection stall cannot be assigned to the disabled async chat-mode fetch,
its `RwLock`, or its `tokio::Mutex`; those locks exist only inside the disabled
branch.  The prior spawned MCP/catalog/announcement/heap calls are still not
syntactically awaited by `initialize`.

This does not show that synchronous `self.model_state(None)` is harmless or
that the installed binary has the same code.  The public source/binary
correspondence remains unestablished, and no exact `model_state(None)` lock or
callback graph was inspected because the authoritative directory listing was
unavailable.  A saved-source deadlock claim would be unsupported.

## Repair implication

There is no documented runtime environment/config switch in the acquired source
to toggle the disabled chat path, so no supported billing-neutral configuration
repair is established.  The concrete next repair remains robust ACP initialize
instrumentation on a separately allocated supported CLI invocation: persist the
native result/session id, capture safe milestones around the response boundary,
and join the session.  It should not refresh auth, dispatch a model, or retry
the closed M4/M5 run.

## Pins

* local saved `acp_agent.rs` SHA-256:
  `4D4689029CBCAADCA67C5C3561698F37F5CB02342098E5A7B9DC8FCC1F2BD56E`
* local saved `chat_modes.rs` was inspected through the pinned raw URL above;
  this follow-up did not save another copy or assert a local file hash.
* GitHub contents listing endpoint:
  `https://api.github.com/repos/xai-org/grok-build/contents/crates/codegen/xai-grok-shell/src/agent/mvp_agent?ref=bc7f02eddd3d84085849dc19ed216f11c23b0571`
  — HTTP 403 rate limit, no listing retained.
