# Independent Messages evaluator

The exact provider kind is `anthropic-messages-independent-evaluator-v1`, backed
by `MessagesEvaluatorModelPort` in `evaluation.modular.messages_evaluator`.
It accepts only `frozen-independent-evaluator-call-v1`, verifies the frozen rubric,
canonical anonymous prompt and schema, and owns a separate private allocation.
It does not wrap the public TRAIN port or claim any Grok identity. The existing
TRAIN reference resolver remains mandatory in `scorer_process.build_service`.

Use this exact `evaluator` specification in the frozen scorer-process config:

```python
{
    'provider_kind': 'anthropic-messages-independent-evaluator-v1',
    'endpoint': 'https://api.icompify.com/anthropic/v1/messages',
    'model': 'deepseek-v4-pro',
    'response_models': ['deepseek-v4-pro'],
    'credential_file': '<absolute private credential file>',
    'work_root': '<new absolute private evaluator ledger directory>',
    'evaluator_id': '<exact ScorerConfig evaluator_id>',
    'evaluator_version': '<exact ScorerConfig version>',
    'max_calls': '<frozen integer>',
    'max_tokens': '<frozen integer total budget>',
    'output_cap': 4096,
    'input_byte_cap': 262144,
    'observed_token_cap': 131072,
    'timeout_seconds': 120,
    'max_response_bytes': 2097152,
}
```

The credential JSON uses `base_url` and `token`, with `base_url` equal to the
endpoint or its prefix before `/v1/messages`. Only dispatch reads credentials.
No auth value is written to model configuration, request originals, or journals.
Each call reserves the full observed-token ceiling against the remaining budget
before dispatch. No retry or fallback exists. Unknown, truncated and failed
attempts preserve raw bytes and observed usage and permanently stop allocation.
Thinking is requested disabled; returned thinking stays in private raw originals,
while only text blocks form the schema-validated output. Reported tokens are not
settled costs. References never cross into producer requests or public receipts.

`scorer_process.messages_evaluator_descriptor(spec)` computes the exact immutable
binding without reading credentials or creating a ledger. Pass that descriptor
to `LinkedScorerProcessClient(evaluator_provider=..., ...)` with the normal complete
panel/config/handle/authority bindings. Run the production worker by importing
`scorer_process.main` and calling it after module initialization. Finalize through
`client.finalize_messages_evaluator(receipts=...)`.

The existing stdio finalization wire is reused for compatibility, but the signed
payload has schema `messages-independent-evaluator-closure-v1`, distinct provider
identity, four API token counters and its own verifier. Its scope lists every
planned cell and unscored count; partial completion does not establish whole-panel
acceptance. Finalization independently replays private HTTP originals and binds
them to ordered signed score receipts and the worker journal.

The bounded tests score one synthetic cell from each benchmark in an actual
independent process over local HTTP, then reconstruct the service and replay
originals without new requests. They preserve the original twelve-cell denominator
(two scored, ten unscored), reject raw tampering and unknown/truncated failures,
and verify private-label/credential boundaries. Prior full Q3.1 Docker evidence
is separate; these tests make no actual API, calibration, VAL or scientific claim.
