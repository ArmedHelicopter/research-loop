# No-tools model port

`CodexModelPort(executable, work_root, model="gpt-5.6-luna", effort="low",
max_calls=..., max_tokens=..., schema_by_slot=...)` is a callable suitable for
`RunSession.invoke(slot, port, instruction=...)`. It accepts only the frozen
`public-model-request-v1` record produced by that session and returns a
`FrozenRecord` whose object exactly matches the schema frozen for that slot.

Each invocation reserves a persistent ledger entry before starting Codex. The
entry records request and prompt hashes, requested provider/model identity, the
complete argument vector, output/event hashes, exit status, token usage and a
terminal status. A timeout becomes `unknown`; provider errors, absent output,
invalid output, and absent usage become incomplete billing. An incomplete
ledger blocks every following call, including after the port is reopened.

The port invokes the installed CLI with `exec --ignore-user-config
--ignore-rules --ephemeral --skip-git-repo-check -C <empty per-call directory>
-s read-only --json --output-schema ... -o ...`. It also disables the listed
tool, browser, plugin, hook, app, skill, image and goal features and sets
`project_doc_max_bytes=0`, disabled web search and host-skill discovery. The
arguments were checked against `codex exec --help` on Codex CLI 0.153.4.

This constrains Codex configuration and its working directory. It is not an OS
sandbox or a claim that a compromised provider process cannot access the host.
The port does not discover files, derive task metadata or labels, load scorer
or validation data, or feed any scoring/validation result into a solver.
