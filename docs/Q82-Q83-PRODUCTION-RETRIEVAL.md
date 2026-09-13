# Q8.2 / Q8.3 caller-bound retrieval contract

This delivery implements the Q8.2 and Q8.3 production compiler, registry,
controller, and runtime seams. Q8.1 and Q8.4–Q8.7 remain outside this production
driver registration. It does not close the 48-question programme, modify its
success thresholds, prune combinations after a null result, or run validation.

## Behavior and frozen comparison

The caller freezes a `typed-retrieval-panel-bundle-v2` against the actual train
task identity, public payload, query, and all six material variants. Q8.2 supplies
correction, runnable-method/resource, and question-reframing documents. Its M6
off arm receives no external source context and explicitly records its unused
retrieval allowance. Q8.2 measures source-to-request context changes here;
dependency fulfillment and method execution are not measured by this driver.

Q8.3 shares exactly one frozen source pool across support-only, neutral, and
three-lane variants. The public question remains unchanged. M6 on allocates
support-only calls to the support lane, neutral calls cyclically across all
three lanes with a position-neutral query, and three-lane calls cyclically with
an explicit support/counterevidence/method query. M6 off uses the same ordinary
neutral policy for all three variants. Empty lanes and unused source slots are
valid observations and stay in the denominator.

Every strategy uses the same **total** `provider_calls`, `source_cap`, and
`context_bytes`. Source slots are divided over call opportunities before I/O;
the cap is not multiplied by the number of lanes. `context_bytes` bounds the
UTF-8 canonical serialization of the complete retrieval projection, including
source IDs, root IDs, provenance digests, and qualification metadata. Whole
documents that do not fit are excluded and recorded outside the model context.
The surrounding fixed task/instruction/opaque-cell envelope and the model output
budget are separate, identical controller controls. Equal byte caps are not a
claim that realized tokenizer counts or provider costs are identical.

## Source and budget safety

Both a caller-owned provider and a caller-owned admission callable are required
before export. The callable receives the typed task and exact source pool; its
strict `public-train-retrieval-admission-v1` receipt must bind identity, task
digest, pool digest, `public_train_safe=true`, and `scientific_verified=false`.
This is a caller trust boundary for public/train eligibility, not a self-issued
scientific validation. Text keywords cannot create eligibility. The admission
receipt is recorded before provider or model I/O.

`RecordedRetrievalProvider` reserves each call and its complete source allowance
before invoking the caller, records each yielded item, and probes at most
`source_limit + 1` items. Foreign, altered, mislabelled, and excessive returns
fail closed. Partial failures retain prior items, reservations, reported cost,
and explicitly unknown verified external cost. Counting a provider invocation
does not establish how many external requests an arbitrary provider made.

Returned documents must exactly match the frozen pool. Root de-duplication is
structural across the selected context; root diversity does not establish
scientific independence. Retrieved text cannot change the objective. Public
source IDs are not evidence-ledger IDs and do not pass P0 scientific admission.
P0 remains fixed, including when M6 is off.

## Verification and limits

The frozen controller grid is 2 questions × 2 primary benchmark adapters ×
3 variants × 2 M6 states = **24 cells**. It uses actual custody inventory/split,
train packet export, production compiler/registry/controller, real
`CodexModelPort` with only its process transport/context probe replaced by public
fixtures, caller provider/admission, runtime journals, and an independent fixture
authority reading the actual immutable requests and responses. The authority
checks all cell bindings, source membership, query/lane behavior, context
changes, P0 control, and total budget accounting. No registry or compiler is
patched to make the grid execute.

The fixture transport deterministically reports the source text that actually
reached its request. That proves causal request/response plumbing, not reasoning
improvement, scientific correction, meaningful confirmation-bias reduction,
method executability, parameter learning, or benchmark score gains. The provider
fixture deliberately misses counterevidence for a generic query, and this
controlled fixture behavior is not empirical evidence about a search service.
Scientific status remains `not_measured`; model evidence lists remain empty.
No paid model calls, live network retrieval, reference payloads, or real
validation data are used.

The retained safety02 RED includes a P0 refusal when the transport incorrectly
reported public source IDs as scientific evidence, plus two obsolete fixture-only
compiler expectations. Repair retains P0 and changes the transport to report
context only. The older `m6-causal-baseline.xml` is an unfrozen draft RED after
initial repairs, not a pristine source baseline; the older draft GREEN (13 tests
in its XML, previously described as 14) is also
not frozen delivery evidence. Their files and hashes remain in the evidence
record. Final source commit and JUnit/trace hashes are recorded alongside the
frozen verification artifacts.
