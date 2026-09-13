# Private diagnostic model ports

This adapter serves only the frozen four-TRAIN diagnostic pilot. It cannot issue
a CalibrationReceipt, validation eligibility, or a benchmark RuntimeReceipt.
The existing standard reference resolver and primary rubric remain unchanged.

Before any transport I/O, a blinded reviewer/arbitrator request must match the
manifest, slot, identity, handle, candidate and reference pins. The standard
resolver supplies only the corresponding task/reference inside the private
worker. The provider sees task, reference and anonymous candidate plus frozen
instructions; no expected target, category, other review or evaluator output.

The HTTP contract is an explicit, narrow chat-completions JSON contract. Provider
model, schema, context, tokenizer bound and tariff evidence must be frozen. The
wire request must carry its actual completion-token cap. Capacity measures that
exact serialized request, including its instructions. Every HTTP opportunity
requires an fsynced reservation before I/O; raw responses, partial response bytes,
failures and independently bound usage receipts remain private. Unknown billing,
source drift, reused provider usage and bound violations close further I/O.

Local HTTP fixtures must exercise actual serialization, cap fields, resolver
bindings, partial timeouts, errors, reused usage and the full 36-slot/72-judge
pilot. Fixture success proves adapter wiring only. A reviewed production
deployment still needs real API/capacity/tokenizer/tariff evidence; merely setting
a boolean or returning a signed capacity assertion is insufficient. No real
answers, models, network endpoints, split or hold are used in this implementation
task; localhost fixtures are the only transport execution.
