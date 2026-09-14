# Typed TRAIN phase provider scopes

`phase_provider.py` adds the versioned helper seam used by native TRAIN phases.
It does not change legacy Codex helpers, schemas, model policy or any controller
admission. Controller integration is a separate change.

- `provider_configuration(provider)` admits only the two actual closed wrappers.
- `validate_configuration(config, schemas=..., main_opportunities=..., exact=True)`
  checks a complete phase allocation. Native lifetime remains 60 seconds per call;
  requested output, prompt bytes and observed MAIN have different bounds.
- `call_accounting(checked_calls)` retains known MAIN, unknown MAIN, possible
  title opportunities and unknown final settlement separately.
- `PhaseProviderSession(provider, path)` requires a fresh provider. Each
  `with session.scope(scope_id) as model` owns an ordered contiguous call span.
  The scoped callable exposes `cursor()` and `calls_since(cursor)` for charge
  journals. Scope names are unique, and calls outside scopes invalidate sealing.
- `session.seal(path)` returns a `PhaseProviderLedger`. Its `verify()` replays
  the native originals and the complete global scope partition. Its
  `bind_events(events, scope_id=..., require_eligible=True)` supplies exact call
  IDs to the core original-evidence verifier. No native call is converted to a
  Codex-shaped ledger row.

A build-prefix seal remains verifiable after legitimate target appends, even
when a later target fails. Failure removes scoring eligibility, but keeps prior
history evidence and consumed-call accounting. A zero-call blocked scope remains
in the denominator. A scope is an engineering allocation, not a qualification,
validation lease, promotion permission or scientific result.

For an unresolved provenance fault, `session.abort()` can preserve a core
`failure_snapshot()` only after the core has already recorded a durable terminal
fault. It records the completed scope prefix and an explicitly unresolved active
scope. It never invents call IDs for a historical count lower bound.

`session.terminal()` and `session.usage()` can take this explicit abort path when
strict original replay raises. An unrelated programming error cannot produce a
core failure snapshot. `session.finish(path)` returns either the ordinary typed
`PhaseProviderLedger` or a distinct `PhaseProviderAbort`; callers must branch on
the exact type. `seal()` remains strict. An abort is bound to its original disk
bytes and terminal snapshot; its `verify()` reports only terminal accounting,
and its `bind_events()` always rejects. Barriers and scorers cannot consume it.

After abort, exact unused MAIN and complete current totals are unknown. The
snapshot's observed counts/tokens remain historical lower bounds with explicit
unknown unobserved opportunities. Controller cleanup and complete planned rows
remain required even when an eligible original seal cannot be issued.

`inspect_configuration_and_calls()` returns configuration and call views from
one fresh original inspection. `PhaseProviderSession.verify()` uses that one
pass for both its configuration comparison and scope-count check. Previously,
`configuration()` inspected the full prefix, then `inspect()` repeated it.
No original file, source pin, scope rule or terminal behavior is skipped, and
the returned tuple confers no seal or scoring authority. Subsequent verification
still re-reads every original; there is no persistent cache or replay exemption.

Both real provider types are exercised through their existing synthetic ports.
The regression counts original call replays and changes original response bytes
or configuration after a successful check. It requires the next fresh check to
close dispatch. This demonstrates removal of one duplicate pass, not a measured
end-to-end throughput improvement or scientific effectiveness.
