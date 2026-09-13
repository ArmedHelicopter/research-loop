# Frozen evaluator model port

`CodexEvaluatorModelPort` is the provider-facing transport for
`frozen-independent-evaluator-call-v1`. It accepts only the rubric endpoint's
private evaluator request, verifies the exact benchmark output schema, rubric
contract digest, prompt digest, and frozen prompt template, then uses the same
reviewed-context/no-tools reservation path as `CodexModelPort`.

The evaluator ledger is separately pinned with purpose and request-contract
fields. Existing solver `CodexModelPort` ledgers retain their original config
shape and can still reopen unchanged. The returned `FrozenRecord` is the raw
benchmark-schema JSON expected by `FrozenBenchmarkRubricEndpoint`; it is not a
scientific-validity assertion.
