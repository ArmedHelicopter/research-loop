# Grok normal-headless TRAIN deployments

`GrokHeadlessTrainModelPort` keeps the historical 1.0.13 normal-CLI contract
when `deployment` is omitted. Existing ledger configurations therefore retain
their original fields and are not silently upgraded.

The only opt-in alternate is
`FrozenHeadlessTrainDeployment.create(executable)`. It admits one pinned 1.0.30
binary (`ca24…5266`), the `grok-4.6` model, normal streaming-JSON command
contract, empty inspect inventory contract, and the `1.0.30` account client
header. The descriptor, digest, executable bytes, and its source pins are
frozen into the provider configuration and every call context. Account request
records preserve the versioned header metadata, and replay requires it.

The explicit record is also admitted by the private frozen-rubric evaluator
factory. That evaluator writes the same descriptor and digest into its own
configuration and per-call context, then rechecks them when replaying original
native evidence. It does not admit the record to ACP or alter legacy evaluator
declarations.

Neither path relaxes account/login checks, authorizes API-key billing, settles
title or all-opportunity usage, or establishes a model result. Any failed or
uncertain opportunity remains terminal with unknown completeness.
