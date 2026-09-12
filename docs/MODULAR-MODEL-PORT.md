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

The default port is **unqualified** and refuses paid calls. Real execution
requires `frozen_base_context=FrozenBaseContextPolicy(reviewed_manifest_path,
reviewed_manifest_sha256)`. There is no boolean qualification flag. An explicit
`allow_mock_context=True` is only available when both process runners are
non-subprocess test fixtures; it is recorded as `mock_fixture` in the ledger.

`audit_base_context(executable, fixed_cwd, audit_root, ...)` performs only a
non-billed `debug prompt-input`. Use a direct CLI executable (on Windows, the
actual `.exe`, not an unhashed launcher chain), a fixed empty directory outside
all ancestors containing `data/labels`, and a new empty audit destination.
The helper archives the raw render, strictly validated visible role/content,
a configuration source hash inventory, exact shared arguments, environment
hash, CLI hash, and an **UNQUALIFIED** candidate manifest. It does not qualify
the candidate. No credential files or environment values are copied into the
report. Source inventories include absent paths and glob membership so new
configuration/rule/skill files also change the binding.

A reviewer must read the raw render and audit, check that the source inventory
also covers any externally referenced configuration/instruction files, and
write a separate manifest with `status="REVIEWED"` and a `review` object:
`reviewer`, `reviewed_at`, `rationale`, and `source_completeness`. Preserve the
candidate's `binding`, `audit_path`, and `audit_sha256`. Pin the resulting
manifest file's SHA256 when constructing the port. This records a concrete
review and the material it reviewed; it is not a signature proving the reviewer's
identity. Reviewed common system/skill text is permitted across arms. An empty
skills catalog is not a qualification requirement.

One `shared_args()` supplies both `debug prompt-input` and `exec`, including
model, reasoning effort, read-only sandbox configuration, never approval,
project document limit, disabled web, and the same disabled execution/tool
features. Both processes receive the exact same fixed empty cwd and captured
environment, using the same default user config and rules. Neither uses
`--ignore-user-config`, `--ignore-rules`, nor an alternate probe-only home.
Every configured MCP server found in the inventoried TOML sources must have an
explicit disabled override. Reviewed `skills.config` overrides may reference
`SKILL.md` paths to reduce the common catalog. CLI bare MCP keys use
`mcp_servers.NAME.enabled=false`; names outside the accepted bare-key grammar
are refused rather than silently introducing a different server entry.

Before each call, the controller rehashes the policy/audit materials, CLI,
configuration inventory and environment; verifies cwd emptiness and label
ancestry; renders the base prompt; and compares its exact role/content digest.
It rechecks local bindings after rendering and immediately before reserving the
paid call. Empty, malformed, unsuccessful, or changed renders cannot start the
paid runner. The raw CLI JSON includes fresh message IDs/timestamps, so only
those transport fields are excluded from the visible digest; all text,
roles, content ordering, environment text and dates remain bound. The ledger
freezes the full policy/hash/config binding and rejects changed configuration
on reopen, including a different reviewed policy with identical prompt text.
For a stable local deployment descriptor, pass an absolute
`model_catalog_json` override in the shared arguments and include that exact
catalog file in `context_source_specs(..., model_catalog_path=...)`. The live
no-paid check verified this override against the installed CLI. A task-local
catalog can preserve the cache's complete `models` array while archiving its
original bytes separately; only refresh metadata (`fetched_at`, `etag`,
`client_version`) is omitted from the catalog. In this explicit override mode,
the unused shared `models_cache.json` is not a request source and its refresh
does not block calls. Any frozen catalog content change still blocks. The
catalog freezes the available local descriptors, not the provider's underlying
weights or deployment version. Environment changes across processes require a
fresh reviewed audit, not silent acceptance. Each call records actual argv/cwd, environment/policy hashes, probe
receipt and its frozen slot-schema hash.

The installed CLI's debug command renders base messages, not the full provider
request/tool schema. `exec` additionally supplies the public task prompt and
the ledger-frozen response schema for that slot, plus output/ephemeral flags.
The controller does not establish identity of provider-owned instructions or
remote deployments, nor atomic filesystem isolation against a concurrent
writer. Tool events and skill-context error events still seal a call as
untrusted. Configuration restrictions and event checks do not prove an OS
sandbox. The contract requires the same reviewed base binding across arms;
experiment orchestration must supply that policy consistently.

CLI startup notices are also fail-closed by default. Two specific notices can
be approved in advance: the exact warning for the frozen
`skip_host_skill_discovery` flag, and the exact disabled-code-mode-host notice
when both code mode features are disabled. Neither notice reports a skill
catalog or a skill-loading failure. A reviewed policy may add an
`allowed_startup_notices` list of objects containing `kind`, exact `message`,
absolute `source_events_path`, and `source_events_sha256`; its review must also
include `startup_notice_rationale`. The supported kinds are
`unstable_skip_host_skill_discovery` and `disabled_code_mode_host`. Each message
must equal the known wording for the policy's frozen flags/config path and
occur exactly once in the hash-pinned archived startup event stream.

At execution, that exact event envelope/message is allowed only once before
the turn begins. Its message hash and startup phase are recorded with the
policy-bound call. Changed wording, extra enabled features, unknown warnings,
catalog truncation, load errors, duplicate notices, and notices during the
turn remain faults. This exception does not prove a provider tool schema or
turn a failed old call into a success. Changing the allowlist requires a newly
reviewed policy hash and a new ledger; terminal inspection uses the allowlist
frozen in the original ledger, never a later replacement policy.

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
