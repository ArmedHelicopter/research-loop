# No-tools model port

`CodexModelPort(executable, work_root, model="gpt-5.6-luna", effort="low",
max_calls=..., max_tokens=..., schema_by_slot=...)` is a callable suitable for
`RunSession.invoke(slot, port, instruction=...)`. It accepts only the frozen
`public-model-request-v1` record produced by that session and returns a
`FrozenRecord` whose object exactly matches the schema frozen for that slot.

Each invocation reserves a persistent ledger entry before starting Codex. The
entry records request and prompt hashes, requested provider/model identity, the
complete argument vector, output/event hashes, exit status, token usage, and
any prohibited tool event. A valid stream has exactly one `turn.completed`
usage object with the five literal-integer fields `input_tokens`,
`cached_input_tokens`, `cache_write_input_tokens`, `output_tokens`, and
`reasoning_output_tokens`. Accounting adds input plus output only; cached and
reasoning fields are retained in the receipt without double counting. A timeout
becomes `unknown`; provider errors, absent or duplicate usage, tool/execution
events, detected skill-context errors, absent output, invalid output, and a
token-budget overrun become terminal. A reopened port rejects every
ledger with a reserved, unknown, failed, over-budget, or incomplete call.

The port invokes the installed CLI with `exec --ignore-user-config
--ignore-rules --ephemeral --skip-git-repo-check -C <empty per-call directory>
-s read-only --json --output-schema ... -o ...`. It also disables the listed
tool, browser, plugin, hook, app, skill, image and goal features and sets
`project_doc_max_bytes=0`, disabled web search, memories, skill search, and
host-skill discovery (`--enable skip_host_skill_discovery`). A skill-context
error event seals the call as untrusted. Before every paid `exec`, the port also
runs the installed CLI's non-billed `debug prompt-input` with an empty task-local
`CODEX_HOME` and the same skill/plugin/memory feature flags. It stores only a
hash and boolean result, then refuses the paid process if the rendered context
contains a skills block. This is a fail-closed probe, not an OS sandbox. The
arguments were checked against `codex exec --help` on Codex CLI 0.153.4.

The task-local contract uses the documented `[[skills.config]]` form with a
`SKILL.md` path and `enabled = false` for each discovered local skill. On this
host that override reduces local entries but does not remove the bundled SYSTEM
catalog. A paid run therefore remains refused until the probe observes no skills
block; it must not treat local overrides as proof that system skills are absent.

`max_tokens` is enforced against recorded cumulative provider usage after each
call. The CLI version checked here exposes no per-call output-token switch, so
it is an accounting stop, not a pre-call output-token cap.

This constrains Codex configuration and its working directory. It is not an OS
sandbox or a claim that a compromised provider process cannot access the host.
The port does not discover files, derive task metadata or labels, load scorer
or validation data, or feed any scoring/validation result into a solver.

`inspect_terminal_call(work_root, call_id)` is read-only reconciliation for a
completed call that a previous parser rejected. It checks the stored event and
output hashes, the frozen output schema, full usage, tool events and context
faults, and can return the already-written `FrozenRecord` response. It never
changes the original ledger or permits a retry. A recovered response with a
skill-context fault remains unreconciled and must not be presented as a formal
experiment result.
