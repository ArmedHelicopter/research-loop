# Native initialization timeout: read-only finding

The original authoring envelope remains terminal and is not retried. Its archive
commit is5e1b18410910d57fbb67bafcc1ec78d4bcbc3afd:60 files and58 ZIP payloads were
verified against disk, index and committed Git bytes. All36 materials remain
unresolved and all72 evaluator opportunities remain represented. No diagnostic
request was dispatched.

The parent worker exited0 after70.875 seconds and closed its process tree. Native
raw output contains zero stdout/stderr bytes. Its only outbound RPC was initialize;
there was no session/new, billing, topup or session/prompt request and no native
prompt reservation. The native receipt reports timeout, no shutdown failure and
unknown usage/cost. The original native exit code was not captured and remains
unknown. A scoped Win32_Process check found zero surviving owned Grok processes.

Read-only inspection confirms the140810568-byte executable still matches the
frozen bf43dc75f5478a106eab1e86d422c963e4dbe9666cf14dab363733d27bf1e672 SHA256.
The native startup log reports version1.0.13. All four config files still equal
the frozen diagnostic configuration with output8192. All four cwd directories
are empty. Cwd/home/profile path lengths are166/175/178 characters. No path error
was observed; their contribution is not established. Only the attempted runtime
home acquired startup files; the other three homes retain only auth/config.

The58-row private startup log shows these source-matched phases (UTC):

| Time | Safe phase |
| --- | --- |
| 2026-09-13T22:34:02.262Z | Native initialize handler entered |
| 2026-09-13T22:34:02.272Z | Cached login was expired; silent refresh path selected |
| 2026-09-13T22:34:02.839Z | Auth advisory-lock warning |
| 2026-09-13T22:34:03.955Z | Refreshed auth persisted; refresh succeeded |
| 2026-09-13T22:34:03.956Z | ACP auth methods constructed and default selected |
| 2026-09-13T22:34:04.897Z | Last startup-log record, auth enrichment timing |

Whitelisted metadata reports OIDC mode, no external API key, cached auth available
after refresh and no enterprise OIDC. No credential body was inspected. The
lock warning preceded successful refresh and is not established as the timeout
cause. Source-matched static event names, not unfiltered messages, were used.

Pinned public source37949780c144e37df692e3d669051a21fec24f20 shows initialize's
silent-refresh branch at acp_agent.rs lines350–372, auth-method construction/log
at420–483, then background setup and model-state resolution at485–511 before it
returns InitializeResponse from line519 onward. The evidence locates the missing
step after auth-method selection and before a received initialization response.
It does not identify which later function stalled or prove a failed refresh.

Source: https://raw.githubusercontent.com/xai-org/grok-build/37949780c144e37df692e3d669051a21fec24f20/crates/codegen/xai-grok-shell/src/agent/mvp_agent/acp_agent.rs

Only existing files/logs, process metadata and pinned public source were read.
No new native executable, ACP handshake, model prompt, login flow or setting
mutation was performed during this investigation. The separately proposed
initialize-only experiment requires root scope review before its one launch.
