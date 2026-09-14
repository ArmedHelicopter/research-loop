# Public TRAIN provider core v1

`train_provider.py` is an explicit adapter layer. It does not admit any controller, change `_safe_call`, replace `FrozenProviderLedger`, or reinterpret legacy Codex/Grok records. Downstream controllers need their own versioned provider envelopes and integration checks.

Only exact `CodexModelPort` and exact `GrokTrainModelPort` are admitted by `wrap_train_provider`. The wrappers are `CodexTrainProvider` and `GrokTrainProvider`; `TrainProvider` is their closed union. Grok remains independent and requires the default `run_native_train` entry. Codex requires its original reviewed context policy. No arbitrary callable or provider subclass is evidence.

- `configuration() -> FrozenRecord`: derived `public-train-provider-config-v1`, original native configuration/digest, adapter source hashes, model, limits and accounting scope.
- `call(FrozenRecord) -> FrozenRecord` (also callable): inspect originals before dispatch, invoke the actual port once, inspect original call evidence before returning output. A failure durably closes the wrapper and the existing native ledger flag.
- `inspect() -> tuple[FrozenRecord, ...]`, `calls_since(cursor=0)`: original call views, including failed attempts. Never invoke a model or a Codex context probe. A detected provenance fault is durably recorded and dispatch closes.
- `usage() -> FrozenRecord`: observed opportunity count and known reported MAIN tokens, unknown MAIN opportunities, possible initial TITLE opportunities, terminal state. TITLE, all-opportunity totals and settled additional charges remain unknown, including when MAIN is known.
- `terminal() -> bool`: inspect the session and return whether it has stopped. Corrupt originals raise `ContractError`; they are not a false or healthy result.
- `seal(path, prefix=None) -> FrozenTrainProviderLedgerV2`: create an exclusive immutable `frozen-train-provider-ledger-v2` snapshot. A prefix is a call count, not the live mutable ledger hash.
- `seal.verify_originals() -> FrozenRecord`: checks sealed bytes and original prefix evidence after legitimate appends. `successful_prefix` remains true after a later failed target. `score_eligible` is false whenever the current provider is terminal, the sealed prefix contains failed/unknown calls, the prefix is empty, or it was sealed after a terminal state.
- `seal.bind_events(events, require_eligible=True) -> tuple[int, ...]`: ordered native call identifiers for runtime requests and exact responses. Repeated identical requests are represented as separate ordered opportunities. `require_eligible=False` is for historical audit only; it does not return scientific eligibility.

`originals_verified=False` means failed evidence is only captured and hash-checked, not verified as a successful request/response. Such a view has no response digest. Valid scalar usage parsed directly from original streams remains visible but is marked incomplete. The original failed ledger and raw streams remain inspectable. Sidecar state and original native ledger bytes are preserved before a terminal flag is written.

Grok input limits bound the full prompt text; schema bytes and the larger request envelope are separate observed sizes, with no invented upper-bound claim. Output caps are requested caps; observed MAIN token caps remain a different field. Legacy Codex's text-mode prompt hash is replayed using its historical newline semantics while the v2 seal separately hashes exact original file bytes.

The seal is an in-process typed evidence object bound to a live original session. It is not an offline archive reader or a signature against a malicious process able to rewrite Python objects. No controller is enabled by constructing it. Existing immutable artifacts keep their old schema meanings. This engineering layer does not perform generation, selection, validation, or scientific scoring; C5's remaining selection/calibration/validation limitation stays open.
