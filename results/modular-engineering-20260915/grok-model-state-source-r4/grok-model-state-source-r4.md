# Synchronous `model_state` source lookup r4

## Evidence and scope

This note reads the public Git tree at commit
`bc7f02eddd3d84085849dc19ed216f11c23b0571` from the local bare repository
`WORK/grok-source-tree-r5`.  `source-manifest.json` binds the three retained
public source blobs.  This source is not shown to be the installed pinned
`ca24...` 1.0.30 executable.

The separate private-log allowlist reports one initialize-only diagnostic with
no response, one initialize, and no prompt.  It reports an `acp_initialize` and
`model_state` marker at line 47, followed by model-catalog notifications and
an auth-enrichment completion in its separate unified log.  Raw private log
text and account fields were not read or copied here.

## Exact source finding

`crates/codegen/xai-grok-shell/src/agent/mvp_agent/acp_agent.rs` calls
`self.model_state(None)` while constructing the ACP initialize response, after
starting several background tasks.  At this commit the process chat-mode branch
is disabled by the previously checked `process_chat_mode_enabled()` source, so
the call is synchronous rather than the alternate awaited chat-mode call.

The definition in `.../mvp_agent/agent_ops.rs` builds the response from:

- `models_manager.current_model_id()`;
- `models_manager.available()` and a cloned visible-model map; and
- `models_manager.current_reasoning_effort()`.

For `None`, the per-session `resident_handle` lookups short-circuit, so this
path does not wait for a session actor or execute a callback.  The definition
contains no async operation, HTTP call, file I/O, or model request.

`crates/codegen/xai-grok-shell/src/agent/models.rs` implements those accessors
with `parking_lot::RwLock` reads for the current model id, catalog, and current
reasoning effort.  Its model-catalog refresh/config paths write the catalog,
but the shown fetch/cache operations occur outside the catalog-write sections;
the write sections replace or clone in-memory state and publish notifications.
Therefore the source supports one narrow remaining possibility: the synchronous
reader can block while an in-process writer owns one of these locks.  It does
not demonstrate such ownership, a deadlock, or correspondence to the installed
binary.

## Consequence

There is no supported source-derived repair switch that safely bypasses
`model_state`; the initialize response needs its model-state metadata.  The
only concrete next localization is instrumentation of lock acquisition/holder
inside a matching local build or an installed-binary stack trace/diagnostic that
preserves the same no-prompt, initialize-only boundary.  Changing auth,
configuration, model/billing route, or repeating a full TRAIN run is not
supported by this source finding.

## Correction: auth accessor in the call graph

`ModelsManager::available()` does more than clone the catalog: it calls
`is_session_auth()`, which calls `AuthManager::current_or_expired()`.
The retained `auth_manager.rs` shows that this is a synchronous in-memory
credential read through `AuthManager.inner: Arc<parking_lot::RwLock<Option<GrokAuth>>>`,
then expiry/policy checks. `current_or_expired()` is `current().or_else(expired_auth())`;
the shown methods do not read `auth.json`, refresh a token, await, or make a
network request. It can nevertheless synchronously wait for the in-memory auth
RwLock writer. Thus the reviewed `model_state(None)` call graph contains reads
of model-manager locks **and** the auth-manager in-memory lock. It does not
prove any one lock was held in the installed binary or that these public source
blobs correspond to that binary.
