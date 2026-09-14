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
