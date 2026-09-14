# Grok native sampling source audit r1

## Scope

This note preserves a primary-source reading of public `xai-org/grok-build` at commit `bc7f02eddd3d84085849dc19ed216f11c23b0571`. It makes no native, model, account, or API call. It does not establish that the installed executable is built from this source.

## Source finding

`[models].max_completion_tokens` is a fallback only. In `crates/codegen/xai-grok-shell/src/agent/config.rs:3729-3746`, `apply_global_scalar_defaults` calls `info.max_completion_tokens.get_or_insert(v)` and documents the global value as “a fallback, not a clamp.” A populated remote or prefetched entry wins over that global field.

A per-model override is the direct configuration route. `ConfigModelOverride.apply` writes a configured `max_completion_tokens` to `entry.info.max_completion_tokens` (`config.rs:4116-4117`). `sampling_config_for_model` reads that value and writes it to `SamplerConfig.max_completion_tokens` (`config.rs:5248-5291`); `ModelsManager.sampling_config` builds sampling from the current resolved model (`agent/models.rs:1017-1042`).

The parser expects a top-level `[model.<key>]` table. `config_model_override_parse.rs:1,207-235` reads `raw_config.get("model")` and parses each entry as a `ConfigModelOverride`; it does not use `[models.overrides.<key>]`. `Config::new_from_toml_cfg` invokes that parser (`config.rs:2030-2035`).

The supported native effort control is `--reasoning-effort` (`xai-grok-pager/src/app/cli.rs:513-523`). Headless mode resolves it against the selected model's advertised effort options and warns/ignores an unsupported value (`xai-grok-pager/src/headless.rs:670-715`).

## Verified r2 configuration and catalogue

`work/headless-instrumented-request-r2/home/config.toml` contains both `[models] max_completion_tokens = 8192` and `[model."grok-4.6"] max_completion_tokens = 8192` (lines 4, 7, 9, 10). The latter has the correct syntax for the pinned parser.

Only safe fields in `work/headless-instrumented-request-r2/home/models_cache.json` were read. The relevant entry is:

```json
{"catalog_key":"grok-4.6","id":"grok-4.6","model":"grok-4.6","max_completion_tokens":null,"supports_reasoning_effort":true,"reasoning_effort":"high","reasoning_efforts":["xhigh","high","medium","low"]}
```

There is no `grok-4.6-build` key. The cache has no non-null completion value that would outrank the global fallback, and the exact per-model table key matches the cache key.

A whitelist-only extraction from `native/debug.private.log` found one request-marked structured `max_completion_tokens` field with numeric value `8192` (line 74). No raw debug text was retained or reported. This establishes that a request-associated debug record carries the intended value, but does not independently prove installed-binary equivalence or provider-side enforcement.

## Superseding conclusion

The existing r2 configuration already uses the valid exact per-model syntax. The source routing and cache-key findings therefore do **not** provide a configuration correction. The completed r2 cap breach remains unresolved by this audit and remains rejected. A future request must preserve an independently inspectable effective-request/response bound before its outcome can be accepted; copying the same TOML is not a repair.

## Boundary

Public-source control flow, a cached catalogue, and a request-marked debug field do not establish installed-binary equivalence or provider-side limit enforcement. They also do not validate the completed r2 result.
