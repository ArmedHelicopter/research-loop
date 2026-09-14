# Authless native configuration inspection, 2026-09-14

Two bounded `inspect --json` commands completed under separate fresh
home/profile/cwd directories. Installed 1.0.13 took 0.125 seconds; separately
staged 1.0.30 took 1.422 seconds. Both exited zero and their owned Windows Jobs
closed. Each executable was checked against its existing SHA-256 pin.

Both outputs report exactly the supplied user configuration layer, no discovered
skills, hooks, plugins, MCP servers, LSP servers, marketplaces or project
instructions, and no project root. Three built-in agent definitions remain
listed. This is a discovery inventory, not an execution/tool inventory.
`externalCompat.remoteSettingsLoaded` is false in both outputs: neither
describes authenticated remote settings or a later session.

No auth file was supplied, read, hashed or copied. No auth file appeared in the
new homes. The observer passed no prompt and wrote zero stdin bytes or ACP
methods. No model response, fresh account/quota snapshot, settlement or
generation readiness was observed. Global settings and installed binaries were
unchanged. This observation launched no benchmark and ran no pytest suite.

This separates successful local configuration discovery from earlier initialize
stalls. It establishes neither their root cause nor a qualified headless
generation route. The version difference was already known historically:
1.0.13 previously succeeded and later timed out. It is not a newly discovered
fix. These observations do not justify another identical initialize retry.

The 13 files in `manifest.json` preserve exact original bytes. Complete inspection
JSON was reviewed before inclusion: only this authless context, built-in
definitions and default/configured policy values appear; no credential-bearing
file is included. The original `private` filename suffix was conservative
collection handling. The source snapshot records the actual `ProcessTree`
implementation used, not a complete Python environment or reproducible build.

The outcome remains modular implementation and TRAIN/VAL-separated experiments.
This is infrastructure evidence, not scientific efficacy, VAL acceptance or
completion of that outcome.
