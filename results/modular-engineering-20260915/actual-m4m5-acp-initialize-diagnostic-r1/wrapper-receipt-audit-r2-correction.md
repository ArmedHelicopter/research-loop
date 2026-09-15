# Correction r2: `exec_command` yield is not process termination

This additive correction supersedes the causal interpretation in
`wrapper-receipt-audit-r1.md`.  It does not change `receipt.incomplete.json`,
the diagnostic, or any frozen original.

## Exact retained invocation evidence

The diagnostic was launched by this `functions.exec` JavaScript:

```js
const r = await tools.exec_command({cmd:"$env:PYTHONDONTWRITEBYTECODE='1'; python 'E:\\_ryanDev\\AI\\research-loop-modular\\work\\actual-m4m5-acp-initialize-diagnostic-r1\\run_acp_initialize_only.py'; $code=$LASTEXITCODE; if(Test-Path -LiteralPath 'E:\\_ryanDev\\AI\\research-loop-modular\\work\\actual-m4m5-acp-initialize-diagnostic-r1\\receipt.json'){Get-Content -Raw -LiteralPath 'E:\\_ryanDev\\AI\\research-loop-modular\\work\\actual-m4m5-acp-initialize-diagnostic-r1\\receipt.json'}; exit $code",workdir:"E:\\_ryanDev\\AI\\research-loop-modular",yield_time_ms:30000,max_output_tokens:8000});
text(r.output);
```

The model-visible outer result was exactly `Script completed`, wall time
`30.2 seconds`, with an empty output body.  The JavaScript forwarded only
`r.output`; it did not call `text(JSON.stringify(r))`, `store`, or otherwise
retain the full nested `exec_command` result.  Therefore the raw nested return,
including a possible `session_id`, is unavailable in the retained artifact
set.  There is no unjoined session id available to give to the root controller.

## Corrected interpretation

`yield_time_ms: 30000` is a yield boundary, not a process timeout.  The prior
statement that overlap between the helper's nominal 20+10-second path and that
yield proves wrapper termination is unsupported and withdrawn.  The outer
empty result does not establish any of these alternatives:

* whether `exec_command` returned a live `session_id` that the JavaScript
  discarded after forwarding only `.output`;
* whether the helper/PowerShell process was still running when the tool turn
  ended;
* whether any parent or child was terminated by another boundary; or
* whether the helper itself failed before receipt finalization.

The later observation of Python PID 39236 and the absence of a current matching
process remain observations only.  They do not select among those alternatives.
Likewise, helper source contains an owned-tree `taskkill` branch but does not
prove that it ran.  Usage, settlement, exit, timeout, and final raw stdio stay
unknown exactly as recorded in the immutable incomplete receipt.

## Correct lifecycle rule and narrow instrumentation repair

A native `exec_command` result that yields a `session_id` remains live until it
is explicitly joined through `write_stdin`; yielding alone is not closure.
Future orchestration must preserve the full nested result before returning from
`functions.exec`, for example by `text(JSON.stringify(r))` or `store` of the
result, and if `session_id` is present, repeatedly call `write_stdin` to join
it and record the final exit result.  This is separate from the helper's own
durable launch/final receipt instrumentation.

The helper still needs immediate fsynced launch metadata, streamed pipe files,
bounded cleanup, and a `finally` final receipt.  Those changes improve evidence
quality, but a future supervisor must not require the child to finish before a
tool yield boundary.  It must instead retain and join the reported native
session.
