# Retained headless initialization location

2026-09-15. This is a read-only refinement of two existing native runs. It
does not launch Grok, dispatch a model, reopen the failed authoring reservation,
read validation data, or change an original outcome.

The native unified log uses `ts`, `msg`, and `ctx`. The older comparison looked
for `timestamp`, so its null times did not mean that the source lacked times.
The new extractor publishes only explicit fixed event names and selected typed
fields. It retains 31 events from the successful constant trial and 25 from
the failed material trial. Original log bytes and mtimes were unchanged; raw
logs and credential-related context fields are not copied into this archive.

Both runs recorded a real model catalogue with two models, an unexpired
cached token, no pending user-info enrichment, and no auth change on disk
reload. The failed run recorded `acp_initialize` at 15:17:38.334 UTC, auth
method selection at 15:17:38.339, then a long-running `acp_initialize` warning
at 15:17:48.676 with open_ms=10341. It has no later phase record. The successful
run progressed from initialization to eager authentication and session creation,
then recorded prompt receipt and inference. These are logged milestones, not
proof that every unlogged action was absent.

The earlier observation that only the successful log contained catalogue
notifications remains true, but does not imply that the failed run could not
fetch its model catalogue. Its earlier fetch and real-catalogue observations
are now included. The evidence does not support diagnosing this failure as
expired login or a missing model catalogue.

The separately pinned public initialization source returns through several
synchronous setup operations after auth-method selection. Related public source
shows the release chat-mode branch disabled and heap monitoring scheduled after
a 30-second sleep. A small memtrace file appearing after 30 seconds is therefore
not evidence that heap monitoring caused the initialization stall. None of these
source observations identifies the binary's blocked instruction. The public
repository did not resolve the binary's displayed 5e9a58528b76 revision (HTTP
422); binary/source correspondence remains unestablished.

Public source URLs:

- https://raw.githubusercontent.com/xai-org/grok-build/bc7f02eddd3d84085849dc19ed216f11c23b0571/crates/codegen/xai-grok-shell/src/agent/mvp_agent/acp_agent.rs
- https://raw.githubusercontent.com/xai-org/grok-build/bc7f02eddd3d84085849dc19ed216f11c23b0571/crates/codegen/xai-grok-shell/src/agent/chat_modes.rs
- https://raw.githubusercontent.com/xai-org/grok-build/bc7f02eddd3d84085849dc19ed216f11c23b0571/crates/codegen/xai-grok-shell/src/agent/mvp_agent/heap_profile.rs

The failed full-material run remains timed out with empty native streams,
unknown usage/settlement, zero ready and 36 unresolved material slots. This
read-only work establishes no transport repair, material quality, module effect,
calibration or validation acceptance.
