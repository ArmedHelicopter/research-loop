# Grok 1.0.30 initialize stack diagnostic r1

Prepared only; no Grok process or debugger attach has run in this directory. `driver.py` permits one fixed ACP `initialize` write, no authentication/session/prompt/billing RPC writes, and creates a private auth copy without reading its contents. `init_engine.py` invokes `stack_capture.py` only when that exact spawned child remains alive without an initialize response after 15 seconds.

The capture command is fixed to x64 CDB `-pvr -pd -netsym:no -sins -noshell -logo ... -c "~* k; q"`. Raw CDB files remain in `private-cdb/`; public closure output retains only status/counts/module labels. The prepared CDB help output confirms the flags; its nonzero help exit code is retained verbatim in `cdb-help-result.json`. `-pd` requests automatic detach, but a separate detach acknowledgement is unavailable and is recorded as unobserved. A capture is only marked established when CDB exits 0 and a stack-frame parser finds at least one frame; all other completed attempts remain `capture_success_not_established`.

Execution must preserve the exclusive-root guard and review the closure rather than interpreting a stack as source-level proof or account/network evidence.
