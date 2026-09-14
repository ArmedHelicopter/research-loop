# Ordinary native TRAIN provider envelopes

The new ordinary controller envelopes freeze the actual
`GrokTrainProvider.configuration()` record in `provider`. They do not carry the
legacy top-level `model`, `effort`, `max_calls`, `max_tokens`, or `schemas` fields.
The old schema versions retain their Codex contracts. M4/M5 v4, build/phase
controllers, and C4 are outside this ordinary route change.

`train_provider_preflight.NATIVE_SCHEMAS` explicitly names each new envelope.
`validate_native_declaration` checks the frozen schema/allocation and native
policy. `native_provider_preflight` additionally requires the closed independent
Grok wrapper, exact live descriptor equality, and a fresh healthy allocation.
It therefore reaches the core's original source/config/default-entry checks.
Neither shape validation nor a callable assertion authorizes a provider call.

Every declared ordinary slot has a complete prompt bound of 262144 bytes.
`analysis_program` and Q3.2 `program_1` through `program_3` request 8192 output
tokens; other slots request 2048. The cumulative observed MAIN token stop cap is
131072. Schema and request-envelope byte bounds remain separately unset, rather
than acquiring the prompt bound. Native lifetime is 60 seconds, retry count zero,
and billing is included-only with API-key routing prohibited. Each MAIN has one
possible initial TITLE opportunity; TITLE/all-call tokens and additional-charge
settlement remain unknown.

`scorer_process_preflight` checks the registered family serializer, independent
authority keys, and the existing process configuration handshake. Lineage uses
the complete typed four-panel process pool with its frozen reference binding.
Controller-specific compiled-panel equality and signed receipt verification
remain required at the caller. Provider scopes and original seals must bind each
runtime's ordered request/response events before scoring.

This first seam does not itself change controller admission or demonstrate all
73 ordinary obligations. Subsequent versioned consumers must retain all planned
cells after a failed or unknown MAIN call. Synthetic integration results are
engineering evidence only. C5 selection/calibration and validation lifecycle
limitations remain open; no validation or real model run is authorized here.
