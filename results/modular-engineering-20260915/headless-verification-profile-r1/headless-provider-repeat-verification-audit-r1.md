# Headless provider repeated-verification audit r1

Scope: read-only review of source commit `0a5739e463e3c4a294141ff5bdfd1aec53a75835` and the closed full5 synthetic-provider profile.  No live C5 artifacts, transport, Docker, model, or source file was accessed or changed.

The closed full5 direct replay of 136 completed headless provider calls took 1.619 seconds.  That replay is a useful unit-cost observation only: it does not estimate a live C5 duration.

## Repeated full-ledger passes

`PhaseProviderLedger.bind_events_with_calls` is one consumer entry that necessarily calls three complete provider audits today.

1. `phase_provider.py:258` calls `calls_for_scope`.
2. `calls_for_scope` at line 241 calls `PhaseProviderLedger.verify`.
3. That `verify` calls `PhaseProviderSession.verify` at line 230.  `PhaseProviderSession.verify` uses `provider.inspect_configuration_and_calls` (`phase_provider.py:123`), which calls `_TrainProvider.inspect` (`train_provider.py:330`).  This is the first complete current-original pass.
4. The same `PhaseProviderLedger.verify` then calls `self.original.verify_originals()` at line 238.  That invokes `_TrainProvider.inspect` again (`train_provider.py:457`): a second complete current-original pass.
5. Back in `bind_events_with_calls`, line 259 calls `FrozenTrainProviderLedgerV2.bind_events`.  Its `_bind_events` calls `verify_originals` again (`train_provider.py:483`), producing a third complete current-original pass before event matching.

All three passes reread the current state, native ledger and every saved call.  For a succeeded headless row, `_TrainProvider.inspect` calls `train_provider_headless.observation` (`train_provider_headless.py:79`), which hashes the complete retained native directory (lines 52-61) and invokes `_replay_headless_native_call` (line 99).  The latter re-reads the request, reservation, process streams, account snapshots and frozen sources.  Thus the repeat is genuine I/O and validation work, not only `FrozenRecord` reconstruction.  `FrozenRecord`'s bounded LRU cache in `contracts.py:17` covers large canonical digest calculation only; it does not cache any file read or validation result.

The direct profile supports the cost shape: 136 calls had 7,218 `read_bytes`, 22,440 `lstat`/symlink-or-junction checks, and 0.532 cumulative seconds in `_sources`.  These are overlapping profile values and must not be summed.  Applying its 1.619-second direct replay time to phase entries would be an extrapolation, so this audit only establishes the structural count.

Other public paths can intentionally cause separate fresh passes.  For example callers in `full_loo_native_provider.py:132` and `joint_train_controller.py:126` use `calls_for_scope` for slot-order checks and later invoke stage verification, which binds runtime events.  Those are separate validation operations and should not be joined by a cache.  `ordinary_provider.final_provider_gate` also has several fresh accounting/sealing barriers; it is outside the single event-binding seam reviewed here.

## One bounded repair worth considering

Only fuse the *third* pass inside `PhaseProviderLedger.bind_events_with_calls`:

* Keep `calls_for_scope`, including its `self.verify()` call, unchanged.  Its two passes preserve the existing phase-scope and sealed-original checks.
* Add a private, non-public `FrozenTrainProviderLedgerV2` helper that performs the current event-to-call matching only after it is given the already-fresh `verify_originals()` result from the immediately preceding `PhaseProviderLedger.verify`.
* Have `bind_events_with_calls` use that helper rather than calling public `original.bind_events`, which otherwise repeats `verify_originals`.

This changes one invocation from three current-original passes to two.  It creates no reusable token, stores no result, and leaves public `FrozenTrainProviderLedgerV2.bind_events` unchanged: every independent consumer invocation still starts with `PhaseProviderLedger.verify`, rereads the actual originals, and rejects drift before matching events.  Do not attempt to cache `calls`, source hashes, `FrozenRecord.data`, directory walks, or account projections across consumer invocations.

The potentially smaller `train_provider_headless.observation` improvement (defer `observed_usage` for a succeeded row until after `_replay_headless_native_call`) avoids one stream parse, but it does not address the full-ledger replay multiplication above.  It is not recommended in the same change.

## Required regression checks if implemented

1. With a real synthetic native provider and two saved calls, instrument `_verify_call`: one `PhaseProviderLedger.bind_events_with_calls` must retain correct ordered IDs/views and run exactly two complete original passes; a second invocation must run two new passes.  This asserts no cross-consumer reuse.
2. After a successful first binding, alter one persisted original response or prompt and invoke `bind_events_with_calls` again.  It must reject and poison/close the provider before event consumption.  This proves the next consumer rereads originals rather than accepting the earlier pass.
3. Preserve existing malformed-event and failed/unknown usage tests: an empty/mismatched event sequence must still fail, while historical noneligible binding with `require_eligible=False` retains its existing lower-bound behavior.

No code change is recommended until those checks are added with the narrow private-helper refactor.  A broader fusion of `PhaseProviderSession.verify` and `FrozenTrainProviderLedgerV2.verify_originals` would eliminate another pass but mixes scope-journal and original-seal authority, so this audit does not recommend it without a separate proof design.
