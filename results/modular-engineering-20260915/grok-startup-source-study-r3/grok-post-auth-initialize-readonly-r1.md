# Post-auth initialize source boundary r1

## Saved-source finding

After the last retained `auth method selection` log, saved
`acp_agent.rs` performs `set_auth_method` and then synchronous calls to
`sync_process_static_api_key`, cwd/hostname capture, and construction of an
empty MCP-server vector.  It schedules MCP/catalog/announcement/heap work with
spawn calls.  Those scheduled calls are not syntactically awaited here.

The only explicit remaining await before the initialize response is:

```rust
if process_chat_mode_enabled() {
    self.chat_modes.model_state().await
} else {
    self.model_state(None)
}
```

The response is then constructed synchronously.  The saved source therefore
does not contain another explicit awaited auth or refresh operation after auth
method selection.  It leaves three source-level possibilities: the conditional
chat-mode await when enabled, a synchronous call that blocks despite not being
an `await`, or behavior absent from the saved source.

## Recorded mode evidence

The retained initialization-location finding says its related saved source
shows the release chat-mode branch disabled.  It also records that successful
and failed profiles had the same safe auth state through selection.  No retained
safe log exposes a definitive `process_chat_mode_enabled` value for the
installed binary.  Review-r2 reached startup complete after selection; actual
M4/M5 and initialize-only r1 did not.  This is a behavioral difference, not a
mode-selection proof.

The requested implementation of `process_chat_mode_enabled` and
`chat_modes::model_state` is not present in the saved local source subset;
this study therefore cannot attribute the stall to that await.  The retained
finding also explicitly says public source/binary correspondence is
unestablished, so installed-binary behavior may differ from these lines.

## Supported-option check

No documented Grok CLI 4.6 command-line or saved-config option was found in
the retained local sources that explicitly toggles `process_chat_mode_enabled`
or selects the post-auth `model_state` branch.  It would be speculative to set
an invented environment variable or config key.  Existing no-tools, no-plan,
no-subagents, disabled-web-search, and disabled API-key-auth controls do not
documentedly discriminate this remaining await.

The narrow evidence-preserving repair is therefore instrumentation, not a
configuration mutation: a future separately allocated supported `grok agent
stdio` initialize-only helper should persist the full native session result,
record safe mode declaration if the response arrives, and join its session id.
It must stop before session creation/prompt/model dispatch.  This does not
justify another M4/M5 retry, a token refresh, billing change, or a Daybreak
approval prerequisite.
