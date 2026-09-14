# Isolated 1.0.30 readiness context and internal reload response

Explicit `FrozenNativeDeployment.create(executable, skill_isolation=True)` selects
deployment v2. It pins the same official 1.0.30 executable and argv; the default
constructor remains deployment v1, and omitted deployment remains native 1.0.13.
Only the 128-output-token `run_native` readiness entry accepts deployment v2.
Material authoring and diagnostic provisioning/readers reject this deployment;
their old envelopes and meanings are unchanged.

Create fresh, disjoint Windows cwd, GROK_HOME and user-profile directories outside
any repository or ancestor discovery directory. Write
`grok_skill_isolation.isolated_config(cwd, private_home, private_profile)` to
GROK_HOME/config.toml and pin its actual bytes together with
`deployment.source_pins()` and the executable. Existing authorized login handling
remains opaque and outside this helper. Do not hash credentials into the manifest.
Then call the existing `run_native(..., deployment=deployment)` entry with the
unchanged main-and-initial-title-v2 opportunity contract and maximum 60 seconds.
This document is a call recipe, not authorization to run a real probe.

The context record derives exact absolute ordinary-skill ignore prefixes. They
cover all controlled roots, later GROK_HOME/bundled downloads and ancestor discovery
directories. Empty extra/server/bundled paths do not alone disable discovery; the
official prefix filter is necessary. Initial native launch still requires only
auth.json/config.toml in GROK_HOME, and empty cwd/profile. The observer rejects
ancestor discovery directories/repositories, profile discovery directories,
GROK_HOME/plugins, installed-plugins, managed_config.toml and requirements.toml.
It checks path aliases/reparse points and bounded metadata traversal, without
reading auth or skill bodies. It repeats at each received frame, before each RPC,
and after process shutdown. Ordinary bundle creation is permitted because its
paths remain ignored; plugin-source arrival is terminal, even without a reload
RPC. No policy file is deleted, blocked or changed; a discovered policy layer
causes refusal to use this isolated contract.

All five observed built-ins (compact, always-approve, context, session-info,
feedback) must occur once in the command inventory; `_meta.tools` remains exactly
empty. After that inventory and the one session have been bound, the only new
side response admitted is exactly:

```json
{"jsonrpc":"2.0","id":"skills-reload","result":{"result":{"reloaded":1}}}
```

Boolean 1, extra keys, errors, other counts, other IDs and early unbound responses
are rejected. `reloaded` counts sessions enqueued, not skills or completed reloads.
The response is recorded separately with the outstanding numeric request ID,
session and context observation. It cannot satisfy a MAIN request or supply
usage. The original deadline is never reset. Original response/session/prompt,
MAIN usage, selected model, fresh billing, no-topup and tool gates still apply.

Receipt v4 and reservation v3 bind the context digest, deployment, original
request/stdout hashes, context observations and classified internal frames. MAIN
usage and unknown initial TITLE/all-opportunity settlement remain separate.
An incomplete MAIN remains incomplete even if a reload response was accepted.
Failed evidence is retained and no legacy receipt is rewritten.

Evidence limits: the context policy follows public source commit
bc7f02eddd3d84085849dc19ed216f11c23b0571, which creates an empty SkillManager even
when discoverSkills=false. A background RefreshSkillBaseline can update it
without any internal RPC. Public source and the 1.0.30 binary are not proven byte
equivalent. Synthetic tests run the actual native_launch and ACP parser with only
the final process spawn replaced; a synthetic child models the public prefix
filter on a newly created bundle. They do not inspect a real model's effective
context or establish billing settlement or scientific validity. A later real
readiness probe, if separately approved, must preserve these evidence limits.
