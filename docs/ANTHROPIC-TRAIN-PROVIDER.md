# Messages TRAIN provider

`AnthropicMessagesTrainModelPort` in `research_loop.modular.anthropic_train_provider`
is wrapped by the exact `AnthropicTrainProvider`, using existing
`PhaseProviderSession` scopes and original-ledger seals. Singleton controller
configuration must use `train-panel-controller-v3`. Older Grok envelopes do not
admit this provider. TRAIN identity is required before any HTTP reservation.

Constructor parameters: `work_root`, exact `endpoint`, exact requested `model`,
explicit `response_models` aliases, private `credential_file`, `schemas`,
`max_calls`, `slot_output_caps`, `slot_input_byte_caps`,
`observed_main_token_cap`, `timeout_seconds` (1–600), `max_response_bytes`.
The private credential JSON has `base_url` and `token`; only the dispatch code
loads it. Bearer authentication is never written to configuration or journals.
HTTPS is required except literal 127.0.0.1 for the synthetic HTTP fixture.

Each request uses the Messages protocol, version 2023-06-01, temperature zero,
no streaming or tools, and requests disabled thinking. The provider may still
return thinking: original bytes stay private, while only text blocks are joined
and parsed as strict schema-valid JSON. A successful response requires the exact
frozen response model, `end_turn`, HTTP 200 and bounded known usage. Four reported
token counters are retained separately; their sum is an observed token count,
not a price or settlement assertion. No retries or alternative routes exist.

Every attempt first persists a reservation, then immutable request and response
originals and an append-only completion event. Errors preserve observed usage
and any received bytes, stop future I/O, and cannot produce a successful score
or turn an incomplete panel into a complete one. Source hashes bind the provider,
phase and controller code. Seals re-read original bytes and the full event journal.

`tests/test_anthropic_train_provider.py` uses a real local HTTP server and the
existing complete Q3.1 consumer: both synthetic benchmarks, all twelve cells,
48 producer calls, constrained Docker, an independent synthetic native scorer
process and signed complete closure. This is engineering evidence, not measured
model performance. Actual API experiments require a separately frozen model,
budget and dataset series, and must not be pooled with Grok results.
