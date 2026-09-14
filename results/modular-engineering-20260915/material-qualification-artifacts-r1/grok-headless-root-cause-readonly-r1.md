# Grok headless root-cause review (read-only, 2026-09-15)

Scope: source and retained local evidence only. No Grok, network, account, or
model invocation was made. This note does not retry the closed four-TRAIN
batch.

## Observed evidence

The retained first material attempt is
`work/headless-authoring-actual-run-r1/private-output/39a896.../native-observer-receipt.json`.
It records `accepted=false`, `input_bytes=4906`, `timed_out=true`, exit code
`0`, owned process tree closed, and SHA-256 values for both stdout and stderr
equal to the empty-byte digest. Its stream faults are
`runtime_tools_unobserved,end_count`; it has no stream event count or end
event. This agrees with the closed/rejected state and does not establish that a
model request was processed.

The installed executable is `C:\\Users\\Administrator\\.grok\\bin\\grok.exe`;
the current source pins SHA-256
`bf43dc75f5478a106eab1e86d422c963e4dbe9666cf14dab363733d27bf1e672`.
The non-secret installed configuration exposes `[cli] auto_update=true`, but
the attempt used a freshly copied private home and its transport sets updater
disablement itself. The deployment metadata has the non-secret field names
`executable`, `cwd`, `private_home`, and `private_profile`; each slot receives
an empty dedicated cwd/profile. No secret-bearing file was read.

## Material difference from the successful readiness mechanism

The rejected material path is selected by authoring v3 at
`evaluation/modular/diagnostic_material_authoring.py:555-563`. It invokes
`run_headless_diagnostic`, whose direct CLI command uses `--prompt-file`, an
inline `--json-schema`, `--output-format streaming-json`, `--session-id`, and
other headless flags (`research_loop/modular/grok_headless_transport.py:208-215`).
It launches that command through `communicate(timeout=240)`
(`:231-277`), so there is no stdin framing or concurrent reader; the only
evidence it can inspect is the process's terminal stdout after exit/timeout.

The successful readiness implementation is a different transport: it launches
`grok ... agent stdio` (`research_loop/modular/grok_acp_transport.py:851-858`),
opens stdin/stdout pipes under a Windows kill-on-close Job
(`:245-293`), reads stdout concurrently line by line (`:619-641`), then sends
newline-delimited JSON-RPC `initialize`, `session/new`, and `session/prompt`
frames (`:642-693`). It requires a pre-prompt `available_commands_update`
inventory for that session (`:660-668`) and records notifications and terminal
usage separately (`:752-810`).

Both routes isolate cwd/profile and disable side features. Thus the retained
evidence distinguishes transport/framing and observation strategy, rather than
showing a changed model, subscription, account, working directory, executable,
or unowned child process. The direct route did use process-tree ownership
(`grok_headless_transport.py:236-263`), and closure is recorded, so surviving
children are not an established cause.

## Conclusion and concrete future repair condition

No root cause for the direct CLI's empty stream is established. The evidence
does not identify whether the CLI buffered output, rejected this flag/
prompt-file combination, waited in an internal startup state, or encountered a
service-side condition.

One concrete source-level changed condition is available for a future bounded
repair: a frozen revision must route the material request through the observed
ACP `agent stdio` framing, rather than v3's direct
`--prompt-file --output-format streaming-json` route, while preserving the
same pinned executable, private cwd/profile, one reservation, no retries, and
the material input/schema binding. Before any full material prompt, that repair
must emit and retain its own ACP startup evidence: successful `initialize` and
`session/new`, the same-session zero-tool inventory, and a fresh pre-prompt
deadline. Only that changed condition makes a new bounded transport test
meaningfully distinct from the closed request; it is not yet validated for the
full prompt and is not authorization to dispatch one.

## Root correction after checking the actual readiness receipts

The comparison above is insufficient as a repair recommendation. Root inspected
`work/grok-headless-constant-readiness-r2/reservation.json` and its receipt:
the successful 12.609-second, 1,950-main-token trial itself used
`--prompt-file --output-format streaming-json`, with the same installed 1.0.13
binary digest. Thus ACP versus direct headless is NOT the difference between
that successful trial and the failed full-material attempt. The matching
checked-in explanation is `docs/GROK-HEADLESS-READINESS.md`.

There is an older successful ACP constant trial, documented separately in
`docs/GROK_ACP_TRANSPORT.md`, but returning to ACP cannot by itself be called a
new demonstrated repair. `work/material-authoring-actual-run-r1/` already
retains a version-1 ACP material batch under source
`5704c53db0ab3d0ade2e033f5fb4ef155d7a44dc`. Its original public parent closure
has worker_exit=0, elapsed_seconds=70.875 and retry_allowed=false. Its original
public-outcome.json records native timeout, no prompt may-have-been-dispatched,
zero ready / 36 unresolved slots and zero reviewer calls. Those failures and
unknown costs remain unchanged.

Root made no Grok, account, network or model invocation during this correction.
No causal repair or newly justified dispatch condition has been established;
the two transport implementations alone do not justify another probe.
