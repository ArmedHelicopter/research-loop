# ACP initialize-only diagnostic r1: incomplete negative receipt

One separately owned diagnostic launch was made through the locally documented
entrypoint `grok agent stdio`, using executable SHA-256
`BF43DC75F5478A106EAB1E86D422C963E4DBE9666CF14DAB363733D27BF1E672`.
The helper sent exactly one ACP JSON-RPC `initialize` request.  It constructed
no `session/new`, prompt, model selection, evaluator, VAL, or Docker request.
The source M4/M5 native home was copied opaquely into a diagnostic-owned input
and then runtime home; credential values were never parsed or emitted.  Its
noncredential bytes and mtimes match the frozen opaque input after the launch.

The helper carried a 20-second process deadline.  Its outer command wrapper
ended before helper receipt finalization, so there is no trustworthy process
PID, exit code, complete raw stdio capture, or terminal timeout receipt.
Accordingly, process exit, timeout status, usage, and settlement are all
**unknown**.  No Grok process was present after the wrapper returned.  This
consumed the single permitted diagnostic launch and must not be retried from
this artifact.

The retained runtime unified-log hash is recorded privately and the public safe
timeline exposes only timestamps and message names.  The new diagnostic events
reached `agent initialized`, disk-refresh/auth-method construction, and `auth
method selection` at `2026-09-15T02:24:42.723Z`; there is no later retained
event or response receipt.  This reproduces the closed M4/M5 failure prefix at
the source-defined initialize boundary under the copied profile and a different
ACP stdio adapter.  It excludes neither a later unlogged operation nor transient
external state, and it does not name a blocked instruction or establish an
exact binary/source correspondence.

The prepared bounded diagnostic therefore did not produce a repair.  It adds a
metadata-only observation: the copied profile can again reach auth-method
selection without a session or prompt, but a completed initialization response
was not retained.  No score, module effect, or zero-usage conclusion follows.

## Receipt pins

* `frozen-prelaunch.json` —
  `985487B22CE26ECCDBA00F2706CCE4E1F1555CD2D904A80E9FAA939B39430455`
* `run_acp_initialize_only.py` —
  `904E0A4412774C6082E2FF3167ED7669386694347684CA64B3574A858F24C0E2`
* `receipt.incomplete.json` —
  `55552A9E4A3734610CFF34B4475B68467DF2F19ABFD91A7CBA6CE5658B0B2928`
* `source-home-before-after.json` —
  `52CD60AC25BD684DBFB627E64966901F8441E3C0A3A5FEC354919DB422291D06`
* `private-runtime-log-hashes.json` —
  `6807B3676906851EE7C21C3E94C8DE8FC7A5D1C454A19D142753FFC8E23879B3`
* `log-event-timeline.safe.json` —
  `117D41FB40C5323753D65268EC634F94700CF92D6F16D8E1500203C215E8DD1F`
