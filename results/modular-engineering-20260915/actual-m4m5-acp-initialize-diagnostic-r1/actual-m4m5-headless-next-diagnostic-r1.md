# Actual M4/M5 native startup: one bounded next diagnostic

## Scope and status

This is a read-only source and retained-metadata study.  It made no Grok CLI,
model, HTTP, Docker, or evaluator call and did not inspect an `auth.json` value.
It does **not** reopen the closed M4/M5 attempt or change its allocation.

The closed first solver call (PID 44884) timed out after 60 seconds with empty
captured streams; the later `process_tree_shutdown_failed` is a cleanup result,
not a successful return.  The retained diagnosis records that its unified log
reached `agent initialized` and then remained in `acp_initialize`; it did not
reach session creation, prompt receipt, or inference.  Thus usage remains
unknown, not zero, and this record supplies no score or module-effect result.

## Saved-source boundary

The examined saved public source is
`work/grok-headless-initialize-location-r2/acp_agent.rs`, SHA-256
`4D4689029CBCAADCA67C5C3561698F37F5CB02342098E5A7B9DC8FCC1F2BD56E`.
It is useful for locating candidate waits, but this study has not established
that it is the exact build of the installed executable.  The following are
source-level candidates, not a binary-level root-cause attribution.

`Agent::initialize` logs `agent initialized` at line 51.  Before the first
post-init disk-refresh log (line 218), it can await
`auth_manager.update(auth)` at line 107 when the cached user id is empty or
`unknown`.  It then performs a synchronous disk reload.  Later in the same
method it may await the first-party API-key probe (lines 271--281), may await a
silent token refresh if there is no current expired token (lines 303--308), and
may await `chat_modes.model_state()` only when process chat mode is enabled
(lines 433--437).  The worktree and stale-session cleanups at lines 64--74 and
the MCP/catalog setup at lines 422--423 are spawned, so this source does not
make them awaited blockers of the initialize response.  The source does not
identify which candidate, if any, was active in the closed binary.

## Compared safe projections

The actual failed process is
`work/actual-m4m5-headless-run-r1/solver-model/calls/0001-m4_plan/native/process.json`.
The closest successful review-r2 process is
`work/headless-review-run-r2/review.private.jsonl.headless/0758dc2a5487a274516af9cb33bcc86d829c9eb9bb2f06337e0f3eefccdc4bf6/native/process.json`
(PID 52912).  Both used the same recorded executable, `grok-4.6`, low
reasoning effort, a 60-second limit, one turn, streaming JSON, no subagents,
no plan, disabled web search/MCP tools, the same no-tools agent definition,
and the same system-prompt override.  The successful process returned normally;
the actual process did not.

The public command descriptors establish three real input differences:

* different isolated `--cwd`, private prompt file, JSON schema, and session id;
  the actual schema asks for the M4 three-branch object while review-r2 asks
  for a dimensions object;
* different per-attempt `GROK_HOME`/home/temp/app-data locations; and
* all 25 recorded environment names are the same.  The seven explicit feature
  knobs (`GROK_DISABLE_API_KEY_AUTH`, `GROK_DISABLE_AUTOUPDATER`, memory,
  subagents, title refresh, turn summary, and workflows) have equal safe
  recorded values; `PATH` also has the same SHA-256.  Per-attempt path-valued
  variables necessarily differ.

The retained diagnosis separately records equal `config.toml` bytes and empty
active-session files for the comparison.  It also records a `worktrees.db`
creation/update in the actual isolated home before its session phase.  That is
a timing observation only, not evidence that the database caused the hang.

The previously retained direct-headless comparison already rules out treating
ACP-versus-direct transport as a demonstrated repair: a successful constant
readiness call also used direct headless.  No observed difference justifies a
full M4/M5 retry.

## One finite discriminating diagnostic to prepare, not run here

If a later owner explicitly authorizes one diagnostic allocation, run exactly
one **ACP-initialize-only profile replay**, separately frozen from M4/M5:

1. Byte-copy the closed call's private native-home as an opaque input into a
   new diagnostic-owned home.  Do not modify the closed run or print/read
   credential values.  Record source/destination manifests and exclude
   credential content from public artifacts.
2. Start the same pinned executable with the same feature-knob environment and
   a fresh diagnostic public cwd, using its ACP stdio entrypoint.  Send one
   protocol `initialize` request and wait only for its response.  Do not send
   `session/new`, a prompt, a model selection, or any evaluator request.
3. Enforce one 20-second wall-clock deadline, then close only the owned process
   tree.  Capture redacted command/environment projections, ACP request/response
   framing, exit/timeout state, and a credential-free log event timeline.
   Declare usage/settlement unknown unless independently settled; do not infer
   zero usage from absence of a prompt.
4. Stop after that one process.  No Docker, scorer, VAL data, module cells, or
   M4/M5 rerun follows from either result.

This is discriminating because the source places the observed stall inside the
initialize method before any session or prompt.  A second stall in this copied
profile would narrow the issue to initialization/profile/external-startup
classes and exclude the M4 schema/prompt as a necessary trigger.  A timely
initialize response would instead show that the direct-headless adapter input
or timing (or transient external state) differs.  Neither outcome identifies a
specific awaited operation or proves a production repair; the entrypoint is a
controlled diagnostic, not a substitute for the failed direct route.

## Inputs consulted

* `work/actual-m4m5-headless-native-diagnosis-r1.md`
* `work/grok-headless-root-cause-readonly-r1.md`
* `work/headless-existing-log-comparison-r1.md`
* the two process/command descriptors named above
* saved public `acp_agent.rs` named above
