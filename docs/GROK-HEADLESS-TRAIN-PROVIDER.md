# Headless Grok TRAIN provider and artifact provenance

The headless CLI route has its own `GrokHeadlessTrainModelPort` and
`GrokHeadlessTrainProvider`, identified as `grok-headless-public-train-v1`.
It reuses the independently readable headless acquisition transport. It does
not relabel headless observations as ACP receipts, and existing ACP declarations
keep their original meaning.

Each request reserves one MAIN opportunity before native execution. A fresh
private context contains an opaque copy of the authorized login, with paid API
fallback disabled, low reasoning, a 60 second lifetime and no MAIN retry.
An explicit account-read policy permits two complete observation attempts for
the already defined transient account-query failures. This never retries MAIN.
Constructor and dispatch share an exclusive allocation lock. A stale second
allocator cannot replace the existing ledger or spend a second opportunity.

The immutable constructor configuration binds the source files, executable,
model, limits, schema, account-read policy and context roots. Every call stores
canonical public request bytes, the actual private prompt/schema, native
reservation, process and account observations, raw stream, response and
independently reconstructed binding. Successful reads verify those originals
again before later calls and before returning a result. Opaque login material
is neither copied into public artifacts nor hashed in the provider inventory.

The shared provider seals original call prefixes and binds them to actual
`model_request` and `model_response` events. Phase scopes bind call IDs to a
particular module or combination cell. An earlier history prefix remains
verifiable after target calls append; a response consumed under another
request or scope is rejected. These are execution and consumption claims,
not proof that the model's answer is scientifically correct.

Rejected, malformed and unknown-usage calls remain in the denominator. Known
MAIN usage is reported separately from unknown title usage and all-call
settlement. A rejected postflight check may leave a native raw response file;
the file is retained as unconsumed evidence. No successful response or eligible
seal is synthesized from it. Raw accounting faults close subsequent dispatch.

The M4/M5 route explicitly selects
`m4-m5-train-controller-config-v5`. It retains the four arms, two TRAIN tasks,
five model slots per cell, 40 MAIN opportunities and eight scorer opportunities.
The v5 declaration binds the headless kind, low reasoning and account-read
policy. The original v4 ACP declaration remains unchanged. Post-score and final
original replay still gate contrast eligibility; a late provenance fault keeps
historical scorer returns while refusing an eligible contrast.

Engineering checks use local synthetic child processes and synthetic HTTP
observations through the actual producer, port, reader and provider. Controller
checks additionally use real restricted Docker execution and an independent
scorer process. They do not measure the effectiveness of actual Grok on the
official benchmark data. No VAL data or paid API is needed for these checks.

The full experiment registry, TRAIN-only optimization, VAL-only acceptance,
singleton/pair/triple/full/LOO obligations and negative-result retention remain
unchanged. This provider implementation alone does not complete those effects
experiments or authorize a validation lease.

The phase event-binding consumer now performs two complete original audits
within one synchronous invocation instead of three. It reuses only that
invocation's verified immutable observations for event matching; the next
consumer and the public original-ledger entry still reread current files.
Invalid arguments retain each entry's existing validation/poison order.
The [102-check frozen integration](../results/modular-engineering-20260915/headless-binding-replay-r1/README.md)
includes legacy providers, tampering between consumers, terminal accounting
and label isolation. This establishes the reduced pass count, not a measured
end-to-end speedup. The separate [closed-original profile](../results/modular-engineering-20260915/headless-verification-profile-r1/INTEGRATION.md)
retains its initial rejection, additive correction and subsequent replay.
