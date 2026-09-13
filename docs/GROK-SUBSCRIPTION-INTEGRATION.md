# Grok TRAIN and diagnostic integration seams

Read-only integration review at root source `72e48ff`. This is a prospective
implementation boundary, not a deployment or experiment receipt.

The user permits the existing Grok CLI grok-4.6 and no additional API fees.
The four TRAIN tasks, nine diagnostic material kinds, 36 material slots,
up to 108 blind-review/arbitration and 72 evaluator opportunities remain fixed.
Validation stays acceptance-only. Actual diagnostic materials are not yet
prepared; low-level transport does not establish scorer qualification.

## Explicit subscription accounting

The historical `four-train-diagnostic-calibration-v1` requires reliable token
and monetary capacity quotes and exact reported cost. Reusing it by supplying
a fabricated free tariff, positive dummy monetary budget or dummy tokenizer
would violate its contract. A new version must represent included subscription
usage directly and preserve the original HTTP validator and budget behavior.

Each model opportunity must reserve one main prompt and one possible initial
title opportunity, with the same grok-4.6 model selection. Main and title output
caps, input byte cap, wall-time bound, executable/config/source pins, exact
schema and request digests are frozen before dispatch. This describes request
limits; it does not assert an exact tokenization bound for an unknown tokenizer.
The native transport owns fresh billing/topup and empty-tool checks in the
same session. A prior account snapshot cannot replace this check.

Main usage, server accounting and title usage require separate fields. Missing
title usage is expected unknown, never zero and never added to the main count
as a measured token number. No extra fee is an account-routing constraint, not
a measured zero-dollar model tariff. Unknown main dispatch/usage, violated
caps, reused receipt identity or changed source must halt subsequent I/O.
A known main response with unreported title usage may be usable only under the
explicit new opportunity-bound subscription contract. It is incompatible with
the old exact-total-cost contract.

## Diagnostic integration first

`PrivateRequestRenderer` already binds complete standard TRAIN references,
anonymous candidates and benchmark rubric prompts. Keep that logic and the
private worker custody. Do not truncate BLADE references to fit a guessed cap.
Independent reviewer sessions get no expected target, other review or judge
output. Freeze every review decision before the first evaluator request.

A versioned subscription budget must preserve all 36 slot denominators and
72 evaluator opportunities, including unavailable, failed, unknown and unused.
Separate reviewer/arbitration/evaluator counters from potential title requests.
Keep the diagnostic result ineligible for formal calibration and validation.
Real subprocess fixture coverage must exercise the renderer, reservation,
native-shaped accounting and diagnostic result; a transport-only test is not
an integration test. An actual small diagnostic must follow a successfully
closed corrected transport smoke and separately frozen complete materials.

## Solver integration remains a different seam

`CodexModelPort`, `_reviewed_model_policy`, the combination preflight, family
model validators and terminal replay are Codex-specific. Several family
configurations explicitly require gpt-5.6-luna/low. A Grok class must not inherit
that type merely to bypass admission, translate native events into claimed
Codex receipts or relabel the model. Introduce an explicit provider contract
and native replay adapter, then version or narrowly extend each registered
configuration. Preserve old frozen recipes and original result identities.

Subscription token totals cannot be written into the existing exact-total
ledger while hiding title uncertainty. Downstream contrast/cost reports need
the new accounting semantics. The first solver integration check should cover
one complete primary TRAIN panel with actual Docker and independent scoring,
plus a native unknown-main outcome that prevents later reserved calls. Only
then should more controllers opt into the provider contract.
